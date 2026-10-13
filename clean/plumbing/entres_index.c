/* SPDX-License-Identifier: MIT
 * ER1 sidecar reader; one sector, no allocation, bounded bucket scans. */
#include "entres_index.h"
#include <string.h>
static uint32_t u32(const unsigned char *b) {
  return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) |
         ((uint32_t)b[3] << 24);
}
static unsigned u16(const unsigned char *b) {
  return b[0] | ((unsigned)b[1] << 8);
}
static uint32_t hash(const unsigned char *b, size_t n) {
  uint32_t h = 2166136261u;
  for (size_t i = 0; i < n; i++)
    h = (h ^ b[i]) * 16777619u;
  return h;
}
static int rd(cds4_kb *x, uint32_t off, unsigned n, unsigned char *out) {
  if (off > x->size || n > x->size - off) {
    x->err = CDS4_E_CORRUPT;
    return -1;
  }
  while (n) {
    uint32_t s = off / 512, at = off % 512;
    unsigned take = 512 - at;
    if (take > n)
      take = n;
    if (x->sector != s) {
      unsigned bytes = x->size - s * 512;
      if (bytes > 512)
        bytes = 512;
      if ((x->fault_after >= 0 &&
           x->sector_reads >= (uint32_t)x->fault_after) ||
          fseek(x->f, (long)(s * 512), SEEK_SET) ||
          fread(x->buf, 1, bytes, x->f) != bytes) {
        x->err = CDS4_E_IO;
        x->sector = UINT32_MAX;
        return -1;
      }
      x->sector = s;
      x->sector_reads++;
    }
    memcpy(out, x->buf + at, take);
    out += take;
    off += take;
    n -= take;
  }
  return 0;
}
cds4_open_status cds4_ent_open(cds4_kb *x, const char *path, cds4_kb *base) {
  unsigned char h[512], bh[64];
  memset(x, 0, sizeof *x);
  x->sector = UINT32_MAX;
  x->fault_after = -1;
  x->f = fopen(path, "rb");
  if (!x->f)
    return CDS4_OPEN_MISSING;
  if (fseek(x->f, 0, SEEK_END))
    goto io;
  long real = ftell(x->f);
  if (real < 512 || real > 64L * 1024 * 1024)
    goto bad;
  if (fseek(x->f, 0, SEEK_SET) || fread(h, 1, 512, x->f) != 512 ||
      fseek(base->f, 0, SEEK_SET) || fread(bh, 1, 64, base->f) != 64)
    goto io;
  x->size = u32(h + 8);
  x->nb = u32(h + 12);
  x->bt = u32(h + 20);
  x->ko = u32(h + 24);
  x->ro = base->fwo - base->ro;
  if (memcmp(h, "ER1\0", 4) || u32(h + 4) != 1 || x->size != (uint32_t)real ||
      !x->nb || (x->nb & (x->nb - 1)) || x->nb > 1000000 ||
      u32(h + 16) > 1000000 || x->bt != 512 || x->ko % 512 ||
      x->ko >= x->size || x->ko < 512 || x->ko - x->bt < 4 * (x->nb + 1) ||
      u32(h + 28) != base->size || u32(h + 32) != hash(bh, 64))
    goto bad;
  return CDS4_OPEN_OK;
io:
  cds4_close(x);
  return CDS4_OPEN_IO;
bad:
  cds4_close(x);
  return CDS4_OPEN_CORRUPT;
}
int cds4_ent_lookup(cds4_kb *x, const char *key, cds4_cand out[4],
                    unsigned char pop[4], unsigned char weak[4]) {
  size_t n = strlen(key);
  unsigned char b[64], raw[52];
  x->lookups++;
  if (!n || n > 63)
    return 0;
  uint32_t h = hash((const unsigned char *)key, n);
  if (rd(x, x->bt + 4 * (h & (x->nb - 1)), 8, b))
    return -1;
  uint32_t a = u32(b), e = u32(b + 4);
  if (a > e || e > x->size - x->ko || e - a > 4096)
    goto bad;
  while (a < e) {
    if (e - a < 6 || rd(x, x->ko + a, 6, b))
      goto bad;
    uint32_t hh = u32(b);
    unsigned kl = b[4], nc = b[5], len = 6 + kl + 13 * nc;
    if (!kl || kl > 63 || !nc || nc > 4 || len > e - a)
      goto bad;
    if (hh == h && kl == n) {
      if (rd(x, x->ko + a + 6, kl, b))
        return -1;
      if (!memcmp(b, key, n)) {
        if (rd(x, x->ko + a + 6 + kl, 13 * nc, raw))
          return -1;
        for (unsigned i = 0; i < nc; i++) {
          const unsigned char *p = raw + 13 * i;
          out[i].recoff = u32(p);
          out[i].kind = p[4];
          out[i].prom = p[5];
          out[i].etype = p[6];
          out[i].pmask = (uint16_t)u16(p + 7);
          out[i].mmask = (uint16_t)u16(p + 9);
          pop[i] = p[11];
          weak[i] = p[12];
          if (out[i].recoff > x->ro - 2 || out[i].kind > 3 ||
              out[i].prom > 63 || out[i].etype > 4 || pop[i] > 63 ||
              weak[i] > 1 || (out[i].pmask | out[i].mmask) >> 14)
            goto bad;
        }
        return (int)nc;
      }
    }
    a += len;
  }
  return 0;
bad:
  if (!x->err)
    x->err = CDS4_E_CORRUPT;
  return -1;
}
