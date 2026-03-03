device:	           l/sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0
    ---> l/sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0:
        address:                "0000:84:00.0"
        cntlid:                 "1"
        dev:                    "246:0"
        firmware_rev:           "42AZS6AC"
        model:                  "ADATA SX8200PNP"
        rescan_controller:	    Can't read
        reset_controller:	    Can't read
        serial:	                "2J4920149154"
        state:                  "live"
        subsysnqn:              "nqn.2019-12.com.adata:nvm-subsystem-sn-2J4920149154"
        transport:              "pcie"
        uevent:                 "MAJOR=246\nMINOR=0\nDEVNAME=nvme0"
    *** DIRECTORIES UNDER /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0
        device/:	       l/sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/
            aer_dev_correctable:	    "RxErr 0 BadTLP 0 BadDLLP 0 Rollover 0 Timeout 0 NonFatalErr 0 CorrIntErr 0 HeaderOF 0 TOTAL_ERR_COR 0"
            aer_dev_fatal:	            "Undefined 0 DLP 0 SDES 0 TLP 0 FCP 0 CmpltTO 0 CmpltAbrt 0 UnxCmplt 0 RxOF 0 MalfTLP 0 ECRC 0 UnsupReq 0 ACSViol 0 UncorrIntErr 0 BlockedTLP 0 AtomicOpBlocked 0 TLPBlockedErr 0 TOTAL_ERR_FATAL 0"
            aer_dev_nonfatal:	        "Undefined 0 DLP 0 SDES 0 TLP 0 FCP 0 CmpltTO 0 CmpltAbrt 0 UnxCmplt 0 RxOF 0 MalfTLP 0 ECRC 0 UnsupReq 0 ACSViol 0 UncorrIntErr 0 BlockedTLP 0 AtomicOpBlocked 0 TLPBlockedErr 0 TOTAL_ERR_NONFATAL 0"
            ari_enabled:	            "0"
            broken_parity_status:	    "0"
            class:	                    "0x010802"
            config:	                    <Binary data>
            consistent_dma_mask_bits:	"64"
            current_link_speed:	        "8 GT/s"
            current_link_width:	        "4"
            d3cold_allowed:	            "1"
            device:	                    "0x8201"
            dma_mask_bits:	            "64"
            driver_override:	        "(null)"
            enable:	                    "1"
            irq:	                    "54"
            local_cpulist:	            "0-47"
            local_cpus:	                "ffff,ffffffff"
            max_link_speed:	            "8 GT/s"
            max_link_width:	            "4"
            modalias:	                "pci:v00001CC1d00008201sv00001CC1sd00008201bc01sc08i02"
            msi_bus:	                "1"
            numa_node:	                "0"
            pools:	                    "poolinfo - 0.1 prp list 256 0 48 256 3 prp list page 0 56 4096 56"
            remove:	                    Permission denied
            rescan:	                    Permission denied
            reset:	                    Permission denied
            resource:	                "0x00000000ab200000 0x00000000ab203fff 0x0000000000140204 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000 0x0000000000000000"
            resource0:	                Input/output error
            revision:	                "0x03"
            subsystem_device:	        "0x8201"
            subsystem_vendor:	        "0x1cc1"
            uevent:	                    "DRIVER=nvme PCI_CLASS=10802 PCI_ID=1CC1:8201 PCI_SUBSYS_ID=1CC1:8201 PCI_SLOT_NAME=0000:84:00.0 MODALIAS=pci:v00001CC1d00008201sv00001CC1sd00008201bc01sc08i02"
            vendor:	                    "0x1cc1"

            driver/            l/sys/bus/pci/drivers/nvme
                0000:44:00.0/: l/sys/devices/pci0000:40/0000:40:01.2/0000:44:00.0
                0000:84:00.0/: l/sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0
                bind:           Permission Denied
                module/:	   l/sys/module/nvme
                    SEE SEPARATE SECTION
                new_id:         Permission Denied
                remove_id:      Permission Denied
                uevent:         Permission Denied
                unbind:         Permission Denied
            firmware_node/      l/sys/devices/LNXSYSTM:00/LNXSYBUS:00/PNP0A08:01/device:18/device:19
            iommu/              l/sys/devices/pci0000:80/0000:80:00.2/iommu/ivhd1
            iommu_group/        l/sys/kernel/iommu_groups/29
            msi_irqs/
            nvme/
            power/
            subsystem/          l/sys/bus/pci

        <--- END /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/

        nvme0n1/:           Back up to block device

        power/:	            /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/power/
            ---> /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/power/: BORING!
                async:                          "disabled"
                autosuspend_delay_ms:           can't read
                control:                        "auto"
                pm_qos_latency_tolerance_us:    "100000"
                runtime_active_kids:            0
                runtime_active_time:            0
                runtime_enabled:                "disabled"
                runtime_status:                 "unsupported"
                runtime_suspended_time:         "0"
                runtime_usage:                  "0"
            <--- END /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0/power/

        subsystem:  	       l/sys/class/nvme/
            ---> /sys/class/nvme/:
                nvme0              l/sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0 -> Goes back to other explored paths. No reason to enter.
                nvme1              l/sys/devices/pci0000:40/0000:40:01.2/0000:44:00.0/nvme/nvme1
            <--- END /sys/class/nvme/
    *** END DIRECTORIES UNDER /sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0:
    <--- END l/sys/devices/pci0000:80/0000:80:03.1/0000:84:00.0/nvme/nvme0 ---
