"""SQLite database layer for UptimeDown receiver ingestion."""

import sqlite3
import logging
from .transform import (
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

logger = logging.getLogger("receiver")


# SQLite schema: all CREATE TABLE statements
_SCHEMA_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS hosts (
    id          INTEGER PRIMARY KEY,
    system_id   TEXT    NOT NULL UNIQUE,
    hostname    TEXT    NOT NULL,
    platform    TEXT    NOT NULL,
    first_seen  REAL    NOT NULL,
    last_seen   REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS cpu_info (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL,
    recorded_at     REAL,
    cpu_count       INTEGER,
    cpu_count_cfg   INTEGER,
    vendor_id       TEXT,
    model_name      TEXT,
    cpu_family      TEXT,
    model           INTEGER,
    stepping        INTEGER,
    cpu_cores       INTEGER,
    siblings        INTEGER,
    cpu_mhz         REAL,
    cache_size      TEXT,
    flags           TEXT,
    description     TEXT,
    processor_hz    INTEGER,
    FOREIGN KEY (host_id) REFERENCES hosts(id)
);

CREATE TABLE IF NOT EXISTS cpu_stats (
    id                      INTEGER PRIMARY KEY,
    host_id                 INTEGER NOT NULL,
    collected_at            REAL    NOT NULL,
    user_ticks              INTEGER,
    sys_ticks               INTEGER,
    idle_ticks              INTEGER,
    iowait_ticks            INTEGER,
    nice_ticks              INTEGER,
    irq_ticks               INTEGER,
    softirq_ticks           INTEGER,
    steal_ticks             INTEGER,
    guest_ticks             INTEGER,
    guest_nice_ticks        INTEGER,
    ctxt                    INTEGER,
    btime                   INTEGER,
    processes               INTEGER,
    procs_running           INTEGER,
    procs_blocked           INTEGER,
    ncpus                   INTEGER,
    ncpus_cfg               INTEGER,
    ncpus_enumerated        INTEGER,
    syscall                 INTEGER,
    sysread                 INTEGER,
    syswrite                INTEGER,
    sysfork                 INTEGER,
    sysexec                 INTEGER,
    readch                  INTEGER,
    writech                 INTEGER,
    devintrs                INTEGER,
    softintrs               INTEGER,
    runque                  INTEGER,
    swpque                  INTEGER,
    runocc                  INTEGER,
    swpocc                  INTEGER,
    loadavg_1               REAL,
    loadavg_5               REAL,
    loadavg_15              REAL,
    idle_donated_purr       INTEGER,
    idle_donated_spurr      INTEGER,
    busy_donated_purr       INTEGER,
    busy_donated_spurr      INTEGER,
    idle_stolen_purr        INTEGER,
    idle_stolen_spurr       INTEGER,
    busy_stolen_purr        INTEGER,
    busy_stolen_spurr       INTEGER,
    puser_spurr             INTEGER,
    psys_spurr              INTEGER,
    pidle_spurr             INTEGER,
    pwait_spurr             INTEGER,
    FOREIGN KEY (host_id) REFERENCES hosts(id)
);

CREATE TABLE IF NOT EXISTS memory (
    id                  INTEGER PRIMARY KEY,
    host_id             INTEGER NOT NULL,
    collected_at        REAL    NOT NULL,
    mem_total           INTEGER,
    mem_free            INTEGER,
    mem_available       INTEGER,
    mem_cached          INTEGER,
    swap_total          INTEGER,
    swap_free           INTEGER,
    buffers             INTEGER,
    swap_cached         INTEGER,
    active              INTEGER,
    inactive            INTEGER,
    dirty               INTEGER,
    writeback           INTEGER,
    slab                INTEGER,
    s_reclaimable       INTEGER,
    s_unreclaim         INTEGER,
    anon_pages          INTEGER,
    mapped              INTEGER,
    huge_pages_total    INTEGER,
    huge_pages_free     INTEGER,
    huge_page_size      INTEGER,
    extra_json          TEXT,
    FOREIGN KEY (host_id) REFERENCES hosts(id)
);

CREATE TABLE IF NOT EXISTS memory_slabs (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL,
    collected_at    REAL    NOT NULL,
    slab_name       TEXT    NOT NULL,
    active_objs     INTEGER,
    num_objs        INTEGER,
    objsize          INTEGER,
    objperslab      INTEGER,
    pagesperslab    INTEGER,
    "limit"         INTEGER,
    batchcount      INTEGER,
    sharedfactor    INTEGER,
    active_slabs    INTEGER,
    num_slabs       INTEGER,
    sharedavail     INTEGER,
    FOREIGN KEY (host_id) REFERENCES hosts(id)
);

CREATE TABLE IF NOT EXISTS filesystems (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL,
    collected_at    REAL    NOT NULL,
    mountpoint      TEXT    NOT NULL,
    mounted         INTEGER NOT NULL,
    fs_rdonly       INTEGER NOT NULL DEFAULT 0,
    dev             TEXT,
    vfs             TEXT,
    fs_log          TEXT,
    mount_auto      TEXT,
    fs_type         TEXT,
    options         TEXT,
    bytes_total     INTEGER,
    bytes_free      INTEGER,
    bytes_available INTEGER,
    pct_used        REAL,
    pct_available   REAL,
    pct_free        REAL,
    pct_reserved    REAL,
    f_files         INTEGER,
    f_ffree         INTEGER,
    f_favail        INTEGER,
    FOREIGN KEY (host_id) REFERENCES hosts(id)
);

CREATE TABLE IF NOT EXISTS disk_total (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL,
    collected_at    REAL    NOT NULL,
    ndisks          INTEGER,
    size_bytes      INTEGER,
    free_bytes      INTEGER,
    xfers           INTEGER,
    read_ios        INTEGER,
    write_ios       INTEGER,
    read_blocks     INTEGER,
    write_blocks    INTEGER,
    read_ticks      INTEGER,
    write_ticks     INTEGER,
    time            INTEGER,
    min_rserv       INTEGER,
    max_rserv       INTEGER,
    min_wserv       INTEGER,
    max_wserv       INTEGER,
    rtimeout        INTEGER,
    wtimeout        INTEGER,
    rfailed         INTEGER,
    wfailed         INTEGER,
    wq_depth        INTEGER,
    wq_time         INTEGER,
    wq_min_time     INTEGER,
    wq_max_time     INTEGER,
    FOREIGN KEY (host_id) REFERENCES hosts(id)
);

CREATE TABLE IF NOT EXISTS disk_devices_aix (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL,
    collected_at    REAL    NOT NULL,
    name            TEXT    NOT NULL,
    description     TEXT,
    vgname          TEXT,
    adapter         TEXT,
    size_bytes      INTEGER,
    free_bytes      INTEGER,
    bsize           INTEGER,
    xfers           INTEGER,
    read_ios        INTEGER,
    write_ios       INTEGER,
    read_blocks     INTEGER,
    write_blocks    INTEGER,
    read_ticks      INTEGER,
    write_ticks     INTEGER,
    time            INTEGER,
    qdepth          INTEGER,
    q_full          INTEGER,
    q_sampled       INTEGER,
    paths_count     INTEGER,
    min_rserv       INTEGER,
    max_rserv       INTEGER,
    min_wserv       INTEGER,
    max_wserv       INTEGER,
    rtimeout        INTEGER,
    wtimeout        INTEGER,
    rfailed         INTEGER,
    wfailed         INTEGER,
    wq_depth        INTEGER,
    wq_sampled      INTEGER,
    wq_time         INTEGER,
    wq_min_time     INTEGER,
    wq_max_time     INTEGER,
    wpar_id         INTEGER,
    dk_type         TEXT,
    FOREIGN KEY (host_id) REFERENCES hosts(id)
);

CREATE TABLE IF NOT EXISTS disk_devices_linux (
    id                      INTEGER PRIMARY KEY,
    host_id                 INTEGER NOT NULL,
    collected_at            REAL    NOT NULL,
    name                    TEXT    NOT NULL,
    major                   INTEGER NOT NULL,
    minor                   INTEGER NOT NULL,
    read_ios                INTEGER,
    read_merge              INTEGER,
    read_sectors            INTEGER,
    read_ticks              INTEGER,
    write_ios               INTEGER,
    write_merges            INTEGER,
    write_sectors           INTEGER,
    write_ticks             INTEGER,
    in_flight               INTEGER,
    total_io_ticks          INTEGER,
    total_time_in_queue     INTEGER,
    discard_ios             INTEGER,
    discard_merges          INTEGER,
    discard_sectors         INTEGER,
    discard_ticks           INTEGER,
    flush_ios               INTEGER,
    flush_ticks             INTEGER,
    extra_json              TEXT,
    FOREIGN KEY (host_id) REFERENCES hosts(id),
    UNIQUE (host_id, major, minor, collected_at)
);

CREATE TABLE IF NOT EXISTS net_interfaces (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL,
    collected_at    REAL    NOT NULL,
    iface           TEXT    NOT NULL,
    ibytes          INTEGER,
    ipackets        INTEGER,
    ierrors         INTEGER,
    obytes          INTEGER,
    opackets        INTEGER,
    oerrors         INTEGER,
    idrop           INTEGER,
    odrop           INTEGER,
    mtu             INTEGER,
    speed_mbps      INTEGER,
    type            INTEGER,
    operstate       TEXT,
    description     TEXT,
    FOREIGN KEY (host_id) REFERENCES hosts(id)
);

CREATE TABLE IF NOT EXISTS cloud_metadata (
    id                  INTEGER PRIMARY KEY,
    host_id             INTEGER NOT NULL,
    recorded_at         REAL,
    provider            TEXT,
    instance_id         TEXT,
    instance_type       TEXT,
    region              TEXT,
    availability_zone   TEXT,
    account_id          TEXT,
    ami_id              TEXT,
    architecture        TEXT,
    private_ip          TEXT,
    public_ip           TEXT,
    iam_profile         TEXT,
    instance_life_cycle TEXT,
    autoscaling_group   TEXT,
    tags_json           TEXT,
    extra_json          TEXT,
    FOREIGN KEY (host_id) REFERENCES hosts(id)
);
"""


def init_schema(conn):
    """Create all database tables if they don't exist.

    Args:
        conn: SQLite connection object
    """
    conn.executescript(_SCHEMA_DDL)
    conn.commit()

    # Validate foreign key integrity (development/test safety check)
    cursor = conn.execute("PRAGMA foreign_key_check")
    violations = cursor.fetchall()
    if violations:
        logger.warning("Foreign key violations detected in schema: %s", violations)


def upsert_host(conn, system_id, hostname, platform, collected_at) -> int:
    """Upsert a host record and return its id.

    If the host (identified by system_id) already exists, updates last_seen but
    preserves first_seen and the id. If new, creates it with first_seen = last_seen.

    Args:
        conn: SQLite connection
        system_id: unique agent identifier (from monitoring/identity.py)
        hostname: agent hostname
        platform: agent platform (sys.platform: "linux", "aix", etc.)
        collected_at: current collection timestamp

    Returns:
        int: host_id (primary key)
    """
    conn.execute(
        """
        INSERT INTO hosts (system_id, hostname, platform, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (system_id) DO UPDATE SET
            last_seen = excluded.last_seen,
            hostname = excluded.hostname
        """,
        (system_id, hostname, platform, collected_at, collected_at),
    )
    # Fetch the resulting id
    cursor = conn.execute(
        "SELECT id FROM hosts WHERE system_id = ?", (system_id,)
    )
    row = cursor.fetchone()
    return row[0]


def _insert_one(conn, table, row):
    """Insert a single row dict into the specified table.

    Column names are taken from the dict keys (which come from transform.py
    allowlists and are already sanitized). Table name is hardcoded, not from
    request data.

    Args:
        conn: SQLite connection
        table: table name (str, never from request data)
        row: dict mapping column name -> value
    """
    if not row:
        return
    if not isinstance(row, dict):
        logger.error("Malformed row for table %s: expected dict, got %s", table, type(row).__name__)
        return
    cols = list(row.keys())
    placeholders = ", ".join("?" * len(cols))
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    try:
        conn.execute(sql, [row[c] for c in cols])
    except KeyError as e:
        logger.error("Malformed row for table %s: missing key %s", table, e)
    except Exception as e:
        logger.error("Insert failed for table %s: %s", table, e)
        raise


def _insert_many(conn, table, rows):
    """Insert multiple row dicts into the specified table.

    All rows must have identical column keys.

    Args:
        conn: SQLite connection
        table: table name (str, never from request data)
        rows: list of row dicts
    """
    if not rows:
        return
    if not isinstance(rows, list):
        logger.error("Malformed rows for table %s: expected list, got %s", table, type(rows).__name__)
        return
    if not isinstance(rows[0], dict):
        logger.error("Malformed rows for table %s: expected list of dicts, got list of %s", table, type(rows[0]).__name__)
        return
    cols = list(rows[0].keys())
    placeholders = ", ".join("?" * len(cols))
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    try:
        conn.executemany(sql, [[r[c] for c in cols] for r in rows])
    except KeyError as e:
        logger.error("Malformed rows for table %s: missing key %s", table, e)
    except Exception as e:
        logger.error("Batch insert failed for table %s (%d rows): %s", table, len(rows), e)
        raise


def ingest(conn, data):
    """Transform and insert all sections from a validated payload.

    All inserts happen within a single transaction — if any insert fails,
    the entire payload rolls back.

    Args:
        conn: SQLite connection
        data: validated JSON payload dict (contains system_id, collected_at,
              hostname, platform, and optional section keys)

    Raises:
        Exception: on database error (connection will rollback)
    """
    system_id = data["system_id"]
    collected_at = data["collected_at"]
    hostname = data["hostname"]
    platform = data["platform"]

    with conn:
        # Upsert host and get its id
        host_id = upsert_host(conn, system_id, hostname, platform, collected_at)

        # Transform and insert each section that's present

        if "cpustats" in data:
            row = transform_cpu_stats(data["cpustats"], host_id, collected_at)
            _insert_one(conn, "cpu_stats", row)

        if "cpuinfo" in data:
            cpu_count = data["cpustats"].get("ncpus") if "cpustats" in data else None
            row = transform_cpu_info(
                data["cpuinfo"], host_id, collected_at, cpu_count
            )
            _insert_one(conn, "cpu_info", row)

        if "memory" in data:
            mem_row = transform_memory(
                data["memory"]["memory"], host_id, collected_at
            )
            _insert_one(conn, "memory", mem_row)
            slab_rows = transform_memory_slabs(
                data["memory"]["slabs"], host_id, collected_at
            )
            _insert_many(conn, "memory_slabs", slab_rows)

        if "filesystems" in data:
            rows = transform_filesystems(data["filesystems"], host_id, collected_at)
            _insert_many(conn, "filesystems", rows)

        if "disks" in data:
            # Platform-explicit disk routing:
            # - AIX: perfstat_disk_total() provides native aggregate; transform returns (device_rows, total_row)
            # - Linux: aggregate disk stats at collection time by summing per-device counters across all disks
            # Using platform instead of "disk_total" presence makes intent explicit and handles edge cases.
            if platform == "aix" and "disk_total" in data:
                # AIX path: transform returns (disk_rows, total_row)
                disk_rows, total_row = transform_disks_aix(
                    data["disks"], data["disk_total"], host_id, collected_at
                )
                _insert_many(conn, "disk_devices_aix", disk_rows)
                _insert_one(conn, "disk_total", total_row)
            elif platform == "linux":
                # Linux path: transform returns list of device rows + one aggregate row
                rows = transform_disks_linux(data["disks"], host_id, collected_at)
                _insert_many(conn, "disk_devices_linux", rows)
                # Compute and insert aggregate disk stats
                total_row = transform_disk_total_linux(
                    data["disks"], host_id, collected_at
                )
                _insert_one(conn, "disk_total", total_row)
            else:
                logger.warning(
                    "Unexpected platform %s for disk ingest; skipping disks section",
                    platform,
                )

        if "network" in data:
            rows = transform_network(data["network"], host_id, collected_at)
            _insert_many(conn, "net_interfaces", rows)
