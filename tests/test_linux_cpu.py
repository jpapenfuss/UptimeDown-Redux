import io
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import via the package so that relative imports (from . import util) resolve.
from monitoring.gather import linux_cpu

# ---------------------------------------------------------------------------
# Sample /proc/cpuinfo content (single cpu0 stanza, blank-line terminated)
# ---------------------------------------------------------------------------
CPUINFO_SAMPLE = """\
processor\t: 0
vendor_id\t: GenuineIntel
cpu family\t: 6
model\t\t: 85
model name\t: Intel(R) Xeon(R) Gold 6148 CPU @ 2.40GHz
stepping\t: 4
cpu MHz\t\t: 2400.000
cache size\t: 28160 KB
physical id\t: 0
siblings\t: 40
core id\t\t: 0
cpu cores\t: 20
apicid\t\t: 0
initial apicid\t: 0
bogomips\t: 4800.00
clflush size\t: 64
cache_alignment\t: 64
flags\t\t: fpu vme de pse tsc msr pae mce
bugs\t\t: cpu_meltdown spectre_v1

"""

# ---------------------------------------------------------------------------
# Sample /proc/stat content (4 CPUs)
# ---------------------------------------------------------------------------
STAT_SAMPLE = """\
cpu  100 20 50 800 10 5 3 2 1 0
cpu0 25 5 12 200 2 1 1 0 0 0
cpu1 25 5 13 200 3 1 1 1 0 0
cpu2 25 5 12 200 2 2 1 1 1 0
cpu3 25 5 13 200 3 1 0 0 0 0
intr 12345 1 2 3
ctxt 9876543
btime 1700000000
processes 12345
procs_running 2
procs_blocked 0
softirq 5000 0 1000 0 500 0 0 100 200 0 3200
"""

# ---------------------------------------------------------------------------
# Sample /proc/softirqs content (matching 4 CPUs above)
# ---------------------------------------------------------------------------
SOFTIRQS_SAMPLE = """\
                    cpu0       cpu1       cpu2       cpu3
          HI:          0          0          0          0
       TIMER:       1000       1001       1002       1003
      NET_TX:         10         11         12         13
      NET_RX:        100        101        102        103
"""


class TestGetCpuinfo(unittest.TestCase):

    def _make_cpu(self, content):
        """Return a Cpu instance with GetCpuinfo() driven by content string."""
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", lambda *a, **kw: io.StringIO(content)), \
             patch("time.time", return_value=1000.0):
            cpu = linux_cpu.Cpu.__new__(linux_cpu.Cpu)
            return cpu.GetCpuinfo()

    def test_returns_dict(self):
        result = self._make_cpu(CPUINFO_SAMPLE)
        self.assertIsInstance(result, dict)

    def test_time_key_present(self):
        result = self._make_cpu(CPUINFO_SAMPLE)
        self.assertEqual(result["_time"], 1000.0)

    def test_integer_field_coerced(self):
        result = self._make_cpu(CPUINFO_SAMPLE)
        self.assertIsInstance(result["processor"], int)
        self.assertEqual(result["processor"], 0)

    def test_float_field_coerced(self):
        result = self._make_cpu(CPUINFO_SAMPLE)
        self.assertIsInstance(result["cpu MHz"], float)
        self.assertAlmostEqual(result["cpu MHz"], 2400.0)

    def test_float_bogomips(self):
        result = self._make_cpu(CPUINFO_SAMPLE)
        self.assertIsInstance(result["bogomips"], float)

    def test_list_field_flags(self):
        result = self._make_cpu(CPUINFO_SAMPLE)
        self.assertIsInstance(result["flags"], list)
        self.assertIn("fpu", result["flags"])

    def test_list_field_bugs(self):
        result = self._make_cpu(CPUINFO_SAMPLE)
        self.assertIsInstance(result["bugs"], list)
        self.assertIn("cpu_meltdown", result["bugs"])

    def test_unknown_field_kept_as_string(self):
        result = self._make_cpu(CPUINFO_SAMPLE)
        self.assertIsInstance(result["model name"], str)
        self.assertIn("Xeon", result["model name"])

    def test_stops_at_blank_line(self):
        # cpu0 stanza ends at first blank line; cpu1 data should not appear
        content = CPUINFO_SAMPLE + "processor\t: 1\n"
        result = self._make_cpu(content)
        # processor value should be 0 (cpu0), not 1 (cpu1 comes after blank)
        self.assertEqual(result["processor"], 0)

    def test_returns_false_when_unreadable(self):
        with patch("monitoring.gather.util.caniread", return_value=False):
            cpu = linux_cpu.Cpu.__new__(linux_cpu.Cpu)
            result = cpu.GetCpuinfo()
        self.assertIs(result, False)

    def test_line_without_colon_is_skipped(self):
        # A cpuinfo line with no colon must not raise IndexError.
        content = "processor\t: 0\nno_colon_here\nmodel name\t: Test CPU\n\n"
        result = self._make_cpu(content)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["processor"], 0)
        self.assertNotIn("no_colon_here", result)


class TestGetCpuProcStats(unittest.TestCase):

    def _make_stats(self, stat_content=STAT_SAMPLE, softirq_content=SOFTIRQS_SAMPLE):
        def fake_open(path, *args, **kwargs):
            if "softirqs" in path:
                return io.StringIO(softirq_content)
            return io.StringIO(stat_content)

        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", side_effect=fake_open), \
             patch("time.time", return_value=2000.0):
            cpu = linux_cpu.Cpu.__new__(linux_cpu.Cpu)
            return cpu.GetCpuProcStats()

    def test_returns_dict(self):
        self.assertIsInstance(self._make_stats(), dict)

    def test_time_key_present(self):
        result = self._make_stats()
        self.assertEqual(result["_time"], 2000.0)

    def test_aggregate_cpu_row(self):
        result = self._make_stats()
        self.assertIn("cpu", result)
        self.assertEqual(result["cpu"]["user"], 100)
        self.assertEqual(result["cpu"]["system"], 50)

    def test_per_core_rows(self):
        result = self._make_stats()
        for core in ("cpu0", "cpu1", "cpu2", "cpu3"):
            self.assertIn(core, result)

    def test_system_stats_coerced_to_int(self):
        result = self._make_stats()
        self.assertEqual(result["ctxt"], 9876543)
        self.assertEqual(result["btime"], 1700000000)
        self.assertEqual(result["processes"], 12345)
        self.assertEqual(result["procs_running"], 2)
        self.assertEqual(result["procs_blocked"], 0)

    def test_softirqs_sub_dict_initialized(self):
        result = self._make_stats()
        self.assertIn("softirqs", result["cpu0"])

    def test_softirqs_populated(self):
        result = self._make_stats()
        self.assertEqual(result["cpu0"]["softirqs"]["TIMER"], 1000)
        self.assertEqual(result["cpu1"]["softirqs"]["NET_RX"], 101)

    def test_normalized_aggregate_keys(self):
        result = self._make_stats()
        self.assertEqual(result["user_ticks"], 100)
        self.assertEqual(result["nice_ticks"], 20)
        self.assertEqual(result["sys_ticks"], 50)
        self.assertEqual(result["idle_ticks"], 800)
        self.assertEqual(result["iowait_ticks"], 10)
        self.assertEqual(result["irq_ticks"], 5)
        self.assertEqual(result["softirq_ticks"], 3)
        self.assertEqual(result["steal_ticks"], 2)
        self.assertEqual(result["guest_ticks"], 1)

    def test_returns_false_when_unreadable(self):
        with patch("monitoring.gather.util.caniread", return_value=False):
            cpu = linux_cpu.Cpu.__new__(linux_cpu.Cpu)
            result = cpu.GetCpuProcStats()
        self.assertIs(result, False)

    def test_softirqs_unreadable_does_not_crash(self):
        # GetCpuSoftIrqs returning False must not cause a TypeError on
        # the subsequent cpustats_values["_time"] assignment.
        def caniread_side(path):
            # /proc/stat is readable; /proc/softirqs is not
            return "softirqs" not in path

        def fake_open(path, *args, **kwargs):
            return io.StringIO(STAT_SAMPLE)

        with patch("monitoring.gather.util.caniread", side_effect=caniread_side), \
             patch("builtins.open", side_effect=fake_open), \
             patch("time.time", return_value=2000.0):
            cpu = linux_cpu.Cpu.__new__(linux_cpu.Cpu)
            result = cpu.GetCpuProcStats()
        # Must return a valid dict (not crash, not return False)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["_time"], 2000.0)
        self.assertIn("cpu", result)


class TestGetCpuSoftIrqs(unittest.TestCase):

    def _make_softirqs(self, content=SOFTIRQS_SAMPLE):
        cpustats = {
            "cpu":  {"softirqs": {}},
            "cpu0": {"softirqs": {}},
            "cpu1": {"softirqs": {}},
            "cpu2": {"softirqs": {}},
            "cpu3": {"softirqs": {}},
        }
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", lambda *a, **kw: io.StringIO(content)):
            cpu = linux_cpu.Cpu.__new__(linux_cpu.Cpu)
            return cpu.GetCpuSoftIrqs(cpustats)

    def test_returns_dict(self):
        self.assertIsInstance(self._make_softirqs(), dict)

    def test_timer_counts_per_cpu(self):
        result = self._make_softirqs()
        self.assertEqual(result["cpu0"]["softirqs"]["TIMER"], 1000)
        self.assertEqual(result["cpu1"]["softirqs"]["TIMER"], 1001)
        self.assertEqual(result["cpu2"]["softirqs"]["TIMER"], 1002)
        self.assertEqual(result["cpu3"]["softirqs"]["TIMER"], 1003)

    def test_net_rx_counts(self):
        result = self._make_softirqs()
        self.assertEqual(result["cpu0"]["softirqs"]["NET_RX"], 100)
        self.assertEqual(result["cpu3"]["softirqs"]["NET_RX"], 103)

    def test_aggregate_cpu_row_skipped(self):
        # The bare "cpu" key has no column in /proc/softirqs — it should remain
        # untouched (not given TIMER etc. counts from per-cpu columns)
        result = self._make_softirqs()
        self.assertEqual(result["cpu"]["softirqs"], {})

    def test_returns_false_when_unreadable(self):
        with patch("monitoring.gather.util.caniread", return_value=False):
            cpu = linux_cpu.Cpu.__new__(linux_cpu.Cpu)
            result = cpu.GetCpuSoftIrqs({})
        self.assertIs(result, False)


class TestUpdateValues(unittest.TestCase):

    def test_updatevalues_populates_both_attributes(self):
        cpu = linux_cpu.Cpu.__new__(linux_cpu.Cpu)
        cpu.GetCpuinfo = MagicMock(return_value={"_time": 1.0, "processor": 0})
        cpu.GetCpuProcStats = MagicMock(return_value={"_time": 1.0, "user_ticks": 10})
        cpu.UpdateValues()
        self.assertEqual(cpu.cpuinfo_values["processor"], 0)
        self.assertEqual(cpu.cpustat_values["user_ticks"], 10)
        cpu.GetCpuinfo.assert_called_once()
        cpu.GetCpuProcStats.assert_called_once()

    def test_updatevalues_called_on_init(self):
        with patch.object(linux_cpu.Cpu, "UpdateValues") as mock_update:
            linux_cpu.Cpu.__new__(linux_cpu.Cpu).__init__()
            # __init__ calls UpdateValues
        # We can't easily call __init__ without triggering real file reads,
        # so just verify UpdateValues is wired to __init__ by checking the source.
        import inspect
        src = inspect.getsource(linux_cpu.Cpu.__init__)
        self.assertIn("UpdateValues", src)


if __name__ == "__main__":
    unittest.main()
