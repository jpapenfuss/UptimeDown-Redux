# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UptimeDown is an experimental Linux system monitoring tool written in Python 3. It reads system metrics directly from `/proc` and `/sys` filesystems (intentionally avoiding psutil) and outputs them as JSON. This is a learning project — see `README.md`.

## Running

```bash
# Via the run script (calls python3 monitoring as a package):
./run.sh

# Or directly:
python3 monitoring
```

There is a virtualenv at `env/` but no `requirements.txt` — the only runtime dependency is the Python standard library. The `setup.py` references `docopt` and a `skele` package (leftover scaffolding from [skele-cli](https://github.com/rdegges/skele-cli), not used by the monitoring code).

No tests exist currently.

## Architecture

The project runs as a Python package (`monitoring/`). Entry point is `monitoring/__main__.py`, which instantiates gatherer classes, collects their data, and dumps everything as a single JSON object with timing info.

### Gatherer Classes (`monitoring/gather/`)

Each gatherer is a class that reads from Linux `/proc` or `/sys` files, parses them, and exposes parsed data as instance attributes:

- **`cpu.Cpu`** — Reads `/proc/cpuinfo`, `/proc/stat`, and `/proc/softirqs`. Exposes `cpuinfo_values` (hardware info for cpu0) and `cpustat_values` (per-core usage counters + softirqs). Type coercion is driven by `INTEGER_STATS`, `FLOAT_STATS`, and `LIST_STATS` class constants.
- **`memory.Memory`** — Reads `/proc/meminfo` and `/proc/slabinfo`. Exposes `stats` dict with `memory` and `slabs` sub-dicts. Uses `util.tobytes()` to normalize units.
- **`filesystems.Filesystems`** — Reads `/proc/mounts` (falls back to `/etc/mtab`), calls `os.statvfs()` for each real filesystem, and computes usage percentages. Filters out virtual filesystems via `FS_IGNORE` list.
- **`disk.Disk`** — Reads `/proc/diskstats` and `/sys/dev/block/`. Work in progress — `get_sys_stats()` and `get_queue()` are stubs.

### Shared Utilities (`monitoring/gather/util.py`)

- `caniread(path)` — Checks read access before opening files
- `tobytes(value, multiplier)` — Converts kB/MB/GB/TB strings to byte values

### Import Pattern

Each gatherer module uses a dual-import pattern: `from . import util` when imported as a package, and `import util` when run directly (`__main__`). This allows individual modules to be tested standalone (e.g., `cd monitoring/gather && python3 cpu.py`).

### Key Conventions

- Every gatherer attaches a `_time` key (via `time.time()`) to its output for tracking when data was captured.
- Logging uses the `"monitoring"` logger name throughout, configured in `monitoring/log_setup.py` (DEBUG to `monitoring.log`, ERROR to stderr).
- `config.ini` defines per-subsystem refresh intervals but is not yet wired into the main loop.
- This is Linux-only — all gatherers depend on `/proc` and `/sys` paths.
