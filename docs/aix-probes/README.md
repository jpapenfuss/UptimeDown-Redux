# AIX Probe Scripts

These scripts are manual exploration tools for validating libperfstat ctypes layouts and field mapping on real AIX hosts.

They are not part of the automated unit test suite.

## Scripts

- `aix_cpu_probe.py`: probes `perfstat_cpu_total` and `perfstat_partition_total`.
- `aix_disk_probe.py`: probes disk totals, per-disk stats, and `/etc/filesystems` + `statvfs` data.

## Usage

Run on an AIX 7.x host:

```bash
python3 docs/aix-probes/aix_cpu_probe.py
python3 docs/aix-probes/aix_disk_probe.py
```
