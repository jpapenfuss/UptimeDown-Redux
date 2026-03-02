import ctypes
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "monitoring", "gather"))
import aix_memory
from aix_memory import get_memory_total, AixMemory, perfstat_memory_total_t, PAGE_SIZE


class TestStructSize(unittest.TestCase):

    def test_memory_total_size(self):
        self.assertEqual(ctypes.sizeof(perfstat_memory_total_t), 176)


class TestGetMemoryTotal(unittest.TestCase):

    def _make_lib(self, retval=1):
        lib = MagicMock()
        lib.perfstat_memory_total.return_value = retval
        return lib

    def test_returns_false_when_lib_missing(self):
        with patch("ctypes.CDLL", side_effect=OSError("no libperfstat")):
            result = get_memory_total()
        self.assertIs(result, False)

    def test_returns_false_when_call_fails(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(0)):
            result = get_memory_total()
        self.assertIs(result, False)

    def test_returns_false_when_call_returns_unexpected(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(2)):
            result = get_memory_total()
        self.assertIs(result, False)

    def test_returns_dict_on_success(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_memory_total()
        self.assertIsInstance(result, dict)

    def test_time_key_present(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=6666.0):
            result = get_memory_total()
        self.assertEqual(result["_time"], 6666.0)

    def test_normalized_keys_present(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_memory_total()
        for key in ("mem_total", "mem_free", "mem_cached", "swap_total", "swap_free"):
            self.assertIn(key, result)

    def test_aix_specific_keys_present(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_memory_total()
        for key in ("virt_total", "virt_active", "real_pinned", "real_inuse",
                    "real_system", "real_user", "real_process", "pgsp_rsvd"):
            self.assertIn(key, result)

    def test_counter_keys_present(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_memory_total()
        for key in ("pgbad", "pgexct", "pgins", "pgouts", "pgspins", "pgspouts",
                    "scans", "cycles", "pgsteals"):
            self.assertIn(key, result)

    def test_page_values_converted_to_bytes(self):
        lib = MagicMock()
        def fill(name_p, buf_p, size, count):
            buf_p._obj.real_total = 100
            buf_p._obj.real_free  = 40
            buf_p._obj.numperm    = 10
            buf_p._obj.pgsp_total = 20
            buf_p._obj.pgsp_free  = 15
            return 1
        lib.perfstat_memory_total.side_effect = fill
        with patch("ctypes.CDLL", return_value=lib), \
             patch("time.time", return_value=1.0):
            result = get_memory_total()
        self.assertEqual(result["mem_total"],  100 * PAGE_SIZE)
        self.assertEqual(result["mem_free"],    40 * PAGE_SIZE)
        self.assertEqual(result["mem_cached"],  10 * PAGE_SIZE)
        self.assertEqual(result["swap_total"],  20 * PAGE_SIZE)
        self.assertEqual(result["swap_free"],   15 * PAGE_SIZE)

    def test_counters_not_multiplied(self):
        lib = MagicMock()
        def fill(name_p, buf_p, size, count):
            buf_p._obj.pgexct = 999
            buf_p._obj.pgins  = 42
            return 1
        lib.perfstat_memory_total.side_effect = fill
        with patch("ctypes.CDLL", return_value=lib), \
             patch("time.time", return_value=1.0):
            result = get_memory_total()
        self.assertEqual(result["pgexct"], 999)
        self.assertEqual(result["pgins"],   42)

    def test_page_size_constant(self):
        self.assertEqual(PAGE_SIZE, 4096)


class TestAixMemory(unittest.TestCase):

    def test_init_creates_stats_with_memory_and_slabs(self):
        fake = {"mem_total": 1024 * PAGE_SIZE, "_time": 1.0}
        with patch("aix_memory.get_memory_total", return_value=fake):
            obj = AixMemory()
        self.assertIn("memory", obj.stats)
        self.assertIn("slabs", obj.stats)

    def test_slabs_always_none(self):
        with patch("aix_memory.get_memory_total", return_value={"_time": 1.0}):
            obj = AixMemory()
        self.assertIsNone(obj.stats["slabs"])

    def test_update_values_refreshes_memory(self):
        obj = AixMemory.__new__(AixMemory)
        obj.stats = {}
        new_data = {"mem_total": 999 * PAGE_SIZE, "_time": 2.0}
        with patch("aix_memory.get_memory_total", return_value=new_data):
            obj.UpdateValues()
        self.assertEqual(obj.stats["memory"], new_data)
        self.assertIsNone(obj.stats["slabs"])

    def test_update_values_called_on_init(self):
        with patch.object(AixMemory, "UpdateValues") as mock_update:
            obj = AixMemory.__new__(AixMemory)
            obj.__init__()
        mock_update.assert_called_once()


if __name__ == "__main__":
    unittest.main()
