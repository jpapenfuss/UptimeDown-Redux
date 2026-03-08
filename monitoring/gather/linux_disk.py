# Linux disk gatherer. Reads /proc/diskstats for per-device I/O counters
# and enriches each entry with sysfs data (size, rotational, block sizes,
# scheduler) from /sys/dev/block/.
#
# Exposes a Disk class. After instantiation:
#   blockdevices — flat dict keyed by device name containing /proc/diskstats
#                  counters merged with /sys/dev/block/ sysfs attributes.
#
# References:
#   https://www.kernel.org/doc/Documentation/ABI/testing/procfs-diskstats
#   https://www.kernel.org/doc/Documentation/admin-guide/iostats.rst
#   https://www.kernel.org/doc/Documentation/block/queue-sysfs.txt
import sys
sys.dont_write_bytecode = True
import logging
import os
import re
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


class Disk:
    """Linux disk gatherer. Reads /proc/diskstats for per-device I/O counters.

    After instantiation:
        blockdevices — flat dict keyed by device name (e.g. "sda", "nvme0n1"),
                       each entry containing integer counters from DISKSTAT_KEYS
                       merged with sysfs attributes (size_bytes, rotational,
                       physical_block_size, logical_block_size, discard_granularity,
                       scheduler) where available.

    Devices matching IGNORE_PREFIXES (loop*, ram*) are silently skipped.
    """

    sys_block_path = "/sys/block/"
    # /sys/class/block was absent on some older kernels (e.g. QNAP kernel 4.14).
    sys_class_block_path = "/sys/class/block/"
    sys_dev_block_path = "/sys/dev/block/"
    proc_diskstats_path = "/proc/diskstats"

    def get_devices(self, _time=None):
        """Parse /proc/diskstats and return a dict of per-device I/O counters.

        Each entry is keyed by device name (e.g. "sda", "nvme0n1") and contains
        a flat dict of integer counters mapped by DISKSTAT_KEYS.
        Devices whose names start with any prefix in
        IGNORE_PREFIXES are skipped.

        /proc/diskstats format (one line per device):
            major minor name field1 field2 ... fieldN
        The device name is at index 2; it is popped before zipping so the
        remaining tokens align with DISKSTAT_KEYS positionally.

        Counters beyond the first 11 (discard and flush fields) were added in
        Linux 4.18 and 5.5 respectively.  zip() stops at the shorter iterable,
        so older kernels with fewer fields are handled without error — the
        missing counters simply won't appear in the output dict.

        Returns False if /proc/diskstats is unreadable.
        """
        logger.debug("get_devices: reading %s", self.proc_diskstats_path)
        diskstats = {}
        if not util.caniread(self.proc_diskstats_path):
            logger.error("linux_disk: can't read %s", self.proc_diskstats_path)
            return False

        nskipped = 0
        try:
            with open(self.proc_diskstats_path, "r") as reader:
                # Example line:
                #   8  0 sda 6812071 23231120 460799263 43073497 9561353 55255999 ...
                # Fields: major minor name [DISKSTAT_KEYS...]
                diskstats_line = reader.readline().strip().split()
                while diskstats_line != []:
                    try:
                        if diskstats_line[2].startswith(IGNORE_PREFIXES):
                            # Skip loop and ram devices — they inflate the device list
                            # with entries that are never interesting for monitoring.
                            logger.debug("get_devices: skipping %s (ignored prefix)", diskstats_line[2])
                            nskipped += 1
                            diskstats_line = reader.readline().strip().split()
                            continue
                        # Pop the device name from index 2 before zipping the counters.
                        diskname = diskstats_line.pop(2)
                        diskstats[diskname] = util.dict_from_fields(diskstats_line, DISKSTAT_KEYS)
                    except (IndexError, ValueError, TypeError) as e:
                        logger.warning("get_devices: error parsing diskstats line: %s", e)
                    diskstats_line = reader.readline().strip().split()
        except (IOError, OSError) as e:
            logger.error("linux_disk: error reading /proc/diskstats: %s", e)
            return False
        logger.debug("get_devices: found %d block devices (%d skipped)", len(diskstats), nskipped)
        for devname, s in diskstats.items():
            logger.debug("get_devices:   %s (%d:%d) read_ios=%d write_ios=%d in_flight=%d "
                         "read_sectors=%d write_sectors=%d",
                         devname, s["major"], s["minor"],
                         s["read_ios"], s["write_ios"], s["in_flight"],
                         s.get("read_sectors", 0), s.get("write_sectors", 0))
        return diskstats

    def get_queue(self, queue_path):
        """Read queue/* sysfs attributes for a block device.

        queue_path is the absolute path to the device's queue/ directory,
        e.g. "/sys/dev/block/8:0/queue".

        Returns a dict with any of:
            rotational          (int) — 1=HDD, 0=SSD/NVMe
            physical_block_size (int) — physical sector size in bytes
            logical_block_size  (int) — logical sector size in bytes
            scheduler           (str) — active I/O scheduler name (the bracketed entry)
            discard_granularity (int) — discard/TRIM granularity in bytes
        Missing files are silently omitted.
        """
        result = {}

        for attr in ("rotational", "physical_block_size", "logical_block_size",
                     "discard_granularity"):
            val = util.read_sysfs_int(os.path.join(queue_path, attr))
            if val is not None:
                result[attr] = val

        # scheduler: "none [mq-deadline] bfq" — extract the bracketed token.
        sched_line = util.read_sysfs_str(os.path.join(queue_path, "scheduler"))
        if sched_line:
            m = re.search(r"\[([^\]]+)\]", sched_line)
            if m:
                result["scheduler"] = m.group(1)

        return result

    def get_sys_stats(self, devnum):
        """Read /sys/dev/block/<major>:<minor>/ for a given device.

        devnum is a "major:minor" string (e.g. "8:0").  The symlink at
        /sys/dev/block/<devnum> resolves to the device's sysfs directory.
        Reads size_bytes from the "size" file (sectors × 512), then calls
        get_queue() to enrich with queue attributes.

        For partition entries the queue/ subdirectory does not exist; in that
        case get_queue() is called on the parent device's queue/ instead (one
        level up, i.e. "../queue").

        Returns a dict with size_bytes and any queue attributes on success,
        or an empty dict if the sysfs path cannot be resolved.
        """
        symlink = os.path.join(self.sys_dev_block_path, devnum)
        try:
            dev_path = os.path.realpath(symlink)
        except OSError:
            logger.debug("get_sys_stats: realpath failed for %s", symlink)
            return {}

        result = {}

        # Read device size in 512-byte sectors.
        try:
            with open(os.path.join(dev_path, "size"), "r") as f:
                sectors = int(f.read().strip())
            result["size_bytes"] = sectors * 512
        except (FileNotFoundError, ValueError, OSError):
            pass

        # Prefer the device's own queue/; fall back to parent's for partitions.
        queue_path = os.path.join(dev_path, "queue")
        if not os.path.isdir(queue_path):
            queue_path = os.path.join(dev_path, "..", "queue")
        result.update(self.get_queue(queue_path))

        logger.debug("get_sys_stats: %s → %s size_bytes=%s rotational=%s scheduler=%s",
                     devnum, dev_path,
                     result.get("size_bytes", "?"),
                     result.get("rotational", "?"),
                     result.get("scheduler", "?"))
        return result

    def get_disks(self):
        """Collect stats for all non-ignored block devices.

        Calls get_devices() for /proc/diskstats counters, then for each device
        calls get_sys_stats() with its "major:minor" string to enrich the entry
        with /sys/dev/block/ data (size_bytes, rotational, block sizes, scheduler).
        Sets self.blockdevices to the resulting dict.
        """
        logger.debug("get_disks: starting collection")
        ts = getattr(self, '_ts', None)
        devs = self.get_devices(ts)
        if devs is False:
            logger.error("linux_disk: get_devices() failed, skipping")
            return
        for dev in devs:
            # Build the "major:minor" string that /sys/dev/block/ uses as a key.
            devnum = (
                str(devs[dev]["major"])
                + ":"
                + str(devs[dev]["minor"])
            )
            sys_stats = self.get_sys_stats(devnum)
            if sys_stats:
                devs[dev].update(sys_stats)
        self.blockdevices = devs
        logger.debug("get_disks: collected stats for %d devices", len(devs))

    def __init__(self, _time=None):
        """Initialise blockdevices to {} and call get_disks() to populate it."""
        self._ts = _time if _time is not None else time.time()
        self.blockdevices = {}
        self.get_disks()


if __name__ == "__main__":
    import pprint
    import util  # pylint: disable=import-error
    mydisk = Disk()
    pprint.PrettyPrinter(indent=4).pprint(mydisk.blockdevices)
else:
    from . import util
