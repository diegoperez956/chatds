/* SPDX-License-Identifier: MIT
 * KB4 reader, twin of corpus/kb/kb4.py (layout: corpus/kb/FORMAT-KB4.md). */
#include <string.h>
#include <errno.h>
#include "kb4.h"

#define SECTOR 512u
#define MAX_SPAN 4096u
#define NOFF 16

const char *const cds4_rel_name[C4R_COUNT] = {"definition", "date_range", "birth_date", "birth_place", "death_date",
                                              "death_place", "location", "surname", "capital", "occupation", "quantity", "creator", "height", "length"};

static uint32_t le32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint32_t le16(const unsigned char *p) { return p[0] | (uint32_t)p[1] << 8; }

static uint32_t fnv1a(const char *s, size_t n) {
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < n; i++)
        h = (h ^ (unsigned char)s[i]) * 16777619u;
    return h;
}

static void fail(cds4_kb *kb, int e) {
    if (!kb->err)
        kb->err = e;
}

static int fill(cds4_kb *kb, uint32_t s) {
    uint32_t n = kb->size - s * SECTOR < SECTOR ? kb->size - s * SECTOR : SECTOR;
    if (kb->fault_after >= 0 && (long)kb->sector_reads >= kb->fault_after) {
        kb->sector = UINT32_MAX;
        return -1;
    }
    for (int tries = 0; tries < 2; tries++) { /* one retry: a card read can fail transiently */
        clearerr(kb->f);
        if (fseek(kb->f, (long)s * SECTOR, SEEK_SET) == 0 && fread(kb->buf, 1, n, kb->f) == n) {
            kb->sector = s;
            kb->sector_reads++;
            return 0;
        }
    }
    kb->sector = UINT32_MAX;
    return -1;
}

static int rd(cds4_kb *kb, uint32_t off, void *dst, uint32_t n) {
    unsigned char *d = dst;
    if (kb->err)
        return -1;
    if (off > kb->size || n > kb->size - off) {
        fail(kb, CDS4_E_CORRUPT);
        return -1;
    }
    while (n) {
        uint32_t s = off / SECTOR, at = off % SECTOR, k = SECTOR - at < n ? SECTOR - at : n;
        if (s != kb->sector && fill(kb, s)) {
            fail(kb, CDS4_E_IO);
            return -1;
        }
        memcpy(d, kb->buf + at, k);
        d += k, off += k, n -= k;
    }
    return 0;
}

static int pow2(uint32_t x) { return x && !(x & (x - 1)); }

cds4_open_status cds4_open(cds4_kb *kb, const char *path) {
    unsigned char h[64];
    cds4_open_status st = CDS4_OPEN_CORRUPT;
    memset(kb, 0, sizeof *kb);
    kb->sector = UINT32_MAX;
    kb->fault_after = -1;
    if (!(kb->f = fopen(path, "rb")))
        return errno == ENOENT ? CDS4_OPEN_MISSING : CDS4_OPEN_IO;
    setvbuf(kb->f, NULL, _IONBF, 0);
    long real = -1;
    if (fseek(kb->f, 0, SEEK_END) == 0)
        real = ftell(kb->f);
    if (real < (long)SECTOR || fseek(kb->f, 0, SEEK_SET) || fread(h, 1, sizeof h, kb->f) != sizeof h) {
        st = real < 0 ? CDS4_OPEN_IO : CDS4_OPEN_CORRUPT;
        goto bad;
    }
    kb->version = le32(h + 4);
    if (memcmp(h, "KB4\0", 4) || (kb->version != 4 && kb->version != 41))
        goto bad;
    kb->nb = le32(h + 8), kb->bt = le32(h + 20), kb->ko = le32(h + 24), kb->ro = le32(h + 28);
    kb->size = le32(h + 32);
    kb->fnb = le32(h + 36), kb->fbt = le32(h + 40), kb->fent = le32(h + 44), kb->fwo = le32(h + 48);
    kb->fzmin = le32(h + 60) ? le32(h + 60) : 5;
    if (kb->fzmin < 3 || kb->fzmin > 8)
        goto bad;
    if ((unsigned long)real != kb->size || !pow2(kb->nb) || !pow2(kb->fnb))
        goto bad;
    uint32_t off[] = {kb->bt, kb->ko, kb->ro, kb->fbt, kb->fent, kb->fwo};
    for (unsigned i = 0; i < sizeof off / sizeof *off; i++)
        if (off[i] >= kb->size)
            goto bad;
    if (!(SECTOR <= kb->bt && kb->bt < kb->ko && kb->ko < kb->ro && kb->ro < kb->fwo &&
          kb->fwo < kb->fbt && kb->fbt < kb->fent && kb->fent < kb->size))
        goto bad;
    for (unsigned i = 0; i < sizeof off / sizeof *off; i++)
        if (off[i] % SECTOR) goto bad;
    if ((kb->ko - kb->bt) / 4 <= kb->nb || (kb->fent - kb->fbt) / 4 <= kb->fnb)
        goto bad;
    return CDS4_OPEN_OK;
bad:
    fclose(kb->f);
    kb->f = NULL;
    return st;
}

void cds4_close(cds4_kb *kb) {
    if (kb->f)
        fclose(kb->f);
    kb->f = NULL;
}

static int bucket(cds4_kb *kb, uint32_t tab, uint32_t b, uint32_t *a, uint32_t *e) {
    unsigned char p[8];
    if (rd(kb, tab + 4 * b, p, 8))
        return -1;
    *a = le32(p), *e = le32(p + 4);
    if (*e < *a) {
        fail(kb, CDS4_E_CORRUPT);
        return -1;
    }
    return 0;
}

int cds4_lookup(cds4_kb *kb, const char *key, cds4_cand out[CDS4_CAND_MAX]) {
    unsigned char p[6];
    size_t kl = strlen(key);
    uint32_t a, e;
    kb->lookups++;
    if (kl == 0 || kl > CDS4_KEY_MAX)
        return 0;
    uint32_t h = fnv1a(key, kl);
    if (bucket(kb, kb->bt, h & (kb->nb - 1), &a, &e))
        return -1;
    if (e > kb->ro - kb->ko || e - a > MAX_SPAN * (6 + CDS4_KEY_MAX + 11 * CDS4_CAND_MAX)) {
        fail(kb, CDS4_E_CORRUPT);
        return -1;
    }
    for (uint32_t i = a; i < e;) {
        if (rd(kb, kb->ko + i, p, 6))
            return -1;
        uint32_t ln = p[4], nc = p[5];
        if (ln > CDS4_KEY_MAX || e - i < 6 + ln + 11 * nc || nc == 0 || nc > CDS4_CAND_MAX) {
            fail(kb, CDS4_E_CORRUPT);
            return -1;
        }
        if (le32(p) == h && ln == kl) {
            char k[CDS4_KEY_MAX + 1];
            if (rd(kb, kb->ko + i + 6, k, ln))
                return -1;
            if (memcmp(k, key, ln) == 0) {
                unsigned char raw[11 * CDS4_CAND_MAX];
                if (rd(kb, kb->ko + i + 6 + ln, raw, 11 * nc))
                    return -1;
                for (uint32_t c = 0; c < nc; c++) {
                    const unsigned char *q = raw + 11 * c;
                    out[c].recoff = le32(q), out[c].kind = q[4], out[c].prom = q[5], out[c].etype = q[6];
                    out[c].pmask = (uint16_t)le16(q + 7), out[c].mmask = (uint16_t)le16(q + 9);
                    if (out[c].recoff >= kb->size - kb->ro || out[c].kind > 3 || out[c].etype > 4) {
                        fail(kb, CDS4_E_CORRUPT);
                        return -1;
                    }
                }
                return (int)nc;
            }
        }
        i += 6 + ln + 11 * nc;
    }
    return 0;
}

int cds4_record(cds4_kb *kb, uint32_t recoff, int want_rel, cds4_rec *r) {
    unsigned char hd[2], b[CDS4_REC_MAX];
    if (recoff > kb->fwo - kb->ro || kb->fwo - kb->ro - recoff < 2) {
        fail(kb, CDS4_E_CORRUPT);
        return -1;
    }
    if (rd(kb, kb->ro + recoff, hd, 2))
        return -1;
    uint32_t n = le16(hd);
    if (n < 10 || n > CDS4_REC_MAX || n > kb->fwo - kb->ro - recoff - 2) {
        fail(kb, CDS4_E_CORRUPT);
        return -1;
    }
    if (rd(kb, kb->ro + recoff + 2, b, n))
        return -1;
    memset(r, 0, sizeof *r);
    r->eid = le32(b), r->etype = b[4], r->prom = b[5];
    uint32_t tl = b[6], p = 7;
    if (tl > 63 || p + tl + 1 > n)
        goto bad;
    memcpy(r->title, b + p, tl);
    p += tl;
    uint32_t dl = b[p++];
    if (dl > 111 || p + dl + 1 > n)
        goto bad;
    memcpy(r->def, b + p, dl);
    p += dl;
    uint32_t nf = b[p++];
    if (nf > (kb->version == 41 ? CDS4_MAX_FIELDS : 12))
        goto bad;
    for (uint32_t i = 0; i < nf; i++) {
        if (p + 3 > n)
            goto bad;
        uint32_t rel = b[p], fl = b[p + 1], vl = b[p + 2];
        p += 3;
        if (p + vl > n || rel == 0 || rel >= C4R_COUNT || vl > 63 ||
            (kb->version == 4 && rel > C4R_QUANTITY) || fl > (kb->version == 41 ? 31u : 15u))
            goto bad;
        if (!(fl & 1))
            for (uint32_t x = 0; x < vl; x++)
                if (b[p + x] >= 0x80)
                    goto bad;
        if ((int)rel == want_rel) { /* a repeated relation: the last one wins, like kb4.py */
            r->found = 1;
            memset(&r->f, 0, sizeof r->f);
            r->f.rel = (uint8_t)rel, r->f.flags = (uint8_t)fl, r->f.vlen = (uint8_t)vl;
            if (!(fl & 1))
                memcpy(r->f.value, b + p, vl);
        }
        p += vl;
        if (kb->version == 41) {
            if (p + 4 > n)
                goto bad;
            uint32_t sid = le16(b + p), end_sid = le16(b + p + 2);
            if ((sid >= 250 && sid < 65532) || (end_sid >= 250 && end_sid < 65532)) goto bad;
            if ((int)rel == want_rel) {
                r->f.source_sid = (uint16_t)sid;
                r->f.end_sid = (uint16_t)end_sid;
            }
            p += 4;
        }
    }
    for (uint32_t i = 0; i < tl + dl; i++) /* ASCII only: the renderer and the model input assume it */
        if ((unsigned char)(i < tl ? r->title[i] : r->def[i - tl]) >= 0x80)
            goto bad;
    return 0;
bad:
    fail(kb, CDS4_E_CORRUPT);
    return -1;
}

static int share_variant(const char *a, const char *b) {
    size_t na = strlen(a), nb = strlen(b);
    for (size_t i = 0; i <= na; i++)
        for (size_t j = 0; j <= nb; j++) {
            if (na - (i < na) != nb - (j < nb))
                continue;
            size_t x = 0, y = 0;
            int ok = 1;
            while (x < na || y < nb) {
                if (x == i)
                    x++;
                if (y == j)
                    y++;
                if (x >= na || y >= nb) {
                    ok = x >= na && y >= nb;
                    break;
                }
                if (a[x] != b[y]) {
                    ok = 0;
                    break;
                }
                x++, y++;
            }
            if (ok)
                return 1;
        }
    return 0;
}

int cds4_fuzzy(cds4_kb *kb, const char *q, char out[CDS4_CAND_MAX][CDS4_KEY_MAX + 1], int *known) {
    uint32_t offs[NOFF];
    int noff = 0, nout = 0;
    size_t nq = strlen(q);
    char v[CDS4_KEY_MAX + 1];
    *known = 0;
    if (nq > CDS4_KEY_MAX)
        return 0;
    for (size_t d = nq + 1; d-- > 0;) {
        if (d < nq && d > 0 && q[d] == q[d - 1])
            continue;
        size_t n = 0;
        for (size_t i = 0; i < nq; i++)
            if (i != d)
                v[n++] = q[i];
        uint32_t h = fnv1a(v, n), a, e;
        if (bucket(kb, kb->fbt, h & (kb->fnb - 1), &a, &e))
            return -1;
        if (e > kb->size - kb->fent || (e - a) % 8 || e - a > 8 * MAX_SPAN) {
            fail(kb, CDS4_E_CORRUPT);
            return -1;
        }
        for (uint32_t i = a; i + 8 <= e; i += 8) {
            unsigned char p[8];
            if (rd(kb, kb->fent + i, p, 8))
                return -1;
            if (le32(p) != h)
                continue;
            uint32_t wo = le32(p + 4);
            int at = noff;
            while (at > 0 && offs[at - 1] > wo)
                at--;
            if ((at > 0 && offs[at - 1] == wo) || at == NOFF)
                continue;
            if (noff < NOFF)
                noff++;
            memmove(offs + at + 1, offs + at, (noff - 1 - at) * sizeof *offs);
            offs[at] = wo;
        }
    }
    for (int i = 0; i < noff; i++) {
        unsigned char n;
        char w[256];
        if (nout == CDS4_CAND_MAX && *known)
            break;
        if (offs[i] > kb->size - kb->fwo)
            return nout;
        if (rd(kb, kb->fwo + offs[i], &n, 1) || rd(kb, kb->fwo + offs[i] + 1, w, n))
            return -1;
        if (n > CDS4_KEY_MAX)
            continue;
        w[n] = 0;
        if (strcmp(w, q) == 0) {
            *known = 1;
            continue;
        }
        if (!share_variant(w, q) || nout == CDS4_CAND_MAX)
            continue;
        memcpy(out[nout++], w, n + 1);
    }
    return nout;
}
