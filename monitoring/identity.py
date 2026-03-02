"""System identity module. Provides a unique, immutable identifier for this system.

Works across Linux and AIX (including WPARs and LPARs). On NFS-mounted systems,
uses platform-specific persistent identifiers rather than state files.
"""
import subprocess
import sys
import uuid


def get_system_id():
    """Get platform-specific system ID.

    Returns a unique, immutable identifier for this system:
    - Linux: /etc/machine-id (systemd machine ID)
    - AIX: os_uuid from ODM (works for LPAR and WPAR)
    - Fallback: UUID v4 (generated randomly)

    Returns:
        str: UUID or machine ID string
    """
    platform = sys.platform

    if platform == "linux":
        # Try /etc/machine-id first (systemd standard)
        try:
            with open("/etc/machine-id") as f:
                return f.read().strip()
        except (FileNotFoundError, IOError):
            pass

        # Fall back to DMI product UUID
        try:
            with open("/sys/class/dmi/id/product_uuid") as f:
                return f.read().strip()
        except (FileNotFoundError, IOError):
            pass

    elif platform == "aix":
        # Query AIX ODM for os_uuid (unique per LPAR and WPAR)
        try:
            result = subprocess.check_output(
                ['odmget', '-q', 'name=sys0 and attribute=os_uuid', 'CuAt'],
                stderr=subprocess.DEVNULL,
                text=True
            )
            for line in result.split('\n'):
                if 'value = ' in line:
                    # Extract UUID from: value = "uuid-here"
                    return line.split('"')[1]
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    # Fallback: generate a random UUID v4
    return str(uuid.uuid4())
