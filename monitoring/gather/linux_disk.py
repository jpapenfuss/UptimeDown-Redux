# Linux disk gatherer. Reads /proc/diskstats and (eventually) /sys/dev/block/.
#
# Exposes a Disk class. After instantiation:
#   blockdevices — dict keyed by device name, each entry containing an
#                  "iostats" sub-dict of /proc/diskstats counters plus '_time'.
#
# NOTE: get_sys_stats() and get_queue() are stubs. /sys/block enrichment is
# not yet implemented.
#
# References:
#   https://www.kernel.org/doc/Documentation/ABI/testing/procfs-diskstats
#   https://www.kernel.org/doc/Documentation/admin-guide/iostats.rst
#   https://www.kernel.org/doc/Documentation/block/queue-sysfs.txt
import sys
sys.dont_write_bytecode = True
import logging
import os
import time

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())

# Device name prefixes to skip entirely — these are not physical storage.
#   loop  = loopback devices
#   ram   = RAM-backed block devices
# nbd (network block device) and zram are intentionally NOT ignored here
# in case callers want to monitor them; filter them in the caller if needed.
IGNORE_PREFIXES = (
    "loop",
    "ram",
)

# Column names for /proc/diskstats fields, in order. The device name column
# (index 2 in the raw file) is popped before zipping, so it is omitted here.
DISKSTAT_KEYS = (
    "major",
    "minor",
    "read_ios",
    "read_merge",
    "read_sectors",
    "read_ticks",
    "write_ios",
    "write_merges",
    "write_sectors",
    "write_ticks",
    "in_flight",
    "total_io_ticks",
    "total_time_in_queue",
    "discard_ios",
    "discard_merges",
    "discard_sectors",
    "discard_ticks",
    "flush_ios",
    "flush_ticks",
)

# /sys/block/<dev>/ files we intend to read once get_sys_stats() is implemented.
BLOCK_FILES = [
    "inflight",
    "size",
    "queue/discard_granularity",
    "queue/hw_sector_size",
    "queue/io_poll",
    "queue/io_poll_delay",
    "queue/io_timeout",
    "queue/iostats",
    "queue/logical_block_size",
    "queue/max_hw_sectors_kb",
    "queue/max_sectors_kb",
    "queue/minimum_io_size",
    "queue/nomerges",
    "queue/optimal_io_size",
    "queue/physical_block_size",
    "queue/read_ahead_kb",
    "queue/rotational",
    "queue/rq_affinity",
    "queue/scheduler",
    "queue/write_cache",
]


class Disk:
    sys_block_path = "/sys/block/"
    # /sys/class/block was absent on some older kernels (e.g. QNAP kernel 4.14).
    sys_class_block_path = "/sys/class/block/"
    sys_dev_block_path = "/sys/dev/block/"
    proc_diskstats_path = "/proc/diskstats"

    def get_devices(self):
        """Parse /proc/diskstats and return a dict of per-device I/O counters.

        Each entry is keyed by device name (e.g. "sda", "nvme0n1") and contains
        an "iostats" sub-dict of integer counters mapped by DISKSTAT_KEYS, plus
        a '_time' timestamp.  Devices whose names start with any prefix in
        IGNORE_PREFIXES are skipped.

        /proc/diskstats format (one line per device):
            major minor name field1 field2 ... fieldN
        The device name is at index 2; it is popped before zipping so the
        remaining tokens align with DISKSTAT_KEYS positionally.

        Counters beyond the first 11 (discard and flush fields) were added in
        Linux 4.18 and 5.5 respectively.  zip() stops at the shorter iterable,
        so older kernels with fewer fields are handled without error — the
        missing counters simply won't appear in the output dict.

        Returns None if /proc/diskstats is unreadable.
        """
        logger.debug("get_devices: reading %s", self.proc_diskstats_path)
        diskstats = {}
        if util.caniread(self.proc_diskstats_path) is False:
            logger.error(f"Fatal: Can't open {self.proc_diskstats_path} for reading.")
            return None

        ts = time.time()
        nskipped = 0
        with open(self.proc_diskstats_path, "r") as reader:
            # Example line:
            #   8  0 sda 6812071 23231120 460799263 43073497 9561353 55255999 ...
            # Fields: major minor name [DISKSTAT_KEYS...]
            diskstats_line = str(reader.readline()).strip().split()
            while diskstats_line != []:
                if diskstats_line[2].startswith(IGNORE_PREFIXES):
                    # Skip loop and ram devices — they inflate the device list
                    # with entries that are never interesting for monitoring.
                    logger.debug("get_devices: skipping %s (ignored prefix)", diskstats_line[2])
                    nskipped += 1
                    diskstats_line = str(reader.readline()).strip().split()
                    continue
                # Pop the device name from index 2 before zipping the counters.
                diskname = diskstats_line.pop(2)
                diskstats[diskname] = {
                    "iostats": dict(zip(DISKSTAT_KEYS, map(int, diskstats_line))),
                    "_time": ts,
                }
                diskstats_line = str(reader.readline()).strip().split()
        logger.debug("get_devices: found %d block devices (%d skipped)", len(diskstats), nskipped)
        for devname, entry in diskstats.items():
            s = entry["iostats"]
            logger.debug("get_devices:   %s (%d:%d) read_ios=%d write_ios=%d in_flight=%d "
                         "read_sectors=%d write_sectors=%d",
                         devname, s["major"], s["minor"],
                         s["read_ios"], s["write_ios"], s["in_flight"],
                         s.get("read_sectors", 0), s.get("write_sectors", 0))
        return diskstats

    def get_sys_stats(self, devnum):
        """Stub: will read /sys/dev/block/<major>:<minor>/ for a given device.

        devnum is a "major:minor" string (e.g. "8:0").  The symlink at
        /sys/dev/block/<devnum> resolves to the device's sysfs directory,
        which may represent a whole disk, a partition, an md array, a dm
        device, or an NVMe namespace — each with a different sub-tree shape.
        Not yet implemented.
        """
        pass

    def get_queue(self, queue):
        """Stub: will read queue/* sysfs attributes for a block device.

        Not yet implemented. See BLOCK_FILES for the intended attribute list.
        """
        return 0

    def get_disks(self):
        """Collect stats for all non-ignored block devices.

        Calls get_devices() for /proc/diskstats counters, then for each device
        calls get_sys_stats() with its "major:minor" string to enrich the entry
        with /sys/dev/block/ data (currently a no-op stub — see get_sys_stats).
        Sets self.blockdevices to the resulting dict.
        """
        logger.debug("get_disks: starting collection")
        devs = self.get_devices()
        if devs is None:
            logger.error("get_disks: get_devices() returned None, skipping")
            return
        for dev in devs:
            # Build the "major:minor" string that /sys/dev/block/ uses as a key.
            devnum = (
                str(devs[dev]["iostats"]["major"])
                + ":"
                + str(devs[dev]["iostats"]["minor"])
            )
            self.get_sys_stats(devnum)
        self.blockdevices = devs
        logger.debug("get_disks: collected stats for %d devices", len(devs))

    def __init__(self):
        self.blockdevices = {}
        self.get_disks()


if __name__ == "__main__":
    import pprint
    import util  # pylint: disable=import-error
    mydisk = Disk()
    pprint.PrettyPrinter(indent=4).pprint(mydisk.blockdevices)
else:
    from . import util
