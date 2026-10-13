/* SPDX-License-Identifier: MIT
 * Product-private session seam: no engine ABI changes. The generator always
 * resets KV before prefill; deterministic paths never read it. Load exact int8
 * CDSR files into that idle arena, share one hash buffer, discard all views
 * before any forward. Model arithmetic/context/KV precision stay unchanged. */
#include <stdio.h>
#include <string.h>
#include "internal.h"
#include "learned.h"
static const char *model_directory;
enum { ACT_BYTES = 22660, OP_BYTES = 11452, TAG_BYTES = 5224,
       BLOB_BYTES = ACT_BYTES + OP_BYTES + TAG_BYTES };
static const char *const names[] = {"round3-act.cdsr", "round3-op.cdsr", "round3-tag.cdsr"};
static const size_t sizes[] = {ACT_BYTES, OP_BYTES, TAG_BYTES};
static const uint8_t hashes[3][32] = {
 {0xe4,0x67,0x81,0xff,0xcd,0xbf,0xf4,0x85,0xf3,0x3f,0xcc,0x91,0x8d,0xff,0xc5,0x99,0x4d,0x3d,0xa8,0x26,0x24,0x1a,0xe5,0x4a,0x71,0x2b,0xef,0xb3,0x8a,0x1a,0x7a,0x86},
 {0xaa,0x82,0x5e,0x49,0x2e,0x45,0xb5,0x37,0xdf,0x09,0x15,0x0e,0x64,0x91,0x56,0x36,0xcb,0xa7,0x77,0xca,0x7e,0x9e,0x2d,0xdb,0xaa,0xdc,0x2c,0x9e,0x30,0xdb,0x5d,0xd1},
 {0x6b,0x7b,0xd4,0xdb,0x55,0x9f,0xd9,0x36,0xf1,0xa2,0x60,0xa4,0x50,0x03,0xda,0x88,0x13,0x5e,0x69,0xdc,0x61,0x81,0x4b,0x2e,0xc5,0x14,0x51,0xba,0x5c,0xcc,0xac,0xf4}
};
static int arena(chatds_session *s, uint8_t **blob, cds_router_work **work) {
    if (!s || s->kv_bytes / 2 < BLOB_BYTES + sizeof(cds_router_work)) return -1;
    *blob = (uint8_t *)s->values;
    *work = (cds_router_work *)(*blob + BLOB_BYTES);
    return 0;
}
static int load(int head, uint8_t *blob, cds_router *r) {
    char path[512]; uint8_t hash[32];
    if (!model_directory || snprintf(path, sizeof path, "%s%s", model_directory, names[head]) >= (int)sizeof path) return -1;
    FILE *f = fopen(path, "rb"); if (!f) return -1;
    /* No per-file stdio read buffer: avoid a new high-water heap allocation. */
    setvbuf(f, NULL, _IONBF, 0);
    int bad = fread(blob, 1, sizes[head], f) != sizes[head];
    bad |= fgetc(f) != EOF || ferror(f); bad |= fclose(f) != 0;
    if (bad) return -1;
    cds_router_sha256(blob, sizes[head], hash);
    if (memcmp(hash, hashes[head], 32) || cds_router_open(r, blob, sizes[head], 1)) return -1;
    return 0;
}
static int models(chatds_session *s, cds_round3 *r, cds_router_work **work) {
    uint8_t *blob; if (arena(s, &blob, work)) return -1;
    if (load(0, blob, &r->act) || load(1, blob + ACT_BYTES, &r->op) ||
        load(2, blob + ACT_BYTES + OP_BYTES, &r->tag)) return -1;
    r->act_threshold = 1793; r->op_threshold = 386; r->tag_threshold = 0;
    return 0;
}
int c24_models_init(chatds_session *s, const char *directory) {
    cds_round3 r; cds_router_work *work;
    model_directory = directory;
    return models(s, &r, &work);
}
int c24_act(chatds_session *s, const char *q, int32_t *margin) {
    cds_round3 r; cds_router_work *work; uint8_t *blob;
    if (arena(s, &blob, &work) || load(0, blob, &r.act)) return -1;
    r.act_threshold = 1793;
    return cds_round3_act(&r, work, q, 0, margin);
}
int c24_text(chatds_session *s, const char *q, cds_round3_text *result, char *out, size_t cap) {
    cds_round3 r; cds_router_work *work;
    if (models(s, &r, &work)) return -1;
    return cds_round3_textop(&r, work, q, result, out, cap);
}
