# AIX filesystem gatherer. Uses /etc/filesystems as the authoritative source
# of all configured filesystems, then attempts os.statvfs() on each to
# determine whether it is currently mounted and to collect live space stats.
#
# Exposes an AixFilesystems class. After instantiation:
#   filesystems — dict keyed by mountpoint path. Every configured filesystem
#                 appears regardless of mount state. Each entry has a 'mounted'
#                 boolean; only mounted entries have statvfs-derived fields
#                 (bytesTotal, bytesFree, pctUsed, etc.).
#
# This approach captures WPARs and other dynamically-mounted filesystems that
# are configured but not currently active, allowing alerting when they come
# online and are already filling up.
import logging
import os
import time

logger = logging.getLogger("monitoring")


class AixFilesystems:
    """AIX filesystem gatherer.

    Reads /etc/filesystems for the complete list of configured filesystems
    (typically 400+ on a WPAR-enabled LPAR), then calls os.statvfs() on each
    mountpoint. Mounted filesystems get full space stats; unmounted ones are
    recorded with config data only and mounted=False.

    Exposes:
        self.filesystems — dict keyed by mountpoint, with '_time' key.
                           Shape matches Linux Filesystems class for mounted
                           entries. Unmounted entries carry dev/vfs/type/etc
                           from /etc/filesystems config with mounted=False.
    """

    def get_filesystems(self):
        """Parse /etc/filesystems and enrich with statvfs where mounted.

        /etc/filesystems stanza format:
            /mountpoint:
                    dev     = /dev/fslv00
                    vfs     = jfs2
                    log     = INLINE
                    mount   = false
                    type    = wpar01
                    account = false

        Returns a dict keyed by mountpoint. All configured filesystems are
        included. The 'mounted' key distinguishes live entries from config-only.
        """
        etc_fs_path = "/etc/filesystems"
        if not os.access(etc_fs_path, os.R_OK):
            logger.error("Can't read %s", etc_fs_path)
            return {}

        # Parse stanzas.
        config = {}
        current_stanza = None
        with open(etc_fs_path, "r") as f:
            for line in f:
                line = line.rstrip("\n")
                stripped = line.strip()
                if not stripped or stripped.startswith("*"):
                    continue
                if not line[0].isspace() and stripped.endswith(":"):
                    current_stanza = stripped.rstrip(":")
                    config[current_stanza] = {}
                elif current_stanza and "=" in line:
                    key, _, val = line.partition("=")
                    config[current_stanza][key.strip()] = val.strip()

        # Attempt statvfs on each configured mountpoint.
        filesystems = {}
        for mountpoint, attrs in config.items():
            entry = {
                "mountpoint": mountpoint,
                "dev":        attrs.get("dev", ""),
                "vfs":        attrs.get("vfs", ""),
                "log":        attrs.get("log", ""),
                "mount":      attrs.get("mount", ""),
                "type":       attrs.get("type", ""),
                "account":    attrs.get("account", ""),
                "options":    attrs.get("options", ""),
            }
            try:
                st = os.statvfs(mountpoint)
                entry["mounted"]  = True
                entry["f_bsize"]  = st.f_bsize
                entry["f_frsize"] = st.f_frsize
                entry["f_blocks"] = st.f_blocks
                entry["f_bfree"]  = st.f_bfree
                entry["f_bavail"] = st.f_bavail
                entry["f_files"]  = st.f_files
                entry["f_ffree"]  = st.f_ffree
                entry["f_favail"] = st.f_favail
                if st.f_blocks > 0:
                    entry["bytesTotal"]     = st.f_frsize * st.f_blocks
                    entry["bytesFree"]      = st.f_frsize * st.f_bfree
                    entry["bytesAvailable"] = st.f_frsize * st.f_bavail
                    entry["pctFree"]        = (st.f_bfree  / st.f_blocks) * 100
                    entry["pctAvailable"]   = (st.f_bavail / st.f_blocks) * 100
                    entry["pctUsed"]        = (1.0 - st.f_bfree  / st.f_blocks) * 100
                    entry["pctReserved"]    = (1.0 - st.f_bavail / st.f_blocks) * 100
            except OSError:
                entry["mounted"] = False

            filesystems[mountpoint] = entry

        filesystems["_time"] = time.time()
        return filesystems

    def __init__(self):
        self.filesystems = self.get_filesystems()


if __name__ == "__main__":
    import pprint
    pp = pprint.PrettyPrinter(indent=4)
    myfs = AixFilesystems()
    mounted   = {k: v for k, v in myfs.filesystems.items() if isinstance(v, dict) and v.get("mounted")}
    unmounted = {k: v for k, v in myfs.filesystems.items() if isinstance(v, dict) and not v.get("mounted")}
    print(f"Total: {len(myfs.filesystems)-1}  Mounted: {len(mounted)}  Unmounted: {len(unmounted)}")
    pp.pprint(myfs.filesystems)
