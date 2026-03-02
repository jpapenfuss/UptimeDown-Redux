# Linux CPU gatherer. Reads /proc/cpuinfo, /proc/stat, and /proc/softirqs.
#
# Exposes a Cpu class with two attributes after instantiation:
#   cpuinfo_values  — hardware description for cpu0 (model, MHz, flags, etc.)
#   cpustat_values  — per-core usage counters plus system-wide stats and softirqs
#
# Both dicts include a '_time' key (Unix timestamp) recording when the data
# was captured.  Call UpdateValues() to refresh.
import sys
sys.dont_write_bytecode = True
import time
import logging

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())


class Cpu:
    # Fields from /proc/cpuinfo and /proc/stat that should be coerced to int.
    INTEGER_STATS = [
        "apicid",
        "btime",
        "cache_alignment",
        "clflush size",
        "core id",
        "cpu cores",
        "cpu family",
        "cpuid level",
        "ctxt",
        "guest",
        "guest_nice",
        "idle",
        "initial apicid",
        "iowait",
        "irq",
        "model",
        "nice",
        "physical id",
        "processes",
        "processor",
        "procs_blocked",
        "procs_running",
        "siblings",
        "steal",
        "stepping",
        "system",
        "user",
    ]
    # Fields that should be coerced to float.
    FLOAT_STATS = ["bogomips", "cpu MHz"]
    # Fields whose values are space-separated lists.
    LIST_STATS = ["flags", "bugs"]

    def GetCpuinfo(self):
        """Parse /proc/cpuinfo and return a dict of hardware info for cpu0.

        Reads only up to the first blank line, which terminates the cpu0 stanza.
        Values are coerced to int, float, or list according to INTEGER_STATS,
        FLOAT_STATS, and LIST_STATS. Unknown fields are kept as strings.
        Returns False if /proc/cpuinfo is unreadable.
        """
        logger.debug("GetCpuinfo: reading /proc/cpuinfo")
        cpuinfo_values = {}
        cpuinfo_path = "/proc/cpuinfo"
        if util.caniread(cpuinfo_path) is False:
            logger.warning(f"Can't read {cpuinfo_path}, bailing out.")
            # Non-fatal: other gatherers may still succeed.
            return False
        with open(cpuinfo_path, "r") as reader:
            cpuinfo_line = str(reader.readline()).strip()
            # Stop at the first blank line — that ends the cpu0 stanza.
            while cpuinfo_line != "":
                # Lines look like:  model name      : AMD EPYC 7571
                # Split on the first colon only; the value may contain colons.
                split = cpuinfo_line.split(":", 1)
                if len(split) < 2:
                    # Line without a colon — skip (shouldn't happen in practice).
                    cpuinfo_line = str(reader.readline()).strip()
                    continue
                split[0] = split[0].strip()
                split[1] = split[1].strip()
                if split[0] in self.INTEGER_STATS:
                    cpuinfo_values[split[0]] = int(split[1])
                elif split[0] in self.FLOAT_STATS:
                    cpuinfo_values[split[0]] = float(split[1])
                elif split[0] in self.LIST_STATS:
                    # flags and bugs are space-separated capability strings.
                    cpuinfo_values[split[0]] = split[1].split()
                else:
                    cpuinfo_values[split[0]] = split[1]
                cpuinfo_line = str(reader.readline()).strip()
        cpuinfo_values["_time"] = time.time()
        nfields = len(cpuinfo_values) - 1  # exclude _time
        logger.debug("GetCpuinfo: parsed %d fields for cpu0", nfields)
        logger.debug("GetCpuinfo: model=%r MHz=%s bogomips=%s flags=%d bugs=%d",
                     cpuinfo_values.get("model name", "unknown"),
                     cpuinfo_values.get("cpu MHz", "?"),
                     cpuinfo_values.get("bogomips", "?"),
                     len(cpuinfo_values.get("flags", [])),
                     len(cpuinfo_values.get("bugs", [])))
        return cpuinfo_values

    def GetCpuSoftIrqs(self, cpustats_values):
        """Parse /proc/softirqs and merge per-CPU softirq counters into cpustats_values.

        /proc/softirqs has a header row naming each CPU column, followed by one
        row per IRQ type with a count per CPU.  The header is parsed first to
        guarantee correct column-to-CPU mapping regardless of CPU ordering.

        The softirq counts are stored under cpustats_values[cpuN]["softirqs"][irqname].
        Only CPUs that already exist in cpustats_values (populated by GetCpuProcStats)
        are updated — the aggregate "cpu" key is skipped.
        Returns the updated cpustats_values dict, or False if the file is unreadable.
        """
        logger.debug("GetCpuSoftIrqs: reading /proc/softirqs")
        softirq_path = "/proc/softirqs"
        if util.caniread(softirq_path) is False:
            logger.error(f"Fatal: Can't open {softirq_path} for reading.")
            return False
        nirq_types = 0
        with open(softirq_path, "r") as reader:
            # First line is the header: "    CPU0  CPU1  CPU2 ..."
            # Parse it to get column→CPU name mapping before reading data rows.
            header_line = str(reader.readline()).strip()
            cpu_columns = [c.strip() for c in header_line.split() if c.strip()]
            logger.debug("GetCpuSoftIrqs: header lists %d CPU columns", len(cpu_columns))
            softirq_line = str(reader.readline()).strip()
            while softirq_line != "":
                # Lines look like:  NET_RX:    12345    67890 ...
                # Strip the trailing colon from the IRQ name before splitting.
                irq = softirq_line.replace(":", "").split()
                irqname = irq.pop(0)
                for i, cpu_name in enumerate(cpu_columns):
                    if cpu_name in cpustats_values and cpu_name != "cpu":
                        cpustats_values[cpu_name]["softirqs"][irqname] = int(irq[i])
                nirq_types += 1
                softirq_line = str(reader.readline()).strip()
        ncpus = sum(1 for k in cpustats_values if k.startswith("cpu") and k != "cpu")
        logger.debug("GetCpuSoftIrqs: merged %d softirq types across %d CPUs",
                     nirq_types, ncpus)
        return cpustats_values

    def GetCpuProcStats(self):
        """Parse /proc/stat and return a dict of per-core counters and system-wide stats.

        Each cpu/cpuN line becomes a sub-dict keyed by the CPU name, with fields
        named by cpustats_labels (user, nice, system, idle, ...).  A "softirqs"
        sub-dict is also populated by calling GetCpuSoftIrqs once the per-CPU
        section of /proc/stat is exhausted (triggered by the "intr" line).

        Non-CPU lines (ctxt, btime, processes, procs_running, procs_blocked)
        are stored at the top level, coerced to int or float where known.

        After parsing, the aggregate "cpu" row's tick counters are also promoted
        to top-level schema keys (user_ticks, sys_ticks, etc.) so Linux and AIX
        samples share the same column names in the cpu_stats table.

        Returns False if /proc/stat is unreadable.
        """
        logger.debug("GetCpuProcStats: reading /proc/stat")
        cpustats_values = {}
        # /proc/stat CPU line columns, in order. Not all kernels populate all fields;
        # zip() stops at the shorter of the two so missing trailing fields are silently
        # omitted rather than causing an IndexError.
        cpustats_labels = ["user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal", "guest", "guest_nice"]
        stat_path = "/proc/stat"
        if util.caniread(stat_path) is False:
            logger.error(f"Fatal: Can't open {stat_path} for reading.")
            return False
        with open(stat_path, "r") as reader:
            stat_line = str(reader.readline()).strip()
            while stat_line != "":
                if stat_line.startswith("cpu"):
                    split = stat_line.split()
                    # cpu_name is "cpu" for the aggregate row, "cpuN" for each core.
                    cpu_name = split.pop(0)
                    cpustats_values[cpu_name] = dict(
                        zip(cpustats_labels, map(int, split))
                    )
                    # Softirqs are merged in after the per-CPU section is fully read.
                    cpustats_values[cpu_name]["softirqs"] = {}
                elif stat_line.startswith("intr"):
                    # The "intr" line marks the end of the per-CPU section.
                    # Pull softirq counts from /proc/softirqs now so they can
                    # be attached to the already-parsed per-core dicts.
                    result = self.GetCpuSoftIrqs(cpustats_values)
                    if result is not False:
                        cpustats_values = result
                else:
                    split = stat_line.split()
                    key = split.pop(0)
                    if key in self.INTEGER_STATS:
                        cpustats_values[key] = int(split[0])
                    elif key in self.FLOAT_STATS:
                        cpustats_values[key] = float(split[0])
                    elif key == "softirq":
                        # "softirq" line: total followed by per-type counts.
                        cpustats_values[key] = list(map(int, split))
                    else:
                        cpustats_values[key] = split
                stat_line = str(reader.readline()).strip()

        cpustats_values["_time"] = time.time()

        # Promote aggregate CPU row's tick counters to top-level schema column names
        # so Linux and AIX rows share the same keys in the cpu_stats table.
        # The per-core sub-dicts (cpu0, cpu1, ...) keep their original names.
        agg = cpustats_values.get("cpu", {})
        cpustats_values["user_ticks"]     = agg.get("user")
        cpustats_values["nice_ticks"]     = agg.get("nice")
        cpustats_values["sys_ticks"]      = agg.get("system")
        cpustats_values["idle_ticks"]     = agg.get("idle")
        cpustats_values["iowait_ticks"]   = agg.get("iowait")
        cpustats_values["irq_ticks"]      = agg.get("irq")
        cpustats_values["softirq_ticks"]  = agg.get("softirq")
        cpustats_values["steal_ticks"]    = agg.get("steal")
        cpustats_values["guest_ticks"]    = agg.get("guest")

        ncores = sum(1 for k in cpustats_values if k.startswith("cpu") and k != "cpu")
        logger.debug("GetCpuProcStats: parsed aggregate + %d per-core CPU rows", ncores)
        logger.debug("GetCpuProcStats: user=%s nice=%s sys=%s idle=%s iowait=%s steal=%s",
                     cpustats_values.get("user_ticks"),
                     cpustats_values.get("nice_ticks"),
                     cpustats_values.get("sys_ticks"),
                     cpustats_values.get("idle_ticks"),
                     cpustats_values.get("iowait_ticks"),
                     cpustats_values.get("steal_ticks"))
        logger.debug("GetCpuProcStats: procs_running=%s procs_blocked=%s ctxt=%s btime=%s",
                     cpustats_values.get("procs_running"),
                     cpustats_values.get("procs_blocked"),
                     cpustats_values.get("ctxt"),
                     cpustats_values.get("btime"))
        return cpustats_values

    def UpdateValues(self):
        """Refresh both cpuinfo_values and cpustat_values from /proc."""
        logger.debug("Cpu.UpdateValues: starting")
        self.cpuinfo_values = self.GetCpuinfo()
        self.cpustat_values = self.GetCpuProcStats()
        logger.debug("Cpu.UpdateValues: complete")

    def __init__(self):
        # Populate both attributes immediately on instantiation.
        logger.debug("Cpu: initializing")
        self.UpdateValues()


if __name__ == "__main__":
    import pprint
    import util  # pylint: disable=import-error

    pp = pprint.PrettyPrinter(indent=4)
    mycpu = Cpu()
    pp.pprint(mycpu.cpustat_values)
    pp.pprint(mycpu.cpuinfo_values)
else:
    from . import util
