# Shared utility functions used by all gatherer modules.
import sys
sys.dont_write_bytecode = True
import os


def caniread(path):
    """Return True if the current process has read access to path, False otherwise.

    Used as a preflight check before opening /proc and /sys files, since
    some files (e.g. /proc/slabinfo) require root and will fail silently
    without this check.
    """
    if os.access(path, os.R_OK) is False:
        return False
    else:
        return True


_IEC = {p + 'ib': 1024 ** e for e, p in enumerate('kmgtpe', 1)}
_SI  = {p + 'b':  1000 ** e for e, p in enumerate('kmgtpe', 1)}
_MULTIPLIERS = {'b': 1, **_SI, **_IEC}


def tobytes(value, unit):
    """Convert a value with a unit string to bytes.

    Supports SI (KB=1000) and IEC (KiB=1024) prefixes from kilo through exa,
    plus bare 'b' for bytes. Unit matching is case-insensitive.
    Returns 0 for unrecognised units.
    """
    return value * _MULTIPLIERS.get(unit.lower(), 0)
