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
import logging
import os
import time

logger = logging.getLogger("monitoring")

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
            bytesTotal     — total capacity in bytes (f_blocks * f_frsize)
            bytesFree      — free bytes including reserved root blocks
            bytesAvailable — free bytes available to unprivileged users
            pctFree        — percentage free (including reserved)
            pctAvailable   — percentage available to unprivileged users
            pctUsed        — percentage consumed (1 - pctFree)
            pctReserved    — percentage reserved for root (pctFree - pctAvailable)
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
        fs_stats["bytesTotal"]     = fs_stats["f_frsize"] * fs_stats["f_blocks"]
        fs_stats["bytesFree"]      = fs_stats["f_frsize"] * fs_stats["f_bfree"]
        fs_stats["bytesAvailable"] = fs_stats["f_frsize"] * fs_stats["f_bavail"]
        try:
            fs_stats["pctFree"]      = int((fs_stats["f_bfree"]  / fs_stats["f_blocks"]) * 1000000) / 10000
            fs_stats["pctAvailable"] = int((fs_stats["f_bavail"] / fs_stats["f_blocks"]) * 1000000) / 10000
            fs_stats["pctUsed"]      = int((1.0 - fs_stats["f_bfree"]  / fs_stats["f_blocks"]) * 1000000) / 10000
            fs_stats["pctReserved"]  = int((1.0 - fs_stats["f_bavail"] / fs_stats["f_blocks"]) * 1000000) / 10000
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
        if mount[2] in FS_IGNORE or mount[1] in self.fs_reject:
            return {}
        try:
            fs_stats = self.explode_statvfs(os.statvfs(mount[1]))
        except OSError as e:
            logger.warning("statvfs(%s) failed: %s — skipping", mount[1], e)
            return {}
        if fs_stats is None:
            # No block storage — remember this path to skip it next time.
            self.fs_reject.append(mount[1])
            return {}
        entry = {
            "mountpoint": mount[1],
            "dev":        mount[0],
            "vfs":        mount[2],
            "options":    mount[3],   # keep as raw string; parsed form not needed for storage
            "mounted":    True,
        }
        entry.update(fs_stats)
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
