# AIX CPU gatherer. Uses libperfstat via ctypes to call perfstat_cpu_total().
#
# Exposes an AixCpu class. After instantiation:
#   cpustat_values — dict of system-wide CPU counters from perfstat_cpu_total_t,
#                    including usage ticks, load averages, syscall counts, and
#                    LPAR/POWER-specific PURR/SPURR donated/stolen cycle counters.
#                    Includes a '_time' key.
#
# Call UpdateValues() to refresh. The class interface mirrors Linux Cpu so that
# __main__.py can treat them interchangeably (noting AIX has no cpuinfo_values).
import sys
sys.dont_write_bytecode = True
import ctypes
import time
import logging

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())

# IDENTIFIER_LENGTH matches IDENTIFIER_LENGTH in libperfstat.h (64 bytes).
IDENTIFIER_LENGTH = 64


class perfstat_id_t(ctypes.Structure):
    """perfstat_id_t — used to identify the starting object for enumeration calls.

    Pass with name="" (FIRST_CPU / FIRST_DISK etc.) to start from the beginning,
    or with a specific name to start enumeration from that object.
    Pass NULL (None) to query-count calls that don't enumerate.
    """
    _fields_ = [
        ("name", ctypes.c_char * IDENTIFIER_LENGTH),
    ]


class perfstat_cpu_total_t(ctypes.Structure):
    """Matches perfstat_cpu_total_t_72 from libperfstat.h (AIX 7.2/7.3).

    Struct layout sourced from OpenJDK's libperfstat_aix.hpp and IBM AIX 7.3
    documentation. sizeof == 696, confirmed on AIX 7.3 POWER8 with gcc -m64.

    Padding fields (_padN) are inserted at natural alignment boundaries where
    a 4-byte int precedes an 8-byte u_longlong_t. They are skipped when
    converting to a dict.

    PURR/SPURR fields are POWER-specific cycle counters used for capacity
    planning in shared LPAR environments (donated = given to other LPARs,
    stolen = taken from this LPAR by the hypervisor).
    """
    _fields_ = [
        ("ncpus",              ctypes.c_int),
        ("ncpus_cfg",          ctypes.c_int),
        ("description",        ctypes.c_char * IDENTIFIER_LENGTH),
        ("processorHZ",        ctypes.c_ulonglong),
        ("user",               ctypes.c_ulonglong),
        ("sys",                ctypes.c_ulonglong),
        ("idle",               ctypes.c_ulonglong),
        ("wait",               ctypes.c_ulonglong),
        ("pswitch",            ctypes.c_ulonglong),
        ("syscall",            ctypes.c_ulonglong),
        ("sysread",            ctypes.c_ulonglong),
        ("syswrite",           ctypes.c_ulonglong),
        ("sysfork",            ctypes.c_ulonglong),
        ("sysexec",            ctypes.c_ulonglong),
        ("readch",             ctypes.c_ulonglong),
        ("writech",            ctypes.c_ulonglong),
        ("devintrs",           ctypes.c_ulonglong),
        ("softintrs",          ctypes.c_ulonglong),
        ("lbolt",              ctypes.c_longlong),   # time_t on 64-bit AIX
        ("loadavg",            ctypes.c_ulonglong * 3),
        ("runque",             ctypes.c_ulonglong),
        ("swpque",             ctypes.c_ulonglong),
        ("bread",              ctypes.c_ulonglong),
        ("bwrite",             ctypes.c_ulonglong),
        ("lread",              ctypes.c_ulonglong),
        ("lwrite",             ctypes.c_ulonglong),
        ("phread",             ctypes.c_ulonglong),
        ("phwrite",            ctypes.c_ulonglong),
        ("runocc",             ctypes.c_ulonglong),
        ("swpocc",             ctypes.c_ulonglong),
        ("iget",               ctypes.c_ulonglong),
        ("namei",              ctypes.c_ulonglong),
        ("dirblk",             ctypes.c_ulonglong),
        ("msg",                ctypes.c_ulonglong),
        ("sema",               ctypes.c_ulonglong),
        ("rcvint",             ctypes.c_ulonglong),
        ("xmtint",             ctypes.c_ulonglong),
        ("mdmint",             ctypes.c_ulonglong),
        ("tty_rawinch",        ctypes.c_ulonglong),
        ("tty_caninch",        ctypes.c_ulonglong),
        ("tty_rawoutch",       ctypes.c_ulonglong),
        ("ksched",             ctypes.c_ulonglong),
        ("koverf",             ctypes.c_ulonglong),
        ("kexit",              ctypes.c_ulonglong),
        ("rbread",             ctypes.c_ulonglong),
        ("rcread",             ctypes.c_ulonglong),
        ("rbwrt",              ctypes.c_ulonglong),
        ("rcwrt",              ctypes.c_ulonglong),
        ("traps",              ctypes.c_ulonglong),
        ("ncpus_high",         ctypes.c_int),
        # 4-byte int followed by 8-byte u_longlong_t — compiler inserts 4 bytes.
        ("_pad0",              ctypes.c_int),
        ("puser",              ctypes.c_ulonglong),
        ("psys",               ctypes.c_ulonglong),
        ("pidle",              ctypes.c_ulonglong),
        ("pwait",              ctypes.c_ulonglong),
        ("decrintrs",          ctypes.c_ulonglong),
        ("mpcrintrs",          ctypes.c_ulonglong),
        ("mpcsintrs",          ctypes.c_ulonglong),
        ("phantintrs",         ctypes.c_ulonglong),
        ("idle_donated_purr",  ctypes.c_ulonglong),
        ("idle_donated_spurr", ctypes.c_ulonglong),
        ("busy_donated_purr",  ctypes.c_ulonglong),
        ("busy_donated_spurr", ctypes.c_ulonglong),
        ("idle_stolen_purr",   ctypes.c_ulonglong),
        ("idle_stolen_spurr",  ctypes.c_ulonglong),
        ("busy_stolen_purr",   ctypes.c_ulonglong),
        ("busy_stolen_spurr",  ctypes.c_ulonglong),
        ("iowait",             ctypes.c_short),
        ("physio",             ctypes.c_short),
        # Two shorts (4 bytes total) followed by 8-byte longlong_t.
        ("_pad1",              ctypes.c_int),
        ("twait",              ctypes.c_longlong),
        ("hpi",                ctypes.c_ulonglong),
        ("hpit",               ctypes.c_ulonglong),
        ("puser_spurr",        ctypes.c_ulonglong),
        ("psys_spurr",         ctypes.c_ulonglong),
        ("pidle_spurr",        ctypes.c_ulonglong),
        ("pwait_spurr",        ctypes.c_ulonglong),
        ("spurrflag",          ctypes.c_int),
        # 4-byte int before 8-byte u_longlong_t.
        ("_pad2",              ctypes.c_int),
        ("version",            ctypes.c_ulonglong),
        ("tb_last",            ctypes.c_ulonglong),
        ("purr_coalescing",    ctypes.c_ulonglong),
        ("spurr_coalescing",   ctypes.c_ulonglong),
    ]


def _load_libperfstat():
    """Load libperfstat from its AIX shared archive member.

    On AIX, shared libraries are bundled inside .a archive files. The member
    shr_64.o is the 64-bit shared object. This must be loaded before any
    perfstat_* function can be called.
    """
    return ctypes.CDLL("libperfstat.a(shr_64.o)")


def get_cpu_total():
    """Call perfstat_cpu_total() and return the result as a plain dict.

    Calls with count=1 to fill a single perfstat_cpu_total_t buffer.
    Skips padding fields (_padN) when building the result dict.
    The 'loadavg' array is unpacked to a plain Python list and then split
    into loadavg_1/5/15 keys so they match the schema column names.

    The raw loadavg values from perfstat are fixed-point integers scaled by
    FSCALE (2^16 = 65536 on AIX). Divide by 65536.0 for the familiar float.

    Tick counters (user, sys, idle, wait) are renamed to user_ticks/sys_ticks/
    idle_ticks/iowait_ticks to match the cross-platform cpu_stats schema.

    Returns False and logs an error if the call does not return exactly 1.
    """
    logger.debug("get_cpu_total: calling perfstat_cpu_total")
    lib = _load_libperfstat()

    lib.perfstat_cpu_total.argtypes = [
        ctypes.POINTER(perfstat_id_t),
        ctypes.POINTER(perfstat_cpu_total_t),
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.perfstat_cpu_total.restype = ctypes.c_int

    buf = perfstat_cpu_total_t()
    ret = lib.perfstat_cpu_total(
        None,
        ctypes.byref(buf),
        ctypes.sizeof(buf),
        1,
    )
    if ret != 1:
        logger.error(f"perfstat_cpu_total returned {ret}, expected 1")
        return False

    raw = {}
    for field_name, _ in perfstat_cpu_total_t._fields_:
        if field_name.startswith("_pad"):
            continue
        val = getattr(buf, field_name)
        if field_name == "description":
            raw[field_name] = val.decode("ascii", errors="replace").rstrip("\x00")
        elif field_name == "loadavg":
            raw[field_name] = [val[0], val[1], val[2]]
        else:
            raw[field_name] = val

    # Normalize to schema column names so AIX and Linux rows share the same keys.
    # AIX-only fields keep their names; cross-platform tick counters are renamed.
    la = raw.pop("loadavg")
    raw["user_ticks"]    = raw.pop("user")
    raw["sys_ticks"]     = raw.pop("sys")
    raw["idle_ticks"]    = raw.pop("idle")
    raw["iowait_ticks"]  = raw.pop("wait")
    raw["processor_hz"]  = raw.pop("processorHZ")
    raw["loadavg_1"]     = la[0]
    raw["loadavg_5"]     = la[1]
    raw["loadavg_15"]    = la[2]
    result = raw

    result["_time"] = time.time()

    logger.debug("get_cpu_total: description=%r ncpus=%d processor_hz=%d",
                 result.get("description"), result.get("ncpus"), result.get("processor_hz"))
    logger.debug("get_cpu_total: user_ticks=%d sys_ticks=%d idle_ticks=%d iowait_ticks=%d",
                 result.get("user_ticks", 0), result.get("sys_ticks", 0),
                 result.get("idle_ticks", 0), result.get("iowait_ticks", 0))
    # loadavg values from perfstat are fixed-point: divide by 2^SBITS (65536) for
    # a human-readable load average. Log both raw and scaled values.
    SBITS = 16
    logger.debug("get_cpu_total: loadavg_1=%.2f loadavg_5=%.2f loadavg_15=%.2f "
                 "(raw: %d %d %d)",
                 result.get("loadavg_1", 0) / (1 << SBITS),
                 result.get("loadavg_5", 0) / (1 << SBITS),
                 result.get("loadavg_15", 0) / (1 << SBITS),
                 result.get("loadavg_1", 0),
                 result.get("loadavg_5", 0),
                 result.get("loadavg_15", 0))
    logger.debug("get_cpu_total: syscall=%d pswitch=%d sysfork=%d sysexec=%d",
                 result.get("syscall", 0), result.get("pswitch", 0),
                 result.get("sysfork", 0), result.get("sysexec", 0))
    total_donated = (result.get("idle_donated_purr", 0) + result.get("busy_donated_purr", 0))
    total_stolen  = (result.get("idle_stolen_purr",  0) + result.get("busy_stolen_purr",  0))
    logger.debug("get_cpu_total: PURR donated=%d stolen=%d (idle_donated=%d busy_donated=%d "
                 "idle_stolen=%d busy_stolen=%d)",
                 total_donated, total_stolen,
                 result.get("idle_donated_purr", 0), result.get("busy_donated_purr", 0),
                 result.get("idle_stolen_purr",  0), result.get("busy_stolen_purr",  0))
    return result


class AixCpu:
    """AIX CPU gatherer. Wraps get_cpu_total() to match the Linux Cpu interface.

    Exposes:
        cpustat_values — dict from perfstat_cpu_total_t, including '_time'.

    Note: AIX has no cpuinfo equivalent accessible without parsing lsattr/lsdev
    output. There is no cpuinfo_values attribute on this class.
    """

    def UpdateValues(self):
        """Refresh cpustat_values by calling perfstat_cpu_total() again."""
        logger.debug("AixCpu.UpdateValues: starting")
        self.cpustat_values = get_cpu_total()
        logger.debug("AixCpu.UpdateValues: complete (ok=%s)", self.cpustat_values is not False)

    def __init__(self):
        logger.debug("AixCpu: initializing")
        self.UpdateValues()


if __name__ == "__main__":
    import pprint

    pp = pprint.PrettyPrinter(indent=4)
    mycpu = AixCpu()
    pp.pprint(mycpu.cpustat_values)
