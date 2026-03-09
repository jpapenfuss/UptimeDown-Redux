"""HTTP receiver server for UptimeDown metrics ingestion."""

import json
import time
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

MAX_BODY_BYTES = 10 * 1024 * 1024

logger = logging.getLogger("receiver")


class IngestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the receiver."""

    def log_message(self, format, *args):
        """Override to use Python logging instead of stderr."""
        logger.info("%s - %s", self.client_address[0], format % args)

    def _send_json(self, status_code, body_dict):
        """Send a JSON response with proper headers."""
        payload = json.dumps(body_dict).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _route(self, method):
        """
        Central routing logic. Returns (handler_name, error_code).
        - handler_name: "health" or "ingest" if route matches and method is allowed
        - error_code: 405 for wrong method on known path, 404 for unknown path
        - (None, None): handler not found but no error (shouldn't happen)
        """
        if self.path == "/health":
            if method == "GET":
                return ("health", None)
            return (None, 405)
        if self.path == "/ingest":
            if method == "POST":
                return ("ingest", None)
            return (None, 405)
        return (None, 404)

    def do_GET(self):
        """Handle GET requests."""
        remote_ip = self.client_address[0]
        start = time.monotonic()
        route, err = self._route("GET")

        if err:
            error_msg = "method not allowed" if err == 405 else "not found"
            self._send_json(err, {"error": error_msg})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s %d Content-Length=%s elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                err,
                self.headers.get("Content-Length", "0"),
                elapsed_ms,
            )
            return

        # route == "health"
        self._send_json(200, {"status": "ok"})
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "%s %s %s 200 Content-Length=%s elapsed=%dms",
            remote_ip,
            self.command,
            self.path,
            self.headers.get("Content-Length", "0"),
            elapsed_ms,
        )

    def do_POST(self):
        """Handle POST requests."""
        remote_ip = self.client_address[0]
        start = time.monotonic()
        route, err = self._route("POST")

        if err:
            error_msg = "method not allowed" if err == 405 else "not found"
            self._send_json(err, {"error": error_msg})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s %d Content-Length=%s elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                err,
                self.headers.get("Content-Length", "0"),
                elapsed_ms,
            )
            return

        # route == "ingest"
        # Check Content-Type
        content_type = self.headers.get("Content-Type", "")
        if content_type != "application/json":
            self._send_json(415, {"error": "unsupported media type"})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s 415 Content-Length=%s elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                self.headers.get("Content-Length", "0"),
                elapsed_ms,
            )
            return

        # Check Content-Length header exists
        content_length_str = self.headers.get("Content-Length")
        if content_length_str is None:
            self._send_json(411, {"error": "length required"})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s 411 Content-Length=None elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                elapsed_ms,
            )
            return

        # Check Content-Length value
        try:
            content_length = int(content_length_str)
        except ValueError:
            self._send_json(400, {"error": "invalid content-length"})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s 400 Content-Length=%s elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                content_length_str,
                elapsed_ms,
            )
            return

        if content_length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "payload too large"})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s 413 Content-Length=%d elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                content_length,
                elapsed_ms,
            )
            return

        # Read body
        try:
            body_bytes = self.rfile.read(content_length)
        except Exception as e:
            logger.error("Error reading request body: %s", e)
            self._send_json(400, {"error": "failed to read body"})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s 400 Content-Length=%d elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                content_length,
                elapsed_ms,
            )
            return

        # Parse JSON
        try:
            json.loads(body_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "invalid JSON"})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s 400 Content-Length=%d elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                content_length,
                elapsed_ms,
            )
            return

        # Success
        self._send_json(202, {"status": "accepted"})
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "%s %s %s 202 Content-Length=%d elapsed=%dms",
            remote_ip,
            self.command,
            self.path,
            content_length,
            elapsed_ms,
        )

    def do_PUT(self):
        """Handle PUT requests."""
        remote_ip = self.client_address[0]
        start = time.monotonic()
        route, err = self._route("PUT")

        if err:
            error_msg = "method not allowed" if err == 405 else "not found"
            self._send_json(err, {"error": error_msg})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s %d Content-Length=%s elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                err,
                self.headers.get("Content-Length", "0"),
                elapsed_ms,
            )
            return

    def do_DELETE(self):
        """Handle DELETE requests."""
        remote_ip = self.client_address[0]
        start = time.monotonic()
        route, err = self._route("DELETE")

        if err:
            error_msg = "method not allowed" if err == 405 else "not found"
            self._send_json(err, {"error": error_msg})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s %d Content-Length=%s elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                err,
                self.headers.get("Content-Length", "0"),
                elapsed_ms,
            )
            return

    def do_PATCH(self):
        """Handle PATCH requests."""
        remote_ip = self.client_address[0]
        start = time.monotonic()
        route, err = self._route("PATCH")

        if err:
            error_msg = "method not allowed" if err == 405 else "not found"
            self._send_json(err, {"error": error_msg})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "%s %s %s %d Content-Length=%s elapsed=%dms",
                remote_ip,
                self.command,
                self.path,
                err,
                self.headers.get("Content-Length", "0"),
                elapsed_ms,
            )
            return


def main():
    """Start the HTTP receiver server."""
    port = int(os.environ.get("RECEIVER_PORT", "8443"))
    server = HTTPServer(("0.0.0.0", port), IngestHandler)
    logger.info("Starting receiver on port %d", port)
    server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    main()
