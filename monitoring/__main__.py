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
import time
import signal
import uuid
import os

from log_setup import log_setup
from identity import get_system_id
from config import Config

# sys.platform values: "linux", "aix", "darwin", "freebsd7" ... "freebsd14", etc.
_PLATFORM = sys.platform
_SYSTEM_ID = get_system_id()

if _PLATFORM == "aix":
    from gather import aix_cpu, aix_disk, aix_filesystems, aix_memory, aix_network
elif _PLATFORM == "linux":
    from gather import linux_cpu, linux_disk, linux_memory, linux_filesystems, linux_network
else:
    raise RuntimeError(f"Unsupported platform: {_PLATFORM!r}")

# Cloud metadata gatherer — platform-agnostic, fast-fails on non-cloud machines.
from gather import aws


def collect_once(logger, json_module):
    """Collect metrics once and return (json_string, timings_dict)."""
    timestart = time.time()

    # Single timestamp for this collection run. All data tables in the database
    # use this value as collected_at, ensuring cross-subsystem joins work on
    # exact equality. Rounded to milliseconds to survive JSON round-tripping
    # without float-precision drift.
    collected_at = round(time.time(), 3)

    # Cloud metadata — runs on all platforms; fast-fails (TCP probe) on non-cloud machines.
    timebeforecloud = time.time()
    mycloud = aws.AwsCloud()
    timeaftercloud = time.time()

    if _PLATFORM == "aix":
        timebeforecpu = time.time()
        mycpu    = aix_cpu.AixCpu()
        mydisk   = aix_disk.AixDisk()
        myfs     = aix_filesystems.AixFilesystems()
        mymemory = aix_memory.AixMemory()
        mynet    = aix_network.AixNetwork()
        timeafterfs = time.time()

        timebeforejson = time.time()
        # Capture ncpus_enumerated separately for consistency tracking during SMT transitions
        ncpus_enumerated = len(mycpu.cpus) if mycpu.cpus and mycpu.cpus is not False else 0
        cpustats_with_enum = dict(mycpu.cpustat_values) if mycpu.cpustat_values else {}
        cpustats_with_enum["ncpus_enumerated"] = ncpus_enumerated

        jsonout = json_module.dumps({
            "system_id":   _SYSTEM_ID,
            "collected_at": collected_at,
            "cloud":       mycloud.metadata,
            "cpustats":    cpustats_with_enum,
            "cpus":        mycpu.cpus,
            "disks":       mydisk.blockdevices,
            "disk_total":  mydisk.disk_total,
            "filesystems": myfs.filesystems,
            "memory":      mymemory.stats,
            "network":     mynet.interfaces,
        }, indent=4)
        timeafterjson = time.time()

        timeend = time.time()
        timings = {
            'total': timeend - timestart,
            'startup': timebeforecpu - timestart,
            'cloud': timeaftercloud - timebeforecloud,
            'cpu': mycpu.cpustat_values['_time'] - timestart,
            'disk': mydisk.disk_total['_time'] - mycpu.cpustat_values['_time'],
            'fs': myfs.filesystems['_time'] - mydisk.disk_total['_time'],
            'memory': mymemory.stats['memory']['_time'] - myfs.filesystems['_time'],
            'json': timeafterjson - timebeforejson,
        }

    elif _PLATFORM == "linux":
        timebeforecpu = time.time()
        mycpu    = linux_cpu.Cpu()
        mydisk   = linux_disk.Disk()
        mymemory = linux_memory.Memory()
        myfs     = linux_filesystems.Filesystems()
        mynet    = linux_network.Network()
        timeafterfs = time.time()

        timebeforejson = time.time()
        jsonout = json_module.dumps({
            "system_id":   _SYSTEM_ID,
            "collected_at": collected_at,
            "cloud":       mycloud.metadata,
            "cpustats":    mycpu.cpustat_values,
            "cpuinfo":     mycpu.cpuinfo_values,
            "disks":       mydisk.blockdevices,
            "memory":      mymemory.stats,
            "filesystems": myfs.filesystems,
            "network":     mynet.interfaces,
        }, indent=4)
        timeafterjson = time.time()

        timeend = time.time()
        slabs_time = None
        if mymemory.stats["slabs"] is not False:
            slabs_time = mymemory.stats['slabs']['_time'] - mymemory.stats['memory']['_time']
            fs_start_time = mymemory.stats['slabs']['_time']
        else:
            fs_start_time = mymemory.stats['memory']['_time']

        timings = {
            'total': timeend - timestart,
            'startup': timebeforecpu - timestart,
            'cloud': timeaftercloud - timebeforecloud,
            'cpu': mycpu.cpustat_values['_time'] - timestart,
            'cpuinfo': mycpu.cpuinfo_values['_time'] - mycpu.cpustat_values['_time'],
            'memory': mymemory.stats['memory']['_time'] - mycpu.cpuinfo_values['_time'],
            'slabs': slabs_time,
            'fs': myfs.filesystems['_time'] - fs_start_time,
            'json': timeafterjson - timebeforejson,
        }

    return jsonout, timings


def dump_json_file(json_string, logger):
    """Dump JSON output to a file with uuid-timestamp naming.

    Filename format: <uuid>-<timestamp>.json
    Uses current Unix timestamp as the timestamp component.
    Attempts to write to current directory; silently fails if not writable.
    """
    try:
        filename = f"{uuid.uuid4()}-{int(time.time())}.json"
        with open(filename, 'w') as f:
            f.write(json_string)
        logger.debug(f"Wrote JSON dump to {filename}")
    except (IOError, OSError) as e:
        logger.debug(f"Could not write JSON dump file: {e}")


def print_timings(timings):
    """Print collection timings."""
    print(f"Time between start and finish: \t\t\t\t{timings['total']}")
    print(f"Time from start to before gathering: \t\t\t{timings['startup']}")
    print(f"Time for cloud metadata probe: \t\t\t\t{timings['cloud']}")
    print(f"Time from start to end of CPU Stat: \t\t\t{timings['cpu']}")

    if _PLATFORM == "aix":
        print(f"Time from end of CPU to end of Disk: \t\t\t{timings['disk']}")
        print(f"Time from end of Disk to end of FS: \t\t\t{timings['fs']}")
        print(f"Time from end of FS to end of Memory: \t\t\t{timings['memory']}")
    else:  # linux
        print(f"Time from end of CPU Info to end of CPU Stat: \t\t{timings['cpuinfo']}")
        print(f"Time from end of CPU Info to end of Memory: \t\t{timings['memory']}")
        if timings['slabs'] is not None:
            print(f"Time from end of Memory to end of Slabs: \t\t{timings['slabs']}")
            print(f"Time from end of Slabs to end of FS: \t\t\t{timings['fs']}")
        else:
            print(f"Time from end of Memory to end of Slabs: \t\tskipped (slabinfo unreadable)")
            print(f"Time from end of Memory to end of FS: \t\t\t{timings['fs']}")

    print(f"Time to generate json: \t\t\t\t\t{timings['json']}")


def main():
    logger = log_setup()
    import json
    cfg = Config()

    # Flag for graceful shutdown on SIGTERM/SIGINT
    should_exit = False

    def signal_handler(signum, frame):
        nonlocal should_exit
        should_exit = True

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    iteration = 0

    while True:
        iteration += 1

        # Collect metrics
        jsonout, timings = collect_once(logger, json)

        # Print diagnostics and JSON
        print_timings(timings)
        print(jsonout)

        # Dump JSON to file if DEBUG logging is enabled
        if cfg.log_level == "DEBUG":
            dump_json_file(jsonout, logger)

        # Check if we should exit
        if cfg.max_iterations is not None and iteration >= cfg.max_iterations:
            break

        if should_exit:
            break

        # Sleep until next collection (but be responsive to signals)
        print(f"\nNext collection in {cfg.run_interval} seconds...", file=sys.stderr)
        time.sleep(cfg.run_interval)


if __name__ == "__main__":
    main()
