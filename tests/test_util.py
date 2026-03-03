"""Tests for monitoring/gather/util.py — caniread(), tobytes(), and IMDS helpers."""
import io
import os
import socket
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "monitoring", "gather"))
import util


class TestCaniread(unittest.TestCase):
    """Verify caniread() returns correct booleans and passes os.R_OK to os.access."""

    def test_readable_file_returns_true(self):
        with patch("os.access", return_value=True):
            self.assertTrue(util.caniread("/any/path"))

    def test_unreadable_file_returns_false(self):
        with patch("os.access", return_value=False):
            self.assertFalse(util.caniread("/any/path"))

    def test_passes_r_ok_flag(self):
        with patch("os.access") as mock_access:
            mock_access.return_value = True
            util.caniread("/some/path")
            mock_access.assert_called_once_with("/some/path", os.R_OK)

    def test_real_readable_file(self):
        # /dev/null is always readable
        self.assertTrue(util.caniread("/dev/null"))

    def test_real_nonexistent_path(self):
        self.assertFalse(util.caniread("/nonexistent/path/that/does/not/exist"))


class TestTobytes(unittest.TestCase):
    """Verify tobytes() correctly converts SI, IEC, and bare-byte unit strings."""

    # --- bare bytes ---
    def test_b(self):
        self.assertEqual(util.tobytes(1, "b"), 1)

    # --- SI (powers of 1000) ---
    def test_kb_si(self):
        self.assertEqual(util.tobytes(1, "KB"), 1000)

    def test_mb_si(self):
        self.assertEqual(util.tobytes(1, "MB"), 1000 ** 2)

    def test_gb_si(self):
        self.assertEqual(util.tobytes(1, "GB"), 1000 ** 3)

    def test_tb_si(self):
        self.assertEqual(util.tobytes(1, "TB"), 1000 ** 4)

    def test_pb_si(self):
        self.assertEqual(util.tobytes(1, "PB"), 1000 ** 5)

    def test_eb_si(self):
        self.assertEqual(util.tobytes(1, "EB"), 1000 ** 6)

    # --- IEC (powers of 1024) ---
    def test_kib(self):
        self.assertEqual(util.tobytes(1, "KiB"), 1024)

    def test_mib(self):
        self.assertEqual(util.tobytes(1, "MiB"), 1024 ** 2)

    def test_gib(self):
        self.assertEqual(util.tobytes(1, "GiB"), 1024 ** 3)

    def test_tib(self):
        self.assertEqual(util.tobytes(1, "TiB"), 1024 ** 4)

    def test_pib(self):
        self.assertEqual(util.tobytes(1, "PiB"), 1024 ** 5)

    def test_eib(self):
        self.assertEqual(util.tobytes(1, "EiB"), 1024 ** 6)

    # --- case-insensitivity ---
    def test_case_insensitive_si(self):
        self.assertEqual(util.tobytes(1, "kb"), 1000)

    def test_case_insensitive_iec(self):
        self.assertEqual(util.tobytes(1, "kib"), 1024)

    # --- value scaling ---
    def test_value_multiplied(self):
        self.assertEqual(util.tobytes(16384, "KiB"), 16384 * 1024)

    # --- unknown / edge cases ---
    def test_unknown_returns_zero(self):
        self.assertEqual(util.tobytes(100, "qb"), 0)

    def test_empty_returns_zero(self):
        self.assertEqual(util.tobytes(100, ""), 0)

    def test_zero_value(self):
        self.assertEqual(util.tobytes(0, "KiB"), 0)


class TestImdsReachable(unittest.TestCase):
    """Verify imds_reachable() returns correct booleans based on TCP probe outcome."""

    def test_returns_true_when_connection_succeeds(self):
        mock_sock = MagicMock()
        with patch("socket.create_connection", return_value=mock_sock):
            self.assertTrue(util.imds_reachable())

    def test_closes_socket_on_success(self):
        mock_sock = MagicMock()
        with patch("socket.create_connection", return_value=mock_sock):
            util.imds_reachable()
        mock_sock.close.assert_called_once()

    def test_returns_false_on_timeout(self):
        with patch("socket.create_connection", side_effect=socket.timeout):
            self.assertFalse(util.imds_reachable())

    def test_returns_false_on_connection_refused(self):
        with patch("socket.create_connection", side_effect=ConnectionRefusedError):
            self.assertFalse(util.imds_reachable())

    def test_returns_false_on_os_error(self):
        with patch("socket.create_connection", side_effect=OSError):
            self.assertFalse(util.imds_reachable())

    def test_uses_supplied_ip_and_port(self):
        mock_sock = MagicMock()
        with patch("socket.create_connection", return_value=mock_sock) as mock_conn:
            util.imds_reachable(ip="1.2.3.4", port=8080, timeout=0.1)
        mock_conn.assert_called_once_with(("1.2.3.4", 8080), timeout=0.1)


class TestImdsGet(unittest.TestCase):
    """Verify imds_get() makes a GET request and returns the response body."""

    def _mock_urlopen(self, body):
        mock_resp = MagicMock()
        mock_resp.read.return_value = body.encode('utf-8')
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return patch("urllib.request.urlopen", return_value=mock_resp)

    def test_returns_response_body(self):
        with self._mock_urlopen("hello"):
            result = util.imds_get("169.254.169.254", "/latest/meta-data/")
        self.assertEqual(result, "hello")

    def test_returns_none_on_exception(self):
        with patch("urllib.request.urlopen", side_effect=OSError):
            result = util.imds_get("169.254.169.254", "/latest/meta-data/")
        self.assertIsNone(result)

    def test_passes_headers(self):
        with self._mock_urlopen("ok") as mock_urlopen:
            util.imds_get("169.254.169.254", "/path",
                          headers={"X-aws-ec2-metadata-token": "tok"})
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_header("X-aws-ec2-metadata-token"), "tok")


class TestImdsPut(unittest.TestCase):
    """Verify imds_put() makes a PUT request with an empty body."""

    def _mock_urlopen(self, body):
        mock_resp = MagicMock()
        mock_resp.read.return_value = body.encode('utf-8')
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return patch("urllib.request.urlopen", return_value=mock_resp)

    def test_returns_response_body(self):
        with self._mock_urlopen("the-token"):
            result = util.imds_put("169.254.169.254", "/latest/api/token",
                                   headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"})
        self.assertEqual(result, "the-token")

    def test_returns_none_on_exception(self):
        with patch("urllib.request.urlopen", side_effect=OSError):
            result = util.imds_put("169.254.169.254", "/latest/api/token")
        self.assertIsNone(result)

    def test_request_method_is_put(self):
        with self._mock_urlopen("tok") as mock_urlopen:
            util.imds_put("169.254.169.254", "/latest/api/token")
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_method(), "PUT")

    def test_request_has_empty_body(self):
        with self._mock_urlopen("tok") as mock_urlopen:
            util.imds_put("169.254.169.254", "/latest/api/token")
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.data, b'')


if __name__ == "__main__":
    unittest.main()
