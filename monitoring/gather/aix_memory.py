# AIX memory gatherer. Uses libperfstat via ctypes to call
# perfstat_memory_total().
#
# Exposes an AixMemory class. After instantiation:
#   stats — dict with a 'memory' sub-dict, mirroring the shape of the Linux
#            Memory class so __main__.py can treat them interchangeably.
#            The 'slabs' key is always None (no AIX equivalent).
#
# Output keys in stats['memory'] are normalized to match the schema:
#   Shared with Linux: mem_total, mem_free, cached, swap_total, swap_free
#   AIX-only: real_pinned, real_inuse, real_system, real_user, real_process,
#             virt_total, virt_active, pgsp_rsvd,
#             pgbad, pgexct, pgins, pgouts, pgspins, pgspouts,
#             scans, cycles, pgsteals
#   All byte values are in bytes (pages converted by multiplying by PAGE_SIZE).
#   All counter values are cumulative since boot.
import sys
sys.dont_write_bytecode = True
import ctypes
import time
import logging

try:
    from . import aix_util
except ImportError:
    import aix_util  # type: ignore

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())

# AIX uses 4 KB pages throughout libperfstat.
PAGE_SIZE = 4096


class perfstat_memory_total_t(ctypes.Structure):
    """perfstat_memory_total_t — system-wide memory statistics.

    All 22 fields are u_longlong_t (unsigned 64-bit). No padding is needed
    because every field is naturally 8-byte aligned.
    sizeof == 176, confirmed against the OpenJDK libperfstat_aix.hpp reference
    (same source used to verify perfstat_cpu_total_t).

    Page-valued fields (virt_total, real_total, real_free, real_pinned,
    real_inuse, numperm, pgsp_total, pgsp_free, pgsp_rsvd, real_system,
    real_user, real_process, virt_active) are in 4 KB pages.
    Counter fields (pgbad, pgexct, pgins, pgouts, pgspins, pgspouts, scans,
    cycles, pgsteals) are cumulative event counts since boot.
    """
    _fields_ = [
        ("virt_total",    ctypes.c_ulonglong),  # total virtual memory (pages)
        ("real_total",    ctypes.c_ulonglong),  # total RAM (pages)
        ("real_free",     ctypes.c_ulonglong),  # free RAM (pages)
        ("real_pinned",   ctypes.c_ulonglong),  # pinned RAM, cannot be paged out (pages)
        ("real_inuse",    ctypes.c_ulonglong),  # RAM currently in use (pages)
        ("pgbad",         ctypes.c_ulonglong),  # bad pages detected
        ("pgexct",        ctypes.c_ulonglong),  # page faults
        ("pgins",         ctypes.c_ulonglong),  # pages paged in from disk
        ("pgouts",        ctypes.c_ulonglong),  # pages paged out to disk
        ("pgspins",       ctypes.c_ulonglong),  # page ins from paging space
        ("pgspouts",      ctypes.c_ulonglong),  # page outs to paging space
        ("scans",         ctypes.c_ulonglong),  # page scans by clock algorithm
        ("cycles",        ctypes.c_ulonglong),  # page replacement cycles
        ("pgsteals",      ctypes.c_ulonglong),  # page steals (frames reclaimed)
        ("numperm",       ctypes.c_ulonglong),  # frames used for file cache (pages)
        ("pgsp_total",    ctypes.c_ulonglong),  # total paging space (pages)
        ("pgsp_free",     ctypes.c_ulonglong),  # free paging space (pages)
        ("pgsp_rsvd",     ctypes.c_ulonglong),  # reserved paging space (pages)
        ("real_system",   ctypes.c_ulonglong),  # RAM used by system segments (pages)
        ("real_user",     ctypes.c_ulonglong),  # RAM used by non-system segments (pages)
        ("real_process",  ctypes.c_ulonglong),  # RAM used by process segments (pages)
        ("virt_active",   ctypes.c_ulonglong),  # active virtual pages (pages)
    ]


def get_memory_total(_time=None):
    """Call perfstat_memory_total() and return a normalized memory stats dict.

    Page-valued fields are converted to bytes (pages * PAGE_SIZE = pages * 4096).
    Counter fields (pgexct, pgins, pgouts, etc.) are stored as-is — they are
    cumulative since boot and rates should be computed at query time.

    Normalized keys shared with the Linux memory gatherer:
        mem_total    — total RAM in bytes        (real_total * PAGE_SIZE)
        mem_free     — free RAM in bytes         (real_free  * PAGE_SIZE)
        cached       — file cache in bytes       (numperm    * PAGE_SIZE)
        swap_total   — total paging space bytes  (pgsp_total * PAGE_SIZE)
        swap_free    — free paging space bytes   (pgsp_free  * PAGE_SIZE)

    AIX-only page fields (also converted to bytes):
        real_pinned  — RAM locked in memory (cannot be paged out)
        real_inuse   — RAM currently in use
        real_system  — RAM used by kernel segments
        real_user    — RAM used by user segments
        real_process — RAM used by process segments
        virt_total   — total virtual address space
        virt_active  — currently active virtual pages
        pgsp_rsvd    — reserved (but not yet used) paging space

    Returns False and logs an error if the perfstat call fails.
    """
    logger.debug("get_memory_total: calling perfstat_memory_total")
    try:
        lib = aix_util.load_libperfstat()
    except (OSError, AttributeError, ctypes.ArgumentError) as e:
        logger.error("aix_memory: could not load libperfstat: %s", e)
        return False

    try:
        lib.perfstat_memory_total.argtypes = [
            ctypes.c_void_p,                             # name (NULL for total)
            ctypes.POINTER(perfstat_memory_total_t),
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.perfstat_memory_total.restype = ctypes.c_int

        buf = perfstat_memory_total_t()
        ret = lib.perfstat_memory_total(None, ctypes.byref(buf), ctypes.sizeof(buf), 1)
        if ret != 1:
            logger.error("aix_memory: perfstat_memory_total returned %d, expected 1", ret)
            return False
    except (OSError, AttributeError, ctypes.ArgumentError) as e:
        logger.error("aix_memory: perfstat_memory_total call failed: %s", e)
        return False

    p = PAGE_SIZE
    result = {
        # --- Normalized keys (shared with Linux) ---
        "mem_total": buf.real_total * p,
        "mem_free": buf.real_free * p,
        "cached": buf.numperm * p,  # file cache; matches Linux 'Cached' → 'cached'
        "swap_total": buf.pgsp_total * p,
        "swap_free": buf.pgsp_free * p,

        # --- AIX-only page-valued fields (stored as bytes) ---
        "virt_total": buf.virt_total * p,
        "virt_active": buf.virt_active * p,
        "real_pinned": buf.real_pinned * p,
        "real_inuse": buf.real_inuse * p,
        "real_system": buf.real_system * p,
        "real_user": buf.real_user * p,
        "real_process": buf.real_process * p,
        "pgsp_rsvd": buf.pgsp_rsvd * p,

        # --- AIX-only counters (cumulative since boot) ---
        "pgbad": buf.pgbad,
        "pgexct": buf.pgexct,
        "pgins": buf.pgins,
        "pgouts": buf.pgouts,
        "pgspins": buf.pgspins,
        "pgspouts": buf.pgspouts,
        "scans": buf.scans,
        "cycles": buf.cycles,
        "pgsteals": buf.pgsteals,
    }

    gb = 1024 ** 3
    logger.debug("get_memory_total: mem_total=%.2f GB mem_free=%.2f GB cached=%.2f GB",
                 result["mem_total"] / gb, result["mem_free"] / gb, result["cached"] / gb)
    logger.debug("get_memory_total: real_inuse=%.2f GB real_pinned=%.2f GB virt_total=%.2f GB",
                 result["real_inuse"] / gb, result["real_pinned"] / gb, result["virt_total"] / gb)
    logger.debug("get_memory_total: swap_total=%.2f GB swap_free=%.2f GB pgsp_rsvd=%.2f GB",
                 result["swap_total"] / gb, result["swap_free"] / gb, result["pgsp_rsvd"] / gb)
    logger.debug("get_memory_total: pgexct=%d pgins=%d pgouts=%d pgspins=%d pgspouts=%d pgsteals=%d",
                 result["pgexct"], result["pgins"], result["pgouts"],
                 result["pgspins"], result["pgspouts"], result["pgsteals"])
    return result


class AixMemory:
    """AIX memory gatherer. Mirrors the Linux Memory class interface.

    Exposes:
        stats["memory"] — normalized memory stats dict from
                          perfstat_memory_total_t, with page values converted
                          to bytes and keys shared with Linux where applicable.
        stats["slabs"]  — always False (no AIX equivalent of /proc/slabinfo).
    """

    def update_values(self):
        """Refresh stats by calling perfstat_memory_total() again."""
        logger.debug("AixMemory.update_values: starting")
        ts = getattr(self, '_ts', None)
        self.stats = {
            "memory": get_memory_total(ts),
            "slabs":  False,
        }
        logger.debug("AixMemory.update_values: complete (ok=%s)",
                     self.stats["memory"] is not False)

    def __init__(self, _time=None):
        """Initialise the gatherer and immediately collect memory stats."""
        self._ts = _time if _time is not None else time.time()
        logger.debug("AixMemory: initializing")
        self.update_values()


if __name__ == "__main__":
    import pprint

    # Verify struct size before making any calls.
    expected = 176
    actual = ctypes.sizeof(perfstat_memory_total_t)
    if actual != expected:
        print(f"FAIL: perfstat_memory_total_t size {actual}, expected {expected}")
    else:
        print(f"perfstat_memory_total_t size: {actual} bytes (OK)")
        pp = pprint.PrettyPrinter(indent=4)
        m = AixMemory()
        pp.pprint(m.stats)
        mem = m.stats["memory"]
        if mem:
            gb = 1024 ** 3
            print(f"\n  RAM total:  {mem['mem_total']  / gb:.2f} GB")
            print(f"  RAM free:   {mem['mem_free']   / gb:.2f} GB")
            print(f"  RAM inuse:  {mem['real_inuse'] / gb:.2f} GB")
            print(f"  Cached:     {mem['cached'] / gb:.2f} GB")
            print(f"  Swap total: {mem['swap_total'] / gb:.2f} GB")
            print(f"  Swap free:  {mem['swap_free']  / gb:.2f} GB")
