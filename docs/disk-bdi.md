/sys/class/bdi:
        0:48:	            /sys/devices/virtual/bdi/0:48
        259:0:	            /sys/devices/virtual/bdi/259:0
        259:1:	            /sys/devices/virtual/bdi/259:1
        8:0:	            /sys/devices/virtual/bdi/8:0
        8:16:	            /sys/devices/virtual/bdi/8:16
        8:32:	            /sys/devices/virtual/bdi/8:32
        9:127:	            /sys/devices/virtual/bdi/9:127
        cifs-1:	            /sys/devices/virtual/bdi/cifs-1
        cifs-2:	            /sys/devices/virtual/bdi/cifs-2

*** Directories under /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/nvme0n1:
    bdi:	           l/sys/devices/virtual/bdi/259:0/
        ---> /sys/devices/virtual/bdi/259:0:
            max_ratio:	            "100"
            min_ratio:              "0"
            power:	                Not interesting
            read_ahead_kb:	        "128"
            stable_pages_required:  "0"
            subsystem:             l/sys/class/bdi/ -> Could be useful to explore for block devices mostly uninteresting
            uevent:                 Empty
        <--- END /sys/devices/virtual/bdi/259:0

*** Entries under: /sys/block/sda/bdi/ -> /sys/devices/virtual/bdi/8:0/
        ---> /sys/block/sda/bdi/ -> /sys/devices/virtual/bdi/8:0/
            max_ratio:                  "100"
            min_ratio:                  "0"
            read_ahead_kb:	            "128"
            stable_pages_required:	    "0"
            uevent:	                    Empty
            power/:	                    /sys/devices/virtual/bdi/8:0/power
            --->
                async:                  "disabled"
                autosuspend_delay_ms:   Input/output error
                control:                "auto"
                runtime_active_kids:    "0"
                runtime_active_time:    "0"
                runtime_enabled:        "disabled"
                runtime_status:         "unsupported"
                runtime_suspended_time: "0"
                runtime_usage:          "0"
            <---

            subsystem/:	                l/sys/class/bdi
            --->Filled with symlinks to other bdi class devices
                0:48:	 /sys/devices/virtual/bdi/0:48
                259:0:	 /sys/devices/virtual/bdi/259:0
                259:1:	 /sys/devices/virtual/bdi/259:1
                8:0:	 /sys/devices/virtual/bdi/8:0
                8:16:	 /sys/devices/virtual/bdi/8:16
                8:32:	 /sys/devices/virtual/bdi/8:32
                9:127:	 /sys/devices/virtual/bdi/9:127
                cifs-1:	 /sys/devices/virtual/bdi/cifs-1
                cifs-2:	 /sys/devices/virtual/bdi/cifs-2
            <---
