"""Tests for monitoring/gather/aix_filesystems.py — get_filesystems() and AixFilesystems class."""
import os
import sys
import unittest
from unittest.mock import patch, mock_open
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "monitoring", "gather"))
import aix_filesystems
from aix_filesystems import AixFilesystems

# ---------------------------------------------------------------------------
# Sample /etc/filesystems content
# ---------------------------------------------------------------------------
ETC_FILESYSTEMS_SAMPLE = """\
* This is a comment

/:
        dev             = /dev/hd4
        vfs             = jfs2
        log             = /dev/hd8
        mount           = automatic
        account         = false

/home:
        dev             = /dev/hd1
        vfs             = jfs2
        log             = /dev/hd8
        mount           = automatic
        account         = false

/wpars/wpar01/home:
        dev             = /dev/fslv01
        vfs             = jfs2
        log             = INLINE
        mount           = false
        type            = wpar01
        account         = false
"""


def _make_statvfs(f_frsize=4096, f_blocks=1000000, f_bfree=600000, f_bavail=550000,
                  f_bsize=4096, f_files=200000, f_ffree=180000, f_favail=180000):
    return SimpleNamespace(
        f_bsize=f_bsize, f_frsize=f_frsize, f_blocks=f_blocks,
        f_bfree=f_bfree, f_bavail=f_bavail, f_files=f_files,
        f_ffree=f_ffree, f_favail=f_favail,
    )


class TestGetFilesystems(unittest.TestCase):
    """Tests for get_filesystems(): /etc/filesystems parsing, statvfs probing, and edge cases."""

    def _run(self, content=ETC_FILESYSTEMS_SAMPLE, statvfs_side_effect=None):
        if statvfs_side_effect is None:
            statvfs_side_effect = _make_statvfs()

        with patch("os.access", return_value=True), \
             patch("builtins.open", mock_open(read_data=content)), \
             patch("os.statvfs", return_value=statvfs_side_effect), \
             patch("time.time", return_value=7000.0):
            fs = AixFilesystems.__new__(AixFilesystems)
            return fs.get_filesystems()

    def test_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_time_key_absent(self):
        result = self._run()
        self.assertNotIn("_time", result)

    def test_all_configured_mountpoints_present(self):
        result = self._run()
        self.assertIn("/", result)
        self.assertIn("/home", result)
        self.assertIn("/wpars/wpar01/home", result)

    def test_comment_lines_skipped(self):
        result = self._run()
        # No key should be a comment
        for key in result:
            self.assertFalse(key.startswith("*"), f"Comment leaked as key: {key}")

    def test_mounted_entry_has_space_stats(self):
        result = self._run()
        entry = result["/"]
        self.assertTrue(entry["mounted"])
        self.assertIn("bytes_total", entry)
        self.assertIn("pct_used", entry)
        self.assertIn("f_blocks", entry)

    def test_mounted_entry_config_fields(self):
        result = self._run()
        entry = result["/"]
        self.assertEqual(entry["dev"], "/dev/hd4")
        self.assertEqual(entry["vfs"], "jfs2")
        self.assertEqual(entry["mount"], "automatic")

    def test_unmounted_entry_mounted_false(self):
        def statvfs_side(path):
            if path == "/wpars/wpar01/home":
                raise OSError("not mounted")
            return _make_statvfs()

        with patch("os.access", return_value=True), \
             patch("builtins.open", mock_open(read_data=ETC_FILESYSTEMS_SAMPLE)), \
             patch("os.statvfs", side_effect=statvfs_side), \
             patch("time.time", return_value=1.0):
            fs = AixFilesystems.__new__(AixFilesystems)
            result = fs.get_filesystems()

        entry = result["/wpars/wpar01/home"]
        self.assertFalse(entry["mounted"])
        self.assertNotIn("bytes_total", entry)

    def test_unmounted_entry_retains_config_fields(self):
        def statvfs_side(path):
            if path == "/wpars/wpar01/home":
                raise OSError("not mounted")
            return _make_statvfs()

        with patch("os.access", return_value=True), \
             patch("builtins.open", mock_open(read_data=ETC_FILESYSTEMS_SAMPLE)), \
             patch("os.statvfs", side_effect=statvfs_side), \
             patch("time.time", return_value=1.0):
            fs = AixFilesystems.__new__(AixFilesystems)
            result = fs.get_filesystems()

        entry = result["/wpars/wpar01/home"]
        self.assertEqual(entry["dev"], "/dev/fslv01")
        self.assertEqual(entry["vfs"], "jfs2")
        self.assertEqual(entry["type"], "wpar01")

    def test_returns_empty_dict_when_file_unreadable(self):
        with patch("os.access", return_value=False):
            fs = AixFilesystems.__new__(AixFilesystems)
            result = fs.get_filesystems()
        self.assertEqual(result, {})

    def test_bytes_calculated_with_frsize(self):
        st = _make_statvfs(f_frsize=4096, f_bsize=8192, f_blocks=1000)
        result = self._run(statvfs_side_effect=st)
        self.assertEqual(result["/"]["bytes_total"], 4096 * 1000)
        self.assertNotEqual(result["/"]["bytes_total"], 8192 * 1000)

    def test_pct_used_calculation(self):
        # 750/1000 blocks used → 75.0%
        st = _make_statvfs(f_blocks=1000, f_bfree=250, f_bavail=200)
        result = self._run(statvfs_side_effect=st)
        self.assertEqual(result["/"]["pct_used"], 75.0)

    def test_zero_f_blocks_no_pct_keys(self):
        # A mounted filesystem with f_blocks=0 should still be mounted=True
        # but must not have pct/bytes keys (would cause division by zero)
        st = _make_statvfs(f_blocks=0)
        result = self._run(statvfs_side_effect=st)
        entry = result["/"]
        self.assertTrue(entry["mounted"])
        self.assertNotIn("pct_used", entry)
        self.assertNotIn("bytes_total", entry)

    def test_mountpoint_key_in_entry(self):
        result = self._run()
        self.assertEqual(result["/"]["mountpoint"], "/")
        self.assertEqual(result["/home"]["mountpoint"], "/home")


class TestAixFilesystemsInit(unittest.TestCase):
    """Verify that AixFilesystems.__init__() calls get_filesystems() and stores the result."""

    def test_init_populates_filesystems(self):
        fake = {"/": {"mounted": True, "dev": "/dev/hd4"}}
        with patch.object(AixFilesystems, "get_filesystems", return_value=fake):
            obj = AixFilesystems()
        self.assertEqual(obj.filesystems, fake)


if __name__ == "__main__":
    unittest.main()
