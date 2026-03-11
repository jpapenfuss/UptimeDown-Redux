"""Unit tests for receiver.db module (SQLite ingestion layer)."""

import unittest
import sqlite3
import json
from unittest.mock import patch, MagicMock

from receiver import db
from receiver.transform import (
    transform_cpu_stats,
    transform_cpu_info,
    transform_memory,
    transform_memory_slabs,
    transform_filesystems,
    transform_disks_linux,
    transform_disks_aix,
    transform_network,
)


class TestInitSchema(unittest.TestCase):
    """Test schema creation."""

    def test_init_schema_creates_all_tables(self):
        """Schema creation creates all 9 tables."""
        conn = sqlite3.connect(":memory:")
        db.init_schema(conn)

        cursor = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
        tables = [row[0] for row in cursor.fetchall()]
        expected = [
            "cloud_metadata",
            "cpu_info",
            "cpu_stats",
            "disk_devices_aix",
            "disk_devices_linux",
            "disk_total",
            "filesystems",
            "hosts",
            "memory",
            "memory_slabs",
            "net_interfaces",
        ]
        self.assertEqual(sorted(tables), expected)
        conn.close()

    def test_init_schema_idempotent(self):
        """Calling init_schema twice is safe (tables exist already)."""
        conn = sqlite3.connect(":memory:")
        db.init_schema(conn)
        # Second call should not raise
        db.init_schema(conn)

        # Verify tables still exist
        cursor = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='hosts'"
        )
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1)
        conn.close()

    def test_init_schema_enables_foreign_keys(self):
        """Schema creation enables PRAGMA foreign_keys."""
        conn = sqlite3.connect(":memory:")
        db.init_schema(conn)

        cursor = conn.execute("PRAGMA foreign_keys")
        enabled = cursor.fetchone()[0]
        self.assertEqual(enabled, 1)
        conn.close()


class TestUpsertHost(unittest.TestCase):
    """Test host upsert logic."""

    def setUp(self):
        """Create in-memory database with schema for each test."""
        self.conn = sqlite3.connect(":memory:")
        db.init_schema(self.conn)

    def tearDown(self):
        """Close connection."""
        self.conn.close()

    def test_upsert_host_creates_new_row(self):
        """Upserting a new system_id creates a host row."""
        host_id = db.upsert_host(
            self.conn,
            system_id="test-001",
            hostname="myhost",
            platform="linux",
            collected_at=1234567890.123,
        )

        self.assertIsInstance(host_id, int)
        self.assertGreater(host_id, 0)

        # Verify row was created
        cursor = self.conn.execute(
            "SELECT system_id, hostname, platform, first_seen, last_seen FROM hosts WHERE id = ?",
            (host_id,),
        )
        row = cursor.fetchone()
        self.assertEqual(row[0], "test-001")
        self.assertEqual(row[1], "myhost")
        self.assertEqual(row[2], "linux")
        self.assertEqual(row[3], 1234567890.123)  # first_seen
        self.assertEqual(row[4], 1234567890.123)  # last_seen

    def test_upsert_host_existing_updates_last_seen(self):
        """Upserting an existing system_id updates last_seen but preserves first_seen."""
        # First upsert
        host_id_1 = db.upsert_host(
            self.conn,
            system_id="test-002",
            hostname="myhost",
            platform="linux",
            collected_at=1000000000.0,
        )

        # Second upsert with different timestamp
        host_id_2 = db.upsert_host(
            self.conn,
            system_id="test-002",
            hostname="myhost",
            platform="linux",
            collected_at=1000000100.0,
        )

        # Same host_id
        self.assertEqual(host_id_1, host_id_2)

        # Verify first_seen unchanged, last_seen updated
        cursor = self.conn.execute(
            "SELECT first_seen, last_seen FROM hosts WHERE id = ?", (host_id_1,)
        )
        row = cursor.fetchone()
        self.assertEqual(row[0], 1000000000.0)  # first_seen unchanged
        self.assertEqual(row[1], 1000000100.0)  # last_seen updated

    def test_upsert_host_id_stable_across_updates(self):
        """Host id never changes across updates (no INSERT OR REPLACE)."""
        id1 = db.upsert_host(
            self.conn,
            system_id="test-003",
            hostname="myhost",
            platform="linux",
            collected_at=1234567890.0,
        )
        id2 = db.upsert_host(
            self.conn,
            system_id="test-003",
            hostname="myhost-updated",
            platform="linux",
            collected_at=1234567900.0,
        )

        self.assertEqual(id1, id2)

    def test_upsert_host_hostname_updated(self):
        """Hostname is updated on conflict."""
        db.upsert_host(
            self.conn,
            system_id="test-004",
            hostname="oldname",
            platform="linux",
            collected_at=1000000000.0,
        )
        db.upsert_host(
            self.conn,
            system_id="test-004",
            hostname="newname",
            platform="linux",
            collected_at=1000000100.0,
        )

        cursor = self.conn.execute(
            "SELECT hostname FROM hosts WHERE system_id = ?", ("test-004",)
        )
        hostname = cursor.fetchone()[0]
        self.assertEqual(hostname, "newname")


class TestInsertOne(unittest.TestCase):
    """Test single-row insert helper."""

    def setUp(self):
        """Create in-memory database with schema."""
        self.conn = sqlite3.connect(":memory:")
        db.init_schema(self.conn)
        # Insert a dummy host for foreign key references
        self.host_id = db.upsert_host(
            self.conn, "test-host", "hostname", "linux", 1234567890.0
        )

    def tearDown(self):
        """Close connection."""
        self.conn.close()

    def test_insert_one_single_column(self):
        """Insert a single-column row."""
        row = {"host_id": self.host_id, "collected_at": 1234567890.0, "ncpus": 4}
        db._insert_one(self.conn, "cpu_stats", row)

        cursor = self.conn.execute(
            "SELECT ncpus FROM cpu_stats WHERE host_id = ?", (self.host_id,)
        )
        result = cursor.fetchone()
        self.assertEqual(result[0], 4)

    def test_insert_one_multiple_columns(self):
        """Insert a multi-column row."""
        row = {
            "host_id": self.host_id,
            "collected_at": 1234567890.0,
            "user_ticks": 100,
            "sys_ticks": 50,
            "idle_ticks": 800,
        }
        db._insert_one(self.conn, "cpu_stats", row)

        cursor = self.conn.execute(
            "SELECT user_ticks, sys_ticks, idle_ticks FROM cpu_stats WHERE host_id = ?",
            (self.host_id,),
        )
        result = cursor.fetchone()
        self.assertEqual(result, (100, 50, 800))

    def test_insert_one_empty_dict_noop(self):
        """Inserting an empty dict is a no-op."""
        db._insert_one(self.conn, "cpu_stats", {})
        cursor = self.conn.execute("SELECT COUNT(*) FROM cpu_stats")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)


class TestInsertMany(unittest.TestCase):
    """Test batch insert helper."""

    def setUp(self):
        """Create in-memory database with schema."""
        self.conn = sqlite3.connect(":memory:")
        db.init_schema(self.conn)
        self.host_id = db.upsert_host(
            self.conn, "test-host", "hostname", "linux", 1234567890.0
        )

    def tearDown(self):
        """Close connection."""
        self.conn.close()

    def test_insert_many_multiple_rows(self):
        """Batch insert multiple rows."""
        rows = [
            {
                "host_id": self.host_id,
                "collected_at": 1234567890.0,
                "mountpoint": "/",
                "mounted": 1,
            },
            {
                "host_id": self.host_id,
                "collected_at": 1234567890.0,
                "mountpoint": "/home",
                "mounted": 1,
            },
            {
                "host_id": self.host_id,
                "collected_at": 1234567890.0,
                "mountpoint": "/mnt/unused",
                "mounted": 0,
            },
        ]
        db._insert_many(self.conn, "filesystems", rows)

        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM filesystems WHERE host_id = ?", (self.host_id,)
        )
        count = cursor.fetchone()[0]
        self.assertEqual(count, 3)

    def test_insert_many_empty_list_noop(self):
        """Batch inserting an empty list is a no-op."""
        db._insert_many(self.conn, "filesystems", [])
        cursor = self.conn.execute("SELECT COUNT(*) FROM filesystems")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)


class TestIngest(unittest.TestCase):
    """Test full ingest pipeline."""

    def setUp(self):
        """Create in-memory database with schema."""
        self.conn = sqlite3.connect(":memory:")
        db.init_schema(self.conn)

    def tearDown(self):
        """Close connection."""
        self.conn.close()

    def test_ingest_cpustats_only(self):
        """Ingest a minimal payload with just cpustats."""
        data = {
            "system_id": "test-001",
            "collected_at": 1234567890.0,
            "hostname": "myhost",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            "cpustats": {
                "user_ticks": 100,
                "sys_ticks": 50,
                "idle_ticks": 800,
                "ctxt": 10000,
            },
        }
        db.ingest(self.conn, data)

        # Verify host was created
        cursor = self.conn.execute("SELECT COUNT(*) FROM hosts")
        host_count = cursor.fetchone()[0]
        self.assertEqual(host_count, 1)

        # Verify cpu_stats was created
        cursor = self.conn.execute(
            "SELECT user_ticks, sys_ticks FROM cpu_stats WHERE ctxt = ?", (10000,)
        )
        row = cursor.fetchone()
        self.assertEqual(row, (100, 50))

    def test_ingest_linux_full(self):
        """Ingest a complete Linux payload."""
        data = {
            "system_id": "linux-host",
            "collected_at": 1234567890.0,
            "hostname": "linux-box",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            "cpustats": {"user_ticks": 100, "sys_ticks": 50, "idle_ticks": 800},
            "cpuinfo": {"vendor_id": "GenuineIntel", "model_name": "Intel(R) Core(TM)"},
            "memory": {
                "memory": {"mem_total": 1000000, "mem_free": 500000},
                "slabs": False,
            },
            "filesystems": {
                "/": {
                    "mountpoint": "/",
                    "dev": "/dev/sda1",
                    "vfs": "ext4",
                    "mounted": 1,
                    "options": "rw",
                    "bytes_total": 1000000000,
                    "bytes_free": 500000000,
                    "bytes_available": 500000000,
                    "pct_used": 50.0,
                    "pct_available": 50.0,
                    "pct_free": 50.0,
                    "pct_reserved": 5.0,
                    "f_files": 1000,
                    "f_ffree": 500,
                    "f_favail": 500,
                    "f_flag": 0,
                }
            },
            "disks": {
                "sda": {
                    "major": 8,
                    "minor": 0,
                    "read_ios": 1000,
                    "read_sectors": 100000,
                    "write_ios": 500,
                    "write_sectors": 50000,
                }
            },
            "network": {
                "eth0": {
                    "ibytes": 10000000,
                    "ipackets": 100000,
                    "obytes": 5000000,
                    "opackets": 50000,
                }
            },
        }
        db.ingest(self.conn, data)

        # Verify all tables have data
        tables = ["hosts", "cpu_stats", "cpu_info", "memory", "filesystems", "disk_devices_linux", "net_interfaces"]
        for table in tables:
            cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            self.assertGreater(count, 0, f"{table} should have at least one row")

    def test_ingest_aix_full(self):
        """Ingest a complete AIX payload."""
        data = {
            "system_id": "aix-host",
            "collected_at": 1234567890.0,
            "hostname": "aix-box",
            "platform": "aix",
            "collection_errors": {},
            "cloud": False,
            "cpustats": {"user_ticks": 100, "sys_ticks": 50, "idle_ticks": 800},
            "cpus": {},  # AIX per-CPU enumeration (skipped in db.py)
            "memory": {
                "memory": {"mem_total": 1000000, "mem_free": 500000},
                "slabs": False,
            },
            "filesystems": {
                "/": {
                    "mountpoint": "/",
                    "dev": "/dev/hd1",
                    "vfs": "jfs2",
                    "mounted": 1,
                    "options": "rw",
                    "bytes_total": 1000000000,
                    "bytes_free": 500000000,
                    "bytes_available": 500000000,
                    "pct_used": 50.0,
                    "pct_available": 50.0,
                    "pct_free": 50.0,
                    "pct_reserved": 5.0,
                    "f_files": 1000,
                    "f_ffree": 500,
                    "f_favail": 500,
                    "f_flag": 0,
                }
            },
            "disks": {
                "hdisk0": {
                    "name": "hdisk0",
                    "read_ios": 1000,
                    "read_blocks": 100000,
                    "write_ios": 500,
                    "write_blocks": 50000,
                }
            },
            "disk_total": {
                "ndisks": 1,
                "size_bytes": 1000000000,
                "free_bytes": 500000000,
                "read_ios": 1000,
                "write_ios": 500,
                "read_blocks": 100000,
                "write_blocks": 50000,
            },
            "network": {
                "en0": {
                    "ibytes": 10000000,
                    "ipackets": 100000,
                    "obytes": 5000000,
                    "opackets": 50000,
                }
            },
        }
        db.ingest(self.conn, data)

        # Verify AIX-specific tables
        cursor = self.conn.execute("SELECT COUNT(*) FROM disk_devices_aix")
        count = cursor.fetchone()[0]
        self.assertGreater(count, 0)

        cursor = self.conn.execute("SELECT COUNT(*) FROM disk_total")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1)

    def test_ingest_memory_slabs_false(self):
        """Ingest memory section where slabs=False returns empty list."""
        data = {
            "system_id": "test-002",
            "collected_at": 1234567890.0,
            "hostname": "myhost",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            "memory": {
                "memory": {"mem_total": 1000000, "mem_free": 500000},
                "slabs": False,
            },
        }
        db.ingest(self.conn, data)

        # Verify memory table has one row
        cursor = self.conn.execute("SELECT COUNT(*) FROM memory")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1)

        # Verify memory_slabs is empty
        cursor = self.conn.execute("SELECT COUNT(*) FROM memory_slabs")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)

    def test_ingest_memory_slabs_dict(self):
        """Ingest memory section where slabs is a dict creates rows."""
        data = {
            "system_id": "test-003",
            "collected_at": 1234567890.0,
            "hostname": "myhost",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            "memory": {
                "memory": {"mem_total": 1000000, "mem_free": 500000},
                "slabs": {
                    "kmalloc-32": {
                        "active_objs": 100,
                        "num_objs": 200,
                        "objsize": 32,
                    },
                    "kmalloc-64": {
                        "active_objs": 50,
                        "num_objs": 100,
                        "objsize": 64,
                    },
                },
            },
        }
        db.ingest(self.conn, data)

        # Verify memory_slabs has two rows
        cursor = self.conn.execute("SELECT COUNT(*) FROM memory_slabs")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 2)

    def test_ingest_missing_sections(self):
        """Ingest payload with missing optional sections creates no rows for those tables."""
        data = {
            "system_id": "test-004",
            "collected_at": 1234567890.0,
            "hostname": "myhost",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            # No filesystems, disks, or network sections
        }
        db.ingest(self.conn, data)

        # Verify hosts was created (required)
        cursor = self.conn.execute("SELECT COUNT(*) FROM hosts")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1)

        # Verify optional tables are empty
        cursor = self.conn.execute("SELECT COUNT(*) FROM filesystems")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)

        cursor = self.conn.execute("SELECT COUNT(*) FROM disk_devices_linux")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)

        cursor = self.conn.execute("SELECT COUNT(*) FROM net_interfaces")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)

    def test_ingest_transaction_rollback_on_error(self):
        """If an error occurs during ingest, the entire transaction rolls back."""
        data = {
            "system_id": "test-005",
            "collected_at": 1234567890.0,
            "hostname": "myhost",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            "cpustats": {
                "user_ticks": 100,
                "sys_ticks": 50,
                "idle_ticks": 800,
            },
        }

        # Mock transform_cpu_stats to raise an error mid-transaction
        with patch("receiver.db.transform_cpu_stats", side_effect=ValueError("test error")):
            with self.assertRaises(ValueError):
                db.ingest(self.conn, data)

        # Verify host record was NOT created (transaction rolled back)
        cursor = self.conn.execute("SELECT COUNT(*) FROM hosts")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)

    def test_ingest_preserves_extra_json_fields(self):
        """Ingest preserves extra_json bundle from transform functions."""
        data = {
            "system_id": "test-006",
            "collected_at": 1234567890.0,
            "hostname": "myhost",
            "platform": "linux",
            "collection_errors": {},
            "cloud": False,
            "memory": {
                "memory": {
                    "mem_total": 1000000,
                    "mem_free": 500000,
                    "unknown_field": 123,
                },
                "slabs": False,
            },
        }
        db.ingest(self.conn, data)

        # Verify memory row has extra_json populated
        cursor = self.conn.execute(
            "SELECT extra_json FROM memory WHERE mem_total = ?", (1000000,)
        )
        result = cursor.fetchone()
        self.assertIsNotNone(result[0])
        # Parse JSON to verify it contains unknown_field
        extra = json.loads(result[0])
        self.assertIn("unknown_field", extra)
        self.assertEqual(extra["unknown_field"], 123)


if __name__ == "__main__":
    unittest.main()
