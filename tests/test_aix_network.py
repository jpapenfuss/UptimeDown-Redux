"""Tests for monitoring/gather/aix_network.py — get_interfaces() and AixNetwork class."""
import ctypes
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "monitoring", "gather"))
import aix_network
from aix_network import get_interfaces, AixNetwork, perfstat_netinterface_t


class TestStructSize(unittest.TestCase):
    """Verify perfstat_netinterface_t layout matches the on-AIX ABI size (224 bytes)."""

    def test_netinterface_size(self):
        # sizeof verified: 64+64+1+7pad + 11×8 = 224
        self.assertEqual(ctypes.sizeof(perfstat_netinterface_t), 224)


class TestGetInterfaces(unittest.TestCase):
    """Tests for get_interfaces(): two-call enumeration, field renames (ipacets→ipackets), and error paths."""

    def _make_lib(self, nifaces=2):
        """Return a mock libperfstat that returns nifaces on count call and
        fills the buffer with synthetic interface data on the enumeration call.
        """
        lib = MagicMock()

        def perfstat_side(id_p, buf_p, size, count):
            if count == 0:
                return nifaces
            # Fill the first nifaces entries.
            for i in range(min(nifaces, count)):
                entry = buf_p[i]
                entry.name        = f"en{i}".encode()
                entry.description = f"Virtual Ethernet {i}".encode()
                entry.type        = 6
                entry.mtu         = 1500
                entry.ipacets     = 1000 + i
                entry.ibytes      = 100000 + i
                entry.ierrors     = i
                entry.opackets    = 2000 + i
                entry.obytes      = 200000 + i
                entry.oerrors     = i
                entry.collisions  = 0
                entry.bitrate     = 1000000000
                entry.if_iqdrops  = i
                entry.if_arpdrops = 0
            return nifaces

        lib.perfstat_netinterface.side_effect = perfstat_side
        return lib

    def test_returns_dict(self):
        with patch("ctypes.CDLL", return_value=self._make_lib()), \
             patch("time.time", return_value=8000.0):
            result = get_interfaces()
        self.assertIsInstance(result, dict)

    def test_interface_names_present(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(2)), \
             patch("time.time", return_value=8000.0):
            result = get_interfaces()
        self.assertIn("en0", result)
        self.assertIn("en1", result)

    def test_ipackets_renamed_from_ipacets(self):
        # The libperfstat typo 'ipacets' must be renamed to 'ipackets' at output.
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_interfaces()
        self.assertIn("ipackets", result["en0"])
        self.assertNotIn("ipacets", result["en0"])

    def test_ipackets_value_correct(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_interfaces()
        self.assertEqual(result["en0"]["ipackets"], 1000)

    def test_ibytes_correct(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_interfaces()
        self.assertEqual(result["en0"]["ibytes"], 100000)

    def test_aix_specific_keys_present(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_interfaces()
        for key in ("mtu", "speed_mbps", "idrop", "if_arpdrops", "description", "type"):
            self.assertIn(key, result["en0"])

    def test_if_iqdrops_renamed_to_idrop(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_interfaces()
        self.assertIn("idrop", result["en0"])
        self.assertNotIn("if_iqdrops", result["en0"])

    def test_bitrate_renamed_to_speed_mbps(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_interfaces()
        self.assertNotIn("bitrate", result["en0"])
        self.assertIn("speed_mbps", result["en0"])

    def test_speed_mbps_converted_from_bps(self):
        # bitrate in mock is 1000000000 bps → 1000 Mbps
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=1.0):
            result = get_interfaces()
        self.assertEqual(result["en0"]["speed_mbps"], 1000)

    def test_time_key_absent(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(1)), \
             patch("time.time", return_value=8000.0):
            result = get_interfaces()
        self.assertNotIn("_time", result["en0"])

    def test_all_interfaces_have_no_time_key(self):
        with patch("ctypes.CDLL", return_value=self._make_lib(2)), \
             patch("time.time", return_value=8000.0):
            result = get_interfaces()
        self.assertNotIn("_time", result["en0"])
        self.assertNotIn("_time", result["en1"])

    def test_returns_empty_dict_when_lib_missing(self):
        with patch("ctypes.CDLL", side_effect=OSError("no libperfstat")):
            result = get_interfaces()
        self.assertEqual(result, {})

    def test_returns_empty_dict_when_count_query_fails(self):
        lib = MagicMock()
        lib.perfstat_netinterface.return_value = 0
        with patch("ctypes.CDLL", return_value=lib):
            result = get_interfaces()
        self.assertEqual(result, {})

    def test_returns_empty_dict_when_enumeration_fails(self):
        lib = MagicMock()
        call_count = [0]

        def side(id_p, buf_p, size, count):
            call_count[0] += 1
            if count == 0:
                return 2     # claim 2 interfaces
            return -1        # enumeration fails

        lib.perfstat_netinterface.side_effect = side
        with patch("ctypes.CDLL", return_value=lib):
            result = get_interfaces()
        self.assertEqual(result, {})


class TestAixNetwork(unittest.TestCase):
    """Tests for AixNetwork class: init wiring, update_values() refresh, and get_interfaces() delegation."""

    def test_init_populates_interfaces(self):
        fake = {"en0": {"ibytes": 100}}
        with patch("aix_network.get_interfaces", return_value=fake):
            obj = AixNetwork()
        self.assertEqual(obj.interfaces, fake)

    def test_update_values_refreshes(self):
        obj = AixNetwork.__new__(AixNetwork)
        new_data = {"en0": {"ibytes": 999}}
        with patch("aix_network.get_interfaces", return_value=new_data):
            obj.update_values()
        self.assertEqual(obj.interfaces, new_data)

    def test_update_values_called_on_init(self):
        with patch("aix_network.get_interfaces", return_value={}) as mock_get:
            obj = AixNetwork()
        # update_values is the only code path that calls get_interfaces;
        # if it was called, update_values was called from __init__.
        mock_get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
