"""Tests for monitoring/gather/util.py — caniread() and tobytes()."""
import os
import sys
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
