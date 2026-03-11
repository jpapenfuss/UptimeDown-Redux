# UptimeDown

Don't use this.

No, really. This is an experiment — a project to work on Python skills and figure out where system monitoring tools actually get their data. If you need this for real work, use psutil and call it a day.

## What it does

UptimeDown reads system metrics directly from OS interfaces and outputs them as JSON:

- **Linux**: reads `/proc` and `/sys` (cpuinfo, stat, softirqs, meminfo, slabinfo, diskstats, mounts, network stats)
- **AIX**: calls libperfstat via ctypes (CPU, memory, filesystems, disk, network)
- **Metrics**: CPU (per-core + aggregate), memory, disk I/O, filesystems (usage, mount info), network interfaces

Output is a single JSON object with a unified `collected_at` timestamp. Optional daemon mode with configurable per-gatherer poll intervals.

## Running

```bash
# One-shot collection
python3 monitoring

# Via run script
./run.sh

# Tests
python3 -m unittest discover -s tests
```

## Why

Wanted to understand what `/proc` actually contains, how different tools parse it, and whether you can avoid external dependencies. Also wanted to try ctypes bindings (AIX libperfstat) to handle monitoring on systems without psutil. AIX code is tested on real hardware (LPARs and WPARs) via SSH.

Only dependency: Python 3 standard library.

## Receiver Service

HTTP receiver for collecting metrics from distributed agents:

- **Bearer token auth** with constant-time comparison
- **Comprehensive JSON validation** (type checking, range validation, platform awareness)
- **Schema-aware transform** layer (key renames, derived fields, extra_json bundling)
- **SQLite persistence** with transaction semantics and host upsert logic
- **Push client** in monitoring agents with exponential backoff retry, FIFO caching, automatic purge
- **612+ tests**, all passing

See [docs/receiver_plan.md](docs/receiver_plan.md) for architecture and [receiver/](receiver/) for implementation.

## Known limitations

- No Windows support (would need Windows API via ctypes)
- SQLite only (production Postgres/MariaDB support planned as Phase 7)
