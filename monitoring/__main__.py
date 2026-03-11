# Entry point for the monitoring package. Run as: python3 monitoring
#
# Detects the current platform, imports the appropriate gatherer modules,
# instantiates them, serialises results to JSON, and prints timing diagnostics.
#
# Platform dispatch is done at import time so that platform-specific modules
# (which may import ctypes extensions or reference /proc paths) are never
# imported on an unsupported OS.
#
# Adding a new platform (e.g. darwin, freebsd):
#   1. Add an elif branch in the import block below.
#   2. Add a matching elif branch in collect_once() with its gather calls and JSON keys.
#
# Daemon mode: Set run_interval and optionally max_iterations in config.ini [daemon] section.
import sys
sys.dont_write_bytecode = True
import json
import time
import os
import socket

# Support both `python3 monitoring` (script-style) and `python3 -m monitoring`
# (package-style) execution modes.
if __package__:
    from .log_setup import log_setup
    from .identity import get_system_id
    from .config import Config, create_argument_parser
    from .scheduler import GathererScheduler
else:
    from log_setup import log_setup
    from identity import get_system_id
    from config import Config, create_argument_parser
    from scheduler import GathererScheduler

# sys.platform values: "linux", "aix", "darwin", "freebsd7" ... "freebsd14", etc.
_PLATFORM = sys.platform
_SYSTEM_ID = get_system_id()

if _PLATFORM == "aix":
    if __package__:
        from .gather import aix_cpu, aix_disk, aix_filesystems, aix_memory, aix_network
    else:
        from gather import aix_cpu, aix_disk, aix_filesystems, aix_memory, aix_network
elif _PLATFORM == "linux":
    if __package__:
        from .gather import linux_cpu, linux_disk, linux_memory, linux_filesystems, linux_network
    else:
        from gather import linux_cpu, linux_disk, linux_memory, linux_filesystems, linux_network
else:
    raise RuntimeError(f"Unsupported platform: {_PLATFORM!r}")

# Cloud metadata gatherer — platform-agnostic, fast-fails on non-cloud machines.
if __package__:
    from .gather import aws
else:
    from gather import aws


# ---------------------------------------------------------------------------
# Per-gatherer collect functions.
#
# Each returns a flat dict of {json_key: value} pairs that get merged into
# the final JSON output. This makes it trivial to later put individual keys
# on different intervals — just split into separate gatherer entries.
# ---------------------------------------------------------------------------

def _gather_cloud():
    return {"cloud": aws.AwsCloud(round(time.time(), 3)).metadata}


if _PLATFORM == "linux":
    def _gather_cpu():
        obj = linux_cpu.Cpu(round(time.time(), 3))
        return {"cpustats": obj.cpustat_values, "cpuinfo": obj.cpuinfo_values}

    def _gather_memory():
        return {"memory": linux_memory.Memory(round(time.time(), 3)).stats}

    def _gather_disk():
        return {"disks": linux_disk.Disk(round(time.time(), 3)).blockdevices}

    def _gather_filesystems():
        return {"filesystems": linux_filesystems.Filesystems(round(time.time(), 3)).filesystems}

    def _gather_network():
        return {"network": linux_network.Network(round(time.time(), 3)).interfaces}

elif _PLATFORM == "aix":
    def _gather_cpu():
        obj = aix_cpu.AixCpu(round(time.time(), 3))
        # Capture ncpus_enumerated for consistency tracking during SMT transitions
        ncpus_enumerated = len(obj.cpus) if obj.cpus and obj.cpus is not False else 0
        cpustats = dict(obj.cpustat_values) if obj.cpustat_values else {}
        cpustats["ncpus_enumerated"] = ncpus_enumerated
        return {"cpustats": cpustats, "cpus": obj.cpus}

    def _gather_memory():
        return {"memory": aix_memory.AixMemory(round(time.time(), 3)).stats}

    def _gather_disk():
        obj = aix_disk.AixDisk(round(time.time(), 3))
        return {"disks": obj.blockdevices, "disk_total": obj.disk_total}

    def _gather_filesystems():
        return {"filesystems": aix_filesystems.AixFilesystems(round(time.time(), 3)).filesystems}

    def _gather_network():
        return {"network": aix_network.AixNetwork(round(time.time(), 3)).interfaces}


def _build_gatherers():
    """Return ordered dict of name -> collect_fn for the current platform."""
    return {
        "cloud":       _gather_cloud,
        "cpu":         _gather_cpu,
        "memory":      _gather_memory,
        "disk":        _gather_disk,
        "filesystems": _gather_filesystems,
        "network":     _gather_network,
    }


def _assemble_json(cache, collected_at, json_module, errors=None, names=None):
    """Merge gatherer cache into a single JSON string.

    Args:
        cache: dict of gatherer name -> result (may contain None for failed gatherers)
        collected_at: float timestamp (seconds since epoch)
        json_module: json module
        errors: dict of gatherer name -> {error, message}; defaults to empty dict
        names: iterable of gatherer names to include; if None, include all

    Failed gatherers have cache[name] = None and are skipped during merge.
    Only gatherers in *names* are included in output (if provided).
    """
    output = {
        "system_id": _SYSTEM_ID,
        "collected_at": collected_at,
        "hostname": socket.gethostname(),
        "platform": _PLATFORM,
        "collection_errors": errors or {},
    }
    for name, data in cache.items():
        if data is not None and (names is None or name in names):
            output.update(data)
    return json_module.dumps(output, indent=4)


def dump_json_file(json_string, logger, data_dir, system_id):
    """Dump JSON output to a file with system-id-timestamp naming.

    Filename format: <system_id>-<timestamp>.json
    Writes to the specified data_dir, creating it if needed.
    Silently fails if not writable.
    """
    try:
        os.makedirs(data_dir, exist_ok=True)
        filename = os.path.join(data_dir, f"{system_id}-{int(time.time())}.json")
        with open(filename, 'w') as f:
            f.write(json_string)
        logger.debug(f"Wrote JSON dump to {filename}")
    except (IOError, OSError) as e:
        logger.debug(f"Could not write JSON dump file: {e}")


def print_timings(timings):
    """Print per-gatherer collection timings for this tick."""
    for name, elapsed in sorted(timings.items()):
        print(f"  Collected {name}: {elapsed:.4f}s")


def main():
    parser = create_argument_parser()
    args = parser.parse_args()

    # Handle --once shorthand: sets max_iterations to 1
    if args.once:
        args.max_iterations = 1

    logger = log_setup()
    cfg = Config(args)

    scheduler = GathererScheduler(
        _build_gatherers(),
        cfg.gatherer_intervals,
        cfg.run_interval,
        cfg.base_tick,
    )

    iteration = 0

    while True:
        cache, timings, errors = scheduler.tick()

        if not timings:
            # No gatherers ran this tick; skip output and sleep.
            time.sleep(scheduler.base_tick)
            continue

        iteration += 1
        collected_at = round(time.time(), 3)
        # Only include data from gatherers that ran this tick (no stale data)
        jsonout = _assemble_json(cache, collected_at, json, errors, names=set(timings.keys()))

        # Print diagnostics and JSON
        print_timings(timings)
        print(jsonout)

        # Dump JSON to file if enabled (via --dump flag or config.ini [output] dump_json)
        if cfg.dump_json:
            dump_json_file(jsonout, logger, cfg.data_dir, _SYSTEM_ID)

        # Check if we should exit
        if cfg.max_iterations is not None and iteration >= cfg.max_iterations:
            break

        # Sleep until next check — base_tick controls polling cadence.
        # Gatherers are only re-collected when their individual interval elapses.
        time.sleep(scheduler.base_tick)


if __name__ == "__main__":
    main()
