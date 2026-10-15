/* SPDX-License-Identifier: MIT */
#ifndef CDS_PRODUCT_LEARNED_H
#define CDS_PRODUCT_LEARNED_H
#include "chatds_engine.h"
#include "round3.h"
/* Single serialized product session. Cache in main-RAM values across
 * deterministic turns; invalidate BEFORE any generator reset/forward.
 * Init checks workspace only; file validation is lazy and fails closed. */
int c24_models_init(chatds_session *session, const char *directory);
void c24_models_invalidate(chatds_session *session);
int c24_act(chatds_session *session, const char *q, int32_t *margin);
int c24_text(chatds_session *session, const char *q, cds_round3_text *result,
             char *out, size_t cap);
#endif
