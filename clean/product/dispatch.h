/* SPDX-License-Identifier: MIT */
#ifndef CDS_PRODUCT_DISPATCH_H
#define CDS_PRODUCT_DISPATCH_H
#include "chatds_ui_engine.h"
#include "kb4.h"
#include "prestep.h"
#include "rules.h"
#include "mathnb.h"
/* Owns session dialogue, not model KV (KV resets per transformer question).
 * Fixed buffers; calls serialized. No owned heap requests after initialization;
 * c24 card-head views borrow idle main-RAM KV values until generator reset. */
typedef struct { char title[64], def[112]; } c14_identity;
typedef struct {
    chatds_ui_engine_gen *g;
    cds4_kb kb4;
    union { cds4_ctx_storage retrieval; c14_identity identities[12]; } scratch;
    cds4_result evidence;
    cds_dlg dlg;
    char q[128], inner[128], effective[128];
    char path[40], template_name[32];
    c14_decision dec;
    int style, state_row, keep, no_style, deterministic, finalized;
    int learned_act, learned_text;
    int32_t act_margin, op_margin, tag_margin;
    size_t shown;
    mnb_spec mathnb;
    mnb_values mathnb_values;
    int mathnb_active;
} c14_runtime;
int c14_open(c14_runtime *r, chatds_ui_engine_gen *g, const char *kb4_path);
void c14_close(c14_runtime *r);
int c14_begin(c14_runtime *r, const char *question);
chatds_gen_event c14_step(c14_runtime *r, char *out, size_t cap, size_t *len);
void c14_cancel(c14_runtime *r);
int c14_log(c14_runtime *r, const char *directory);
#endif
