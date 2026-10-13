/* SPDX-License-Identifier: MIT
 * Host driver for test_retrieve4.py: test-retrieve4 KB4.bin K EXPAND [FAULT_AFTER [ROUTED]] < queries (one per line)
 * prints one TSV row per query; the Python twin (corpus/kb/retrieve4.py) must print the same rows. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "kb4.h"
#include "entres_index.h"

int main(int argc, char **argv) {
    static cds4_kb kb, idx;
    static cds4_ctx_storage st;
    static cds4_result r;
    char line[1024];
    if (argc < 4)
        return 2;
    cds4_open_status os = cds4_open(&kb, argv[1]);
    if (os != CDS4_OPEN_OK) {
        printf("open_failed\t%d\n", (int)os);
        return 0;
    }
    int entres = argc > 6;
    if (entres && cds4_ent_open(&idx, argv[6], &kb) != CDS4_OPEN_OK) {
        printf("open_failed\tentres\n");
        cds4_close(&kb);
        return 0;
    }
    int k = atoi(argv[2]), expand = atoi(argv[3]);
    long fault = argc > 4 ? atol(argv[4]) : -1;
    int routed = argc > 5 ? atoi(argv[5]) : 0;
    printf("ctx_bytes\t%zu\tkb_bytes\t%zu\tresult_bytes\t%zu\n", cds4_ctx_size(), sizeof kb, sizeof r);
    while (fgets(line, sizeof line, stdin)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = 0;
        kb.sector = UINT32_MAX;
        kb.fault_after = fault >= 0 ? (long)kb.sector_reads + fault : -1;
        idx.sector = UINT32_MAX;
        cds4_status s = entres ? cds4_retrieve_entres((cds4_ctx *)&st, &kb, &idx, line, k, expand, routed, &r)
                              : cds4_retrieve((cds4_ctx *)&st, &kb, line, k, expand, routed, &r);
        printf("%s\t%s\t%u\t%s\t%s\t%s\t%u\t%u\t%d\t%u\t%d\t%d\t%s\t%u\t%u\t%u\t%u", cds4_status_name[s],
               s == CDS4_GATED || s >= CDS4_IO_ERROR ? "-" : cds4_rel_name[r.field], s >= CDS4_NO_MATCH ? 0u : r.eid,
               s >= CDS4_NO_MATCH ? "" : r.title, r.value, r.context, r.sector_reads, r.lookups, r.keys_tried, r.keys_hash,
               r.candidates, r.expansion, r.reason ? r.reason : "", r.prov,
               s == CDS4_ANSWER_PRESENT ? r.source_sid : 0u, (r.field_flags & 16) != 0,
               s == CDS4_ANSWER_PRESENT ? r.end_sid : 0u);
        if (entres) printf("\t%d\t%u", r.n_alt, r.n_alt ? r.alt_recoff[0] : 0u);
        putchar('\n');
        kb.err = 0;
    }
    if (entres) cds4_close(&idx);
    cds4_close(&kb);
    return 0;
}
