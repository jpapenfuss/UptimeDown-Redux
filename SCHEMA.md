# UptimeDown SQLite Schema

This document defines the SQLite schema for persisting monitoring data collected
by UptimeDown. It is the authoritative reference — update it whenever the schema
changes before modifying the database code.

---

## Design Principles

- **One row per sample per object.** Every collection run inserts new rows; no
  upserts. Historical data is preserved for trending.
- **`collected_at` is a Unix timestamp** (REAL, seconds since epoch) matching the
  `_time` value from the gatherer dict wherever available.
- **`host_id` foreign-key** ties every row to the `hosts` table so the same
  database can store data from multiple monitored systems.
- **NULL is intentional.** Fields that are optional on a given platform or
  unavailable on a given run are stored as NULL rather than a sentinel value.
- **Cumulative counters are stored as-is.** Rate calculations (IOPS, %CPU) are
  done at query time by differencing adjacent rows. This avoids data loss and
  keeps the schema simple.
- **Slab data is large and optional.** It goes in a separate table and is only
  populated when `/proc/slabinfo` is readable (i.e., when running as root).
- **Gatherer output keys match schema column names.** Normalization is done
  inside each gatherer module, not in the storage layer. The only exceptions are
  AIX-only and Linux-only fields (which are simply absent/NULL on the other
  platform) and the Linux disk table (see `disk_devices_linux` note below).
- **All column names are snake_case.** Gatherer dicts must use snake_case keys
  at output time (e.g. `bytes_total`, `pct_used`, `mem_total`). camelCase keys
  are never stored.
- **`bytes_total`/`bytes_free`/`bytes_available` use `f_frsize`** (fundamental
  block size) on both platforms, not `f_bsize` (preferred I/O block size).
  These differ on some filesystems; `f_frsize` is the POSIX-correct value.

---

## Tables

### `hosts`

One row per monitored host. Populated automatically the first time a host reports.

```sql
CREATE TABLE IF NOT EXISTS hosts (
    id          INTEGER PRIMARY KEY,
    hostname    TEXT    NOT NULL,
    platform    TEXT    NOT NULL,   -- 'linux', 'aix', 'darwin', etc. (sys.platform)
    first_seen  REAL    NOT NULL,   -- Unix timestamp
    last_seen   REAL    NOT NULL    -- updated on each collection run
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_hosts_hostname ON hosts (hostname);
```

---

### `cpu_stats`

One row per collection run. Stores cumulative tick counters (AIX and Linux)
plus AIX-specific LPAR and PURR/SPURR fields.

All tick/counter fields are `INTEGER` (cumulative since boot or since counter
start). `NULL` for fields not available on the current platform.

```sql
CREATE TABLE IF NOT EXISTS cpu_stats (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,   -- _time from gatherer

    -- Available on both Linux and AIX
    user_ticks      INTEGER,    -- time in user mode          (Linux: 'user', AIX: 'user')
    nice_ticks      INTEGER,    -- time in user mode (niced)  (Linux only)
    sys_ticks       INTEGER,    -- time in kernel mode        (Linux: 'system', AIX: 'sys')
    idle_ticks      INTEGER,    -- idle time                  (Linux: 'idle', AIX: 'idle')
    iowait_ticks    INTEGER,    -- waiting for I/O            (Linux: 'iowait', AIX: 'wait')
    irq_ticks       INTEGER,    -- servicing hardware IRQs    (Linux only)
    softirq_ticks   INTEGER,    -- servicing soft IRQs        (Linux only)
    steal_ticks     INTEGER,    -- stolen by hypervisor       (Linux only)
    guest_ticks     INTEGER,    -- running virtual CPU        (Linux only)

    -- Linux-specific system-wide stats (from /proc/stat non-cpu lines)
    ctxt            INTEGER,    -- total context switches
    btime           INTEGER,    -- boot time (Unix timestamp)
    processes       INTEGER,    -- processes forked since boot
    procs_running   INTEGER,    -- currently runnable
    procs_blocked   INTEGER,    -- blocked on I/O

    -- AIX: CPU topology
    ncpus           INTEGER,    -- online CPUs
    ncpus_cfg       INTEGER,    -- configured CPUs (may exceed online)
    ncpus_high      INTEGER,    -- highest online CPU index seen
    description     TEXT,       -- processor description string (e.g. 'PowerPC_POWER8')
    processor_hz    INTEGER,    -- processor frequency in Hz

    -- AIX: additional counters
    pswitch         INTEGER,    -- process switches
    syscall         INTEGER,    -- system calls
    sysread         INTEGER,    -- read system calls
    syswrite        INTEGER,    -- write system calls
    sysfork         INTEGER,    -- fork system calls
    sysexec         INTEGER,    -- exec system calls
    readch          INTEGER,    -- bytes read
    writech         INTEGER,    -- bytes written
    devintrs        INTEGER,    -- device interrupts
    softintrs       INTEGER,    -- software interrupts
    lbolt           INTEGER,    -- ticks since boot (time_t)
    runque          INTEGER,    -- processes in run queue
    swpque          INTEGER,    -- processes in swap queue
    runocc          INTEGER,    -- run queue occupancy samples
    swpocc          INTEGER,    -- swap queue occupancy samples

    -- AIX: load average (fixed-point, divide by 65536.0 for float)
    loadavg_1       INTEGER,    -- 1-minute  load average (raw FSCALE units)
    loadavg_5       INTEGER,    -- 5-minute  load average
    loadavg_15      INTEGER,    -- 15-minute load average

    -- AIX: LPAR PURR/SPURR donated/stolen cycle counters (POWER hypervisor)
    idle_donated_purr   INTEGER,
    idle_donated_spurr  INTEGER,
    busy_donated_purr   INTEGER,
    busy_donated_spurr  INTEGER,
    idle_stolen_purr    INTEGER,
    idle_stolen_spurr   INTEGER,
    busy_stolen_purr    INTEGER,
    busy_stolen_spurr   INTEGER,
    puser_spurr         INTEGER,
    psys_spurr          INTEGER,
    pidle_spurr         INTEGER,
    pwait_spurr         INTEGER,
    spurrflag           INTEGER,

    -- AIX: hyperpage/huge-page interrupts
    hpi                 INTEGER,    -- hyperpage interrupts
    hpit                INTEGER,    -- hyperpage interrupt time

    -- AIX: version field from struct
    version             INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cpu_stats_host_time
    ON cpu_stats (host_id, collected_at);
```

---

### `disk_total`

Aggregate I/O stats across all disks. One row per collection run.
AIX source: `perfstat_disk_total_t`. Linux: to be added when linux_disk.py is
complete.

```sql
CREATE TABLE IF NOT EXISTS disk_total (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,

    ndisks          INTEGER,    -- number of disks
    size_mb         INTEGER,    -- total disk capacity in MB
    free_mb         INTEGER,    -- total free space in MB
    xfers           INTEGER,    -- total I/O operations since boot
    xrate           INTEGER,    -- read transfers since boot (__rxfers)
    rblks           INTEGER,    -- 512-byte blocks read
    wblks           INTEGER,    -- 512-byte blocks written
    rserv           INTEGER,    -- cumulative read service time (ms)
    wserv           INTEGER,    -- cumulative write service time (ms)
    min_rserv       INTEGER,
    max_rserv       INTEGER,
    min_wserv       INTEGER,
    max_wserv       INTEGER,
    rtimeout        INTEGER,    -- read timeouts
    wtimeout        INTEGER,    -- write timeouts
    rfailed         INTEGER,    -- failed reads
    wfailed         INTEGER,    -- failed writes
    wq_depth        INTEGER,    -- write queue depth samples
    wq_time         INTEGER,    -- write queue time
    wq_min_time     INTEGER,
    wq_max_time     INTEGER,
    version         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_disk_total_host_time
    ON disk_total (host_id, collected_at);
```

---

### `disk_devices`

Per-disk stats. One row per disk per collection run.
AIX source: `perfstat_disk_t`. Linux: `/proc/diskstats` (future).

```sql
CREATE TABLE IF NOT EXISTS disk_devices (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,

    name            TEXT    NOT NULL,   -- disk name (e.g. 'hdisk0', 'sda')
    description     TEXT,               -- human-readable disk description
    vgname          TEXT,               -- volume group name (AIX LVM)
    adapter         TEXT,               -- adapter/controller name
    size_mb         INTEGER,            -- disk capacity in MB
    free_mb         INTEGER,            -- free MB (unallocated to LVM PPs)
    bsize           INTEGER,            -- bytes per block for this disk
    xfers           INTEGER,            -- total transfers (r+w)
    xrate           INTEGER,            -- read transfers (__rxfers on AIX)
    rblks           INTEGER,            -- 512-byte blocks read
    wblks           INTEGER,            -- 512-byte blocks written
    qdepth          INTEGER,            -- I/O queue depth
    q_full          INTEGER,            -- queue-full events
    q_sampled       INTEGER,            -- queue depth sample count
    paths_count     INTEGER,            -- multipath path count
    rserv           INTEGER,            -- cumulative read service time (ms)
    wserv           INTEGER,            -- cumulative write service time (ms)
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
    wpar_id         INTEGER,            -- WPAR ID (0 = global LPAR)
    dk_type         INTEGER,            -- device type code
    version         INTEGER
);

CREATE INDEX IF NOT EXISTS idx_disk_devices_host_time
    ON disk_devices (host_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_disk_devices_host_name
    ON disk_devices (host_id, name, collected_at);
```

> **Linux disk note:** Linux `/proc/diskstats` exposes sector-level I/O counters
> (`read_ios`, `read_sectors`, `write_ios`, `write_sectors`, `read_ticks`, etc.)
> with no capacity or service-time fields — structurally incompatible with the
> AIX perfstat columns above. Linux disk data will go in a separate
> `disk_devices_linux` table (to be added when `linux_disk.py` is complete).

---

### `net_interfaces`

Per-interface network counters. One row per interface per collection run.
All counter fields are cumulative since boot; compute rates by differencing
adjacent rows at query time.

Linux source: `/proc/net/dev`. AIX source: `perfstat_netinterface_t`.
Platform-specific columns are NULL on the other platform.

```sql
CREATE TABLE IF NOT EXISTS net_interfaces (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,

    iface           TEXT    NOT NULL,   -- interface name (e.g. 'eth0', 'en0', 'en1')

    -- Available on both Linux (/proc/net/dev) and AIX (perfstat_netinterface_t)
    ibytes          INTEGER,    -- bytes received
    ipackets        INTEGER,    -- packets received
    ierrors         INTEGER,    -- input errors
    obytes          INTEGER,    -- bytes sent
    opackets        INTEGER,    -- packets sent
    oerrors         INTEGER,    -- output errors
    collisions      INTEGER,    -- collisions (CSMA interfaces)

    -- Linux-only fields (from /proc/net/dev column order)
    idrop           INTEGER,    -- rx packets dropped
    ififo           INTEGER,    -- rx FIFO buffer errors
    iframe          INTEGER,    -- rx frame alignment errors
    icompressed     INTEGER,    -- rx compressed packets
    imulticast      INTEGER,    -- rx multicast frames
    odrop           INTEGER,    -- tx packets dropped
    ofifo           INTEGER,    -- tx FIFO buffer errors
    ocarrier        INTEGER,    -- tx carrier sense errors
    ocompressed     INTEGER,    -- tx compressed packets

    -- AIX-only fields (from perfstat_netinterface_t)
    mtu             INTEGER,    -- maximum transmission unit (bytes)
    bitrate         INTEGER,    -- adapter link speed (bits/sec)
    if_iqdrops      INTEGER,    -- input queue drops
    if_arpdrops     INTEGER,    -- drops due to missing ARP entry
    description     TEXT,       -- adapter description from ODM (e.g. 'Virtual I/O Ethernet Adapter')
    type            INTEGER     -- interface type code (1=Ethernet, 6=token ring, etc.)
);

CREATE INDEX IF NOT EXISTS idx_net_interfaces_host_time
    ON net_interfaces (host_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_net_interfaces_host_iface
    ON net_interfaces (host_id, iface, collected_at);
```

---

### `filesystems`

One row per configured filesystem per collection run. Covers both mounted and
unmounted filesystems (e.g. WPAR filesystems that are offline).

`mounted = 1` rows have space stats populated; `mounted = 0` rows have only
config fields from `/etc/filesystems` (AIX) or `/proc/mounts` (Linux).

```sql
CREATE TABLE IF NOT EXISTS filesystems (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,

    mountpoint      TEXT    NOT NULL,
    mounted         INTEGER NOT NULL,   -- 1 if statvfs succeeded, 0 otherwise

    -- Config fields (always present where source provides them)
    dev             TEXT,               -- block device (e.g. /dev/hd1, /dev/sda1)
    vfs             TEXT,               -- filesystem type (jfs2, ext4, xfs, ...)
    fs_log          TEXT,               -- journal log device (AIX: 'log' field)
    mount_auto      TEXT,               -- mount=automatic/true/false from /etc/filesystems
    fs_type         TEXT,               -- WPAR name or class (AIX 'type' field)
    account         TEXT,               -- accounting flag
    options         TEXT,               -- mount options string

    -- Space stats (NULL when mounted = 0, or when f_blocks = 0)
    -- Truncated to 4 decimal places at collection time (never scientific notation).
    bytes_total     INTEGER,            -- f_frsize * f_blocks
    bytes_free      INTEGER,            -- f_frsize * f_bfree
    bytes_available INTEGER,            -- f_frsize * f_bavail (excludes reserved)
    pct_used        REAL,               -- (1 - f_bfree/f_blocks) * 100, truncated
    pct_available   REAL,               -- (f_bavail/f_blocks) * 100, truncated
    pct_free        REAL,               -- (f_bfree/f_blocks) * 100, truncated
    pct_reserved    REAL,               -- (1 - f_bavail/f_blocks) * 100, truncated

    -- Raw statvfs fields (NULL when not mounted)
    f_bsize         INTEGER,            -- preferred I/O block size
    f_frsize        INTEGER,            -- fundamental block size
    f_blocks        INTEGER,            -- total blocks
    f_bfree         INTEGER,            -- free blocks
    f_bavail        INTEGER,            -- free blocks available to non-root
    f_files         INTEGER,            -- total inodes
    f_ffree         INTEGER,            -- free inodes
    f_favail        INTEGER             -- free inodes available to non-root
);

CREATE INDEX IF NOT EXISTS idx_filesystems_host_time
    ON filesystems (host_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_filesystems_host_mp
    ON filesystems (host_id, mountpoint, collected_at);
-- Fast lookup for "is this WPAR filesystem nearly full when it comes online?"
CREATE INDEX IF NOT EXISTS idx_filesystems_mounted
    ON filesystems (host_id, mounted, pct_used);
```

---

### `memory` (Linux only)

One row per collection run. All `/proc/meminfo` fields stored as bytes (already
converted by `util.tobytes()`). Column names are the `/proc/meminfo` field names
with the colon stripped, lowercased, and converted to snake_case
(e.g. `MemTotal` → `mem_total`, `HugePages_Total` → `huge_pages_total`).
This conversion is done inside `linux_memory.py` at output time.

Only the most universally present fields are listed below. Additional fields
present on the host are serialised to the `extra_json` column as a JSON object
so that schema changes are not required for every kernel version.

```sql
CREATE TABLE IF NOT EXISTS memory (
    id                  INTEGER PRIMARY KEY,
    host_id             INTEGER NOT NULL REFERENCES hosts(id),
    collected_at        REAL    NOT NULL,

    mem_total           INTEGER,    -- MemTotal
    mem_free            INTEGER,    -- MemFree
    mem_available       INTEGER,    -- MemAvailable
    buffers             INTEGER,    -- Buffers
    cached              INTEGER,    -- Cached
    swap_cached         INTEGER,    -- SwapCached
    active              INTEGER,    -- Active
    inactive            INTEGER,    -- Inactive
    swap_total          INTEGER,    -- SwapTotal
    swap_free           INTEGER,    -- SwapFree
    dirty               INTEGER,    -- Dirty
    writeback           INTEGER,    -- Writeback
    slab                INTEGER,    -- Slab
    s_reclaimable       INTEGER,    -- SReclaimable
    s_unreclaim         INTEGER,    -- SUnreclaim
    anon_pages          INTEGER,    -- AnonPages
    mapped              INTEGER,    -- Mapped
    huge_pages_total    INTEGER,    -- HugePages_Total (count, not bytes)
    huge_pages_free     INTEGER,    -- HugePages_Free
    huge_page_size      INTEGER,    -- Hugepagesize (bytes)

    extra_json          TEXT        -- JSON object with any remaining fields
);

CREATE INDEX IF NOT EXISTS idx_memory_host_time
    ON memory (host_id, collected_at);
```

---

### `memory_slabs` (Linux only, root required)

One row per slab per collection run from `/proc/slabinfo`.

```sql
CREATE TABLE IF NOT EXISTS memory_slabs (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,

    slab_name       TEXT    NOT NULL,
    active_objs     INTEGER,
    num_objs        INTEGER,
    objsize         INTEGER,
    objperslab      INTEGER,
    pagesperslab    INTEGER,
    limit           INTEGER,
    batchcount      INTEGER,
    sharedfactor    INTEGER,
    active_slabs    INTEGER,
    num_slabs       INTEGER,
    sharedavail     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_memory_slabs_host_time
    ON memory_slabs (host_id, collected_at);
```

---

## Notes on Derived Metrics

The schema stores raw counters, not derived rates. Compute rates at query time:

```sql
-- CPU utilisation % between two adjacent samples
SELECT
    100.0 * (b.sys_ticks - a.sys_ticks)
          / (b.user_ticks + b.sys_ticks + b.idle_ticks + b.iowait_ticks
           - a.user_ticks - a.sys_ticks - a.idle_ticks - a.iowait_ticks)
    AS pct_sys
FROM cpu_stats a
JOIN cpu_stats b ON b.host_id = a.host_id
    AND b.id = (SELECT MIN(id) FROM cpu_stats WHERE id > a.id AND host_id = a.host_id)
WHERE a.host_id = 1
ORDER BY a.collected_at DESC
LIMIT 10;

-- Disk read IOPS between two samples
SELECT
    (b.xrate - a.xrate) / (b.collected_at - a.collected_at) AS read_iops
FROM disk_total a
JOIN disk_total b ON b.host_id = a.host_id
    AND b.id = (SELECT MIN(id) FROM disk_total WHERE id > a.id AND host_id = a.host_id)
WHERE a.host_id = 1;

-- Network throughput (bytes/sec) on a given interface between two samples
SELECT
    n.iface,
    (b.ibytes - a.ibytes) / (b.collected_at - a.collected_at) AS rx_bytes_per_sec,
    (b.obytes - a.obytes) / (b.collected_at - a.collected_at) AS tx_bytes_per_sec
FROM net_interfaces a
JOIN net_interfaces b ON b.host_id = a.host_id AND b.iface = a.iface
    AND b.id = (SELECT MIN(id) FROM net_interfaces WHERE id > a.id AND host_id = a.host_id AND iface = a.iface)
JOIN net_interfaces n ON n.id = a.id
WHERE a.host_id = 1 AND a.iface = 'eth0'
ORDER BY a.collected_at DESC LIMIT 10;
```

## AIX loadavg Conversion

The `loadavg_*` fields are stored as raw FSCALE-fixed-point integers (AIX uses
FSCALE = 65536). To convert to the familiar float:

```sql
SELECT loadavg_1 / 65536.0 AS load_1min FROM cpu_stats WHERE host_id = 1 ORDER BY collected_at DESC LIMIT 1;
```
