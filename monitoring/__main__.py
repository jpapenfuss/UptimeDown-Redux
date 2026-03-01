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
#   2. Add a matching elif branch in main() with its gather calls and JSON keys.
import sys
import time
timestart = time.time()

from log_setup import log_setup

# sys.platform values: "linux", "aix", "darwin", "freebsd7" ... "freebsd14", etc.
_PLATFORM = sys.platform

if _PLATFORM == "aix":
    from gather import aix_cpu, aix_disk, aix_filesystems, aix_memory, aix_network
elif _PLATFORM == "linux":
    from gather import linux_cpu, linux_disk, linux_memory, linux_filesystems, linux_network
else:
    raise RuntimeError(f"Unsupported platform: {_PLATFORM!r}")


def main():
    logger = log_setup()
    import json

    if _PLATFORM == "aix":
        timebeforecpu = time.time()
        mycpu    = aix_cpu.AixCpu()
        mydisk   = aix_disk.AixDisk()
        myfs     = aix_filesystems.AixFilesystems()
        mymemory = aix_memory.AixMemory()
        mynet    = aix_network.AixNetwork()
        timeafterfs = time.time()

        timebeforejson = time.time()
        jsonout = json.dumps({
            "cpustats":    mycpu.cpustat_values,
            "disks":       mydisk.blockdevices,
            "disk_total":  mydisk.disk_total,
            "filesystems": myfs.filesystems,
            "memory":      mymemory.stats,
            "network":     mynet.interfaces,
        }, indent=4)
        timeafterjson = time.time()

        timeend = time.time()
        print(f"Time between start and finish: \t\t\t\t{timeend - timestart}")
        print(f"Time from start to before gathering: \t\t\t{timebeforecpu - timestart}")
        print(f"Time from start to end of CPU Stat: \t\t\t{mycpu.cpustat_values['_time'] - timestart}")
        print(f"Time from end of CPU to end of Disk: \t\t\t{mydisk.disk_total['_time'] - mycpu.cpustat_values['_time']}")
        print(f"Time from end of Disk to end of FS: \t\t\t{myfs.filesystems['_time'] - mydisk.disk_total['_time']}")
        print(f"Time from end of FS to end of Memory: \t\t\t{mymemory.stats['memory']['_time'] - myfs.filesystems['_time']}")
        print(f"Time from start to end of gathering stats: \t\t{timeafterfs - timebeforecpu}")
        print(f"Time to generate json: \t\t\t\t\t{timeafterjson - timebeforejson}")

    elif _PLATFORM == "linux":
        timebeforecpu = time.time()
        mycpu    = linux_cpu.Cpu()
        mymemory = linux_memory.Memory()
        myfs     = linux_filesystems.Filesystems()
        mynet    = linux_network.Network()
        timeafterfs = time.time()

        timebeforejson = time.time()
        jsonout = json.dumps({
            "cpustats":    mycpu.cpustat_values,
            "cpuinfo":     mycpu.cpuinfo_values,
            "memory":      mymemory.stats,
            "filesystems": myfs.filesystems,
            "network":     mynet.interfaces,
        }, indent=4)
        timeafterjson = time.time()

        timeend = time.time()
        print(f"Time between start and finish: \t\t\t\t{timeend - timestart}")
        print(f"Time from start to before gathering: \t\t\t{timebeforecpu - timestart}")
        print(f"Time from start to end of CPU Stat: \t\t\t{mycpu.cpustat_values['_time'] - timestart}")
        print(f"Time from end of CPU Info to end of CPU Stat: \t\t{mycpu.cpustat_values['_time'] - mycpu.cpuinfo_values['_time']}")
        print(f"Time from end of CPU Info to end of Memory: \t\t{mymemory.stats['memory']['_time'] - mycpu.cpuinfo_values['_time']}")
        if mymemory.stats["slabs"] is not False:
            print(f"Time from end of Memory to end of Slabs: \t\t{mymemory.stats['slabs']['_time'] - mymemory.stats['memory']['_time']}")
        else:
            print(f"Time from end of Memory to end of Slabs: \t\tskipped (slabinfo unreadable)")
        if mymemory.stats["slabs"] is not False:
            print(f"Time from end of Slabs to end of FS: \t\t\t{myfs.filesystems['_time'] - mymemory.stats['slabs']['_time']}")
        else:
            print(f"Time from end of Memory to end of FS: \t\t\t{myfs.filesystems['_time'] - mymemory.stats['memory']['_time']}")
        print(f"Time from start to end of gathering stats: \t\t{timeafterfs - timebeforecpu}")
        print(f"Time to generate json: \t\t\t\t\t{timeafterjson - timebeforejson}")

    print(jsonout)


if __name__ == "__main__":
    main()
