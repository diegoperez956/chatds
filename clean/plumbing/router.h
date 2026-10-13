/* SPDX-License-Identifier: MIT
 * Learned router inference: fixed-point hashed word+char n-gram featurizer, int8 weights, integer accumulation,
 * margin output.  Twin of the featurizer/reader in campaign/router/round3.py.
 * No floats, no heap.  Called by round3.c; the product (clean/product/learned.c) owns the sidecar bytes.
 *
 * Sidecar file ("CDSR", little endian, 64-byte header, then body; sha256 covers the body):
 *   0  char[4] "CDSR"        4  u16 version (1)       6  u16 header_len (64)
 *   8  u8 kind (0 flat, 1 two-level)  9 u8 nheads  10 u8 nroutes  11 u8 nhandlers  12 u16 dims (pow2 <= 4096)
 *   14 u16 taxonomy (route count: 4,6,8,12,16,24,32,45)  16 u32 body_len  20 u8[32] sha256(body)  52..63 zero
 * body: route_handler[nroutes] (u8, 255 = route spans several canonical handlers)
 *       route_group[nroutes]   (u8, margin group: handler id, or 100+route for multi-handler routes)
 *       handler_default[nhandlers] (u8 route, 255 = handler has several routes)      -> pad to 4
 *       per head: u8 owner(255 none) u8 nout u16 0 | f32 q (host only) | u8 out_route[nout] (255 none) -> pad to 4
 *                 int8 W[dims][nout] (feature-major) | int16 bias[nout] -> pad to 4
 * Score of output c = sum_j acc_j*W[j][c] + n*bias[c]  (int32), n = max(1, sum_j |acc_j|); acc clipped to [-7,7].
 * margin_q8 = ((best - best_other_group) << 8) / n  (int64 intermediate, truncating). */
#ifndef CDS_ROUTER_H
#define CDS_ROUTER_H
#include <stddef.h>
#include <stdint.h>

#define CDS_ROUTER_MAX_DIMS 4096
#define CDS_ROUTER_MAX_ROUTES 48
#define CDS_ROUTER_MAX_HEADS 10
#define CDS_ROUTER_MAX_HANDLERS 8
#define CDS_ROUTER_QMAX 127
#define CDS_ROUTER_NONE 255

enum { CDS_ROUTER_OK = 0, CDS_ROUTER_E_MAGIC = -1, CDS_ROUTER_E_VERSION = -2, CDS_ROUTER_E_SIZE = -3, CDS_ROUTER_E_SHA = -4,
       CDS_ROUTER_E_LIMITS = -5 };

typedef struct {
    uint8_t owner, nout;
    const uint8_t *out_route; /* nout entries */
    const int8_t *w;          /* dims * nout, feature-major */
    const uint8_t *bias;      /* nout little-endian int16 (unaligned-safe) */
} cds_router_head;

typedef struct {
    uint8_t kind, nheads, nroutes, nhandlers;
    uint16_t dims, taxonomy;
    const uint8_t *route_handler, *route_group, *handler_default;
    cds_router_head head[CDS_ROUTER_MAX_HEADS];
} cds_router; /* a view into the (read-only, possibly ROM/flash-resident) sidecar blob */

typedef struct {
    uint8_t route;   /* chosen route id (index into the taxonomy's route list) */
    uint8_t group;   /* chosen handler group (canonical handler id, or 100+route for multi-handler routes) */
    uint8_t group2;  /* runner-up group: the second candidate path when the margin is low */
    uint8_t handler; /* canonical handler id of route, 255 if the route spans handlers */
    int32_t margin;  /* Q8 (x/256 score-per-L1 units) between group and the best other group */
    int32_t n;       /* L1 norm of the hashed feature vector */
} cds_route_result;

/* Scratch for one query: dims*2 + 4*CDS_ROUTER_MAX_ROUTES*... see cds_router_work_bytes(). */
typedef struct {
    int16_t acc[CDS_ROUTER_MAX_DIMS];
    int32_t s[CDS_ROUTER_MAX_HEADS][CDS_ROUTER_MAX_ROUTES];
} cds_router_work;

int cds_router_open(cds_router *r, const uint8_t *blob, size_t len, int verify_sha);
int cds_router_run(const cds_router *r, cds_router_work *w, const char *question, cds_route_result *out);
size_t cds_router_work_bytes(void);
size_t cds_router_coeff_bytes(const cds_router *r); /* int8 weights + int16 biases, all heads */
void cds_router_sha256(const uint8_t *p, size_t n, uint8_t out[32]);
/* featurizer exposed for tests: fills w->acc (clipped), returns n = max(1, L1) */
int32_t cds_router_features(uint16_t dims, int16_t *acc, const char *question);
#endif
