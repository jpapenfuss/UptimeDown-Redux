import io
import os
import sys
import unittest
from unittest.mock import patch, mock_open, MagicMock, call
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from monitoring.gather import linux_filesystems
from monitoring.gather.linux_filesystems import Filesystems

# ---------------------------------------------------------------------------
# Sample /proc/mounts content
# ---------------------------------------------------------------------------
PROC_MOUNTS_SAMPLE = """\
sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
/dev/sda1 / ext4 rw,relatime,errors=remount-ro 0 0
/dev/sda2 /home xfs rw,relatime 0 0
tmpfs /run tmpfs rw,nosuid,nodev,noexec,relatime,size=819200k,mode=755 0 0
"""


def _make_statvfs(f_frsize=4096, f_blocks=1000000, f_bfree=500000, f_bavail=450000,
                  f_bsize=4096, f_files=200000, f_ffree=180000, f_favail=180000,
                  f_flag=0, f_namemax=255):
    """Return a mock os.statvfs_result-like object."""
    return SimpleNamespace(
        f_bsize=f_bsize, f_frsize=f_frsize, f_blocks=f_blocks,
        f_bfree=f_bfree, f_bavail=f_bavail, f_files=f_files,
        f_ffree=f_ffree, f_favail=f_favail, f_flag=f_flag, f_namemax=f_namemax,
    )


class TestExplodeStatvfs(unittest.TestCase):

    def _fs(self):
        fs = Filesystems.__new__(Filesystems)
        fs.fs_reject = []
        return fs

    def test_returns_none_when_f_blocks_zero(self):
        st = _make_statvfs(f_blocks=0)
        self.assertIsNone(self._fs().explode_statvfs(st))

    def test_returns_dict_for_normal_fs(self):
        st = _make_statvfs()
        result = self._fs().explode_statvfs(st)
        self.assertIsInstance(result, dict)

    def test_raw_statvfs_fields_present(self):
        st = _make_statvfs()
        result = self._fs().explode_statvfs(st)
        for field in ("f_bsize", "f_frsize", "f_blocks", "f_bfree", "f_bavail",
                      "f_files", "f_ffree", "f_favail"):
            self.assertIn(field, result)

    def test_uses_frsize_for_bytes_total(self):
        # f_frsize=4096, f_bsize=8192 — must use f_frsize
        st = _make_statvfs(f_frsize=4096, f_bsize=8192, f_blocks=1000)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["bytesTotal"], 4096 * 1000)

    def test_bytes_free_uses_frsize(self):
        st = _make_statvfs(f_frsize=4096, f_bsize=8192, f_bfree=500)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["bytesFree"], 4096 * 500)

    def test_bytes_available_uses_frsize(self):
        st = _make_statvfs(f_frsize=4096, f_bsize=8192, f_bavail=450)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["bytesAvailable"], 4096 * 450)

    def test_pct_used_calculation(self):
        st = _make_statvfs(f_blocks=1000, f_bfree=250, f_bavail=200)
        result = self._fs().explode_statvfs(st)
        self.assertAlmostEqual(result["pctUsed"], 75.0)

    def test_pct_free_calculation(self):
        st = _make_statvfs(f_blocks=1000, f_bfree=250)
        result = self._fs().explode_statvfs(st)
        self.assertAlmostEqual(result["pctFree"], 25.0)

    def test_pct_available_calculation(self):
        st = _make_statvfs(f_blocks=1000, f_bavail=200)
        result = self._fs().explode_statvfs(st)
        self.assertAlmostEqual(result["pctAvailable"], 20.0)

    def test_pct_reserved_calculation(self):
        # reserved = pctFree - pctAvailable  (blocks free to root but not users)
        st = _make_statvfs(f_blocks=1000, f_bfree=250, f_bavail=200)
        result = self._fs().explode_statvfs(st)
        self.assertAlmostEqual(result["pctReserved"], (1.0 - 200/1000) * 100)

    def test_full_disk_pct_used_100(self):
        st = _make_statvfs(f_blocks=1000, f_bfree=0, f_bavail=0)
        result = self._fs().explode_statvfs(st)
        self.assertAlmostEqual(result["pctUsed"], 100.0)

    def test_empty_disk_pct_used_zero(self):
        st = _make_statvfs(f_blocks=1000, f_bfree=1000, f_bavail=1000)
        result = self._fs().explode_statvfs(st)
        self.assertAlmostEqual(result["pctUsed"], 0.0)


class TestProcessMount(unittest.TestCase):

    def _fs(self):
        fs = Filesystems.__new__(Filesystems)
        fs.fs_reject = []
        return fs

    def _mount_line(self, device="/dev/sda1", path="/mnt", fstype="ext4",
                    options="rw,relatime", dump="0", passno="0"):
        return [device, path, fstype, options, dump, passno]

    def test_normal_mount_returns_entry(self):
        st = _make_statvfs()
        with patch("os.statvfs", return_value=st):
            fs = self._fs()
            result = fs.process_mount(self._mount_line())
        self.assertIn("/mnt", result)

    def test_entry_has_normalized_keys(self):
        st = _make_statvfs()
        with patch("os.statvfs", return_value=st):
            fs = self._fs()
            result = fs.process_mount(self._mount_line())
        entry = result["/mnt"]
        self.assertEqual(entry["mountpoint"], "/mnt")
        self.assertEqual(entry["dev"], "/dev/sda1")
        self.assertEqual(entry["vfs"], "ext4")
        self.assertTrue(entry["mounted"])

    def test_space_stats_merged_in(self):
        st = _make_statvfs()
        with patch("os.statvfs", return_value=st):
            result = self._fs().process_mount(self._mount_line())
        entry = result["/mnt"]
        self.assertIn("bytesTotal", entry)
        self.assertIn("pctUsed", entry)
        self.assertIn("f_blocks", entry)

    def test_ignored_fstype_returns_empty(self):
        for fstype in ("tmpfs", "sysfs", "cgroup", "proc"):
            with self.subTest(fstype=fstype):
                result = self._fs().process_mount(self._mount_line(fstype=fstype))
                self.assertEqual(result, {})

    def test_rejected_path_returns_empty(self):
        fs = self._fs()
        fs.fs_reject = ["/mnt"]
        result = fs.process_mount(self._mount_line())
        self.assertEqual(result, {})

    def test_zero_block_fs_returns_empty_and_adds_to_reject(self):
        st = _make_statvfs(f_blocks=0)
        with patch("os.statvfs", return_value=st):
            fs = self._fs()
            result = fs.process_mount(self._mount_line())
        self.assertEqual(result, {})
        self.assertIn("/mnt", fs.fs_reject)

    def test_options_kept_as_string(self):
        st = _make_statvfs()
        with patch("os.statvfs", return_value=st):
            result = self._fs().process_mount(self._mount_line(options="rw,relatime"))
        entry = result["/mnt"]
        self.assertEqual(entry["options"], "rw,relatime")

    def test_statvfs_oserror_returns_empty(self):
        # Stale NFS mounts, disappeared bind mounts, etc. raise OSError.
        # process_mount() must catch it and return {} rather than crashing.
        with patch("os.statvfs", side_effect=OSError("Stale file handle")):
            result = self._fs().process_mount(self._mount_line())
        self.assertEqual(result, {})


class TestGetFilesystems(unittest.TestCase):

    def test_prefers_proc_mounts(self):
        fs = Filesystems.__new__(Filesystems)
        fs.fs_reject = []
        with patch("monitoring.gather.util.caniread", side_effect=lambda p: True), \
             patch.object(fs, "get_filesystems_from_proc", return_value={}) as mock_gffp:
            fs.get_filesystems()
            mock_gffp.assert_called_once_with("/proc/mounts")

    def test_falls_back_to_mtab(self):
        fs = Filesystems.__new__(Filesystems)
        fs.fs_reject = []
        def caniread_side(path):
            return path == "/etc/mtab"
        with patch("monitoring.gather.util.caniread", side_effect=caniread_side), \
             patch.object(fs, "get_filesystems_from_proc", return_value={}) as mock_gffp:
            fs.get_filesystems()
            mock_gffp.assert_called_once_with("/etc/mtab")

    def test_raises_when_both_unreadable(self):
        fs = Filesystems.__new__(Filesystems)
        fs.fs_reject = []
        with patch("monitoring.gather.util.caniread", return_value=False):
            with self.assertRaises(RuntimeError):
                fs.get_filesystems()


class TestGetFilesystemsFromProc(unittest.TestCase):

    def test_has_time_key(self):
        st = _make_statvfs()
        fs = Filesystems.__new__(Filesystems)
        fs.fs_reject = []
        with patch("builtins.open", lambda *a, **kw: io.StringIO(PROC_MOUNTS_SAMPLE)), \
             patch("os.statvfs", return_value=st), \
             patch("time.time", return_value=9999.0):
            result = fs.get_filesystems_from_proc("/proc/mounts")
        self.assertEqual(result["_time"], 9999.0)

    def test_real_filesystems_included(self):
        st = _make_statvfs()
        fs = Filesystems.__new__(Filesystems)
        fs.fs_reject = []
        with patch("builtins.open", lambda *a, **kw: io.StringIO(PROC_MOUNTS_SAMPLE)), \
             patch("os.statvfs", return_value=st), \
             patch("time.time", return_value=1.0):
            result = fs.get_filesystems_from_proc("/proc/mounts")
        self.assertIn("/", result)
        self.assertIn("/home", result)

    def test_ignored_fstypes_excluded(self):
        st = _make_statvfs()
        fs = Filesystems.__new__(Filesystems)
        fs.fs_reject = []
        with patch("builtins.open", lambda *a, **kw: io.StringIO(PROC_MOUNTS_SAMPLE)), \
             patch("os.statvfs", return_value=st), \
             patch("time.time", return_value=1.0):
            result = fs.get_filesystems_from_proc("/proc/mounts")
        self.assertNotIn("/sys", result)
        self.assertNotIn("/proc", result)
        self.assertNotIn("/run", result)


if __name__ == "__main__":
    unittest.main()
