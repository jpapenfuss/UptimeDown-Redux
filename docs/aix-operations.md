# AIX Monitoring Operations Guide

This document covers operational aspects of running the UptimeDown monitoring system on AIX, including troubleshooting, understanding dynamic CPU changes, and database integration.

## Quick Start

### Running on AIX

```bash
# Copy the monitoring code to AIX system
scp -r monitoring root@aix-system:/opt/uptimedown/

# Run single collection
cd /opt/uptimedown
python3 -m monitoring

# Run with DEBUG logging (saves JSON dumps)
# Edit config.ini:
# [logging]
# level = DEBUG

# Then run again
python3 -m monitoring
```

## CPU Monitoring on AIX

### Understanding the Output

The `cpustats` object contains two CPU count fields:

```json
{
  "cpustats": {
    "ncpus": 12,
    "ncpus_enumerated": 16,
    "user_ticks": 98954,
    "sys_ticks": 335684,
    ...
  },
  "cpus": {
    "cpu0": { "user": 24476, "sys": 119351, ... },
    "cpu1": { "user": 12257, "sys": 24851, ... },
    ...
    "cpu15": { "user": 6462, "sys": 17828, ... }
  }
}
```

**Interpreting the counts:**
- `ncpus` — What `perfstat_cpu_total()` reported at collection time
- `ncpus_enumerated` — Actual CPU count from enumeration (usually more reliable)
- `cpus` — Dict keyed by CPU name; count of keys = `ncpus_enumerated`

### Dynamic CPU Changes (SMT Transitions)

AIX supports **Simultaneous Multi-Threading (SMT)** at runtime. Changing SMT thread count dynamically hotplugs CPUs:

```bash
# Current SMT status
lsattr -El proc0 | grep smt

# Change SMT threads from 4 to 8
smtctl -t 8

# Change back to 4
smtctl -t 4

# Or disable SMT entirely
smtctl -m off

# Enable with recommended setting
smtctl -m recommended
```

### Expected Behavior During SMT Changes

When SMT thread count changes, you will see:

```
Time range: < 1-2 seconds

ncpus:              8 → 9 → 12 → 15 → 14 → 11 → 8 (fluctuating)
ncpus_enumerated:   8 → 8 → 8  → 8  → 8  → 8  → 8 (stable)

Then after transition completes:

ncpus:              16 (matches enumerated)
ncpus_enumerated:   16
```

**Why this happens:**
- Kernel hotplug process takes ~100-500ms
- `perfstat_cpu_total()` captures ncpus at call time
- CPU enumeration may lag/lead by milliseconds
- Both values are valid; they just measure at slightly different moments

### Handling in Database

Your database schema should **expect ncpus to vary per sample**:

✅ **Good schema:**
```sql
CREATE TABLE cpu_stats (
  id BIGINT PRIMARY KEY,
  system_id VARCHAR(64),
  collected_at TIMESTAMP,
  ncpus_reported INT,       -- May fluctuate
  ncpus_enumerated INT,     -- More stable
  user_ticks BIGINT,
  sys_ticks BIGINT,
  -- ... other fields
  INDEX idx_system_time (system_id, collected_at)
);

CREATE TABLE cpu_detail (
  id BIGINT PRIMARY KEY,
  stats_id BIGINT,          -- FK to cpu_stats
  cpu_name VARCHAR(16),     -- cpu0, cpu1, etc.
  state VARCHAR(16),        -- online, offline
  user BIGINT,
  sys BIGINT,
  -- ... other fields
  INDEX idx_stats (stats_id)
);

-- NO constraint: (system_id, collected_at) must match CPU count
-- CPU count can vary per sample during transitions
```

❌ **Problematic schema:**
```sql
-- Don't do this:
ALTER TABLE cpu_detail
  ADD CONSTRAINT cpu_count_check
  FOREIGN KEY (stats_id)
  CHECK (count(distinct cpu_name) == ncpus);
```

## Troubleshooting

### No Data Collected

**Symptom:** Script runs but produces no output or minimal output.

**Checklist:**
```bash
# 1. Verify libperfstat is available
ls -la /usr/include/libperfstat.h
nm -D libperfstat.a(shr_64.o) | grep perfstat_cpu

# 2. Check Python ctypes can load library
python3 -c "import ctypes; lib = ctypes.CDLL('libperfstat.a(shr_64.o)'); print('OK')"

# 3. Check permissions
whoami  # Should be root or in system group
id      # Verify access

# 4. Check AIX version
oslevel  # Should be 7.1+
```

### CPU Count Mismatch Alerts

If your monitoring system triggers alerts for ncpus mismatches:

```
Alert: ncpus_reported (8) != ncpus_enumerated (16)
```

**This is expected during SMT transitions.** Solutions:

**Option 1:** Ignore ncpus_reported, use ncpus_enumerated
```sql
SELECT ncpus_enumerated FROM cpu_stats WHERE ...
```

**Option 2:** Only alert if mismatch persists > 5 seconds
```sql
WITH recent_samples AS (
  SELECT
    system_id,
    collected_at,
    ncpus_reported,
    ncpus_enumerated,
    LAG(ncpus_enumerated) OVER (ORDER BY collected_at) as prev_enum
  FROM cpu_stats
  WHERE system_id = ?
    AND collected_at > now() - interval 5 seconds
)
SELECT * FROM recent_samples
WHERE ncpus_reported != ncpus_enumerated
  AND prev_enum != ncpus_enumerated;  -- Consistent enum, so not mid-transition
```

**Option 3:** Track SMT transitions
```python
# In application logic
prev_ncpus = None
for sample in samples:
    curr_ncpus = sample['ncpus_enumerated']
    if prev_ncpus and curr_ncpus != prev_ncpus:
        print(f"SMT transition detected: {prev_ncpus} -> {curr_ncpus} CPUs")
    prev_ncpus = curr_ncpus
```

### CPU State Field Always "offline"

**Symptom:** `cpu.state` is "offline" for all CPUs even when they should be online.

**Cause:** Byte decoding issue.

**Fix in code:**
```python
# Check how state field is coming in
state_val = cpu.state  # What type is this?
if isinstance(state_val, bytes):
    state_byte = state_val[0]
elif isinstance(state_val, int):
    state_byte = state_val
else:
    state_byte = ord(state_val) if state_val else 0

# Debug: log raw value
logger.debug(f"CPU {name} raw state: {repr(state_val)} -> {state_byte}")

# Online is typically > 0
state_str = "online" if state_byte > 0 else "offline"
```

### Load Average Looks Too High

**Symptom:** Load average in JSON shows values like `1572480` instead of `24.0`.

**Cause:** Forgot to divide by FSCALE (65536).

**Fix:**
```python
# Wrong:
loadavg_1 = result["loadavg_1"]  # 1572480

# Right:
FSCALE = 1 << 16  # 65536
loadavg_1 = result["loadavg_1"] / FSCALE  # 24.0
```

Check [aix-perfstat.md](aix-perfstat.md#load-average-scaling) for details.

### Intermittent Collection Failures

**Symptom:** Occasionally `cpus` dict is empty or False.

**Causes:**
1. Transient perfstat library issue
2. System under extreme load during collection
3. SMT transition mid-collection

**Mitigation:**
```python
# Check for failures in application code
if not mycpu.cpus or mycpu.cpus is False:
    logger.warning("CPU enumeration failed, retrying...")
    # Option 1: Retry immediately
    time.sleep(0.1)
    mycpu.UpdateValues()

    # Option 2: Skip this sample
    # (daemon will retry next interval)

    # Option 3: Report partial data
    if mycpu.cpustat_values and mycpu.cpustat_values is not False:
        # Still have aggregate stats
        pass
```

### High CPU Usage During Collection

**Symptom:** Collection takes >50ms and impacts system.

**Checklist:**
1. **CPU count:** More CPUs = longer collection
   - 8 CPUs: ~5-10ms
   - 64 CPUs: ~30-50ms
   - 256 CPUs: ~100-200ms

2. **Load:** High system load may slow perfstat calls

3. **Frequency:** Collection interval too short
   - Minimum enforced: 5 seconds (see config.ini)
   - Recommended: 30-60 seconds for production

4. **JSON generation:** Large with 100+ CPUs
   - Use streaming JSON for large systems
   - Consider separating aggregate and per-CPU into separate endpoints

### Debugging with DEBUG Logging

Enable DEBUG logging to get JSON dumps:

```ini
# monitoring/config.ini
[logging]
level = DEBUG
```

Dumps will be written as `{uuid}-{timestamp}.json` files:

```bash
# Find recent dumps
ls -lh *.json | tail -5

# Inspect a dump
python3 -m json.tool < 12345678-1234567890.json | less

# Compare samples during SMT change
diff <(jq .cpustats < sample1.json) <(jq .cpustats < sample2.json)
```

## Performance Tuning

### Collection Interval

```ini
[daemon]
# Default 60 seconds is good for most systems
# Minimum enforced: 5 seconds
# Very high frequency (< 5s) not recommended due to:
# - perfstat call overhead
# - Network I/O for shipping data
# - Database write load
run_interval = 60
```

### Daemon Mode

```ini
[daemon]
# Run N iterations then stop (useful for cron)
max_iterations = 10

# Run indefinitely (useful for systemd service)
# max_iterations commented out
```

### Limiting Network/DB Load

For systems with many CPUs, consider:

1. **Reduce collection frequency:**
   ```ini
   run_interval = 300  # 5 minutes for large systems
   ```

2. **Separate aggregate and detail:**
   - Ship cpustats to one database
   - Ship cpus (per-CPU) to time-series DB only (optional)

3. **Sample per-CPU data:**
   ```python
   # Collect all, but only store every Nth sample
   if iteration % 5 == 0:
       store_cpu_detail(cpu.cpus)
   ```

## AIX-Specific Considerations

### LPAR Mode

If running in an LPAR, pay special attention to PURR/SPURR metrics:

```json
{
  "idle_donated_purr": 269126347920988,    # Cycles donated (idle)
  "busy_stolen_purr": 33865352,            # Cycles stolen (busy)
  "puser_spurr": 252210712528,             # User-mode SPURR cycles
}
```

These help answer:
- How much capacity is this LPAR actually getting?
- Is the hypervisor stealing significant cycles?
- Are we donation-heavy (underutilized)?

### Virtual Processors

On shared processor LPARs, `ncpus` may be fractional in terms of actual hardware. The `processor_hz` field tells the actual CPU frequency:

```python
virtual_cpus = data['cpustats']['ncpus']
freq_hz = data['cpustats']['processor_hz']
# Capacity = virtual_cpus * freq_hz (in theoretical cycles per second)
```

### AIX Versions

Tested on:
- AIX 7.1 ✓
- AIX 7.2 ✓
- AIX 7.3 ✓

Should work on 6.1+ (perfstat available since AIX 6.1).

## Integration with External Systems

### Time Series Database (InfluxDB, Prometheus, etc.)

```python
# Example for Prometheus
from prometheus_client import Gauge

cpu_user = Gauge('aix_cpu_user_ticks', 'User CPU ticks', ['system_id'])
cpu_sys = Gauge('aix_cpu_sys_ticks', 'System CPU ticks', ['system_id'])

# After collection
cpu_user.labels(system_id=data['system_id']).set(
    data['cpustats']['user_ticks']
)
cpu_sys.labels(system_id=data['system_id']).set(
    data['cpustats']['sys_ticks']
)
```

### Relational Database (PostgreSQL, etc.)

See schema recommendations in [Handling in Database](#handling-in-database) section.

### Structured Logging

```python
import json

# Log each collection as JSON
logger.info(json.dumps({
    "event": "cpu_collection",
    "system_id": data['system_id'],
    "collected_at": data['collected_at'],
    "ncpus": data['cpustats']['ncpus_enumerated'],
    "user_ticks": data['cpustats']['user_ticks'],
    "load_avg": data['cpustats']['loadavg_1'] / 65536.0,
}))
```

## References

- AIX Performance Tools: `man perfstat`
- IBM Knowledge Center: [AIX Performance Tuning](https://www.ibm.com/support/knowledgecenter/ssw_aix)
- libperfstat header: `/usr/include/libperfstat.h`
- SMT Configuration: `man smtctl`
