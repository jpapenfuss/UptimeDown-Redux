import io
import os
import sys
import unittest
from unittest.mock import patch, mock_open, MagicMock

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

    def test_iostats_sub_dict_present(self):
        result = self._run()
        self.assertIn("iostats", result["sda"])

    def test_iostats_fields_mapped(self):
        result = self._run()
        iostats = result["sda"]["iostats"]
        self.assertEqual(iostats["major"], 8)
        self.assertEqual(iostats["minor"], 0)
        self.assertEqual(iostats["read_ios"], 6812071)
        self.assertEqual(iostats["write_ios"], 9561353)

    def test_time_key_per_device(self):
        result = self._run()
        self.assertEqual(result["sda"]["_time"], 5000.0)

    def test_device_name_is_dict_key_not_field(self):
        # Device name is popped before zipping; it must not appear as an
        # iostats field — otherwise the column alignment shifts by one.
        result = self._run()
        self.assertNotIn("name", result["sda"]["iostats"])
        # And major must be the first column (8), not shifted to second
        self.assertEqual(result["sda"]["iostats"]["major"], 8)

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
            self.assertIn(key, result["nvme0n1"]["iostats"],
                          f"Expected key {key!r} missing from iostats")

    def test_19_field_values_correct(self):
        # Spot-check several fields from the fixture to confirm correct column mapping.
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", lambda *a, **kw: io.StringIO(DISKSTATS_SAMPLE_19)), \
             patch("time.time", return_value=1.0):
            d = Disk.__new__(Disk)
            result = d.get_devices()
        iostats = result["nvme0n1"]["iostats"]
        self.assertEqual(iostats["major"],          259)
        self.assertEqual(iostats["minor"],          5)
        self.assertEqual(iostats["read_ios"],       16564)
        self.assertEqual(iostats["write_ios"],      538776)
        self.assertEqual(iostats["discard_ios"],    0)
        self.assertEqual(iostats["flush_ios"],      12885)
        self.assertEqual(iostats["flush_ticks"],    28136)

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
        self.assertNotIn("discard_ios", result["sda"]["iostats"])
        self.assertNotIn("flush_ios",   result["sda"]["iostats"])
        self.assertEqual(len(result["sda"]["iostats"]), 13)

    def test_empty_file_returns_empty_dict(self):
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", mock_open(read_data="")), \
             patch("time.time", return_value=1.0):
            d = Disk.__new__(Disk)
            result = d.get_devices()
        self.assertEqual(result, {})


class TestGetDisks(unittest.TestCase):

    def test_populates_blockdevices_on_success(self):
        fake_devices = {"sda": {"iostats": {"major": 8, "minor": 0}, "_time": 1.0}}
        d = Disk.__new__(Disk)
        d.blockdevices = {}
        d.get_devices = MagicMock(return_value=fake_devices)
        d.get_sys_stats = MagicMock(return_value=None)
        d.get_disks()
        self.assertEqual(d.blockdevices, fake_devices)

    def test_blockdevices_unchanged_when_get_devices_returns_none(self):
        d = Disk.__new__(Disk)
        d.blockdevices = {}
        d.get_devices = MagicMock(return_value=None)
        d.get_disks()
        self.assertEqual(d.blockdevices, {})

    def test_get_sys_stats_called_per_device(self):
        fake_devices = {
            "sda": {"iostats": {"major": 8, "minor": 0}, "_time": 1.0},
            "sdb": {"iostats": {"major": 8, "minor": 16}, "_time": 1.0},
        }
        d = Disk.__new__(Disk)
        d.blockdevices = {}
        d.get_devices = MagicMock(return_value=fake_devices)
        d.get_sys_stats = MagicMock(return_value=None)
        d.get_disks()
        self.assertEqual(d.get_sys_stats.call_count, 2)


class TestStubs(unittest.TestCase):

    def test_get_sys_stats_returns_none(self):
        d = Disk.__new__(Disk)
        self.assertIsNone(d.get_sys_stats("8:0"))

    def test_get_queue_returns_zero(self):
        d = Disk.__new__(Disk)
        self.assertEqual(d.get_queue("anything"), 0)


class TestDiskInit(unittest.TestCase):

    def test_blockdevices_initialized_empty(self):
        d = Disk.__new__(Disk)
        d.get_disks = MagicMock()
        d.__init__()
        # blockdevices starts empty; get_disks fills it
        d.get_disks.assert_called_once()


if __name__ == "__main__":
    unittest.main()
