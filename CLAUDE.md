# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UptimeDown is an experimental cross-platform system monitoring tool written in Python 3 that reads system metrics directly from OS interfaces (Linux `/proc`/`/sys`, AIX libperfstat via ctypes). It intentionally avoids psutil and outputs metrics as JSON. This is a learning project — see `README.md`.

## Running

```bash
# Via the run script (calls python3 monitoring as a package):
./run.sh

# Or directly:
python3 monitoring

# Run tests:
python3 -m unittest discover -s tests
```

Only runtime dependency is the Python 3 standard library (ctypes for AIX support).

## Architecture

The project runs as a Python package (`monitoring/`). Entry point is `monitoring/__main__.py`, which:
1. Detects the current platform (`sys.platform`: "linux" or "aix")
2. Imports the appropriate platform-specific gatherer modules at import time (so unsupported modules are never loaded)
3. Instantiates gatherer classes, collects data, and dumps everything as a single JSON object
4. Prints timing diagnostics for each subsystem
5. Optionally writes JSON to a dated file in DEBUG mode

Platform dispatch happens at import time — see the `if _PLATFORM == "aix"` / `elif _PLATFORM == "linux"` blocks in `__main__.py` for how to add new platforms.

### Gatherer Classes (`monitoring/gather/`)

Platform-specific gatherer modules — each exposes a class that reads from OS interfaces and exposes parsed data as instance attributes.

**Linux gatherers** (read `/proc` and `/sys`):
- **`linux_cpu.Cpu`** — `/proc/cpuinfo`, `/proc/stat`, `/proc/softirqs`. Exposes `cpuinfo_values` (hardware info) and `cpustat_values` (per-core usage counters + softirqs). Type coercion via `INTEGER_STATS`, `FLOAT_STATS`, `LIST_STATS` class constants.
- **`linux_memory.Memory`** — `/proc/meminfo`, `/proc/slabinfo`. Exposes `stats` dict with `memory` and `slabs` sub-dicts. Uses `util.tobytes()` to normalize units (kB/MB/GB/TB → bytes, supporting both SI and IEC).
- **`linux_filesystems.Filesystems`** — `/proc/mounts` (falls back to `/etc/mtab`), calls `os.statvfs()` for each real filesystem, computes usage percentages. Filters out virtual filesystems via `FS_IGNORE` list.
- **`linux_disk.Disk`** — `/proc/diskstats` and `/sys/dev/block/`. Exposes `blockdevices` dict and `disk_total` dict.
- **`linux_network.Network`** — `/proc/net/dev` and `/sys/class/net/`. Exposes `interfaces` dict with per-interface stats.

**AIX gatherers** (use libperfstat via ctypes):
- **`aix_cpu.AixCpu`** — Calls `perfstat_cpu_total()`. Exposes `cpustat_values` (system-wide CPU counters, load averages, LPAR/POWER metrics) and `cpus` (per-CPU enumeration). No `cpuinfo_values` on AIX.
- **`aix_memory.AixMemory`** — Uses `perfstat_memory_total()`. Exposes `stats` dict structure similar to Linux.
- **`aix_filesystems.AixFilesystems`** — Uses `statvfs()` for mounted filesystems. Exposes `filesystems` dict.
- **`aix_disk.AixDisk`** — Uses `perfstat_disk_total()` and per-disk enumeration. Exposes `blockdevices` and `disk_total`.
- **`aix_network.AixNetwork`** — Uses `perfstat_netinterface()` enumeration. Exposes `interfaces` dict.

### Shared Utilities (`monitoring/gather/util.py`)

- `caniread(path)` — Checks read access before opening files
- `tobytes(value, multiplier)` — Converts kB/MB/GB/TB strings to bytes (handles both SI and IEC units)

### Key Conventions

- Every gatherer attaches a `_time` key (via `time.time()`) to track when data was captured.
- Logging uses the `"monitoring"` logger name throughout, configured in `monitoring/log_setup.py` (DEBUG to `monitoring.log`, ERROR to stderr).
- Optional log file — if current directory is not writable, logging silently falls back to stderr.
- `config.ini` controls daemon mode (`run_interval`, `max_iterations`), logging level, and output behavior.
- System ID tracking via `identity.py` — each run gets a unique system_id in JSON output (helps identify which box the metrics came from).
- JSON output includes a `collected_at` timestamp (rounded to milliseconds for consistency).
- When DEBUG logging is enabled, JSON is also written to a dated file in the current directory (`<uuid>-<timestamp>.json`).
- Per-CPU enumeration tracking: AIX includes `ncpus_enumerated` in `cpustats` to detect SMT/core count changes.

Before running any AIX-specific command, verify it's valid for AIX (not a Linux/GNU-specific variant). For example, use smtctl not chdev for SMT, and avoid grep -P. List the commands you plan to run and let me confirm before executing.

