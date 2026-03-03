"""Tests for monitoring/gather/linux_memory.py — Memory.GetMeminfo() and GetSlabinfo()."""
import io
import os
import sys
import unittest
from unittest.mock import patch, mock_open, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from monitoring.gather import linux_memory

MEMINFO_SAMPLE = """\
MemTotal:       16384000 kB
MemFree:         8192000 kB
MemAvailable:   10000000 kB
Buffers:          512000 kB
Cached:          2048000 kB
SwapCached:            0 kB
Active:          4096000 kB
Inactive:        2048000 kB
SwapTotal:       4096000 kB
SwapFree:        4000000 kB
Dirty:              1024 kB
Writeback:             0 kB
AnonPages:       2048000 kB
Mapped:           512000 kB
Slab:             256000 kB
SReclaimable:     128000 kB
SUnreclaim:       128000 kB
HugePages_Total:       0
HugePages_Free:        0
Hugepagesize:       2048 kB
"""

SLABINFO_SAMPLE = """\
slabinfo - version: 2.1
# name            <active_objs> <num_objs> <objsize> <objperslab> <pagesperslab> : tunables <limit> <batchcount> <sharedfactor> : slabdata <active_slabs> <num_slabs> <sharedavail>
ext4_inode_cache  30338  44330   1096   29   8 : tunables   0   0   0 : slabdata   2834   2834     0
kmalloc-256        1234   2048    256   16   1 : tunables   0   0   0 : slabdata    128    128     0
"""


class TestGetMeminfo(unittest.TestCase):
    """Tests for GetMeminfo(): /proc/meminfo parsing, unit conversion, and key normalisation."""

    def _run(self, content=MEMINFO_SAMPLE):
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", lambda *a, **kw: io.StringIO(content)), \
             patch("time.time", return_value=3000.0):
            mem = linux_memory.Memory.__new__(linux_memory.Memory)
            return mem.GetMeminfo()

    def test_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_time_key_present(self):
        self.assertEqual(self._run()["_time"], 3000.0)

    def test_kb_converted_to_bytes(self):
        result = self._run()
        self.assertEqual(result["mem_total"], 16384000 * 1024)
        self.assertEqual(result["mem_free"], 8192000 * 1024)

    def test_field_without_unit_stored_as_int(self):
        result = self._run()
        self.assertEqual(result["huge_pages_total"], 0)
        self.assertEqual(result["huge_pages_free"], 0)

    def test_multiple_fields_present(self):
        result = self._run()
        for key in ("mem_total", "mem_free", "cached", "swap_total", "swap_free"):
            self.assertIn(key, result)

    def test_keys_are_snake_case(self):
        result = self._run()
        for key in result:
            if key == "_time":
                continue
            self.assertFalse(any(c.isupper() for c in key),
                             f"Non-snake_case key in output: {key!r}")

    def test_sreclaimable_key_correct(self):
        # SReclaimable starts with two consecutive uppercase letters — the first
        # regex pass (lowercase→uppercase) finds no boundary between S and R, so
        # a second pass is needed.  Without it the key would be "sreclaimable".
        result = self._run()
        self.assertIn("s_reclaimable", result)
        self.assertNotIn("sreclaimable", result)

    def test_sunreclaim_key_correct(self):
        result = self._run()
        self.assertIn("s_unreclaim", result)
        self.assertNotIn("sunreclaim", result)

    def test_original_keys_absent(self):
        result = self._run()
        for key in ("MemTotal", "MemFree", "HugePages_Total", "SwapTotal"):
            self.assertNotIn(key, result)

    def test_raises_when_unreadable(self):
        with patch("monitoring.gather.util.caniread", return_value=False):
            mem = linux_memory.Memory.__new__(linux_memory.Memory)
            with self.assertRaises(RuntimeError):
                mem.GetMeminfo()


class TestGetSlabinfo(unittest.TestCase):
    """Tests for GetSlabinfo(): /proc/slabinfo v2.1 parsing, header skipping, and field mapping."""

    def _run(self, content=SLABINFO_SAMPLE):
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", lambda *a, **kw: io.StringIO(content)), \
             patch("time.time", return_value=3500.0):
            mem = linux_memory.Memory.__new__(linux_memory.Memory)
            return mem.GetSlabinfo()

    def test_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_time_key_present(self):
        self.assertEqual(self._run()["_time"], 3500.0)

    def test_skips_header_line(self):
        result = self._run()
        self.assertNotIn("slabinfo - version: 2.1", result)

    def test_skips_comment_line(self):
        result = self._run()
        self.assertNotIn("# name", result)
        for key in result:
            self.assertFalse(key.startswith("#"), f"Comment line leaked: {key}")

    def test_slab_entry_parsed(self):
        result = self._run()
        self.assertIn("ext4_inode_cache", result)

    def test_slab_fields_correct(self):
        result = self._run()
        slab = result["ext4_inode_cache"]
        self.assertEqual(slab["active_objs"], 30338)
        self.assertEqual(slab["num_objs"], 44330)
        self.assertEqual(slab["objsize"], 1096)
        self.assertEqual(slab["objperslab"], 29)
        self.assertEqual(slab["pagesperslab"], 8)
        self.assertEqual(slab["limit"], 0)
        self.assertEqual(slab["batchcount"], 0)
        self.assertEqual(slab["sharedfactor"], 0)
        self.assertEqual(slab["active_slabs"], 2834)
        self.assertEqual(slab["num_slabs"], 2834)
        self.assertEqual(slab["sharedavail"], 0)

    def test_multiple_slabs(self):
        result = self._run()
        self.assertIn("kmalloc-256", result)

    def test_returns_false_when_unreadable(self):
        with patch("monitoring.gather.util.caniread", return_value=False):
            mem = linux_memory.Memory.__new__(linux_memory.Memory)
            result = mem.GetSlabinfo()
        self.assertIs(result, False)


class TestMemoryInit(unittest.TestCase):
    """Tests for Memory.__init__() — verifies both sub-dicts are populated correctly."""

    def test_stats_has_memory_and_slabs_keys(self):
        mem = linux_memory.Memory.__new__(linux_memory.Memory)
        fake_memory = {"_time": 1.0, "mem_total": 1024}
        fake_slabs = {"_time": 1.0, "kmalloc-64": {"active_objs": 10}}
        mem.GetMeminfo = MagicMock(return_value=fake_memory)
        mem.GetSlabinfo = MagicMock(return_value=fake_slabs)
        mem.__init__()
        self.assertIn("memory", mem.stats)
        self.assertIn("slabs", mem.stats)
        self.assertEqual(mem.stats["memory"], fake_memory)
        self.assertEqual(mem.stats["slabs"], fake_slabs)

    def test_slabs_false_when_unreadable(self):
        mem = linux_memory.Memory.__new__(linux_memory.Memory)
        mem.GetMeminfo = MagicMock(return_value={"_time": 1.0})
        mem.GetSlabinfo = MagicMock(return_value=False)
        mem.__init__()
        self.assertIs(mem.stats["slabs"], False)


if __name__ == "__main__":
    unittest.main()
