# Linux memory gatherer. Reads /proc/meminfo and /proc/slabinfo.
#
# Exposes a Memory class with one attribute after instantiation:
#   stats — dict with two sub-dicts:
#       stats["memory"] — all /proc/meminfo fields, values converted to bytes
#       stats["slabs"]  — per-slab allocator stats from /proc/slabinfo,
#                         or False if slabinfo is unreadable (requires root)
#
# Both sub-dicts include a '_time' key.
import sys
sys.dont_write_bytecode = True
import time
import logging

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())


class Memory:

    @staticmethod
    def _meminfo_key(raw):
        """Normalize a /proc/meminfo field name to snake_case.

        Examples:
            MemTotal        → mem_total
            HugePages_Total → huge_pages_total
            SReclaimable    → s_reclaimable
        """
        import re
        # Insert underscore before each uppercase letter that follows a
        # lowercase letter or digit (camelCase boundary).
        s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', raw)
        # Handle names that start with a run of uppercase letters (e.g. SReclaimable,
        # SUnreclaim, KReclaimable) where the first regex finds no lowercase→uppercase
        # boundary.  Match an uppercase letter followed by another uppercase+lowercase
        # pair and insert the underscore between them.
        s = re.sub(r'([A-Z])([A-Z][a-z])', r'\1_\2', s)
        return s.lower()

    def GetMeminfo(self):
        """Parse /proc/meminfo and return a dict of memory statistics.

        All values with a unit multiplier (kB) are converted to bytes via
        util.tobytes(). Values without a multiplier are stored as plain ints.
        Keys are normalized to snake_case (e.g. MemTotal → mem_total).

        /proc/meminfo lines have two forms:
            MemTotal:       16384 kB   (3 tokens: name, value, unit)
            HugePages_Total:       0   (2 tokens: name, value — no unit)
        The colon is stripped from the key before splitting on whitespace.

        Raises RuntimeError if /proc/meminfo is unreadable — it must always
        exist on Linux; absence indicates a serious kernel or mount problem.
        """
        logger.debug("GetMeminfo: reading /proc/meminfo")
        meminfo_path = "/proc/meminfo"
        meminfo_values = {}

        if not util.caniread(meminfo_path):
            raise RuntimeError(f"Can't open {meminfo_path} for reading.")
        with open(meminfo_path, "r") as reader:
            meminfo_line = str(reader.readline()).strip()
            while meminfo_line != "":
                # Replace the trailing colon on the key so we can split uniformly.
                # Example before: "MemTotal:       16384 kB"
                # Example after split: ["MemTotal", "16384", "kB"]
                meminfo_line = meminfo_line.replace(":", " ")
                line = meminfo_line.split()
                key = self._meminfo_key(line[0])
                line[1] = int(line[1])
                # Three tokens means there's a unit multiplier (e.g. "kB").
                if len(line) == 3:
                    line[1] = util.tobytes(line[1], line[2])
                meminfo_values[key] = line[1]
                meminfo_line = str(reader.readline()).strip()
        meminfo_values["_time"] = time.time()
        nfields = len(meminfo_values) - 1  # exclude _time
        logger.debug("GetMeminfo: parsed %d fields", nfields)
        logger.debug("GetMeminfo: mem_total=%d mem_free=%d mem_available=%d",
                     meminfo_values.get("mem_total", 0),
                     meminfo_values.get("mem_free", 0),
                     meminfo_values.get("mem_available", 0))
        logger.debug("GetMeminfo: swap_total=%d swap_free=%d cached=%d buffers=%d",
                     meminfo_values.get("swap_total", 0),
                     meminfo_values.get("swap_free", 0),
                     meminfo_values.get("cached", 0),
                     meminfo_values.get("buffers", 0))
        return meminfo_values

    def GetSlabinfo(self):
        """Parse /proc/slabinfo and return a dict of kernel slab allocator stats.

        /proc/slabinfo requires root. Returns False (not an error) if unreadable
        so the caller can treat slab stats as optional.

        /proc/slabinfo format (v2.1):
            slabinfo - version: 2.1
            # name     <active_objs> <num_objs> <objsize> <objperslab> <pagesperslab> \
            #   : tunables <limit> <batchcount> <sharedfactor> \
            #   : slabdata <active_slabs> <num_slabs> <sharedavail>

        The ": tunables" and ": slabdata" section markers are stripped before
        splitting so the 14 data fields can be zipped uniformly.

        Each slab entry is stored as a dict of 11 integer fields:
            active_objs, num_objs, objsize, objperslab, pagesperslab,
            limit, batchcount, sharedfactor, active_slabs, num_slabs, sharedavail
        """
        logger.debug("GetSlabinfo: reading /proc/slabinfo")
        slabs = {}
        if (util.caniread("/proc/slabinfo")) is False:
            logger.warning(
                "Can't read /proc/slabinfo - I may not be root. Will not collect slab stats"
            )
            return False
        with open("/proc/slabinfo", "r") as reader:
            slabline = reader.readline()
            while slabline != "":
                # Skip the version header ("slabinfo - version: 2.1") and the
                # column-name comment line ("# name  <active_objs> ...").
                if slabline.startswith("slabinfo") or slabline.startswith("# name"):
                    slabline = reader.readline()
                    continue
                # Strip ": tunables" and ": slabdata" section markers so the
                # remaining tokens are uniformly positional.
                # Before: ext4_inode_cache 30338 44330 1096 29 8 : tunables 0 0 0 : slabdata 2834 2834 0
                # After:  ext4_inode_cache 30338 44330 1096 29 8   0 0 0   2834 2834 0
                slabline = slabline.replace(": tunables", "").replace(": slabdata", "")
                slab = slabline.strip().split()
                slabname = slab.pop(0)
                slabs[slabname] = dict(
                    zip(
                        [
                            "active_objs",
                            "num_objs",
                            "objsize",
                            "objperslab",
                            "pagesperslab",
                            "limit",
                            "batchcount",
                            "sharedfactor",
                            "active_slabs",
                            "num_slabs",
                            "sharedavail",
                        ],
                        list(map(int, slab)),
                    )
                )
                slabline = reader.readline()
        slabs["_time"] = time.time()
        nslabs = len(slabs) - 1  # exclude _time
        logger.debug("GetSlabinfo: parsed %d slab entries", nslabs)
        # Log only the top 5 slabs by active_objs — there can be hundreds of
        # slab types and logging all of them would flood the debug log.
        top = sorted(
            ((k, v["active_objs"]) for k, v in slabs.items() if k != "_time"),
            key=lambda x: x[1], reverse=True
        )[:5]
        for name, active in top:
            logger.debug("GetSlabinfo:   %s active_objs=%d", name, active)
        return slabs

    def __init__(self):
        logger.debug("Memory: initializing")
        self.stats = {}
        self.stats["memory"] = self.GetMeminfo()
        self.stats["slabs"] = self.GetSlabinfo()
        logger.debug("Memory: initialized (slabs=%s)",
                     "collected" if self.stats["slabs"] is not False else "unavailable")


if __name__ == "__main__":
    import util  # pylint: disable=import-error
    import pprint

    pp = pprint.PrettyPrinter(indent=4)
    mymemory = Memory()
    pp.pprint(mymemory.stats)
else:
    from . import util
