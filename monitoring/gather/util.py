"""Shared utility functions used by all platform gatherer modules.

caniread()       — preflight read-access check for /proc and /sys paths.
tobytes()        — converts a (value, unit) pair to bytes, supporting both SI
                   (KB=1000) and IEC (KiB=1024) unit prefixes through exa scale.
imds_reachable() — TCP probe for cloud IMDS endpoints (169.254.169.254).
imds_get()       — HTTP GET to a cloud IMDS endpoint path.
imds_put()       — HTTP PUT to a cloud IMDS endpoint path (e.g. IMDSv2 token).
"""
import sys
sys.dont_write_bytecode = True
import os
import socket
import urllib.request


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
