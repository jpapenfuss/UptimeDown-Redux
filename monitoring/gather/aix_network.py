# AIX network interface gatherer. Uses libperfstat via ctypes to call
# perfstat_netinterface().
#
# Exposes an AixNetwork class. After instantiation:
#   interfaces — dict keyed by interface name (e.g. 'en0', 'lo0'), each entry
#                containing all perfstat_netinterface_t counters.
#
# All counter fields are cumulative since boot; compute rates by differencing
# adjacent samples at query time (see SCHEMA.md).
#
# References:
#   https://www.ibm.com/docs/en/aix/7.3?topic=interfaces-perfstat-netinterface-interface
#   OpenJDK shenandoah libperfstat_aix.hpp for struct layout
import sys
sys.dont_write_bytecode = True
import ctypes
import time
import logging

try:
    from . import aix_util
except ImportError:
    import aix_util  # type: ignore

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())

# IDENTIFIER_LENGTH matches IDENTIFIER_LENGTH in libperfstat.h (64 bytes).
# Kept here because it is used in the struct field definitions below.
IDENTIFIER_LENGTH = 64


class perfstat_netinterface_t(ctypes.Structure):
    """Per-interface network statistics — perfstat_netinterface_t.

    Layout: char[64] name, char[64] description, uchar type (1 byte),
    7 bytes implicit padding to align the following u_longlong_t to 8 bytes,
    then 11 × u_longlong_t fields.
    sizeof == 224.

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


def get_interfaces(_time=None):
    """Call perfstat_netinterface() and return per-interface stats as a dict.

    Uses aix_util.perfstat_enumerate() to handle the two-call enumeration pattern.

    Output keys are normalized to schema column names:
        ipacets    → ipackets  (corrects the long-standing typo in libperfstat.h)
        if_iqdrops → idrop     (input queue drops; matches Linux idrop)

    Counter fields (ibytes, obytes, ipackets, opackets, ierrors, oerrors,
    collisions, idrop, if_arpdrops) are cumulative since boot. Rates
    should be computed at query time by differencing adjacent rows.

    Returns a dict keyed by interface name (e.g. 'en0', 'lo0'), or an empty
    dict on error.
    """
    logger.debug("get_interfaces: calling perfstat_netinterface (count query + enumeration)")
    try:
        lib = aix_util.load_libperfstat()
    except (OSError, AttributeError, ctypes.ArgumentError) as e:
        logger.error("aix_network: could not load libperfstat: %s", e)
        return {}

    try:
        iface_structs = aix_util.perfstat_enumerate(lib, lib.perfstat_netinterface, perfstat_netinterface_t)
        if not iface_structs:
            logger.error("aix_network: perfstat_netinterface enumeration failed")
            return {}
    except (OSError, AttributeError, ctypes.ArgumentError) as e:
        logger.error("aix_network: perfstat_netinterface enumeration failed: %s", e)
        return {}

    interfaces = {}
    try:
        for buf in iface_structs:
            iface_name = buf.name.decode("ascii", errors="replace").rstrip("\x00")
            entry = {
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
                "speed_mbps":   buf.bitrate // 1_000_000,  # bps → Mbps; matches Linux speed_mbps
                "idrop":        buf.if_iqdrops,             # input queue drops; matches Linux idrop
                "if_arpdrops":  buf.if_arpdrops,
            }
            interfaces[iface_name] = entry
    except (AttributeError, TypeError, ValueError, ZeroDivisionError) as e:
        logger.error("aix_network: error processing interface structs: %s", e)
        return {}
    logger.debug("get_interfaces: collected %d interfaces", len(interfaces))
    for iface, e in interfaces.items():
        logger.debug("get_interfaces:   %s ibytes=%d obytes=%d ierrors=%d oerrors=%d "
                     "speed_mbps=%d idrop=%d if_arpdrops=%d",
                     iface, e["ibytes"], e["obytes"], e["ierrors"], e["oerrors"],
                     e["speed_mbps"], e["idrop"], e["if_arpdrops"])
    return interfaces


class AixNetwork:
    """AIX network interface gatherer using libperfstat.

    Exposes:
        interfaces — per-interface stats dict keyed by interface name
                     (e.g. 'en0', 'lo0'), each entry from
                     perfstat_netinterface_t.
    """

    def UpdateValues(self):
        """Refresh interfaces by calling perfstat_netinterface() again."""
        logger.debug("AixNetwork.UpdateValues: starting")
        ts = getattr(self, '_ts', None)
        self.interfaces = get_interfaces(ts)
        logger.debug("AixNetwork.UpdateValues: complete (%d interfaces)", len(self.interfaces))

    def __init__(self, _time=None):
        """Initialise the gatherer and immediately collect interface stats."""
        self._ts = _time if _time is not None else time.time()
        logger.debug("AixNetwork: initializing")
        self.UpdateValues()


if __name__ == "__main__":
    import pprint
    pprint.PrettyPrinter(indent=4).pprint(AixNetwork().interfaces)
