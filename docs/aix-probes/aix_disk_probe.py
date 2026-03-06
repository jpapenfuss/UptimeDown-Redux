#!/usr/bin/env python3
"""Self-contained AIX disk and filesystem exploration via libperfstat + statvfs.

Copy this single file to an AIX 7.x box and run:
    python3 docs/aix-probes/aix_disk_probe.py

Calls:
  1. perfstat_disk_total()  - aggregate disk stats
  2. perfstat_disk()        - per-disk stats (IOPS, service times, capacity)
  3. /etc/filesystems parse + os.statvfs() - mounted filesystem space
"""

import ctypes
import os
import pprint
import sys
import time

IDENTIFIER_LENGTH = 64

pp = pprint.PrettyPrinter(indent=4)

# ---------------------------------------------------------------------------
# Structs
# ---------------------------------------------------------------------------

class perfstat_id_t(ctypes.Structure):
    """Cursor/name argument passed to perfstat enumeration calls (64-byte name buffer)."""

    _fields_ = [
        ("name", ctypes.c_char * IDENTIFIER_LENGTH),
    ]


class perfstat_disk_total_t(ctypes.Structure):
    """perfstat_disk_total_t - aggregate stats for all disks.

    Struct layout from JNA (java-native-access) Perfstat.java and
    Go power-devops/perfstat DiskTotal, cross-referenced with IBM docs.
    """
    _fields_ = [
        ("number", ctypes.c_int),
        # pad: int followed by u_longlong_t
        ("_pad0", ctypes.c_int),
        ("size", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("xrate", ctypes.c_ulonglong),
        ("xfers", ctypes.c_ulonglong),
        ("wblks", ctypes.c_ulonglong),
        ("rblks", ctypes.c_ulonglong),
        ("time", ctypes.c_ulonglong),
        # 8-byte gap at offset 64 (between time and version per offsetof dump)
        ("_pad1", ctypes.c_ulonglong),
        ("version", ctypes.c_ulonglong),
        ("rserv", ctypes.c_ulonglong),
        ("min_rserv", ctypes.c_ulonglong),
        ("max_rserv", ctypes.c_ulonglong),
        ("rtimeout", ctypes.c_ulonglong),
        ("rfailed", ctypes.c_ulonglong),
        ("wserv", ctypes.c_ulonglong),
        ("min_wserv", ctypes.c_ulonglong),
        ("max_wserv", ctypes.c_ulonglong),
        ("wtimeout", ctypes.c_ulonglong),
        ("wfailed", ctypes.c_ulonglong),
        ("wq_depth", ctypes.c_ulonglong),
        ("wq_time", ctypes.c_ulonglong),
        ("wq_min_time", ctypes.c_ulonglong),
        ("wq_max_time", ctypes.c_ulonglong),
    ]


class perfstat_disk_t(ctypes.Structure):
    """perfstat_disk_t - per-disk stats.

    Struct layout from JNA Perfstat.perfstat_disk_t, cross-referenced with
    Go power-devops/perfstat Disk struct and nmon source code.

    Field 'xrate' in the C struct is '__rxfers' internally (read transfers).
    psutil accesses it as '__rxfers'; JNA and Go expose it as 'xrate'.
    """
    _fields_ = [
        ("name", ctypes.c_char * IDENTIFIER_LENGTH),
        ("description", ctypes.c_char * IDENTIFIER_LENGTH),
        ("vgname", ctypes.c_char * IDENTIFIER_LENGTH),
        ("size", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("bsize", ctypes.c_ulonglong),
        ("xrate", ctypes.c_ulonglong),       # __rxfers: read transfers
        ("xfers", ctypes.c_ulonglong),        # total transfers (read + write)
        ("wblks", ctypes.c_ulonglong),
        ("rblks", ctypes.c_ulonglong),
        ("qdepth", ctypes.c_ulonglong),
        ("time", ctypes.c_ulonglong),
        ("adapter", ctypes.c_char * IDENTIFIER_LENGTH),
        ("paths_count", ctypes.c_int),
        # pad: int followed by u_longlong_t
        ("_pad0", ctypes.c_int),
        ("q_full", ctypes.c_ulonglong),
        ("rserv", ctypes.c_ulonglong),
        ("rtimeout", ctypes.c_ulonglong),
        ("rfailed", ctypes.c_ulonglong),
        ("min_rserv", ctypes.c_ulonglong),
        ("max_rserv", ctypes.c_ulonglong),
        ("wserv", ctypes.c_ulonglong),
        ("wtimeout", ctypes.c_ulonglong),
        ("wfailed", ctypes.c_ulonglong),
        ("min_wserv", ctypes.c_ulonglong),
        ("max_wserv", ctypes.c_ulonglong),
        ("wq_depth", ctypes.c_ulonglong),
        ("wq_sampled", ctypes.c_ulonglong),
        ("wq_time", ctypes.c_ulonglong),
        ("wq_min_time", ctypes.c_ulonglong),
        ("wq_max_time", ctypes.c_ulonglong),
        ("q_sampled", ctypes.c_ulonglong),
        ("wpar_id", ctypes.c_short),
        # pad: short followed by u_longlong_t; need 6 bytes
        ("_pad1", ctypes.c_short),
        ("_pad2", ctypes.c_int),
        ("version", ctypes.c_ulonglong),
        ("dk_type", ctypes.c_int),
        # trailing pad for alignment if struct is used in an array
        ("_pad3", ctypes.c_int),
    ]


def struct_to_dict(buf, struct_class):
    """Convert a ctypes Structure to a plain dict, skipping padding fields."""
    result = {}
    for field_name, _ in struct_class._fields_:
        if field_name.startswith("_pad"):
            continue
        val = getattr(buf, field_name)
        if isinstance(val, bytes):
            result[field_name] = val.decode("ascii", errors="replace").rstrip("\x00")
        elif hasattr(val, "__len__"):
            result[field_name] = list(val)
        else:
            result[field_name] = val
    return result


# ---------------------------------------------------------------------------
# Filesystem collection: /etc/filesystems + statvfs
# ---------------------------------------------------------------------------

def get_all_filesystems():
    """Return all configured filesystems, with live space stats where mounted.

    Uses /etc/filesystems as the authoritative source (covers all 429+
    configured filesystems including unmounted WPAR filesystems). For each
    entry, attempts os.statvfs() on the mountpoint:
      - Success: filesystem is currently mounted; space stats are included.
      - OSError: filesystem is not mounted; config data only, mounted=False.

    Each entry includes:
        mountpoint      — filesystem mount path (dict key)
        dev             — block device
        vfs             — filesystem type (jfs2, procfs, namefs, ...)
        mounted         — True if statvfs succeeded, False otherwise
        mount           — 'automatic'/'true'/'false' from /etc/filesystems
        type            — WPAR name or class if present
        log             — journal log device if present
        options, account — other /etc/filesystems attributes
        (statvfs fields + bytesTotal/bytesFree/bytesAvailable/pct* if mounted)
    """
    etc_fs_path = "/etc/filesystems"
    if not os.access(etc_fs_path, os.R_OK):
        print(f"  WARNING: Can't read {etc_fs_path}")
        return {}

    # Parse /etc/filesystems stanza format.
    config = {}
    current_stanza = None
    with open(etc_fs_path, "r") as f:
        for line in f:
            line = line.rstrip("\n")
            stripped = line.strip()
            if not stripped or stripped.startswith("*"):
                continue
            if not line[0].isspace() and stripped.endswith(":"):
                current_stanza = stripped.rstrip(":")
                config[current_stanza] = {}
            elif current_stanza and "=" in line:
                key, _, val = line.partition("=")
                config[current_stanza][key.strip()] = val.strip()

    # Attempt statvfs on each configured mountpoint.
    filesystems = {}
    for mountpoint, attrs in config.items():
        entry = {
            "mountpoint": mountpoint,
            "dev":        attrs.get("dev", ""),
            "vfs":        attrs.get("vfs", ""),
            "log":        attrs.get("log", ""),
            "mount":      attrs.get("mount", ""),
            "type":       attrs.get("type", ""),
            "account":    attrs.get("account", ""),
            "options":    attrs.get("options", ""),
        }
        try:
            st = os.statvfs(mountpoint)
            entry["mounted"]  = True
            entry["f_bsize"]  = st.f_bsize
            entry["f_frsize"] = st.f_frsize
            entry["f_blocks"] = st.f_blocks
            entry["f_bfree"]  = st.f_bfree
            entry["f_bavail"] = st.f_bavail
            entry["f_files"]  = st.f_files
            entry["f_ffree"]  = st.f_ffree
            entry["f_favail"] = st.f_favail
            if st.f_blocks > 0:
                entry["bytesTotal"]     = st.f_frsize * st.f_blocks
                entry["bytesFree"]      = st.f_frsize * st.f_bfree
                entry["bytesAvailable"] = st.f_frsize * st.f_bavail
                entry["pctFree"]        = (st.f_bfree  / st.f_blocks) * 100
                entry["pctAvailable"]   = (st.f_bavail / st.f_blocks) * 100
                entry["pctUsed"]        = (1.0 - st.f_bfree  / st.f_blocks) * 100
                entry["pctReserved"]    = (1.0 - st.f_bavail / st.f_blocks) * 100
        except OSError:
            entry["mounted"] = False

        filesystems[mountpoint] = entry

    return filesystems


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

disk_total_size = ctypes.sizeof(perfstat_disk_total_t)
disk_size = ctypes.sizeof(perfstat_disk_t)
print(f"perfstat_disk_total_t size: {disk_total_size} bytes (expect 192)")
print(f"perfstat_disk_t size:       {disk_size} bytes (expect 496)")

if disk_total_size != 192:
    print(f"FAIL: perfstat_disk_total_t size mismatch: got {disk_total_size}, expected 192")
    sys.exit(1)
if disk_size != 496:
    print(f"FAIL: perfstat_disk_t size mismatch: got {disk_size}, expected 496")
    sys.exit(1)

# Load library
print("\nLoading libperfstat.a(shr_64.o)...")
try:
    lib = ctypes.CDLL("libperfstat.a(shr_64.o)")
except OSError as e:
    print(f"FAIL: Can't load libperfstat: {e}")
    sys.exit(1)


# === 1. perfstat_disk_total ===

print("\n" + "=" * 60)
print("perfstat_disk_total()")
print("=" * 60)

lib.perfstat_disk_total.argtypes = [
    ctypes.POINTER(perfstat_id_t),
    ctypes.POINTER(perfstat_disk_total_t),
    ctypes.c_int,
    ctypes.c_int,
]
lib.perfstat_disk_total.restype = ctypes.c_int

disk_total_buf = perfstat_disk_total_t()
ret = lib.perfstat_disk_total(
    None, ctypes.byref(disk_total_buf), ctypes.sizeof(disk_total_buf), 1
)

if ret != 1:
    print(f"FAIL: perfstat_disk_total returned {ret}")
else:
    dt = struct_to_dict(disk_total_buf, perfstat_disk_total_t)
    dt["_time"] = time.time()
    print(f"\n  Total disks:     {dt['number']}")
    print(f"  Total size (MB): {dt['size']}")
    print(f"  Total free (MB): {dt['free']}")
    print(f"  Total xfers:     {dt['xfers']}")
    print(f"  Total rblks:     {dt['rblks']} (512-byte blocks)")
    print(f"  Total wblks:     {dt['wblks']} (512-byte blocks)")
    print(f"\n  Full output:")
    pp.pprint(dt)


# === 2. perfstat_disk (per-disk) ===

print("\n" + "=" * 60)
print("perfstat_disk() - per-disk enumeration")
print("=" * 60)

lib.perfstat_disk.argtypes = [
    ctypes.POINTER(perfstat_id_t),
    ctypes.POINTER(perfstat_disk_t),
    ctypes.c_int,
    ctypes.c_int,
]
lib.perfstat_disk.restype = ctypes.c_int

# First, query how many disks there are
ndisks = lib.perfstat_disk(None, None, ctypes.sizeof(perfstat_disk_t), 0)
print(f"\n  perfstat_disk reports {ndisks} disk(s)")

if ndisks > 0:
    # Allocate array of perfstat_disk_t
    DiskArray = perfstat_disk_t * ndisks
    disk_buf = DiskArray()

    # FIRST_DISK: set name to empty string to request all disks
    first = perfstat_id_t()
    first.name = b""

    ret = lib.perfstat_disk(
        ctypes.byref(first),
        ctypes.cast(disk_buf, ctypes.POINTER(perfstat_disk_t)),
        ctypes.sizeof(perfstat_disk_t),
        ndisks,
    )

    if ret < 0:
        print(f"  FAIL: perfstat_disk returned {ret}")
    else:
        print(f"  Got {ret} disk(s):\n")
        all_disks = {}
        for i in range(ret):
            d = struct_to_dict(disk_buf[i], perfstat_disk_t)
            d["_time"] = time.time()
            name = d["name"]
            all_disks[name] = d

            size_gb = d["size"] / 1024 if d["size"] > 0 else 0
            free_gb = d["free"] / 1024 if d["free"] > 0 else 0
            pct_used = ((d["size"] - d["free"]) / d["size"] * 100) if d["size"] > 0 else 0

            print(f"  --- {name} ---")
            print(f"    description:  {d['description']}")
            print(f"    vgname:       {d['vgname']}")
            print(f"    adapter:      {d['adapter']}")
            print(f"    size:         {d['size']} MB ({size_gb:.1f} GB)")
            print(f"    free:         {d['free']} MB ({free_gb:.1f} GB)")
            print(f"    used:         {pct_used:.1f}%")
            print(f"    bsize:        {d['bsize']} bytes")
            print(f"    xfers:        {d['xfers']} (total)")
            print(f"    xrate:        {d['xrate']} (reads)")
            print(f"    rblks:        {d['rblks']}")
            print(f"    wblks:        {d['wblks']}")
            print(f"    rserv:        {d['rserv']}")
            print(f"    wserv:        {d['wserv']}")
            print(f"    qdepth:       {d['qdepth']}")
            print(f"    paths_count:  {d['paths_count']}")
            print(f"    dk_type:      {d['dk_type']}")
            print()

        print("  Full per-disk output:")
        pp.pprint(all_disks)


# === 3. Filesystems ===

print("\n" + "=" * 60)
print("Filesystem information")
print("=" * 60)

all_fs = get_all_filesystems()
mounted_fs   = {k: v for k, v in all_fs.items() if v["mounted"]}
unmounted_fs = {k: v for k, v in all_fs.items() if not v["mounted"]}

print(f"\n  Total configured: {len(all_fs)}")
print(f"  Currently mounted: {len(mounted_fs)}")
print(f"  Not mounted: {len(unmounted_fs)}")

print("\n--- Mounted filesystems (with space stats) ---")
for mp, info in sorted(mounted_fs.items()):
    total = info.get("bytesTotal", 0)
    avail = info.get("bytesAvailable", 0)
    pct   = info.get("pctUsed", 0)
    total_gb = total / (1024**3) if total else 0
    avail_gb = avail / (1024**3) if avail else 0
    print(f"  {mp}")
    print(f"    dev:    {info['dev']}  vfs: {info['vfs']}")
    if total > 0:
        print(f"    total:  {total_gb:.2f} GB   avail: {avail_gb:.2f} GB   used: {pct:.1f}%")
    print()

print("\n--- Unmounted filesystems (config only, first 10) ---")
for mp, info in sorted(unmounted_fs.items())[:10]:
    print(f"  {mp}  dev={info['dev']}  vfs={info['vfs']}  type={info['type']}")

print("\n  Full filesystem output (all):")
pp.pprint(all_fs)


print("\nDone.")
