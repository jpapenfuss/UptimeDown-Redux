Disks are proving to be a pain in the ass.

On a QNAP NAS, /sys/block is not full of symlinks, they're normal directories.

QNAP's OS doens't have /sys/class/block. It has tons of other entries though!

On Debian 10.9, /sys/block/nvme0n1 is a symlink to:
/sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1

And has:


/sys/block/nvme0n1 ->      l/sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1
/sys/dev/block/259:0 ->    l/sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1
/sys/class/block/nvme0n1 ->l/sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1
    ---> /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1/:
        alignment_offset:	"0"
        capability:	        "50"
        dev:	            "259:0"
        discard_alignment:  "0"
        ext_range:	        "256"
        hidden:	            "0"
        inflight:	        "0 0"
        nsid:	            "1"
        range:	            "0"
        removable:	        "0"
        ro:	                "0"
        size:	            "2000409264"
        stat:	            "350368 10216 94989840 133099 1327012 165678 367383712 342754 0 167516 497168 13669 0 1758032920 52066"
        trace:	            If debug is on...
        uevent:	            "MAJOR=259\nMINOR=0\nDEVNAME=nvme0n1\nDEVTYPE=disk"
        wwid:	            "nvme.1cc1-324a34393230313439313534-414441544120535838323030504e50-00000001"

    *** Directories under /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1:
        bdi:	           l/sys/devices/virtual/bdi/259:0/
            --- See disk-bdi.md

        holders/:	        /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1/holders/
            ---> /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1/holders/:
                md127:              l/sys/devices/virtual/block/md127 ----> We will address md* separately
            <--- END /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1/holders/

        power/:	            /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1/power/
            ---> /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1/power/:
                async:                  "disabled"
                autosuspend_delay_ms:   Input/output error
                control:                "auto"
                runtime_active_kids:    "0"
                runtime_active_time:    "0"
                runtime_enabled:        "disabled"
                runtime_status:         "unsupported"
                runtime_suspended_time: "0"
                runtime_usage:          "0"
            <--- END /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1/power/

        integrity/:	        Uninteresting directory contents
        mq/:                it's own big thing, nothign useful
        queue/:	            /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1/queue/ -> Oh boy
            ---> /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1/queue/:
                --- See disk-queue.md
            <--- END /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1/queue/
        slaves/:            Empty for this drive
        subsystem/:	       l/sys/class/block/ -> Back to the class directory


QNAP:
/sys/block/nvme0n1 ->       /sys/block/nvme0n1
    Differences:
        QNAP doesn't have trace directory
bdi ->                      /sys/devices/virtual/bdi/259:0
    Differences:
        None

device ->                   /sys/devices/pci0000:00/0000:00:1b.0/0000:02:00.0/nvme/nvme0
    Differences:
        QNAP doesn't have "address"
        QNAP "nvme0n1" is a symlink back to /sys/block/nvme0n1, Debian it's a normal directory
        QNAP lacks several items under power/

subsystem ->                /sys/block
