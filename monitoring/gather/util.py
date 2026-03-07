"""Shared utility functions used by all platform gatherer modules.

caniread()              — preflight read-access check for /proc and /sys paths.
tobytes()               — converts a (value, unit) pair to bytes, supporting both SI
                          (KB=1000) and IEC (KiB=1024) unit prefixes through exa scale.
imds_reachable()        — TCP probe for cloud IMDS endpoints (169.254.169.254).
imds_get()              — HTTP GET to a cloud IMDS endpoint path.
imds_put()              — HTTP PUT to a cloud IMDS endpoint path (e.g. IMDSv2 token).

coerce_field()          — coerce string values to int/float/list based on field membership.
to_snake_case()         — convert camelCase field names to snake_case.
calculate_percentages() — compute filesystem percentage usage from block counts.
parse_mount_options()   — parse comma-separated mount options into a dict.
dict_from_fields()      — construct a dict by zipping fields with keys, coercing to int.
"""
import sys
sys.dont_write_bytecode = True
import os
import re
import socket
import urllib.request


def caniread(path):
    """Return True if the current process has read access to path, False otherwise.

    Used as a preflight check before opening /proc and /sys files, since
    some files (e.g. /proc/slabinfo) require root and will fail silently
    without this check.
    """
    return os.access(path, os.R_OK)


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


# ---------------------------------------------------------------------------
# Cloud IMDS helpers — used by cloud provider gatherers (aws.py, etc.)
# ---------------------------------------------------------------------------

_IMDS_CONNECT_TIMEOUT = 0.5  # seconds — short probe to avoid blocking on non-cloud machines


def imds_reachable(ip='169.254.169.254', port=80, timeout=_IMDS_CONNECT_TIMEOUT):
    """Return True if a cloud IMDS endpoint is reachable via TCP, False otherwise.

    Uses a short timeout so non-cloud machines fail fast without blocking a
    collection cycle. Call this before attempting any IMDS HTTP requests.
    """
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def imds_get(ip, path, headers=None, timeout=2.0):
    """GET a path from a cloud IMDS endpoint at ip.

    Returns the response body as a str on success, None on any error.
    headers — optional dict of HTTP request headers.
    timeout — per-request timeout in seconds.
    """
    url = f"http://{ip}{path}"
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8')
    except Exception:
        return None


def imds_put(ip, path, headers=None, timeout=2.0):
    """PUT to a path on a cloud IMDS endpoint at ip.

    Returns the response body as a str on success, None on any error.
    Sends an empty body — required for AWS IMDSv2 token requests.
    headers — optional dict of HTTP request headers.
    timeout — per-request timeout in seconds.
    """
    url = f"http://{ip}{path}"
    req = urllib.request.Request(url, data=b'', method='PUT', headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8')
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Gatherer helpers — used by platform-specific gather modules
# ---------------------------------------------------------------------------

def coerce_field(value, field_name, integer_stats, float_stats, list_stats):
    """Coerce a string value based on field name membership in stat lists.

    If field_name is in integer_stats, returns int(value).
    If field_name is in float_stats, returns float(value).
    If field_name is in list_stats, returns value.split() (space-separated list).
    Otherwise, returns value unchanged (as string).

    Used by cpu, memory, and other gatherers to coerce /proc fields consistently.
    """
    if field_name in integer_stats:
        return int(value)
    elif field_name in float_stats:
        return float(value)
    elif field_name in list_stats:
        return value.split()
    else:
        return value


def to_snake_case(name):
    """Convert a field name from camelCase to snake_case.

    Handles multiple patterns:
        MemTotal        → mem_total
        HugePages_Total → huge_pages_total
        SReclaimable    → s_reclaimable

    Used by /proc/meminfo and other parsers to normalize field names.
    """
    # Insert underscore before each uppercase letter that follows a lowercase letter or digit.
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    # Handle names starting with a run of uppercase letters (e.g. SReclaimable).
    # Match an uppercase letter followed by another uppercase+lowercase pair and insert
    # the underscore between them.
    s = re.sub(r'([A-Z])([A-Z][a-z])', r'\1_\2', s)
    return s.lower()


def calculate_percentages(free, available, total):
    """Calculate filesystem percentages from block counts.

    Args:
        free: Number of free blocks (f_bfree)
        available: Number of available blocks for unprivileged users (f_bavail)
        total: Total number of blocks (f_blocks)

    Returns a dict with four percentage fields, using 2 decimal place precision:
        pct_free: Percentage free including reserved root blocks
        pct_available: Percentage available to unprivileged users
        pct_used: Percentage consumed (1 - pct_free)
        pct_reserved: Percentage reserved for root (pct_free - pct_available)

    Precision is achieved by multiplying by 1000000 and dividing by 10000 to get
    exactly 2 decimal places, matching the original code in linux_filesystems
    and aix_filesystems.
    """
    try:
        pct_free = int((free / total) * 1000000) / 10000
        pct_available = int((available / total) * 1000000) / 10000
        pct_used = int((1.0 - free / total) * 1000000) / 10000
        pct_reserved = int(((free - available) / total) * 1000000) / 10000
        return {
            "pct_free": pct_free,
            "pct_available": pct_available,
            "pct_used": pct_used,
            "pct_reserved": pct_reserved,
        }
    except ZeroDivisionError:
        raise RuntimeError("calculate_percentages called with total == 0")


def parse_mount_options(options_str):
    """Parse a comma-separated mount options string into a dict.

    Bare flags (e.g. 'rw', 'noatime') map to True.
    Key=value pairs (e.g. 'size=1g', 'uid=0') map to the value string.
    The result is intended to be stored as JSON via json.dumps().

    Used by both Linux and AIX filesystem gatherers.
    """
    opts = {}
    for token in options_str.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            k, _, v = token.partition("=")
            opts[k.strip()] = v.strip()
        else:
            opts[token] = True
    return opts


def dict_from_fields(fields, keys):
    """Construct a dict by zipping field values with key names, coercing to int.

    Args:
        fields: List of field values (usually strings from split())
        keys: List or tuple of field names (or dict key tuples)

    Returns a dict where each key from keys maps to the corresponding field
    value, coerced to int. zip() stops at the shorter iterable, so extra
    fields are silently ignored.

    Used by disk, network, and CPU parsers to convert split lines into dicts.
    """
    return dict(zip(keys, map(int, fields)))


def read_sysfs_int(path):
    """Read a single integer value from a sysfs file.

    Opens path, strips whitespace, and casts to int.
    Returns the int on success, or None if the file does not exist, is
    unreadable, or its contents cannot be parsed as an integer.

    Used by linux_disk and linux_network to read /sys/class/net/* and
    /sys/dev/block/*/queue/* attributes without repetitive try/except blocks.
    """
    try:
        with open(path, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def read_sysfs_str(path):
    """Read a single string value from a sysfs file.

    Opens path, strips whitespace, and returns the result.
    Returns None if the file does not exist, is unreadable, or its stripped
    contents are empty.

    Used by linux_disk and linux_network to read string-valued /sys attributes
    (e.g. operstate, scheduler) without repetitive try/except blocks.
    """
    try:
        with open(path, "r") as f:
            val = f.read().strip()
            return val if val else None
    except (FileNotFoundError, OSError):
        return None
