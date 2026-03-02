# Linux network interface gatherer. Reads /proc/net/dev.
#
# Exposes a Network class. After instantiation:
#   interfaces — dict keyed by interface name (e.g. 'eth0', 'lo'), each entry
#                containing all /proc/net/dev counters plus '_time'.
#
# All counter fields are cumulative since boot; compute rates by differencing
# adjacent samples at query time (see SCHEMA.md).
#
# /proc/net/dev format (16 fields per interface after the name):
#   Receive:  bytes packets errs drop fifo frame compressed multicast
#   Transmit: bytes packets errs drop fifo colls carrier  compressed
#
# References:
#   https://www.kernel.org/doc/html/latest/networking/statistics.html
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


class Network:
    proc_net_dev_path = "/proc/net/dev"

    def get_interfaces(self):
        """Parse /proc/net/dev and return a dict of per-interface counters.

        Each entry is keyed by interface name (e.g. 'eth0', 'lo') and contains
        integer counters mapped by NET_DEV_KEYS, plus a '_time' timestamp.
        Returns False if /proc/net/dev is unreadable.
        """
        logger.debug("get_interfaces: reading %s", self.proc_net_dev_path)
        if util.caniread(self.proc_net_dev_path) is False:
            logger.error("Fatal: Can't open %s for reading.", self.proc_net_dev_path)
            return False

        interfaces = {}
        ts = time.time()
        with open(self.proc_net_dev_path, "r") as reader:
            # Skip the two header lines.
            reader.readline()
            reader.readline()
            line = reader.readline()
            while line:
                # Lines look like:  eth0: 12345 678 0 0 0 0 0 0 98765 432 0 0 0 0 0 0
                # The interface name is followed by a colon; strip it before splitting.
                line = line.strip()
                if not line:
                    line = reader.readline()
                    continue
                colon = line.index(":")
                iface = line[:colon].strip()
                fields = line[colon + 1:].split()
                interfaces[iface] = dict(zip(NET_DEV_KEYS, map(int, fields)))
                interfaces[iface]["_time"] = ts
                line = reader.readline()
        logger.debug("get_interfaces: collected %d interfaces", len(interfaces))
        for iface, stats in interfaces.items():
            logger.debug("get_interfaces:   %s ibytes=%d obytes=%d ierrors=%d oerrors=%d idrop=%d odrop=%d",
                         iface,
                         stats["ibytes"], stats["obytes"],
                         stats["ierrors"], stats["oerrors"],
                         stats["idrop"], stats["odrop"])
        return interfaces

    def __init__(self):
        self.interfaces = self.get_interfaces()


if __name__ == "__main__":
    import pprint
    import util  # pylint: disable=import-error
    pprint.PrettyPrinter(indent=4).pprint(Network().interfaces)
else:
    from . import util
