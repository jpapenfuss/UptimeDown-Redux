"""Test suite for receiver JSON validation."""

import json
import unittest
from receiver.validate import (
    validate_envelope,
    validate_cpustats,
    validate_cpuinfo,
    validate_cpus,
    validate_cloud,
    validate_memory,
    validate_disks,
    validate_disk_total,
    validate_filesystems,
    validate_network,
    validate_payload,
)


class TestValidateEnvelope(unittest.TestCase):
    """Tests for envelope validation."""

    def test_01_valid_envelope(self):
        """Test: Valid envelope with all required keys."""
        data = {
            "system_id": "test-system-001",
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertEqual(errors, [])

    def test_02_missing_system_id(self):
        """Test: Missing system_id key."""
        data = {
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("system_id" in e for e in errors))

    def test_03_system_id_is_int(self):
        """Test: system_id is int instead of str."""
        data = {
            "system_id": 12345,
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("system_id" in e and "str" in e for e in errors))

    def test_04_system_id_empty(self):
        """Test: system_id is empty string."""
        data = {
            "system_id": "",
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("system_id" in e and "empty" in e for e in errors))

    def test_05_system_id_with_special_chars(self):
        """Test: system_id with SQL injection attempt."""
        data = {
            "system_id": "'; DROP TABLE hosts;--",
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("alphanumeric" in e for e in errors))

    def test_06_system_id_too_long(self):
        """Test: system_id exceeds 64 chars."""
        data = {
            "system_id": "a" * 65,
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("64 characters" in e for e in errors))

    def test_07_collected_at_is_string(self):
        """Test: collected_at is string."""
        data = {
            "system_id": "test-001",
            "collected_at": "2023-11-15",
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("collected_at" in e and ("int" in e or "float" in e) for e in errors))

    def test_08_collected_at_is_negative(self):
        """Test: collected_at is negative."""
        data = {
            "system_id": "test-001",
            "collected_at": -100,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("collected_at" in e and "positive" in e for e in errors))

    def test_09_collected_at_year_1970(self):
        """Test: collected_at is before year 2020."""
        data = {
            "system_id": "test-001",
            "collected_at": 100000000,  # ~1973
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("2020" in e for e in errors))

    def test_10_collected_at_year_2050(self):
        """Test: collected_at is after year 2033."""
        data = {
            "system_id": "test-001",
            "collected_at": 2500000000,  # ~2049
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("2033" in e for e in errors))

    def test_11_unknown_top_level_key(self):
        """Test: Unknown top-level key 'malicious_key'."""
        data = {
            "system_id": "test-001",
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            "malicious_key": "evil",
        }
        errors = validate_envelope(data)
        self.assertTrue(any("Unknown" in e and "malicious_key" in e for e in errors))

    def test_12_collection_errors_is_list(self):
        """Test: collection_errors is list instead of dict."""
        data = {
            "system_id": "test-001",
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": [],
            "cloud": False,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("collection_errors" in e and "dict" in e for e in errors))

    def test_13_missing_cloud_key(self):
        """Test: Missing cloud key (required, always present)."""
        data = {
            "system_id": "test-001",
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
        }
        errors = validate_envelope(data)
        self.assertTrue(any("cloud" in e for e in errors))

    def test_14_cloud_is_none(self):
        """Test: cloud is None."""
        data = {
            "system_id": "test-001",
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": None,
        }
        errors = validate_envelope(data)
        self.assertTrue(any("cloud" in e for e in errors))

    def test_15_payload_is_list(self):
        """Test: Payload is a list instead of dict."""
        errors = validate_envelope([])
        self.assertTrue(any("dict" in e for e in errors))


class TestValidateCpustats(unittest.TestCase):
    """Tests for CPU stats validation."""

    def test_01_valid_linux_cpustats(self):
        """Test: Valid Linux cpustats with per-CPU dicts."""
        data = {
            "user_ticks": 1000,
            "sys_ticks": 500,
            "loadavg_1": 1.5,
            "loadavg_5": 1.2,
            "loadavg_15": 1.0,
            "cpu0": {
                "user_ticks": 500,
                "sys_ticks": 250,
                "idle_ticks": 10000,
                "softirqs": {"HI": 10, "TIMER": 50},
            },
        }
        errors = validate_cpustats(data)
        self.assertEqual(errors, [])

    def test_02_per_cpu_tick_is_string(self):
        """Test: Per-CPU tick field is string."""
        data = {
            "user_ticks": 1000,
            "cpu0": {"user_ticks": "1234"},
        }
        errors = validate_cpustats(data)
        self.assertTrue(any("str" in e for e in errors))

    def test_03_per_cpu_tick_is_negative(self):
        """Test: Per-CPU tick field is negative."""
        data = {
            "user_ticks": 1000,
            "cpu0": {"user_ticks": -100},
        }
        errors = validate_cpustats(data)
        self.assertTrue(any("non-negative" in e for e in errors))

    def test_04_per_cpu_tick_is_bool(self):
        """Test: Per-CPU tick field is boolean."""
        data = {
            "user_ticks": 1000,
            "cpu0": {"user_ticks": True},
        }
        errors = validate_cpustats(data)
        self.assertTrue(any("int" in e or "bool" in e for e in errors))

    def test_05_aggregate_user_ticks_is_float(self):
        """Test: Aggregate user_ticks is float instead of int."""
        data = {"user_ticks": 1.5}
        errors = validate_cpustats(data)
        self.assertTrue(any("int" in e for e in errors))

    def test_06_loadavg_is_string(self):
        """Test: loadavg_1 is string."""
        data = {"loadavg_1": "1.5"}
        errors = validate_cpustats(data)
        self.assertTrue(any("loadavg_1" in e for e in errors))

    def test_07_loadavg_is_negative(self):
        """Test: loadavg_1 is negative."""
        data = {"loadavg_1": -1.5}
        errors = validate_cpustats(data)
        self.assertTrue(any("non-negative" in e for e in errors))

    def test_08_per_cpu_value_is_float(self):
        """Test: Per-CPU field is float instead of int."""
        data = {
            "user_ticks": 1000,
            "cpu0": {"user_ticks": 1.5},
        }
        errors = validate_cpustats(data)
        self.assertTrue(any("int" in e for e in errors))

    def test_09_valid_aix_cpustats(self):
        """Test: Valid AIX cpustats (no per-CPU sub-dicts, all aggregate)."""
        data = {
            "user_ticks": 1000,
            "sys_ticks": 500,
            "loadavg_1": 1.5,
            "description": "PowerPC_POWER8",
            "ncpus_enumerated": 4,
            "syscall": 50000,
            "processor_hz": 3500000000,
        }
        errors = validate_cpustats(data)
        self.assertEqual(errors, [])

    def test_10_per_cpu_softirqs_value_is_string(self):
        """Test: Per-CPU softirqs value is string."""
        data = {
            "user_ticks": 1000,
            "cpu0": {"softirqs": {"HI": "10"}},
        }
        errors = validate_cpustats(data)
        self.assertTrue(any("int" in e for e in errors))

    def test_11_per_cpu_softirqs_is_list(self):
        """Test: Per-CPU softirqs is list instead of dict."""
        data = {
            "user_ticks": 1000,
            "cpu0": {"softirqs": [1, 2, 3]},
        }
        errors = validate_cpustats(data)
        self.assertTrue(any("dict" in e for e in errors))


class TestValidateCpuinfo(unittest.TestCase):
    """Tests for CPU info validation."""

    def test_01_valid_cpuinfo(self):
        """Test: Valid cpuinfo with known fields."""
        data = {
            "processor": 0,
            "vendor_id": "GenuineIntel",
            "cpu family": 6,
            "model": 158,
            "stepping": 10,
            "cpu MHz": 3600.0,
            "cache size": "8192 KB",
            "flags": ["fpu", "vme", "de"],
            "bugs": [],
        }
        errors = validate_cpuinfo(data)
        self.assertEqual(errors, [])

    def test_02_unknown_field_is_accepted(self):
        """Test: Unknown field is accepted."""
        data = {
            "processor": 0,
            "vendor_id": "GenuineIntel",
            "unknown_future_field": "anything",
        }
        errors = validate_cpuinfo(data)
        self.assertEqual(errors, [])


class TestValidateCpus(unittest.TestCase):
    """Tests for per-CPU enumeration validation."""

    def test_01_valid_aix_cpus(self):
        """Test: Valid AIX per-CPU dict."""
        data = {
            "cpu0": {
                "user_ticks": 1000,
                "sys_ticks": 500,
                "idle_ticks": 10000,
                "state": "running",
            },
            "cpu1": {
                "user_ticks": 900,
                "sys_ticks": 600,
                "idle_ticks": 10000,
                "state": "idle",
            },
        }
        errors = validate_cpus(data)
        self.assertEqual(errors, [])

    def test_02_cpu_field_is_float(self):
        """Test: CPU field is float."""
        data = {
            "cpu0": {
                "user_ticks": 1000.5,
            }
        }
        errors = validate_cpus(data)
        self.assertTrue(any("int" in e for e in errors))

    def test_03_cpu_field_is_bool(self):
        """Test: CPU field is bool."""
        data = {
            "cpu0": {
                "user_ticks": True,
            }
        }
        errors = validate_cpus(data)
        self.assertTrue(any("bool" in e for e in errors))


class TestValidateCloud(unittest.TestCase):
    """Tests for cloud metadata validation."""

    def test_01_cloud_is_false(self):
        """Test: cloud is False (not on cloud)."""
        errors = validate_cloud(False)
        self.assertEqual(errors, [])

    def test_02_cloud_is_dict(self):
        """Test: cloud is non-empty dict."""
        errors = validate_cloud({"provider": "ec2", "region": "us-east-1"})
        self.assertEqual(errors, [])

    def test_03_cloud_is_empty_dict(self):
        """Test: cloud is empty dict."""
        errors = validate_cloud({})
        self.assertTrue(any("non-empty" in e for e in errors))

    def test_04_cloud_is_none(self):
        """Test: cloud is None."""
        errors = validate_cloud(None)
        self.assertTrue(any("cloud" in e for e in errors))


class TestValidateMemory(unittest.TestCase):
    """Tests for memory validation."""

    def test_01_valid_memory(self):
        """Test: Valid memory structure."""
        data = {
            "memory": {
                "mem_total": 8000000000,
                "mem_free": 2000000000,
                "cached": 1000000000,
            },
            "slabs": False,
        }
        errors = validate_memory(data)
        self.assertEqual(errors, [])

    def test_02_memory_value_is_string(self):
        """Test: memory sub-dict value is string."""
        data = {
            "memory": {"mem_total": "8GB"},
            "slabs": False,
        }
        errors = validate_memory(data)
        self.assertTrue(any("int" in e for e in errors))

    def test_03_memory_value_is_negative(self):
        """Test: memory sub-dict value is negative."""
        data = {
            "memory": {"mem_total": -1000},
            "slabs": False,
        }
        errors = validate_memory(data)
        self.assertTrue(any("non-negative" in e for e in errors))

    def test_04_slabs_is_none(self):
        """Test: slabs is None."""
        data = {
            "memory": {"mem_total": 8000000000},
            "slabs": None,
        }
        errors = validate_memory(data)
        self.assertTrue(any("slabs" in e for e in errors))

    def test_05_slab_value_is_float(self):
        """Test: Slab entry value is float."""
        data = {
            "memory": {"mem_total": 8000000000},
            "slabs": {"kmalloc-8": {"active_objs": 1.5}},
        }
        errors = validate_memory(data)
        self.assertTrue(any("int" in e for e in errors))

    def test_06_memory_with_parenthesized_keys(self):
        """Test: memory dict with parenthesized keys (Linux /proc/meminfo)."""
        data = {
            "memory": {
                "mem_total": 8000000000,
                "active(anon)": 2000000000,
                "inactive(file)": 1000000000,
            },
            "slabs": False,
        }
        errors = validate_memory(data)
        self.assertEqual(errors, [])

    def test_07_valid_aix_memory(self):
        """Test: Valid AIX memory (different key set, slabs is False)."""
        data = {
            "memory": {
                "mem_total": 8000000000,
                "mem_free": 2000000000,
                "mem_available": 3000000000,
            },
            "slabs": False,
        }
        errors = validate_memory(data)
        self.assertEqual(errors, [])


class TestValidateFilesystems(unittest.TestCase):
    """Tests for filesystem validation."""

    def test_01_valid_mounted_filesystem(self):
        """Test: Valid mounted filesystem with statvfs fields."""
        data = {
            "/": {
                "mountpoint": "/",
                "dev": "/dev/sda1",
                "vfs": "ext4",
                "mounted": True,
                "options": '{"rw":true}',
                "f_bsize": 4096,
                "f_frsize": 4096,
                "f_blocks": 500000,
                "f_bfree": 100000,
                "f_bavail": 90000,
                "f_files": 1000000,
                "f_ffree": 900000,
                "f_favail": 900000,
                "bytes_total": 2000000000,
                "bytes_free": 400000000,
                "bytes_available": 360000000,
                "f_flag": 0,
                "f_namemax": 255,
                "pct_used": 80.0,
                "pct_free": 20.0,
                "pct_available": 18.0,
                "pct_reserved": 2.0,
            }
        }
        errors = validate_filesystems(data)
        self.assertEqual(errors, [])

    def test_02_pct_used_exceeds_100(self):
        """Test: pct_used > 100."""
        data = {
            "/": {
                "mountpoint": "/",
                "dev": "/dev/sda1",
                "vfs": "ext4",
                "mounted": True,
                "options": "{}",
                "f_bsize": 4096,
                "f_blocks": 100,
                "f_bfree": 10,
                "f_bavail": 10,
                "f_files": 100,
                "f_ffree": 50,
                "f_favail": 50,
                "bytes_total": 1000,
                "bytes_free": 100,
                "bytes_available": 100,
                "f_flag": 0,
                "f_namemax": 255,
                "pct_used": 150.0,
                "pct_free": 50.0,
                "pct_available": 50.0,
                "pct_reserved": 0.0,
            }
        }
        errors = validate_filesystems(data)
        self.assertTrue(any("100" in e for e in errors))

    def test_03_pct_used_is_negative(self):
        """Test: pct_used < 0."""
        data = {
            "/": {
                "mountpoint": "/",
                "dev": "/dev/sda1",
                "vfs": "ext4",
                "mounted": True,
                "options": "{}",
                "f_bsize": 4096,
                "f_blocks": 100,
                "f_bfree": 10,
                "f_bavail": 10,
                "f_files": 100,
                "f_ffree": 50,
                "f_favail": 50,
                "bytes_total": 1000,
                "bytes_free": 100,
                "bytes_available": 100,
                "f_flag": 0,
                "f_namemax": 255,
                "pct_used": -5.0,
                "pct_free": 105.0,
                "pct_available": 105.0,
                "pct_reserved": 0.0,
            }
        }
        errors = validate_filesystems(data)
        self.assertTrue(any("0.0 and 100.0" in e for e in errors))

    def test_04_mounted_is_int(self):
        """Test: mounted is int instead of bool."""
        data = {
            "/": {
                "mountpoint": "/",
                "dev": "/dev/sda1",
                "vfs": "ext4",
                "mounted": 1,
                "options": "{}",
            }
        }
        errors = validate_filesystems(data)
        self.assertTrue(any("bool" in e for e in errors))

    def test_05_missing_bytes_total_when_mounted(self):
        """Test: Missing bytes_total when mounted is True."""
        data = {
            "/": {
                "mountpoint": "/",
                "dev": "/dev/sda1",
                "vfs": "ext4",
                "mounted": True,
                "options": "{}",
                "f_bsize": 4096,
                "f_blocks": 100,
                "f_bfree": 10,
                "f_bavail": 10,
                "f_files": 100,
                "f_ffree": 50,
                "f_favail": 50,
                "bytes_free": 100,
                "bytes_available": 100,
                "f_flag": 0,
                "f_namemax": 255,
                "pct_used": 80.0,
                "pct_free": 20.0,
                "pct_available": 18.0,
                "pct_reserved": 2.0,
            }
        }
        errors = validate_filesystems(data)
        self.assertTrue(any("bytes_total" in e for e in errors))

    def test_06_valid_aix_unmounted_filesystem(self):
        """Test: Valid AIX unmounted filesystem (WPAR entry)."""
        data = {
            "/wpar": {
                "mountpoint": "/wpar",
                "dev": "none",
                "vfs": "jfs2",
                "mounted": False,
                "options": "{}",
                "log": "/dev/loglv00",
                "mount": "automatic",
                "type": "jfs2",
                "account": "yes",
            }
        }
        errors = validate_filesystems(data)
        self.assertEqual(errors, [])

    def test_07_valid_aix_mounted_filesystem(self):
        """Test: Valid AIX mounted filesystem with statvfs."""
        data = {
            "/": {
                "mountpoint": "/",
                "dev": "/dev/hd5",
                "vfs": "jfs2",
                "mounted": True,
                "options": "{}",
                "log": "/dev/loglv00",
                "mount": "automatic",
                "type": "jfs2",
                "account": "yes",
                "f_bsize": 4096,
                "f_frsize": 4096,
                "f_blocks": 500000,
                "f_bfree": 100000,
                "f_bavail": 90000,
                "f_files": 1000000,
                "f_ffree": 900000,
                "f_favail": 900000,
                "bytes_total": 2000000000,
                "bytes_free": 400000000,
                "bytes_available": 360000000,
                "f_flag": 0,
                "f_namemax": 255,
                "pct_used": 80.0,
                "pct_free": 20.0,
                "pct_available": 18.0,
                "pct_reserved": 2.0,
            }
        }
        errors = validate_filesystems(data)
        self.assertEqual(errors, [])

    def test_08_unknown_string_field_accepted(self):
        """Test: Unknown string field is accepted."""
        data = {
            "/": {
                "mountpoint": "/",
                "dev": "/dev/sda1",
                "vfs": "ext4",
                "mounted": False,
                "options": "{}",
                "custom_field": "anything",
            }
        }
        errors = validate_filesystems(data)
        self.assertEqual(errors, [])


class TestValidateDisks(unittest.TestCase):
    """Tests for disk validation."""

    def test_01_valid_linux_disk(self):
        """Test: Valid Linux disk entry."""
        data = {
            "sda": {
                "major": 8,
                "minor": 0,
                "read_ios": 1000,
                "write_ios": 500,
                "read_sectors": 10000,
                "write_sectors": 5000,
                "read_ticks": 100,
                "write_ticks": 50,
            }
        }
        errors = validate_disks(data)
        self.assertEqual(errors, [])

    def test_02_valid_aix_disk(self):
        """Test: Valid AIX disk entry."""
        data = {
            "hdisk0": {
                "size_bytes": 1000000000,
                "free_bytes": 500000000,
                "read_ios": 1000,
                "write_ios": 500,
                "read_blocks": 10000,
                "write_blocks": 5000,
                "description": "SCSI Disk Drive",
                "vgname": "rootvg",
            }
        }
        errors = validate_disks(data)
        self.assertEqual(errors, [])

    def test_03_disk_field_is_float(self):
        """Test: Disk field is float."""
        data = {
            "sda": {
                "read_ios": 1.5,
            }
        }
        errors = validate_disks(data)
        self.assertTrue(any("int" in e for e in errors))

    def test_04_disk_field_is_negative(self):
        """Test: Disk field is negative."""
        data = {
            "sda": {
                "read_ios": -100,
            }
        }
        errors = validate_disks(data)
        self.assertTrue(any("non-negative" in e for e in errors))

    def test_05_disk_field_is_nested_dict(self):
        """Test: Disk field is nested dict."""
        data = {
            "sda": {
                "read_ios": {"value": 1000},
            }
        }
        errors = validate_disks(data)
        self.assertTrue(any("int" in e or "str" in e for e in errors))


class TestValidateDiskTotal(unittest.TestCase):
    """Tests for disk_total (AIX) validation."""

    def test_01_valid_disk_total(self):
        """Test: Valid disk_total dict."""
        data = {
            "xfers": 10000,
            "time": 500,
            "read_blocks": 100000,
            "write_blocks": 50000,
            "ndisks": 4,
        }
        errors = validate_disk_total(data)
        self.assertEqual(errors, [])

    def test_02_field_is_negative(self):
        """Test: Field is negative."""
        data = {"ndisks": -1}
        errors = validate_disk_total(data)
        self.assertTrue(any("non-negative" in e for e in errors))

    def test_03_field_is_str(self):
        """Test: Field is str."""
        data = {"ndisks": "4"}
        errors = validate_disk_total(data)
        self.assertTrue(any("int" in e for e in errors))

    def test_04_unknown_field_accepted(self):
        """Test: Unknown field is accepted."""
        data = {"ndisks": 4, "future_field": 100}
        errors = validate_disk_total(data)
        self.assertEqual(errors, [])


class TestValidateNetwork(unittest.TestCase):
    """Tests for network validation."""

    def test_01_valid_linux_network(self):
        """Test: Valid Linux network entry."""
        data = {
            "eth0": {
                "ibytes": 1000000,
                "ipackets": 1000,
                "ierrors": 0,
                "idrop": 0,
                "ififo": 0,
                "iframe": 0,
                "icompressed": 0,
                "imulticast": 0,
                "obytes": 500000,
                "opackets": 500,
                "oerrors": 0,
                "odrop": 0,
                "ofifo": 0,
                "collisions": 0,
                "ocarrier": 0,
                "ocompressed": 0,
                "mtu": 1500,
                "operstate": "up",
                "type": 1,
                "speed_mbps": 1000,
            }
        }
        errors = validate_network(data)
        self.assertEqual(errors, [])

    def test_02_ibytes_is_negative(self):
        """Test: ibytes is negative."""
        data = {
            "eth0": {
                "ibytes": -1000,
            }
        }
        errors = validate_network(data)
        self.assertTrue(any("non-negative" in e for e in errors))

    def test_03_ibytes_is_string(self):
        """Test: ibytes is string."""
        data = {
            "eth0": {
                "ibytes": "1000",
            }
        }
        errors = validate_network(data)
        self.assertTrue(any("int" in e for e in errors))

    def test_04_operstate_is_int(self):
        """Test: operstate is int."""
        data = {
            "eth0": {
                "operstate": 1,
            }
        }
        errors = validate_network(data)
        self.assertTrue(any("str" in e for e in errors))

    def test_05_valid_aix_network(self):
        """Test: Valid AIX network entry."""
        data = {
            "en0": {
                "ibytes": 1000000,
                "ipackets": 1000,
                "ierrors": 0,
                "idrop": 0,
                "obytes": 500000,
                "opackets": 500,
                "oerrors": 0,
                "collisions": 0,
                "if_arpdrops": 0,
                "mtu": 1500,
                "speed_mbps": 1000,
                "type": 1,
                "description": "Standard Ethernet Network Interface",
            }
        }
        errors = validate_network(data)
        self.assertEqual(errors, [])

    def test_06_linux_fields_not_required_on_aix(self):
        """Test: Linux-only fields absent from AIX entry is OK."""
        data = {
            "en0": {
                "ibytes": 1000000,
                "ipackets": 1000,
                "obytes": 500000,
                "opackets": 500,
                "mtu": 1500,
                "description": "Interface",
            }
        }
        errors = validate_network(data)
        self.assertEqual(errors, [])


class TestFullPayload(unittest.TestCase):
    """Full payload integration tests."""

    def test_01_valid_payload_with_optional_sections(self):
        """Test: Valid payload with optional cpustats and memory."""
        data = {
            "system_id": "test-system",
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            "cpustats": {
                "user_ticks": 1000,
                "sys_ticks": 500,
                "loadavg_1": 1.5,
                "cpu0": {"user_ticks": 500, "idle_ticks": 10000},
            },
            "memory": {
                "memory": {"mem_total": 8000000000},
                "slabs": False,
            },
        }
        errors = validate_payload(data)
        self.assertEqual(errors, [])

    def test_02_envelope_error_stops_validation(self):
        """Test: Envelope error prevents section validation."""
        data = {
            "system_id": "",  # Invalid
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            "memory": {
                "memory": {"mem_total": "not_a_number"},  # Would be invalid
                "slabs": False,
            },
        }
        errors = validate_payload(data)
        # Should have only envelope error, not memory error
        self.assertTrue(any("system_id" in e for e in errors))
        self.assertFalse(any("memory" in e for e in errors))

    def test_03_multiple_section_errors(self):
        """Test: Multiple section errors are collected."""
        data = {
            "system_id": "test-system",
            "collected_at": 1700000000.0,
            "hostname": "test-host",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            "cpustats": {
                "user_ticks": -100,  # Invalid: negative
                "loadavg_1": "not_a_number",  # Invalid: string
            },
            "memory": {
                "memory": {"mem_total": -1000},  # Invalid: negative
                "slabs": None,  # Invalid: None instead of False/dict
            },
        }
        errors = validate_payload(data)
        self.assertTrue(len(errors) >= 3)


if __name__ == "__main__":
    unittest.main()
