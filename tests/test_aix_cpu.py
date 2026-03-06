"""Tests for monitoring/gather/aix_cpu.py — get_cpu_total(), get_cpus(), and AixCpu class."""
import ctypes
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "monitoring", "gather"))
import aix_cpu
from aix_cpu import get_cpu_total, get_cpus, AixCpu, perfstat_cpu_total_t, perfstat_cpu_t


class TestStructSize(unittest.TestCase):
    """Verify that the ctypes struct layout matches the on-AIX ABI size (696 bytes)."""

    def test_cpu_total_size(self):
        self.assertEqual(ctypes.sizeof(perfstat_cpu_total_t), 696)


class TestGetCpuTotal(unittest.TestCase):
    """Tests for get_cpu_total(): perfstat_cpu_total() call, field normalisation, and error paths."""

    def _make_lib(self, retval=1):
        lib = MagicMock()
        lib.perfstat_cpu_total.return_value = retval
        return lib

    def test_returns_false_when_call_fails(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(0)):
            result = get_cpu_total()
        self.assertIs(result, False)

    def test_returns_false_when_call_returns_unexpected(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(2)):
            result = get_cpu_total()
        self.assertIs(result, False)

    def test_returns_dict_on_success(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        self.assertIsInstance(result, dict)

    def test_time_key_absent(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)), \
             patch("time.time", return_value=8888.0):
            result = get_cpu_total()
        self.assertNotIn("_time", result)

    def test_no_padding_fields_in_result(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        for key in result:
            self.assertFalse(key.startswith("_pad"), f"Padding field leaked: {key}")

    def test_description_decoded_to_str(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        self.assertIsInstance(result["description"], str)

    def test_normalized_tick_keys(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        for key in ("user_ticks", "sys_ticks", "idle_ticks", "iowait_ticks"):
            self.assertIn(key, result)

    def test_old_tick_keys_absent(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        for key in ("user", "sys", "idle", "wait"):
            self.assertNotIn(key, result, f"Old key still present: {key}")

    def test_processor_hz_renamed(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        self.assertIn("processor_hz", result)
        self.assertNotIn("processorHZ", result)

    def test_loadavg_unpacked_to_three_keys(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        self.assertIn("loadavg_1", result)
        self.assertIn("loadavg_5", result)
        self.assertIn("loadavg_15", result)
        self.assertNotIn("loadavg", result)

    def test_purr_spurr_fields_present(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        for key in ("idle_donated_purr", "busy_stolen_purr", "puser_spurr"):
            self.assertIn(key, result)

    def test_pswitch_renamed_to_ctxt(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        self.assertIn("ctxt", result)
        self.assertNotIn("pswitch", result)

    def test_ctxt_value_from_struct(self):
        lib = MagicMock()
        def fill(name_p, buf_p, size, count):
            buf_p._obj.pswitch = 99999
            return 1
        lib.perfstat_cpu_total.side_effect = fill
        with patch("aix_cpu._load_libperfstat", return_value=lib), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        self.assertEqual(result["ctxt"], 99999)

    def test_loadavg_converted_to_float(self):
        """loadavg values must be divided by 65536 at collection time."""
        lib = MagicMock()
        def fill(name_p, buf_p, size, count):
            buf_p._obj.loadavg[0] = 131072   # 2.0
            buf_p._obj.loadavg[1] = 98304    # 1.5
            buf_p._obj.loadavg[2] = 65536    # 1.0
            return 1
        lib.perfstat_cpu_total.side_effect = fill
        with patch("aix_cpu._load_libperfstat", return_value=lib), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        self.assertAlmostEqual(result["loadavg_1"],  2.0)
        self.assertAlmostEqual(result["loadavg_5"],  1.5)
        self.assertAlmostEqual(result["loadavg_15"], 1.0)

    def test_tick_values_from_struct(self):
        """Verify normalization correctly reads struct fields."""
        lib = MagicMock()
        def fill(name_p, buf_p, size, count):
            buf_p._obj.user = 100
            buf_p._obj.sys = 50
            buf_p._obj.idle = 800
            buf_p._obj.wait = 10
            buf_p._obj.processorHZ = 3000000000
            return 1
        lib.perfstat_cpu_total.side_effect = fill
        with patch("aix_cpu._load_libperfstat", return_value=lib), \
             patch("time.time", return_value=1.0):
            result = get_cpu_total()
        self.assertEqual(result["user_ticks"], 100)
        self.assertEqual(result["sys_ticks"], 50)
        self.assertEqual(result["idle_ticks"], 800)
        self.assertEqual(result["iowait_ticks"], 10)
        self.assertEqual(result["processor_hz"], 3000000000)


class TestGetCpus(unittest.TestCase):
    """Tests for get_cpus(): per-CPU enumeration and tick field renames."""

    def _make_lib(self, ncpus=2):
        lib = MagicMock()
        def side(id_p, buf_p, size, count):
            if count == 0:
                return ncpus
            for i in range(min(ncpus, count)):
                entry = buf_p[i]
                entry.name = f"cpu{i}".encode()
                entry.user = 100 + i
                entry.sys = 50 + i
                entry.idle = 800 + i
                entry.wait = 10 + i
                entry.state = b'\x01'
            return ncpus
        lib.perfstat_cpu.side_effect = side
        return lib

    def test_per_cpu_tick_fields_renamed(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)):
            result = get_cpus()
        cpu = result["cpu0"]
        for key in ("user_ticks", "sys_ticks", "idle_ticks", "iowait_ticks"):
            self.assertIn(key, cpu, f"Missing renamed key: {key}")

    def test_per_cpu_old_tick_keys_absent(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)):
            result = get_cpus()
        cpu = result["cpu0"]
        for key in ("user", "sys", "idle", "wait"):
            self.assertNotIn(key, cpu, f"Old key still present: {key}")

    def test_per_cpu_tick_values_correct(self):
        with patch("aix_cpu._load_libperfstat", return_value=self._make_lib(1)):
            result = get_cpus()
        cpu = result["cpu0"]
        self.assertEqual(cpu["user_ticks"], 100)
        self.assertEqual(cpu["sys_ticks"], 50)
        self.assertEqual(cpu["idle_ticks"], 800)
        self.assertEqual(cpu["iowait_ticks"], 10)

    def test_returns_false_on_failure(self):
        lib = MagicMock()
        lib.perfstat_cpu.return_value = 0
        with patch("aix_cpu._load_libperfstat", return_value=lib):
            result = get_cpus()
        self.assertIs(result, False)


class TestAixCpu(unittest.TestCase):
    """Tests for AixCpu class construction and UpdateValues() refresh behaviour."""

    def test_init_populates_cpustat_values(self):
        fake = {"user_ticks": 100}
        with patch("aix_cpu.get_cpu_total", return_value=fake), \
             patch("aix_cpu.get_cpus", return_value={}):
            obj = AixCpu()
        self.assertEqual(obj.cpustat_values, fake)

    def test_update_values_refreshes(self):
        obj = AixCpu.__new__(AixCpu)
        obj.cpustat_values = {}
        new_data = {"user_ticks": 999}
        with patch("aix_cpu.get_cpu_total", return_value=new_data), \
             patch("aix_cpu.get_cpus", return_value={}):
            obj.UpdateValues()
        self.assertEqual(obj.cpustat_values["user_ticks"], 999)

    def test_update_values_called_on_init(self):
        with patch.object(AixCpu, "UpdateValues") as mock_update:
            obj = AixCpu.__new__(AixCpu)
            obj.__init__()
        mock_update.assert_called_once()


if __name__ == "__main__":
    unittest.main()
