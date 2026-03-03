/*
 * Prints sizeof and field offsets for perfstat disk structs.
 * Compile on AIX:
 *   cc -q64 -o dump_offsets dump_offsets.c -lperfstat
 * Run:
 *   ./dump_offsets
 */

#include <stdio.h>
#include <stddef.h>
#include <libperfstat.h>

#define OFF(type, field) printf("  %-40s offset=%4zu  size=%zu\n", \
    #field, offsetof(type, field), sizeof(((type *)0)->field))

int main() {
    printf("perfstat_disk_total_t  sizeof=%zu\n", sizeof(perfstat_disk_total_t));
    OFF(perfstat_disk_total_t, number);
    OFF(perfstat_disk_total_t, size);
    OFF(perfstat_disk_total_t, free);
    OFF(perfstat_disk_total_t, xrate);
    OFF(perfstat_disk_total_t, xfers);
    OFF(perfstat_disk_total_t, wblks);
    OFF(perfstat_disk_total_t, rblks);
    OFF(perfstat_disk_total_t, time);
    OFF(perfstat_disk_total_t, version);
    OFF(perfstat_disk_total_t, rserv);
    OFF(perfstat_disk_total_t, min_rserv);
    OFF(perfstat_disk_total_t, max_rserv);
    OFF(perfstat_disk_total_t, rtimeout);
    OFF(perfstat_disk_total_t, rfailed);
    OFF(perfstat_disk_total_t, wserv);
    OFF(perfstat_disk_total_t, min_wserv);
    OFF(perfstat_disk_total_t, max_wserv);
    OFF(perfstat_disk_total_t, wtimeout);
    OFF(perfstat_disk_total_t, wfailed);
    OFF(perfstat_disk_total_t, wq_depth);
    OFF(perfstat_disk_total_t, wq_time);
    OFF(perfstat_disk_total_t, wq_min_time);
    OFF(perfstat_disk_total_t, wq_max_time);

    printf("\nperfstat_disk_t  sizeof=%zu\n", sizeof(perfstat_disk_t));
    OFF(perfstat_disk_t, name);
    OFF(perfstat_disk_t, description);
    OFF(perfstat_disk_t, vgname);
    OFF(perfstat_disk_t, size);
    OFF(perfstat_disk_t, free);
    OFF(perfstat_disk_t, bsize);
    OFF(perfstat_disk_t, xrate);
    OFF(perfstat_disk_t, xfers);
    OFF(perfstat_disk_t, wblks);
    OFF(perfstat_disk_t, rblks);
    OFF(perfstat_disk_t, qdepth);
    OFF(perfstat_disk_t, time);
    OFF(perfstat_disk_t, adapter);
    OFF(perfstat_disk_t, paths_count);
    OFF(perfstat_disk_t, q_full);
    OFF(perfstat_disk_t, rserv);
    OFF(perfstat_disk_t, rtimeout);
    OFF(perfstat_disk_t, rfailed);
    OFF(perfstat_disk_t, min_rserv);
    OFF(perfstat_disk_t, max_rserv);
    OFF(perfstat_disk_t, wserv);
    OFF(perfstat_disk_t, wtimeout);
    OFF(perfstat_disk_t, wfailed);
    OFF(perfstat_disk_t, min_wserv);
    OFF(perfstat_disk_t, max_wserv);
    OFF(perfstat_disk_t, wq_depth);
    OFF(perfstat_disk_t, wq_sampled);
    OFF(perfstat_disk_t, wq_time);
    OFF(perfstat_disk_t, wq_min_time);
    OFF(perfstat_disk_t, wq_max_time);
    OFF(perfstat_disk_t, q_sampled);
    OFF(perfstat_disk_t, wpar_id);
    OFF(perfstat_disk_t, version);
    OFF(perfstat_disk_t, dk_type);

    printf("\nperfstat_cpu_total_t  sizeof=%zu\n", sizeof(perfstat_cpu_total_t));
    printf("perfstat_partition_total_t  sizeof=%zu\n", sizeof(perfstat_partition_total_t));

    return 0;
}
