"""
Tests for receiver.transform module.

Tests the transformation of validated JSON sections into SQL row dicts.
"""

import json
import unittest

from receiver.transform import (
    transform_cpu_stats,
    transform_cpu_info,
    transform_memory,
    transform_memory_slabs,
    transform_filesystems,
    transform_disks_linux,
    transform_disk_total_linux,
    transform_disks_aix,
    transform_network,
)


class TestTransformCpuStats(unittest.TestCase):
    """Tests for transform_cpu_stats."""

    def test_linux_aggregate_cpustats(self):
        """Linux cpustats → row-dict has aggregate fields at top level."""
        cpustats = {
            'user_ticks': 100,
            'sys_ticks': 50,
            'idle_ticks': 800,
            'iowait_ticks': 10,
            'nice_ticks': 5,
            'irq_ticks': 2,
            'softirq_ticks': 3,
            'steal_ticks': 0,
            'guest_ticks': 0,
            'guest_nice_ticks': 0,
            'ctxt': 12345,
            'btime': 1677000000,
            'processes': 5000,
            'procs_running': 2,
            'procs_blocked': 0,
            'loadavg_1': 1.2,
            'loadavg_5': 1.5,
            'loadavg_15': 1.8,
            'softirq': [1, 2, 3],  # Should be skipped
            'cpu0': {'user_ticks': 50, 'sys_ticks': 25},  # Should be skipped
        }
        row = transform_cpu_stats(cpustats, host_id=1, collected_at=1234567890.0)

        # Check direct fields
        self.assertEqual(row['host_id'], 1)
        self.assertEqual(row['collected_at'], 1234567890.0)
        self.assertEqual(row['user_ticks'], 100)
        self.assertEqual(row['nice_ticks'], 5)
        self.assertEqual(row['btime'], 1677000000)

        # Check that per-CPU and softirq are excluded
        self.assertNotIn('cpu0', row)
        self.assertNotIn('softirq', row)

    def test_aix_cpustats(self):
        """AIX cpustats → row-dict has AIX-specific fields."""
        cpustats = {
            'user_ticks': 100,
            'sys_ticks': 50,
            'idle_ticks': 800,
            'iowait_ticks': 10,
            'ctxt': 67890,
            'loadavg_1': 0.5,
            'loadavg_5': 0.6,
            'loadavg_15': 0.7,
            'ncpus': 8,
            'ncpus_cfg': 8,
            'ncpus_high': 8,
            'syscall': 12345,
            'sysread': 1000,
            'syswrite': 2000,
            'sysfork': 500,
            'sysexec': 300,
            'readch': 5000,
            'writech': 3000,
            'devintrs': 100,
            'softintrs': 200,
            'lbolt': 999999,
            'runque': 1,
            'swpque': 0,
            'runocc': 100,
            'swpocc': 0,
            'puser_spurr': 50,
            'psys_spurr': 25,
            'pidle_spurr': 800,
            'pwait_spurr': 5,
            # Fields NOT in schema (should be excluded)
            'spurrflag': 1,
            'version': 3,
            'lbolt': 999999,
            'bread': 999,
            'bwrite': 888,
            'puser': 999,
        }
        row = transform_cpu_stats(cpustats, host_id=2, collected_at=1234567890.0)

        # Check AIX-specific schema columns are included
        self.assertEqual(row['ncpus'], 8)
        self.assertEqual(row['syscall'], 12345)
        self.assertEqual(row['puser_spurr'], 50)

        # Check dropped fields are excluded
        self.assertNotIn('spurrflag', row)
        self.assertNotIn('version', row)
        self.assertNotIn('lbolt', row)
        self.assertNotIn('bread', row)
        self.assertNotIn('bwrite', row)
        self.assertNotIn('puser', row)

    def test_per_cpu_keys_excluded(self):
        """Per-CPU keys (cpu0, cpu1, ...) are excluded from output."""
        cpustats = {
            'user_ticks': 100,
            'sys_ticks': 50,
            'idle_ticks': 800,
            'iowait_ticks': 10,
            'cpu0': {'user_ticks': 50},
            'cpu1': {'user_ticks': 50},
        }
        row = transform_cpu_stats(cpustats, host_id=1, collected_at=1234567890.0)

        self.assertNotIn('cpu0', row)
        self.assertNotIn('cpu1', row)
        self.assertEqual(row['user_ticks'], 100)


class TestTransformCpuInfo(unittest.TestCase):
    """Tests for transform_cpu_info."""

    def test_key_renames(self):
        """'cpu family', 'model name', 'cpu MHz' are renamed."""
        cpuinfo = {
            'vendor_id': 'GenuineIntel',
            'cpu family': 6,
            'model name': 'Intel(R) Core(TM) i7-8700K',
            'cpu MHz': 3700.0,
            'stepping': 10,
        }
        row = transform_cpu_info(cpuinfo, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['cpu_family'], 6)
        self.assertEqual(row['model_name'], 'Intel(R) Core(TM) i7-8700K')
        self.assertEqual(row['cpu_mhz'], 3700.0)
        self.assertEqual(row['vendor_id'], 'GenuineIntel')
        self.assertEqual(row['recorded_at'], 1234567890.0)
        self.assertNotIn('collected_at', row)

    def test_flags_list_to_string(self):
        """flags list → space-separated string."""
        cpuinfo = {
            'flags': ['fpu', 'vme', 'de', 'pse', 'tsc'],
        }
        row = transform_cpu_info(cpuinfo, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['flags'], 'fpu vme de pse tsc')

    def test_bugs_list_dropped(self):
        """bugs list is converted but dropped (not in schema)."""
        cpuinfo = {
            'vendor_id': 'GenuineIntel',
            'bugs': ['cpu_meltdown', 'spectre_v1'],
        }
        row = transform_cpu_info(cpuinfo, host_id=1, collected_at=1234567890.0)

        # bugs should not be in output
        self.assertNotIn('bugs', row)
        # But vendor_id should be
        self.assertEqual(row['vendor_id'], 'GenuineIntel')

    def test_non_schema_keys_dropped(self):
        """Keys not in schema (microcode, fpu, wp, etc.) are dropped."""
        cpuinfo = {
            'vendor_id': 'GenuineIntel',
            'model_name': 'Intel Core i7',
            'microcode': '0xca',
            'fpu': 'yes',
            'wp': 'yes',
            'vmx flags': 'yes',
            'cpuid level': 22,
            'address sizes': '46 bits physical, 48 bits virtual',
            'power management': 'ts arat pln pts',
        }
        row = transform_cpu_info(cpuinfo, host_id=1, collected_at=1234567890.0)

        # Schema keys should be present
        self.assertEqual(row['vendor_id'], 'GenuineIntel')
        self.assertEqual(row['model_name'], 'Intel Core i7')

        # Non-schema keys should be dropped
        self.assertNotIn('microcode', row)
        self.assertNotIn('fpu', row)
        self.assertNotIn('wp', row)
        self.assertNotIn('vmx flags', row)
        self.assertNotIn('cpuid level', row)
        self.assertNotIn('address sizes', row)
        self.assertNotIn('power management', row)

    def test_cpu_count_parameter(self):
        """cpu_count parameter is included in output."""
        cpuinfo = {'vendor_id': 'GenuineIntel'}
        row = transform_cpu_info(cpuinfo, host_id=1, collected_at=1234567890.0, cpu_count=8)

        self.assertEqual(row['cpu_count'], 8)

    def test_cpu_count_parameter_none(self):
        """cpu_count=None is not included in output."""
        cpuinfo = {'vendor_id': 'GenuineIntel'}
        row = transform_cpu_info(cpuinfo, host_id=1, collected_at=1234567890.0, cpu_count=None)

        self.assertNotIn('cpu_count', row)


class TestTransformMemory(unittest.TestCase):
    """Tests for transform_memory."""

    def test_memory_key_renames(self):
        """'cached' → 'mem_cached', 'hugepagesize' → 'huge_page_size'."""
        memory_inner = {
            'mem_total': 16777216000,
            'mem_free': 4194304000,
            'cached': 2097152000,
            'hugepagesize': 2097152,
        }
        row = transform_memory(memory_inner, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['mem_total'], 16777216000)
        self.assertEqual(row['mem_cached'], 2097152000)
        self.assertEqual(row['huge_page_size'], 2097152)
        self.assertNotIn('cached', row)
        self.assertNotIn('hugepagesize', row)

    def test_unknown_keys_to_extra_json(self):
        """Unknown keys go into extra_json."""
        memory_inner = {
            'mem_total': 16777216000,
            'mem_free': 4194304000,
            'active(anon)': 1000000000,
            'inactive(anon)': 500000000,
            'active(file)': 2000000000,
        }
        row = transform_memory(memory_inner, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['mem_total'], 16777216000)
        self.assertEqual(row['mem_free'], 4194304000)

        extra = json.loads(row['extra_json'])
        self.assertEqual(extra['active(anon)'], 1000000000)
        self.assertEqual(extra['inactive(anon)'], 500000000)
        self.assertEqual(extra['active(file)'], 2000000000)

    def test_aix_keys_to_extra_json(self):
        """AIX-only keys (real_inuse, pgbad, etc.) go into extra_json."""
        memory_inner = {
            'mem_total': 16777216000,
            'mem_free': 4194304000,
            'mem_available': 8388608000,
            'real_inuse': 10000000000,
            'pgbad': 100,
            'virt_total': 16777216000,
        }
        row = transform_memory(memory_inner, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['mem_total'], 16777216000)
        self.assertEqual(row['mem_available'], 8388608000)

        extra = json.loads(row['extra_json'])
        self.assertEqual(extra['real_inuse'], 10000000000)
        self.assertEqual(extra['pgbad'], 100)
        self.assertEqual(extra['virt_total'], 16777216000)

    def test_no_extra_json_when_empty(self):
        """extra_json is None when no unknown keys."""
        memory_inner = {
            'mem_total': 16777216000,
            'mem_free': 4194304000,
        }
        row = transform_memory(memory_inner, host_id=1, collected_at=1234567890.0)

        self.assertIsNone(row['extra_json'])


class TestTransformMemorySlabs(unittest.TestCase):
    """Tests for transform_memory_slabs."""

    def test_slabs_false(self):
        """Input slabs=False → empty list."""
        rows = transform_memory_slabs(False, host_id=1, collected_at=1234567890.0)
        self.assertEqual(rows, [])

    def test_valid_slabs(self):
        """Valid slabs dict → list of rows with correct keys."""
        slabs = {
            'kmalloc-256': {
                'active_objs': 1000,
                'num_objs': 2000,
                'objsize': 256,
                'objperslab': 16,
                'pagesperslab': 1,
                'limit': 2000,
                'batchcount': 2,
                'sharedfactor': 1,
                'active_slabs': 100,
                'num_slabs': 200,
                'sharedavail': 0,
            },
            'kmalloc-512': {
                'active_objs': 500,
                'num_objs': 1000,
                'objsize': 512,
                'objperslab': 8,
                'pagesperslab': 1,
                'limit': 1000,
                'batchcount': 2,
                'sharedfactor': 1,
                'active_slabs': 50,
                'num_slabs': 125,
                'sharedavail': 0,
            },
        }
        rows = transform_memory_slabs(slabs, host_id=1, collected_at=1234567890.0)

        self.assertEqual(len(rows), 2)

        # Check first slab
        row0 = next(r for r in rows if r['slab_name'] == 'kmalloc-256')
        self.assertEqual(row0['host_id'], 1)
        self.assertEqual(row0['collected_at'], 1234567890.0)
        self.assertEqual(row0['active_objs'], 1000)
        self.assertEqual(row0['objsize'], 256)

        # Check second slab
        row1 = next(r for r in rows if r['slab_name'] == 'kmalloc-512')
        self.assertEqual(row1['active_objs'], 500)
        self.assertEqual(row1['objsize'], 512)


class TestTransformFilesystems(unittest.TestCase):
    """Tests for transform_filesystems."""

    def test_f_flag_rdonly_derivation(self):
        """f_flag & 1 → fs_rdonly."""
        filesystems = {
            '/': {
                'mountpoint': '/',
                'dev': '/dev/sda1',
                'vfs': 'ext4',
                'mounted': True,
                'f_flag': 1,
                'bytes_total': 1000000000,
                'bytes_free': 500000000,
                'bytes_available': 500000000,
                'pct_used': 50.0,
                'pct_free': 50.0,
                'pct_available': 50.0,
                'pct_reserved': 0.0,
            },
            '/home': {
                'mountpoint': '/home',
                'dev': '/dev/sda2',
                'vfs': 'ext4',
                'mounted': True,
                'f_flag': 0,
                'bytes_total': 2000000000,
                'bytes_free': 1000000000,
                'bytes_available': 1000000000,
                'pct_used': 50.0,
                'pct_free': 50.0,
                'pct_available': 50.0,
                'pct_reserved': 0.0,
            },
        }
        rows = transform_filesystems(filesystems, host_id=1, collected_at=1234567890.0)

        self.assertEqual(len(rows), 2)

        root = next(r for r in rows if r['mountpoint'] == '/')
        self.assertEqual(root['fs_rdonly'], 1)

        home = next(r for r in rows if r['mountpoint'] == '/home')
        self.assertEqual(home['fs_rdonly'], 0)

    def test_aix_renames(self):
        """AIX 'log' → 'fs_log', 'mount' → 'mount_auto', 'type' → 'fs_type'."""
        filesystems = {
            '/wpar': {
                'mountpoint': '/wpar',
                'dev': '/dev/mapper/wpar_vol',
                'vfs': 'jfs2',
                'mounted': False,
                'log': 'logvol',
                'mount': 'mount_point',
                'type': 'writeable',
            },
        }
        rows = transform_filesystems(filesystems, host_id=1, collected_at=1234567890.0)

        row = rows[0]
        self.assertEqual(row['fs_log'], 'logvol')
        self.assertEqual(row['mount_auto'], 'mount_point')
        self.assertEqual(row['fs_type'], 'writeable')
        self.assertNotIn('log', row)
        self.assertNotIn('mount', row)
        self.assertNotIn('type', row)

    def test_bool_mounted_to_int(self):
        """mounted: True → 1, False → 0."""
        filesystems = {
            '/mounted': {
                'mounted': True,
                'dev': '/dev/sda1',
                'vfs': 'ext4',
            },
            '/unmounted': {
                'mounted': False,
                'dev': '/dev/sdb1',
                'vfs': 'ext4',
            },
        }
        rows = transform_filesystems(filesystems, host_id=1, collected_at=1234567890.0)

        mounted_row = next(r for r in rows if r['mountpoint'] == '/mounted')
        self.assertEqual(mounted_row['mounted'], 1)

        unmounted_row = next(r for r in rows if r['mountpoint'] == '/unmounted')
        self.assertEqual(unmounted_row['mounted'], 0)

    def test_unmounted_no_statvfs_fields(self):
        """Unmounted entry has no statvfs fields (NULL in DB)."""
        filesystems = {
            '/unmounted': {
                'mounted': False,
                'dev': '/dev/sdb1',
                'vfs': 'ext4',
                'options': '{}',
                # statvfs fields would be here if mounted=True
            },
        }
        rows = transform_filesystems(filesystems, host_id=1, collected_at=1234567890.0)

        row = rows[0]
        self.assertEqual(row['mounted'], 0)
        # Ensure statvfs fields are absent
        self.assertNotIn('bytes_total', row)
        self.assertNotIn('pct_used', row)

    def test_f_namemax_dropped(self):
        """f_namemax is dropped from output."""
        filesystems = {
            '/': {
                'mounted': True,
                'dev': '/dev/sda1',
                'vfs': 'ext4',
                'f_namemax': 255,
                'f_flag': 0,
                'bytes_total': 1000000000,
            },
        }
        rows = transform_filesystems(filesystems, host_id=1, collected_at=1234567890.0)

        row = rows[0]
        self.assertNotIn('f_namemax', row)

    def test_account_dropped(self):
        """AIX 'account' field is dropped from output."""
        filesystems = {
            '/wpar': {
                'mounted': False,
                'dev': '/dev/vg',
                'vfs': 'jfs2',
                'account': 'wpar_account',
            },
        }
        rows = transform_filesystems(filesystems, host_id=1, collected_at=1234567890.0)

        row = rows[0]
        self.assertNotIn('account', row)


class TestTransformDisksLinux(unittest.TestCase):
    """Tests for transform_disks_linux."""

    def test_sysfs_to_extra_json(self):
        """Sysfs fields bundled into extra_json."""
        disks = {
            'sda': {
                'major': 8,
                'minor': 0,
                'read_ios': 10000,
                'read_sectors': 1000000,
                'write_ios': 5000,
                'write_sectors': 500000,
                'size_bytes': 1000000000000,
                'rotational': 1,
                'physical_block_size': 512,
                'logical_block_size': 512,
                'scheduler': 'deadline',
            },
        }
        rows = transform_disks_linux(disks, host_id=1, collected_at=1234567890.0)

        row = rows[0]
        self.assertEqual(row['name'], 'sda')
        self.assertEqual(row['major'], 8)
        self.assertEqual(row['minor'], 0)
        self.assertEqual(row['read_ios'], 10000)

        extra = json.loads(row['extra_json'])
        self.assertEqual(extra['size_bytes'], 1000000000000)
        self.assertEqual(extra['rotational'], 1)
        self.assertEqual(extra['scheduler'], 'deadline')

    def test_no_sysfs_extra_json_none(self):
        """Disk with no sysfs data → extra_json is None."""
        disks = {
            'nvme0n1': {
                'major': 259,
                'minor': 0,
                'read_ios': 20000,
                'read_sectors': 2000000,
                'write_ios': 10000,
                'write_sectors': 1000000,
            },
        }
        rows = transform_disks_linux(disks, host_id=1, collected_at=1234567890.0)

        row = rows[0]
        self.assertIsNone(row['extra_json'])


class TestTransformDiskTotalLinux(unittest.TestCase):
    """Tests for transform_disk_total_linux."""

    def test_single_disk(self):
        """Single disk aggregation."""
        disks = {
            'sda': {
                'major': 8,
                'minor': 0,
                'read_ios': 100,
                'read_merge': 10,
                'read_sectors': 1000,
                'read_ticks': 50,
                'write_ios': 50,
                'write_merges': 5,
                'write_sectors': 500,
                'write_ticks': 25,
                'in_flight': 0,
                'total_io_ticks': 75,
                'total_time_in_queue': 100,
            },
        }
        row = transform_disk_total_linux(disks, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['host_id'], 1)
        self.assertEqual(row['collected_at'], 1234567890.0)
        self.assertEqual(row['ndisks'], 1)
        self.assertEqual(row['read_ios'], 100)
        self.assertEqual(row['write_ios'], 50)
        self.assertEqual(row['read_blocks'], 1000)
        self.assertEqual(row['write_blocks'], 500)
        self.assertEqual(row['time'], 75)

    def test_multiple_disks_sum(self):
        """Multiple disks are summed."""
        disks = {
            'sda': {
                'read_ios': 100,
                'write_ios': 50,
                'read_sectors': 1000,
                'write_sectors': 500,
                'read_ticks': 50,
                'write_ticks': 25,
                'total_io_ticks': 75,
            },
            'sdb': {
                'read_ios': 200,
                'write_ios': 100,
                'read_sectors': 2000,
                'write_sectors': 1000,
                'read_ticks': 100,
                'write_ticks': 50,
                'total_io_ticks': 150,
            },
        }
        row = transform_disk_total_linux(disks, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['ndisks'], 2)
        self.assertEqual(row['read_ios'], 300)
        self.assertEqual(row['write_ios'], 150)
        self.assertEqual(row['read_blocks'], 3000)
        self.assertEqual(row['write_blocks'], 1500)
        self.assertEqual(row['read_ticks'], 150)
        self.assertEqual(row['write_ticks'], 75)
        self.assertEqual(row['time'], 225)

    def test_sparse_fields(self):
        """Devices with different field subsets — only present fields summed."""
        disks = {
            'sda': {
                'read_ios': 100,
                'write_ios': 50,
            },
            'sdb': {
                'read_ios': 200,
                'read_sectors': 2000,
            },
        }
        row = transform_disk_total_linux(disks, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['ndisks'], 2)
        self.assertEqual(row['read_ios'], 300)
        self.assertEqual(row['write_ios'], 50)
        self.assertIn('read_blocks', row)
        self.assertEqual(row['read_blocks'], 2000)
        self.assertNotIn('write_blocks', row)

    def test_missing_optional_fields(self):
        """Devices without certain fields — those fields omitted from total."""
        disks = {
            'nvme0n1': {
                'read_ios': 100,
                'write_ios': 50,
            },
        }
        row = transform_disk_total_linux(disks, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['ndisks'], 1)
        self.assertEqual(row['read_ios'], 100)
        self.assertNotIn('read_blocks', row)
        self.assertNotIn('write_blocks', row)
        self.assertNotIn('time', row)

    def test_all_fields_present(self):
        """All summed fields are included when available."""
        disks = {
            'sda': {
                'read_ios': 100,
                'read_sectors': 1000,
                'read_ticks': 50,
                'write_ios': 50,
                'write_sectors': 500,
                'write_ticks': 25,
                'total_io_ticks': 75,
            },
        }
        row = transform_disk_total_linux(disks, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['read_ios'], 100)
        self.assertEqual(row['read_blocks'], 1000)
        self.assertEqual(row['read_ticks'], 50)
        self.assertEqual(row['write_ios'], 50)
        self.assertEqual(row['write_blocks'], 500)
        self.assertEqual(row['write_ticks'], 25)
        self.assertEqual(row['time'], 75)

    def test_empty_disks_dict(self):
        """Empty disks dict → ndisks=0, no other fields."""
        row = transform_disk_total_linux({}, host_id=1, collected_at=1234567890.0)

        self.assertEqual(row['ndisks'], 0)
        # Only host_id, collected_at, and ndisks should be present
        self.assertEqual(len(row), 3)


class TestTransformDisksAix(unittest.TestCase):
    """Tests for transform_disks_aix."""

    def test_disk_rows_and_total(self):
        """Returns (per_device_rows, disk_total_row)."""
        disks = {
            'hdisk0': {
                'description': 'IBM 146GB SAS Disk Drive',
                'vgname': 'rootvg',
                'size_bytes': 146605465600,
                'free_bytes': 10737418240,
                'xfers': 100000,
                'read_ios': 60000,
                'write_ios': 40000,
                'read_blocks': 500000,
                'write_blocks': 400000,
                'read_ticks': 5000,
                'write_ticks': 3000,
                'time': 8000,
                'version': 1,
            },
            'hdisk1': {
                'description': 'IBM 146GB SAS Disk Drive',
                'size_bytes': 146605465600,
                'free_bytes': 5368709120,
                'xfers': 80000,
                'read_ios': 50000,
                'write_ios': 30000,
                'version': 1,
            },
        }
        disk_total = {
            'ndisks': 2,
            'size_bytes': 293210931200,
            'free_bytes': 16106127360,
            'xfers': 180000,
            'read_ios': 110000,
            'write_ios': 70000,
            'version': 1,
        }

        disk_rows, total_row = transform_disks_aix(
            disks, disk_total, host_id=1, collected_at=1234567890.0
        )

        self.assertEqual(len(disk_rows), 2)
        self.assertEqual(disk_rows[0]['name'], 'hdisk0')
        self.assertEqual(disk_rows[0]['description'], 'IBM 146GB SAS Disk Drive')
        self.assertEqual(disk_rows[0]['size_bytes'], 146605465600)
        self.assertNotIn('version', disk_rows[0])

        self.assertEqual(total_row['host_id'], 1)
        self.assertEqual(total_row['ndisks'], 2)
        self.assertEqual(total_row['xfers'], 180000)
        self.assertNotIn('version', total_row)


class TestTransformNetwork(unittest.TestCase):
    """Tests for transform_network."""

    def test_linux_all_fields(self):
        """Linux interface fields — stored columns pass through, dropped columns are filtered."""
        network = {
            'eth0': {
                # Stored columns
                'ibytes': 100000000,
                'ipackets': 1000000,
                'ierrors': 10,
                'idrop': 5,
                'obytes': 50000000,
                'opackets': 500000,
                'oerrors': 5,
                'odrop': 2,
                'mtu': 1500,
                'operstate': 'up',
                'type': 1,
                # Dropped columns (gatherer emits them, transform ignores them)
                'ififo': 0,
                'iframe': 0,
                'icompressed': 0,
                'imulticast': 100,
                'ofifo': 0,
                'collisions': 0,
                'ocarrier': 0,
                'ocompressed': 0,
            },
        }
        rows = transform_network(network, host_id=1, collected_at=1234567890.0)

        row = rows[0]
        self.assertEqual(row['iface'], 'eth0')
        self.assertEqual(row['ibytes'], 100000000)
        self.assertEqual(row['odrop'], 2)
        self.assertEqual(row['operstate'], 'up')
        self.assertEqual(row['mtu'], 1500)

        # Dropped columns must not appear in output
        self.assertNotIn('collisions', row)
        self.assertNotIn('ififo', row)
        self.assertNotIn('iframe', row)
        self.assertNotIn('icompressed', row)
        self.assertNotIn('imulticast', row)
        self.assertNotIn('ofifo', row)
        self.assertNotIn('ocarrier', row)
        self.assertNotIn('ocompressed', row)

    def test_linux_speed_mbps_optional(self):
        """speed_mbps is optional on Linux — absent when not in input."""
        network = {
            'eth0': {
                'ibytes': 100000000,
                'ipackets': 1000000,
                'operstate': 'up',
                'mtu': 1500,
                'type': 1,
            },
            'eth1': {
                'ibytes': 50000000,
                'ipackets': 500000,
                'operstate': 'down',
                'mtu': 1500,
                'type': 1,
                'speed_mbps': 1000,
            },
        }
        rows = transform_network(network, host_id=1, collected_at=1234567890.0)

        eth0 = next(r for r in rows if r['iface'] == 'eth0')
        self.assertNotIn('speed_mbps', eth0)

        eth1 = next(r for r in rows if r['iface'] == 'eth1')
        self.assertEqual(eth1['speed_mbps'], 1000)

    def test_aix_only_aix_fields(self):
        """AIX interface only has AIX-specific fields; Linux-only and dropped fields absent."""
        network = {
            'en0': {
                'ibytes': 100000000,
                'ipackets': 1000000,
                'ierrors': 10,
                'idrop': 5,
                'obytes': 50000000,
                'opackets': 500000,
                'oerrors': 5,
                'mtu': 1500,
                'speed_mbps': 1000,
                'type': 1,
                'description': 'Ethernet',
                # Dropped (not in schema)
                'collisions': 0,
                'if_arpdrops': 0,
            },
        }
        rows = transform_network(network, host_id=1, collected_at=1234567890.0)

        row = rows[0]
        self.assertEqual(row['iface'], 'en0')
        self.assertEqual(row['description'], 'Ethernet')
        self.assertEqual(row['idrop'], 5)

        # Dropped columns not in output
        self.assertNotIn('collisions', row)
        self.assertNotIn('if_arpdrops', row)
        # Linux-only field absent (AIX doesn't emit it)
        self.assertNotIn('operstate', row)
        # AIX doesn't emit odrop; not in output
        self.assertNotIn('odrop', row)

    def test_no_field_defaulting(self):
        """Absent fields are not included in output (no defaulting to NULL/0)."""
        network = {
            'lo': {
                'ibytes': 1000000,
                'ipackets': 10000,
                'obytes': 1000000,
                'opackets': 10000,
                'type': 772,
            },
        }
        rows = transform_network(network, host_id=1, collected_at=1234567890.0)

        row = rows[0]
        self.assertEqual(row['iface'], 'lo')
        self.assertEqual(row['ibytes'], 1000000)

        # Missing fields are not in row
        self.assertNotIn('mtu', row)
        self.assertNotIn('ierrors', row)


if __name__ == '__main__':
    unittest.main()
