# UptimeDown SQLite Schema

This document defines the SQLite schema for persisting monitoring data collected
by UptimeDown. It is the authoritative reference — update it whenever the schema
changes before modifying the database code.

---

## Design Principles

- **One row per sample per object.** Every collection run inserts new rows; no
  upserts. Historical data is preserved for trending.
- **`collected_at` is a single Unix timestamp per collection run** (REAL, seconds
  since epoch, rounded to milliseconds). It is captured once in `__main__.py`
  before any gatherers run and written identically to every data table.
  Cross-subsystem joins use exact equality on `(host_id, collected_at)`.
  Individual gatherers still record their own `_time` in JSON output for
  diagnostics, but `_time` is not stored in the database.
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
  platform) and the Linux disk table (`disk_devices_linux` vs `disk_devices`).
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

In a distributed setup, `hostname` alone is insufficient to uniquely identify a host
(multiple datacenters may have identically-named systems). Use `system_id` as the
primary unique key for each reporting agent. `system_id` should be assigned at
configuration time and is immutable; the first report from a `system_id` creates
the host record.

```sql
CREATE TABLE IF NOT EXISTS hosts (
    id          INTEGER PRIMARY KEY,
    system_id   TEXT    NOT NULL,   -- unique agent identifier (UUID, hostname+domain, or custom)
    hostname    TEXT    NOT NULL,   -- human-readable hostname
    platform    TEXT    NOT NULL,   -- 'linux', 'aix', 'darwin', etc. (sys.platform)
    first_seen  REAL    NOT NULL,   -- Unix timestamp
    last_seen   REAL    NOT NULL    -- updated on each collection run
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_hosts_system_id ON hosts (system_id);
CREATE INDEX IF NOT EXISTS idx_hosts_hostname ON hosts (hostname);
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
AIX-only. Source: `perfstat_disk_total_t`. Linux has no equivalent — Linux disk
data is per-device only (see `disk_devices_linux`).

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
AIX-only. Source: `perfstat_disk_t`. Linux uses a separate table — see `disk_devices_linux`.

In a distributed setup, disk names (`hdisk0`, `sda`, etc.) can repeat across
different monitored systems. The composite key (host_id, name, collected_at)
ensures uniqueness; additionally, AIX provides device type and adapter information
that may help identify the same physical device if a system is moved or reconfigured.

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

---

### `disk_devices_linux`

Per-device I/O counters from `/proc/diskstats`. One row per device per
collection run. Linux-only.

All counter fields are cumulative since boot. Sector counts use the kernel's
logical sector size (512 bytes on most hardware, regardless of physical sector
size). Tick counts are in milliseconds.

`major`/`minor` are the kernel device numbers. These are stable within a Linux
instance and combined with `host_id` form a unique device identity across the
monitoring database. `discard_*` and `flush_*` fields are zero on kernels < 4.18
and 5.5 respectively — store them as-is; NULL would be misleading since the
counter is genuinely zero rather than absent.

Device naming conventions seen in the wild: `sda`/`sdb` (SCSI/SATA),
`nvme0n1`/`nvme0n1p1` (NVMe), `zd0`/`zd16` (ZFS zvols), `md0` (software RAID),
`dm-0` (device mapper / LVM). Multiple hosts may have identically-named devices
(e.g., both `sda`); use the composite key (host_id, major, minor) to differentiate.

```sql
CREATE TABLE IF NOT EXISTS disk_devices_linux (
    id                  INTEGER PRIMARY KEY,
    host_id             INTEGER NOT NULL REFERENCES hosts(id),
    collected_at        REAL    NOT NULL,

    name                TEXT    NOT NULL,   -- device name (e.g. 'sda', 'nvme0n1', 'zd0')
    major               INTEGER NOT NULL,   -- kernel major device number
    minor               INTEGER NOT NULL,   -- kernel minor device number

    -- Read counters
    read_ios            INTEGER,    -- completed read I/Os
    read_merge          INTEGER,    -- adjacent reads merged by I/O scheduler
    read_sectors        INTEGER,    -- sectors read (512 bytes each)
    read_ticks          INTEGER,    -- time spent reading (ms)

    -- Write counters
    write_ios           INTEGER,    -- completed write I/Os
    write_merges        INTEGER,    -- adjacent writes merged by I/O scheduler
    write_sectors       INTEGER,    -- sectors written (512 bytes each)
    write_ticks         INTEGER,    -- time spent writing (ms)

    -- Queue / latency
    in_flight           INTEGER,    -- I/Os currently in flight
    total_io_ticks      INTEGER,    -- time this device had I/O in flight (ms)
    total_time_in_queue INTEGER,    -- weighted time waiting in queue (ms)

    -- Discard counters (kernel >= 4.18, zero on older kernels)
    discard_ios         INTEGER,    -- completed discard I/Os
    discard_merges      INTEGER,    -- discards merged
    discard_sectors     INTEGER,    -- sectors discarded
    discard_ticks       INTEGER,    -- time spent on discards (ms)

    -- Flush counters (kernel >= 5.5, zero on older kernels)
    flush_ios           INTEGER,    -- completed flush I/Os
    flush_ticks         INTEGER     -- time spent on flushes (ms)
);

CREATE INDEX IF NOT EXISTS idx_disk_devices_linux_host_time
    ON disk_devices_linux (host_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_disk_devices_linux_host_name
    ON disk_devices_linux (host_id, name, collected_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_disk_devices_linux_device_identity
    ON disk_devices_linux (host_id, major, minor, collected_at);
```

---

### `net_interfaces`

Per-interface network counters. One row per interface per collection run.
All counter fields are cumulative since boot; compute rates by differencing
adjacent rows at query time.

Linux source: `/proc/net/dev`. AIX source: `perfstat_netinterface_t`.
Platform-specific columns are NULL on the other platform.

In a distributed setup, interface names (`eth0`, `en0`, etc.) commonly repeat
across different monitored systems. Use the composite key (host_id, iface,
collected_at) to differentiate interfaces on different hosts.

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

In a distributed setup, mountpoints repeat across systems (e.g., `/home` appears
on every Linux host). Use the composite key (host_id, mountpoint, collected_at)
to differentiate mountpoints on different hosts. Device names (`/dev/sda1`)
similarly repeat; use `dev` with `host_id` for disambiguation.

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

## Distributed Monitoring: System Identification

This schema is designed to support a distributed monitoring setup where multiple
independent systems report metrics to a shared database. The key architectural
decision is the use of `system_id` in the `hosts` table as the authoritative
unique identifier for each reporting agent.

### `system_id` Assignment Strategies

`system_id` must be:
- **Globally unique** — no two reporting agents can have the same `system_id`
- **Immutable** — once assigned, it should never change (or data continuity breaks)
- **Resolvable** — the operator should be able to map it back to a physical system

**Recommended strategies:**

1. **UUID (Most robust):** Generate a UUID v4 or v5 at agent initialization; persist
   to a local config file. Guarantees global uniqueness with no coordination.

2. **`hostname:domain`** (If reliable DNS exists) — E.g., `web01.prod.example.com`.
   Works if your naming convention guarantees uniqueness within your domain. Fragile
   if systems are renamed.

3. **`hostname:hwaddr`** — E.g., `web01:00:1a:2b:3c:4d:5e`. Combines hostname for
   human readability with a hardware address (MAC, BIOS UUID, or `/sys/class/dmi/id/product_uuid`)
   for uniqueness. Survives hostname changes on the same physical hardware.

4. **Custom identifier** — E.g., a datacenter-assigned agent ID like `dc-us-east-1:rack-42:box-05`.
   Works well if you have an asset management system that can mint IDs.

### Handling Overlapping Device Names and Mountpoints

Multiple hosts will have:
- Identically-named block devices (`sda`, `sdb`, `nvme0n1`)
- Identically-named network interfaces (`eth0`, `lo`, `en0`)
- Identically-named filesystems and mountpoints (`/`, `/home`, `/var`)

These are disambiguated via composite keys in the schema:
- `disk_devices_linux`: Use (host_id, major, minor) to uniquely identify a device across the cluster
- `net_interfaces`: Use (host_id, iface) to uniquely identify an interface
- `filesystems`: Use (host_id, mountpoint) to uniquely identify a filesystem on a specific host

### Sample Query Patterns

The primary use case is selecting metrics by time range and host(s):

```sql
-- Memory trend for one host over the last hour
SELECT collected_at, mem_total, mem_free, mem_available
FROM memory
WHERE host_id = 42
  AND collected_at BETWEEN ? AND ?
ORDER BY collected_at;

-- Cross-subsystem correlation: CPU vs memory for one host
-- Works because collected_at is identical across all tables for a given run.
SELECT c.collected_at, c.user_ticks, c.sys_ticks, m.mem_free
FROM cpu_stats c
JOIN memory m ON m.host_id = c.host_id AND m.collected_at = c.collected_at
WHERE c.host_id = 42
  AND c.collected_at BETWEEN ? AND ?
ORDER BY c.collected_at;

-- Filesystem usage across multiple hosts
SELECT h.system_id, h.hostname, f.mountpoint, f.pct_used, f.collected_at
FROM filesystems f
JOIN hosts h ON h.id = f.host_id
WHERE h.system_id IN (?, ?, ?)
  AND f.collected_at BETWEEN ? AND ?
  AND f.mounted = 1
ORDER BY h.hostname, f.mountpoint, f.collected_at;
```

### Retention and Cleanup Considerations

In a distributed setup with many hosts:
- Row count grows as O(hosts × samples × metrics)
- Consider archiving old data or partitioning by time
- Use `host_id` indexes to quickly filter to a single host's data
- Use `collected_at` indexes to efficiently query time ranges

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

-- Linux disk read IOPS between two samples
SELECT
    (b.read_ios - a.read_ios) / (b.collected_at - a.collected_at) AS read_iops,
    (b.write_ios - a.write_ios) / (b.collected_at - a.collected_at) AS write_iops
FROM disk_devices_linux a
JOIN disk_devices_linux b ON b.host_id = a.host_id AND b.name = a.name
    AND b.id = (SELECT MIN(id) FROM disk_devices_linux WHERE id > a.id AND host_id = a.host_id AND name = a.name)
WHERE a.host_id = 1 AND a.name = 'sda'
ORDER BY a.collected_at DESC LIMIT 10;

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
