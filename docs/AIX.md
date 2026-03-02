# AIX Monitoring Documentation Index

This directory contains comprehensive documentation for monitoring AIX systems using libperfstat via Python ctypes.

## Documents

### [aix-perfstat.md](aix-perfstat.md)
**For:** Developers implementing or modifying AIX monitoring
**Topics:**
- libperfstat library overview and concepts
- perfstat_cpu_total_t and perfstat_cpu_t structure details
- Two-call enumeration pattern
- Field normalization (padding, load average, state decoding)
- Dynamic CPU count handling and the ncpus consistency issue
- LPAR-specific PURR/SPURR metrics
- Performance characteristics and error handling

**Key Section:** [Dynamic CPU Count Handling](aix-perfstat.md#dynamic-cpu-count-handling)
— Explains why ncpus_reported and ncpus_enumerated diverge during SMT transitions

### [ctypes-patterns.md](ctypes-patterns.md)
**For:** Developers integrating C libraries via ctypes
**Topics:**
- Structure definition and field mapping
- Struct padding alignment
- Library loading and function binding
- Pointer and buffer management
- Error handling and type safety
- Portability (endianness, 32/64-bit)
- Testing and debugging techniques
- Performance tips and common pitfalls

**Key Section:** [Handling Struct Padding](ctypes-patterns.md#handling-struct-padding)
— Critical for AIX integration where struct alignment matters

### [aix-operations.md](aix-operations.md)
**For:** Operators and SREs running monitoring in production
**Topics:**
- Quick start guide
- Understanding CPU output (ncpus vs ncpus_enumerated)
- SMT transitions and expected behavior
- Database schema recommendations
- Troubleshooting common issues
- Performance tuning
- Integration with external systems (Prometheus, InfluxDB, PostgreSQL, etc.)

**Key Section:** [Dynamic CPU Changes](aix-operations.md#dynamic-cpu-changes-smt-transitions)
— How to handle SMT transitions in production

## Quick Reference

### What is ncpus_reported vs ncpus_enumerated?

```json
{
  "cpustats": {
    "ncpus": 12,              // ← ncpus_reported (may lag)
    "ncpus_enumerated": 16    // ← actual CPU count (ground truth)
  },
  "cpus": {
    "cpu0": {...},
    "cpu1": {...},
    ...
    "cpu15": {...}
  }
}
```

| Field | Source | During SMT Change | Use For |
|-------|--------|-------------------|---------|
| `ncpus` | `perfstat_cpu_total()` | Fluctuates (lag indicator) | Historical diagnostics |
| `ncpus_enumerated` | `perfstat_cpu()` enumeration | Stable | Authoritative CPU count |

**See:** [aix-operations.md#dynamic-cpu-changes-smt-transitions](aix-operations.md#dynamic-cpu-changes-smt-transitions)

### Per-CPU Data

The `cpus` dict contains granular per-CPU metrics:

```json
"cpus": {
  "cpu0": {
    "user": 24476,
    "sys": 119351,
    "idle": 26740069,
    "wait": 2976,
    "pswitch": 44299797,
    "state": "online",
    ...
  },
  ...
}
```

All fields from perfstat_cpu_t are included. See [aix-perfstat.md#perfstat_cpu_t](aix-perfstat.md#perfstat_cpu_t-per-cpu-detail) for complete field list.

### Structure Sizes

| Structure | Size | Location |
|-----------|------|----------|
| `perfstat_id_t` | 64 bytes | Cursor/identifier |
| `perfstat_cpu_total_t` | 696 bytes | System-wide aggregate |
| `perfstat_cpu_t` | ~504 bytes | Per-CPU detail (×ncpus) |

## Implementation Summary

### File Structure
```
monitoring/
├── gather/
│   ├── aix_cpu.py          # AIX CPU gatherer (perfstat integration)
│   └── ...
├── __main__.py             # Entry point (includes JSON output logic)
└── config.ini              # Configuration (logging level, intervals)

docs/
├── AIX.md                  # This file
├── aix-perfstat.md         # Technical deep dive
├── ctypes-patterns.md      # Integration patterns
└── aix-operations.md       # Operational guide
```

### Key Classes

**monitoring/gather/aix_cpu.py:**
- `perfstat_id_t` — C struct wrapper for perfstat identifiers
- `perfstat_cpu_t` — C struct wrapper for per-CPU statistics (67 fields)
- `perfstat_cpu_total_t` — C struct wrapper for system-wide statistics (68 fields)
- `AixCpu` — High-level gatherer class
  - `cpustat_values` — System-wide aggregate stats
  - `cpus` — Per-CPU detail dict keyed by "cpu0", "cpu1", etc.

### Code Patterns

**Enumeration pattern** (used for per-CPU collection):
```python
# Query count
ncpus = lib.perfstat_cpu(None, None, sizeof, 0)

# Allocate and enumerate
CpuArray = perfstat_cpu_t * ncpus
cpu_buf = CpuArray()
id_buf = perfstat_id_t()
id_buf.name = b""
ret = lib.perfstat_cpu(ctypes.byref(id_buf), cpu_ptr, sizeof, ncpus)
```

**See:** [aix-perfstat.md#per-cpu-enumeration-two-call-pattern](aix-perfstat.md#per-cpu-enumeration-two-call-pattern)

## Common Tasks

### I want to...

**...understand why CPU count fluctuates**
→ Read [aix-operations.md#dynamic-cpu-changes-smt-transitions](aix-operations.md#dynamic-cpu-changes-smt-transitions)

**...modify the CPU gatherer**
→ Read [aix-perfstat.md](aix-perfstat.md) (technical reference)

**...integrate with my database**
→ Read [aix-operations.md#integration-with-external-systems](aix-operations.md#integration-with-external-systems)

**...debug a ctypes issue**
→ Read [ctypes-patterns.md#testing-and-debugging](ctypes-patterns.md#testing-and-debugging)

**...add another perfstat data source (disks, network, etc.)**
→ Read [aix-perfstat.md#enumeration-patterns](aix-perfstat.md#enumeration-patterns) (pattern reference)
→ Look at [monitoring/gather/aix_disk.py](../monitoring/gather/aix_disk.py) (working example)

**...troubleshoot data collection failures**
→ Read [aix-operations.md#troubleshooting](aix-operations.md#troubleshooting)

**...understand LPAR metrics**
→ Read [aix-perfstat.md#lpar-specific-metrics](aix-perfstat.md#lpar-specific-metrics)
→ Read [aix-operations.md#lpar-mode](aix-operations.md#lpar-mode)

## Testing

### Running on AIX System

```bash
# SSH to AIX system
ssh root@aix-system

# Test CPU collection directly
cd /path/to/UptimeDown/monitoring/gather
python3 aix_cpu.py

# Test full monitoring
cd /path/to/UptimeDown
python3 -m monitoring

# With DEBUG output (saves JSON files)
# Edit config.ini [logging] level=DEBUG, then:
python3 -m monitoring
```

### Simulating SMT Transitions

```bash
# Current SMT config
lsattr -El proc0 | grep smt

# Change SMT threads
smtctl -t 8    # Set to 8 threads
smtctl -t 4    # Set to 4 threads

# While changing, collect samples:
while true; do python3 -m monitoring | head -1; sleep 0.5; done
```

## Known Issues and Workarounds

### ncpus Mismatch During SMT Transitions

**Issue:** `ncpus_reported != ncpus_enumerated` for 1-2 seconds during SMT changes.

**Expected behavior:** Normal due to kernel hotplug non-atomicity.

**Workaround:** Use `ncpus_enumerated` as authoritative count.

**See:** [aix-operations.md#expected-behavior-during-smt-changes](aix-operations.md#expected-behavior-during-smt-changes)

### Load Average Too High

**Issue:** Load average shows ~1.5M instead of ~24.

**Cause:** Forgot to divide by FSCALE (65536).

**Fix:** See [aix-perfstat.md#load-average-scaling](aix-perfstat.md#load-average-scaling)

## References

- **IBM AIX Docs:** `/usr/include/libperfstat.h` (on AIX system)
- **OpenJDK Reference:** libperfstat_aix.hpp in OpenJDK source
- **Python ctypes:** https://docs.python.org/3/library/ctypes.html
- **AIX Performance Tools:** `man perfstat` (on AIX system)

## Contributing

When adding new AIX data sources (network, disk, memory, etc.):

1. Study the enumeration pattern in [aix-perfstat.md#enumeration-patterns](aix-perfstat.md#enumeration-patterns)
2. Look at working examples: `aix_cpu.py`, `aix_disk.py`, `aix_network.py`
3. Define ctypes structures matching C headers
4. Implement two-call pattern (count query + enumeration)
5. Handle errors gracefully (return False on failure)
6. Document struct field meanings in docstrings
7. Add tests to verify struct sizes with `ctypes.sizeof()`

---

**Last Updated:** March 2, 2026
**AIX Versions Tested:** 7.1, 7.2, 7.3
**perfstat API Version:** Compatible with AIX 6.1+
