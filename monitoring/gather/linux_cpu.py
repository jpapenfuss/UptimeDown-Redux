# Linux CPU gatherer. Reads /proc/cpuinfo, /proc/stat, and /proc/softirqs.
#
# Exposes a Cpu class with two attributes after instantiation:
#   cpuinfo_values  — hardware description for cpu0 (model, MHz, flags, etc.)
#   cpustat_values  — per-core usage counters plus system-wide stats and softirqs
#
# Both dicts include a '_time' key (Unix timestamp) recording when the data
# was captured.  Call UpdateValues() to refresh.
import time
import logging

logger = logging.getLogger("monitoring")


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
    LIST_STATS = ["flags", "bugs", "softirq"]

    def GetCpuinfo(self):
        """Parse /proc/cpuinfo and return a dict of hardware info for cpu0.

        Reads only up to the first blank line, which terminates the cpu0 stanza.
        Values are coerced to int, float, or list according to INTEGER_STATS,
        FLOAT_STATS, and LIST_STATS. Unknown fields are kept as strings.
        Returns False if /proc/cpuinfo is unreadable.
        """
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
                split = cpuinfo_line.split(":", 1)
                split[0] = split[0].strip()
                split[1] = split[1].strip()
                if split[0] in self.INTEGER_STATS:
                    cpuinfo_values[split[0]] = int(split[1])
                elif split[0] in self.FLOAT_STATS:
                    cpuinfo_values[split[0]] = float(split[1])
                elif split[0] in self.LIST_STATS:
                    cpuinfo_values[split[0]] = split[1].split()
                else:
                    cpuinfo_values[split[0]] = split[1]
                cpuinfo_line = str(reader.readline()).strip()
        cpuinfo_values["_time"] = time.time()
        return cpuinfo_values

    def GetCpuSoftIrqs(self, cpustats_values):
        """Parse /proc/softirqs and merge per-CPU softirq counters into cpustats_values.

        /proc/softirqs has a header row naming each CPU column, followed by one
        row per IRQ type with a count per CPU.  The header is parsed first to
        guarantee correct column-to-CPU mapping regardless of CPU ordering.

        The softirq counts are stored under cpustats_values[cpuN]["softirqs"][irqname].
        Returns the updated cpustats_values dict, or False if the file is unreadable.
        """
        logger.debug("Entering GetCpuSoftIrqs")
        softirq_path = "/proc/softirqs"
        if util.caniread(softirq_path) is False:
            logger.error(f"Fatal: Can't open {softirq_path} for reading.")
            return False
        with open(softirq_path, "r") as reader:
            # First line is the header: "    CPU0  CPU1  CPU2 ..."
            header_line = str(reader.readline()).strip()
            cpu_columns = [c.strip() for c in header_line.split() if c.strip()]
            softirq_line = str(reader.readline()).strip()
            while softirq_line != "":
                # Lines look like:  NET_RX:    12345    67890 ...
                irq = softirq_line.replace(":", "").split()
                irqname = irq.pop(0)
                for i, cpu_name in enumerate(cpu_columns):
                    if cpu_name in cpustats_values and cpu_name != "cpu":
                        cpustats_values[cpu_name]["softirqs"][irqname] = int(irq[i])
                softirq_line = str(reader.readline()).strip()
        return cpustats_values

    def GetCpuProcStats(self):
        """Parse /proc/stat and return a dict of per-core counters and system-wide stats.

        Each cpu/cpuN line becomes a sub-dict keyed by the CPU name, with fields
        named by cpustats_labels (user, nice, system, idle, ...).  A "softirqs"
        sub-dict is also populated by calling GetCpuSoftIrqs once the per-CPU
        section of /proc/stat is exhausted (triggered by the "intr" line).

        Non-CPU lines (ctxt, btime, processes, etc.) are stored at the top level,
        coerced to int or float where known.
        Returns False if /proc/stat is unreadable.
        """
        cpustats_values = {}
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
                    cpustats_values[cpu_name]["softirqs"] = {}
                elif stat_line.startswith("intr"):
                    # The "intr" line marks the end of the per-CPU section.
                    # Pull softirq counts from /proc/softirqs now so they can
                    # be attached to the already-parsed CPU entries.
                    cpustats_values = self.GetCpuSoftIrqs(cpustats_values)
                else:
                    split = stat_line.split()
                    key = split.pop(0)
                    if key in self.INTEGER_STATS:
                        cpustats_values[key] = int(split[0])
                    elif key in self.FLOAT_STATS:
                        cpustats_values[key] = float(split[0])
                    elif key == "softirq":
                        cpustats_values[key] = list(map(int, split))
                    else:
                        cpustats_values[key] = split
                stat_line = str(reader.readline()).strip()

        cpustats_values["_time"] = time.time()

        # Normalize aggregate CPU row to schema column names so Linux and AIX
        # rows share the same keys in the cpu_stats table.
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

        return cpustats_values

    def UpdateValues(self):
        """Refresh both cpuinfo_values and cpustat_values from /proc."""
        self.cpuinfo_values = self.GetCpuinfo()
        self.cpustat_values = self.GetCpuProcStats()

    def __init__(self):
        # Populate both attributes immediately on instantiation.
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
