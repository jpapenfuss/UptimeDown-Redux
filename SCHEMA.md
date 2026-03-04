# UptimeDown Database Schema

This document defines the SQL schema for persisting monitoring data collected by
UptimeDown. It is the authoritative reference — update it whenever the schema changes
before modifying database or ingestion code.

---

## Database Target

The canonical deployment is a **central PostgreSQL database** receiving data from
multiple decentralized agents. PostgreSQL is recommended over SQLite for any
multi-host setup because:

- Multiple agents write concurrently; SQLite's write lock does not scale
- PostgreSQL's `LAG()` / `LEAD()` window functions are standard and efficient
- Partitioning by time (`collected_at`) becomes practical at scale

**SQLite** is acceptable for single-host local dev/testing or as an agent-side
write buffer before forwarding to the central store. The schema is written in
standard SQL; the only SQLite-specific quirk is `INTEGER PRIMARY KEY` (implicit
rowid alias). PostgreSQL would use `BIGSERIAL PRIMARY KEY` or `GENERATED ALWAYS AS IDENTITY`.

---

## Design Principles

- **One row per sample per object.** Every collection run inserts new rows; no
  upserts. Historical data is preserved for trending.

- **`collected_at` is a single Unix timestamp per collection run** (`REAL`, seconds
  since epoch, rounded to milliseconds). It is captured once in `__main__.py`
  before any gatherers run and written identically to every data table.
  Cross-subsystem joins use exact equality on `(host_id, collected_at)`.
  Gatherers do not emit per-object `_time` keys.

- **`host_id` foreign-key** ties every row to the `hosts` table so the same
  database stores data from multiple monitored systems.

- **NULL is intentional.** Fields that are optional on a given platform or
  unavailable on a given run are stored as NULL rather than a sentinel value.

- **Cumulative counters are stored as-is.** CPU tick counters, network byte
  counters, and disk I/O counters are cumulative since boot. Rate calculations
  (IOPS, %CPU, bytes/sec) are computed at query time using `LAG()` window
  functions. This avoids data loss and keeps the schema simple.

- **Point-in-time metrics need no differencing.** Memory (`mem_total`,
  `mem_available`), filesystem percentages (`pct_used`), and load averages are
  instantaneous values — query them directly for dashboard time-series.

- **Semi-static data goes in separate tables.** CPU hardware info (`cpu_info`)
  and cloud instance metadata (`cloud_metadata`) change infrequently. Store them
  separately rather than repeating them on every collection row.

- **All column names are snake_case.** Gatherer dicts must use snake_case keys
  at output time. camelCase keys are never stored.

- **`bytes_total`/`bytes_free`/`bytes_available` use `f_frsize`** (fundamental
  block size), not `f_bsize` (preferred I/O block size). These differ on some
  filesystems; `f_frsize` is the POSIX-correct value.

- **Slab data is large and optional.** It goes in a separate table and is only
  populated when `/proc/slabinfo` is readable (i.e., when running as root).

---

## Tables

### `hosts`

One row per monitored host. Populated automatically the first time a host reports.

In a distributed setup, `hostname` alone is insufficient to uniquely identify a host
(multiple datacenters may have identically-named systems). Use `system_id` as the
primary unique key for each reporting agent. `system_id` is assigned at agent
initialization and is immutable; the first report from a `system_id` creates the
host record.

```sql
CREATE TABLE IF NOT EXISTS hosts (
    id          INTEGER PRIMARY KEY,
    system_id   TEXT    NOT NULL,   -- unique agent identifier (UUID from identity.py)
    hostname    TEXT    NOT NULL,   -- human-readable hostname
    platform    TEXT    NOT NULL,   -- 'linux', 'aix', 'darwin', etc. (sys.platform)
    first_seen  REAL    NOT NULL,   -- Unix timestamp
    last_seen   REAL    NOT NULL    -- updated on each collection run
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_hosts_system_id ON hosts (system_id);
CREATE INDEX        IF NOT EXISTS idx_hosts_hostname   ON hosts (hostname);
```

---

### `cpu_info`

Semi-static CPU hardware facts. One row per change detection or agent startup.
This data changes rarely (hardware upgrades, SMT reconfigurations) and should not
be repeated on every `cpu_stats` row.

Source: Linux `/proc/cpuinfo` cpu0 stanza; AIX `perfstat_cpu_total_t` description
and frequency fields. Platform-specific columns are NULL on the other platform.

```sql
CREATE TABLE IF NOT EXISTS cpu_info (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    recorded_at     REAL    NOT NULL,   -- when this snapshot was captured

    -- Available on both platforms
    cpu_count       INTEGER,    -- logical CPU count online (Linux: nproc, AIX: ncpus)
    cpu_count_cfg   INTEGER,    -- configured CPUs (AIX: ncpus_cfg; NULL on Linux)

    -- Linux-specific (/proc/cpuinfo cpu0 stanza)
    vendor_id       TEXT,       -- e.g. 'GenuineIntel', 'AuthenticAMD'
    model_name      TEXT,       -- e.g. 'Intel(R) Xeon(R) Gold 6154'
    cpu_family      INTEGER,
    model           INTEGER,
    stepping        INTEGER,
    cpu_cores       INTEGER,    -- physical cores per socket
    siblings        INTEGER,    -- logical CPUs per socket (includes HT)
    cpu_mhz         REAL,       -- current frequency (varies with cpufreq)
    cache_size      TEXT,       -- raw string, e.g. '32768 KB'
    flags           TEXT,       -- space-separated capability flag string

    -- AIX-specific (perfstat_cpu_total_t)
    description     TEXT,       -- e.g. 'PowerPC_POWER8'
    processor_hz    INTEGER     -- processor frequency in Hz
);

CREATE INDEX IF NOT EXISTS idx_cpu_info_host_time ON cpu_info (host_id, recorded_at);
```

---

### `cpu_stats`

Aggregate CPU counters. One row per collection run.

All tick and counter fields are cumulative since boot. Compute utilization
percentages using `LAG()` at query time (see Dashboard Queries section).
NULL for fields not available on the current platform.

```sql
CREATE TABLE IF NOT EXISTS cpu_stats (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,

    -- Available on both Linux and AIX
    user_ticks      INTEGER,    -- time in user mode
    sys_ticks       INTEGER,    -- time in kernel mode   (Linux: 'system', AIX: 'sys')
    idle_ticks      INTEGER,    -- idle time
    iowait_ticks    INTEGER,    -- waiting for I/O       (Linux: 'iowait', AIX: 'wait')

    -- Linux-specific tick counters (NULL on AIX)
    nice_ticks      INTEGER,    -- time in user mode (niced)
    irq_ticks       INTEGER,    -- servicing hardware IRQs
    softirq_ticks   INTEGER,    -- servicing soft IRQs
    steal_ticks     INTEGER,    -- stolen by hypervisor
    guest_ticks     INTEGER,    -- running virtual CPU

    -- Linux: system-wide process counters from /proc/stat non-cpu lines
    ctxt            INTEGER,    -- total context switches since boot
    btime           INTEGER,    -- boot time (Unix timestamp)
    processes       INTEGER,    -- processes forked since boot
    procs_running   INTEGER,    -- currently runnable
    procs_blocked   INTEGER,    -- blocked on I/O

    -- AIX: CPU topology (NULL on Linux; use cpu_info for semi-static values)
    ncpus           INTEGER,    -- online CPUs this sample
    ncpus_cfg       INTEGER,    -- configured CPUs (may exceed online)
    ncpus_high      INTEGER,    -- highest online CPU index seen

    -- AIX: additional system-call and I/O counters
    pswitch         INTEGER,    -- process switches
    syscall         INTEGER,    -- system calls
    sysread         INTEGER,    -- read system calls
    syswrite        INTEGER,    -- write system calls
    sysfork         INTEGER,    -- fork system calls
    sysexec         INTEGER,    -- exec system calls
    readch          INTEGER,    -- bytes read via read(2)
    writech         INTEGER,    -- bytes written via write(2)
    devintrs        INTEGER,    -- device interrupts
    softintrs       INTEGER,    -- software interrupts
    lbolt           INTEGER,    -- ticks since boot
    runque          INTEGER,    -- processes in run queue
    swpque          INTEGER,    -- processes in swap queue
    runocc          INTEGER,    -- run queue occupancy samples
    swpocc          INTEGER,    -- swap queue occupancy samples

    -- AIX: load average (fixed-point; divide by 65536.0 for float value)
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

    -- AIX: hyperpage interrupts
    hpi                 INTEGER,
    hpit                INTEGER,

    version             INTEGER
);

CREATE INDEX IF NOT EXISTS idx_cpu_stats_host_time ON cpu_stats (host_id, collected_at);
```

---

### `memory`

One row per collection run. All size fields are in **bytes**.

Works for both Linux and AIX. Linux gathers from `/proc/meminfo` and normalizes
to snake_case. AIX normalizes `real_total` → `mem_total`, `real_free` → `mem_free`,
`numperm` → `mem_cached`, `pgsp_total` → `swap_total`, `pgsp_free` → `swap_free`.
Linux-specific fields (buffers, active, dirty, etc.) are NULL on AIX. AIX-specific
fields not in this table go in `extra_json`.

```sql
CREATE TABLE IF NOT EXISTS memory (
    id                  INTEGER PRIMARY KEY,
    host_id             INTEGER NOT NULL REFERENCES hosts(id),
    collected_at        REAL    NOT NULL,

    -- Core fields — available on both Linux and AIX (normalized)
    mem_total           INTEGER,    -- total physical RAM
    mem_free            INTEGER,    -- unused RAM
    mem_available       INTEGER,    -- RAM available for new allocations (Linux: MemAvailable; AIX: approximated)
    mem_cached          INTEGER,    -- page cache (Linux: Cached; AIX: numperm pages × page_size)
    swap_total          INTEGER,    -- total swap space
    swap_free           INTEGER,    -- free swap space

    -- Linux-specific (NULL on AIX)
    buffers             INTEGER,    -- block device buffer cache
    swap_cached         INTEGER,    -- swap pages cached in RAM
    active              INTEGER,    -- recently used pages (hard to reclaim)
    inactive            INTEGER,    -- older pages (easier to reclaim)
    dirty               INTEGER,    -- pages waiting to be written to disk
    writeback           INTEGER,    -- pages actively being written
    slab                INTEGER,    -- kernel slab allocator total
    s_reclaimable       INTEGER,    -- reclaimable slab memory
    s_unreclaim         INTEGER,    -- unreclaimable slab memory
    anon_pages          INTEGER,    -- anonymous (non-file-backed) pages
    mapped              INTEGER,    -- files mapped into memory
    huge_pages_total    INTEGER,    -- HugePages_Total (count, not bytes)
    huge_pages_free     INTEGER,    -- HugePages_Free (count)
    huge_page_size      INTEGER,    -- Hugepagesize in bytes

    extra_json          TEXT        -- JSON object for remaining /proc/meminfo or AIX-specific fields
);

CREATE INDEX IF NOT EXISTS idx_memory_host_time ON memory (host_id, collected_at);
```

---

### `memory_slabs` (Linux only, root required)

One row per slab allocator entry per collection run from `/proc/slabinfo`.
Omitted entirely when not running as root.

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

CREATE INDEX IF NOT EXISTS idx_memory_slabs_host_time ON memory_slabs (host_id, collected_at);
```

---

### `filesystems`

One row per configured filesystem per collection run.

`mounted = 1` rows have space stats populated; `mounted = 0` rows have only
config fields (AIX filesystems that are offline). Mountpoints repeat across
hosts — use `(host_id, mountpoint)` to identify a filesystem on a specific host.

```sql
CREATE TABLE IF NOT EXISTS filesystems (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,

    mountpoint      TEXT    NOT NULL,
    mounted         INTEGER NOT NULL,   -- 1 if statvfs succeeded, 0 otherwise

    -- Config fields (present where source provides them)
    dev             TEXT,               -- block device (e.g. /dev/sda1, /dev/hd1)
    vfs             TEXT,               -- filesystem type (ext4, xfs, jfs2, ...)
    fs_log          TEXT,               -- journal log device (AIX 'log' field)
    mount_auto      TEXT,               -- mount=automatic/true/false (/etc/filesystems)
    fs_type         TEXT,               -- WPAR name or class (AIX 'type' field)
    account         TEXT,               -- accounting flag
    options         TEXT,               -- mount options string

    -- Space stats (NULL when mounted = 0 or f_blocks = 0)
    -- Truncated to 4 decimal places at collection time.
    bytes_total     INTEGER,            -- f_frsize × f_blocks
    bytes_free      INTEGER,            -- f_frsize × f_bfree
    bytes_available INTEGER,            -- f_frsize × f_bavail (excludes root reserve)
    pct_used        REAL,               -- (1 - f_bfree/f_blocks) × 100
    pct_available   REAL,               -- (f_bavail/f_blocks) × 100
    pct_free        REAL,               -- (f_bfree/f_blocks) × 100
    pct_reserved    REAL,               -- (1 - f_bavail/f_blocks) × 100

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

CREATE INDEX IF NOT EXISTS idx_filesystems_host_time  ON filesystems (host_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_filesystems_host_mp    ON filesystems (host_id, mountpoint, collected_at);
CREATE INDEX IF NOT EXISTS idx_filesystems_mounted    ON filesystems (host_id, mounted, pct_used);
```

---

### `disk_total` (AIX only)

Aggregate I/O stats across all disks. One row per collection run.
Source: `perfstat_disk_total_t`. Linux has no equivalent — Linux disk data is
per-device only (see `disk_devices_linux`).

`rblks`/`wblks` are in **512-byte blocks** as defined by IBM's perfstat
documentation, regardless of the physical sector size of individual disks. This
is consistent with the Linux convention. The `bsize` field in `disk_devices_aix`
gives each disk's actual physical block size.

```sql
CREATE TABLE IF NOT EXISTS disk_total (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,

    ndisks          INTEGER,    -- number of disks
    size_bytes      INTEGER,    -- total disk capacity in bytes
    free_bytes      INTEGER,    -- total free space in bytes
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

CREATE INDEX IF NOT EXISTS idx_disk_total_host_time ON disk_total (host_id, collected_at);
```

---

### `disk_devices_aix` (AIX only)

Per-disk I/O stats. One row per disk per collection run.
Source: `perfstat_disk_t`. Linux uses a separate table — see `disk_devices_linux`.

```sql
CREATE TABLE IF NOT EXISTS disk_devices_aix (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,

    name            TEXT    NOT NULL,   -- disk name (e.g. 'hdisk0')
    description     TEXT,               -- human-readable disk description
    vgname          TEXT,               -- volume group name (AIX LVM)
    adapter         TEXT,               -- adapter/controller name
    size_bytes      INTEGER,            -- disk capacity in bytes
    free_bytes      INTEGER,            -- free bytes (unallocated LVM PPs)
    bsize           INTEGER,            -- bytes per block for this disk
    xfers           INTEGER,            -- total transfers (r+w)
    xrate           INTEGER,            -- read transfers (__rxfers)
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

CREATE INDEX IF NOT EXISTS idx_disk_devices_aix_host_time ON disk_devices_aix (host_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_disk_devices_aix_host_name ON disk_devices_aix (host_id, name, collected_at);
```

---

### `disk_devices_linux` (Linux only)

Per-device I/O counters from `/proc/diskstats`. One row per device per
collection run.

All counter fields are cumulative since boot. Tick counts are in milliseconds.

**Sector unit is always 512 bytes**, regardless of the physical sector size of the
drive. The Linux block layer hard-codes 512-byte logical sectors for all
`/proc/diskstats` counters — this applies to 4K Advanced Format drives, NVMe,
and all other media. To convert to bytes: multiply by 512. To get the actual
physical sector size, read `/sys/block/<dev>/queue/physical_block_size`
(available from the stubbed `get_sys_stats()` path in `linux_disk.py`).

`discard_*` and `flush_*` fields are zero on kernels < 4.18 and 5.5 respectively.

Device naming varies: `sda`/`sdb` (SCSI/SATA), `nvme0n1` (NVMe), `zd0` (ZFS
zvols), `md0` (software RAID), `dm-0` (device mapper/LVM). Use the composite key
`(host_id, major, minor)` to identify a device uniquely across hosts.

```sql
CREATE TABLE IF NOT EXISTS disk_devices_linux (
    id                  INTEGER PRIMARY KEY,
    host_id             INTEGER NOT NULL REFERENCES hosts(id),
    collected_at        REAL    NOT NULL,

    name                TEXT    NOT NULL,
    major               INTEGER NOT NULL,   -- kernel major device number
    minor               INTEGER NOT NULL,   -- kernel minor device number

    read_ios            INTEGER,    -- completed read I/Os
    read_merge          INTEGER,    -- adjacent reads merged by I/O scheduler
    read_sectors        INTEGER,    -- sectors read (512 bytes each)
    read_ticks          INTEGER,    -- time spent reading (ms)

    write_ios           INTEGER,    -- completed write I/Os
    write_merges        INTEGER,    -- adjacent writes merged
    write_sectors       INTEGER,    -- sectors written (512 bytes each)
    write_ticks         INTEGER,    -- time spent writing (ms)

    in_flight           INTEGER,    -- I/Os currently in flight
    total_io_ticks      INTEGER,    -- time device had I/O in flight (ms)
    total_time_in_queue INTEGER,    -- weighted time waiting in queue (ms)

    -- Discard counters (kernel >= 4.18, zero on older kernels — not NULL)
    discard_ios         INTEGER,
    discard_merges      INTEGER,
    discard_sectors     INTEGER,
    discard_ticks       INTEGER,

    -- Flush counters (kernel >= 5.5, zero on older kernels — not NULL)
    flush_ios           INTEGER,
    flush_ticks         INTEGER
);

CREATE INDEX        IF NOT EXISTS idx_disk_devices_linux_host_time
    ON disk_devices_linux (host_id, collected_at);
CREATE INDEX        IF NOT EXISTS idx_disk_devices_linux_host_name
    ON disk_devices_linux (host_id, name, collected_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_disk_devices_linux_device_identity
    ON disk_devices_linux (host_id, major, minor, collected_at);
```

---

### `net_interfaces`

Per-interface network counters. One row per interface per collection run.
All counter fields are cumulative since boot.

Linux source: `/proc/net/dev`. AIX source: `perfstat_netinterface_t`.
Platform-specific columns are NULL on the other platform.

Interface names repeat across hosts (`eth0`, `lo`). Use `(host_id, iface)` to
identify an interface on a specific host.

```sql
CREATE TABLE IF NOT EXISTS net_interfaces (
    id              INTEGER PRIMARY KEY,
    host_id         INTEGER NOT NULL REFERENCES hosts(id),
    collected_at    REAL    NOT NULL,

    iface           TEXT    NOT NULL,

    -- Available on both Linux and AIX
    ibytes          INTEGER,    -- bytes received
    ipackets        INTEGER,    -- packets received
    ierrors         INTEGER,    -- input errors
    obytes          INTEGER,    -- bytes sent
    opackets        INTEGER,    -- packets sent
    oerrors         INTEGER,    -- output errors
    collisions      INTEGER,    -- collisions (CSMA interfaces)

    -- Linux-only (NULL on AIX)
    idrop           INTEGER,    -- rx packets dropped
    ififo           INTEGER,    -- rx FIFO buffer errors
    iframe          INTEGER,    -- rx frame alignment errors
    icompressed     INTEGER,    -- rx compressed packets
    imulticast      INTEGER,    -- rx multicast frames
    odrop           INTEGER,    -- tx packets dropped
    ofifo           INTEGER,    -- tx FIFO buffer errors
    ocarrier        INTEGER,    -- tx carrier sense errors
    ocompressed     INTEGER,    -- tx compressed packets

    -- AIX-only (NULL on Linux)
    mtu             INTEGER,    -- maximum transmission unit (bytes)
    bitrate         INTEGER,    -- adapter link speed (bits/sec)
    if_iqdrops      INTEGER,    -- input queue drops
    if_arpdrops     INTEGER,    -- drops due to missing ARP entry
    description     TEXT,       -- adapter description from ODM
    type            INTEGER     -- interface type code (1=Ethernet, etc.)
);

CREATE INDEX IF NOT EXISTS idx_net_interfaces_host_time  ON net_interfaces (host_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_net_interfaces_host_iface ON net_interfaces (host_id, iface, collected_at);
```

---

### `cloud_metadata` (AWS EC2 only)

Semi-static EC2 instance attributes captured from IMDSv2 and optionally boto3.
One row per agent startup or when change is detected. Not inserted on every
collection run — changes infrequently.

```sql
CREATE TABLE IF NOT EXISTS cloud_metadata (
    id                  INTEGER PRIMARY KEY,
    host_id             INTEGER NOT NULL REFERENCES hosts(id),
    recorded_at         REAL    NOT NULL,

    provider            TEXT,           -- 'aws'
    instance_id         TEXT,           -- 'i-0abc123...'
    instance_type       TEXT,           -- 't3.medium', 'm5.xlarge', etc.
    region              TEXT,           -- 'us-east-1'
    availability_zone   TEXT,           -- 'us-east-1b'
    account_id          TEXT,
    ami_id              TEXT,
    architecture        TEXT,           -- 'x86_64' or 'arm64'
    private_ip          TEXT,
    public_ip           TEXT,           -- NULL if no public IP
    iam_profile         TEXT,           -- IAM instance profile ARN or NULL
    instance_life_cycle TEXT,           -- 'on-demand', 'spot', 'scheduled', 'capacity-block'
    autoscaling_group   TEXT,           -- ASG name or NULL
    tags_json           TEXT,           -- JSON object of instance tags
    extra_json          TEXT            -- JSON for less common/transient fields
);

CREATE INDEX IF NOT EXISTS idx_cloud_metadata_host ON cloud_metadata (host_id, recorded_at);
```

---

## Dashboard Queries

The following are the canonical query patterns the monitoring dashboard will use.

### Memory utilization across all nodes — time range

Memory is a point-in-time metric (no differencing required). This is the primary
query pattern: all monitored nodes, bounded time range, ordered for graphing.

```sql
SELECT
    h.hostname,
    m.collected_at,
    m.mem_total,
    m.mem_available,
    100.0 * (m.mem_total - m.mem_available) / NULLIF(m.mem_total, 0) AS pct_used
FROM memory m
JOIN hosts h ON h.id = m.host_id
WHERE m.collected_at BETWEEN :start AND :end
ORDER BY h.hostname, m.collected_at;
```

### CPU utilization across all nodes — time range

CPU tick counters are cumulative, requiring `LAG()` to compute utilization
between adjacent samples. Extend the query window back by one interval so the
first returned sample has a valid LAG value. Filter `pct_busy IS NOT NULL` in the
application layer to discard the first row per host.

```sql
SELECT
    h.hostname,
    c.collected_at,
    100.0 * (
        (c.user_ticks + c.sys_ticks + c.iowait_ticks
            + COALESCE(c.irq_ticks, 0) + COALESCE(c.softirq_ticks, 0) + COALESCE(c.steal_ticks, 0))
        - LAG(c.user_ticks + c.sys_ticks + c.iowait_ticks
            + COALESCE(c.irq_ticks, 0) + COALESCE(c.softirq_ticks, 0) + COALESCE(c.steal_ticks, 0))
            OVER w
    ) / NULLIF(
        (c.user_ticks + c.sys_ticks + c.idle_ticks + c.iowait_ticks
            + COALESCE(c.irq_ticks, 0) + COALESCE(c.softirq_ticks, 0) + COALESCE(c.steal_ticks, 0))
        - LAG(c.user_ticks + c.sys_ticks + c.idle_ticks + c.iowait_ticks
            + COALESCE(c.irq_ticks, 0) + COALESCE(c.softirq_ticks, 0) + COALESCE(c.steal_ticks, 0))
            OVER w,
        0
    ) AS pct_busy
FROM cpu_stats c
JOIN hosts h ON h.id = c.host_id
WHERE c.collected_at BETWEEN (:start - :interval) AND :end
WINDOW w AS (PARTITION BY c.host_id ORDER BY c.collected_at)
ORDER BY h.hostname, c.collected_at;
```

### Network throughput — single host, time range

```sql
SELECT
    iface,
    collected_at,
    (ibytes - LAG(ibytes) OVER w) / NULLIF(collected_at - LAG(collected_at) OVER w, 0) AS rx_bytes_per_sec,
    (obytes - LAG(obytes) OVER w) / NULLIF(collected_at - LAG(collected_at) OVER w, 0) AS tx_bytes_per_sec
FROM net_interfaces
WHERE host_id = :host_id
  AND collected_at BETWEEN (:start - :interval) AND :end
WINDOW w AS (PARTITION BY host_id, iface ORDER BY collected_at)
ORDER BY iface, collected_at;
```

### Disk IOPS — Linux, single device, time range

```sql
SELECT
    name,
    collected_at,
    (read_ios  - LAG(read_ios)  OVER w) / NULLIF(collected_at - LAG(collected_at) OVER w, 0) AS read_iops,
    (write_ios - LAG(write_ios) OVER w) / NULLIF(collected_at - LAG(collected_at) OVER w, 0) AS write_iops
FROM disk_devices_linux
WHERE host_id = :host_id
  AND name = :device
  AND collected_at BETWEEN (:start - :interval) AND :end
WINDOW w AS (PARTITION BY host_id, major, minor ORDER BY collected_at)
ORDER BY collected_at;
```

### Filesystem usage across multiple hosts

```sql
SELECT
    h.hostname,
    f.mountpoint,
    f.pct_used,
    f.bytes_total,
    f.bytes_available,
    f.collected_at
FROM filesystems f
JOIN hosts h ON h.id = f.host_id
WHERE h.system_id IN (:id1, :id2, :id3)
  AND f.collected_at BETWEEN :start AND :end
  AND f.mounted = 1
ORDER BY h.hostname, f.mountpoint, f.collected_at;
```

### Cross-subsystem join: CPU vs memory for one host

Works because `collected_at` is identical across all tables for a given run.

```sql
SELECT
    c.collected_at,
    100.0 * (m.mem_total - m.mem_available) / NULLIF(m.mem_total, 0) AS mem_pct_used,
    -- CPU pct_busy computed as above (abbreviated here)
    (c.user_ticks + c.sys_ticks - LAG(c.user_ticks + c.sys_ticks) OVER w)
        / NULLIF((c.user_ticks + c.sys_ticks + c.idle_ticks) - LAG(c.user_ticks + c.sys_ticks + c.idle_ticks) OVER w, 0)
        * 100.0 AS cpu_pct_busy
FROM cpu_stats c
JOIN memory m ON m.host_id = c.host_id AND m.collected_at = c.collected_at
WHERE c.host_id = :host_id
  AND c.collected_at BETWEEN (:start - :interval) AND :end
WINDOW w AS (PARTITION BY c.host_id ORDER BY c.collected_at)
ORDER BY c.collected_at;
```

---

## Distributed Monitoring: System Identification

### `system_id` Assignment

`system_id` must be globally unique, immutable, and operator-readable.
The current `identity.py` reads `/etc/machine-id` on Linux and `odmget` on AIX,
falling back to a random UUID. This works for single-host installs but has
implications at scale:

- **Recommended**: Supplement with a configured override in `config.ini`
  (`[agent] system_id = <your-assigned-id>`). This allows operators to assign
  meaningful IDs without changing hardware.
- **Avoid**: Pure hostnames are not globally unique across datacenters.

### Handling Overlapping Names

Multiple hosts will share device names, interface names, and mountpoints:

| Object | Disambiguate via |
|--------|-----------------|
| Network interface | `(host_id, iface)` |
| Block device | `(host_id, major, minor)` on Linux; `(host_id, name)` on AIX |
| Filesystem | `(host_id, mountpoint)` |

### Ingestion Architecture (to be designed)

The schema supports multi-host data but does not yet define how decentralized
agents deliver data to the central database. Key options and trade-offs:

| Approach | Pros | Cons |
|----------|------|------|
| **Direct DB write** | Simple; no intermediary | Agents need DB credentials; no buffering on network failure |
| **REST API (ingest service)** | Credentials stay server-side; can validate/transform; can buffer | Requires building and running an ingest service |
| **Message queue (Kafka, RabbitMQ)** | High throughput; durable; replay | Operational overhead of running a broker |
| **Agent-side SQLite buffer + sync** | Agents survive network outages; sync on reconnect | More complex agent code; conflict resolution needed |

For the initial implementation, a lightweight REST API (agents POST JSON; server
writes to PostgreSQL) is the recommended starting point. Agents already produce
a JSON document per collection cycle — the same structure can be POSTed verbatim
to an ingest endpoint that maps it to SQL rows.

### Retention and Cleanup

In a distributed setup with many hosts, row count grows as O(hosts × samples × metrics):

- A 60-second interval, 10 hosts, 365 days → ~5 million rows in `cpu_stats` alone
- Use time-based partitioning in PostgreSQL (`PARTITION BY RANGE (collected_at)`)
- Drop old partitions rather than row-by-row DELETE
- Index `collected_at` on every table (already done in schema above)

---

## Derived Metric Reference

| Dashboard metric | Source table(s) | Computation |
|-----------------|-----------------|-------------|
| Memory % used | `memory` | `(mem_total - mem_available) / mem_total * 100` |
| Filesystem % used | `filesystems` | `pct_used` (stored directly) |
| CPU % busy | `cpu_stats` | LAG-diff of `(user+sys+iowait+irq+softirq+steal) / total_ticks` |
| Network rx/tx bytes/sec | `net_interfaces` | LAG-diff of `ibytes`/`obytes` ÷ elapsed seconds |
| Disk read/write IOPS | `disk_devices_linux` | LAG-diff of `read_ios`/`write_ios` ÷ elapsed seconds |
| Disk read/write bytes/s | `disk_devices_linux` | LAG-diff of `read_sectors`/`write_sectors` × 512 ÷ elapsed seconds (always 512 regardless of physical sector size) |
| AIX disk read/write bytes/s | `disk_devices_aix` | LAG-diff of `rblks`/`wblks` × 512 ÷ elapsed seconds |
| AIX load average | `cpu_stats` | `loadavg_1 / 65536.0` |
| AIX disk IOPS | `disk_total` or `disk_devices_aix` | LAG-diff of `xrate`/`xfers` ÷ elapsed seconds |
| AIX disk capacity used | `disk_devices_aix` | `size_bytes - free_bytes` |

---

## Notes

### SQLite LAG() support

`LAG()` window functions are available in SQLite 3.25.0+ (released 2018-09-15).
Any modern OS has a sufficiently recent SQLite. Verify with `SELECT sqlite_version();`.

### AIX loadavg conversion

The `loadavg_*` fields use AIX's raw FSCALE fixed-point (FSCALE = 65536):

```sql
SELECT loadavg_1 / 65536.0 AS load_1min
FROM cpu_stats
WHERE host_id = :host_id
ORDER BY collected_at DESC
LIMIT 1;
```

### Counter wraparound

Cumulative counters on Linux wrap at `ULONG_MAX` (2^64 on 64-bit kernels) or
after very long uptimes on 32-bit systems. The ingestion layer should detect
when `current_value < previous_value` and handle the wraparound (add `ULONG_MAX`
to the difference). Filesystem and memory values do not wrap.
