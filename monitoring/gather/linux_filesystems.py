# Linux filesystem gatherer. Reads /proc/mounts (or /etc/mtab as fallback)
# and calls os.statvfs() for space usage on each real filesystem.
#
# Exposes a Filesystems class. After instantiation:
#   filesystems — dict keyed by mount path, each entry containing device,
#                 filesystem type, mount options, and space stats. Also has a
#                 top-level '_time' key.
#
# Virtual filesystems (cgroup, sysfs, tmpfs, etc.) are excluded via FS_IGNORE.
#
# References:
#   https://docs.python.org/3/library/os.html#os.statvfs
#   https://man7.org/linux/man-pages/man3/statvfs.3.html
import sys
sys.dont_write_bytecode = True
import json
import logging
import os
import time

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())

# Filesystem types that carry no real block storage and should be skipped.
# Add entries here as new virtual fs types are encountered.
FS_IGNORE = [
    "autofs",
    "bpf",
    "cgroup",
    "cgroup2",
    "configfs",
    "debugfs",
    "devpts",
    "devtmpfs",
    "fusectl",
    "hugetlbfs",
    "mqueue",
    "proc",
    "pstore",
    "securityfs",
    "squashfs",
    "sysfs",
    "tmpfs",
    "tracefs",
    "efivarfs",
    "rpc_pipefs",
    "fuse",
    "binfmt_misc",
    "overlay",
]

class Filesystems:

    @staticmethod
    def _parse_options(options_str):
        """Parse a comma-separated mount options string into a dict.

        Bare flags (e.g. 'rw', 'noatime') map to True.
        Key=value pairs (e.g. 'size=1g', 'uid=0') map to the value string.
        The result is intended to be stored as JSON via json.dumps().
        """
        opts = {}
        for token in options_str.split(","):
            token = token.strip()
            if not token:
                continue
            if "=" in token:
                k, _, v = token.partition("=")
                opts[k.strip()] = v.strip()
            else:
                opts[token] = True
        return opts

    def get_filesystems(self):
        """Determine the best available mount source and return parsed filesystems.

        Prefers /proc/mounts as the authoritative kernel view. Falls back to
        /etc/mtab if /proc/mounts is unreadable. Both files share the same
        whitespace-delimited format so the same parser handles both.
        Exits with an error if neither file is readable.
        """
        mtab_path = "/etc/mtab"
        proc_mounts_path = "/proc/mounts"

        mtab_access = util.caniread(mtab_path)
        proc_mounts_access = util.caniread(proc_mounts_path)

        if proc_mounts_access:
            logger.debug("Can read %s, using that for mounts.", proc_mounts_path)
            filesystems = self.get_filesystems_from_proc(proc_mounts_path)
        elif mtab_access:
            logger.warning("Failed through from proc, but can read %s, using that for mounts.", mtab_path)
            filesystems = self.get_filesystems_from_proc(mtab_path)
        else:
            raise RuntimeError(f"Can't open either {proc_mounts_path} or {mtab_path} for reading.")

        return filesystems

    def explode_statvfs(self, statvfs):
        """Convert an os.statvfs_result into a dict with derived space metrics.

        Returns None if f_blocks == 0 (virtual or empty filesystem with no
        block storage), which signals the caller to reject the mount.

        Byte calculations use f_frsize (fundamental block size), not f_bsize
        (preferred I/O block size). On most Linux filesystems these are equal,
        but f_frsize is the POSIX-correct value for capacity arithmetic and
        matches the calculation used by the AIX gatherer.

        Derived fields added beyond the raw statvfs values:
            bytes_total     — total capacity in bytes (f_blocks * f_frsize)
            bytes_free      — free bytes including reserved root blocks
            bytes_available — free bytes available to unprivileged users
            pct_free        — percentage free (including reserved)
            pct_available   — percentage available to unprivileged users
            pct_used        — percentage consumed (1 - pct_free)
            pct_reserved    — percentage reserved for root (pct_free - pct_available)
        """
        fs_stats = {
            "f_bsize": statvfs.f_bsize,
            "f_frsize": statvfs.f_frsize,
            "f_blocks": statvfs.f_blocks,
            "f_bfree": statvfs.f_bfree,
            "f_bavail": statvfs.f_bavail,
            "f_files": statvfs.f_files,
            "f_ffree": statvfs.f_ffree,
            "f_favail": statvfs.f_favail,
            "f_flag": statvfs.f_flag,
            "f_namemax": statvfs.f_namemax
        }
        # No blocks means no real storage — caller will skip this mount.
        if fs_stats['f_blocks'] == 0:
            return None
        fs_stats["bytes_total"]     = fs_stats["f_frsize"] * fs_stats["f_blocks"]
        fs_stats["bytes_free"]      = fs_stats["f_frsize"] * fs_stats["f_bfree"]
        fs_stats["bytes_available"] = fs_stats["f_frsize"] * fs_stats["f_bavail"]
        try:
            fs_stats["pct_free"]      = int((fs_stats["f_bfree"]  / fs_stats["f_blocks"]) * 1000000) / 10000
            fs_stats["pct_available"] = int((fs_stats["f_bavail"] / fs_stats["f_blocks"]) * 1000000) / 10000
            fs_stats["pct_used"]      = int((1.0 - fs_stats["f_bfree"]  / fs_stats["f_blocks"]) * 1000000) / 10000
            fs_stats["pct_reserved"]  = int(((fs_stats["f_bfree"] - fs_stats["f_bavail"]) / fs_stats["f_blocks"]) * 1000000) / 10000
        except ZeroDivisionError:
            # Should be unreachable: we already excluded f_blocks == 0 above.
            raise RuntimeError(f"ZeroDivisionError on f_blocks for a mount with f_blocks != 0")
        return fs_stats

    def get_filesystems_from_proc(self, proc_mounts_path):
        """Read and parse a /proc/mounts-format file into the filesystems dict.

        Each non-ignored mount is processed by process_mount(), which calls
        explode_statvfs() and explode_options(). Mounts that resolve to virtual
        filesystems (f_blocks == 0) are added to fs_reject so they are silently
        skipped on future calls.

        Note: duplicate mountpoints overwrite earlier entries (last-write wins).
        """
        logger.debug("get_filesystems_from_proc: reading %s", proc_mounts_path)
        fs = {}
        with open(proc_mounts_path, "r") as reader:
            mount_line = str(reader.readline()).strip()
            while mount_line != "":
                mount = mount_line.split()
                filesystem = self.process_mount(mount)
                if filesystem:
                    fs.update(filesystem)
                mount_line = str(reader.readline()).strip()
        fs["_time"] = time.time()
        nmounts = len(fs) - 1  # exclude _time
        logger.debug("get_filesystems_from_proc: collected %d filesystems", nmounts)
        return fs

    def process_mount(self, mount):
        """Process a single parsed mount line and return a one-entry dict, or None.

        mount is a list of 6 strings:
            [device, path, filesystem, options, dump, pass]

        Skips the mount if its filesystem type is in FS_IGNORE or its path is
        in fs_reject (previously found to have no block storage). Returns None
        for skipped or virtual mounts so the caller can discard them cleanly.

        Output entry keys are normalized to match the filesystems schema so
        that Linux and AIX entries can be stored in the same table:
            dev        — block device (was: device)
            mountpoint — mount path   (was: path)
            vfs        — fs type      (was: filesystem)
            options    — mount options as a comma-separated string
            mounted    — always True for entries returned by this method
        Space stats from explode_statvfs() are merged in at the top level
        (no fs_stats sub-dict).
        """
        if mount[2] in FS_IGNORE:
            logger.debug("process_mount: skipping %s (fstype %s ignored)", mount[1], mount[2])
            return {}
        if mount[1] in self.fs_reject:
            logger.debug("process_mount: skipping %s (previously rejected)", mount[1])
            return {}
        try:
            fs_stats = self.explode_statvfs(os.statvfs(mount[1]))
        except OSError as e:
            logger.warning("statvfs(%s) failed: %s — skipping", mount[1], e)
            return {}
        if fs_stats is None:
            # No block storage — remember this path to skip it next time.
            logger.debug("process_mount: %s has no block storage, adding to reject list", mount[1])
            self.fs_reject.append(mount[1])
            return {}
        entry = {
            "mountpoint": mount[1],
            "dev":        mount[0],
            "vfs":        mount[2],
            "options":    json.dumps(self._parse_options(mount[3])),
            "mounted":    True,
        }
        entry.update(fs_stats)
        logger.debug("process_mount: collected %s (%s, %s, %.1f%% used)",
                     mount[1], mount[0], mount[2], fs_stats["pct_used"])
        return {mount[1]: entry}

    def __init__(self):
        # fs_reject accumulates mountpoints with no block storage so they are
        # skipped without a statvfs() call on subsequent UpdateValues() calls.
        self.fs_reject = []
        self.filesystems = self.get_filesystems()


if __name__ == "__main__":
    import util  # pylint: disable=import-error
    myfilesystems = Filesystems()
    import pprint

    pp = pprint.PrettyPrinter(indent=4)
    pp.pprint(myfilesystems.filesystems)
else:
    from . import util
