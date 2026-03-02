# AIX network interface gatherer. Uses libperfstat via ctypes to call
# perfstat_netinterface().
#
# Exposes an AixNetwork class. After instantiation:
#   interfaces — dict keyed by interface name (e.g. 'en0', 'lo0'), each entry
#                containing all perfstat_netinterface_t counters plus '_time'.
#
# All counter fields are cumulative since boot; compute rates by differencing
# adjacent samples at query time (see SCHEMA.md).
#
# References:
#   https://www.ibm.com/docs/en/aix/7.3?topic=interfaces-perfstat-netinterface-interface
#   OpenJDK shenandoah libperfstat_aix.hpp for struct layout
import ctypes
import time
import logging

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())

# IDENTIFIER_LENGTH matches IDENTIFIER_LENGTH in libperfstat.h (64 bytes).
IDENTIFIER_LENGTH = 64


class perfstat_id_t(ctypes.Structure):
    """perfstat_id_t — cursor used to control perfstat enumeration.

    Set name to b"" (empty string) to start enumeration from the first object.
    After a successful call, name is updated to the last object returned,
    enabling paginated enumeration.
    """
    _fields_ = [
        ("name", ctypes.c_char * IDENTIFIER_LENGTH),
    ]


class perfstat_netinterface_t(ctypes.Structure):
    """Per-interface network statistics — perfstat_netinterface_t.

    Layout: char[64] name, char[64] description, uchar type (1 byte),
    7 bytes implicit padding to align the following u_longlong_t to 8 bytes,
    then 12 × u_longlong_t fields.
    sizeof == 232.

    Note: the C struct spells the rx packet count field 'ipackets' but the
    IBM/OpenJDK header has it as 'ipacets' (a long-standing typo in libperfstat.h).
    The ctypes field name matches the C struct ('ipacets') to preserve ABI
    compatibility; it is renamed to 'ipackets' in get_interfaces() output.
    """
    _fields_ = [
        ("name",         ctypes.c_char * IDENTIFIER_LENGTH),
        ("description",  ctypes.c_char * IDENTIFIER_LENGTH),
        ("type",         ctypes.c_ubyte),
        ("_pad0",        ctypes.c_byte * 7),        # uchar → u_longlong_t alignment
        ("mtu",          ctypes.c_ulonglong),
        ("ipacets",      ctypes.c_ulonglong),        # typo in libperfstat.h; means ipackets
        ("ibytes",       ctypes.c_ulonglong),
        ("ierrors",      ctypes.c_ulonglong),
        ("opackets",     ctypes.c_ulonglong),
        ("obytes",       ctypes.c_ulonglong),
        ("oerrors",      ctypes.c_ulonglong),
        ("collisions",   ctypes.c_ulonglong),
        ("bitrate",      ctypes.c_ulonglong),
        ("if_iqdrops",   ctypes.c_ulonglong),
        ("if_arpdrops",  ctypes.c_ulonglong),
    ]


def get_interfaces():
    """Call perfstat_netinterface() and return per-interface stats as a dict.

    Uses the standard two-call perfstat enumeration pattern:
        1. NULL id, NULL buffer, count=0 → returns total interface count.
        2. Allocate array, set id.name=b"" (FIRST_INTERFACE), call with count.

    Returns a dict keyed by interface name (e.g. 'en0', 'lo0'), or an empty
    dict on error. All entries share a single '_time' timestamp.

    Output keys are normalized to schema column names:
        ipacets  → ipackets  (corrects the typo in libperfstat.h)
    """
    logger.debug("get_interfaces: calling perfstat_netinterface (count query + enumeration)")
    try:
        lib = ctypes.CDLL("libperfstat.a(shr_64.o)")
    except OSError as e:
        logger.error("Can't load libperfstat: %s", e)
        return {}

    lib.perfstat_netinterface.argtypes = [
        ctypes.POINTER(perfstat_id_t),
        ctypes.POINTER(perfstat_netinterface_t),
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.perfstat_netinterface.restype = ctypes.c_int

    # Count-only call: NULL id, NULL buffer, count=0 → returns number of interfaces.
    nifaces = lib.perfstat_netinterface(
        None, None, ctypes.sizeof(perfstat_netinterface_t), 0
    )
    if nifaces <= 0:
        logger.error("perfstat_netinterface count query returned %d", nifaces)
        return {}
    logger.debug("get_interfaces: perfstat reports %d interfaces", nifaces)

    IfaceArray = perfstat_netinterface_t * nifaces
    iface_buf = IfaceArray()

    first = perfstat_id_t()
    first.name = b""

    ret = lib.perfstat_netinterface(
        ctypes.byref(first),
        ctypes.cast(iface_buf, ctypes.POINTER(perfstat_netinterface_t)),
        ctypes.sizeof(perfstat_netinterface_t),
        nifaces,
    )
    if ret < 0:
        logger.error("perfstat_netinterface enumeration returned %d", ret)
        return {}

    interfaces = {}
    ts = time.time()
    for i in range(ret):
        buf = iface_buf[i]
        entry = {
            "iface":        buf.name.decode("ascii", errors="replace").rstrip("\x00"),
            "description":  buf.description.decode("ascii", errors="replace").rstrip("\x00"),
            "type":         buf.type,
            "mtu":          buf.mtu,
            "ipackets":     buf.ipacets,    # correct the libperfstat.h typo at output time
            "ibytes":       buf.ibytes,
            "ierrors":      buf.ierrors,
            "opackets":     buf.opackets,
            "obytes":       buf.obytes,
            "oerrors":      buf.oerrors,
            "collisions":   buf.collisions,
            "bitrate":      buf.bitrate,
            "if_iqdrops":   buf.if_iqdrops,
            "if_arpdrops":  buf.if_arpdrops,
            "_time":        ts,
        }
        interfaces[entry["iface"]] = entry
    logger.debug("get_interfaces: collected %d interfaces", len(interfaces))
    for iface, e in interfaces.items():
        logger.debug("get_interfaces:   %s ibytes=%d obytes=%d ierrors=%d oerrors=%d "
                     "bitrate=%d if_iqdrops=%d if_arpdrops=%d",
                     iface, e["ibytes"], e["obytes"], e["ierrors"], e["oerrors"],
                     e["bitrate"], e["if_iqdrops"], e["if_arpdrops"])
    return interfaces


class AixNetwork:
    """AIX network interface gatherer using libperfstat.

    Exposes:
        interfaces — per-interface stats dict keyed by interface name
                     (e.g. 'en0', 'lo0'), each entry from
                     perfstat_netinterface_t with '_time'.
    """

    def UpdateValues(self):
        """Refresh interfaces by calling perfstat_netinterface() again."""
        logger.debug("AixNetwork.UpdateValues: starting")
        self.interfaces = get_interfaces()
        logger.debug("AixNetwork.UpdateValues: complete (%d interfaces)", len(self.interfaces))

    def __init__(self):
        logger.debug("AixNetwork: initializing")
        self.UpdateValues()


if __name__ == "__main__":
    import pprint
    pprint.PrettyPrinter(indent=4).pprint(AixNetwork().interfaces)
