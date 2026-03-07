"""Shared utilities for AIX libperfstat gatherer modules.

load_libperfstat() — load libperfstat.a(shr_64.o) via ctypes.
perfstat_id_t      — the enumeration cursor struct shared by all perfstat calls.
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
