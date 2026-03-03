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
import sys
sys.dont_write_bytecode = True
import json
import logging
import os
import time

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())


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
        """Parse /etc/filesystems and enrich with statvfs where mounted.

        /etc/filesystems stanza format (AIX-specific):
            /mountpoint:
                    dev     = /dev/fslv00
                    vfs     = jfs2
                    log     = INLINE
                    mount   = false|automatic|true
                    type    = wpar01       (WPAR name; absent for global LPARs)
                    account = false

        Every stanza is parsed and attempted via os.statvfs():
          - Success (mounted):   entry gets full statvfs-derived space stats,
                                 mounted=True, pct_used/pct_free/bytes_* fields.
          - OSError (unmounted): entry carries only config fields, mounted=False.
            This captures WPAR filesystems that are configured but not active,
            enabling alerting when they come online already nearly full.

        The 'options' field (if present in /etc/filesystems) is parsed into a
        JSON object by _parse_options() — bare flags map to true, key=value
        pairs map to the value string.

        Returns a dict keyed by mountpoint, with a top-level '_time' key.
        Returns {} and logs an error if /etc/filesystems is unreadable.
        """
        logger.debug("get_filesystems: reading /etc/filesystems")
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
                # Stanza headers start at column 0 with no leading whitespace and end with ":".
                # Use stripped (whitespace-removed) to detect headers, ensuring tabs/spaces are
                # treated uniformly. Check that original line doesn't start with whitespace.
                if stripped and not line.startswith((' ', '\t')) and stripped.endswith(":"):
                    current_stanza = stripped.rstrip(":")
                    config[current_stanza] = {}
                elif current_stanza and "=" in line:
                    key, _, val = line.partition("=")
                    config[current_stanza][key.strip()] = val.strip()

        logger.debug("get_filesystems: parsed %d stanzas from /etc/filesystems", len(config))

        # Attempt statvfs on each configured mountpoint.
        filesystems = {}
        nmounted = 0
        nunmounted = 0
        for mountpoint, attrs in config.items():
            entry = {
                "mountpoint": mountpoint,
                "dev":        attrs.get("dev", ""),
                "vfs":        attrs.get("vfs", ""),
                "log":        attrs.get("log", ""),
                "mount":      attrs.get("mount", ""),
                "type":       attrs.get("type", ""),
                "account":    attrs.get("account", ""),
                "options":    json.dumps(self._parse_options(attrs.get("options", ""))),
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
                    entry["bytes_total"]     = st.f_frsize * st.f_blocks
                    entry["bytes_free"]      = st.f_frsize * st.f_bfree
                    entry["bytes_available"] = st.f_frsize * st.f_bavail
                    entry["pct_free"]        = int((st.f_bfree  / st.f_blocks) * 1000000) / 10000
                    entry["pct_available"]   = int((st.f_bavail / st.f_blocks) * 1000000) / 10000
                    entry["pct_used"]        = int((1.0 - st.f_bfree  / st.f_blocks) * 1000000) / 10000
                    entry["pct_reserved"]    = int(((st.f_bfree - st.f_bavail) / st.f_blocks) * 1000000) / 10000
                    logger.debug("get_filesystems:   mounted  %s (%s, %s) %.1f%% used",
                                 mountpoint, entry["dev"], entry["vfs"],
                                 entry["pct_used"])
                else:
                    logger.debug("get_filesystems:   mounted  %s (%s, %s) no block storage",
                                 mountpoint, entry["dev"], entry["vfs"])
                nmounted += 1
            except OSError:
                entry["mounted"] = False
                logger.debug("get_filesystems:   unmounted %s (%s, %s)",
                             mountpoint, entry["dev"], entry["vfs"])
                nunmounted += 1

            filesystems[mountpoint] = entry

        filesystems["_time"] = time.time()
        logger.debug("get_filesystems: total=%d mounted=%d unmounted=%d",
                     len(config), nmounted, nunmounted)
        return filesystems

    def __init__(self):
        """Parse /etc/filesystems and probe each mountpoint via statvfs."""
        logger.debug("AixFilesystems: initializing")
        self.filesystems = self.get_filesystems()
        # Count mounted filesystems, excluding the _time metadata key.
        nmounted = sum(1 for k, v in self.filesystems.items()
                       if k != "_time" and v.get("mounted"))
        logger.debug("AixFilesystems: initialized (%d total, %d mounted)",
                     len(self.filesystems) - 1, nmounted)


if __name__ == "__main__":
    import pprint
    pp = pprint.PrettyPrinter(indent=4)
    myfs = AixFilesystems()
    mounted   = {k: v for k, v in myfs.filesystems.items() if isinstance(v, dict) and v.get("mounted")}
    unmounted = {k: v for k, v in myfs.filesystems.items() if isinstance(v, dict) and not v.get("mounted")}
    print(f"Total: {len(myfs.filesystems)-1}  Mounted: {len(mounted)}  Unmounted: {len(unmounted)}")
    pp.pprint(myfs.filesystems)
