/sys/block/sda/alignment_offset:    "0"
/sys/block/sda/capability:          "50"
/sys/block/sda/dev:                 "8:0"
/sys/block/sda/discard_alignment:   "0"
/sys/block/sda/events:              ""
/sys/block/sda/events_async:        ""
/sys/block/sda/events_poll_msecs:   "-1"
/sys/block/sda/ext_range:           "256"
/sys/block/sda/hidden:              "0"
/sys/block/sda/inflight:            " 0 0"
/sys/block/sda/range:               "16"
/sys/block/sda/removable:           "0"
/sys/block/sda/ro:                  "0"
/sys/block/sda/size:                "3906830384"
/sys/block/sda/stat:                " 307999 4293 33005812 86693 2900224 540114 576272858 22837764 0 918804168 953669904 0 0 0 0"
/sys/block/sda/uevent:              "MAJOR=8 MINOR=0 DEVNAME=sda DEVTYPE=disk"

    /sys/block/sda/bdi/ -> /sys/devices/virtual/bdi/8:0:
        See bdi.md
    *** End bdi dir

    /sys/block/sda/device/ -> /sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0:

        blacklist:                          ""
        delete:                             Permission Denied
        device_blocked:                     0
        device_busy:                        0
        dh_state:                           detached
        eh_timeout:                         10
        evt_capacity_change_reported:       0
        evt_inquiry_change_reported:        0
        evt_lun_change_reported:            0
        evt_media_change:                   0
        evt_mode_parameter_change_reported: 0
        evt_soft_threshold_reached:         0
        inquiry:	                        3HPE LOGICAL VOLUME 3.00 <contains binary nonprintables>
        iocounterbits:                      32
        iodone_cnt:                         0x30fcb9
        ioerr_cnt:                          0x2
        iorequest_cnt:                      0x30fcb9
        modalias:                           scsi:t-0x00
        model:                              LOGICAL VOLUME
        queue_depth:                        1014
        queue_type:                         simple
        raid_level:                         RAID-0
        rescan:                             Permission Denied
        rev:                                3.00
        sas_address:                        No such device
        scsi_level:                         6
        ssd_smart_path_enabled:             0
        state:                              running
        timeout:                            30
        type:                               0
        uevent:                             DEVTYPE=scsi_device DRIVER=sd MODALIAS=scsi:t-0x00
        vendor:                             HPE
        vpd_pg80:                           <binary data>
        vpd_pg83:                           <binary data>
        wwid:                               naa.600508b1001c1edd68ad278c50c389e7

        block/:
            sda/:
                --- readlink resolves this to /sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0/block/sda
                --- Loops.

        bsg/:
            0:1:0:0/
                dev:                "247:1"
                uevent:         "MAJOR=247 MINOR=1 DEVNAME=bsg/0:1:0:0"
                device/:	l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0:
                    Back to /sys/block/sda/device/, loop

                power/: The usual nothing

                subsystem/:	l/sys/class/bsg:
                    To parent bsg class
            --- End 0:1:0:0/
        --- end bsg/

        driver:	                l/sys/bus/scsi/drivers/sd:
            bind:       Permission denied
            uevent:     Permission denied
            unbind:     Permission denied
            0:1:0:0/:	l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0:
            0:1:0:1/:	l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:1:
            1:0:0:0/:	l/sys/devices/pci0000:00/0000:00:08.1/0000:02:00.3/usb4/4-2/4-2.3/4-2.3:1.0/host1/target1:0:0/1:0:0:0:
            module/:	l/sys/module/sd_mod:
                coresize    "61440"
                initsize    "0"
                initstate   "live"
                refcnt:     "4"
                taint:      ""
                uevent:     Permission Denied
                drivers/
                    scsi:sd/ -> l/sys/bus/scsi/drivers/sd, loop
                holders/ - Empty
                notes/ Internal crap
                sections/ Filled with internal binary/kernel structures pointing to hex
            *** End module/
        *** End Driver

        generic/:	            l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0/scsi_generic/sg1
            dev:                "21:1"
            uevent:             "MAJOR=21 MINOR=1 DEVNAME=sg1"
            device/:            l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0 (loop)
            power/:              The usual power entries
            subsystem:          l/sys/class/scsi_generic
                sg0:	 l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/port-0:1/end_device-0:1/target0:0:0/0:0:0:0/scsi_generic/sg0
                sg1:	 l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0/scsi_generic/sg1
                    This is a loop back to our parent 'generic;
                sg2:	 l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:1/scsi_generic/sg2
                sg3:	 l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:2:0/0:2:0:0/scsi_generic/sg3
                sg4:	 l/sys/devices/pci0000:00/0000:00:08.1/0000:02:00.3/usb4/4-2/4-2.3/4-2.3:1.0/host1/target1:0:0/1:0:0:0/scsi_generic/sg4
            *** End subsystem
        *** End Generic

        power/: The usual useless stuff, but different values.
        scsi_device/:
            0:1:0:0/:
                device/         l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0
                    Loop back to block/sda
                power/ guess what
                subsystem/:     l/sys/class/scsi_device
                uevent:         Empty
            *** End 0:1:0:0. Useless.

        scsi_disk/:	            /sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0/scsi_disk:
            0:1:0:0/:
                allow_restart:              0
                app_tag_own:                0
                cache_type:	                write through
                FUA:                        0
                manage_start_stop:          0
                max_medium_access_timeouts: 2
                max_write_same_blocks:      0
                protection_mode:            none
                protection_type:	        0
                provisioning_mode:	        full
                thin_provisioning:	        0
                uevent:                     Empty
                zeroing_mode:               writesame
                device/:                    l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0:
                    Another loop back to parents

                power/:     Still useless.

                subsystem/:	            l/sys/class/scsi_disk:
                    0:1:0:0/:	        l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0/scsi_disk/0:1:0:0
                        subsystem/:     l/sys/class/scsi_disk
                            Loops back to subsystem
                    0:1:0:1/:	    l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:1/scsi_disk/0:1:0:1:
                    1:0:0:0/:	    l/sys/devices/pci0000:00/0000:00:08.1/0000:02:00.3/usb4/4-2/4-2.3/4-2.3:1.0/host1/target1:0:0/1:0:0:0/scsi_disk/1:0:0:0:
        *** End scsi_disk

        scsi_generic/:	        /sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0/scsi_generic:
            sg1/
                dev:            "21:1"
                power:	        still crap
                uevent:         "MAJOR=21 MINOR=1 DEVNAME=sg1"

                device/:	l/sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0:
                    Loops again.
                subsystem/:	l/sys/class/scsi_generic
                    Loops

        *** END scsi_generic

        subsystem/:             l/sys/bus/scsi:
            Loops
    *** End /sys/block/sda/device/ -> /sys/devices/pci0000:40/0000:40:01.1/0000:43:00.0/host0/target0:1:0/0:1:0:0:


/sys/block/sda/holders/
    Empty

/sys/block/sda/integrity/
    device_is_integrity_capable:	 "0"
    format:	                        "none"
    protection_interval_bytes:	    "0"
    read_verify:	                "0"
    tag_size:	                    "0"
    write_generate:	                "0"

/sys/block/sda/mq/:
    One numbered directory per thread

/sys/block/sda/power/:
    The same crap

/sys/block/sda/queue/
    add_random:             "0"
    chunk_sectors:          "0"
    dax:                    "0"
    discard_granularity:    "0"
    discard_max_bytes:      "0"
    discard_max_hw_bytes:   "0"
    discard_zeroes_data:    "0"
    fua:                    "0"
    hw_sector_size:         "512"
    io_poll:                "1"
    io_poll_delay:          "-1"
    iostats:                "1"
    logical_block_size:     "512"
    max_discard_segments:   "1"
    max_hw_sectors_kb:      "1024"
    max_integrity_segments: "0"
    max_sectors_kb:         "512"
    max_segments:           "257"
    max_segment_size:       "65536"
    minimum_io_size:        "131072"
    nomerges:               "0"
    nr_requests:            "1014"
    optimal_io_size:        "524288"
    physical_block_size:    "4096"
    read_ahead_kb:          "128"
    rotational:             "0"
    rq_affinity:            "1"
    scheduler:              "[none] mq-deadline "
    wbt_lat_usec:           "2000"
    write_cache:            "write through"
    write_same_max_bytes:   "0"
    write_zeroes_max_bytes: "0"
    zoned:                  "none"
*** end /sys/block/sda/queue/

/sys/block/sda/sda1/
    alignment_offset:	"0"
    dev:                "8:1"
    discard_alignment:  0
    inflight:           " 0 0"
    partition:          1
    ro:                 0
    size:               1048576
    start:              2048
    stat:               1229 0 15850 73 3 0 10 0 0 36 44 0 0 0 0
    uevent:	"MAJOR=8 MINOR=1 DEVNAME=sda1 DEVTYPE=partition PARTN=1"

    holders/:
        empty
    power/:
        Crap
    subsystem/:	l/sys/class/block
        Lops back to block class
    trace/:
        act_mask:           "disabled"
        enable:             "0"
        end_lba:            "disabled"
        pid:                "disabled"
        start_lba:          "disabled"
*** end /sys/block/sda/sda1/

/sys/block/sda/sda2/
    See /sys/block/sda/sda1/

/sys/block/sda/sda3/
    See /sys/block/sda/sda1/

/sys/block/sda/slaves/
    Empty

/sys/block/sda/subsystem/ -> l/sys/class/block
    Loops

/sys/block/sda/trace/
    act_mask:   "disabled"
    enable:     "0"
    end_lba:    "disabled"
    pid:        "disabled"
    start_lba:  "disabled"
