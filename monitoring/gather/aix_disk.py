# AIX disk gatherer. Uses libperfstat via ctypes to call perfstat_disk_total()
# and perfstat_disk().
#
# Exposes an AixDisk class. After instantiation:
#   disk_total    — aggregate stats across all disks (perfstat_disk_total_t)
#   blockdevices  — per-disk stats dict keyed by disk name (perfstat_disk_t),
#                   matching the shape of the Linux Disk.blockdevices dict
#
# Call __init__() (re-instantiate) or add an UpdateValues() method to refresh.
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
    """perfstat_id_t — cursor used to control perfstat enumeration.

    Set name to b"" (empty string) to start enumeration from the first object
    (FIRST_DISK). After a successful call, name is updated to the last object
    returned, enabling paginated enumeration. Pass NULL (None) for count-only
    calls where no buffer is provided.
    """
    _fields_ = [
        ("name", ctypes.c_char * IDENTIFIER_LENGTH),
    ]


class perfstat_disk_total_t(ctypes.Structure):
    """Aggregate disk statistics across all disks — perfstat_disk_total_t.

    Layout verified with dump_offsets.c (offsetof macro) on AIX 7.3 / gcc -m64.
    sizeof == 192.

    The 8-byte gap between 'time' and 'version' at offset 64 is undocumented
    in IBM's public headers and not present in any third-party binding (JNA,
    Go power-devops/perfstat) but was confirmed by the offsetof dump.

    Units:
        size, free  — megabytes
        xfers       — total I/O operations since boot
        xrate       — read transfers since boot (__rxfers)
        rblks/wblks — 512-byte blocks transferred
        rserv/wserv — cumulative service times in milliseconds
        wq_*        — write-queue depth and wait time statistics
    """
    _fields_ = [
        ("number",       ctypes.c_int),
        ("_pad0",        ctypes.c_int),          # int -> u_longlong_t alignment
        ("size",         ctypes.c_ulonglong),
        ("free",         ctypes.c_ulonglong),
        ("xrate",        ctypes.c_ulonglong),
        ("xfers",        ctypes.c_ulonglong),
        ("wblks",        ctypes.c_ulonglong),
        ("rblks",        ctypes.c_ulonglong),
        ("time",         ctypes.c_ulonglong),
        ("_pad1",        ctypes.c_ulonglong),     # undocumented gap at offset 64
        ("version",      ctypes.c_ulonglong),
        ("rserv",        ctypes.c_ulonglong),
        ("min_rserv",    ctypes.c_ulonglong),
        ("max_rserv",    ctypes.c_ulonglong),
        ("rtimeout",     ctypes.c_ulonglong),
        ("rfailed",      ctypes.c_ulonglong),
        ("wserv",        ctypes.c_ulonglong),
        ("min_wserv",    ctypes.c_ulonglong),
        ("max_wserv",    ctypes.c_ulonglong),
        ("wtimeout",     ctypes.c_ulonglong),
        ("wfailed",      ctypes.c_ulonglong),
        ("wq_depth",     ctypes.c_ulonglong),
        ("wq_time",      ctypes.c_ulonglong),
        ("wq_min_time",  ctypes.c_ulonglong),
        ("wq_max_time",  ctypes.c_ulonglong),
    ]


class perfstat_disk_t(ctypes.Structure):
    """Per-disk statistics — perfstat_disk_t.

    Layout verified with dump_offsets.c (offsetof macro) on AIX 7.3 / gcc -m64.
    sizeof == 496.

    'xrate' maps to the internal field __rxfers (read transfers), not a rate.
    The name is preserved from the C struct for direct correspondence.

    Units:
        size, free  — megabytes
        bsize       — bytes per block for this disk
        xfers       — total transfers (reads + writes)
        xrate       — read transfers (__rxfers)
        rblks/wblks — 512-byte blocks
        rserv/wserv — cumulative service times in milliseconds
        wq_*        — write-queue statistics
        wpar_id     — workload partition ID (0 = global)
        dk_type     — device type code
    """
    _fields_ = [
        ("name",         ctypes.c_char * IDENTIFIER_LENGTH),
        ("description",  ctypes.c_char * IDENTIFIER_LENGTH),
        ("vgname",       ctypes.c_char * IDENTIFIER_LENGTH),
        ("size",         ctypes.c_ulonglong),
        ("free",         ctypes.c_ulonglong),
        ("bsize",        ctypes.c_ulonglong),
        ("xrate",        ctypes.c_ulonglong),     # __rxfers: read transfers
        ("xfers",        ctypes.c_ulonglong),     # total transfers (r + w)
        ("wblks",        ctypes.c_ulonglong),
        ("rblks",        ctypes.c_ulonglong),
        ("qdepth",       ctypes.c_ulonglong),
        ("time",         ctypes.c_ulonglong),
        ("adapter",      ctypes.c_char * IDENTIFIER_LENGTH),
        ("paths_count",  ctypes.c_int),
        ("_pad0",        ctypes.c_int),           # int -> u_longlong_t alignment
        ("q_full",       ctypes.c_ulonglong),
        ("rserv",        ctypes.c_ulonglong),
        ("rtimeout",     ctypes.c_ulonglong),
        ("rfailed",      ctypes.c_ulonglong),
        ("min_rserv",    ctypes.c_ulonglong),
        ("max_rserv",    ctypes.c_ulonglong),
        ("wserv",        ctypes.c_ulonglong),
        ("wtimeout",     ctypes.c_ulonglong),
        ("wfailed",      ctypes.c_ulonglong),
        ("min_wserv",    ctypes.c_ulonglong),
        ("max_wserv",    ctypes.c_ulonglong),
        ("wq_depth",     ctypes.c_ulonglong),
        ("wq_sampled",   ctypes.c_ulonglong),
        ("wq_time",      ctypes.c_ulonglong),
        ("wq_min_time",  ctypes.c_ulonglong),
        ("wq_max_time",  ctypes.c_ulonglong),
        ("q_sampled",    ctypes.c_ulonglong),
        ("wpar_id",      ctypes.c_short),
        ("_pad1",        ctypes.c_short),         # short+short+int -> u_longlong_t
        ("_pad2",        ctypes.c_int),
        ("version",      ctypes.c_ulonglong),
        ("dk_type",      ctypes.c_int),
        ("_pad3",        ctypes.c_int),           # trailing alignment for array use
    ]


def _struct_to_dict(buf, struct_class):
    """Convert a ctypes Structure instance to a plain Python dict.

    Skips any field whose name starts with '_pad' (alignment padding).
    bytes fields (char arrays) are decoded from ASCII, with null bytes stripped.
    """
    result = {}
    for field_name, _ in struct_class._fields_:
        if field_name.startswith("_pad"):
            continue
        val = getattr(buf, field_name)
        if isinstance(val, bytes):
            result[field_name] = val.decode("ascii", errors="replace").rstrip("\x00")
        else:
            result[field_name] = val
    return result


def _load_lib():
    """Load libperfstat from its AIX shared archive member (64-bit object)."""
    return ctypes.CDLL("libperfstat.a(shr_64.o)")


def get_disk_total(lib, _time=None):
    """Call perfstat_disk_total() and return aggregate disk stats as a dict.

    Passes count=1 and a single-struct buffer. The first argument (id) is NULL
    since disk_total is a singleton — unlike perfstat_disk(), it does not
    enumerate multiple objects and does not use a perfstat_id_t cursor.

    The raw struct fields "number", "size", and "free" are renamed to
    "ndisks", "size_mb", and "free_mb" to clarify their meaning and units.

    Returns False and logs an error if the call does not return exactly 1.
    """
    logger.debug("get_disk_total: calling perfstat_disk_total")
    lib.perfstat_disk_total.argtypes = [
        ctypes.POINTER(perfstat_id_t),
        ctypes.POINTER(perfstat_disk_total_t),
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.perfstat_disk_total.restype = ctypes.c_int

    buf = perfstat_disk_total_t()
    ret = lib.perfstat_disk_total(None, ctypes.byref(buf), ctypes.sizeof(buf), 1)
    if ret != 1:
        logger.error("perfstat_disk_total returned %d, expected 1", ret)
        return False

    result = _struct_to_dict(buf, perfstat_disk_total_t)
    # Rename to schema column names and convert capacity to bytes.
    result["ndisks"]      = result.pop("number")
    result["size_bytes"]  = result.pop("size") * 1024 * 1024
    result["free_bytes"]  = result.pop("free") * 1024 * 1024
    logger.debug("get_disk_total: ndisks=%d size_bytes=%d free_bytes=%d xfers=%d",
                 result["ndisks"], result["size_bytes"], result["free_bytes"], result["xfers"])
    logger.debug("get_disk_total: rblks=%d wblks=%d xrate=%d",
                 result["rblks"], result["wblks"], result["xrate"])
    return result


def get_disks(lib, _time=None):
    """Call perfstat_disk() to enumerate all per-disk stats and return them as a dict.

    Uses the standard two-call perfstat enumeration pattern:
        1. Pass NULL id, NULL buffer, count=0 → returns total number of disks.
        2. Allocate an array of that size, set id.name=b"" (FIRST_DISK), then
           call again with the array pointer and count to fill the buffer.

    The array pointer must be cast to POINTER(perfstat_disk_t) because ctypes
    does not implicitly convert a pointer-to-array to a pointer-to-element.

    The raw "size" and "free" fields are renamed to "size_mb" / "free_mb" to
    make units explicit — perfstat_disk_t reports both in megabytes.

    Returns a dict keyed by disk name (e.g. "hdisk0"), or an empty dict on
    error.
    """
    logger.debug("get_disks: calling perfstat_disk (count query + enumeration)")
    lib.perfstat_disk.argtypes = [
        ctypes.POINTER(perfstat_id_t),
        ctypes.POINTER(perfstat_disk_t),
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.perfstat_disk.restype = ctypes.c_int

    # Count-only call: NULL id, NULL buffer, count=0 → returns number of disks.
    ndisks = lib.perfstat_disk(None, None, ctypes.sizeof(perfstat_disk_t), 0)
    if ndisks <= 0:
        logger.error("perfstat_disk count query returned %d", ndisks)
        return {}
    logger.debug("get_disks: perfstat reports %d disks", ndisks)

    DiskArray = perfstat_disk_t * ndisks
    disk_buf = DiskArray()

    # Start enumeration from the first disk (FIRST_DISK = empty name string).
    first = perfstat_id_t()
    first.name = b""

    ret = lib.perfstat_disk(
        ctypes.byref(first),
        ctypes.cast(disk_buf, ctypes.POINTER(perfstat_disk_t)),
        ctypes.sizeof(perfstat_disk_t),
        ndisks,
    )
    if ret != ndisks:
        logger.error("perfstat_disk enumeration returned %d, expected %d (count mismatch)",
                     ret, ndisks)
        return {}

    disks = {}
    for i in range(ret):
        d = _struct_to_dict(disk_buf[i], perfstat_disk_t)
        # Convert capacity from MB to bytes and use schema column names.
        d["size_bytes"] = d.pop("size") * 1024 * 1024
        d["free_bytes"] = d.pop("free") * 1024 * 1024
        disks[d["name"]] = d
    logger.debug("get_disks: collected %d disks", len(disks))
    for dname, d in disks.items():
        logger.debug("get_disks:   %s size_bytes=%d free_bytes=%d xfers=%d xrate=%d vgname=%r",
                     dname, d["size_bytes"], d["free_bytes"], d["xfers"], d["xrate"], d["vgname"])
    return disks


class AixDisk:
    """AIX disk gatherer using libperfstat. Mirrors the Linux Disk class interface.

    Loads libperfstat once and makes both perfstat calls in __init__.

    Exposes:
        disk_total    — aggregate stats dict from perfstat_disk_total_t,
                        matching schema names.
        blockdevices  — per-disk stats dict keyed by disk name (e.g. "hdisk0"),
                        each entry from perfstat_disk_t.
    """

    def __init__(self, _time=None):
        """Load libperfstat once and collect both aggregate and per-disk stats."""
        logger.debug("AixDisk: initializing")
        ts = _time if _time is not None else time.time()
        lib = _load_lib()
        self.disk_total = get_disk_total(lib, ts)
        self.blockdevices = get_disks(lib, ts)
        logger.debug("AixDisk: initialized (disk_total ok=%s, blockdevices=%d)",
                     self.disk_total is not False, len(self.blockdevices))


if __name__ == "__main__":
    import pprint
    pp = pprint.PrettyPrinter(indent=4)
    d = AixDisk()
    print("=== disk_total ===")
    pp.pprint(d.disk_total)
    print("\n=== blockdevices ===")
    pp.pprint(d.blockdevices)
