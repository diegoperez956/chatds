/* SPDX-License-Identifier: MIT */
#ifndef CDS_ROUND3_H
#define CDS_ROUND3_H
#include "router.h"
#include "textops.h"

enum { R3_NONE, R3_GREETING, R3_THANKS, R3_BYE, R3_IDENTITY, R3_CAPABILITIES,
       R3_HOW_ARE_YOU, R3_COMPLIMENT, R3_INSULT, R3_REPEAT, R3_PUSHBACK };
typedef struct {
    cds_router act, op, tag;
    int32_t act_threshold, op_threshold, tag_threshold;
} cds_round3;
typedef struct {
    int op, start, end, xstart, xend, ystart, yend, repeat;
    int32_t margin, tag_margin;
} cds_round3_text;
/* Caller MUST try rules/prestep first, and pass rules_fired for explicit task
 * routes (text/calc/python/shell/fact) or existing conversation/dialogue acts.
 * Return act id, 0 decline. Never infer dialogue state; caller executes repair. */
int cds_round3_act_eligible(const char *q);
int cds_round3_act(const cds_round3 *r, cds_router_work *work, const char *q,
                  int rules_fired, int32_t *margin);
/* Caller MUST try guarded textops regex first and pass original user bytes,
 * never a state-substituted query. This function executes only a confident
 * int8 op + contiguous token-tag span, never rewritten arguments. */
int cds_round3_textop(const cds_round3 *r, cds_router_work *work, const char *q,
                     cds_round3_text *result, char *out, size_t cap);
/* Lazy loader seam: called for op (1) after cheap eligibility checks and tag
 * (2) only after op acceptance. Nonzero loader result returns -1, fail closed.
 * Preloaded callers keep using cds_round3_textop with no callback. */
typedef int (*cds_round3_load_head)(void *ctx, int head);
int cds_round3_textop_lazy(const cds_round3 *r, cds_router_work *work, const char *q,
                          cds_round3_text *result, char *out, size_t cap,
                          cds_round3_load_head ensure, void *ctx);
#endif
