"""Tests for the receiver push client."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

# Support both execution modes
try:
    from monitoring.push import ReceiverClient
    from monitoring.config import Config
except ImportError:
    from push import ReceiverClient
    from config import Config


class MockConfig:
    """Mock config object for testing."""

    def __init__(
        self,
        receiver_url=None,
        receiver_token=None,
        receiver_timeout=10,
        receiver_retries=3,
        receiver_retry_backoff=True,
        receiver_cache_dir=None,
        receiver_cache_max_age=86400,
        receiver_verify_ssl=True,
    ):
        self.receiver_url = receiver_url
        self.receiver_token = receiver_token
        self.receiver_timeout = receiver_timeout
        self.receiver_retries = receiver_retries
        self.receiver_retry_backoff = receiver_retry_backoff
        self.receiver_cache_dir = receiver_cache_dir
        self.receiver_cache_max_age = receiver_cache_max_age
        self.receiver_verify_ssl = receiver_verify_ssl


class TestReceiverClientInit(unittest.TestCase):
    """Test ReceiverClient initialization and URL parsing."""

    def test_disabled_without_url(self):
        """Client should be disabled if URL is missing."""
        cfg = MockConfig(receiver_token="token123")
        client = ReceiverClient("system-1", cfg)
        self.assertFalse(client.enabled)

    def test_disabled_without_token(self):
        """Client should be disabled if token is missing."""
        cfg = MockConfig(receiver_url="https://receiver.example.com:8443/ingest")
        client = ReceiverClient("system-1", cfg)
        self.assertFalse(client.enabled)

    def test_enabled_with_url_and_token(self):
        """Client should be enabled if URL and token are present."""
        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        self.assertTrue(client.enabled)

    def test_parse_https_url(self):
        """Parse HTTPS URL correctly."""
        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        self.assertTrue(client.use_https)
        self.assertEqual(client.host, "receiver.example.com")
        self.assertEqual(client.port, 8443)
        self.assertEqual(client.path, "/ingest")

    def test_parse_http_url(self):
        """Parse HTTP URL correctly."""
        cfg = MockConfig(
            receiver_url="http://receiver.example.com:8080/api/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        self.assertFalse(client.use_https)
        self.assertEqual(client.host, "receiver.example.com")
        self.assertEqual(client.port, 8080)
        self.assertEqual(client.path, "/api/ingest")

    def test_parse_url_default_port_https(self):
        """HTTPS should default to port 443."""
        cfg = MockConfig(
            receiver_url="https://receiver.example.com/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        self.assertEqual(client.port, 443)

    def test_parse_url_default_port_http(self):
        """HTTP should default to port 80."""
        cfg = MockConfig(
            receiver_url="http://receiver.example.com/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        self.assertEqual(client.port, 80)

    def test_parse_url_default_path(self):
        """URL without path should default to /."""
        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        self.assertEqual(client.path, "/")

    def test_parse_url_invalid_port(self):
        """Invalid port should disable client."""
        cfg = MockConfig(
            receiver_url="https://receiver.example.com:notaport/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        self.assertFalse(client.enabled)

    def test_parse_url_invalid_scheme(self):
        """Invalid scheme should disable client."""
        cfg = MockConfig(
            receiver_url="ftp://receiver.example.com/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        self.assertFalse(client.enabled)


class TestSendHttp(unittest.TestCase):
    """Test _send_http method."""

    def test_disabled_client_returns_false(self):
        """Disabled client should return (False, None)."""
        cfg = MockConfig()
        client = ReceiverClient("system-1", cfg)
        success, status = client._send_http(b"test")
        self.assertFalse(success)
        self.assertIsNone(status)

    @mock.patch("http.client.HTTPSConnection")
    def test_successful_202_response(self, mock_conn_class):
        """Success on 202 response."""
        mock_response = mock.Mock()
        mock_response.status = 202
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        success, status = client._send_http(b"test payload")

        self.assertTrue(success)
        self.assertEqual(status, 202)
        mock_conn.request.assert_called_once()

    @mock.patch("http.client.HTTPSConnection")
    def test_400_response(self, mock_conn_class):
        """4xx responses should be returned as-is."""
        mock_response = mock.Mock()
        mock_response.status = 400
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        success, status = client._send_http(b"test payload")

        self.assertFalse(success)
        self.assertEqual(status, 400)

    @mock.patch("http.client.HTTPSConnection")
    def test_500_response(self, mock_conn_class):
        """5xx responses should be returned as-is."""
        mock_response = mock.Mock()
        mock_response.status = 500
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        success, status = client._send_http(b"test payload")

        self.assertFalse(success)
        self.assertEqual(status, 500)

    @mock.patch("http.client.HTTPSConnection")
    def test_connection_error(self, mock_conn_class):
        """Connection error should return (False, None)."""
        mock_conn_class.side_effect = OSError("Connection refused")

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        success, status = client._send_http(b"test payload")

        self.assertFalse(success)
        self.assertIsNone(status)


class TestSendOnce(unittest.TestCase):
    """Test _send_once method (single attempt for cached payloads)."""

    @mock.patch("http.client.HTTPSConnection")
    def test_success(self, mock_conn_class):
        """_send_once should return True on 202."""
        mock_response = mock.Mock()
        mock_response.status = 202
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        result = client._send_once(b"test payload")

        self.assertTrue(result)

    @mock.patch("http.client.HTTPSConnection")
    def test_failure(self, mock_conn_class):
        """_send_once should return False on non-202."""
        mock_response = mock.Mock()
        mock_response.status = 500
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        result = client._send_once(b"test payload")

        self.assertFalse(result)


class TestPush(unittest.TestCase):
    """Test push method (with retries)."""

    @mock.patch("http.client.HTTPSConnection")
    def test_immediate_success(self, mock_conn_class):
        """Should return True on first attempt success."""
        mock_response = mock.Mock()
        mock_response.status = 202
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
        )
        client = ReceiverClient("system-1", cfg)
        result = client.push('{"test": "data"}')

        self.assertTrue(result)

    @mock.patch("http.client.HTTPSConnection")
    def test_retry_on_5xx(self, mock_conn_class):
        """Should retry on 5xx responses."""
        responses = [
            mock.Mock(status=500, read=lambda: b""),
            mock.Mock(status=502, read=lambda: b""),
            mock.Mock(status=202, read=lambda: b""),  # Success on 3rd attempt
        ]

        mock_conn = mock.Mock()
        mock_conn.getresponse.side_effect = responses
        mock_conn_class.return_value = mock_conn

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
            receiver_retries=3,
            receiver_retry_backoff=False,  # No backoff for faster test
        )
        client = ReceiverClient("system-1", cfg)
        result = client.push('{"test": "data"}')

        self.assertTrue(result)

    @mock.patch("http.client.HTTPSConnection")
    def test_no_retry_on_4xx(self, mock_conn_class):
        """Should not retry on 4xx responses."""
        mock_response = mock.Mock()
        mock_response.status = 422
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
            receiver_retries=3,
        )
        client = ReceiverClient("system-1", cfg)
        result = client.push('{"test": "data"}')

        self.assertFalse(result)
        # Should only have called request once (no retries)
        self.assertEqual(mock_conn.request.call_count, 1)

    @mock.patch("http.client.HTTPSConnection")
    @mock.patch("time.sleep")  # Mock sleep to speed up test
    def test_exponential_backoff(self, mock_sleep, mock_conn_class):
        """Should use exponential backoff when enabled."""
        mock_response = mock.Mock()
        mock_response.status = 503  # Service unavailable
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
            receiver_retries=3,
            receiver_retry_backoff=True,
        )
        client = ReceiverClient("system-1", cfg)
        result = client.push('{"test": "data"}')

        self.assertFalse(result)
        # Should have slept with exponential backoff: 2^0=1, 2^1=2, 2^2=4
        sleep_calls = mock_sleep.call_args_list
        self.assertEqual(len(sleep_calls), 3)  # 3 retries
        self.assertEqual(sleep_calls[0][0][0], 1)
        self.assertEqual(sleep_calls[1][0][0], 2)
        self.assertEqual(sleep_calls[2][0][0], 4)

    @mock.patch("http.client.HTTPSConnection")
    def test_cache_on_failure_with_cache_dir(self, mock_conn_class):
        """Should cache payload on failure if cache_dir is configured."""
        mock_conn_class.side_effect = OSError("Connection refused")

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MockConfig(
                receiver_url="https://receiver.example.com:8443/ingest",
                receiver_token="token123",
                receiver_cache_dir=tmpdir,
            )
            client = ReceiverClient("system-1", cfg)
            result = client.push('{"test": "data"}')

            self.assertFalse(result)
            # Check that cache file was created
            cache_files = list(Path(tmpdir).glob("system-1-*.json"))
            self.assertEqual(len(cache_files), 1)

    @mock.patch("http.client.HTTPSConnection")
    def test_no_cache_on_failure_without_cache_dir(self, mock_conn_class):
        """Should not cache if cache_dir is not configured."""
        mock_conn_class.side_effect = OSError("Connection refused")

        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
            receiver_cache_dir=None,
        )
        client = ReceiverClient("system-1", cfg)
        result = client.push('{"test": "data"}')

        self.assertFalse(result)


class TestSendCached(unittest.TestCase):
    """Test send_cached method."""

    @mock.patch("http.client.HTTPSConnection")
    def test_send_cached_success(self, mock_conn_class):
        """Should delete cached file after successful send."""
        mock_response = mock.Mock()
        mock_response.status = 202
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a cached file
            cache_file = Path(tmpdir) / "system-1-1234567890.json"
            cache_file.write_text('{"test": "data"}')

            cfg = MockConfig(
                receiver_url="https://receiver.example.com:8443/ingest",
                receiver_token="token123",
                receiver_cache_dir=tmpdir,
            )
            client = ReceiverClient("system-1", cfg)
            client.send_cached()

            # File should be deleted after successful send
            self.assertFalse(cache_file.exists())

    @mock.patch("http.client.HTTPSConnection")
    def test_send_cached_failure(self, mock_conn_class):
        """Should keep cached file if send fails."""
        mock_response = mock.Mock()
        mock_response.status = 500
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a cached file
            cache_file = Path(tmpdir) / "system-1-1234567890.json"
            cache_file.write_text('{"test": "data"}')

            cfg = MockConfig(
                receiver_url="https://receiver.example.com:8443/ingest",
                receiver_token="token123",
                receiver_cache_dir=tmpdir,
            )
            client = ReceiverClient("system-1", cfg)
            client.send_cached()

            # File should still exist after failed send
            self.assertTrue(cache_file.exists())

    @mock.patch("http.client.HTTPSConnection")
    def test_purge_stale_cache(self, mock_conn_class):
        """Should purge cache entries older than cache_max_age."""
        # Mock successful response for new file, but we don't care about old file
        mock_response = mock.Mock()
        mock_response.status = 202
        mock_response.read.return_value = b""

        mock_conn = mock.Mock()
        mock_conn.getresponse.return_value = mock_response
        mock_conn_class.return_value = mock_conn

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create old and new cache files
            old_time = int(time.time()) - 100000  # Very old
            new_time = int(time.time()) - 1000  # Recent

            old_file = Path(tmpdir) / f"system-1-{old_time}.json"
            new_file = Path(tmpdir) / f"system-1-{new_time}.json"

            old_file.write_text('{"test": "old"}')
            new_file.write_text('{"test": "new"}')

            # Set cache_max_age to 86400 (24 hours)
            cfg = MockConfig(
                receiver_url="https://receiver.example.com:8443/ingest",
                receiver_token="token123",
                receiver_cache_dir=tmpdir,
                receiver_cache_max_age=86400,
            )
            client = ReceiverClient("system-1", cfg)
            client.send_cached()

            # Old file should be deleted (purged for being stale)
            self.assertFalse(old_file.exists())

    def test_send_cached_no_dir(self):
        """Should handle missing cache directory gracefully."""
        cfg = MockConfig(
            receiver_url="https://receiver.example.com:8443/ingest",
            receiver_token="token123",
            receiver_cache_dir="/nonexistent/path",
        )
        client = ReceiverClient("system-1", cfg)
        # Should not raise an exception
        client.send_cached()

    def test_send_cached_disabled_client(self):
        """Should not crash if client is disabled."""
        cfg = MockConfig(receiver_cache_dir="/tmp")
        client = ReceiverClient("system-1", cfg)
        # Should not raise an exception
        client.send_cached()


if __name__ == "__main__":
    unittest.main()
