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


def tobytes(value, multiplier):
    """Convert a numeric value with a unit string to bytes.

    Used when parsing /proc/meminfo lines that look like:
        MemTotal: 16384 kB

    Supports kB, MB, GB, TB (case-insensitive prefix, long form accepted).
    Returns 0 for unrecognised multipliers.
    """
    if multiplier in ["kB", "KB", "kilobyte", "kilobytes"]:
        return value * 1024
    if multiplier in ["mB", "MB", "megabyte", "megabytes"]:
        return value * 1024 * 1024
    if multiplier in ["gB", "GB", "gigabyte", "gigabytes"]:
        return value * 1024 * 1024 * 1024
    if multiplier in ["tB", "TB", "terabyte", "terabytes"]:
        return value * 1024 * 1024 * 1024 * 1024
    else:
        return 0
