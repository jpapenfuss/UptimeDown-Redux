#!/usr/bin/env python3
"""Self-contained probe for AIX perfstat ctypes wrappers.

Copy this single file to an AIX 7.x box and run:
    python3 docs/aix-probes/aix_cpu_probe.py

Probes perfstat_cpu_total and perfstat_partition_total.
"""

import ctypes
import pprint
import sys
import time

IDENTIFIER_LENGTH = 64
CEC_ID_LEN = 40

# ---------------------------------------------------------------------------
# Structs
# ---------------------------------------------------------------------------

class perfstat_id_t(ctypes.Structure):
    """Cursor/name argument passed to perfstat enumeration calls (64-byte name buffer)."""

    _fields_ = [
        ("name", ctypes.c_char * IDENTIFIER_LENGTH),
    ]


class perfstat_cpu_total_t(ctypes.Structure):
    """perfstat_cpu_total_t_72 from libperfstat.h"""
    _fields_ = [
        ("ncpus", ctypes.c_int),
        ("ncpus_cfg", ctypes.c_int),
        ("description", ctypes.c_char * IDENTIFIER_LENGTH),
        ("processorHZ", ctypes.c_ulonglong),
        ("user", ctypes.c_ulonglong),
        ("sys", ctypes.c_ulonglong),
        ("idle", ctypes.c_ulonglong),
        ("wait", ctypes.c_ulonglong),
        ("pswitch", ctypes.c_ulonglong),
        ("syscall", ctypes.c_ulonglong),
        ("sysread", ctypes.c_ulonglong),
        ("syswrite", ctypes.c_ulonglong),
        ("sysfork", ctypes.c_ulonglong),
        ("sysexec", ctypes.c_ulonglong),
        ("readch", ctypes.c_ulonglong),
        ("writech", ctypes.c_ulonglong),
        ("devintrs", ctypes.c_ulonglong),
        ("softintrs", ctypes.c_ulonglong),
        ("lbolt", ctypes.c_longlong),
        ("loadavg", ctypes.c_ulonglong * 3),
        ("runque", ctypes.c_ulonglong),
        ("swpque", ctypes.c_ulonglong),
        ("bread", ctypes.c_ulonglong),
        ("bwrite", ctypes.c_ulonglong),
        ("lread", ctypes.c_ulonglong),
        ("lwrite", ctypes.c_ulonglong),
        ("phread", ctypes.c_ulonglong),
        ("phwrite", ctypes.c_ulonglong),
        ("runocc", ctypes.c_ulonglong),
        ("swpocc", ctypes.c_ulonglong),
        ("iget", ctypes.c_ulonglong),
        ("namei", ctypes.c_ulonglong),
        ("dirblk", ctypes.c_ulonglong),
        ("msg", ctypes.c_ulonglong),
        ("sema", ctypes.c_ulonglong),
        ("rcvint", ctypes.c_ulonglong),
        ("xmtint", ctypes.c_ulonglong),
        ("mdmint", ctypes.c_ulonglong),
        ("tty_rawinch", ctypes.c_ulonglong),
        ("tty_caninch", ctypes.c_ulonglong),
        ("tty_rawoutch", ctypes.c_ulonglong),
        ("ksched", ctypes.c_ulonglong),
        ("koverf", ctypes.c_ulonglong),
        ("kexit", ctypes.c_ulonglong),
        ("rbread", ctypes.c_ulonglong),
        ("rcread", ctypes.c_ulonglong),
        ("rbwrt", ctypes.c_ulonglong),
        ("rcwrt", ctypes.c_ulonglong),
        ("traps", ctypes.c_ulonglong),
        ("ncpus_high", ctypes.c_int),
        ("_pad0", ctypes.c_int),
        ("puser", ctypes.c_ulonglong),
        ("psys", ctypes.c_ulonglong),
        ("pidle", ctypes.c_ulonglong),
        ("pwait", ctypes.c_ulonglong),
        ("decrintrs", ctypes.c_ulonglong),
        ("mpcrintrs", ctypes.c_ulonglong),
        ("mpcsintrs", ctypes.c_ulonglong),
        ("phantintrs", ctypes.c_ulonglong),
        ("idle_donated_purr", ctypes.c_ulonglong),
        ("idle_donated_spurr", ctypes.c_ulonglong),
        ("busy_donated_purr", ctypes.c_ulonglong),
        ("busy_donated_spurr", ctypes.c_ulonglong),
        ("idle_stolen_purr", ctypes.c_ulonglong),
        ("idle_stolen_spurr", ctypes.c_ulonglong),
        ("busy_stolen_purr", ctypes.c_ulonglong),
        ("busy_stolen_spurr", ctypes.c_ulonglong),
        ("iowait", ctypes.c_short),
        ("physio", ctypes.c_short),
        ("_pad1", ctypes.c_int),
        ("twait", ctypes.c_longlong),
        ("hpi", ctypes.c_ulonglong),
        ("hpit", ctypes.c_ulonglong),
        ("puser_spurr", ctypes.c_ulonglong),
        ("psys_spurr", ctypes.c_ulonglong),
        ("pidle_spurr", ctypes.c_ulonglong),
        ("pwait_spurr", ctypes.c_ulonglong),
        ("spurrflag", ctypes.c_int),
        ("_pad2", ctypes.c_int),
        ("version", ctypes.c_ulonglong),
        ("tb_last", ctypes.c_ulonglong),
        ("purr_coalescing", ctypes.c_ulonglong),
        ("spurr_coalescing", ctypes.c_ulonglong),
    ]


class perfstat_partition_total_t(ctypes.Structure):
    """perfstat_partition_total_t_71_1 from libperfstat.h (LATEST as of 7.2/7.3).

    The 'type' field is a union { uint w; struct { bitfields } b; } which is
    4 bytes. We represent it as a plain c_uint and decode the bits in Python.
    """
    _fields_ = [
        ("name", ctypes.c_char * IDENTIFIER_LENGTH),
        # perfstat_partition_type_t is a union of uint and bitfield struct = 4 bytes
        ("type", ctypes.c_uint),
        ("lpar_id", ctypes.c_int),
        ("group_id", ctypes.c_int),
        ("pool_id", ctypes.c_int),
        ("online_cpus", ctypes.c_int),
        ("max_cpus", ctypes.c_int),
        ("min_cpus", ctypes.c_int),
        # 64 + 4 + (6*4) = 92 bytes; next is u_longlong_t, needs pad to 96
        ("_pad0", ctypes.c_int),
        ("online_memory", ctypes.c_ulonglong),
        ("max_memory", ctypes.c_ulonglong),
        ("min_memory", ctypes.c_ulonglong),
        ("entitled_proc_capacity", ctypes.c_int),
        ("max_proc_capacity", ctypes.c_int),
        ("min_proc_capacity", ctypes.c_int),
        ("proc_capacity_increment", ctypes.c_int),
        ("unalloc_proc_capacity", ctypes.c_int),
        ("var_proc_capacity_weight", ctypes.c_int),
        ("unalloc_var_proc_capacity_weight", ctypes.c_int),
        ("online_phys_cpus_sys", ctypes.c_int),
        ("max_phys_cpus_sys", ctypes.c_int),
        ("phys_cpus_pool", ctypes.c_int),
        # 10 ints = 40 bytes after the 3 u_longlong_t; offset = 96+24+40 = 160.
        # 160 is 8-byte aligned, no pad needed before puser.
        ("puser", ctypes.c_ulonglong),
        ("psys", ctypes.c_ulonglong),
        ("pidle", ctypes.c_ulonglong),
        ("pwait", ctypes.c_ulonglong),
        ("pool_idle_time", ctypes.c_ulonglong),
        ("phantintrs", ctypes.c_ulonglong),
        ("invol_virt_cswitch", ctypes.c_ulonglong),
        ("vol_virt_cswitch", ctypes.c_ulonglong),
        ("timebase_last", ctypes.c_ulonglong),
        ("reserved_pages", ctypes.c_ulonglong),
        ("reserved_pagesize", ctypes.c_ulonglong),
        ("idle_donated_purr", ctypes.c_ulonglong),
        ("idle_donated_spurr", ctypes.c_ulonglong),
        ("busy_donated_purr", ctypes.c_ulonglong),
        ("busy_donated_spurr", ctypes.c_ulonglong),
        ("idle_stolen_purr", ctypes.c_ulonglong),
        ("idle_stolen_spurr", ctypes.c_ulonglong),
        ("busy_stolen_purr", ctypes.c_ulonglong),
        ("busy_stolen_spurr", ctypes.c_ulonglong),
        ("shcpus_in_sys", ctypes.c_ulonglong),
        ("max_pool_capacity", ctypes.c_ulonglong),
        ("entitled_pool_capacity", ctypes.c_ulonglong),
        ("pool_max_time", ctypes.c_ulonglong),
        ("pool_busy_time", ctypes.c_ulonglong),
        ("pool_scaled_busy_time", ctypes.c_ulonglong),
        ("shcpu_tot_time", ctypes.c_ulonglong),
        ("shcpu_busy_time", ctypes.c_ulonglong),
        ("shcpu_scaled_busy_time", ctypes.c_ulonglong),
        ("ams_pool_id", ctypes.c_int),
        ("var_mem_weight", ctypes.c_int),
        ("iome", ctypes.c_ulonglong),
        ("pmem", ctypes.c_ulonglong),
        ("hpi", ctypes.c_ulonglong),
        ("hpit", ctypes.c_ulonglong),
        ("hypv_pagesize", ctypes.c_ulonglong),
        # uint online_lcpus, uint smt_thrds = 8 bytes total, already aligned
        ("online_lcpus", ctypes.c_uint),
        ("smt_thrds", ctypes.c_uint),
        ("puser_spurr", ctypes.c_ulonglong),
        ("psys_spurr", ctypes.c_ulonglong),
        ("pidle_spurr", ctypes.c_ulonglong),
        ("pwait_spurr", ctypes.c_ulonglong),
        ("spurrflag", ctypes.c_int),
        # char[40] + int = 44 bytes; but spurrflag is before hardwareid.
        # spurrflag(4) + hardwareid(40) = 44 bytes; then uint power_save_mode.
        # 4 + 40 = 44, next is uint (4 bytes), no alignment issue.
        ("hardwareid", ctypes.c_char * CEC_ID_LEN),
        ("power_save_mode", ctypes.c_uint),
        ("ame_version", ctypes.c_ushort),
        # power_save_mode(4) + ame_version(2) = 6 bytes; next is u_longlong_t.
        # Need 2 bytes padding to reach 8-byte alignment.
        ("_pad1", ctypes.c_ushort),
        ("true_memory", ctypes.c_ulonglong),
        ("expanded_memory", ctypes.c_ulonglong),
        ("target_memexp_factr", ctypes.c_ulonglong),
        ("current_memexp_factr", ctypes.c_ulonglong),
        ("target_cpool_size", ctypes.c_ulonglong),
        ("max_cpool_size", ctypes.c_ulonglong),
        ("min_ucpool_size", ctypes.c_ulonglong),
        ("ame_deficit_size", ctypes.c_ulonglong),
        ("version", ctypes.c_ulonglong),
        ("cmcs_total_time", ctypes.c_ulonglong),
        # _71_1 extension fields:
        ("purr_coalescing", ctypes.c_ulonglong),
        ("spurr_coalescing", ctypes.c_ulonglong),
        ("MemPoolSize", ctypes.c_ulonglong),
        ("IOMemEntInUse", ctypes.c_ulonglong),
        ("IOMemEntFree", ctypes.c_ulonglong),
        ("IOHighWaterMark", ctypes.c_ulonglong),
        ("purr_counter", ctypes.c_ulonglong),
        ("spurr_counter", ctypes.c_ulonglong),
        ("real_free", ctypes.c_ulonglong),
        ("real_avail", ctypes.c_ulonglong),
    ]


def decode_partition_type(type_val):
    """Decode the perfstat_partition_type_t bitfield union."""
    flags = {}
    bit_names = [
        "smt_capable", "smt_enabled", "lpar_capable", "lpar_enabled",
        "shared_capable", "shared_enabled", "dlpar_capable", "capped",
        "kernel_is_64", "pool_util_authority", "donate_capable", "donate_enabled",
        "ams_capable", "ams_enabled", "power_save", "ame_enabled",
        "shared_extended",
    ]
    for i, name in enumerate(bit_names):
        # Bits are numbered from MSB of the uint (bit 31 = index 0)
        flags[name] = bool(type_val & (1 << (31 - i)))
    return flags


def struct_to_dict(buf, struct_class):
    """Convert a ctypes Structure to a plain dict, skipping padding fields."""
    result = {}
    for field_name, _ in struct_class._fields_:
        if field_name.startswith("_pad"):
            continue
        val = getattr(buf, field_name)
        if isinstance(val, bytes):
            result[field_name] = val.decode("ascii", errors="replace").rstrip("\x00")
        elif hasattr(val, '__len__'):
            result[field_name] = list(val)
        else:
            result[field_name] = val
    return result


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

errors = []
pp = pprint.PrettyPrinter(indent=4)

# Struct sizes
cpu_size = ctypes.sizeof(perfstat_cpu_total_t)
part_size = ctypes.sizeof(perfstat_partition_total_t)
id_size = ctypes.sizeof(perfstat_id_t)
print(f"perfstat_cpu_total_t size:       {cpu_size} bytes")
print(f"perfstat_partition_total_t size: {part_size} bytes")
print(f"perfstat_id_t size:              {id_size} bytes")

if id_size != 64:
    errors.append(f"perfstat_id_t should be 64 bytes, got {id_size}")

# Load library
print("\nLoading libperfstat.a(shr_64.o)...")
try:
    lib = ctypes.CDLL("libperfstat.a(shr_64.o)")
except OSError as e:
    print(f"FAIL: Can't load libperfstat: {e}")
    print("(This is expected if you're not on AIX.)")
    sys.exit(1)

# --- perfstat_cpu_total ---

lib.perfstat_cpu_total.argtypes = [
    ctypes.POINTER(perfstat_id_t),
    ctypes.POINTER(perfstat_cpu_total_t),
    ctypes.c_int,
    ctypes.c_int,
]
lib.perfstat_cpu_total.restype = ctypes.c_int

cpu_buf = perfstat_cpu_total_t()
print("\nCalling perfstat_cpu_total()...")
ret = lib.perfstat_cpu_total(None, ctypes.byref(cpu_buf), ctypes.sizeof(cpu_buf), 1)

if ret != 1:
    errors.append(f"perfstat_cpu_total returned {ret}, expected 1")
else:
    cpu_result = struct_to_dict(cpu_buf, perfstat_cpu_total_t)
    cpu_result["_time"] = time.time()

    print(f"\n  ncpus (SMT threads): {cpu_result.get('ncpus')}")
    print(f"  ncpus_cfg:           {cpu_result.get('ncpus_cfg')}")
    print(f"  ncpus_high:          {cpu_result.get('ncpus_high')}")
    print(f"  description:         {cpu_result.get('description')}")
    ghz = cpu_result.get("processorHZ", 0) / 1_000_000_000
    print(f"  processorHZ:         {cpu_result.get('processorHZ')} ({ghz:.2f} GHz)")
    print(f"  user ticks:          {cpu_result.get('user')}")
    print(f"  sys ticks:           {cpu_result.get('sys')}")
    print(f"  idle ticks:          {cpu_result.get('idle')}")
    print(f"  wait ticks:          {cpu_result.get('wait')}")

    if cpu_result.get("ncpus", 0) < 1:
        errors.append(f"cpu ncpus is {cpu_result.get('ncpus')}, expected >= 1")
    if cpu_result.get("processorHZ", 0) == 0:
        errors.append("processorHZ is 0")

# --- perfstat_partition_total ---

lib.perfstat_partition_total.argtypes = [
    ctypes.POINTER(perfstat_id_t),
    ctypes.POINTER(perfstat_partition_total_t),
    ctypes.c_int,
    ctypes.c_int,
]
lib.perfstat_partition_total.restype = ctypes.c_int

part_buf = perfstat_partition_total_t()
print("\nCalling perfstat_partition_total()...")
ret = lib.perfstat_partition_total(None, ctypes.byref(part_buf), ctypes.sizeof(part_buf), 1)

if ret != 1:
    errors.append(f"perfstat_partition_total returned {ret}, expected 1")
else:
    part_result = struct_to_dict(part_buf, perfstat_partition_total_t)
    part_result["type_flags"] = decode_partition_type(part_result.pop("type"))
    part_result["_time"] = time.time()

    print(f"\n  LPAR name:             {part_result.get('name')}")
    print(f"  lpar_id:               {part_result.get('lpar_id')}")
    print(f"  online_cpus (virtual): {part_result.get('online_cpus')}")
    print(f"  max_cpus:              {part_result.get('max_cpus')}")
    print(f"  online_lcpus:          {part_result.get('online_lcpus')}")
    print(f"  smt_thrds:             {part_result.get('smt_thrds')}")
    print(f"  online_phys_cpus_sys:  {part_result.get('online_phys_cpus_sys')}")
    print(f"  max_phys_cpus_sys:     {part_result.get('max_phys_cpus_sys')}")
    print(f"  phys_cpus_pool:        {part_result.get('phys_cpus_pool')}")

    vp = part_result.get("online_cpus", 0)
    smt = part_result.get("smt_thrds", 0)
    lcpus = part_result.get("online_lcpus", 0)
    print(f"  -> {vp} VPs x {smt} SMT threads = {lcpus} logical CPUs")

    print(f"\n  SMT capable:           {part_result['type_flags'].get('smt_capable')}")
    print(f"  SMT enabled:           {part_result['type_flags'].get('smt_enabled')}")
    print(f"  Shared capable:        {part_result['type_flags'].get('shared_capable')}")
    print(f"  Shared enabled:        {part_result['type_flags'].get('shared_enabled')}")
    print(f"  Capped:                {part_result['type_flags'].get('capped')}")

    if part_result.get("online_cpus", 0) < 1:
        errors.append(f"partition online_cpus is {part_result.get('online_cpus')}, expected >= 1")

# --- Full dumps ---

print("\n" + "=" * 60)
print("perfstat_cpu_total full output:")
print("=" * 60)
if 'cpu_result' in dir():
    pp.pprint(cpu_result)

print("\n" + "=" * 60)
print("perfstat_partition_total full output:")
print("=" * 60)
if 'part_result' in dir():
    pp.pprint(part_result)

# --- Summary ---
print()
if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print("All checks passed.")
    sys.exit(0)
