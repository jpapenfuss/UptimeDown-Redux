"""HTTP receiver client for UptimeDown metrics push.

Pushes collected JSON metrics to a configured receiver endpoint, with support for:
- Exponential backoff retry logic for transient failures
- FIFO cache to persist failed payloads on disk
- Automatic purge of stale cache entries (>24 hours by default)
"""
import http.client
import json
import logging
import os
import ssl
import time
from pathlib import Path

logger = logging.getLogger("monitoring")


class ReceiverClient:
    """Pushes JSON payloads to a receiver HTTP endpoint."""

    def __init__(self, system_id, config):
        """Initialize the receiver client.

        Args:
            system_id: Unique system identifier (used for cache filenames)
            config: Config object with receiver_* attributes
        """
        self.system_id = system_id
        self.url = config.receiver_url
        self.token = config.receiver_token
        self.timeout = config.receiver_timeout
        self.max_retries = config.receiver_retries
        self.use_backoff = config.receiver_retry_backoff
        self.cache_dir = config.receiver_cache_dir
        self.cache_max_age = config.receiver_cache_max_age
        self.verify_ssl = config.receiver_verify_ssl

        # Determine if push is enabled (requires both url and token)
        self.enabled = bool(self.url and self.token)

        # Parse URL to get host and path
        self.host = None
        self.path = None
        self.port = 443
        self.use_https = True

        if self.enabled:
            self._parse_url()

    def _parse_url(self):
        """Parse receiver URL into host, port, and path."""
        url = self.url
        # Remove scheme
        if url.startswith("https://"):
            self.use_https = True
            url = url[8:]
        elif url.startswith("http://"):
            self.use_https = False
            url = url[7:]
        else:
            logger.warning("Receiver URL must start with http:// or https://")
            self.enabled = False
            return

        # Split host:port from path
        if "/" in url:
            host_port, path = url.split("/", 1)
            self.path = "/" + path
        else:
            host_port = url
            self.path = "/"

        # Split host and port
        if ":" in host_port:
            self.host, port_str = host_port.rsplit(":", 1)
            try:
                self.port = int(port_str)
            except ValueError:
                logger.warning("Invalid port in receiver URL: %s", port_str)
                self.enabled = False
                return
        else:
            self.host = host_port
            self.port = 443 if self.use_https else 80

    def _send_http(self, json_bytes):
        """Send HTTP POST request with JSON payload.

        Returns:
            (success: bool, status_code: int | None)
            - success=True: 202 response
            - success=False, status_code present: non-202 response (includes 4xx)
            - success=False, status_code=None: connection error
        """
        if not self.enabled:
            return (False, None)

        try:
            if self.use_https:
                context = ssl.create_default_context()
                if not self.verify_ssl:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                conn = http.client.HTTPSConnection(
                    self.host,
                    self.port,
                    timeout=self.timeout,
                    context=context,
                )
            else:
                conn = http.client.HTTPConnection(
                    self.host, self.port, timeout=self.timeout
                )

            conn.request(
                "POST",
                self.path,
                json_bytes,
                {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.token}",
                    "Content-Length": str(len(json_bytes)),
                },
            )
            response = conn.getresponse()
            status_code = response.status
            response.read()  # consume response body
            conn.close()

            if status_code == 202:
                return (True, 202)
            else:
                return (False, status_code)

        except (
            http.client.HTTPException,
            OSError,
            TimeoutError,
        ) as e:
            logger.debug("Receiver connection error: %s", e)
            return (False, None)

    def _send_once(self, json_bytes):
        """Send HTTP request with single attempt (for cached payloads).

        Returns:
            True if successful (202), False otherwise
        """
        success, _ = self._send_http(json_bytes)
        return success

    def push(self, json_string):
        """Push a new JSON payload with retry logic and exponential backoff.

        On failure, caches the payload if cache_dir is configured.

        Args:
            json_string: JSON string to push

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False

        json_bytes = json_string.encode("utf-8")

        for attempt in range(self.max_retries + 1):
            success, status_code = self._send_http(json_bytes)

            if success:
                logger.info("Receiver push succeeded (attempt %d)", attempt + 1)
                return True

            # Don't retry on 4xx client errors (data is invalid)
            if status_code is not None and 400 <= status_code < 500:
                logger.error(
                    "Receiver push failed with %d (client error, not retrying)",
                    status_code,
                )
                return False

            # Retry on 5xx or connection errors
            if attempt < self.max_retries:
                if self.use_backoff:
                    delay = 2 ** attempt
                else:
                    delay = 1
                logger.warning(
                    "Receiver push failed (attempt %d/%d), retrying in %d seconds",
                    attempt + 1,
                    self.max_retries + 1,
                    delay,
                )
                time.sleep(delay)

        # All retries exhausted — cache if enabled
        if self.cache_dir:
            self._cache_payload(json_bytes)
        else:
            logger.error("Receiver push failed after %d retries (caching disabled)", self.max_retries + 1)

        return False

    def _cache_payload(self, json_bytes):
        """Write payload to cache directory with timestamp-based filename."""
        try:
            cache_path = Path(self.cache_dir)
            cache_path.mkdir(parents=True, exist_ok=True)

            # Filename: <system_id>-<unix_timestamp>.json
            timestamp = int(time.time())
            filename = f"{self.system_id}-{timestamp}.json"
            filepath = cache_path / filename

            filepath.write_bytes(json_bytes)
            logger.info("Cached failed payload: %s", filepath)
        except Exception as e:
            logger.error("Failed to cache payload: %s", e)

    def send_cached(self):
        """Purge old cache entries and resend cached payloads (FIFO, one attempt each)."""
        if not self.cache_dir or not self.enabled:
            return

        try:
            cache_path = Path(self.cache_dir)
            if not cache_path.is_dir():
                return

            now = time.time()
            files = sorted(cache_path.glob(f"{self.system_id}-*.json"))

            for filepath in files:
                # Check if file is too old (older than cache_max_age)
                mtime = filepath.stat().st_mtime
                age = now - mtime
                if age > self.cache_max_age:
                    filepath.unlink()
                    logger.info("Purged stale cache entry: %s", filepath)
                    continue

                # Try to send once
                try:
                    json_bytes = filepath.read_bytes()
                    if self._send_once(json_bytes):
                        filepath.unlink()
                        logger.info("Sent cached payload: %s", filepath)
                    # If send failed, leave file in cache for next attempt
                except Exception as e:
                    logger.warning("Error resending cached payload %s: %s", filepath, e)

        except Exception as e:
            logger.error("Error processing cache directory: %s", e)
