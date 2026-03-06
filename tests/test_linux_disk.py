"""Tests for monitoring/gather/linux_disk.py — Disk.get_devices() /proc/diskstats parsing,
IGNORE_PREFIXES filtering, partial-field handling, get_queue(), and get_sys_stats()."""
import io
import os
import sys
import unittest
from unittest.mock import patch, mock_open, MagicMock, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from monitoring.gather import linux_disk
from monitoring.gather.linux_disk import Disk, DISKSTAT_KEYS

# ---------------------------------------------------------------------------
# Sample /proc/diskstats content
# ---------------------------------------------------------------------------
# Mixed: sda is 19-field (kernel >= 5.5, has flush_ios/flush_ticks),
# sda1/dm-0 are 17-field (kernel 4.18–5.4, has discard but no flush),
# loop0/ram0 are filtered by IGNORE_PREFIXES.
DISKSTATS_SAMPLE = """\
   8       0 sda 6812071 23231120 460799263 43073497 9561353 55255999 521187320 82101912 0 25627284 125229116 0 0 0 0 0 0
   8       1 sda1 100 200 1600 500 50 100 1200 300 0 100 800 0 0 0 0
 252       0 dm-0 1000 0 8000 2000 500 0 4000 1500 5 500 3500 0 0 0 0 0 0
   7       0 loop0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
   1       0 ram0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
"""

# 19-field format (kernel >= 5.5): all fields including flush_ios and flush_ticks
DISKSTATS_SAMPLE_19 = """\
 259       5 nvme0n1 16564 1 460608 2427 538776 0 15779872 65928 0 44768 96491 0 0 0 0 12885 28136
"""


class TestGetDevices(unittest.TestCase):
    """Tests for get_devices(): /proc/diskstats parsing, IGNORE_PREFIXES filtering, and field mapping."""

    def _run(self, content=DISKSTATS_SAMPLE):
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", lambda *a, **kw: io.StringIO(content)), \
             patch("time.time", return_value=5000.0):
            d = Disk.__new__(Disk)
            return d.get_devices()

    def test_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_sda_present(self):
        self.assertIn("sda", self._run())

    def test_partition_present(self):
        self.assertIn("sda1", self._run())

    def test_dm_device_present(self):
        self.assertIn("dm-0", self._run())

    def test_loop_skipped(self):
        self.assertNotIn("loop0", self._run())

    def test_ram_skipped(self):
        self.assertNotIn("ram0", self._run())

    def test_no_iostats_wrapper(self):
        # Fields are stored directly on the device entry, not nested under "iostats".
        result = self._run()
        self.assertNotIn("iostats", result["sda"])

    def test_fields_mapped(self):
        result = self._run()
        entry = result["sda"]
        self.assertEqual(entry["major"], 8)
        self.assertEqual(entry["minor"], 0)
        self.assertEqual(entry["read_ios"], 6812071)
        self.assertEqual(entry["write_ios"], 9561353)

    def test_no_time_key_per_device(self):
        result = self._run()
        self.assertNotIn("_time", result["sda"])

    def test_device_name_is_dict_key_not_field(self):
        # Device name is popped before zipping; it must not appear as a field —
        # otherwise the column alignment shifts by one.
        result = self._run()
        self.assertNotIn("name", result["sda"])
        # And major must be the first column (8), not shifted to second.
        self.assertEqual(result["sda"]["major"], 8)

    def test_returns_none_when_unreadable(self):
        with patch("monitoring.gather.util.caniread", return_value=False):
            d = Disk.__new__(Disk)
            result = d.get_devices()
        self.assertIsNone(result)

    def test_all_19_diskstat_keys_present(self):
        # A full 19-field line must produce all keys in DISKSTAT_KEYS.
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", lambda *a, **kw: io.StringIO(DISKSTATS_SAMPLE_19)), \
             patch("time.time", return_value=1.0):
            d = Disk.__new__(Disk)
            result = d.get_devices()
        for key in DISKSTAT_KEYS:
            self.assertIn(key, result["nvme0n1"],
                          f"Expected key {key!r} missing from device entry")

    def test_19_field_values_correct(self):
        # Spot-check several fields from the fixture to confirm correct column mapping.
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", lambda *a, **kw: io.StringIO(DISKSTATS_SAMPLE_19)), \
             patch("time.time", return_value=1.0):
            d = Disk.__new__(Disk)
            result = d.get_devices()
        entry = result["nvme0n1"]
        self.assertEqual(entry["major"],          259)
        self.assertEqual(entry["minor"],          5)
        self.assertEqual(entry["read_ios"],       16564)
        self.assertEqual(entry["write_ios"],      538776)
        self.assertEqual(entry["discard_ios"],    0)
        self.assertEqual(entry["flush_ios"],      12885)
        self.assertEqual(entry["flush_ticks"],    28136)

    def test_partial_fields_produce_no_extra_keys(self):
        # A line shorter than DISKSTAT_KEYS must not invent keys for absent fields.
        # This simulates a kernel that doesn't report discard/flush counters.
        # After the name pop: major(0) minor(1) + 11 counters = 13 values total → 13 keys.
        content_14 = "   8       0 sda 100 0 800 50 200 0 1600 100 0 200 300\n"
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", lambda *a, **kw: io.StringIO(content_14)), \
             patch("time.time", return_value=1.0):
            d = Disk.__new__(Disk)
            result = d.get_devices()
        # Only 13 keys (indices 0-12 of DISKSTAT_KEYS) should be present.
        self.assertNotIn("discard_ios", result["sda"])
        self.assertNotIn("flush_ios",   result["sda"])
        self.assertEqual(len(result["sda"]), 13)

    def test_empty_file_returns_empty_dict(self):
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", mock_open(read_data="")), \
             patch("time.time", return_value=1.0):
            d = Disk.__new__(Disk)
            result = d.get_devices()
        self.assertEqual(result, {})


class TestGetDisks(unittest.TestCase):
    """Tests for get_disks(): orchestration of get_devices() + get_sys_stats() calls."""

    def test_populates_blockdevices_on_success(self):
        fake_devices = {"sda": {"major": 8, "minor": 0}}
        d = Disk.__new__(Disk)
        d.blockdevices = {}
        d.get_devices = MagicMock(return_value=fake_devices)
        d.get_sys_stats = MagicMock(return_value={})
        d.get_disks()
        self.assertIn("sda", d.blockdevices)

    def test_sys_stats_merged_into_device(self):
        fake_devices = {"sda": {"major": 8, "minor": 0}}
        d = Disk.__new__(Disk)
        d.blockdevices = {}
        d.get_devices = MagicMock(return_value=fake_devices)
        d.get_sys_stats = MagicMock(return_value={"size_bytes": 500107862016, "rotational": 1})
        d.get_disks()
        self.assertEqual(d.blockdevices["sda"]["size_bytes"], 500107862016)
        self.assertEqual(d.blockdevices["sda"]["rotational"], 1)

    def test_empty_sys_stats_not_merged(self):
        fake_devices = {"sda": {"major": 8, "minor": 0}}
        d = Disk.__new__(Disk)
        d.blockdevices = {}
        d.get_devices = MagicMock(return_value=fake_devices)
        d.get_sys_stats = MagicMock(return_value={})
        d.get_disks()
        self.assertNotIn("size_bytes", d.blockdevices["sda"])

    def test_blockdevices_unchanged_when_get_devices_returns_none(self):
        d = Disk.__new__(Disk)
        d.blockdevices = {}
        d.get_devices = MagicMock(return_value=None)
        d.get_disks()
        self.assertEqual(d.blockdevices, {})

    def test_get_sys_stats_called_per_device(self):
        fake_devices = {
            "sda": {"major": 8, "minor": 0},
            "sdb": {"major": 8, "minor": 16},
        }
        d = Disk.__new__(Disk)
        d.blockdevices = {}
        d.get_devices = MagicMock(return_value=fake_devices)
        d.get_sys_stats = MagicMock(return_value=None)
        d.get_disks()
        self.assertEqual(d.get_sys_stats.call_count, 2)


class TestGetQueue(unittest.TestCase):
    """Tests for get_queue(): reads queue/* sysfs attributes."""

    def _run(self, files):
        """Run get_queue() with a fake filesystem mapping attr name → file content."""
        d = Disk.__new__(Disk)

        def fake_open(path, *args, **kwargs):
            for attr, content in files.items():
                if path.endswith(attr):
                    return io.StringIO(content)
            raise FileNotFoundError(path)

        with patch("builtins.open", fake_open):
            return d.get_queue("/sys/block/sda/queue")

    def test_returns_dict(self):
        self.assertIsInstance(self._run({}), dict)

    def test_rotational_parsed(self):
        result = self._run({"rotational": "1\n"})
        self.assertEqual(result["rotational"], 1)

    def test_ssd_rotational_zero(self):
        result = self._run({"rotational": "0\n"})
        self.assertEqual(result["rotational"], 0)

    def test_physical_block_size_parsed(self):
        result = self._run({"physical_block_size": "4096\n"})
        self.assertEqual(result["physical_block_size"], 4096)

    def test_logical_block_size_parsed(self):
        result = self._run({"logical_block_size": "512\n"})
        self.assertEqual(result["logical_block_size"], 512)

    def test_discard_granularity_parsed(self):
        result = self._run({"discard_granularity": "512\n"})
        self.assertEqual(result["discard_granularity"], 512)

    def test_scheduler_bracketed_value_extracted(self):
        result = self._run({"scheduler": "none [mq-deadline] bfq\n"})
        self.assertEqual(result["scheduler"], "mq-deadline")

    def test_scheduler_none_active(self):
        result = self._run({"scheduler": "[none]\n"})
        self.assertEqual(result["scheduler"], "none")

    def test_missing_files_omitted(self):
        result = self._run({})
        self.assertNotIn("rotational", result)
        self.assertNotIn("scheduler", result)

    def test_unbracketed_scheduler_omitted(self):
        # If the file exists but has no bracketed entry, scheduler is not added.
        result = self._run({"scheduler": "none\n"})
        self.assertNotIn("scheduler", result)


class TestGetSysStats(unittest.TestCase):
    """Tests for get_sys_stats(): sysfs path resolution and field merging."""

    def _make_disk(self):
        d = Disk.__new__(Disk)
        d.sys_dev_block_path = "/sys/dev/block/"
        return d

    def test_returns_dict(self):
        d = self._make_disk()
        with patch("os.path.realpath", return_value="/sys/block/sda"), \
             patch("os.path.isdir", return_value=True), \
             patch("builtins.open", side_effect=FileNotFoundError), \
             patch.object(d, "get_queue", return_value={}):
            result = d.get_sys_stats("8:0")
        self.assertIsInstance(result, dict)

    def test_size_bytes_calculated(self):
        d = self._make_disk()
        with patch("os.path.realpath", return_value="/sys/block/sda"), \
             patch("os.path.isdir", return_value=True), \
             patch("builtins.open", lambda p, *a, **kw: io.StringIO("976773168\n")), \
             patch.object(d, "get_queue", return_value={}):
            result = d.get_sys_stats("8:0")
        self.assertEqual(result["size_bytes"], 976773168 * 512)

    def test_queue_attrs_merged(self):
        d = self._make_disk()
        queue_data = {"rotational": 1, "scheduler": "mq-deadline"}
        with patch("os.path.realpath", return_value="/sys/block/sda"), \
             patch("os.path.isdir", return_value=True), \
             patch("builtins.open", side_effect=FileNotFoundError), \
             patch.object(d, "get_queue", return_value=queue_data):
            result = d.get_sys_stats("8:0")
        self.assertEqual(result["rotational"], 1)
        self.assertEqual(result["scheduler"], "mq-deadline")

    def test_partition_falls_back_to_parent_queue(self):
        # Partitions have no queue/ dir; get_queue should be called with ../queue.
        d = self._make_disk()
        with patch("os.path.realpath", return_value="/sys/block/sda/sda1"), \
             patch("os.path.isdir", return_value=False), \
             patch("builtins.open", side_effect=FileNotFoundError) as mock_open_call, \
             patch.object(d, "get_queue", return_value={}) as mock_gq:
            d.get_sys_stats("8:1")
        # get_queue should have been called with the parent queue path.
        args = mock_gq.call_args[0][0]
        self.assertIn("..", args)

    def test_returns_empty_dict_when_realpath_fails(self):
        d = self._make_disk()
        with patch("os.path.realpath", side_effect=OSError("no such file")):
            result = d.get_sys_stats("8:0")
        self.assertEqual(result, {})


class TestDiskInit(unittest.TestCase):
    """Tests for Disk.__init__(): verifies get_disks() is called on construction."""

    def test_blockdevices_initialized_empty(self):
        d = Disk.__new__(Disk)
        d.get_disks = MagicMock()
        d.__init__()
        # blockdevices starts empty; get_disks fills it
        d.get_disks.assert_called_once()


if __name__ == "__main__":
    unittest.main()
