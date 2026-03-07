# Linux CPU gatherer. Reads /proc/cpuinfo, /proc/stat, and /proc/softirqs.
#
# Exposes a Cpu class with two attributes after instantiation:
#   cpuinfo_values  — hardware description for cpu0 (model, MHz, flags, etc.)
#   cpustat_values  — per-core usage counters plus system-wide stats and softirqs
#
# Call update_values() to refresh.
import sys
sys.dont_write_bytecode = True
import time
import logging

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())


class Cpu:
    """Linux CPU gatherer. Reads /proc/cpuinfo, /proc/stat, and /proc/softirqs.

    After instantiation (which calls update_values() immediately):
        cpuinfo_values  — hardware info dict for cpu0 (model, MHz, flags …)
        cpustat_values  — per-core tick counters, softirq counts, and
                          system-wide stats (ctxt, btime, processes …)

    Call update_values() to refresh.
    The class-level lists (INTEGER_STATS, FLOAT_STATS, LIST_STATS) control
    how raw string values are coerced during parsing.
    """

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

    def get_cpuinfo(self, _time=None):
        """Parse /proc/cpuinfo and return a dict of hardware info for cpu0.

        Reads only up to the first blank line, which terminates the cpu0 stanza.
        Values are coerced to int, float, or list according to INTEGER_STATS,
        FLOAT_STATS, and LIST_STATS. Unknown fields are kept as strings.
        Returns False if /proc/cpuinfo is unreadable.
        """
        logger.debug("get_cpuinfo: reading /proc/cpuinfo")
        cpuinfo_values = {}
        cpuinfo_path = "/proc/cpuinfo"
        if not util.caniread(cpuinfo_path):
            logger.warning("linux_cpu: can't read %s", cpuinfo_path)
            # Non-fatal: other gatherers may still succeed.
            return False
        try:
            with open(cpuinfo_path, "r") as reader:
                cpuinfo_line = reader.readline().strip()
                # Stop at the first blank line — that ends the cpu0 stanza.
                while cpuinfo_line != "":
                    # Lines look like:  model name      : AMD EPYC 7571
                    # Split on the first colon only; the value may contain colons.
                    split = cpuinfo_line.split(":", 1)
                    if len(split) < 2:
                        # Line without a colon — skip (shouldn't happen in practice).
                        cpuinfo_line = reader.readline().strip()
                        continue
                    split[0] = split[0].strip()
                    split[1] = split[1].strip()
                    cpuinfo_values[split[0]] = util.coerce_field(
                        split[1], split[0],
                        self.INTEGER_STATS, self.FLOAT_STATS, self.LIST_STATS
                    )
                    cpuinfo_line = reader.readline().strip()
        except (IOError, OSError, ValueError, TypeError) as e:
            logger.error("linux_cpu: error reading/parsing /proc/cpuinfo: %s", e)
            return False
        nfields = len(cpuinfo_values)
        logger.debug("get_cpuinfo: parsed %d fields for cpu0", nfields)
        logger.debug("get_cpuinfo: model=%r MHz=%s bogomips=%s flags=%d bugs=%d",
                     cpuinfo_values.get("model name", "unknown"),
                     cpuinfo_values.get("cpu MHz", "?"),
                     cpuinfo_values.get("bogomips", "?"),
                     len(cpuinfo_values.get("flags", [])),
                     len(cpuinfo_values.get("bugs", [])))
        return cpuinfo_values

    def get_cpu_soft_irqs(self, cpustats_values):
        """Parse /proc/softirqs and merge per-CPU softirq counters into cpustats_values.

        /proc/softirqs has a header row naming each CPU column, followed by one
        row per IRQ type with a count per CPU.  The header is parsed first to
        guarantee correct column-to-CPU mapping regardless of CPU ordering.

        The softirq counts are stored under cpustats_values[cpuN]["softirqs"][irqname].
        Only CPUs that already exist in cpustats_values (populated by get_cpu_proc_stats)
        are updated — the aggregate "cpu" key is skipped.
        Returns the updated cpustats_values dict, or False if the file is unreadable.
        """
        logger.debug("get_cpu_soft_irqs: reading /proc/softirqs")
        softirq_path = "/proc/softirqs"
        if not util.caniread(softirq_path):
            logger.error("linux_cpu: can't read %s", softirq_path)
            return False
        nirq_types = 0
        try:
            with open(softirq_path, "r") as reader:
                # First line is the header: "    CPU0  CPU1  CPU2 ..."
                # Parse it to get column→CPU name mapping before reading data rows.
                header_line = reader.readline().strip()
                cpu_columns = [c.strip() for c in header_line.split() if c.strip()]
                logger.debug("get_cpu_soft_irqs: header lists %d CPU columns", len(cpu_columns))
                softirq_line = reader.readline().strip()
                while softirq_line != "":
                    # Lines look like:  NET_RX:    12345    67890 ...
                    # Strip the trailing colon from the IRQ name before splitting.
                    irq = softirq_line.replace(":", "").split()
                    irqname = irq.pop(0)
                    for i, cpu_name in enumerate(cpu_columns):
                        cpu_key = cpu_name.lower()
                        if cpu_key in cpustats_values and cpu_key != "cpu":
                            try:
                                cpustats_values[cpu_key]["softirqs"][irqname] = int(irq[i])
                            except (IndexError, ValueError, TypeError):
                                logger.warning("get_cpu_soft_irqs: could not parse softirq value for %s/%s", cpu_name, irqname)
                    nirq_types += 1
                    softirq_line = reader.readline().strip()
        except (IOError, OSError) as e:
            logger.error("linux_cpu: error reading /proc/softirqs: %s", e)
            return False
        ncpus = sum(1 for k in cpustats_values if k.startswith("cpu") and k != "cpu")
        logger.debug("get_cpu_soft_irqs: merged %d softirq types across %d CPUs",
                     nirq_types, ncpus)
        return cpustats_values

    def get_cpu_proc_stats(self, _time=None):
        """Parse /proc/stat and return a dict of per-core counters and system-wide stats.

        Each cpu/cpuN line becomes a sub-dict keyed by the CPU name, with fields
        named by cpustats_labels (user_ticks, nice_ticks, sys_ticks, idle_ticks, ...).
        A "softirqs" sub-dict is also populated by calling get_cpu_soft_irqs once the
        per-CPU section of /proc/stat is exhausted (triggered by the "intr" line).

        Non-CPU lines (ctxt, btime, processes, procs_running, procs_blocked)
        are stored at the top level, coerced to int or float where known.

        After parsing, the aggregate "cpu" row's tick counters are also promoted
        to top-level schema keys (user_ticks, sys_ticks, etc.) so Linux and AIX
        samples share the same column names in the cpu_stats table.

        Returns False if /proc/stat is unreadable.
        """
        logger.debug("get_cpu_proc_stats: reading /proc/stat")
        cpustats_values = {}
        # /proc/stat CPU line columns, in order. Not all kernels populate all fields;
        # zip() stops at the shorter of the two so missing trailing fields are silently
        # omitted rather than causing an IndexError.
        # Field names use _ticks suffix for consistency with AIX schema.
        cpustats_labels = [
            "user_ticks", "nice_ticks", "sys_ticks", "idle_ticks",
            "iowait_ticks", "irq_ticks", "softirq_ticks", "steal_ticks",
            "guest_ticks", "guest_nice_ticks",
        ]
        stat_path = "/proc/stat"
        if not util.caniread(stat_path):
            logger.error("linux_cpu: can't read %s", stat_path)
            return False
        try:
            with open(stat_path, "r") as reader:
                stat_line = reader.readline().strip()
                while stat_line != "":
                    try:
                        if stat_line.startswith("cpu"):
                            split = stat_line.split()
                            # cpu_name is "cpu" for the aggregate row, "cpuN" for each core.
                            cpu_name = split.pop(0)
                            cpustats_values[cpu_name] = util.dict_from_fields(split, cpustats_labels)
                            # Softirqs are merged in after the per-CPU section is fully read.
                            cpustats_values[cpu_name]["softirqs"] = {}
                        elif stat_line.startswith("intr"):
                            # The "intr" line marks the end of the per-CPU section.
                            # Pull softirq counts from /proc/softirqs now so they can
                            # be attached to the already-parsed per-core dicts.
                            result = self.get_cpu_soft_irqs(cpustats_values)
                            if result is not False:
                                cpustats_values = result
                        else:
                            split = stat_line.split()
                            key = split.pop(0)
                            if key == "softirq":
                                # "softirq" line: total followed by per-type counts.
                                cpustats_values[key] = list(map(int, split))
                            else:
                                cpustats_values[key] = util.coerce_field(
                                    split[0], key,
                                    self.INTEGER_STATS, self.FLOAT_STATS, self.LIST_STATS
                                )
                    except (ValueError, IndexError, TypeError) as e:
                        logger.warning("get_cpu_proc_stats: error parsing line %r: %s", stat_line, e)
                    stat_line = reader.readline().strip()
        except (IOError, OSError) as e:
            logger.error("linux_cpu: error reading /proc/stat: %s", e)
            return False

        # Promote aggregate CPU row's tick counters to top-level schema column names
        # so Linux and AIX rows share the same keys in the cpu_stats table.
        # The per-core sub-dicts (cpu0, cpu1, ...) already use the _ticks suffix.
        agg = cpustats_values.get("cpu", {})
        cpustats_values["user_ticks"] = agg.get("user_ticks")
        cpustats_values["nice_ticks"] = agg.get("nice_ticks")
        cpustats_values["sys_ticks"] = agg.get("sys_ticks")
        cpustats_values["idle_ticks"] = agg.get("idle_ticks")
        cpustats_values["iowait_ticks"] = agg.get("iowait_ticks")
        cpustats_values["irq_ticks"] = agg.get("irq_ticks")
        cpustats_values["softirq_ticks"] = agg.get("softirq_ticks")
        cpustats_values["steal_ticks"] = agg.get("steal_ticks")
        cpustats_values["guest_ticks"] = agg.get("guest_ticks")
        cpustats_values["guest_nice_ticks"] = agg.get("guest_nice_ticks")
        # Remove the now-redundant "cpu" aggregate dict since its fields are promoted.
        cpustats_values.pop("cpu", None)

        ncores = sum(1 for k in cpustats_values if k.startswith("cpu"))
        logger.debug("get_cpu_proc_stats: parsed aggregate + %d per-core CPU rows", ncores)
        logger.debug("get_cpu_proc_stats: user=%s nice=%s sys=%s idle=%s iowait=%s steal=%s",
                     cpustats_values.get("user_ticks"),
                     cpustats_values.get("nice_ticks"),
                     cpustats_values.get("sys_ticks"),
                     cpustats_values.get("idle_ticks"),
                     cpustats_values.get("iowait_ticks"),
                     cpustats_values.get("steal_ticks"))
        logger.debug("get_cpu_proc_stats: procs_running=%s procs_blocked=%s ctxt=%s btime=%s",
                     cpustats_values.get("procs_running"),
                     cpustats_values.get("procs_blocked"),
                     cpustats_values.get("ctxt"),
                     cpustats_values.get("btime"))
        return cpustats_values

    def get_load_avg(self, _time=None):
        """Read /proc/loadavg and return load averages as a dict.

        /proc/loadavg format: 1min 5min 15min runnable/total last_pid
        Returns a dict with loadavg_1, loadavg_5, loadavg_15 as floats,
        or False if /proc/loadavg is unreadable or malformed.
        """
        logger.debug("get_load_avg: reading /proc/loadavg")
        loadavg_path = "/proc/loadavg"
        if not util.caniread(loadavg_path):
            logger.warning("linux_cpu: can't read %s", loadavg_path)
            return False
        try:
            with open(loadavg_path, "r") as f:
                parts = f.readline().split()
            if len(parts) < 3:
                logger.warning("get_load_avg: unexpected format in /proc/loadavg")
                return False
            return {
                "loadavg_1":  float(parts[0]),
                "loadavg_5":  float(parts[1]),
                "loadavg_15": float(parts[2]),
            }
        except (IOError, OSError, ValueError, TypeError) as e:
            logger.error("linux_cpu: error reading/parsing /proc/loadavg: %s", e)
            return False

    def update_values(self):
        """Refresh both cpuinfo_values and cpustat_values from /proc."""
        logger.debug("Cpu.update_values: starting")
        ts = getattr(self, '_ts', None)
        self.cpuinfo_values = self.get_cpuinfo(ts)
        self.cpustat_values = self.get_cpu_proc_stats(ts)
        loadavg = self.get_load_avg(ts)
        if loadavg and self.cpustat_values is not False:
            self.cpustat_values.update(loadavg)
        logger.debug("Cpu.update_values: complete")

    def __init__(self, _time=None):
        # Populate both attributes immediately on instantiation.
        self._ts = _time if _time is not None else time.time()
        logger.debug("Cpu: initializing")
        self.update_values()


if __name__ == "__main__":
    import pprint
    import util  # pylint: disable=import-error

    pp = pprint.PrettyPrinter(indent=4)
    mycpu = Cpu()
    pp.pprint(mycpu.cpustat_values)
    pp.pprint(mycpu.cpuinfo_values)
else:
    from . import util
