"""
Transform validated JSON sections into SQL row dicts.

Each function takes a JSON section dict, host_id, and collected_at,
and returns row-dicts with column names matching SCHEMA.md.
"""

import json


# Schema column allowlists

_CPU_STATS_COLUMNS = frozenset({
    'user_ticks', 'sys_ticks', 'idle_ticks', 'iowait_ticks',
    'nice_ticks', 'irq_ticks', 'softirq_ticks', 'steal_ticks',
    'guest_ticks', 'guest_nice_ticks',
    'ctxt', 'btime', 'processes', 'procs_running', 'procs_blocked',
    'ncpus', 'ncpus_cfg',
    'syscall', 'sysread', 'syswrite', 'sysfork', 'sysexec',
    'readch', 'writech', 'devintrs', 'softintrs',
    'runque', 'swpque', 'runocc', 'swpocc',
    'loadavg_1', 'loadavg_5', 'loadavg_15',
    'idle_donated_purr', 'idle_donated_spurr',
    'busy_donated_purr', 'busy_donated_spurr',
    'idle_stolen_purr', 'idle_stolen_spurr',
    'busy_stolen_purr', 'busy_stolen_spurr',
    'puser_spurr', 'psys_spurr', 'pidle_spurr', 'pwait_spurr',
})

_CPU_INFO_COLUMNS = frozenset({
    'cpu_count', 'cpu_count_cfg', 'vendor_id', 'model_name', 'cpu_family',
    'model', 'stepping', 'cpu_cores', 'siblings', 'cpu_mhz', 'cache_size',
    'flags', 'description', 'processor_hz',
})

_MEMORY_COLUMNS = frozenset({
    'mem_total', 'mem_free', 'mem_available', 'mem_cached',
    'swap_total', 'swap_free', 'buffers', 'swap_cached',
    'active', 'inactive', 'dirty', 'writeback', 'slab',
    's_reclaimable', 's_unreclaim', 'anon_pages', 'mapped',
    'huge_pages_total', 'huge_pages_free', 'huge_page_size',
})

_MEMORY_RENAMES = {'cached': 'mem_cached', 'hugepagesize': 'huge_page_size'}

_SLAB_COLUMNS = frozenset({
    'active_objs', 'num_objs', 'objsize', 'objperslab', 'pagesperslab',
    'limit', 'batchcount', 'sharedfactor', 'active_slabs', 'num_slabs', 'sharedavail',
})

_FS_DIRECT_COLS = frozenset({
    'mountpoint', 'dev', 'vfs', 'options',
    'bytes_total', 'bytes_free', 'bytes_available',
    'pct_used', 'pct_available', 'pct_free', 'pct_reserved',
    'f_files', 'f_ffree', 'f_favail',
    # AIX-renamed columns
    'fs_log', 'mount_auto', 'fs_type',
})

_FS_AIX_RENAMES = {'log': 'fs_log', 'mount': 'mount_auto', 'type': 'fs_type'}

_LINUX_DISK_DIRECT_COLS = frozenset({
    'major', 'minor',
    'read_ios', 'read_merge', 'read_sectors', 'read_ticks',
    'write_ios', 'write_merges', 'write_sectors', 'write_ticks',
    'in_flight', 'total_io_ticks', 'total_time_in_queue',
    'discard_ios', 'discard_merges', 'discard_sectors', 'discard_ticks',
    'flush_ios', 'flush_ticks',
})

_LINUX_DISK_SYSFS_FIELDS = frozenset({
    'size_bytes', 'rotational', 'physical_block_size',
    'logical_block_size', 'scheduler', 'discard_granularity',
})

_AIX_DISK_COLUMNS = frozenset({
    'description', 'vgname', 'adapter',
    'size_bytes', 'free_bytes', 'bsize',
    'xfers', 'read_ios', 'write_ios', 'read_blocks', 'write_blocks',
    'read_ticks', 'write_ticks', 'time', 'qdepth',
    'q_full', 'q_sampled', 'paths_count',
    'min_rserv', 'max_rserv', 'min_wserv', 'max_wserv',
    'rtimeout', 'wtimeout', 'rfailed', 'wfailed',
    'wq_depth', 'wq_sampled', 'wq_time', 'wq_min_time', 'wq_max_time',
    'wpar_id', 'dk_type',
})

_AIX_DISK_TOTAL_COLUMNS = frozenset({
    'ndisks', 'size_bytes', 'free_bytes', 'xfers',
    'read_ios', 'write_ios', 'read_blocks', 'write_blocks',
    'read_ticks', 'write_ticks', 'time',
    'min_rserv', 'max_rserv', 'rtimeout', 'rfailed',
    'min_wserv', 'max_wserv', 'wtimeout', 'wfailed',
    'wq_depth', 'wq_time', 'wq_min_time', 'wq_max_time',
})

_NET_COLUMNS = frozenset({
    'ibytes', 'ipackets', 'ierrors', 'obytes', 'opackets', 'oerrors',
    'idrop', 'odrop', 'mtu', 'speed_mbps', 'type',
    'operstate',        # Linux only
    'description',      # AIX only
})


def transform_cpu_stats(cpustats, host_id, collected_at):
    """Extract aggregate CPU stats.

    Returns one row-dict for cpu_stats table. Per-CPU keys (cpu0, cpu1, ...)
    and list-valued keys (softirq) are excluded.
    Output key: collected_at.
    """
    row = {'host_id': host_id, 'collected_at': collected_at}

    for key, value in cpustats.items():
        # Skip dict values (per-CPU entries) and list values (softirq)
        if isinstance(value, (dict, list)):
            continue

        # Include only schema columns
        if key in _CPU_STATS_COLUMNS:
            row[key] = value

    return row


def transform_cpu_info(cpuinfo, host_id, collected_at, cpu_count=None):
    """Extract CPU hardware info.

    Returns one row-dict for cpu_info table.
    Applies key renames and list→string conversions for flags/bugs.
    Output key: recorded_at (not collected_at).
    """
    row = {'host_id': host_id, 'recorded_at': collected_at}

    if cpu_count is not None:
        row['cpu_count'] = cpu_count

    # Renames for space-separated cpuinfo keys
    renames = {
        'cpu family': 'cpu_family',
        'model name': 'model_name',
        'cpu MHz': 'cpu_mhz',
    }

    for key, value in cpuinfo.items():
        # Apply renames
        col_key = renames.get(key, key)

        # Convert flags/bugs lists to space-separated strings
        if key == 'flags' and isinstance(value, list):
            row['flags'] = ' '.join(value)
            continue
        if key == 'bugs' and isinstance(value, list):
            # 'bugs' is not in schema, so we skip it after converting to string
            continue

        # Include only schema columns
        if col_key in _CPU_INFO_COLUMNS:
            row[col_key] = value

    return row


def transform_memory(memory_inner, host_id, collected_at):
    """Extract memory stats.

    Returns one row-dict for memory table.
    memory_inner is data["memory"]["memory"] (the inner dict).
    Applies renames and bundles unknowns into extra_json.
    Output key: collected_at.
    """
    row = {'host_id': host_id, 'collected_at': collected_at}
    extras = {}

    for key, value in memory_inner.items():
        # Apply renames
        col_key = _MEMORY_RENAMES.get(key, key)

        if col_key in _MEMORY_COLUMNS:
            row[col_key] = value
        else:
            # Unknown key goes to extra_json
            extras[key] = value

    # Bundle extras into extra_json
    if extras:
        row['extra_json'] = json.dumps(extras)
    else:
        row['extra_json'] = None

    return row


def transform_memory_slabs(slabs, host_id, collected_at):
    """Returns list of row-dicts for memory_slabs table (one per slab).

    Returns empty list if slabs is False.
    """
    if slabs is False:
        return []

    rows = []
    for slab_name, slab_dict in slabs.items():
        row = {
            'host_id': host_id,
            'collected_at': collected_at,
            'slab_name': slab_name,
        }

        # Filter slab dict to schema columns
        for key, value in slab_dict.items():
            if key in _SLAB_COLUMNS:
                row[key] = value

        rows.append(row)

    return rows


def transform_filesystems(filesystems, host_id, collected_at):
    """Returns list of row-dicts for filesystems table (one per mountpoint).

    Includes ALL entries regardless of mounted status.
    Derives fs_rdonly from f_flag & 1 when mounted.
    Applies AIX renames.
    Drops f_flag, f_namemax, account, mounted (converted to int).
    """
    rows = []

    for mountpoint, entry in filesystems.items():
        row = {
            'host_id': host_id,
            'collected_at': collected_at,
            'mountpoint': mountpoint,
            'mounted': 1 if entry.get('mounted') else 0,
        }

        # Derive fs_rdonly from f_flag & 1 when present
        if entry.get('mounted'):
            f_flag = entry.get('f_flag')
            row['fs_rdonly'] = (f_flag & 1) if f_flag is not None else 0
        else:
            row['fs_rdonly'] = 0

        # Apply AIX renames and copy direct columns
        for key, value in entry.items():
            # Skip keys we already handled or are dropping
            if key in ('mountpoint', 'mounted', 'f_flag', 'f_namemax', 'account'):
                continue

            # Apply AIX renames
            col_key = _FS_AIX_RENAMES.get(key, key)

            # Include only schema columns
            if col_key in _FS_DIRECT_COLS:
                row[col_key] = value

        rows.append(row)

    return rows


def transform_disks_linux(disks, host_id, collected_at):
    """Returns list of row-dicts for disk_devices_linux table.

    Bundles sysfs fields into extra_json.
    """
    rows = []

    for device_name, device_dict in disks.items():
        row = {
            'host_id': host_id,
            'collected_at': collected_at,
            'name': device_name,
        }

        sysfs_fields = {}

        for key, value in device_dict.items():
            if key in _LINUX_DISK_DIRECT_COLS:
                row[key] = value
            elif key in _LINUX_DISK_SYSFS_FIELDS:
                sysfs_fields[key] = value

        # Bundle sysfs fields into extra_json
        if sysfs_fields:
            row['extra_json'] = json.dumps(sysfs_fields)
        else:
            row['extra_json'] = None

        rows.append(row)

    return rows


def transform_disks_aix(disks, disk_total, host_id, collected_at):
    """Returns (list of disk_devices_aix row-dicts, one disk_total row-dict)."""
    disk_rows = []

    for device_name, device_dict in disks.items():
        row = {
            'host_id': host_id,
            'collected_at': collected_at,
            'name': device_name,
        }

        for key, value in device_dict.items():
            if key in _AIX_DISK_COLUMNS:
                row[key] = value

        disk_rows.append(row)

    # Build disk_total row
    total_row = {
        'host_id': host_id,
        'collected_at': collected_at,
    }

    for key, value in disk_total.items():
        if key in _AIX_DISK_TOTAL_COLUMNS:
            total_row[key] = value

    return disk_rows, total_row


def transform_network(network, host_id, collected_at):
    """Returns list of row-dicts for net_interfaces table (one per interface).

    Each row-dict contains only fields present in input (no defaulting to NULL).
    Output key: collected_at.
    """
    rows = []

    for iface_name, iface_dict in network.items():
        row = {
            'host_id': host_id,
            'collected_at': collected_at,
            'iface': iface_name,
        }

        for key, value in iface_dict.items():
            if key in _NET_COLUMNS:
                row[key] = value

        rows.append(row)

    return rows
