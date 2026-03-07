"""Shared utilities for AIX libperfstat gatherer modules.

load_libperfstat() — load libperfstat.a(shr_64.o) via ctypes.
perfstat_id_t      — the enumeration cursor struct shared by all perfstat calls.
perfstat_enumerate() — centralized two-call enumeration pattern (count → allocate → fill).
struct_to_dict()   — convert a ctypes Structure to a plain dict, skipping _pad fields.

IDENTIFIER_LENGTH  — 64, matching libperfstat.h IDENTIFIER_LENGTH.
"""
import sys
sys.dont_write_bytecode = True
import ctypes

# Matches IDENTIFIER_LENGTH in libperfstat.h (64 bytes).
IDENTIFIER_LENGTH = 64


class perfstat_id_t(ctypes.Structure):
    """perfstat_id_t — cursor used to control perfstat enumeration calls.

    Set name to b"" (empty string / FIRST_CPU / FIRST_DISK etc.) to start
    enumeration from the first object. After a successful call, name is updated
    to the last object returned, enabling paginated enumeration.
    Pass NULL (None) for count-only calls where no buffer is provided.
    """
    _fields_ = [
        ("name", ctypes.c_char * IDENTIFIER_LENGTH),
    ]


def load_libperfstat():
    """Load libperfstat from its AIX shared archive member (64-bit object).

    On AIX, shared libraries are bundled inside .a archive files. The member
    shr_64.o is the 64-bit shared object. Raises OSError if the library
    cannot be loaded (e.g. not running on AIX).
    """
    return ctypes.CDLL("libperfstat.a(shr_64.o)")


def perfstat_enumerate(lib, perfstat_func, struct_type):
    """Perform a perfstat enumeration using the standard two-call pattern.

    Most libperfstat functions require two calls:
        1. Count-only call (NULL buffer) to discover the number of items
        2. Enumeration call (with allocated buffer) to fill it

    Args:
        lib: ctypes.CDLL instance (loaded libperfstat)
        perfstat_func: the perfstat_* function to call (e.g. lib.perfstat_cpu)
        struct_type: the ctypes.Structure subclass for the result (e.g. perfstat_cpu_t)

    Returns:
        List of populated struct instances on success, or empty list on error.
        Automatically handles argtypes/restype setup and error checking.
    """
    # Set up function signature
    perfstat_func.argtypes = [
        ctypes.POINTER(perfstat_id_t),
        ctypes.POINTER(struct_type),
        ctypes.c_int,
        ctypes.c_int,
    ]
    perfstat_func.restype = ctypes.c_int

    # Count-only call: NULL id, NULL buffer, count=0 → returns number of items
    count = perfstat_func(None, None, ctypes.sizeof(struct_type), 0)
    if count <= 0:
        return []

    # Allocate array and enumerate all items
    Array = struct_type * count
    buf = Array()
    first = perfstat_id_t()
    first.name = b""  # FIRST_* constant

    ret = perfstat_func(
        ctypes.byref(first),
        ctypes.cast(buf, ctypes.POINTER(struct_type)),
        ctypes.sizeof(struct_type),
        count,
    )
    if ret != count:
        return []

    return list(buf)


def struct_to_dict(buf, struct_class):
    """Convert a ctypes Structure instance to a plain Python dict.

    Skips any field whose name starts with '_pad' (alignment padding).
    bytes fields (char arrays) are decoded from ASCII, with null bytes stripped.

    Used by aix_disk and other gatherers that iterate over libperfstat structs
    without requiring special per-field handling.
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
