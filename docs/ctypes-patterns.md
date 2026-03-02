# ctypes Patterns for System Library Integration

This document describes best practices and patterns for using Python's ctypes to bind to C libraries, specifically as applied in the AIX perfstat integration.

## Structure Definition

### Basic Pattern

Define ctypes Structures to match C struct layouts exactly:

```python
import ctypes

# C struct:
# struct example_t {
#     char name[64];
#     int count;
#     unsigned long long ticks;
# };

class example_t(ctypes.Structure):
    _fields_ = [
        ("name",   ctypes.c_char * 64),
        ("count",  ctypes.c_int),
        ("ticks",  ctypes.c_ulonglong),
    ]
```

**Key points:**
- Field order must match C struct order
- Use appropriate types: `c_int`, `c_char`, `c_ulonglong`, etc.
- Arrays are represented as `ctypes_type * count`
- Strings are `ctypes.c_char * length`

### Handling Struct Padding

C compilers insert padding bytes for alignment. Explicit padding fields must be added:

```python
# C struct (with padding):
# struct padded_t {
#     int field_a;           // 4 bytes @ offset 0
#     // 4 bytes padding here for alignment
#     unsigned long long field_b;  // 8 bytes @ offset 8
# };

class padded_t(ctypes.Structure):
    _fields_ = [
        ("field_a",  ctypes.c_int),
        ("_pad0",    ctypes.c_int),  # Explicit padding
        ("field_b",  ctypes.c_ulonglong),
    ]
```

**Verification:**
```python
import ctypes
print(ctypes.sizeof(padded_t))  # Should match C sizeof()
```

### Accessing Struct Fields

After ctypes fills a struct, access fields as attributes:

```python
buf = example_t()
# ... ctypes fills buf from C library ...

name = buf.name  # bytes object
count = buf.count  # int
ticks = buf.ticks  # int
```

**String handling:**
```python
name_bytes = buf.name  # b'example\x00...'
name_str = name_bytes.decode("ascii", errors="replace").rstrip("\x00")
```

**Fixed-point conversion:**
```python
raw_fixed_point = buf.loadavg
actual_value = raw_fixed_point / 65536.0  # FSCALE on AIX
```

## Library Binding

### Loading Native Libraries

```python
import ctypes

# On AIX (shared library inside .a archive)
lib = ctypes.CDLL("libperfstat.a(shr_64.o)")

# On Linux (standard shared object)
lib = ctypes.CDLL("libc.so.6")

# With fallback
try:
    lib = ctypes.CDLL("libfoo.so.1")
except OSError:
    lib = ctypes.CDLL("libfoo.so")
```

### Function Binding

Define argument and return types before calling:

```python
lib = ctypes.CDLL("libperfstat.a(shr_64.o)")

# Define function signature:
# int perfstat_cpu(
#     perfstat_id_t *id,
#     perfstat_cpu_t *buf,
#     int sizeof_buf,
#     int desired_count
# );

lib.perfstat_cpu.argtypes = [
    ctypes.POINTER(perfstat_id_t),
    ctypes.POINTER(perfstat_cpu_t),
    ctypes.c_int,
    ctypes.c_int,
]
lib.perfstat_cpu.restype = ctypes.c_int

# Now call it
ret = lib.perfstat_cpu(id_ptr, buf_ptr, sizeof_buf, count)
```

## Pointers and Buffers

### Single Struct Pointer

```python
buf = example_t()
ptr = ctypes.byref(buf)  # Get reference to buf
ret = lib.get_example(ptr, ctypes.sizeof(buf), 1)
```

### Array of Structs

```python
# C: perfstat_cpu_t cpus[16];
CpuArray = perfstat_cpu_t * 16
cpu_array = CpuArray()

# Get pointer to array (cast to pointer to first element)
cpu_ptr = ctypes.cast(cpu_array, ctypes.POINTER(perfstat_cpu_t))

# Access individual elements
cpu0 = cpu_array[0]
cpu1 = cpu_array[1]
```

### NULL Pointers

```python
# For optional C pointers (perfstat_id_t *name)
ret = lib.perfstat_cpu(None, None, sizeof, 0)  # NULL, NULL
```

## Error Handling

### Return Value Checking

Always check function return values:

```python
def get_cpus():
    lib = ctypes.CDLL("libperfstat.a(shr_64.o)")

    # Count query
    ncpus = lib.perfstat_cpu(None, None, ctypes.sizeof(perfstat_cpu_t), 0)
    if ncpus <= 0:
        logger.error(f"perfstat_cpu count returned {ncpus}")
        return False

    # Enumeration
    CpuArray = perfstat_cpu_t * ncpus
    cpu_buf = CpuArray()
    id_buf = perfstat_id_t()
    id_buf.name = b""

    ret = lib.perfstat_cpu(
        ctypes.byref(id_buf),
        ctypes.cast(cpu_buf, ctypes.POINTER(perfstat_cpu_t)),
        ctypes.sizeof(perfstat_cpu_t),
        ncpus,
    )

    if ret != ncpus:
        logger.error(f"Expected {ncpus}, got {ret}")
        return False

    return {cpu_buf[i].name.decode(): {...} for i in range(ncpus)}
```

### OSError During Library Load

```python
try:
    lib = ctypes.CDLL("libfoo.a(shr_64.o)")
except OSError as e:
    logger.error(f"Could not load libfoo: {e}")
    # Handle gracefully - maybe return False or skip feature
    return False
```

## Type Safety and Conversions

### Type Mapping

| C Type | ctypes | Python |
|--------|--------|--------|
| `char` | `c_char` | bytes (1 char) |
| `int` | `c_int` | int |
| `unsigned int` | `c_uint` | int |
| `long` | `c_long` | int |
| `long long` | `c_longlong` | int |
| `unsigned long long` | `c_ulonglong` | int |
| `float` | `c_float` | float |
| `double` | `c_double` | float |
| `void*` | `POINTER(c_void_p)` | None or address |
| `struct*` | `POINTER(struct_t)` | struct_t reference |
| `char[64]` | `c_char * 64` | bytes |

### Byte String Handling

ctypes `c_char` arrays come back as bytes:

```python
# C: char name[64];
name_bytes = buf.name  # type: bytes

# Decode to string
name_str = name_bytes.decode("ascii", errors="replace")

# Strip null terminator
name_clean = name_str.rstrip("\x00")
```

### Numeric Conversions

```python
# Fixed-point to float (AIX loadavg)
FSCALE = 1 << 16
raw_la = 327680  # In fixed-point format
actual_la = raw_la / FSCALE  # 5.0

# Byte to integer (for flags/state fields)
state_byte = buf.state  # type: bytes (1 char)
if isinstance(state_byte, bytes):
    state_int = state_byte[0]  # Get first byte as int
online = state_int > 0
```

## Portability Considerations

### Endianness

Most modern systems are little-endian, but always verify:

```python
import sys
is_little_endian = sys.byteorder == "little"

# If crossing architectures, use struct module for explicit packing:
import struct
value = struct.unpack("<Q", bytes_data)[0]  # Little-endian
value = struct.unpack(">Q", bytes_data)[0]  # Big-endian
```

### 32-bit vs 64-bit

Use explicit types:

```python
# Always explicit (not "c_long" which varies by platform)
field_64bit = ctypes.c_ulonglong  # Always 8 bytes
field_32bit = ctypes.c_uint       # Always 4 bytes
field_int = ctypes.c_int          # May vary

# For maximum compatibility, prefer explicit types:
# c_char, c_int, c_float, c_double
# c_uint, c_longlong, c_ulonglong, c_ubyte
```

### AIX-Specific

```python
# IDENTIFIER_LENGTH is defined in libperfstat.h as 64
# Always use the constant, not magic numbers:

IDENTIFIER_LENGTH = 64

class perfstat_id_t(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char * IDENTIFIER_LENGTH),
    ]
```

## Testing and Debugging

### Struct Size Verification

```python
# C: gcc -E file.c | grep "sizeof(perfstat_cpu_t)"
# or: sizeof_perfstat_cpu_t = 504  (from documentation)

expected_size = 504
actual_size = ctypes.sizeof(perfstat_cpu_t)
assert actual_size == expected_size, \
    f"Struct size mismatch: expected {expected_size}, got {actual_size}"
```

### Printing Field Offsets

```python
for field_name, field_type in perfstat_cpu_t._fields_:
    offset = getattr(perfstat_cpu_t, field_name).offset
    size = ctypes.sizeof(field_type)
    print(f"{field_name:20} offset={offset:3d} size={size:3d}")
```

### Logging Struct Contents

```python
def dump_struct(obj, struct_class):
    """Print all fields of a struct for debugging."""
    for field_name, _ in struct_class._fields_:
        val = getattr(obj, field_name)
        if isinstance(val, bytes):
            val = val.rstrip(b'\x00').decode("ascii", errors="replace")
        print(f"{field_name:30} = {val}")

dump_struct(cpu_buf[0], perfstat_cpu_t)
```

## Performance Tips

### Minimize Struct Copies

```python
# DON'T: Copy entire struct
cpu_copy = cpu_buf[0]  # Creates a copy
# ... modify cpu_copy ...

# DO: Modify in place or iterate carefully
for i in range(ncpus):
    cpu = cpu_buf[i]  # Reference, not copy
    process_cpu(cpu)
```

### Reuse Arrays

```python
# DON'T: Allocate new array each call
def get_cpus():
    CpuArray = perfstat_cpu_t * ncpus
    cpu_buf = CpuArray()  # Allocate
    # ...

# DO: Allocate once if calling repeatedly
class CpuCollector:
    def __init__(self, max_cpus=256):
        CpuArray = perfstat_cpu_t * max_cpus
        self.cpu_buf = CpuArray()  # Reuse
        self.max_cpus = max_cpus

    def collect(self):
        # Reuses self.cpu_buf
```

### Lazy Library Loading

```python
_lib = None

def get_lib():
    global _lib
    if _lib is None:
        _lib = ctypes.CDLL("libperfstat.a(shr_64.o)")
    return _lib
```

## Common Pitfalls

| Pitfall | Issue | Fix |
|---------|-------|-----|
| Struct size mismatch | Padding not accounted for | Verify with `sizeof()` |
| Wrong argument types | Crashes or garbage data | Define argtypes before calling |
| Not checking return values | Silent failures | Always check ret value |
| Forgetting NULL decode | Garbage strings | `.rstrip("\x00")` |
| Array indexing | Off-by-one errors | Loop with `range(actual_count)` |
| Pointer ownership | Memory corruption | Don't free ctypes-allocated memory |

## References

- Python ctypes docs: https://docs.python.org/3/library/ctypes.html
- PEP 384 (Stable ABI): https://www.python.org/dev/peps/pep-0384/
- IBM libperfstat header: `/usr/include/libperfstat.h` (on AIX)
