# Linux network interface gatherer. Reads /proc/net/dev and /sys/class/net.
#
# Exposes a Network class. After instantiation:
#   interfaces — dict keyed by interface name (e.g. 'eth0', 'lo'), each entry
#                containing /proc/net/dev counters plus metadata (mtu, speed, operstate).
#
# Counter fields are cumulative since boot; compute rates by differencing
# adjacent samples at query time (see SCHEMA.md).
#
# /proc/net/dev format (16 fields per interface after the name):
#   Receive:  bytes packets errs drop fifo frame compressed multicast
#   Transmit: bytes packets errs drop fifo colls carrier  compressed
#
# References:
#   https://www.kernel.org/doc/html/latest/networking/statistics.html
import sys
sys.dont_write_bytecode = True
import logging
import time

logger = logging.getLogger("monitoring")
logger.addHandler(logging.NullHandler())

# Field names for /proc/net/dev counters, in column order.
# The interface name is stripped before zipping, so it is not listed here.
NET_DEV_KEYS = (
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
)


def _read_metadata(iface):
    """Read interface metadata from /sys/class/net.

    Attempts to read mtu, speed (Mbps), operstate, and type. Returns a dict
    with available fields. Missing files are silently omitted.

    Returns a dict with any of: mtu (int), speed_mbps (int), operstate (str),
    type (int, ARPHRD code: 1=Ethernet, 24=loopback; matches AIX interface type).
    """
    metadata = {}
    sysfs_base = f"/sys/class/net/{iface}"

    mtu = util.read_sysfs_int(f"{sysfs_base}/mtu")
    if mtu is not None:
        metadata["mtu"] = mtu

    # speed: -1 means unknown/unavailable — omit it to avoid confusion.
    speed_val = util.read_sysfs_int(f"{sysfs_base}/speed")
    if speed_val is not None and speed_val >= 0:
        metadata["speed_mbps"] = speed_val

    # operstate: up/down/dormant/notpresent/lowerlayerdown/testing
    operstate = util.read_sysfs_str(f"{sysfs_base}/operstate")
    if operstate:
        metadata["operstate"] = operstate

    # type: ARPHRD code — matches AIX perfstat 'type' field.
    # Common values: 1=Ethernet, 24=loopback, 772=loopback (older kernels).
    iface_type = util.read_sysfs_int(f"{sysfs_base}/type")
    if iface_type is not None:
        metadata["type"] = iface_type

    return metadata


class Network:
    """Linux network interface gatherer. Reads /proc/net/dev and /sys/class/net.

    After instantiation:
        interfaces — dict keyed by interface name (e.g. 'eth0', 'lo'), each entry
                     containing the 16 counters from NET_DEV_KEYS plus optional
                     metadata: mtu (int), speed_mbps (int), operstate (str).

    Counter fields are cumulative since boot. Compute rates by differencing
    adjacent samples at query time. Metadata fields are instantaneous state values.
    """

    proc_net_dev_path = "/proc/net/dev"

    def get_interfaces(self, _time=None):
        """Parse /proc/net/dev and augment with metadata from /sys/class/net.

        Each entry is keyed by interface name (e.g. 'eth0', 'lo') and contains:
        - Counters from NET_DEV_KEYS (ibytes, ipackets, etc., 16 fields)
        - Metadata if available: mtu, speed_mbps, operstate

        /proc/net/dev format:
            Line 1: "Inter-|   Receive ..."        (human-readable header, skipped)
            Line 2: " face |bytes packets errs ..."  (column names, skipped)
            Line 3+: " eth0:  12345  678  0  0 ..."  (one line per interface)
        The interface name is delimited by a colon; everything after the colon
        is 16 whitespace-separated integer fields in NET_DEV_KEYS order.

        Returns False if /proc/net/dev is unreadable.
        """
        logger.debug("get_interfaces: reading %s", self.proc_net_dev_path)
        if util.caniread(self.proc_net_dev_path) is False:
            logger.error("Fatal: Can't open %s for reading.", self.proc_net_dev_path)
            return False

        interfaces = {}
        try:
            with open(self.proc_net_dev_path, "r") as reader:
                # Skip the two header lines — they describe column layout but are
                # not machine-parseable; we rely on NET_DEV_KEYS ordering instead.
                reader.readline()
                reader.readline()
                line = reader.readline()
                while line:
                    try:
                        line = line.strip()
                        if not line:
                            line = reader.readline()
                            continue
                        # Split on the first colon to separate interface name from counters.
                        # Example: "  eth0: 12345 678 0 0 0 0 0 0 98765 432 0 0 0 0 0 0"
                        colon = line.index(":")
                        iface = line[:colon].strip()
                        fields = line[colon + 1:].split()
                        entry = util.dict_from_fields(fields, NET_DEV_KEYS)
                        # Augment with metadata from /sys/class/net.
                        entry.update(_read_metadata(iface))
                        interfaces[iface] = entry
                    except (ValueError, IndexError, TypeError) as e:
                        logger.warning("get_interfaces: error parsing interface line: %s", e)
                    line = reader.readline()
        except (IOError, OSError) as e:
            logger.error("linux_network: error reading /proc/net/dev: %s", e)
            return False
        logger.debug("get_interfaces: collected %d interfaces", len(interfaces))
        for iface, stats in interfaces.items():
            logger.debug("get_interfaces:   %s ibytes=%d obytes=%d ierrors=%d oerrors=%d "
                         "idrop=%d odrop=%d ipackets=%d opackets=%d mtu=%s speed=%s",
                         iface,
                         stats["ibytes"], stats["obytes"],
                         stats["ierrors"], stats["oerrors"],
                         stats["idrop"], stats["odrop"],
                         stats["ipackets"], stats["opackets"],
                         stats.get("mtu", "?"), stats.get("speed_mbps", "?"))
        return interfaces

    def __init__(self, _time=None):
        """Read /proc/net/dev and populate self.interfaces."""
        self._ts = _time if _time is not None else time.time()
        self.interfaces = self.get_interfaces(self._ts)


if __name__ == "__main__":
    import pprint
    import util  # pylint: disable=import-error
    pprint.PrettyPrinter(indent=4).pprint(Network().interfaces)
else:
    from . import util
