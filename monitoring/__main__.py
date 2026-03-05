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
import uuid
import os

from log_setup import log_setup
from identity import get_system_id
from config import Config, create_argument_parser

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
    mycloud = aws.AwsCloud(collected_at)
    timeaftercloud = time.time()

    if _PLATFORM == "aix":
        timebeforecpu = time.time()
        mycpu    = aix_cpu.AixCpu(collected_at)
        mydisk   = aix_disk.AixDisk(collected_at)
        myfs     = aix_filesystems.AixFilesystems(collected_at)
        mymemory = aix_memory.AixMemory(collected_at)
        mynet    = aix_network.AixNetwork(collected_at)
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
            'gather': timeafterfs - timebeforecpu,
            'json': timeafterjson - timebeforejson,
        }

    elif _PLATFORM == "linux":
        timebeforecpu = time.time()
        mycpu    = linux_cpu.Cpu(collected_at)
        mydisk   = linux_disk.Disk(collected_at)
        mymemory = linux_memory.Memory(collected_at)
        myfs     = linux_filesystems.Filesystems(collected_at)
        mynet    = linux_network.Network(collected_at)
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
        timings = {
            'total': timeend - timestart,
            'startup': timebeforecpu - timestart,
            'cloud': timeaftercloud - timebeforecloud,
            'gather': timeafterfs - timebeforecpu,
            'json': timeafterjson - timebeforejson,
        }

    return jsonout, timings


def dump_json_file(json_string, logger):
    """Dump JSON output to a file with uuid-timestamp naming.

    Filename format: <uuid>-<timestamp>.json
    Writes to the collected-data/ subdirectory of the current directory,
    creating it if needed. Silently fails if not writable.
    """
    try:
        data_dir = "collected-data"
        os.makedirs(data_dir, exist_ok=True)
        filename = os.path.join(data_dir, f"{uuid.uuid4()}-{int(time.time())}.json")
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
    print(f"Time for all gatherers (CPU, disk, memory, fs, net): \t{timings['gather']}")
    print(f"Time to generate json: \t\t\t\t\t{timings['json']}")


def main():
    parser = create_argument_parser()
    args = parser.parse_args()

    # Handle --once shorthand: sets max_iterations to 1
    if args.once:
        args.max_iterations = 1

    logger = log_setup()
    import json
    cfg = Config(args)

    iteration = 0

    while True:
        iteration += 1

        # Collect metrics
        jsonout, timings = collect_once(logger, json)

        # Print diagnostics and JSON
        print_timings(timings)
        print(jsonout)

        # Dump JSON to file if enabled (via --dump flag or config.ini [output] dump_json)
        if cfg.dump_json:
            dump_json_file(jsonout, logger)

        # Check if we should exit
        if cfg.max_iterations is not None and iteration >= cfg.max_iterations:
            break

        # Sleep until next collection
        time.sleep(cfg.run_interval)


if __name__ == "__main__":
    main()
