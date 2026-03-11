"""Test suite for receiver authentication."""

import json
import http.client
import logging
import os
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer

from receiver.auth import load_tokens, check_auth
from receiver.server import IngestHandler


TEST_PORT = 18944


class TestLoadTokens(unittest.TestCase):
    """Tests for the load_tokens function."""

    def test_01_load_tokens_valid_file(self):
        """Test: load_tokens with valid file (3 tokens, 32+ chars each)."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("a" * 32 + "\n")
            f.write("b" * 40 + "\n")
            f.write("c" * 50 + "\n")
            temp_path = f.name

        try:
            tokens = load_tokens(temp_path)
            self.assertEqual(len(tokens), 3)
            self.assertIn("a" * 32, tokens)
            self.assertIn("b" * 40, tokens)
            self.assertIn("c" * 50, tokens)
        finally:
            os.unlink(temp_path)

    def test_02_load_tokens_with_comments_and_blanks(self):
        """Test: load_tokens with comments and blank lines."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("# This is a comment\n")
            f.write("\n")
            f.write("a" * 32 + "\n")
            f.write("  \n")  # whitespace only
            f.write("# Another comment\n")
            f.write("b" * 40 + "\n")
            temp_path = f.name

        try:
            tokens = load_tokens(temp_path)
            self.assertEqual(len(tokens), 2)
            self.assertIn("a" * 32, tokens)
            self.assertIn("b" * 40, tokens)
        finally:
            os.unlink(temp_path)

    def test_02b_load_tokens_strips_leading_whitespace(self):
        """Test: load_tokens strips leading/trailing whitespace from tokens."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("  " + "a" * 32 + "\n")  # leading spaces
            f.write("b" * 40 + "  \n")  # trailing spaces
            f.write("\t" + "c" * 50 + "\n")  # leading tab
            temp_path = f.name

        try:
            tokens = load_tokens(temp_path)
            self.assertEqual(len(tokens), 3)
            self.assertIn("a" * 32, tokens)  # without leading spaces
            self.assertIn("b" * 40, tokens)  # without trailing spaces
            self.assertIn("c" * 50, tokens)  # without leading tab
        finally:
            os.unlink(temp_path)

    def test_03_load_tokens_rejects_short_tokens(self):
        """Test: load_tokens with short token (< 32 chars) is skipped."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("short_token\n")  # 11 chars < 32
            f.write("a" * 32 + "\n")
            temp_path = f.name

        try:
            tokens = load_tokens(temp_path)
            self.assertEqual(len(tokens), 1)
            self.assertIn("a" * 32, tokens)
            self.assertNotIn("short_token", tokens)
        finally:
            os.unlink(temp_path)

    def test_04_load_tokens_nonexistent_file(self):
        """Test: load_tokens with nonexistent file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            load_tokens("/nonexistent/path/tokens.txt")


class TestCheckAuth(unittest.TestCase):
    """Tests for the check_auth function."""

    def setUp(self):
        """Create a valid token set for tests."""
        self.valid_tokens = {"a" * 32, "b" * 40, "c" * 50}

    def test_05_check_auth_valid_bearer_token(self):
        """Test: check_auth with valid Bearer token returns True."""
        # Mock headers object
        class MockHeaders:
            def get(self, key, default=None):
                if key == "Authorization":
                    return f"Bearer {'a' * 32}"
                return default

        headers = MockHeaders()
        result = check_auth(headers, self.valid_tokens)
        self.assertTrue(result)

    def test_06_check_auth_invalid_token(self):
        """Test: check_auth with invalid token returns False."""
        class MockHeaders:
            def get(self, key, default=None):
                if key == "Authorization":
                    return f"Bearer {'x' * 32}"
                return default

        headers = MockHeaders()
        result = check_auth(headers, self.valid_tokens)
        self.assertFalse(result)

    def test_07_check_auth_missing_header(self):
        """Test: check_auth with missing Authorization header returns False."""
        class MockHeaders:
            def get(self, key, default=None):
                return default

        headers = MockHeaders()
        result = check_auth(headers, self.valid_tokens)
        self.assertFalse(result)

    def test_08_check_auth_basic_scheme(self):
        """Test: check_auth with Basic scheme instead of Bearer returns False."""
        class MockHeaders:
            def get(self, key, default=None):
                if key == "Authorization":
                    return f"Basic {'a' * 32}"
                return default

        headers = MockHeaders()
        result = check_auth(headers, self.valid_tokens)
        self.assertFalse(result)

    def test_09_check_auth_empty_token(self):
        """Test: check_auth with empty token string returns False."""
        class MockHeaders:
            def get(self, key, default=None):
                if key == "Authorization":
                    return "Bearer "
                return default

        headers = MockHeaders()
        result = check_auth(headers, self.valid_tokens)
        self.assertFalse(result)

    def test_10_check_auth_extra_whitespace(self):
        """Test: check_auth with extra whitespace 'Bearer  token' returns False."""
        class MockHeaders:
            def get(self, key, default=None):
                if key == "Authorization":
                    return f"Bearer  {'a' * 32}"  # two spaces
                return default

        headers = MockHeaders()
        result = check_auth(headers, self.valid_tokens)
        self.assertFalse(result)

    def test_10b_check_auth_lowercase_bearer(self):
        """Test: check_auth with lowercase 'bearer' scheme returns True (case-insensitive)."""
        class MockHeaders:
            def get(self, key, default=None):
                if key == "Authorization":
                    return f"bearer {'a' * 32}"  # lowercase
                return default

        headers = MockHeaders()
        result = check_auth(headers, self.valid_tokens)
        self.assertTrue(result)

    def test_10c_check_auth_uppercase_bearer(self):
        """Test: check_auth with uppercase 'BEARER' scheme returns True (case-insensitive)."""
        class MockHeaders:
            def get(self, key, default=None):
                if key == "Authorization":
                    return f"BEARER {'a' * 32}"  # uppercase
                return default

        headers = MockHeaders()
        result = check_auth(headers, self.valid_tokens)
        self.assertTrue(result)

    def test_10d_check_auth_bearer_with_trailing_space(self):
        """Test: check_auth with 'Bearer ' (trailing space, no token) returns False."""
        class MockHeaders:
            def get(self, key, default=None):
                if key == "Authorization":
                    return "Bearer "  # no token after space
                return default

        headers = MockHeaders()
        result = check_auth(headers, self.valid_tokens)
        self.assertFalse(result)


class TestReceiverAuthIntegration(unittest.TestCase):
    """Integration tests: authentication with server."""

    @classmethod
    def setUpClass(cls):
        """Start server with valid tokens."""
        # Create temp token file
        cls.token_file = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt"
        )
        cls.valid_token = "x" * 50
        cls.token_file.write(f"{cls.valid_token}\n")
        cls.token_file.write("y" * 60 + "\n")
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
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        """Shut down server and clean up."""
        cls.server.shutdown()
        cls.server_thread.join(timeout=2)
        os.unlink(cls.token_file.name)
        del os.environ["RECEIVER_TOKENS_FILE"]

    def _valid_payload(self):
        """Generate a minimal valid payload for testing."""
        return json.dumps({
            "system_id": "test-system",
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }).encode("utf-8")

    def _raw_request(self, method, path, body=None, headers=None):
        """Low-level HTTP request helper."""
        conn = http.client.HTTPConnection("127.0.0.1", TEST_PORT)
        try:
            conn.request(method, path, body=body, headers=headers or {})
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

    def test_11_post_ingest_without_auth(self):
        """Test: POST /ingest without auth header returns 401."""
        status, body = self._raw_request(
            "POST",
            "/ingest",
            body=b'{"system_id": "test"}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 401)
        self.assertIsNotNone(body)
        self.assertIn("error", body)

    def test_12_post_ingest_with_valid_auth(self):
        """Test: POST /ingest with valid auth + valid JSON returns 202."""
        status, body = self._raw_request(
            "POST",
            "/ingest",
            body=self._valid_payload(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.valid_token}",
            },
        )
        self.assertEqual(status, 202)
        self.assertIsNotNone(body)
        self.assertIn("status", body)

    def test_13_get_health_without_auth(self):
        """Test: GET /health without auth returns 200 (health is unauthenticated)."""
        status, body = self._raw_request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIsNotNone(body)
        self.assertIn("status", body)
        self.assertEqual(body["status"], "ok")


if __name__ == "__main__":
    unittest.main()
