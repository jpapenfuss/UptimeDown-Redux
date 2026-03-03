# AIX libperfstat Integration

This document describes the techniques and patterns used to collect CPU and system metrics on AIX via the libperfstat C library, integrated through Python ctypes.

## Overview

AIX does not provide `/proc` or `/sys` filesystems like Linux. Instead, system performance data is accessed through **libperfstat**, a C library provided by IBM that exposes extensive performance statistics via perfstat function calls.

**Key file:** `monitoring/gather/aix_cpu.py`

## libperfstat Basics

### Library Loading

AIX shared libraries are bundled in `.a` archive files. The 64-bit shared object is stored as a member inside the archive:

```python
import ctypes

def _load_libperfstat():
    """Load libperfstat from its AIX shared archive member."""
    return ctypes.CDLL("libperfstat.a(shr_64.o)")
```

Once loaded, perfstat functions are available for ctypes binding.

### Function Call Pattern

All perfstat enumeration functions follow this pattern:

```
extern int perfstat_ENTITY(
    perfstat_id_t *name,          # Cursor/identifier
    perfstat_ENTITY_t *buffer,    # Output buffer
    int sizeof_buffer,             # Size of struct
    int desired_number             # How many to fetch
);
```

Return value: Number of structures successfully filled.

## Data Structures

### perfstat_id_t (Identifier/Cursor)

```python
class perfstat_id_t(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char * 64),  # IDENTIFIER_LENGTH
    ]
```

Used to identify which entity to start enumeration from. For enumeration queries:
- `name = b""` → Start from first entity (FIRST_CPU, FIRST_DISK, etc.)
- After enumeration, `name` holds the last entity retrieved (for pagination)

### perfstat_cpu_total_t (System-Wide Aggregate)

Contains ~68 fields of system-wide CPU statistics:

```python
class perfstat_cpu_total_t(ctypes.Structure):
    _fields_ = [
        ("ncpus",              ctypes.c_int),     # Active CPUs
        ("ncpus_cfg",          ctypes.c_int),     # Configured CPUs
        ("description",        ctypes.c_char * 64),  # "PowerPC_POWER8" etc.
        ("processorHZ",        ctypes.c_ulonglong),  # CPU frequency in Hz
        ("user",               ctypes.c_ulonglong),  # User-mode ticks
        ("sys",                ctypes.c_ulonglong),  # System-mode ticks
        ("idle",               ctypes.c_ulonglong),  # Idle ticks
        ("wait",               ctypes.c_ulonglong),  # I/O wait ticks
        # ... 60+ more fields
        ("idle_donated_purr",  ctypes.c_ulonglong),  # PURR cycles (LPAR)
        ("busy_stolen_spurr",  ctypes.c_ulonglong),  # SPURR cycles (LPAR)
        # ... etc
    ]
```

**Size:** 696 bytes on AIX 7.2/7.3 POWER8

**Key fields:**
- `ncpus` — Online CPUs at collection time (may lag during SMT transitions)
- `processorHZ` — CPU frequency in Hz
- Tick counters — Per-mode CPU usage (user, sys, idle, wait)
- PURR/SPURR fields — Power-specific cycle counters for LPAR capacity planning
- `loadavg` — 3-element array of load averages (fixed-point, scaled by 2^16)

### perfstat_cpu_t (Per-CPU Detail)

Contains ~67 fields of per-CPU statistics:

```python
class perfstat_cpu_t(ctypes.Structure):
    _fields_ = [
        ("name",               ctypes.c_char * 64),  # "cpu0", "cpu1", etc.
        ("user",               ctypes.c_ulonglong),
        ("sys",                ctypes.c_ulonglong),
        ("idle",               ctypes.c_ulonglong),
        ("wait",               ctypes.c_ulonglong),
        # ... 63 more fields (same as system-wide, per-CPU)
        ("redisp_sd0",         ctypes.c_ulonglong),  # Scheduler domain 0 redispatches
        ("invol_cswitch",      ctypes.c_ulonglong),  # Involuntary context switches
        ("vol_cswitch",        ctypes.c_ulonglong),  # Voluntary context switches
        ("state",              ctypes.c_char),       # Online/offline status
        ("puser_spurr",        ctypes.c_ulonglong),  # SPURR cycles in user mode
        # ... etc
    ]
```

**Size:** ~504 bytes per struct

**Key differences from aggregate:**
- `name` field — Identifies which CPU ("cpu0", "cpu1", etc.)
- `state` field — Single byte indicating online (0x01) or offline (0x00)
- Individual counters per CPU instead of aggregate
- No `ncpus` field (derived from enumeration count)

## Enumeration Patterns

### System-Wide Aggregate (No Enumeration)

```python
def get_cpu_total():
    """Fetch system-wide CPU statistics."""
    lib = _load_libperfstat()

    lib.perfstat_cpu_total.argtypes = [
        ctypes.POINTER(perfstat_id_t),
        ctypes.POINTER(perfstat_cpu_total_t),
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.perfstat_cpu_total.restype = ctypes.c_int

    buf = perfstat_cpu_total_t()
    ret = lib.perfstat_cpu_total(
        None,  # No ID needed; single struct
        ctypes.byref(buf),
        ctypes.sizeof(buf),
        1,  # Request 1 struct
    )

    if ret != 1:
        logger.error(f"perfstat_cpu_total returned {ret}, expected 1")
        return False

    # Convert to dict and return
    return {...}
```

### Per-CPU Enumeration (Two-Call Pattern)

All multi-item enumeration in perfstat uses a two-call approach:

**Call 1: Count Query**
```python
# Call with NULL buffer to get count
ncpus = lib.perfstat_cpu(None, None, ctypes.sizeof(perfstat_cpu_t), 0)
```

**Call 2: Enumeration**
```python
# Allocate array for all items
CpuArray = perfstat_cpu_t * ncpus
cpu_buf = CpuArray()

# Initialize cursor to start from first entity
id_buf = perfstat_id_t()
id_buf.name = b""  # Empty name = FIRST_CPU

# Enumerate all CPUs in one call
ret = lib.perfstat_cpu(
    ctypes.byref(id_buf),
    ctypes.cast(cpu_buf, ctypes.POINTER(perfstat_cpu_t)),
    ctypes.sizeof(perfstat_cpu_t),
    ncpus,  # Request all CPUs
)

if ret != ncpus:
    logger.error(f"Expected {ncpus}, got {ret}")
    return False

# Convert array to dict keyed by CPU name
result = {}
for i in range(ncpus):
    cpu = cpu_buf[i]
    cpu_name = cpu.name.decode("ascii").rstrip("\x00")
    result[cpu_name] = {
        "user": cpu.user,
        "sys": cpu.sys,
        # ... all fields
        "state": "online" if cpu.state[0] > 0 else "offline",
    }
```

**No pagination needed for typical systems** — All CPUs returned in single call.

## Field Normalization

### Padding Fields

Ctypes inserts padding bytes at struct alignment boundaries. These are explicitly skipped:

```python
for field_name, _ in perfstat_cpu_t._fields_:
    if field_name.startswith("_pad"):
        continue
    # Process field
```

### Load Average Scaling

Load averages in perfstat are fixed-point integers scaled by 2^16 (65536):

```python
FSCALE = 1 << 16  # 65536

# Raw loadavg from perfstat_cpu_total_t.loadavg[0-2]
raw_loadavg_1 = result["loadavg"][0]

# Convert to familiar float format
loadavg_1 = raw_loadavg_1 / FSCALE
```

### State Decoding

The `state` field in perfstat_cpu_t is a single byte:

```python
state_byte = cpu.state
if isinstance(state_byte, bytes):
    state_byte = state_byte[0]

# Online = 0x01, Offline = 0x00
state_str = "online" if state_byte > 0 else "offline"
```

## Dynamic CPU Count Handling

### The Challenge

When SMT (Simultaneous Multi-Threading) thread count changes on AIX:
- CPUs are hotplugged/hotremoved dynamically
- The kernel's hotplug process is **not atomic**
- `perfstat_cpu_total().ncpus` reflects the snapshot at call time
- `perfstat_cpu()` enumeration may lag or lead

### Observed Behavior

During rapid SMT transitions (e.g., 8→16→12→9→11...):

```
Time    ncpus    ncpus_enumerated    Status
13:11:04    15        16              MISMATCH
13:11:05    12        16              MISMATCH
13:11:06     9        16              MISMATCH
13:11:07     9        16              MISMATCH
...
```

- `ncpus` fluctuates unpredictably (lagging indicator)
- Enumeration is stable (actual CPU count)

### Solution: Track Both Values

Store both ncpus values in output for transparency:

```python
ncpus_reported = cpu.cpustat_values.get('ncpus')  # What perfstat_cpu_total() said
ncpus_enumerated = len(cpu.cpus)                  # What we actually enumerated

# Output includes both:
# {
#   "cpustats": {
#     "ncpus": 12,              # May lag
#     "ncpus_enumerated": 16,   # Ground truth
#     ...
#   },
#   "cpus": { "cpu0": {...}, "cpu1": {...}, ... }
# }
```

**Recommendation:** Use `ncpus_enumerated` as the authoritative CPU count.

### Database Schema Implications

When CPU counts fluctuate during transitions, DB schema should:
1. **Not enforce FK constraint** on CPU count match
2. **Allow per-sample CPU count variation**
3. **Store both ncpus values** for diagnostic queries
4. **Derive ncpus from detail table** (count distinct CPUs) if needed

Example schema:
```sql
cpu_stats(
  system_id,
  collected_at,
  ncpus_reported,       -- From perfstat_cpu_total() (may lag)
  ncpus_enumerated,     -- Actual enumerated CPUs
  user_ticks,
  sys_ticks,
  -- ... other aggregate fields
);

cpu_detail(
  system_id,
  collected_at,
  cpu_name,
  state,
  user,
  sys,
  -- ... per-CPU fields
);

-- No FK constraint; validate that collected_at values have consistent CPU lists
```

## Error Handling

### Graceful Degradation

All perfstat calls check return values before accessing data:

```python
ncpus = lib.perfstat_cpu(None, None, sizeof, 0)
if ncpus <= 0:
    logger.error(f"perfstat_cpu count returned {ncpus}")
    return False  # Propagate failure, don't crash
```

Failures are logged but don't crash the collector. Parent code checks for `False`:

```python
mycpu = aix_cpu.AixCpu()
if mycpu.cpus is False:
    # Handle missing per-CPU data
    pass
```

### Common Issues

| Issue | Cause | Resolution |
|-------|-------|-----------|
| `perfstat_cpu returned -1` | Library not loaded | Verify `libperfstat.a(shr_64.o)` exists |
| Count mismatch (ncpus vs enum) | SMT transition mid-sample | Expected; use enumerated count as truth |
| State decoding errors | Byte order issues | Verify platform endianness |
| Load average too large | Forgot to divide by FSCALE | Divide by 65536 |

## Performance Characteristics

- **perfstat_cpu_total()**: ~1-2 ms (single call, minimal overhead)
- **perfstat_cpu() count**: ~0.5-1 ms
- **perfstat_cpu() enumeration**: ~1-5 ms (scales with CPU count)
- **Total AIX CPU collection**: ~2-10 ms typical

At 16 CPUs: ~8 ms. At 128 CPUs: ~20 ms.

## LPAR-Specific Metrics

On logical partitions (LPARs), these fields track shared processor donation/theft:

- `idle_donated_purr` — Idle processor cycles donated to other LPARs
- `busy_donated_purr` — Busy processor cycles donated
- `idle_stolen_purr` — Idle processor cycles stolen by hypervisor
- `busy_stolen_purr` — Busy processor cycles stolen
- `puser_spurr`, `psys_spurr`, `pidle_spurr`, `pwait_spurr` — SPURR cycle variants

PURR = Processor Utilization of Resources Register (actual cycles)
SPURR = Scaled Processor Utilization of Resources Register (normalized to base frequency)

These are critical for capacity planning in shared LPAR environments.

## Testing on AIX

To test CPU collection directly:

```bash
# SSH to AIX system
ssh root@192.168.8.1

# Run CPU gatherer directly
cd /path/to/UptimeDown/monitoring/gather
python3 aix_cpu.py

# Or test via main entry point
cd /path/to/UptimeDown
python3 -m monitoring
```

## References

- IBM AIX 7.3 libperfstat documentation: `/usr/include/libperfstat.h`
- OpenJDK libperfstat binding: https://github.com/openjdk/jdk/blob/master/src/java.base/unix/native/libjava/libperfstat_aix.hpp
- AIX Performance Monitoring: IBM Knowledge Center → Performance tuning → Performance tools
