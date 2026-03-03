"""Tests for monitoring/gather/linux_network.py — Network.get_interfaces() /proc/net/dev parsing."""
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from monitoring.gather import linux_network
from monitoring.gather.linux_network import Network, NET_DEV_KEYS

# ---------------------------------------------------------------------------
# Sample /proc/net/dev content
# ---------------------------------------------------------------------------
NET_DEV_SAMPLE = """\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:  908188    5596    0    0    0     0          0         0   908188    5596    0    0    0     0       0          0
  eth0:  614530    7085    2    3    4     5          6         1  1234567   12345    7    8    9    10      11         12
"""


class TestGetInterfaces(unittest.TestCase):
    """Tests for get_interfaces(): /proc/net/dev parsing, counter field mapping, and error handling."""

    def _run(self, content=NET_DEV_SAMPLE):
        with patch("monitoring.gather.util.caniread", return_value=True), \
             patch("builtins.open", lambda *a, **kw: io.StringIO(content)), \
             patch("time.time", return_value=7000.0):
            n = Network.__new__(Network)
            return n.get_interfaces()

    def test_returns_dict(self):
        self.assertIsInstance(self._run(), dict)

    def test_lo_present(self):
        self.assertIn("lo", self._run())

    def test_eth0_present(self):
        self.assertIn("eth0", self._run())

    def test_ibytes_correct(self):
        result = self._run()
        self.assertEqual(result["eth0"]["ibytes"], 614530)
        self.assertEqual(result["lo"]["ibytes"], 908188)

    def test_obytes_correct(self):
        self.assertEqual(self._run()["eth0"]["obytes"], 1234567)

    def test_ipackets_correct(self):
        self.assertEqual(self._run()["eth0"]["ipackets"], 7085)

    def test_opackets_correct(self):
        self.assertEqual(self._run()["eth0"]["opackets"], 12345)

    def test_ierrors_correct(self):
        self.assertEqual(self._run()["eth0"]["ierrors"], 2)

    def test_oerrors_correct(self):
        self.assertEqual(self._run()["eth0"]["oerrors"], 7)

    def test_idrop_correct(self):
        self.assertEqual(self._run()["eth0"]["idrop"], 3)

    def test_collisions_correct(self):
        self.assertEqual(self._run()["eth0"]["collisions"], 10)

    def test_all_keys_present(self):
        result = self._run()
        for key in NET_DEV_KEYS:
            self.assertIn(key, result["eth0"])

    def test_time_key_absent(self):
        result = self._run()
        self.assertNotIn("_time", result["eth0"])
        self.assertNotIn("_time", result["lo"])

    def test_all_values_are_int(self):
        result = self._run()
        for key in NET_DEV_KEYS:
            self.assertIsInstance(result["eth0"][key], int)

    def test_returns_false_when_unreadable(self):
        with patch("monitoring.gather.util.caniread", return_value=False):
            n = Network.__new__(Network)
            result = n.get_interfaces()
        self.assertIs(result, False)

    def test_empty_file_returns_empty_dict(self):
        # Two header lines only, no data.
        content = "Inter-|...\n face |...\n"
        result = self._run(content)
        self.assertEqual(result, {})


class TestNetworkInit(unittest.TestCase):
    """Tests for Network.__init__(): verifies get_interfaces() is called on construction."""

    def test_init_populates_interfaces(self):
        fake = {"eth0": {"ibytes": 100}}
        n = Network.__new__(Network)
        with patch.object(n, "get_interfaces", return_value=fake):
            n.__init__()
        self.assertEqual(n.interfaces, fake)


if __name__ == "__main__":
    unittest.main()
