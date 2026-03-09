"""JSON schema validation for UptimeDown receiver payloads."""

import re
import logging

logger = logging.getLogger("receiver")


def validate_envelope(data: dict) -> list[str]:
    """
    Validate the top-level envelope structure.

    Required keys: system_id, collected_at, collection_errors, cloud
    Optional keys: cpustats, cpuinfo, cpus, memory, disks, disk_total,
                  filesystems, network

    Returns list of validation errors (empty = valid).
    """
    errors = []

    # Check it's a dict
    if not isinstance(data, dict):
        return ["Payload must be a JSON dict, not a list or scalar"]

    # Define allowed keys
    required_keys = {"system_id", "collected_at", "collection_errors", "cloud"}
    optional_keys = {
        "cpustats",
        "cpuinfo",
        "cpus",
        "memory",
        "disks",
        "disk_total",
        "filesystems",
        "network",
    }
    allowed_keys = required_keys | optional_keys

    # Check for unknown keys
    for key in data:
        if key not in allowed_keys:
            errors.append(f"Unknown top-level key: {key}")

    # Validate system_id
    if "system_id" not in data:
        errors.append("Missing required key: system_id")
    elif not isinstance(data["system_id"], str):
        errors.append(f"system_id must be str, got {type(data['system_id']).__name__}")
    elif not data["system_id"]:
        errors.append("system_id must be non-empty")
    elif not re.match(r"^[a-zA-Z0-9-]+$", data["system_id"]):
        errors.append(
            "system_id must contain only alphanumeric characters and hyphens"
        )
    elif len(data["system_id"]) > 64:
        errors.append("system_id must be at most 64 characters")

    # Validate collected_at
    if "collected_at" not in data:
        errors.append("Missing required key: collected_at")
    elif not isinstance(data["collected_at"], (int, float)):
        errors.append(
            f"collected_at must be int or float, got {type(data['collected_at']).__name__}"
        )
    elif isinstance(data["collected_at"], bool):
        errors.append("collected_at must be int or float, not bool")
    else:
        collected_at = data["collected_at"]
        if collected_at <= 0:
            errors.append("collected_at must be positive")
        elif collected_at < 1600000000:  # ~2020-09-13
            errors.append("collected_at is before year 2020 (too old)")
        elif collected_at > 2000000000:  # ~2033-05-18
            errors.append("collected_at is after year 2033 (too far in future)")

    # Validate collection_errors
    if "collection_errors" not in data:
        errors.append("Missing required key: collection_errors")
    elif not isinstance(data["collection_errors"], dict):
        errors.append(
            f"collection_errors must be dict, got {type(data['collection_errors']).__name__}"
        )

    # Validate cloud (required, always present, False or non-empty dict)
    if "cloud" not in data:
        errors.append("Missing required key: cloud")
    elif data["cloud"] is None:
        errors.append("cloud must be False or a dict, not None")
    elif not isinstance(data["cloud"], (bool, dict)):
        errors.append(
            f"cloud must be False or dict, got {type(data['cloud']).__name__}"
        )
    elif isinstance(data["cloud"], dict) and not data["cloud"]:
        errors.append("cloud dict must be non-empty (not empty dict)")

    return errors


def validate_cpustats(cpustats: dict) -> list[str]:
    """
    Validate CPU stats structure.

    Per-CPU entries (Linux): cpu0, cpu1, ... sub-dicts with tick fields
    Aggregate fields (both): user_ticks, sys_ticks, ctxt, etc. (int)
    Special fields:
    - loadavg_1, loadavg_5, loadavg_15: non-negative float
    - softirq: list of non-negative ints (Linux)
    - description: str (AIX)
    - ncpus_enumerated: non-negative int (AIX)

    Returns list of validation errors.
    """
    errors = []

    if not isinstance(cpustats, dict):
        errors.append(f"cpustats must be dict, got {type(cpustats).__name__}")
        return errors

    # Known per-CPU tick field names
    tick_fields = {
        "user_ticks",
        "sys_ticks",
        "idle_ticks",
        "nice_ticks",
        "iowait_ticks",
        "irq_ticks",
        "softirq_ticks",
        "steal_ticks",
        "guest_ticks",
        "guest_nice_ticks",
    }

    # Process each key
    for key, value in cpustats.items():
        # Per-CPU sub-dicts (Linux only)
        if re.match(r"^cpu\d+$", key):
            if not isinstance(value, dict):
                errors.append(
                    f"Per-CPU entry '{key}' must be dict, got {type(value).__name__}"
                )
                continue

            # Validate per-CPU dict
            for cpu_key, cpu_value in value.items():
                if cpu_key == "softirqs":
                    # softirqs is a dict mapping names to counts
                    if not isinstance(cpu_value, dict):
                        errors.append(
                            f"Per-CPU softirqs must be dict, got {type(cpu_value).__name__}"
                        )
                    else:
                        for irq_name, irq_count in cpu_value.items():
                            if not isinstance(irq_name, str):
                                errors.append(
                                    f"Per-CPU softirqs key must be str, got {type(irq_name).__name__}"
                                )
                            if not isinstance(irq_count, int) or isinstance(irq_count, bool):
                                errors.append(
                                    f"Per-CPU softirqs[{irq_name}] must be int, got {type(irq_count).__name__}"
                                )
                            elif irq_count < 0:
                                errors.append(
                                    f"Per-CPU softirqs[{irq_name}] must be non-negative"
                                )
                elif isinstance(cpu_value, int) and not isinstance(cpu_value, bool):
                    # Tick field (int, non-negative)
                    if cpu_value < 0:
                        errors.append(
                            f"Per-CPU {key}.{cpu_key} must be non-negative"
                        )
                elif isinstance(cpu_value, str):
                    errors.append(
                        f"Per-CPU {key}.{cpu_key} must be int or dict, got str"
                    )
                elif isinstance(cpu_value, float) and not isinstance(cpu_value, bool):
                    errors.append(
                        f"Per-CPU {key}.{cpu_key} must be int, got float"
                    )
                elif isinstance(cpu_value, bool):
                    errors.append(
                        f"Per-CPU {key}.{cpu_key} must be int, got bool"
                    )
                elif isinstance(cpu_value, (list, dict)) and cpu_key != "softirqs":
                    errors.append(
                        f"Per-CPU {key}.{cpu_key} has unexpected type {type(cpu_value).__name__}"
                    )

        # Special aggregate fields
        elif key in {"loadavg_1", "loadavg_5", "loadavg_15"}:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(
                    f"{key} must be int or float, got {type(value).__name__}"
                )
            elif value < 0:
                errors.append(f"{key} must be non-negative")

        elif key == "softirq":
            # softirq is a list of counts (Linux aggregate)
            if not isinstance(value, list):
                errors.append(
                    f"softirq must be list, got {type(value).__name__}"
                )
            else:
                for i, count in enumerate(value):
                    if not isinstance(count, int) or isinstance(count, bool):
                        errors.append(
                            f"softirq[{i}] must be int, got {type(count).__name__}"
                        )
                    elif count < 0:
                        errors.append(f"softirq[{i}] must be non-negative")

        elif key == "description":
            # AIX: str
            if not isinstance(value, str):
                errors.append(
                    f"description must be str, got {type(value).__name__}"
                )

        elif key == "ncpus_enumerated":
            # AIX: non-negative int
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(
                    f"ncpus_enumerated must be int, got {type(value).__name__}"
                )
            elif value < 0:
                errors.append("ncpus_enumerated must be non-negative")

        else:
            # All other top-level keys: must be non-negative int
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(
                    f"{key} must be int, got {type(value).__name__}"
                )
            elif value < 0:
                errors.append(f"{key} must be non-negative")

    return errors


def validate_cpuinfo(cpuinfo: dict) -> list[str]:
    """
    Validate CPU info (Linux /proc/cpuinfo cpu0 stanza).

    Known fields with expected types:
    - int: processor, cpu family, model, stepping, cpu cores, siblings, apicid, etc.
    - float: cpu MHz, bogomips
    - str: vendor_id, model name, microcode, fpu, etc.
    - list of str: flags, bugs

    Do NOT reject unknown keys. Validate known keys, accept any type for unknowns.

    Returns list of validation errors.
    """
    errors = []

    if not isinstance(cpuinfo, dict):
        errors.append(f"cpuinfo must be dict, got {type(cpuinfo).__name__}")
        return errors

    # Known int fields
    int_fields = {
        "processor",
        "cpu family",
        "model",
        "stepping",
        "cpu cores",
        "siblings",
        "apicid",
        "initial apicid",
        "core id",
        "physical id",
        "clflush size",
        "cache_alignment",
        "cpuid level",
    }

    # Known float fields
    float_fields = {"cpu MHz", "bogomips"}

    # Known list of str fields
    list_str_fields = {"flags", "bugs"}

    for key, value in cpuinfo.items():
        if key in int_fields:
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(
                    f"cpuinfo[{key}] must be int, got {type(value).__name__}"
                )
        elif key in float_fields:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(
                    f"cpuinfo[{key}] must be int or float, got {type(value).__name__}"
                )
        elif key in list_str_fields:
            if not isinstance(value, list):
                errors.append(
                    f"cpuinfo[{key}] must be list, got {type(value).__name__}"
                )
            else:
                for i, item in enumerate(value):
                    if not isinstance(item, str):
                        errors.append(
                            f"cpuinfo[{key}][{i}] must be str, got {type(item).__name__}"
                        )

    return errors


def validate_cpus(cpus: dict) -> list[str]:
    """
    Validate per-CPU enumeration (AIX only).

    Dict keyed by CPU name (cpu0, cpu1, ...). Each value is a perfstat_cpu_t dict
    with int and str fields.

    Validate: every value must be non-negative int or str. No floats, bools, lists, nested dicts.

    Returns list of validation errors.
    """
    errors = []

    if not isinstance(cpus, dict):
        errors.append(f"cpus must be dict, got {type(cpus).__name__}")
        return errors

    for cpu_name, cpu_dict in cpus.items():
        if not isinstance(cpu_dict, dict):
            errors.append(
                f"cpus[{cpu_name}] must be dict, got {type(cpu_dict).__name__}"
            )
            continue

        for field_name, field_value in cpu_dict.items():
            if isinstance(field_value, bool):
                errors.append(
                    f"cpus[{cpu_name}].{field_name} is bool (not allowed)"
                )
            elif isinstance(field_value, int):
                if field_value < 0:
                    errors.append(
                        f"cpus[{cpu_name}].{field_name} must be non-negative"
                    )
            elif isinstance(field_value, str):
                # str fields are OK (e.g., state)
                pass
            else:
                errors.append(
                    f"cpus[{cpu_name}].{field_name} must be int or str, got {type(field_value).__name__}"
                )

    return errors


def validate_cloud(cloud) -> list[str]:
    """
    Validate cloud metadata.

    Can be False (not on cloud) or a non-empty dict (metadata detected).
    Shallow check only: must be False or non-empty dict.

    Returns list of validation errors.
    """
    errors = []

    if cloud is False:
        # Valid: not on cloud
        pass
    elif isinstance(cloud, dict):
        if not cloud:
            errors.append("cloud dict must be non-empty if present")
    else:
        errors.append(
            f"cloud must be False or dict, got {type(cloud).__name__}"
        )

    return errors


def validate_memory(memory: dict) -> list[str]:
    """
    Validate memory stats.

    Top level has two keys: 'memory' (dict of byte counts) and 'slabs' (dict or False).

    Returns list of validation errors.
    """
    errors = []

    if not isinstance(memory, dict):
        errors.append(f"memory must be dict, got {type(memory).__name__}")
        return errors

    # Validate memory sub-dict
    if "memory" not in memory:
        errors.append("memory sub-dict missing 'memory' key")
    elif not isinstance(memory["memory"], dict):
        errors.append(
            f"memory['memory'] must be dict, got {type(memory['memory']).__name__}"
        )
    else:
        for key, value in memory["memory"].items():
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(
                    f"memory['memory'][{key}] must be int, got {type(value).__name__}"
                )
            elif value < 0:
                errors.append(f"memory['memory'][{key}] must be non-negative")

    # Validate slabs sub-dict
    if "slabs" not in memory:
        errors.append("memory sub-dict missing 'slabs' key")
    elif memory["slabs"] is False:
        # Valid: no slab info available
        pass
    elif isinstance(memory["slabs"], dict):
        for slab_name, slab_dict in memory["slabs"].items():
            if not isinstance(slab_dict, dict):
                errors.append(
                    f"memory['slabs'][{slab_name}] must be dict, got {type(slab_dict).__name__}"
                )
                continue

            for field_name, field_value in slab_dict.items():
                if not isinstance(field_value, int) or isinstance(field_value, bool):
                    errors.append(
                        f"memory['slabs'][{slab_name}].{field_name} must be int, got {type(field_value).__name__}"
                    )
                elif field_value < 0:
                    errors.append(
                        f"memory['slabs'][{slab_name}].{field_name} must be non-negative"
                    )
    else:
        errors.append(
            f"memory['slabs'] must be False or dict, got {type(memory['slabs']).__name__}"
        )

    return errors


def validate_disks(disks: dict) -> list[str]:
    """
    Validate disk devices dict.

    Keyed by device name. Each value is a dict with int and str fields.

    Validate: every value must be non-negative int or str. No floats, bools, lists, nested dicts.

    Returns list of validation errors.
    """
    errors = []

    if not isinstance(disks, dict):
        errors.append(f"disks must be dict, got {type(disks).__name__}")
        return errors

    for device_name, device_dict in disks.items():
        if not isinstance(device_dict, dict):
            errors.append(
                f"disks[{device_name}] must be dict, got {type(device_dict).__name__}"
            )
            continue

        for field_name, field_value in device_dict.items():
            if isinstance(field_value, bool):
                errors.append(
                    f"disks[{device_name}].{field_name} is bool (not allowed)"
                )
            elif isinstance(field_value, int):
                if field_value < 0:
                    errors.append(
                        f"disks[{device_name}].{field_name} must be non-negative"
                    )
            elif isinstance(field_value, str):
                # str fields are OK (e.g., description, vgname, adapter)
                pass
            else:
                errors.append(
                    f"disks[{device_name}].{field_name} must be int or str, got {type(field_value).__name__}"
                )

    return errors


def validate_disk_total(disk_total: dict) -> list[str]:
    """
    Validate AIX disk_total (aggregate across all disks).

    Every value must be non-negative int. No str, float, bool, nested dicts.

    Returns list of validation errors.
    """
    errors = []

    if not isinstance(disk_total, dict):
        errors.append(f"disk_total must be dict, got {type(disk_total).__name__}")
        return errors

    for field_name, field_value in disk_total.items():
        if isinstance(field_value, bool):
            errors.append(f"disk_total.{field_name} is bool (not allowed)")
        elif isinstance(field_value, int):
            if field_value < 0:
                errors.append(f"disk_total.{field_name} must be non-negative")
        else:
            errors.append(
                f"disk_total.{field_name} must be int, got {type(field_value).__name__}"
            )

    return errors


def validate_filesystems(filesystems: dict) -> list[str]:
    """
    Validate filesystems dict.

    Keyed by mountpoint. Each value has:
    - Required: mountpoint (str), dev (str), vfs (str), mounted (bool), options (str)
    - AIX-specific: log (str), mount (str), type (str), account (str)
    - When mounted=False: above fields only
    - When mounted=True: above + statvfs fields (f_bsize, f_blocks, etc.) and percentages

    Returns list of validation errors.
    """
    errors = []

    if not isinstance(filesystems, dict):
        errors.append(f"filesystems must be dict, got {type(filesystems).__name__}")
        return errors

    for mountpoint, fs_dict in filesystems.items():
        if not isinstance(fs_dict, dict):
            errors.append(
                f"filesystems[{mountpoint}] must be dict, got {type(fs_dict).__name__}"
            )
            continue

        # Check required fields
        required_fields = {"mountpoint", "dev", "vfs", "mounted", "options"}
        for field in required_fields:
            if field not in fs_dict:
                errors.append(
                    f"filesystems[{mountpoint}] missing required field: {field}"
                )

        # Validate mounted type (must be bool)
        if "mounted" in fs_dict:
            if not isinstance(fs_dict["mounted"], bool):
                errors.append(
                    f"filesystems[{mountpoint}].mounted must be bool, got {type(fs_dict['mounted']).__name__}"
                )

        # Validate string fields
        for field in {"mountpoint", "dev", "vfs", "options", "log", "mount", "type", "account"}:
            if field in fs_dict:
                if not isinstance(fs_dict[field], str):
                    errors.append(
                        f"filesystems[{mountpoint}].{field} must be str, got {type(fs_dict[field]).__name__}"
                    )

        # If mounted, validate statvfs fields
        if "mounted" in fs_dict and fs_dict["mounted"] is True:
            int_fields = {
                "f_bsize",
                "f_frsize",
                "f_blocks",
                "f_bfree",
                "f_bavail",
                "f_files",
                "f_ffree",
                "f_favail",
                "bytes_total",
                "bytes_free",
                "bytes_available",
                "f_flag",
                "f_namemax",
            }
            pct_fields = {"pct_used", "pct_free", "pct_available", "pct_reserved"}

            # Validate int fields
            for field in int_fields:
                if field not in fs_dict:
                    errors.append(
                        f"filesystems[{mountpoint}] (mounted=True) missing {field}"
                    )
                elif not isinstance(fs_dict[field], int) or isinstance(fs_dict[field], bool):
                    errors.append(
                        f"filesystems[{mountpoint}].{field} must be int, got {type(fs_dict[field]).__name__}"
                    )
                elif fs_dict[field] < 0:
                    errors.append(
                        f"filesystems[{mountpoint}].{field} must be non-negative"
                    )

            # Validate percentage fields
            for field in pct_fields:
                if field not in fs_dict:
                    errors.append(
                        f"filesystems[{mountpoint}] (mounted=True) missing {field}"
                    )
                elif not isinstance(fs_dict[field], (int, float)) or isinstance(fs_dict[field], bool):
                    errors.append(
                        f"filesystems[{mountpoint}].{field} must be float, got {type(fs_dict[field]).__name__}"
                    )
                elif fs_dict[field] < 0 or fs_dict[field] > 100:
                    errors.append(
                        f"filesystems[{mountpoint}].{field} must be between 0.0 and 100.0"
                    )

    return errors


def validate_network(network: dict) -> list[str]:
    """
    Validate network interfaces dict.

    Keyed by interface name. Each value is a dict with counter fields (int) and
    metadata fields (int or str).

    Platform-specific fields:
    - Linux: 16 counter fields (ibytes, ipackets, ...), operstate (str), mtu (int), type (int), speed_mbps (int)
    - AIX: smaller counter set, no operstate, has description (str)

    Counter fields must be non-negative int. Metadata str fields (operstate, description) are OK.
    Any other str-valued field is an error. No floats, bools, lists, nested dicts.

    Returns list of validation errors.
    """
    errors = []

    if not isinstance(network, dict):
        errors.append(f"network must be dict, got {type(network).__name__}")
        return errors

    # Known counter fields (must be int)
    counter_fields = {
        "ibytes",
        "ipackets",
        "ierrors",
        "idrop",
        "ififo",
        "iframe",
        "icompressed",
        "imulticast",
        "obytes",
        "opackets",
        "oerrors",
        "odrop",
        "ofifo",
        "collisions",
        "ocarrier",
        "ocompressed",
        "if_arpdrops",
    }

    # Known metadata str fields (can be str)
    str_fields = {"operstate", "description"}

    # Known metadata int fields (must be int)
    int_metadata_fields = {"mtu", "type", "speed_mbps"}

    for if_name, if_dict in network.items():
        if not isinstance(if_dict, dict):
            errors.append(
                f"network[{if_name}] must be dict, got {type(if_dict).__name__}"
            )
            continue

        for field_name, field_value in if_dict.items():
            if isinstance(field_value, bool):
                errors.append(
                    f"network[{if_name}].{field_name} is bool (not allowed)"
                )
            elif field_name in counter_fields:
                # Counter fields must be int
                if not isinstance(field_value, int) or isinstance(field_value, bool):
                    errors.append(
                        f"network[{if_name}].{field_name} must be int, got {type(field_value).__name__}"
                    )
                elif field_value < 0:
                    errors.append(
                        f"network[{if_name}].{field_name} must be non-negative"
                    )
            elif field_name in int_metadata_fields:
                # Metadata int fields
                if not isinstance(field_value, int) or isinstance(field_value, bool):
                    errors.append(
                        f"network[{if_name}].{field_name} must be int, got {type(field_value).__name__}"
                    )
                elif field_value < 0:
                    errors.append(
                        f"network[{if_name}].{field_name} must be non-negative"
                    )
            elif field_name in str_fields:
                # Metadata str fields (operstate, description)
                if not isinstance(field_value, str):
                    errors.append(
                        f"network[{if_name}].{field_name} must be str, got {type(field_value).__name__}"
                    )
            elif isinstance(field_value, int):
                # Unknown field with int value: OK (could be future field)
                if field_value < 0:
                    errors.append(
                        f"network[{if_name}].{field_name} must be non-negative"
                    )
            elif isinstance(field_value, str):
                # Unknown field with str value: ERROR (only known str fields are operstate/description)
                errors.append(
                    f"network[{if_name}].{field_name} is str but only 'operstate' and 'description' are allowed str fields"
                )
            else:
                errors.append(
                    f"network[{if_name}].{field_name} must be int or str, got {type(field_value).__name__}"
                )

    return errors


def validate_payload(data: dict) -> list[str]:
    """
    Validate complete payload.

    Orchestrates all validators. Returns envelope errors first, then section errors.
    Stops after envelope validation if errors found (don't validate sections on bad envelope).

    Returns list of all validation errors (empty = valid).
    """
    errors = validate_envelope(data)
    if errors:
        return errors

    # Validate each section if present
    if "cpustats" in data and isinstance(data["cpustats"], dict):
        errors.extend(validate_cpustats(data["cpustats"]))
    if "cpuinfo" in data and isinstance(data["cpuinfo"], dict):
        errors.extend(validate_cpuinfo(data["cpuinfo"]))
    if "cpus" in data and isinstance(data["cpus"], dict):
        errors.extend(validate_cpus(data["cpus"]))
    if "cloud" in data:
        errors.extend(validate_cloud(data["cloud"]))
    if "memory" in data and isinstance(data["memory"], dict):
        errors.extend(validate_memory(data["memory"]))
    if "disks" in data and isinstance(data["disks"], dict):
        errors.extend(validate_disks(data["disks"]))
    if "disk_total" in data and isinstance(data["disk_total"], dict):
        errors.extend(validate_disk_total(data["disk_total"]))
    if "filesystems" in data and isinstance(data["filesystems"], dict):
        errors.extend(validate_filesystems(data["filesystems"]))
    if "network" in data and isinstance(data["network"], dict):
        errors.extend(validate_network(data["network"]))

    return errors
