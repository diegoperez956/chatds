/* SPDX-License-Identifier: MIT
 * Learned router inference; format and semantics in router.h.  Mirrors campaign/router/round3.py byte for byte. */
#include <string.h>
#include "router.h"

/* ------------------------------------------------------------------ sha256 (FIPS 180-4) */
static uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
static const uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be,
    0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa,
    0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85,
    0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
    0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f,
    0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

static void sha_block(uint32_t h[8], const uint8_t *p) {
    uint32_t w[64], a, b, c, d, e, f, g, hh;
    for (int i = 0; i < 16; i++)
        w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; i++) {
        uint32_t t1 = hh + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
        uint32_t t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        hh = g, g = f, f = e, e = d + t1, d = c, c = b, b = a, a = t1 + t2;
    }
    h[0] += a, h[1] += b, h[2] += c, h[3] += d, h[4] += e, h[5] += f, h[6] += g, h[7] += hh;
}

void cds_router_sha256(const uint8_t *p, size_t n, uint8_t out[32]) {
    uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    uint8_t tail[128];
    size_t full = n / 64, rem = n % 64;
    for (size_t i = 0; i < full; i++)
        sha_block(h, p + 64 * i);
    memset(tail, 0, sizeof tail);
    memcpy(tail, p + 64 * full, rem);
    tail[rem] = 0x80;
    size_t tl = rem < 56 ? 64 : 128;
    uint64_t bits = (uint64_t)n * 8;
    for (int i = 0; i < 8; i++)
        tail[tl - 1 - i] = (uint8_t)(bits >> (8 * i));
    sha_block(h, tail);
    if (tl == 128)
        sha_block(h, tail + 64);
    for (int i = 0; i < 8; i++)
        for (int k = 0; k < 4; k++)
            out[4 * i + k] = (uint8_t)(h[i] >> (24 - 8 * k));
}

/* ------------------------------------------------------------------ featurizer */
#define FNV_OFF 2166136261u
#define FNV_PRIME 16777619u
#define CLIP 7

static uint32_t fnv_step(uint32_t h, uint8_t c) { return (h ^ c) * FNV_PRIME; }
static int isword(uint8_t c) { return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'; }

static void put(int16_t *acc, uint16_t dims, uint32_t h) { acc[h & (uint32_t)(dims - 1)] += ((h >> 24) & 1) ? -1 : 1; }

/* C/V/D shape of a word token with repeated classes collapsed, then min(len,12); hashed with tag 'S' */
static uint32_t shape_hash(const uint8_t *t, size_t n) {
    uint32_t h = fnv_step(FNV_OFF, 0x53);
    uint8_t last = 0;
    for (size_t i = 0; i < n; i++) {
        uint8_t c = t[i];
        uint8_t k = (c == 'a' || c == 'e' || c == 'i' || c == 'o' || c == 'u' || c == 'y') ? 'V' : (c >= '0' && c <= '9') ? 'D' : c == '_' ? '_' : 'C';
        if (k != last)
            h = fnv_step(h, k), last = k;
    }
    return fnv_step(h, (uint8_t)(n < 12 ? n : 12));
}

int32_t cds_router_features(uint16_t dims, int16_t *acc, const char *question) {
    uint8_t b[CDS_ROUTER_QMAX + 3];
    size_t n = 0;
    int gap = 0;
    memset(acc, 0, (size_t)dims * sizeof *acc);
    for (const uint8_t *s = (const uint8_t *)question; *s; s++) {
        uint8_t c = *s;
        if (c >= 0x80)
            continue;
        if (c == 32 || (c >= 9 && c <= 13)) {
            gap = n > 0;
            continue;
        }
        if (c >= 'A' && c <= 'Z')
            c += 32;
        if (gap) {
            if (n >= CDS_ROUTER_QMAX)
                break;
            b[n++] = 32, gap = 0;
        }
        if (n >= CDS_ROUTER_QMAX)
            break;
        b[n++] = c;
    }
    while (n && b[n - 1] == 32)
        n--;
    /* tokens: runs of [a-z0-9_], else one-byte punctuation */
    size_t ts = 0, te = 0, ps = 0, pe = 0; /* current token [ts,te), previous token [ps,pe) */
    int have_prev = 0;
    size_t i = 0;
    while (i <= n) {
        size_t s0 = 0, e0 = 0;
        int got = 0;
        while (i < n && b[i] == 32)
            i++;
        if (i < n) {
            s0 = i;
            if (isword(b[i])) {
                while (i < n && isword(b[i]))
                    i++;
            } else
                i++;
            e0 = i, got = 1;
        } else
            i = n + 1;
        if (!got)
            break;
        ts = s0, te = e0;
        uint32_t h = fnv_step(FNV_OFF, 0x77);
        int alldig = 1;
        for (size_t k = ts; k < te; k++)
            h = fnv_step(h, b[k]), alldig &= (b[k] >= '0' && b[k] <= '9');
        put(acc, dims, h);
        if (isword(b[ts]))
            put(acc, dims, shape_hash(b + ts, te - ts));
        if (alldig)
            put(acc, dims, fnv_step(FNV_OFF, 0x23));
        if (have_prev) {
            uint32_t g = fnv_step(FNV_OFF, 0x62);
            for (size_t k = ps; k < pe; k++)
                g = fnv_step(g, b[k]);
            g = fnv_step(g, 32);
            for (size_t k = ts; k < te; k++)
                g = fnv_step(g, b[k]);
            put(acc, dims, g);
        }
        ps = ts, pe = te, have_prev = 1;
    }
    /* char 3- and 4-grams of " " + text + " " */
    uint8_t p[CDS_ROUTER_QMAX + 3];
    size_t pl = n + 2;
    p[0] = 32;
    memcpy(p + 1, b, n);
    p[n + 1] = 32;
    for (int g = 3; g <= 4; g++)
        for (size_t k = 0; k + (size_t)g <= pl; k++) {
            uint32_t h = fnv_step(FNV_OFF, 0x63);
            for (int m = 0; m < g; m++)
                h = fnv_step(h, p[k + (size_t)m]);
            put(acc, dims, h);
        }
    int32_t l1 = 0;
    for (uint16_t j = 0; j < dims; j++) {
        int16_t v = acc[j];
        v = v > CLIP ? CLIP : v < -CLIP ? -CLIP : v;
        acc[j] = v;
        l1 += v < 0 ? -v : v;
    }
    return l1 < 1 ? 1 : l1;
}

/* ------------------------------------------------------------------ sidecar */
static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static size_t pad4(size_t x) { return (x + 3) & ~(size_t)3; }

int cds_router_open(cds_router *r, const uint8_t *blob, size_t len, int verify_sha) {
    if (len < 64 || memcmp(blob, "CDSR", 4))
        return CDS_ROUTER_E_MAGIC;
    if (rd16(blob + 4) != 1 || rd16(blob + 6) != 64)
        return CDS_ROUTER_E_VERSION;
    memset(r, 0, sizeof *r);
    r->kind = blob[8], r->nheads = blob[9], r->nroutes = blob[10], r->nhandlers = blob[11];
    r->dims = rd16(blob + 12), r->taxonomy = rd16(blob + 14);
    uint32_t body = rd32(blob + 16);
    if (r->kind > 1 || r->nheads == 0 || r->nheads > CDS_ROUTER_MAX_HEADS || r->nroutes == 0 || r->nroutes > CDS_ROUTER_MAX_ROUTES ||
        r->nhandlers > CDS_ROUTER_MAX_HANDLERS || r->dims == 0 || r->dims > CDS_ROUTER_MAX_DIMS || (r->dims & (r->dims - 1)))
        return CDS_ROUTER_E_LIMITS;
    if ((size_t)body + 64 != len)
        return CDS_ROUTER_E_SIZE;
    if (verify_sha) {
        uint8_t d[32];
        cds_router_sha256(blob + 64, body, d);
        if (memcmp(d, blob + 20, 32))
            return CDS_ROUTER_E_SHA;
    }
    const uint8_t *p = blob + 64, *end = blob + len;
    size_t need = pad4((size_t)2 * r->nroutes + r->nhandlers);
    if ((size_t)(end - p) < need)
        return CDS_ROUTER_E_SIZE;
    r->route_handler = p, r->route_group = p + r->nroutes, r->handler_default = p + 2 * r->nroutes;
    p += need;
    for (int h = 0; h < r->nheads; h++) {
        if (end - p < 8)
            return CDS_ROUTER_E_SIZE;
        cds_router_head *hd = &r->head[h];
        hd->owner = p[0], hd->nout = p[1];
        if (hd->nout == 0 || hd->nout > CDS_ROUTER_MAX_ROUTES)
            return CDS_ROUTER_E_LIMITS;
        p += 8; /* owner,nout,pad16, q f32 */
        size_t o = pad4(hd->nout), w = (size_t)r->dims * hd->nout, bb = (size_t)hd->nout * 2;
        if ((size_t)(end - p) < o + pad4(w) + pad4(bb))
            return CDS_ROUTER_E_SIZE;
        hd->out_route = p, p += o;
        hd->w = (const int8_t *)p, p += pad4(w);
        hd->bias = p, p += pad4(bb);
    }
    return p == end ? CDS_ROUTER_OK : CDS_ROUTER_E_SIZE;
}

size_t cds_router_work_bytes(void) { return sizeof(cds_router_work); }

size_t cds_router_coeff_bytes(const cds_router *r) {
    size_t t = 0;
    for (int h = 0; h < r->nheads; h++)
        t += (size_t)r->dims * r->head[h].nout + 2u * r->head[h].nout;
    return t;
}

/* ------------------------------------------------------------------ inference */
static void head_scores(const cds_router *r, const cds_router_head *hd, const int16_t *acc, int32_t n, int32_t *s) {
    int no = hd->nout;
    for (int c = 0; c < no; c++)
        s[c] = n * (int16_t)rd16(hd->bias + 2 * c);
    for (uint16_t j = 0; j < r->dims; j++) {
        int a = acc[j];
        if (!a)
            continue;
        const int8_t *w = hd->w + (size_t)j * no;
        for (int c = 0; c < no; c++)
            s[c] += a * w[c];
    }
}

static int32_t margin_q8(int32_t top, int32_t other, int32_t n) { return (int32_t)((((int64_t)top - other) * 256) / n); }

/* sub-route for canonical handler hi using heads 1.. (later heads override earlier ones that have candidates) */
static int sub_route(const cds_router *r, int32_t s[][CDS_ROUTER_MAX_ROUTES], int hi) {
    int route = r->handler_default[hi];
    for (int h = 1; h < r->nheads; h++) {
        const cds_router_head *hd = &r->head[h];
        if (hd->owner != CDS_ROUTER_NONE && hd->owner != hi)
            continue;
        int best = -1;
        for (int k = 0; k < hd->nout; k++) {
            int rt = hd->out_route[k];
            if (rt == CDS_ROUTER_NONE || r->route_handler[rt] != hi)
                continue;
            if (best < 0 || s[h][k] > s[h][best])
                best = k;
        }
        if (best >= 0)
            route = hd->out_route[best];
    }
    return route;
}

int cds_router_run(const cds_router *r, cds_router_work *w, const char *question, cds_route_result *out) {
    int32_t n = cds_router_features(r->dims, w->acc, question);
    for (int h = 0; h < r->nheads; h++)
        head_scores(r, &r->head[h], w->acc, n, w->s[h]);
    const int32_t *s0 = w->s[0];
    int no = r->head[0].nout;
    out->n = n;
    if (r->kind == 0) {
        int best = 0;
        for (int c = 1; c < no; c++)
            if (s0[c] > s0[best])
                best = c;
        int rt = r->head[0].out_route[best] == CDS_ROUTER_NONE ? best : r->head[0].out_route[best];
        int g = r->route_group[rt], o2 = -1;
        for (int c = 0; c < no; c++) {
            int rc = r->head[0].out_route[c] == CDS_ROUTER_NONE ? c : r->head[0].out_route[c];
            if (r->route_group[rc] != g && (o2 < 0 || s0[c] > s0[o2]))
                o2 = c;
        }
        out->route = (uint8_t)rt, out->group = (uint8_t)g, out->handler = r->route_handler[rt];
        out->group2 = o2 < 0 ? CDS_ROUTER_NONE : r->route_group[r->head[0].out_route[o2] == CDS_ROUTER_NONE ? o2 : r->head[0].out_route[o2]];
        out->margin = o2 < 0 ? 0x7fffffff : margin_q8(s0[best], s0[o2], n);
        return 0;
    }
    int g1 = 0, g2 = -1;
    for (int c = 1; c < no; c++)
        if (s0[c] > s0[g1])
            g1 = c;
    for (int c = 0; c < no; c++)
        if (c != g1 && (g2 < 0 || s0[c] > s0[g2]))
            g2 = c;
    out->group = (uint8_t)g1, out->group2 = g2 < 0 ? CDS_ROUTER_NONE : (uint8_t)g2;
    out->margin = g2 < 0 ? 0x7fffffff : margin_q8(s0[g1], s0[g2], n);
    int rt = sub_route(r, w->s, g1);
    out->route = (uint8_t)rt;
    out->handler = rt == CDS_ROUTER_NONE ? CDS_ROUTER_NONE : r->route_handler[rt];
    return 0;
}
