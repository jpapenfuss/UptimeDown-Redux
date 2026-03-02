import ctypes
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "monitoring", "gather"))
import aix_disk
from aix_disk import (
    _struct_to_dict,
    get_disk_total,
    get_disks,
    AixDisk,
    perfstat_disk_total_t,
    perfstat_disk_t,
)


class TestStructSize(unittest.TestCase):
    """Verify ctypes struct layouts match the AIX ABI sizes confirmed on-box."""

    def test_disk_total_size(self):
        self.assertEqual(ctypes.sizeof(perfstat_disk_total_t), 192)

    def test_disk_t_size(self):
        self.assertEqual(ctypes.sizeof(perfstat_disk_t), 496)


class TestStructToDict(unittest.TestCase):

    def test_skips_padding_fields(self):
        buf = perfstat_disk_total_t()
        result = _struct_to_dict(buf, perfstat_disk_total_t)
        for key in result:
            self.assertFalse(key.startswith("_pad"), f"Padding field leaked: {key}")

    def test_decodes_bytes_fields(self):
        buf = perfstat_disk_t()
        buf.name = b"hdisk0\x00"
        result = _struct_to_dict(buf, perfstat_disk_t)
        self.assertIsInstance(result["name"], str)
        self.assertEqual(result["name"], "hdisk0")

    def test_strips_null_bytes(self):
        buf = perfstat_disk_t()
        buf.name = b"hdisk1\x00\x00\x00"
        result = _struct_to_dict(buf, perfstat_disk_t)
        self.assertEqual(result["name"], "hdisk1")

    def test_integer_fields_present(self):
        buf = perfstat_disk_total_t()
        buf.xfers = 12345
        result = _struct_to_dict(buf, perfstat_disk_total_t)
        self.assertEqual(result["xfers"], 12345)

    def test_all_non_pad_fields_included(self):
        buf = perfstat_disk_total_t()
        result = _struct_to_dict(buf, perfstat_disk_total_t)
        expected = {f for f, _ in perfstat_disk_total_t._fields_
                    if not f.startswith("_pad")}
        self.assertEqual(set(result.keys()), expected)


class TestGetDiskTotal(unittest.TestCase):

    def _make_lib(self, retval=1):
        lib = MagicMock()
        lib.perfstat_disk_total.return_value = retval
        # When called, fill the buffer with known values via side_effect
        def fill_buf(name_p, buf_p, size, count):
            buf_p._obj.xfers = 9999
            buf_p._obj.size = 1024
            buf_p._obj.free = 512
            buf_p._obj.number = 10
            return retval
        lib.perfstat_disk_total.side_effect = fill_buf
        return lib

    def test_returns_false_when_call_fails(self):
        lib = MagicMock()
        lib.perfstat_disk_total.return_value = 0
        with patch("time.time", return_value=1.0):
            result = get_disk_total(lib)
        self.assertIs(result, False)

    def test_returns_false_when_call_returns_unexpected(self):
        lib = MagicMock()
        lib.perfstat_disk_total.return_value = 2
        with patch("time.time", return_value=1.0):
            result = get_disk_total(lib)
        self.assertIs(result, False)

    def test_returns_dict_on_success(self):
        lib = MagicMock()
        lib.perfstat_disk_total.return_value = 1
        with patch("time.time", return_value=1.0):
            result = get_disk_total(lib)
        self.assertIsInstance(result, dict)

    def test_time_key_present(self):
        lib = MagicMock()
        lib.perfstat_disk_total.return_value = 1
        with patch("time.time", return_value=4242.0):
            result = get_disk_total(lib)
        self.assertEqual(result["_time"], 4242.0)

    def test_field_renames(self):
        lib = MagicMock()
        lib.perfstat_disk_total.return_value = 1
        with patch("time.time", return_value=1.0):
            result = get_disk_total(lib)
        self.assertIn("ndisks", result)
        self.assertIn("size_mb", result)
        self.assertIn("free_mb", result)
        self.assertNotIn("number", result)
        self.assertNotIn("size", result)
        self.assertNotIn("free", result)

    def test_no_padding_in_result(self):
        lib = MagicMock()
        lib.perfstat_disk_total.return_value = 1
        with patch("time.time", return_value=1.0):
            result = get_disk_total(lib)
        for key in result:
            self.assertFalse(key.startswith("_pad"), f"Padding in result: {key}")


class TestGetDisks(unittest.TestCase):

    def test_returns_empty_dict_when_count_zero(self):
        lib = MagicMock()
        lib.perfstat_disk.return_value = 0
        result = get_disks(lib)
        self.assertEqual(result, {})

    def test_returns_empty_dict_when_count_negative(self):
        lib = MagicMock()
        lib.perfstat_disk.return_value = -1
        result = get_disks(lib)
        self.assertEqual(result, {})

    def test_returns_dict_on_success(self):
        # First call (count query) returns 1, second call (fetch) returns 1
        lib = MagicMock()
        call_count = [0]
        def side(id_p, buf_p, size, count):
            call_count[0] += 1
            if call_count[0] == 1:
                return 1  # one disk
            # Fill the first element of the array
            if buf_p is not None:
                buf_p[0].name = b"hdisk0\x00"
                buf_p[0].size = 2048
                buf_p[0].free = 1024
            return 1
        lib.perfstat_disk.side_effect = side
        with patch("time.time", return_value=1.0):
            result = get_disks(lib)
        self.assertIsInstance(result, dict)

    def test_field_renames_in_disk_entry(self):
        lib = MagicMock()
        call_count = [0]
        def side(id_p, buf_p, size, count):
            call_count[0] += 1
            if call_count[0] == 1:
                return 1
            if buf_p is not None:
                buf_p[0].name = b"hdisk0\x00"
                buf_p[0].size = 500
                buf_p[0].free = 100
            return 1
        lib.perfstat_disk.side_effect = side
        with patch("time.time", return_value=1.0):
            result = get_disks(lib)
        self.assertIn("hdisk0", result)
        entry = result["hdisk0"]
        self.assertIn("size_mb", entry)
        self.assertIn("free_mb", entry)
        self.assertNotIn("size", entry)
        self.assertNotIn("free", entry)

    def test_enumeration_failure_returns_empty(self):
        lib = MagicMock()
        call_count = [0]
        def side(id_p, buf_p, size, count):
            call_count[0] += 1
            if call_count[0] == 1:
                return 2       # two disks
            return -1          # enumeration fails
        lib.perfstat_disk.side_effect = side
        with patch("time.time", return_value=1.0):
            result = get_disks(lib)
        self.assertEqual(result, {})


class TestAixDiskInit(unittest.TestCase):

    def test_init_populates_disk_total_and_blockdevices(self):
        fake_lib = MagicMock()
        fake_total = {"ndisks": 5, "size_mb": 1000, "_time": 1.0}
        fake_disks = {"hdisk0": {"name": "hdisk0", "_time": 1.0}}
        with patch("aix_disk._load_lib", return_value=fake_lib), \
             patch("aix_disk.get_disk_total", return_value=fake_total), \
             patch("aix_disk.get_disks", return_value=fake_disks):
            obj = AixDisk()
        self.assertEqual(obj.disk_total, fake_total)
        self.assertEqual(obj.blockdevices, fake_disks)


if __name__ == "__main__":
    unittest.main()
