"""Test suite for receiver HTTP server."""

import json
import http.client
import os
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer

from receiver.server import IngestHandler


TEST_PORT = 18443


class TestReceiverServer(unittest.TestCase):
    """Tests for the HTTP receiver server."""

    @classmethod
    def setUpClass(cls):
        """Start the server in a background thread with authentication tokens."""
        # Create temp token file
        cls.token_file = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt"
        )
        cls.valid_token = "x" * 50
        cls.token_file.write(f"{cls.valid_token}\n")
        cls.token_file.close()

        # Set environment variable
        os.environ["RECEIVER_TOKENS_FILE"] = cls.token_file.name

        # Initialize tokens (loads from env var)
        from receiver.server import initialize_tokens

        initialize_tokens()

        # Start server
        cls.server = HTTPServer(("127.0.0.1", TEST_PORT), IngestHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()
        time.sleep(0.1)  # Give server time to start

    @classmethod
    def tearDownClass(cls):
        """Shut down the server and clean up."""
        cls.server.shutdown()
        cls.server_thread.join(timeout=2)
        os.unlink(cls.token_file.name)
        del os.environ["RECEIVER_TOKENS_FILE"]

    def _raw_request(self, method, path, body=None, headers=None, auth_token=None):
        """
        Low-level HTTP request for testing edge cases.
        Returns (status_code, body_dict_or_None).

        Args:
            method: HTTP method
            path: Request path
            body: Request body (bytes)
            headers: Optional dict of headers
            auth_token: Optional Bearer token to add
        """
        conn = http.client.HTTPConnection("127.0.0.1", TEST_PORT)
        try:
            req_headers = headers or {}
            if auth_token:
                req_headers = {**req_headers, "Authorization": f"Bearer {auth_token}"}
            conn.request(method, path, body=body, headers=req_headers)
            resp = conn.getresponse()
            status = resp.status
            resp_body = resp.read()
            try:
                body_dict = json.loads(resp_body)
            except json.JSONDecodeError:
                body_dict = None
            return status, body_dict
        finally:
            conn.close()

    def test_01_post_ingest_valid_json(self):
        """Test: POST /ingest with valid JSON returns 202."""
        status, body = self._raw_request(
            "POST",
            "/ingest",
            body=b'{"system_id": "test"}',
            headers={
                "Content-Type": "application/json",
            },
            auth_token=self.valid_token,
        )
        self.assertEqual(status, 202)
        self.assertIsNotNone(body)
        self.assertIn("status", body)
        self.assertEqual(body["status"], "accepted")

    def test_02_post_ingest_invalid_json(self):
        """Test: POST /ingest with invalid JSON returns 400."""
        status, body = self._raw_request(
            "POST",
            "/ingest",
            body=b'{not valid json}',
            headers={
                "Content-Type": "application/json",
            },
            auth_token=self.valid_token,
        )
        self.assertEqual(status, 400)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_03_post_ingest_empty_body(self):
        """Test: POST /ingest with empty body returns 400."""
        status, body = self._raw_request(
            "POST",
            "/ingest",
            body=b"",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "0",
            },
            auth_token=self.valid_token,
        )
        self.assertEqual(status, 400)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_04_get_ingest_returns_405(self):
        """Test: GET /ingest returns 405 Method Not Allowed."""
        status, body = self._raw_request("GET", "/ingest")
        self.assertEqual(status, 405)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_05_put_ingest_returns_405(self):
        """Test: PUT /ingest returns 405 Method Not Allowed."""
        status, body = self._raw_request("PUT", "/ingest")
        self.assertEqual(status, 405)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_06_delete_ingest_returns_405(self):
        """Test: DELETE /ingest returns 405 Method Not Allowed."""
        status, body = self._raw_request("DELETE", "/ingest")
        self.assertEqual(status, 405)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_06b_put_nonexistent_returns_404(self):
        """Test: PUT /nonexistent returns 404 (not 405)."""
        status, body = self._raw_request("PUT", "/nonexistent")
        self.assertEqual(status, 404)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_06c_delete_nonexistent_returns_404(self):
        """Test: DELETE /nonexistent returns 404 (not 405)."""
        status, body = self._raw_request("DELETE", "/nonexistent")
        self.assertEqual(status, 404)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_07_post_nonexistent_returns_404(self):
        """Test: POST /nonexistent returns 404."""
        status, body = self._raw_request(
            "POST",
            "/nonexistent",
            body=b"{}",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 404)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_08_post_ingest_wrong_content_type(self):
        """Test: POST /ingest with Content-Type: text/plain returns 415."""
        status, body = self._raw_request(
            "POST",
            "/ingest",
            body=b'{"system_id": "test"}',
            headers={
                "Content-Type": "text/plain",
            },
            auth_token=self.valid_token,
        )
        self.assertEqual(status, 415)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_09_post_ingest_body_too_large(self):
        """Test: POST /ingest with Content-Length exceeding MAX_BODY_BYTES returns 413."""
        status, body = self._raw_request(
            "POST",
            "/ingest",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "999999999",
            },
            auth_token=self.valid_token,
        )
        self.assertEqual(status, 413)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_09b_post_ingest_no_content_length(self):
        """Test: POST /ingest with no Content-Length header returns 411."""
        # To avoid sending Content-Length, we need to use http.client directly
        # and not provide Content-Length
        conn = http.client.HTTPConnection("127.0.0.1", TEST_PORT)
        try:
            # Send raw request without Content-Length
            conn.putrequest("POST", "/ingest")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Authorization", f"Bearer {self.valid_token}")
            conn.endheaders()

            resp = conn.getresponse()
            status = resp.status
            body_dict = json.loads(resp.read())

            self.assertEqual(status, 411)
            self.assertIn("error", body_dict)
        finally:
            conn.close()

    def test_10_get_health_returns_200(self):
        """Test: GET /health returns 200 with status ok."""
        status, body = self._raw_request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIsNotNone(body)
        self.assertIn("status", body)
        self.assertEqual(body["status"], "ok")

    def test_10b_post_health_returns_405(self):
        """Test: POST /health returns 405 (health is GET-only)."""
        status, body = self._raw_request(
            "POST",
            "/health",
            body=b"{}",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 405)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_11_get_unknown_path_returns_404(self):
        """Test: GET /anything-else returns 404."""
        status, body = self._raw_request("GET", "/anything-else")
        self.assertEqual(status, 404)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_12_all_responses_have_json_content_type(self):
        """Test: All error responses have Content-Type: application/json."""
        test_cases = [
            ("POST", "/ingest", b'invalid', {"Content-Type": "text/plain"}),
            ("GET", "/nonexistent", None, {}),
            ("POST", "/ingest", b"{}", {}),  # No Content-Type
        ]

        for method, path, body, headers in test_cases:
            conn = http.client.HTTPConnection("127.0.0.1", TEST_PORT)
            try:
                conn.request(method, path, body=body, headers=headers)
                resp = conn.getresponse()
                content_type = resp.headers.get("Content-Type")
                self.assertEqual(
                    content_type,
                    "application/json",
                    f"Failed for {method} {path}: got {content_type}",
                )
                resp.read()  # Consume body
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
