# UptimeDown HTTP Receiver — Implementation Plan

This document is a step-by-step guide for building the HTTP ingestion service.
Each phase is self-contained and testable. Complete each phase fully (including
tests) before moving to the next. **Do not skip ahead.**

**Target environment**: Any OS with Python 3 (Linux, AIX, macOS, etc.). Receiver is
pure Python stdlib; external dependencies are database drivers only.

**Database support**:
- **Primary**: PostgreSQL (`psycopg2` or `psycopg`)
- **Alternative**: MariaDB (`mysql.connector`)
- **Development/prototyping**: SQLite (`sqlite3`, stdlib)

The receiver logic is database-agnostic; Phase 5 (db.py) implements driver-specific
connection and parameterization.

---

## Architecture Overview

```
Agent (monitoring box)                    Receiver (central server)
┌──────────────┐    HTTPS POST /ingest    ┌──────────────────────┐
│ __main__.py  │ ────────────────────────▶ │  receiver/server.py  │
│ JSON output  │    Content-Type: json     │  ├─ auth check       │
└──────────────┘    Authorization: Bearer  │  ├─ JSON parse       │
                                           │  ├─ envelope valid.  │
                                           │  ├─ section valid.   │
                                           │  ├─ schema transform │
                                           │  └─ DB insert        │
                                           └──────────────────────┘
```

**Package layout** (all new files):
```
receiver/
    __init__.py
    server.py          — HTTP server (Phase 1)
    auth.py            — Authentication (Phase 2)
    validate.py        — JSON structure + type validation (Phase 3)
    transform.py       — Key renames, extra_json bundling, derived fields (Phase 4)
    db.py              — Database connection + insert logic (Phase 5, future)
tests/
    test_receiver_server.py
    test_receiver_auth.py
    test_receiver_validate.py
    test_receiver_transform.py
```

---

## Phase 1: HTTP Server Skeleton

**Goal**: Accept POST requests at `/ingest`, parse JSON body, return status codes.
No validation beyond "is it JSON?" No auth. No database.

### File: `receiver/server.py`

Build on `http.server.HTTPServer` + `BaseHTTPRequestHandler`. Do NOT use Flask,
FastAPI, or any framework.

**Requirements**:

1. Route logic (apply in every `do_*` method):
   - `/health`: `GET` → 200. All other methods → `405 Method Not Allowed`.
   - `/ingest`: `POST` → process. All other methods → `405 Method Not Allowed`.
   - Any other path: `404 Not Found` regardless of method.

2. Require `Content-Type: application/json`. Return `415 Unsupported Media Type`
   if missing or wrong.

3. Enforce a maximum request body size. Hardcode `MAX_BODY_BYTES = 10 * 1024 * 1024`
   (10 MB). If `Content-Length` header is missing, return `411 Length Required`.
   If `Content-Length` exceeds `MAX_BODY_BYTES`, return `413 Payload Too Large`.
   **Read the body in a single `self.rfile.read(content_length)` call — never
   read unbounded.**

4. Parse the body with `json.loads()`. If it fails (`json.JSONDecodeError`),
   return `400 Bad Request` with body `{"error": "invalid JSON"}`.

5. If JSON parses successfully, return `202 Accepted` with body
   `{"status": "accepted"}`. (202, not 200 — we haven't persisted anything yet.)

6. All responses must set `Content-Type: application/json`.

7. **Never log the request body.** Log only: remote IP, method, path, status
   code, Content-Length, and processing time in ms.

8. Add a `GET /health` endpoint that returns `200 {"status": "ok"}`. This is
   the only GET that returns 200.

**Implementation details for Haiku**:

```python
import json
import time
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

MAX_BODY_BYTES = 10 * 1024 * 1024

logger = logging.getLogger("receiver")

class IngestHandler(BaseHTTPRequestHandler):
    # Override log_message to use Python logging, not stderr
    def log_message(self, format, *args):
        logger.info("%s - %s", self.client_address[0], format % args)

    def _send_json(self, status_code, body_dict):
        """Send a JSON response. Use this for ALL responses."""
        payload = json.dumps(body_dict).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _route(self, method):
        """Central routing. Returns (handler_fn, None) or (None, error_response).
        Use this in every do_* method to enforce consistent 404/405 logic."""
        if self.path == "/health":
            if method == "GET":
                return ("health", None)
            return (None, 405)
        if self.path == "/ingest":
            if method == "POST":
                return ("ingest", None)
            return (None, 405)
        return (None, 404)

    def do_GET(self):
        route, err = self._route("GET")
        if err:
            self._send_json(err, {"error": "method not allowed"} if err == 405 else {"error": "not found"})
            return
        # route == "health"
        self._send_json(200, {"status": "ok"})

    def do_POST(self):
        route, err = self._route("POST")
        if err:
            self._send_json(err, {"error": "method not allowed"} if err == 405 else {"error": "not found"})
            return
        start = time.monotonic()
        # ... content-type check, content-length check, read body, parse JSON
```

**IMPORTANT**: Override `do_PUT`, `do_DELETE`, `do_PATCH` using the same
`_route()` pattern so they return 405 for known endpoints and 404 for unknown
paths. The default `BaseHTTPRequestHandler` returns 501 for unimplemented
methods, but we want explicit 404/405 with our JSON body format. Each
override is a 3-liner: call `_route`, send the appropriate error.

Add a `def main()` that creates `HTTPServer(("0.0.0.0", port), IngestHandler)`
and calls `serve_forever()`. Read port from an environment variable
`RECEIVER_PORT` defaulting to `8443`.

### File: `tests/test_receiver_server.py`

Use `unittest` only. Start the server in a thread in `setUpClass`, shut it down
in `tearDownClass`. Use `urllib.request` (stdlib) for HTTP calls — no `requests`
library.

**Required tests** (one test method each):

| # | Test | Assert |
|---|------|--------|
| 1 | POST /ingest with valid JSON `{"system_id": "test"}` | 202, body has `"status": "accepted"` |
| 2 | POST /ingest with invalid JSON `"not json{"` | 400, body has `"error"` |
| 3 | POST /ingest with empty string body `""` (sends Content-Length: 0) | 400 |
| 4 | GET /ingest | 405 |
| 5 | PUT /ingest | 405 |
| 6 | DELETE /ingest | 405 |
| 6b | PUT /nonexistent | 404 (not 405 — unknown path, not wrong method) |
| 6c | DELETE /nonexistent | 404 |
| 7 | POST /nonexistent | 404 |
| 8 | POST /ingest with Content-Type: text/plain | 415 |
| 9 | POST /ingest with Content-Length exceeding MAX_BODY_BYTES | 413 |
| 9b | POST /ingest with no Content-Length header | 411 |
| 10 | GET /health | 200, `{"status": "ok"}` |
| 10b | POST /health | 405 (health is GET-only) |
| 11 | GET /anything-else | 404 |
| 12 | Response Content-Type is application/json for every error case | check all above |

**Testing Content-Length edge cases (tests 9, 9b):** `urllib.request` auto-sets
`Content-Length` from the data, so you can't fake it. Use `http.client` instead:

```python
def _raw_request(self, method, path, body=None, headers=None):
    """Low-level HTTP request for testing edge cases (no auto Content-Length)."""
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", TEST_PORT)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())
```

For test 9: `headers={"Content-Type": "application/json", "Content-Length": "999999999"}`,
body can be `b"{}"`  — the server checks the header value before reading.
For test 9b: `headers={"Content-Type": "application/json"}` with no Content-Length
key at all, body=None.

**Test helper pattern** (give this to Haiku verbatim):
```python
import json
import threading
import unittest
import urllib.request
import urllib.error

from http.server import HTTPServer
from receiver.server import IngestHandler

TEST_PORT = 18943  # high port, unlikely to conflict

class TestIngestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", TEST_PORT), IngestHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def _request(self, method, path, body=None, content_type="application/json"):
        """Helper: make HTTP request, return (status_code, response_body_dict)."""
        url = f"http://127.0.0.1:{TEST_PORT}{path}"
        data = body.encode("utf-8") if isinstance(body, str) else body
        req = urllib.request.Request(url, data=data, method=method)
        if content_type:
            req.add_header("Content-Type", content_type)
        try:
            resp = urllib.request.urlopen(req)
            return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
```

---

## Phase 2: Authentication

**Goal**: Reject requests without a valid Bearer token. Tokens are pre-shared
secrets (one per agent). No OAuth, no JWT, no sessions.

### File: `receiver/auth.py`

**Requirements**:

1. Define a function `load_tokens(path) -> set[str]` that reads a plain text
   file, one token per line. Ignore blank lines and lines starting with `#`.
   Tokens must be at least 32 characters. Reject (log a warning and skip) any
   token shorter than 32 chars.

2. Define a function `check_auth(headers, valid_tokens) -> bool` that:
   - `headers` is an `http.client.HTTPMessage` (from `self.headers` in the
     handler). Use `headers.get("Authorization")` — **not `headers[...]`**
     which raises `KeyError` if missing.
   - Expects format `Bearer <token>` — split on first space only (`split(" ", 1)`).
   - Uses `hmac.compare_digest()` for comparison — **not `==`** or `in`. This
     prevents timing attacks.
   - **CRITICAL**: Always compare against ALL tokens. Do NOT early-return on
     match, and do NOT use `any()` (which short-circuits). Instead:

     ```python
     matched = False
     for valid_token in valid_tokens:
         if hmac.compare_digest(token, valid_token):
             matched = True
     return matched
     ```

   - Returns `False` for missing header, wrong format, or no match

3. **Never log the token value.** Log only "auth failed" or "auth succeeded"
   with the client IP.

**Integration into server.py**:

In `do_POST`, after the path check and before reading the body, call
`check_auth()`. If it returns `False`, return `401 Unauthorized` with
`{"error": "unauthorized"}` and a `WWW-Authenticate: Bearer` header.

Add a server-level attribute or module-level variable for the token set. Load
tokens at startup from a path specified by environment variable `RECEIVER_TOKENS_FILE`.
If the env var is not set or file doesn't exist, **refuse to start** (print error
and `sys.exit(1)`). Running without auth is never acceptable.

### File: `tests/test_receiver_auth.py`

**Required tests**:

| # | Test | Assert |
|---|------|--------|
| 1 | `load_tokens` with valid file (3 tokens, 32+ chars each) | returns set of 3 |
| 2 | `load_tokens` with comments and blank lines | ignores them |
| 3 | `load_tokens` with short token (< 32 chars) | skipped with warning, not in set |
| 4 | `load_tokens` with nonexistent file | raises FileNotFoundError |
| 5 | `check_auth` with valid Bearer token | True |
| 6 | `check_auth` with invalid token | False |
| 7 | `check_auth` with missing Authorization header | False |
| 8 | `check_auth` with `Basic` scheme instead of `Bearer` | False |
| 9 | `check_auth` with empty token string | False |
| 10 | `check_auth` with extra whitespace `Bearer  token` | False (strict parsing) |
| 11 | Server integration: POST /ingest without auth header | 401 |
| 12 | Server integration: POST /ingest with valid auth + valid JSON | 202 |
| 13 | Server integration: GET /health without auth | 200 (health is unauthenticated) |

For integration tests, write the token file to a temp directory in setUp, set
the env var, and start the server with tokens loaded. Use `tempfile.NamedTemporaryFile`.

**IMPORTANT — Phase 1→2 migration**: When you add auth in Phase 2, the server
will refuse to start without a token file. This **breaks the Phase 1 tests**
because they start the server without tokens. Fix this by updating
`test_receiver_server.py` to also create a temp token file and set the env var
in `setUpClass`. The Phase 1 tests don't send auth headers, so they'll get 401
on POST /ingest — **update those test assertions** to expect 401 instead of the
pre-auth status codes. Alternatively, keep a small subset of Phase 1 tests that
DO send a valid Bearer header. Either approach works; pick one and be consistent.

The `_request` helper should gain an optional `auth_token` parameter:

```python
def _request(self, method, path, body=None, content_type="application/json", auth_token=None):
    # ... existing code ...
    if auth_token:
        req.add_header("Authorization", f"Bearer {auth_token}")
```

---

## Phase 3: JSON Validation

**Goal**: Validate that the parsed JSON matches the UptimeDown output structure.
Reject payloads with missing required fields, wrong types, or unexpected values.
This is the most complex phase — take it slow.

### File: `receiver/validate.py`

**Approach**: Define validation as a set of pure functions. Each returns a list
of error strings (empty = valid). This makes testing trivial.

**3A: Envelope validation**

```python
def validate_envelope(data: dict) -> list[str]:
```

Check the top-level structure. The JSON must be a dict (not a list, not a
scalar). Required top-level keys — reject the payload if any is missing:

| Key | Type | Constraint |
|-----|------|-----------|
| `system_id` | `str` | Non-empty, max 64 chars, alphanumeric + hyphens only (regex: `^[a-zA-Z0-9-]+$`). Actual values are UUIDs with or without hyphens depending on the source (Linux product_uuid, AIX ODM, or fallback uuid4). |
| `collected_at` | `float` or `int` | Positive, reasonable range (> 1600000000, < 2000000000 — i.e., years ~2020–2033) |
| `collection_errors` | `dict` | Must be a dict (may be empty `{}`) |
| `cloud` | `bool` (False) or `dict` | Always present. `False` means not running on a recognized cloud provider. A dict means cloud metadata was detected (EC2, etc.). Never absent. |

Optional top-level keys — present only when the corresponding gatherer ran
in the current collection tick. With per-gatherer scheduling (`[intervals]`
in config.ini), a given payload may include only a subset of these:
`cpustats`, `cpuinfo`, `cpus`, `memory`, `disks`, `disk_total`,
`filesystems`, `network`

**Reject any key not in the known set.** This catches typos and injection of
unexpected fields.

**IMPORTANT — `cloud` is always present**: Unlike the data-section keys, `cloud`
is populated at agent startup and included in every payload regardless of which
gatherers ran. A payload missing `cloud` is malformed.

Return a list of all errors found (don't short-circuit on first error).

**3B: Section validators** — one function per data section. Each takes the
section dict and returns a list of error strings.

```python
def validate_cpustats(cpustats: dict) -> list[str]:
def validate_cpuinfo(cpuinfo: dict) -> list[str]:
def validate_cpus(cpus: dict) -> list[str]:       # AIX per-CPU enumeration
def validate_cloud(cloud) -> list[str]:            # False or dict
def validate_memory(memory: dict) -> list[str]:
def validate_disks(disks: dict) -> list[str]:
def validate_disk_total(disk_total: dict) -> list[str]:
def validate_filesystems(filesystems: dict) -> list[str]:
def validate_network(network: dict) -> list[str]:
```

**CRITICAL type-checking rules** (apply in every validator):

1. **Integers must be `int`, not `float`, not `str`.** Python's `json.loads`
   already does this correctly (JSON `42` → `int`, JSON `42.0` → `float`).
   Check with `isinstance(v, int) and not isinstance(v, bool)` — booleans are
   a subclass of int in Python, so `isinstance(True, int)` is `True`. You MUST
   exclude bools explicitly.

2. **Floats must be `float` or `int`.** Accept both since JSON `42` for a float
   field is valid. Check: `isinstance(v, (int, float)) and not isinstance(v, bool)`.

3. **Strings must be `str`.** Check: `isinstance(v, str)`.

4. **Counters must be non-negative.** CPU ticks, byte counts, packet counts
   are cumulative — they can never be negative. Check: `v >= 0`.

5. **Percentages must be 0.0–100.0.** Filesystem `pct_*` fields.

6. **Booleans**: `cloud` can be `False` (not on EC2) or a dict. This is a
   quirk of the current output — `False` means "not detected", dict means
   metadata. Validate accordingly.

**3C: `validate_cpustats` detail** (the most complex one):

cpustats is a dict. **Do NOT reject unknown keys at the top level.** AIX
perfstat emits dozens of fields (bread, bwrite, lread, lwrite, phread, phwrite,
iget, namei, dirblk, msg, sema, traps, puser, psys, pidle, pwait, etc.) that
aren't all in the SCHEMA.md cpu_stats table. New perfstat struct versions may
add more. Instead, validate **types only** for non-per-CPU keys.

**CRITICAL — platform difference in cpustats structure**:

- **Linux cpustats** contains per-CPU sub-dicts keyed `cpu0`, `cpu1`, etc.
  (one entry per logical CPU), plus aggregate fields at the top level.
- **AIX cpustats** is entirely aggregate — it contains **no** `cpu\d+` keys
  whatsoever. AIX per-CPU data lives under the **top-level `cpus` key**, not
  inside cpustats. Do not expect or require per-CPU entries in AIX cpustats.

Keys in cpustats fall into these categories:

- **Per-CPU entries (Linux only)**: keys matching pattern `cpu\d+` (e.g.,
  "cpu0", "cpu1"). Each value is a dict with tick fields. Only present on
  Linux. Validate these when found (see below); their absence is normal on AIX.
- **`description`**: str (AIX only — e.g., "PowerPC_POWER8").
- **`loadavg_1`, `loadavg_5`, `loadavg_15`**: non-negative floats. Present on
  both platforms.
- **`softirq`** (no `_ticks` suffix): list of non-negative ints (Linux only —
  aggregate softirq counters from `/proc/stat`). Not to be confused with
  `softirq_ticks` which is an int. Validate it's a list where every element
  is a non-negative int.
- **`ncpus_enumerated`**: non-negative int (AIX only — added by `__main__.py`).
- **All other top-level keys**: must be non-negative int. This covers both
  known fields (user_ticks, sys_ticks, ctxt, ncpus, syscall, processor_hz,
  tb_last, etc.) and unknown-but-valid perfstat fields. If a value is not int
  (excluding bool), or is negative, report an error.

Linux per-CPU sub-dicts (`cpu0`, `cpu1`, ...):

- Tick fields: `user_ticks`, `sys_ticks`, `idle_ticks`, `nice_ticks`,
  `iowait_ticks`, `irq_ticks`, `softirq_ticks`, `steal_ticks`, `guest_ticks`,
  `guest_nice_ticks` — all non-negative int.
- `softirqs`: a dict mapping IRQ type names (str, e.g. "HI", "TIMER",
  "NET_RX") to non-negative ints. May be empty `{}`. Validate: must be a dict,
  all values non-negative int, all keys str. Accept any IRQ type name.

Since we don't know the platform at validation time, **do NOT reject unknown
keys** in per-CPU dicts. Validate types only: every value must be non-negative
int, str, or dict (for `softirqs`). Report an error only for wrong types.

---

**3C-2: `validate_cpuinfo` detail** (Linux only):

Dict from `/proc/cpuinfo` cpu0 stanza. Known key types:

- **int**: `processor`, `cpu family`, `model`, `stepping`, `cpu cores`, `siblings`, `apicid`, `initial apicid`, `core id`, `physical id`, `clflush size`, `cache_alignment`, `cpuid level`
- **float**: `cpu MHz`, `bogomips`
- **str**: `vendor_id`, `model name`, `cache size`, `microcode`, `fpu`, `fpu_exception`, `wp`, `vmx flags`, `address sizes`, `power management`
- **list of str**: `flags`, `bugs`

**Do NOT reject unknown keys** — kernel versions add new cpuinfo fields.
Validate known keys have correct types. For unknown keys, accept any JSON type.

**3C-3: `validate_cpus` detail** (AIX only):

Dict keyed by CPU name (`cpu0`, `cpu1`, etc.). Each value is a `perfstat_cpu_t`
struct dict from AIX libperfstat. It contains dozens of int fields
(`user_ticks`, `sys_ticks`, `idle_ticks`, `iowait_ticks`, `pswitch`, `syscall`,
`bread`, `bwrite`, `redisp_sd0`–`sd5`, `migration_push`, `invol_cswitch`,
`vol_cswitch`, `cswitches`, `version`, `tb_last`, etc.) plus a `state` string
field (e.g., "running", "idle") and possibly other str fields.

**Do NOT reference AIX cpustats for the structure — AIX cpustats has no
per-CPU entries.** These dicts come from the separate perfstat_cpu_t per-CPU
enumeration, stored in the top-level `cpus` key.

Validate: all values must be non-negative int or str. Do not reject unknown
keys — new AIX kernel versions may add perfstat fields. Report an error only
if a value is float, bool, list, or dict.

**3C-4: `validate_cloud` detail**:

Can be `False` (bool) or a dict. If `False`, it's valid (means not on EC2).
If it's a dict, accept it — the cloud metadata structure is complex and
varies by provider. Do a shallow check: must be `False` or `dict`. If dict,
verify it's not empty (a cloud detection that returned an empty dict is a bug).
Do NOT deep-validate cloud dict contents in this phase.

**IMPORTANT**: Cloud dict values intentionally contain `None`, `bool`, `list`,
and nested dicts (e.g., `"tags": null`, `"burst_capable": true`,
`"network_interfaces": [...]`, `"maintenance_events": {...}`). Do NOT apply
the int/str type rules from §3B to cloud dict values — they do not apply here.
The `validate_cloud` function only checks the top-level type (False or non-empty
dict) and returns immediately.

**3D: `validate_memory` detail**:

Top level has two keys: `memory` (dict) and `slabs` (dict or `False`).

`memory` dict: All values are non-negative integers (byte counts). Known keys:
`mem_total`, `mem_free`, `mem_available`, `swap_total`, `swap_free`, `cached`,
`buffers`, etc. See project_reference.md §8.2 for the full Linux key list.
Accept **any string key** — do NOT restrict to snake_case. Linux /proc/meminfo
produces keys with parentheses such as `active(anon)`, `inactive(anon)`,
`active(file)`, `inactive(file)` that are not snake_case. AIX memory keys are
snake_case but different from Linux. Kernel versions add new keys over time.
Validate types only: every value must be a non-negative int.

`slabs` dict (when not False): keyed by slab name (string). Each value is a
dict with integer fields. Known fields include: `active_objs`, `num_objs`,
`objsize`, `objperslab`, `pagesperslab`, `limit`, `batchcount`, `sharedfactor`,
`active_slabs`, `num_slabs`, `sharedavail`. **Do NOT reject unknown keys** —
/proc/slabinfo output varies by kernel version and slab allocator config.
All values must be non-negative int. Validate types only.

**3E: `validate_disks` detail**:

Dict keyed by device name (string, e.g., "sda", "nvme0n1", "hdisk0"). Each
value is a dict. Fields vary significantly by platform:

- **Linux**: `major` (int), `minor` (int), plus DISKSTAT_KEYS fields — all
  non-negative int. Optional sysfs fields: `size_bytes`, `rotational`,
  `physical_block_size`, `logical_block_size`, `discard_granularity` (int),
  `scheduler` (str).
- **AIX**: Many perfstat fields including `size_bytes`, `free_bytes`, `xfers`,
  `read_blocks`, `write_blocks`, `read_ios`, `write_ios`, `read_ticks`,
  `write_ticks`, `bsize`, `qdepth`, `time`, `paths_count`, `q_full`,
  `q_sampled`, `wq_depth`, `wq_sampled`, `wq_time`, `wq_min_time`,
  `wq_max_time`, `min_rserv`, `max_rserv`, `min_wserv`, `max_wserv`,
  `rtimeout`, `wtimeout`, `rfailed`, `wfailed`, `wpar_id`, `dk_type`,
  `version` — all non-negative int.
  Plus string fields: `description`, `vgname`, `adapter`.

Since platform is unknown at validation time, **do NOT reject unknown keys**.
Validate types only: every value in a disk device dict must be either
non-negative int or str. No floats, no bools, no lists, no nested dicts.

**3E-2: `validate_disk_total` detail** (AIX only):

AIX provides a single aggregate across all disks in addition to per-device
entries. The `disk_total` dict contains all-int fields: `xfers`, `time`,
`version`, `min_rserv`, `max_rserv`, `rtimeout`, `rfailed`, `min_wserv`,
`max_wserv`, `wtimeout`, `wfailed`, `wq_depth`, `wq_time`, `wq_min_time`,
`wq_max_time`, `ndisks`, `size_bytes`, `free_bytes`, `read_blocks`,
`write_blocks`, `read_ticks`, `write_ticks`, `read_ios`, `write_ios`.

Validate: every value must be a non-negative int. **Do NOT reject unknown keys**
— new AIX kernel/perfstat versions may add fields. No str values, no floats, no
bools, no nested dicts. Report an error for any value that fails the
non-negative int check.

This section does not exist on Linux. The orchestrator only calls
`validate_disk_total` when the key is present in the payload.

**3F: `validate_filesystems` detail**:

Dict keyed by mountpoint (string). Each value is a dict. **Do NOT reject
unknown keys** — AIX adds platform-specific fields (listed below) and future
kernel versions may add more. Validate types of known fields only.

Required fields present in **every** filesystem entry (mounted or not):
`mountpoint` (str), `dev` (str), `vfs` (str), `mounted` (bool — True/False),
`options` (str — always a JSON-encoded string, even `'{}'` when empty; do NOT
try to parse it, just validate it's a str).

**AIX-specific fields** present in every AIX entry (mounted or not):
`log` (str), `mount` (str), `type` (str), `account` (str). During validation
just accept them as str. During transform, `log→fs_log`, `mount→mount_auto`,
`type→fs_type` are renamed; `account` is dropped (not in schema).
**These are NOT present on Linux.**

When `mounted` is `False`, **only** the above required fields (and AIX-specific
fields) are present. Do NOT require or check for statvfs fields on unmounted
entries. In practice, the majority of AIX filesystem entries (360 out of 429 in
test data) are unmounted WPAR/zone entries; an implementation that requires
statvfs fields on all entries will reject them all.

When `mounted` is `True`, these additional fields must be present and valid:

- Integer fields (non-negative int): `f_bsize`, `f_frsize`, `f_blocks`,
  `f_bfree`, `f_bavail`, `f_files`, `f_ffree`, `f_favail`, `bytes_total`,
  `bytes_free`, `bytes_available`, `f_flag`, `f_namemax`.
- Float fields (range 0.0–100.0): `pct_used`, `pct_free`, `pct_available`,
  `pct_reserved`.
- `f_flag` (int) — raw statvfs flag; used by transform to derive `fs_rdonly`.
- `f_namemax` (int) — present in JSON but NOT in DB schema. Accept during
  validation; it will be dropped during transform.

**3G: `validate_network` detail**:

Dict keyed by interface name (string, e.g., "eth0", "lo", "en0"). Each value
is a dict. Since platform is unknown, **do NOT reject unknown keys** and
**do NOT require any specific counter field** — field presence varies by
platform and interface type.

**Linux** interface dicts contain all 16 NET_DEV_KEYS counters plus metadata:

- Counters (always present on Linux): `ibytes`, `ipackets`, `ierrors`, `idrop`,
  `ififo`, `iframe`, `icompressed`, `imulticast`, `obytes`, `opackets`,
  `oerrors`, `odrop`, `ofifo`, `collisions`, `ocarrier`, `ocompressed` — all
  non-negative int.
- Metadata (conditional): `mtu` (int, always), `operstate` (str, always),
  `type` (int, always, ARPHRD code), `speed_mbps` (int, only when link speed
  is readable and non-negative; absent on loopback and some virtual interfaces).

**AIX** interface dicts contain a different, smaller set:

- Counters: `ibytes`, `ipackets`, `ierrors`, `idrop`, `obytes`, `opackets`,
  `oerrors`, `collisions`, `if_arpdrops` — all non-negative int.
- Note: `odrop`, `ififo`, `iframe`, `icompressed`, `imulticast`, `ofifo`,
  `ocarrier`, `ocompressed` are **not present** on AIX — they are Linux-only.
- Metadata: `mtu` (int), `speed_mbps` (int), `type` (int), `description` (str).
- Note: `operstate` is **not present** on AIX.

Validate types: every value must be either a non-negative int or a str. The
known str fields are `operstate` (Linux) and `description` (AIX). Any other
string-valued field is an error; any int-valued field must be non-negative.

**3H: Top-level orchestrator**:

```python
def validate_payload(data: dict) -> list[str]:
    """Run all validators. Returns list of all errors (empty = valid)."""
    errors = validate_envelope(data)
    if errors:
        return errors  # Don't validate sections if envelope is bad

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
```

**Integration into server.py**:

After JSON parsing succeeds, call `validate_payload(data)`. If errors are
non-empty, return `422 Unprocessable Entity` with
`{"error": "validation failed", "details": errors}`. Limit `details` to the
first 20 errors to prevent response size explosion on garbage input.

### File: `tests/test_receiver_validate.py`

This is the biggest test file. You need both positive tests (valid data passes)
and negative tests (bad data caught). Use the example JSON files in
`json_examples/` as a source of valid data structures.

**Required tests** (minimum — add more as you find edge cases):

**Envelope tests**:
| # | Test | Assert |
|---|------|--------|
| 1 | Valid envelope with all required keys | no errors |
| 2 | Missing `system_id` | error mentions system_id |
| 3 | `system_id` is int instead of str | error |
| 4 | `system_id` empty string | error |
| 5 | `system_id` with special chars (SQL injection attempt `'; DROP TABLE hosts;--`) | error (alphanumeric+hyphens only) |
| 6 | `collected_at` is a string | error |
| 7 | `collected_at` is negative | error |
| 8 | `collected_at` is year 1970 (too old) | error |
| 9 | `collected_at` is year 2050 (too far future) | error |
| 10 | Unknown top-level key `"malicious_key"` | error |
| 11 | `collection_errors` is a list instead of dict | error |
| 12 | Payload is a JSON list `[]` instead of dict | handled before validate (400 at parse) — but test validate_envelope with a list anyway |
| 13 | Missing `cloud` key | error (`cloud` is required, always present in real payloads) |
| 14 | `cloud` is `None` | error (must be `False` or a non-empty dict, not None) |

**cpustats tests**:
| # | Test |
|---|------|
| 1 | Valid Linux cpustats (from massive_flasharray.json) passes |
| 2 | Per-CPU tick field is string `"1234"` → error |
| 3 | Per-CPU tick field is negative → error |
| 4 | Per-CPU tick field is boolean True → error |
| 5 | Aggregate `user_ticks` is float 1.5 → error |
| 6 | `loadavg_1` is string → error |
| 7 | `loadavg_1` is negative → error |
| 8 | Per-CPU dict value is a float 1.5 (not int) → error |
| 9 | Valid AIX cpustats (from massive_aix_with_wpars.json) passes — all aggregate, no cpu\d+ sub-dicts |
| 10 | Per-CPU `softirqs` value is a string → error (must be non-negative int) |
| 11 | Per-CPU `softirqs` is a list instead of dict → error |

**memory tests**:
| # | Test |
|---|------|
| 1 | Valid Linux memory (from massive_flasharray.json) passes |
| 2 | `memory` sub-dict value is string → error |
| 3 | `memory` sub-dict value is negative → error |
| 4 | `slabs` is None instead of False or dict → error |
| 5 | Slab entry value is float → error |
| 6 | Memory dict with parenthesized keys (`active(anon)`, `inactive(file)`) passes — these are real Linux /proc/meminfo keys |
| 7 | Valid AIX memory (from massive_aix_with_wpars.json) passes — different key set, slabs is False |

**filesystem tests**:
| # | Test |
|---|------|
| 1 | Valid Linux filesystem dict (mounted=True) passes |
| 2 | `pct_used` is 150.0 (> 100) → error |
| 3 | `pct_used` is -5.0 (< 0) → error |
| 4 | `mounted` is 1 instead of True → error (must be bool) |
| 5 | Missing `bytes_total` when mounted is True → error |
| 6 | Valid AIX filesystem (mounted=False, with `log`, `mount`, `type`, `account` fields, no f_* fields) passes — this is the common case for WPAR entries |
| 7 | Valid AIX filesystem (mounted=True, with all statvfs fields plus `log`, `mount`, `type`, `account`) passes |
| 8 | Unknown string field in filesystem entry passes — do NOT reject unknown keys |

**disks tests**:
| # | Test |
|---|------|
| 1 | Valid Linux disk dict (from massive_flasharray.json) passes |
| 2 | Valid AIX disk dict (from massive_aix_with_wpars.json) passes — all-int fields plus `description`, `vgname`, `adapter` strings |
| 3 | Disk field value is float → error |
| 4 | Disk field value is negative → error |
| 5 | Disk field value is a nested dict → error |
| 6 | `validate_disk_total`: valid AIX disk_total passes |
| 7 | `validate_disk_total`: field value is negative → error |
| 8 | `validate_disk_total`: field value is str → error |
| 9 | `validate_disk_total`: unknown extra int field passes (do NOT reject unknown keys) |

**network tests**:
| # | Test |
|---|------|
| 1 | Valid Linux network dict passes |
| 2 | `ibytes` is negative → error |
| 3 | `ibytes` is string → error |
| 4 | `operstate` is int → error |
| 5 | Valid AIX network entry (with `description`, `if_arpdrops`, no `operstate`, no `odrop`) passes |
| 6 | Linux-only fields (`ififo`, `ofifo`, `ocarrier`, `ocompressed`) absent from AIX entry — passes (not required) |

**Full payload integration test**:
| # | Test |
|---|------|
| 1 | Load `massive_flasharray.json`, validate_payload returns no errors |
| 2 | Load `massive_aix_with_wpars.json`, validate_payload returns no errors |
| 3 | Mutate one field to be wrong type, confirm exactly 1 error |

---

## Phase 4: Schema Transform

**Goal**: Transform validated JSON into flat dicts ready for database INSERT.
One function per target table. These functions apply the key renames documented
in SCHEMA.md "Ingestion key mapping" section.

### File: `receiver/transform.py`

Each transform function takes the raw JSON section dict and returns row-dicts.
Each row-dict has keys matching the SQL column names exactly.

**Calling convention**: The caller splits the JSON envelope and passes the
correct sub-dict to each function. For example:

```python
# data is the parsed top-level JSON dict
cpu_stats_row = transform_cpu_stats(data["cpustats"], host_id, data["collected_at"])
memory_row    = transform_memory(data["memory"]["memory"], host_id, data["collected_at"])
slab_rows     = transform_memory_slabs(data["memory"]["slabs"], host_id, data["collected_at"])
```

**Platform detection**: The caller must determine the platform to choose the
correct disk transform. Check for platform-exclusive keys:

- `"cpuinfo" in data` → Linux (call `transform_disks_linux`)
- `"disk_total" in data` or `"cpus" in data` → AIX (call `transform_disks_aix`)

**GOTCHA — per-gatherer scheduling**: With independent gatherer intervals, a
given payload may contain neither `cpuinfo` nor `cpus`/`disk_total` if neither
the CPU nor disk gatherer ran in this tick (e.g., a memory-only tick). In this
case the caller cannot determine platform from the payload alone and must fall
back to the platform stored in the `hosts` table for this `system_id`. The
transform functions themselves do not access the database — the CALLER bridges
this by passing `platform` as a parameter or by routing to the correct
`transform_disks_*` function based on the stored platform.

**`collected_at` vs `recorded_at`**: The SCHEMA.md uses `collected_at` for
per-collection tables (cpu_stats, memory, filesystems, disk_devices, net_interfaces)
and `recorded_at` for semi-static tables (cpu_info, cloud_metadata). The
transform functions must use the correct output key name for each table. The
parameter is always called `collected_at` — rename it in the output dict where
the schema column is `recorded_at`.

```python
def transform_cpu_stats(cpustats: dict, host_id: int, collected_at: float) -> dict:
    """Extract aggregate CPU stats. Returns one row-dict for cpu_stats table.
    Per-CPU data is NOT stored in cpu_stats (future: cpu_stats_per_core table).
    Output key: collected_at."""

def transform_cpu_info(cpuinfo: dict, host_id: int, collected_at: float,
                       cpu_count: int = None) -> dict:
    """Extract CPU hardware info. Returns one row-dict for cpu_info table.
    Apply key renames: 'cpu family'→cpu_family, 'model name'→model_name, 'cpu MHz'→cpu_mhz.
    Converts 'flags' and 'bugs' lists to space-separated strings for TEXT columns.
    Drops keys not in schema (microcode, fpu, wp, vmx flags, cpuid level, etc.).
    Output key: recorded_at (NOT collected_at — this is a semi-static table).

    GOTCHA: The schema has cpu_count (logical CPUs online) but cpuinfo doesn't
    contain it. On Linux, the caller must count cpu\d+ keys in cpustats and pass
    it as cpu_count. On AIX, pass cpustats['ncpus']. The transform itself does
    not access cpustats — the caller bridges this."""

def transform_memory(memory_inner: dict, host_id: int, collected_at: float) -> dict:
    """Extract memory stats. Returns one row-dict for memory table.
    IMPORTANT: pass data["memory"]["memory"], NOT data["memory"].
    Apply renames: 'cached'→mem_cached, 'hugepagesize'→huge_page_size.
    Bundle unknown keys into extra_json. Output key: collected_at."""

def transform_memory_slabs(slabs, host_id: int, collected_at: float) -> list[dict]:
    """Returns list of row-dicts for memory_slabs table (one per slab).
    IMPORTANT: pass data["memory"]["slabs"], NOT data["memory"].
    Returns empty list if slabs is False."""

def transform_filesystems(filesystems: dict, host_id: int, collected_at: float) -> list[dict]:
    """Returns list of row-dicts for filesystems table (one per mountpoint).
    Include ALL entries regardless of mounted status — unmounted entries get
    NULL for all statvfs columns (bytes_total, pct_used, etc.).
    Apply AIX renames: 'log'→fs_log, 'mount'→mount_auto, 'type'→fs_type.
    AIX 'account' field: drop (not in schema, no rename defined).
    Derive fs_rdonly from f_flag & 1 when present; NULL when not mounted.
    Drop f_flag and f_namemax from output (not in schema).
    Convert mounted: True→1, False→0."""

def transform_disks_linux(disks: dict, host_id: int, collected_at: float) -> list[dict]:
    """Returns list of row-dicts for disk_devices_linux table.
    Bundle sysfs fields (size_bytes, rotational, physical_block_size,
    logical_block_size, scheduler, discard_granularity) into extra_json TEXT column."""

def transform_disks_aix(disks: dict, disk_total: dict, host_id: int, collected_at: float) -> tuple[list[dict], dict]:
    """Returns (list of disk_devices_aix row-dicts, one disk_total row-dict)."""

def transform_network(network: dict, host_id: int, collected_at: float) -> list[dict]:
    """Returns list of row-dicts for net_interfaces table (one per interface).
    Each row-dict contains only the fields present in the input for that interface.
    Linux-only field (operstate) is absent from AIX rows — do NOT default
    it to None/0. AIX-only field (description) is absent from Linux rows.
    Output key: collected_at."""
```

**Key principles**:

1. **Only include columns that exist in SCHEMA.md.** If the JSON has a key that
   doesn't map to any column and isn't in `extra_json`, drop it silently.

2. **`extra_json` columns**: Serialize remaining/overflow fields as a JSON string
   using `json.dumps()`. If there are no extra fields, set to `None` (SQL NULL),
   not `"{}"`.

3. **`host_id`**: The transform functions receive `host_id` as a parameter. The
   caller (server or future db layer) is responsible for looking up or creating
   the host record from `system_id`. Transform functions do NOT touch the
   database.

4. **Minimal type changes**: The transform mostly preserves types from validated
   JSON. The only conversions are:
   - `mounted`: `True`/`False` → `1`/`0` (SQL integer)
   - `flags`, `bugs` (cpu_info): list of str → space-separated str (SQL TEXT)
   - `extra_json` fields: dict → `json.dumps()` string (SQL TEXT)

   Everything else passes through unchanged. Do NOT cast ints to str, stringify
   floats, or otherwise alter numeric values.

### File: `tests/test_receiver_transform.py`

**Required tests**:

| # | Test |
|---|------|
| 1 | `transform_cpu_stats`: Linux cpustats → row-dict has `user_ticks`, `sys_ticks`, etc. at top level; per-CPU keys excluded |
| 2 | `transform_cpu_stats`: AIX cpustats → row-dict has AIX-specific fields (ncpus, syscall, etc.); Linux-only fields (nice_ticks, guest_ticks, etc.) absent from row-dict entirely (not NULL — AIX cpustats simply doesn't have them); fields not in schema (bread, bwrite, puser, etc.) dropped |
| 3 | `transform_cpu_stats`: per-CPU keys (`cpu0`, `cpu1`, ...) excluded from output |
| 4 | `transform_cpu_info`: `cpu family` → `cpu_family`, `model name` → `model_name`, `cpu MHz` → `cpu_mhz`; output has `recorded_at` (not `collected_at`) |
| 4b | `transform_cpu_info`: `flags` list → space-separated string; `bugs` list → space-separated string |
| 4c | `transform_cpu_info`: keys not in schema (`microcode`, `fpu`, `wp`, `vmx flags`, `cpuid level`, `address sizes`, `power management`) are dropped |
| 5 | `transform_memory`: `cached` → `mem_cached`, `hugepagesize` → `huge_page_size` |
| 6 | `transform_memory`: unknown keys go into `extra_json` |
| 7 | `transform_memory`: AIX-only keys (`real_inuse`, `pgbad`, `virt_total`, etc.) go into `extra_json` |
| 8 | `transform_memory_slabs`: False input → empty list |
| 9 | `transform_memory_slabs`: valid slabs → list of dicts with correct keys |
| 10 | `transform_filesystems`: `f_flag=1` → `fs_rdonly=1`; `f_flag=0` → `fs_rdonly=0` |
| 11 | `transform_filesystems`: AIX renames: `log`→`fs_log`, `mount`→`mount_auto`, `type`→`fs_type` |
| 12 | `transform_filesystems`: `mounted=True` → `mounted=1` |
| 12b | `transform_filesystems`: `f_namemax` is dropped from output |
| 12c | `transform_filesystems`: unmounted AIX entry (mounted=False) → row included with `mounted=0`; statvfs columns (`bytes_total`, `pct_used`, etc.) absent from row-dict (NULL in DB) |
| 12d | `transform_filesystems`: AIX `account` field dropped (not in schema, no rename) |
| 13 | `transform_disks_linux`: sysfs fields bundled into `extra_json` |
| 14 | `transform_disks_linux`: device with no sysfs data → `extra_json` is None |
| 15 | `transform_network` (Linux): schema columns pass through (`ibytes`, `ipackets`, `ierrors`, `idrop`, `odrop`, `obytes`, `opackets`, `oerrors`, `mtu`, `operstate`, `type`); dropped NET_DEV_KEYS filtered out (`ififo`, `iframe`, `icompressed`, `imulticast`, `ofifo`, `collisions`, `ocarrier`, `ocompressed`); `speed_mbps` absent when not in input |
| 15b | `transform_network` (AIX): only AIX fields present (`ibytes`, `ipackets`, `ierrors`, `idrop`, `obytes`, `opackets`, `oerrors`, `mtu`, `speed_mbps`, `type`, `description`); Linux-only fields (`operstate`, `odrop`) absent; dropped fields (`collisions`, `if_arpdrops`) absent |
| 16 | `transform_network`: `iface` key is set from the outer dict key |
| 17 | Full round-trip: load `massive_flasharray.json` → transform all sections → verify no crash, correct key names |
| 18 | Full round-trip: load `massive_aix_with_wpars.json` → same |

---

## Phase 5: Database Layer (Future — Do Not Implement Yet)

This phase is documented here for context only. Do not implement it until
Phases 1–4 are complete and tested.

**Planned approach**:
- `receiver/db.py` with connection pooling (or simple connection reuse)
- **Driver-specific parameterization**:
  - PostgreSQL/MariaDB: `%s` placeholders
  - SQLite: `?` placeholders
- **Never** use string formatting/f-strings for SQL
- Transaction per ingestion payload (all tables or rollback)
- Host upsert (driver-specific syntax):
  - PostgreSQL/MariaDB: `INSERT ... ON CONFLICT (system_id) DO UPDATE SET last_seen = ...`
  - SQLite: `INSERT OR REPLACE INTO hosts ...`
- Batch inserts for multi-row tables (filesystems, disks, network, slabs)
- PostgreSQL: use `psycopg2.extras.execute_values()` for batch efficiency
- MariaDB: standard `executemany()` with `mysql.connector`
- SQLite: use `executemany()` with `?` placeholders

---

## Security Checklist

Apply these throughout ALL phases. Verify each one in code review.

- [ ] **No unbounded reads.** Always check Content-Length before reading body.
      Never use `self.rfile.read()` without a length argument.
- [ ] **No SQL injection.** All database queries use parameterized statements.
      Never format SQL with f-strings, `.format()`, or `%` operator.
- [ ] **No body logging.** Request bodies may contain sensitive system data.
      Log metadata only (IP, status, timing, Content-Length).
- [ ] **No token logging.** Auth tokens never appear in logs.
- [ ] **Constant-time auth.** Use `hmac.compare_digest()`, not `==`.
- [ ] **Strict input validation.** Reject unknown top-level keys in the
      envelope. For section-level dicts (cpustats, disks, network, etc.),
      validate types and ranges but accept unknown keys (platform variance).
      Default to rejection for types/ranges.
- [ ] **No file I/O with request data.** We never write request bodies to disk.
      The only file read is the token file at startup.
- [ ] **No shell commands.** The receiver never calls `subprocess` or `os.system`.
- [ ] **No eval/exec.** Obviously.
- [ ] **No pickle/marshal.** We only deserialize JSON.
- [ ] **Content-Length required.** Reject requests without it. This prevents
      slow-loris and chunked-encoding attacks on our simple HTTP server.
- [ ] **system_id sanitization.** Alphanumeric + hyphens only. This value ends
      up in SQL queries (parameterized, but defense in depth).
- [ ] **Mountpoint/device name sanitization.** These are strings from the agent.
      Validate they don't contain null bytes or control characters. Use:
      `all(c.isprintable() for c in value) and '\x00' not in value`
- [ ] **Response size limits.** Error detail lists capped at 20 entries.

---

## Iteration Order for Haiku

1. **Phase 1** → run tests → all 12 pass → commit
2. **Phase 2** → run tests → all 13 pass → commit
3. **Phase 3A-3B** (envelope + cpustats only) → run tests → commit
4. **Phase 3C-3G** (remaining validators) → run tests → commit
5. **Phase 4** → run tests → commit

Run the full test suite after each phase: `python3 -m unittest discover -s tests`

Every function must have a docstring. Every test must have a descriptive name
that says what it tests, not `test_1`, `test_2`. Example:
`test_post_invalid_json_returns_400`, `test_system_id_with_sql_injection_rejected`.

---

## Reference: JSON Top-Level Keys by Platform

"Always" means present in every payload. "When gathered" means present only
when that gatherer ran in the current tick (per-gatherer scheduling may omit
a section if its interval hasn't elapsed). `cloud` is the only data key that
is always present regardless of which gatherers ran.

| Key | Linux | AIX | Type |
|-----|-------|-----|------|
| `system_id` | always | always | str |
| `collected_at` | always | always | float |
| `collection_errors` | always | always | dict |
| `cloud` | always | always | `False` (bool) or dict |
| `cpustats` | when gathered | when gathered | dict (Linux: aggregate + per-CPU sub-dicts; AIX: aggregate only — no cpu\d+ sub-dicts) |
| `cpuinfo` | when gathered | never | dict (Linux /proc/cpuinfo cpu0 stanza) |
| `cpus` | never | when gathered | dict keyed by cpu name (AIX per-CPU perfstat_cpu_t structs) |
| `memory` | when gathered | when gathered | dict with `memory` (inner stats dict) and `slabs` (dict or `False`) sub-keys |
| `disks` | when gathered | when gathered | dict keyed by device name |
| `disk_total` | never | when gathered | dict (AIX aggregate across all disks) |
| `filesystems` | when gathered | when gathered | dict keyed by mountpoint |
| `network` | when gathered | when gathered | dict keyed by interface name |

## Reference: Column Name Renames (Ingestion Layer)

Copied from SCHEMA.md for convenience — the transform functions must apply these:

| Source (JSON key) | Target (SQL column) | Table |
|-------------------|---------------------|-------|
| `cpu family` | `cpu_family` | cpu_info |
| `model name` | `model_name` | cpu_info |
| `cpu MHz` | `cpu_mhz` | cpu_info |
| `cached` | `mem_cached` | memory |
| `hugepagesize` | `huge_page_size` | memory |
| `log` | `fs_log` | filesystems |
| `mount` | `mount_auto` | filesystems |
| `type` | `fs_type` | filesystems |
| sysfs fields | bundled into `extra_json` | disk_devices_linux |
| `f_flag & 1` | `fs_rdonly` | filesystems (derived) |
