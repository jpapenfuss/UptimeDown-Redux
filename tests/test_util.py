import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "monitoring", "gather"))
import util


class TestCaniread(unittest.TestCase):

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

    # --- kB variants ---
    def test_kb_lowercase(self):
        self.assertEqual(util.tobytes(1, "kB"), 1024)

    def test_kb_uppercase(self):
        self.assertEqual(util.tobytes(1, "KB"), 1024)

    def test_kilobyte(self):
        self.assertEqual(util.tobytes(1, "kilobyte"), 1024)

    def test_kilobytes(self):
        self.assertEqual(util.tobytes(1, "kilobytes"), 1024)

    def test_kb_value_multiplied(self):
        self.assertEqual(util.tobytes(16384, "kB"), 16384 * 1024)

    # --- MB variants ---
    def test_mb_mixed_case(self):
        self.assertEqual(util.tobytes(1, "mB"), 1024 ** 2)

    def test_mb_uppercase(self):
        self.assertEqual(util.tobytes(1, "MB"), 1024 ** 2)

    def test_megabyte(self):
        self.assertEqual(util.tobytes(1, "megabyte"), 1024 ** 2)

    def test_megabytes(self):
        self.assertEqual(util.tobytes(1, "megabytes"), 1024 ** 2)

    # --- GB variants ---
    def test_gb_mixed_case(self):
        self.assertEqual(util.tobytes(1, "gB"), 1024 ** 3)

    def test_gb_uppercase(self):
        self.assertEqual(util.tobytes(1, "GB"), 1024 ** 3)

    def test_gigabyte(self):
        self.assertEqual(util.tobytes(1, "gigabyte"), 1024 ** 3)

    def test_gigabytes(self):
        self.assertEqual(util.tobytes(1, "gigabytes"), 1024 ** 3)

    # --- TB variants ---
    def test_tb_mixed_case(self):
        self.assertEqual(util.tobytes(1, "tB"), 1024 ** 4)

    def test_tb_uppercase(self):
        self.assertEqual(util.tobytes(1, "TB"), 1024 ** 4)

    def test_terabyte(self):
        self.assertEqual(util.tobytes(1, "terabyte"), 1024 ** 4)

    def test_terabytes(self):
        self.assertEqual(util.tobytes(1, "terabytes"), 1024 ** 4)

    # --- Unknown / edge cases ---
    def test_unknown_multiplier_returns_zero(self):
        self.assertEqual(util.tobytes(100, "pb"), 0)

    def test_empty_multiplier_returns_zero(self):
        self.assertEqual(util.tobytes(100, ""), 0)

    def test_wrong_case_kb_returns_zero(self):
        # "kb" (all lowercase) is not in the accepted list
        self.assertEqual(util.tobytes(1, "kb"), 0)

    def test_zero_value(self):
        self.assertEqual(util.tobytes(0, "kB"), 0)

    def test_large_value_tb(self):
        self.assertEqual(util.tobytes(1024, "TB"), 1024 * 1024 ** 4)


if __name__ == "__main__":
    unittest.main()
