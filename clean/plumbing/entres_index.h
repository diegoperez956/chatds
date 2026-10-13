/* SPDX-License-Identifier: MIT */
#ifndef CDS_ENTRES_INDEX_H
#define CDS_ENTRES_INDEX_H
#include "kb4.h"
/* ER1 reuses the sector-cache handle, not the KB4 file format. ro = base record
 * bytes. */
cds4_open_status cds4_ent_open(cds4_kb *idx, const char *path, cds4_kb *base);
int cds4_ent_lookup(cds4_kb *idx, const char *key, cds4_cand out[4],
                    unsigned char pop[4], unsigned char weak[4]);
cds4_status cds4_retrieve_entres(cds4_ctx *ctx, cds4_kb *kb, cds4_kb *idx,
                                 const char *question, int k, int expand,
                                 int routed, cds4_result *res);
#endif
