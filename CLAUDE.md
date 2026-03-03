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
- **`linux_disk.Disk`** — `/proc/diskstats`. Exposes `blockdevices` dict keyed by device name (DISKSTAT_KEYS fields). `/sys/block/` enrichment is stubbed out for future use.
- **`linux_network.Network`** — `/proc/net/dev` and `/sys/class/net/`. Exposes `interfaces` dict with per-interface stats.

**AIX gatherers** (use libperfstat via ctypes):
- **`aix_cpu.AixCpu`** — Calls `perfstat_cpu_total()`. Exposes `cpustat_values` (system-wide CPU counters, load averages, LPAR/POWER metrics) and `cpus` (per-CPU enumeration). No `cpuinfo_values` on AIX.
- **`aix_memory.AixMemory`** — Uses `perfstat_memory_total()`. Exposes `stats` dict structure similar to Linux.
- **`aix_filesystems.AixFilesystems`** — Uses `statvfs()` for mounted filesystems. Exposes `filesystems` dict.
- **`aix_disk.AixDisk`** — Uses `perfstat_disk_total()` and per-disk enumeration. Exposes `blockdevices` and `disk_total`.
- **`aix_network.AixNetwork`** — Uses `perfstat_netinterface()` enumeration. Exposes `interfaces` dict.

### Shared Utilities (`monitoring/gather/util.py`)

- `caniread(path)` — Checks read access before opening files
- `tobytes(value, unit)` — Converts a (value, unit) pair to bytes, supporting SI (KB=1000) and IEC (KiB=1024) prefixes through exa scale

### Key Conventions

- Collection output uses a single top-level `collected_at` timestamp per run; gatherers do not attach per-object `_time` keys.
- Logging uses the `"monitoring"` logger name throughout, configured in `monitoring/log_setup.py` (DEBUG to `monitoring.log`, ERROR to stderr).
- Optional log file — if current directory is not writable, logging silently falls back to stderr.
- `config.ini` controls daemon mode (`run_interval`, `max_iterations`). `log_level = DEBUG` gates JSON file dumps only — it does not change logger verbosity. Logger levels are hardcoded in `log_setup.py` (file: DEBUG, stderr: ERROR).
- System ID tracking via `identity.py` — each run gets a unique system_id in JSON output (helps identify which box the metrics came from).
- JSON output includes a `collected_at` timestamp (rounded to milliseconds for consistency).
- When `log_level = DEBUG` in config.ini, JSON is also written to a dated file in the current directory (`<uuid>-<timestamp>.json`).
- Per-CPU enumeration tracking: AIX includes `ncpus_enumerated` in `cpustats` to detect SMT/core count changes.

## Documentation Maintenance

**Requirement**: When you modify any Python file in `monitoring/` or `tests/`, you MUST update the corresponding section in `.claude/projects/-Volumes-...-UptimeDown/memory/project_reference.md`.

**What to update**:
- Changed a function signature or method? Update it in the reference.
- Added a new class, constant, or data structure key? Add it to the reference.
- Added or removed a file? Add or remove its section.
- Changed behavior that affects output format? Update the relevant output schema section.

**When to update**: Update the reference **before committing**. Forgetting to do this defeats the purpose of the reference and makes future sessions unreliable.

**How to update**: Edit `.claude/projects/-Volumes-...-UptimeDown/memory/project_reference.md` directly. The reference is organized by file (§ numbering), so find the relevant section and update it. Keep it accurate.

Before running any AIX-specific command, verify it's valid for AIX (not a Linux/GNU-specific variant). For example, use smtctl not chdev for SMT, and avoid grep -P. List the commands you plan to run and let me confirm before executing.

