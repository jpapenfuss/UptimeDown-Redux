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
        # f_frsize=4096, f_bsize=8192 — must use f_frsize, not f_bsize
        st = _make_statvfs(f_frsize=4096, f_bsize=8192, f_blocks=1000)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["bytes_total"], 4096 * 1000)
        # Confirm f_bsize was NOT used
        self.assertNotEqual(result["bytes_total"], 8192 * 1000)

    def test_bytes_free_uses_frsize(self):
        st = _make_statvfs(f_frsize=4096, f_bsize=8192, f_bfree=500)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["bytes_free"], 4096 * 500)

    def test_bytes_available_uses_frsize(self):
        st = _make_statvfs(f_frsize=4096, f_bsize=8192, f_bavail=450)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["bytes_available"], 4096 * 450)

    def test_pct_used_calculation(self):
        # 750/1000 blocks used → 75.0%
        st = _make_statvfs(f_blocks=1000, f_bfree=250, f_bavail=200)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["pct_used"], 75.0)

    def test_pct_free_calculation(self):
        # 250/1000 blocks free → 25.0%
        st = _make_statvfs(f_blocks=1000, f_bfree=250)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["pct_free"], 25.0)

    def test_pct_available_calculation(self):
        # 200/1000 blocks available → 20.0%
        st = _make_statvfs(f_blocks=1000, f_bavail=200)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["pct_available"], 20.0)

    def test_pct_reserved_calculation(self):
        # reserved = 1 - bavail/blocks; 800/1000 → 80.0%
        # (different from pct_used which is 1 - bfree/blocks)
        st = _make_statvfs(f_blocks=1000, f_bfree=250, f_bavail=200)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["pct_reserved"], 80.0)
        # pct_reserved must differ from pct_used when there are reserved blocks
        self.assertNotEqual(result["pct_reserved"], result["pct_used"])

    def test_pct_truncated_not_rounded(self):
        # 1/3 * 100 = 33.3333...% — must truncate to 4 decimal places: 33.3333
        # If rounding were used, 33.33335 would round to 33.3334.
        # Use 2/3 used (1 free out of 3): (1 - 1/3) * 100 = 66.6666...
        # Truncated: 66.6666. Rounded to 4dp: 66.6667. Confirms truncation.
        st = _make_statvfs(f_blocks=3, f_bfree=1, f_bavail=1)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["pct_used"], 66.6666)

    def test_full_disk_pct_used_100(self):
        st = _make_statvfs(f_blocks=1000, f_bfree=0, f_bavail=0)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["pct_used"], 100.0)

    def test_empty_disk_pct_used_zero(self):
        st = _make_statvfs(f_blocks=1000, f_bfree=1000, f_bavail=1000)
        result = self._fs().explode_statvfs(st)
        self.assertEqual(result["pct_used"], 0.0)

    def test_no_camelcase_keys(self):
        st = _make_statvfs()
        result = self._fs().explode_statvfs(st)
        for key in result:
            self.assertFalse(any(c.isupper() for c in key),
                             f"camelCase key leaked into output: {key!r}")


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
        self.assertIn("bytes_total", entry)
        self.assertIn("pct_used", entry)
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

    def test_options_stored_as_json(self):
        st = _make_statvfs()
        with patch("os.statvfs", return_value=st):
            result = self._fs().process_mount(self._mount_line(options="rw,relatime"))
        import json
        opts = json.loads(result["/mnt"]["options"])
        self.assertEqual(opts, {"rw": True, "relatime": True})

    def test_options_key_value_parsed(self):
        st = _make_statvfs()
        with patch("os.statvfs", return_value=st):
            result = self._fs().process_mount(self._mount_line(options="rw,size=1g,uid=0"))
        import json
        opts = json.loads(result["/mnt"]["options"])
        self.assertTrue(opts["rw"])
        self.assertEqual(opts["size"], "1g")
        self.assertEqual(opts["uid"], "0")

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

    def test_space_values_correct_end_to_end(self):
        # Drive a known statvfs through the full parse path and verify
        # bytes_total and pct_used are computed correctly end-to-end.
        st = _make_statvfs(f_frsize=4096, f_blocks=1000, f_bfree=250, f_bavail=200)
        fs = Filesystems.__new__(Filesystems)
        fs.fs_reject = []
        with patch("builtins.open", lambda *a, **kw: io.StringIO(PROC_MOUNTS_SAMPLE)), \
             patch("os.statvfs", return_value=st), \
             patch("time.time", return_value=1.0):
            result = fs.get_filesystems_from_proc("/proc/mounts")
        self.assertEqual(result["/"]["bytes_total"], 4096 * 1000)
        self.assertEqual(result["/"]["pct_used"], 75.0)


if __name__ == "__main__":
    unittest.main()
