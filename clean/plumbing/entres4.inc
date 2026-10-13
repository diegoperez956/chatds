/* SPDX-License-Identifier: MIT
 * ER1 implementation included in retrieve4.c to share bounded ranking/rendering
 * helpers. Python twin: corpus/kb/entres.py. Legacy entry point never calls
 * this code. */
static const char ER_STOP[] =
    "abt bout u ur ya pls plz wanna gonna cuz guy gal dude person thing stuff "
    "info information know anyone anybody someone somebody actually really "
    "basically quick question could would got gimme lemme reckon uh um "
    "definition get fought take";
static const char *const ER_FROM[] = {
    "abt",   "bout",  "u",    "ur",   "ya",      "pls",   "plz",
    "whos",  "whats", "wot",  "whut", "whatsup", "one",   "two",
    "three", "four",  "five", "six",  "seven",   "eight", "nine",
    "ten",   "ii",    "iii",  "iv",   "v",       "vi",    "vii",
    "viii",  "ix",    "x",    "wwii", "wwiii",   "wwi",   NULL};
static const char *const ER_TO[] = {
    "about", "about", "you",  "your", "you", "please", "please", "who", "what",
    "what",  "what",  "what", "1",    "2",   "3",      "4",      "5",   "6",
    "7",     "8",     "9",    "10",   "2",   "3",      "4",      "5",   "6",
    "7",     "8",     "9",    "10",   "ww2", "ww3",    "ww1"};
typedef struct {
  char keys[24][64];
  int cover[24], typo[24], n;
  char tried[44][64];
  int nt;
} er_keys;
static int er_seen(const er_keys *e, const char *key) {
  for (int i = 0; i < e->nt; i++)
    if (!strcmp(e->tried[i], key))
      return 1;
  return 0;
}
static void er_offer(er_keys *e, const char *key, int cover, int typo) {
  size_t n = strlen(key);
  if (!n || n > 63 || e->n >= 24)
    return;
  for (int i = 0; i < e->n; i++)
    if (e->cover[i] == cover && e->typo[i] == typo && !strcmp(e->keys[i], key))
      return;
  strcpy(e->keys[e->n], key);
  e->cover[e->n] = cover;
  e->typo[e->n++] = typo;
}
static int er_lookup(struct cds4_ctx *x, cds4_kb *kb, cds4_kb *idx,
                     cds4_result *r, er_keys *keys, const char *key, int cover,
                     int typo) {
  cds4_cand main[4], side[4];
  unsigned char pops[4], weak[4];
  if (keys->nt < 44)
    strcpy(keys->tried[keys->nt++], key);
  int nm;
  if (key[0] == '~') { /* reserved signatures do not reach the base index */
    r->keys_tried++;
    for (const char *p = key; *p; p++)
      r->keys_hash = (r->keys_hash ^ (unsigned char)*p) * 16777619u;
    r->keys_hash = (r->keys_hash ^ '\n') * 16777619u;
    nm = 0;
  } else
    nm = lookup_key(x, kb, r, key, main);
  if (nm < 0)
    return -1;
  /* Track route updates without storing a key on every candidate. */
  int oldcover[8], oldtypo[8], oldkind[8], oldn = x->npool;
  for (int i = 0; i < oldn; i++)
    oldcover[i] = x->pool[i].cover, oldtypo[i] = x->pool[i].typo,
    oldkind[i] = x->pool[i].c.kind;
  pool_add(x, main, nm, cover, typo);
  int ns = cds4_ent_lookup(idx, key, side, pops, weak);
  if (ns < 0)
    return -1;
  int title_hit = 0;
  for (int j = 0; j < nm; j++)
    title_hit |= main[j].kind == 0;
  if (!title_hit)
    pool_add(x, side, ns, cover, typo);
  for (int i = 0; i < x->npool; i++) {
    pool_t *p = &x->pool[i];
    int found = 0, minweak = 1, route = 0;
    for (int j = 0; j < nm; j++)
      route |= main[j].recoff == p->c.recoff;
    for (int j = 0; j < ns; j++)
      if (side[j].recoff == p->c.recoff) {
        if (pops[j] > p->pop)
          p->pop = pops[j];
        if (weak[j] < minweak)
          minweak = weak[j];
        found = 1;
        route = 1;
      }
    int updated = i >= oldn || p->cover != oldcover[i] ||
                  p->typo != oldtypo[i] || p->c.kind != oldkind[i];
    if (route && updated)
      strcpy(p->route, key);
    int main_strong = 0;
    for (int j = 0; j < nm; j++)
      main_strong |= main[j].recoff == p->c.recoff && main[j].kind <= 2;
    if (route && !strcmp(p->route, key))
      p->weak = main_strong ? 0
                : found     ? minweak
                            : (p->c.kind == 3 && cover == 1);
    if (key[0] == '~' && route && !strcmp(p->route, key))
      p->weak = 1;
  }
  return nm || ns;
}
static cds4_status er_finish(cds4_kb *kb, cds4_kb *idx, cds4_result *r,
                             uint32_t r0, uint32_t l0, uint32_t ir, uint32_t il,
                             cds4_status st) {
  if (idx) {
    kb->sector_reads += idx->sector_reads - ir;
    kb->lookups += idx->lookups - il;
    if (idx->err)
      kb->err = idx->err;
  }
  return finish(kb, r, r0, l0, st);
}
static int er_content(const struct cds4_ctx *x, int i) {
  int us = x->cwl[i] == 2 && !memcmp(x->cw[i], "us", 2);
  if (us && (i == 0 || !in_list("tell give show", x->cw[i - 1], x->cwl[i - 1])))
    return 1;
  return !is_stopish(x, i) && !in_list(ER_STOP, x->cw[i], x->cwl[i]);
}
/* Remove ASCII possessives and plural apostrophes, preserving gate-visible
 * syntax. */
static void er_clean(const char *q, char *out) {
  size_t k = 0;
  for (size_t i = 0; q[i]; i++) {
    if (q[i] == '\'' && i && letter(q[i - 1])) {
      if ((q[i + 1] == 's' || q[i + 1] == 'S') && !letter(q[i + 2]) &&
          !digit(q[i + 2]) && q[i + 2] != '_') {
        i++;
        continue;
      }
      if ((q[i - 1] == 's' || q[i - 1] == 'S') &&
          (!q[i + 1] || space(q[i + 1]) || strchr("?.!,", q[i + 1])))
        continue;
    }
    out[k++] = q[i];
  }
  out[k] = 0;
}
static int er_perm(int *p, int n) {
  int i = n - 2;
  while (i >= 0 && p[i] >= p[i + 1])
    i--;
  if (i < 0)
    return 0;
  int j = n - 1;
  while (p[j] <= p[i])
    j--;
  int t = p[i];
  p[i] = p[j];
  p[j] = t;
  for (int a = i + 1, b = n - 1; a < b; a++, b--) {
    t = p[a];
    p[a] = p[b];
    p[b] = t;
  }
  return 1;
}
cds4_status cds4_retrieve_entres(cds4_ctx *x, cds4_kb *kb, cds4_kb *idx,
                                 const char *question, int k, int expand,
                                 int routed, cds4_result *res) {
  uint32_t r0 = kb->sector_reads, l0 = kb->lookups,
           ir = idx ? idx->sector_reads : 0, il = idx ? idx->lookups : 0;
  char clean[128];
  er_keys keys;
  memset(&keys, 0, sizeof keys);
  memset(res, 0, sizeof *res);
  res->keys_hash = 2166136261u;
  kb->err = 0;
  if (idx)
    idx->err = 0;
  x->npool = x->ord = 0;
  cds4_status status = CDS4_NO_MATCH;
  if (strlen(question) > 127) {
    res->reason = "too_long";
    status = CDS4_GATED;
    goto done;
  }
  er_clean(question, clean);
  if (cds_normalize(clean, x->norm, sizeof x->norm) < 0) {
    res->reason = "too_long";
    status = CDS4_GATED;
    goto done;
  }
  x->nw = 0;
  for (char *p = x->norm; *p;) {
    char *e = strchr(p, ' ');
    size_t n = e ? (size_t)(e - p) : strlen(p);
    if (x->nw >= 32) {
      res->reason = "too_long";
      status = CDS4_GATED;
      goto done;
    }
    x->w[x->nw] = p;
    x->wl[x->nw++] = (unsigned char)n;
    p += n + (e != NULL);
  }
  const char *g = gate(clean, x);
  if (g) {
    res->reason = g;
    status = CDS4_GATED;
    goto done;
  }
  if (!idx || !idx->f) {
    kb->err = CDS4_E_IO;
    goto done;
  }
  int casual = hasw(typed(x), "tell know gimme lemme");
  for (int i = 0; i < x->nw; i++) {
    for (int j = 0; ER_FROM[j]; j++)
      if (x->wl[i] == strlen(ER_FROM[j]) &&
          !memcmp(x->w[i], ER_FROM[j], x->wl[i])) {
        x->w[i] = ER_TO[j];
        x->wl[i] = (unsigned char)strlen(ER_TO[j]);
        break;
      }
    x->cw[i] = x->w[i];
    x->cwl[i] = x->wl[i];
    x->isent[i] = er_content(x, i);
  }
  if (cue_typos(x, kb) < 0)
    goto done;
  if (!routed && !cue_ok(x) && !casual) {
    res->reason = "no_cue";
    status = CDS4_GATED;
    goto done;
  }
  int rel = parse_relation(x);
  res->field = rel;
  x->total = 0;
  for (int i = 0; i < x->nw; i++) {
    const char *glue = rel == C4R_OCCUPATION ? "kind work"
                       : rel == C4R_QUANTITY ? "big large"
                                             : "";
    x->isent[i] = er_content(x, i) && !in_list(glue, x->cw[i], x->cwl[i]);
    x->total += x->isent[i];
  }
  int cue_entity = x->total == 0;
  if (cue_entity)
    for (int i = 0; i < x->nw; i++) {
      x->isent[i] = !((in_list(STOP, x->w[i], x->wl[i]) ||
                       in_list(FILL, x->w[i], x->wl[i]) ||
                       in_list(ER_STOP, x->w[i], x->wl[i])) &&
                      !in_list(REL_WORDS, x->w[i], x->wl[i]));
      x->total += x->isent[i];
    }
  build_grams(x);
  if (x->total && !cue_entity)
    for (int a = 0, tried = 0; a < x->ng && tried < 12; a++) {
      int c = G_C(x->grams[a]), n = G_N(x->grams[a]), i = G_I(x->grams[a]);
      if (join(x, i, n, -1, NULL, x->key) < 0 || skip_gram(x, i, n))
        continue;
      tried++;
      int got = er_lookup(x, kb, idx, res, &keys, x->key, c, 0);
      if (got < 0)
        goto done;
      if (got && c == x->total)
        break;
    }
  int ew[32], ne = 0;
  for (int i = 0; i < x->nw; i++)
    if (x->isent[i])
      ew[ne++] = i;
  if (ne >= 1 && ne <= 4) {
    int perm[4] = {0, 1, 2, 3};
    for (int t = 0; t < 12; t++) {
      size_t at = 0;
      for (int i = 0; i < ne; i++) {
        int wi = ew[perm[i]];
        unsigned n = x->wl[wi];
        if (at + (i > 0) + n > 63) {
          at = 64;
          break;
        }
        if (i)
          x->key[at++] = ' ';
        memcpy(x->key + at, x->w[wi], n);
        at += n;
      }
      if (at <= 63) {
        x->key[at] = 0;
        er_offer(&keys, x->key, x->total, 0);
      }
      if (t == 0) {
        at = 0;
        for (int i = 0; i < ne; i++) {
          int wi = ew[ne - i - 1];
          unsigned n = x->wl[wi];
          if (at + (i > 0) + n > 63) {
            at = 64;
            break;
          }
          if (i)
            x->key[at++] = ' ';
          memcpy(x->key + at, x->w[wi], n);
          at += n;
        }
        if (at <= 63) {
          x->key[at] = 0;
          er_offer(&keys, x->key, x->total, 0);
        }
      }
      if (!er_perm(perm, ne))
        break;
    }
    size_t at = 0;
    int changed = 0;
    for (int i = 0; i < ne; i++) {
      int wi = ew[i];
      const char *w = x->w[wi];
      unsigned n = x->wl[wi], take = n;
      int y = 0;
      if (n > 4 && !memcmp(w + n - 3, "ies", 3)) {
        take = n - 3;
        y = 1;
        changed = 1;
      } else if (n > 3 && w[n - 1] == 's' && memcmp(w + n - 2, "ss", 2) &&
                 memcmp(w + n - 2, "us", 2) && memcmp(w + n - 2, "is", 2)) {
        take = n - 1;
        changed = 1;
      }
      if (at + (i > 0) + take + y > 63) {
        at = 64;
        break;
      }
      if (i)
        x->key[at++] = ' ';
      memcpy(x->key + at, w, take);
      at += take;
      if (y)
        x->key[at++] = 'y';
    }
    if (changed && at <= 63) {
      x->key[at] = 0;
      er_offer(&keys, x->key, x->total, 1);
    }
  }
  for (int i = 0; i < ne; i++)
    if (x->wl[ew[i]] >= 3 && x->wl[ew[i]] <= 63) {
      memcpy(x->key, x->w[ew[i]], x->wl[ew[i]]);
      x->key[x->wl[ew[i]]] = 0;
      er_offer(&keys, x->key, 1, 0);
    }
  int protected_hit = 0;
  for (int i = 0; i < x->npool; i++)
    protected_hit |= x->pool[i].cover == x->total && !x->pool[i].typo &&
                     !x->pool[i].weak && x->pool[i].c.kind <= 2;
  if (!protected_hit)
    for (int i = 0; i < keys.n; i++)
      if (keys.cover[i] == x->total && !er_seen(&keys, keys.keys[i]) &&
          er_lookup(x, kb, idx, res, &keys, keys.keys[i], keys.cover[i],
                    keys.typo[i]) < 0)
        goto done;
  int expneeded = expand && x->total && !full(x);
  if (expneeded) {
    res->expansion = 1;
    if (expand_round(x, kb, res, cue_entity))
      goto done;
  }
  /* Compact content for the existing two-word fuzzy pass. */
  for (int i = 0; i < ne; i++) {
    x->w[i] = x->w[ew[i]];
    x->wl[i] = x->wl[ew[i]];
    x->isent[i] = 1;
  }
  x->nw = ne;
  build_grams(x);
  if (expneeded) {
    if (!full(x) && expand_round(x, kb, res, cue_entity))
      goto done;
    char sig[8][6];
    int ns = 0;
    for (int i = 0; i < ne; i++)
      if (x->wl[i] >= 2 && x->wl[i] <= 4) {
        for (int d = -1; d < (int)x->wl[i]; d++) {
          char key[6];
          int at = 0;
          key[at++] = '~';
          for (int j = 0; j < x->wl[i]; j++)
            if (j != d)
              key[at++] = x->w[i][j];
          key[at] = 0;
          int dup = 0;
          for (int j = 0; j < ns; j++)
            dup |= !strcmp(sig[j], key);
          if (!dup && ns < 8)
            strcpy(sig[ns++], key);
        }
      }
    if (!full(x))
      for (int i = 0; i < ns; i++)
        if (er_lookup(x, kb, idx, res, &keys, sig[i], 1, 1) < 0)
          goto done;
  }
  if (!full(x))
    for (int i = 0; i < keys.n; i++)
      if (keys.cover[i] < x->total && !er_seen(&keys, keys.keys[i]) &&
          er_lookup(x, kb, idx, res, &keys, keys.keys[i], keys.cover[i],
                    keys.typo[i]) < 0)
        goto done;
  res->candidates = x->npool;
  if (!x->npool) {
    res->reason = "no_candidate";
    goto done;
  }
  int ranked[8];
  for (int i = 0; i < x->npool; i++) {
    pool_t *p = &x->pool[i];
    p->s1 = W_COVER * (100 * p->cover / x->total) + kind_bonus[p->c.kind & 3] +
            p->c.prom - W_TYPO * p->typo;
    p->s2 = p->s1 + rel_score(p, rel);
    ranked[i] = i;
  }
  for (int i = 1; i < x->npool; i++) {
    int v = ranked[i], j = i;
    pool_t *p = &x->pool[v];
    while (j > 0) {
      pool_t *q = &x->pool[ranked[j - 1]];
      if (q->s1 > p->s1 ||
          (q->s1 == p->s1 &&
           (q->pop > p->pop || (q->pop == p->pop && q->ord < p->ord))))
        break;
      ranked[j] = ranked[j - 1];
      j--;
    }
    ranked[j] = v;
  }
  if (k < 2)
    k = 2;
  int nt = x->npool < k ? x->npool : k;
  for (int i = 1; i < nt; i++) {
    int v = ranked[i], j = i;
    pool_t *p = &x->pool[v];
    int ps = p->weak ? p->s1 : p->s2;
    while (j > 0) {
      pool_t *q = &x->pool[ranked[j - 1]];
      int qs = q->weak ? q->s1 : q->s2;
      if (qs > ps || (qs == ps && (q->pop > p->pop ||
                                   (q->pop == p->pop && q->ord < p->ord))))
        break;
      ranked[j] = ranked[j - 1];
      j--;
    }
    ranked[j] = v;
  }
  pool_t *best = &x->pool[ranked[0]],
         *second = nt > 1 ? &x->pool[ranked[1]] : NULL;
  int gap = second ? best->s1 + best->pop - second->s1 - second->pop : 999;
  int close = second && second->cover == best->cover &&
              (best->weak ? best->s1 : best->s2) -
                      (second->weak ? second->s1 : second->s2) <=
                  12 &&
              best->pop - second->pop < 24;
  int floor = best->cover < x->total || best->s1 < 500 ||
              (best->weak && (best->pop < 16 || gap < 32 || best->typo));
  if (cds4_record(kb, best->c.recoff, rel, &x->rec))
    goto done;
  res->eid = x->rec.eid;
  memcpy(res->title, x->rec.title, sizeof res->title);
  if (close || floor) {
    res->reason = floor ? "confidence_floor" : "close_candidates";
    if (second)
      res->alt_recoff[res->n_alt++] = second->c.recoff;
    status = CDS4_AMBIGUOUS;
    goto done;
  }
  const cds4_field *f =
      rel != C4R_DEFINITION && x->rec.found ? &x->rec.f : NULL;
  if (rel != C4R_DEFINITION && (!f || (f->flags & 1))) {
    res->reason = f ? "field_marked_missing" : "field_not_applicable";
    status = CDS4_FIELD_MISSING;
    goto done;
  }
  const char *v = rel == C4R_DEFINITION ? x->rec.def : f->value;
  res->prov = rel == C4R_DEFINITION ? 4 : (uint8_t)((f->flags >> 1) & 7);
  res->field_flags = rel == C4R_DEFINITION ? 0 : f->flags;
  res->source_sid =
      rel == C4R_DEFINITION || kb->version == 4 ? UINT16_MAX : f->source_sid;
  res->end_sid =
      rel == C4R_DEFINITION || kb->version == 4 ? UINT16_MAX : f->end_sid;
  strcpy(res->value, v);
  if (render(&x->rec, rel, v, res->context, sizeof res->context))
    kb->err = CDS4_E_CORRUPT;
  status = CDS4_ANSWER_PRESENT;
done:
  return er_finish(kb, idx, res, r0, l0, ir, il, status);
}
