/* SPDX-License-Identifier: MIT */
#ifndef CDS_PRODUCT_LEARNED_H
#define CDS_PRODUCT_LEARNED_H
#include "chatds_engine.h"
#include "round3.h"
/* Serialized pre-dispatch only. Borrow main-RAM values, invalidated by the
 * next generator reset; never the halfword-only external VRAM keys. */
int c24_models_init(chatds_session *session, const char *directory);
int c24_act(chatds_session *session, const char *q, int32_t *margin);
int c24_text(chatds_session *session, const char *q, cds_round3_text *result,
             char *out, size_t cap);
#endif
