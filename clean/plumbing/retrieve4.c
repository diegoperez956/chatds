/* SPDX-License-Identifier: MIT
 * KB4 ranked entity + relation retrieval: C twin of corpus/kb/retrieve4.py (weights, word lists and order of
 * operations must stay identical; clean/plumbing/test_retrieve4.py checks the two on thousands of queries).
 * Fixed buffers, bounded loops, no malloc. */
#include <string.h>
#include "kb4.h"
#include "plumbing.h"
#include "entres_index.h"

#define W_COVER 6
#define W_TYPO 40
#define W_PROM 1
#define W_REL_PRESENT 60
#define W_REL_MISSING 20
#define AMBIG_GAP 12
#define MAX_KEYS 12
#define MAX_FKEYS 16
#define FZ_WORDS 8
#define MAX_F2KEYS 16
#define CONTENT_MIN 4

const char *const cds4_status_name[7] = {"answer_present", "field_missing", "ambiguous", "no_match", "gated", "io_error", "corrupt_kb"};

static const int kind_bonus[4] = {8, 6, 4, -20};

/* word lists: identical to retrieve4.py (test_retrieve4.py diffs them) */
static const char STOP[] =
    "what who where when why how is are was were the a an of in on to do does can i you me my your "
    "tell about whats which whom this that it its and or for with at by from be as if so please explain define "
    "describe give say know mean means there their they he she we us our "
    "continent currency language capital country city money name main official primary spoken speak located called "
    "use used people plus minus times divided multiply add subtract percent calculate much";
static const char CUES[] = "who what whats where when which define explain describe";
static const char REL_WORDS[] =
    "last surname family capital born birth birthday birthdate birthplace died die dies death dead job occupation "
    "profession career population years year date dates start started begin began end ended lasted happen happened occur "
    "occurred located location situated country continent place state town live lives living pass passed away "
    "author authored inventor invented creator created wrote written founded established known tall height length long";
static const char GATE_REL[] =
    "surname capital born birth birthday birthplace died die dies death population occupation profession job "
    "years year date dates lasted located location happened";
static const char AUX[] = "did has have had will would old long many";
static const char FILL[] = "hi hello hey thanks thank now good morning afternoon evening ok okay yo";
static const char CONVERSATION[] =
    "hi hello hey heyy hii hello chatds thanks thank thx thankyou ok okay cool fine good great nice yep yup yeah yes no nah lol lmao haha hehe sup wassup yo bye goodbye cya see ya later for now you too morning evening afternoon well doing im i am alright awesome sure dude bro mate much not nm nothing bored tired sad happy hiya howdy greetings friend k understood then laters tomorrow";
static const char WHERE[] = "where place birthplace city town country state";
static const char *const CUE_TYPO[] = {"born", "died", "birth", "death", "birthday", "capital", "population", "surname", "occupation", "profession", "last", "name", "family", "where", "birthplace", "started", "founded", "established", NULL};
static const char CODE_OPS[] = "print return sort reverse loop function variable command dict";
static const char NUM_WORDS[] =
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million";
static const char MATH_WORDS[] =
    "half double twice triple quarter over sum product added add subtract subtracted multiply divide difference "
    "squared cubed and away take more less than";
static const char ARITH_WORDS[] = "plus minus times divided multiplied percent";

typedef struct {
    cds4_cand c;
    int cover, typo, s1, s2, ord, pop, weak;
    char route[64];
} pool_t;

struct cds4_ctx {
    char norm[CDS4_QUESTION_MAX + 1];
    const char *w[CDS4_MAX_WORDS];  /* the words as typed */
    unsigned char wl[CDS4_MAX_WORDS];
    const char *cw[CDS4_MAX_WORDS]; /* the words with relation-word typos repaired (what parse_relation sees) */
    unsigned char cwl[CDS4_MAX_WORDS];
    unsigned char isent[CDS4_MAX_WORDS];
    int nw, total;
    uint16_t grams[4 * CDS4_MAX_WORDS];
    int ng;
    pool_t pool[CDS4_POOL];
    int npool, ord;
    char key[CDS4_KEY_MAX + 1];
    char fz[CDS4_CAND_MAX][CDS4_KEY_MAX + 1];
    char unk[2][CDS4_CAND_MAX][CDS4_KEY_MAX + 1]; /* corrections of the first two unknown words (two-word pass) */
    int unk_j[2], unk_n[2], nunk;
    cds4_rec rec;
    int tried; /* lookups spent in the expansion round */
};

size_t cds4_ctx_size(void) { return sizeof(struct cds4_ctx); }
typedef char ctx_fits[sizeof(struct cds4_ctx) <= CDS4_CTX_BYTES ? 1 : -1];

static int in_list(const char *list, const char *w, size_t n) {
    for (const char *p = list; *p;) {
        const char *e = strchr(p, ' ');
        size_t k = e ? (size_t)(e - p) : strlen(p);
        if (k == n && memcmp(p, w, n) == 0)
            return 1;
        p += k + (e != NULL);
    }
    return 0;
}

typedef struct {
    const char *const *w;
    const unsigned char *l;
    int n;
} view_t;
static view_t typed(const struct cds4_ctx *x) { view_t v = {x->w, x->wl, x->nw}; return v; }
static view_t fixed(const struct cds4_ctx *x) { view_t v = {x->cw, x->cwl, x->nw}; return v; }

static int hasw(view_t v, const char *list) {
    for (int i = 0; i < v.n; i++)
        if (in_list(list, v.w[i], v.l[i]))
            return 1;
    return 0;
}
static int is_word(view_t v, const char *s) {
    size_t n = strlen(s);
    for (int i = 0; i < v.n; i++)
        if (v.l[i] == n && memcmp(v.w[i], s, n) == 0)
            return 1;
    return 0;
}
static int has_pair(view_t v, const char *a, const char *b) {
    size_t na = strlen(a), nb = strlen(b);
    for (int i = 0; i + 1 < v.n; i++)
        if (v.l[i] == na && v.l[i + 1] == nb && memcmp(v.w[i], a, na) == 0 && memcmp(v.w[i + 1], b, nb) == 0)
            return 1;
    return 0;
}
static int hasany(view_t v, const char *const *ws) {
    for (; *ws; ws++)
        if (is_word(v, *ws))
            return 1;
    return 0;
}

static int letter(char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
static int digit(char c) { return c >= '0' && c <= '9'; }
static int op(char c) { return c && strchr("-+*/%^", c); }
static int space(char c) { return c && strchr(" \t\n\r\v\f\x1c\x1d\x1e\x1f", c); }

static int stretched(const char *w, size_t n, const char *base) {
    size_t k = strlen(base);
    if (n < k || memcmp(w, base, k)) return 0;
    for (size_t i = k; i < n; i++) if (w[i] != base[k - 1]) return 0;
    return 1;
}
static int conversation_act(const struct cds4_ctx *x) {
    if (!x->nw || x->nw > 4) return 0;
    for (int j = 0; j < x->nw; j++) {
        const char *w = x->w[j]; size_t n = x->wl[j];
        int haha = n >= 6 && n % 2 == 0;
        for (size_t i = 0; i < n && haha; i++) haha = w[i] == (i % 2 ? 'a' : 'h');
        if (!in_list(CONVERSATION, w, n) && !stretched(w, n, "hey") &&
            !stretched(w, n, "hi") && !stretched(w, n, "hello") && !haha) return 0;
    }
    return 1;
}

/* NULL if the question may reach the KB, else the reason */
static const char *gate(const char *q, const struct cds4_ctx *x) {
    view_t v = typed(x);
    if (conversation_act(x))
        return "conversation";
    for (const char *p = q; *p; p++)
        if (strchr("()[]{}=\"`_", *p))
            return "code_chars";
    for (size_t i = 0; q[i]; i++)
        if (q[i] == '\'' && (i == 0 || !letter(q[i - 1]) || !letter(q[i + 1])))
            return "quote";
    for (size_t i = 0; q[i]; i++) {
        if (!digit(q[i]) && !op(q[i]))
            continue;
        size_t j = i + 1;
        while (space(q[j]))
            j++;
        if (digit(q[i]) ? op(q[j]) : digit(q[j]))
            return "arith";
    }
    if (hasw(v, CODE_OPS))
        return "code_op";
    int num = hasw(v, NUM_WORDS);
    int hasnum = num;
    for (const char *p = q; *p && !hasnum; p++)
        hasnum = digit(*p);
    if (num && hasw(v, MATH_WORDS))
        return "arith_words";
    if (hasnum && hasw(v, ARITH_WORDS))
        return "arith_words";
    return NULL;
}

/* a question word, 'tell me about', or a relation word (after leading greetings/filler), on the typo-repaired words */
static int cue_ok(const struct cds4_ctx *x) {
    view_t v = fixed(x);
    int rel = hasw(v, GATE_REL) || has_pair(v, "last", "name") || has_pair(v, "family", "name") || has_pair(v, "many", "people");
    int i0 = 0;
    while (i0 < x->nw && in_list(FILL, x->cw[i0], x->cwl[i0]))
        i0++;
    if (i0 < x->nw && (in_list(CUES, x->cw[i0], x->cwl[i0]) || rel))
        return 1;
    /* "tell me about " on the repaired words: compare word by word */
    static const char *const tell[] = {"tell", "me", "about", NULL};
    for (int t = 0; tell[t]; t++) {
        size_t n = strlen(tell[t]);
        if (i0 + t >= x->nw || x->cwl[i0 + t] != n || memcmp(x->cw[i0 + t], tell[t], n))
            return 0;
    }
    return i0 + 3 < x->nw; /* the python test is startswith("tell me about "): a word must follow */
}

static int parse_relation(const struct cds4_ctx *x) {
    view_t v = fixed(x);
    int where = hasw(v, WHERE);
    if (is_word(v, "surname") || has_pair(v, "last", "name") || has_pair(v, "family", "name"))
        return C4R_SURNAME;
    if (is_word(v, "capital"))
        return C4R_CAPITAL;
    static const char *const born[] = {"born", "birth", "birthday", "birthdate", "birthplace", NULL};
    static const char *const died[] = {"died", "die", "dies", "death", "dead", NULL};
    static const char *const job[] = {"job", "occupation", "profession", "career", NULL};
    static const char *const date[] = {"years", "year", "date", "long", "dates", "start", "started", "begin", "began", "end", "ended",
                                       "lasted", "happen", "happened", "occur", "occurred", "when", "founded", "established", NULL};
    static const char *const loc[] = {"where", "located", "location", "situated", "country", "continent", NULL};
    if (hasany(v, born))
        return where ? C4R_BIRTH_PLACE : C4R_BIRTH_DATE;
    if (hasany(v, died) || has_pair(v, "pass", "away") || has_pair(v, "passed", "away"))
        return where ? C4R_DEATH_PLACE : C4R_DEATH_DATE;
    if (hasany(v, job) || (is_word(v, "do") && (is_word(v, "did") || is_word(v, "does")))) /* "what did X do" */
        return C4R_OCCUPATION;
    if (hasw(v, "author authored inventor invented creator created wrote written") && !hasw(v, "when year date"))
        return C4R_CREATOR;
    if (hasw(v, "tall height"))
        return C4R_HEIGHT;
    if (is_word(v, "length") || (is_word(v, "long") && is_word(v, "how") && !is_word(v, "did")))
        return C4R_LENGTH;
    if (is_word(v, "population") || has_pair(v, "many", "people"))
        return C4R_QUANTITY;
    if (is_word(v, "old"))
        return C4R_BIRTH_DATE;
    if (hasany(v, date))
        return C4R_DATE_RANGE;
    if (hasany(v, loc))
        return C4R_LOCATION;
    return C4R_DEFINITION;
}

/* ---- rendering ---- */
static const char *const MONTH[12] = {"January", "February", "March", "April", "May", "June", "July", "August",
                                      "September", "October", "November", "December"};

typedef struct {
    char *p;
    size_t cap, n;
    int over;
} sb_t;
static void sb_add(sb_t *b, const char *s) {
    size_t k = strlen(s);
    if (b->n + k + 1 > b->cap) {
        b->over = 1;
        return;
    }
    memcpy(b->p + b->n, s, k + 1);
    b->n += k;
}
static void sb_num(sb_t *b, int v) {
    char t[16];
    int n = 0, neg = v < 0;
    unsigned u = neg ? 0u - (unsigned)v : (unsigned)v;
    do
        t[n++] = (char)('0' + u % 10), u /= 10;
    while (u);
    char r[18];
    int m = 0;
    if (neg)
        r[m++] = '-';
    while (n)
        r[m++] = t[--n];
    r[m] = 0;
    sb_add(b, r);
}

/* "-?Y{1,4}(-MM(-DD)?)?"; returns the number of '-'-separated parts after the sign, 0 = invalid */
static int parse_iso(const char *s, size_t n, int *y, int *m, int *d, int *bc) {
    size_t i = 0;
    int parts = 0, v[3] = {0, 0, 0};
    *bc = 0;
    if (n && s[0] == '-')
        *bc = 1, i = 1;
    while (i <= n && parts < 3) {
        size_t st = i;
        int val = 0;
        while (i < n && digit(s[i]))
            val = val * 10 + (s[i] - '0'), i++;
        size_t len = i - st;
        if (parts == 0 ? (len < 1 || len > 4) : len != 2)
            return 0;
        v[parts++] = val;
        if (i == n)
            break;
        if (s[i] != '-')
            return 0;
        i++;
    }
    if (i != n)
        return 0;
    *y = v[0], *m = parts > 1 ? v[1] : 0, *d = parts > 2 ? v[2] : 0;
    if (parts > 1 && (*m < 1 || *m > 12))
        return 0;
    if (parts > 2 && (*d < 1 || *d > 31))
        return 0;
    return parts;
}

/* ISO date -> "14 October 1066" / "October 1066" / "1066" / "428 BC" in out; *on = full date (day given) */
static int date_text(char *out, size_t cap, const char *s, size_t n, int *on) {
    int y, m, d, bc, parts = parse_iso(s, n, &y, &m, &d, &bc);
    sb_t b = {out, cap, 0, 0};
    out[0] = 0;
    if (!parts)
        return -1;
    if (on)
        *on = parts == 3;
    if (parts == 3)
        sb_num(&b, d), sb_add(&b, " ");
    if (parts >= 2)
        sb_add(&b, MONTH[m - 1]), sb_add(&b, " ");
    sb_num(&b, y);
    if (bc)
        sb_add(&b, " BC");
    return b.over ? -1 : 0;
}

int cds4_date_text(char *out, size_t cap, const char *value) {
    return date_text(out, cap, value, strlen(value), NULL);
}

static int render(const cds4_rec *rec, int rel, const char *v, char *out, size_t cap) {
    sb_t b = {out, cap, 0, 0};
    char t[64], d1[40], d2[40];
    size_t tl = strlen(rec->title);
    int on = 0;
    out[0] = 0;
    memcpy(t, rec->title, tl + 1);
    if (tl && t[tl - 1] == ')') { /* drop the " (qualifier)" */
        char *q = NULL;
        for (char *p = t; (p = strstr(p, " (")) != NULL; p++)
            q = p;
        if (q)
            *q = 0;
    }
    switch (rel) {
    case C4R_DEFINITION:
        sb_add(&b, v);
        break;
    case C4R_DATE_RANGE: {
        const char *sl = strchr(v, '/');
        if (sl == v) {
            if (date_text(d2, sizeof d2, sl + 1, strlen(sl + 1), &on)) return -1;
            sb_add(&b, t), sb_add(&b, on ? " ended on " : " ended in "), sb_add(&b, d2);
        } else if (sl) {
            if (date_text(d1, sizeof d1, v, (size_t)(sl - v), NULL) || date_text(d2, sizeof d2, sl + 1, strlen(sl + 1), NULL))
                return -1;
            sb_add(&b, t), sb_add(&b, " was from "), sb_add(&b, d1), sb_add(&b, " to "), sb_add(&b, d2);
        } else {
            if (date_text(d1, sizeof d1, v, strlen(v), &on))
                return -1;
            sb_add(&b, t), sb_add(&b, on ? " was on " : " was in "), sb_add(&b, d1);
        }
        sb_add(&b, ".");
        break;
    }
    case C4R_BIRTH_DATE:
    case C4R_DEATH_DATE:
        if (date_text(d1, sizeof d1, v, strlen(v), &on))
            return -1;
        sb_add(&b, t), sb_add(&b, rel == C4R_BIRTH_DATE ? " was born " : " died "), sb_add(&b, on ? "on " : "in "), sb_add(&b, d1);
        sb_add(&b, ".");
        break;
    case C4R_BIRTH_PLACE:
    case C4R_DEATH_PLACE:
        sb_add(&b, t), sb_add(&b, rel == C4R_BIRTH_PLACE ? " was born in " : " died in "), sb_add(&b, v), sb_add(&b, ".");
        break;
    case C4R_LOCATION:
        sb_add(&b, t), sb_add(&b, " is in "), sb_add(&b, v), sb_add(&b, ".");
        break;
    case C4R_SURNAME:
        sb_add(&b, "The last name of "), sb_add(&b, t), sb_add(&b, " is "), sb_add(&b, v), sb_add(&b, ".");
        break;
    case C4R_CAPITAL:
        sb_add(&b, "The capital of "), sb_add(&b, t), sb_add(&b, " is "), sb_add(&b, v), sb_add(&b, ".");
        break;
    case C4R_OCCUPATION: {
        char c = v[0] >= 'A' && v[0] <= 'Z' ? (char)(v[0] + 32) : v[0];
        sb_add(&b, t), sb_add(&b, c == 0 || strchr("aeiou", c) ? " was an " : " was a "), sb_add(&b, v), sb_add(&b, ".");
        break;
    }
    case C4R_CREATOR:
        sb_add(&b, t), sb_add(&b, " was created by "), sb_add(&b, v), sb_add(&b, ".");
        break;
    case C4R_HEIGHT:
    case C4R_LENGTH:
        sb_add(&b, t), sb_add(&b, " is "), sb_add(&b, v), sb_add(&b, rel == C4R_HEIGHT ? " tall." : " long.");
        break;
    case C4R_QUANTITY:
        sb_add(&b, t), sb_add(&b, " has a population of "), sb_add(&b, v), sb_add(&b, ".");
        break;
    default:
        return -1;
    }
    return b.over ? -1 : 0;
}

/* ---- retrieval ---- */
static int lookup_key(struct cds4_ctx *x, cds4_kb *kb, cds4_result *res, const char *key, cds4_cand out[CDS4_CAND_MAX]) {
    size_t n = strlen(key);
    res->keys_tried++;
    for (size_t i = 0; i < n; i++)
        res->keys_hash = (res->keys_hash ^ (unsigned char)key[i]) * 16777619u;
    res->keys_hash = (res->keys_hash ^ '\n') * 16777619u;
    (void)x;
    return cds4_lookup(kb, key, out);
}

/* words[i..i+n) joined; word j replaced by sub (NULL = none). -1 if over CDS4_KEY_MAX */
static int join(const struct cds4_ctx *x, int i, int n, int j, const char *sub, char *key) {
    size_t k = 0;
    for (int a = i; a < i + n; a++) {
        const char *w = a == j && sub ? sub : x->w[a];
        size_t l = a == j && sub ? strlen(sub) : x->wl[a];
        if (k + (a > i) + l > CDS4_KEY_MAX)
            return -1;
        if (a > i)
            key[k++] = ' ';
        memcpy(key + k, w, l);
        k += l;
    }
    key[k] = 0;
    return (int)k;
}

static void build_grams(struct cds4_ctx *x) {
    x->ng = 0;
    for (int n = 1; n <= 4; n++)
        for (int i = 0; i + n <= x->nw; i++) {
            if (!(x->isent[i] && x->isent[i + n - 1]))
                continue;
            int c = 0;
            for (int a = i; a < i + n; a++)
                c += x->isent[a];
            if (2 * c <= x->total)
                continue;
            uint16_t key = (uint16_t)(((63 - c) << 9) | ((7 - n) << 5) | i);
            int at = x->ng++;
            while (at > 0 && x->grams[at - 1] > key)
                x->grams[at] = x->grams[at - 1], at--;
            x->grams[at] = key;
        }
}
#define G_C(g) (63 - ((g) >> 9))
#define G_N(g) (7 - (((g) >> 5) & 7))
#define G_I(g) ((g) & 31)

static void pool_add(struct cds4_ctx *x, const cds4_cand *cands, int nc, int cover, int typo) {
    for (int ci = 0; ci < nc; ci++) {
        const cds4_cand *c = &cands[ci];
        int p;
        for (p = 0; p < x->npool; p++)
            if (x->pool[p].c.recoff == c->recoff)
                break;
        if (p == x->npool) {
            if (x->npool >= CDS4_POOL)
                continue;
            x->pool[p].c = *c, x->pool[p].cover = cover, x->pool[p].typo = typo, x->pool[p].ord = x->ord++;
            x->pool[p].pop = 0; x->pool[p].weak = c->kind == 3; x->pool[p].route[0] = 0;
            x->npool++;
            continue;
        }
        pool_t *q = &x->pool[p];
        /* (cover, -typo, -kind) > (q.cover, -q.typo, -q.kind) */
        int better = cover != q->cover ? cover > q->cover : typo != q->typo ? typo < q->typo : c->kind < q->c.kind;
        if (better) {
            q->c = *c, q->cover = cover, q->typo = typo;
            q->route[0] = 0;
        }
    }
}

static int rel_score(const pool_t *p, int rel) {
    unsigned b = 1u << rel;
    return p->c.pmask & b ? W_REL_PRESENT : (p->c.mmask & b ? W_REL_MISSING : 0);
}

/* returns best pool index or -1; *st = 0 ok, 1 ambiguous */
static int decide(struct cds4_ctx *x, int rel, int k, int *st, cds4_result *res) {
    int acc[CDS4_POOL], na = 0;
    *st = 0;
    for (int i = 0; i < x->npool; i++)
        if (2 * x->pool[i].cover > x->total) {
            pool_t *p = &x->pool[i];
            int pct = x->total ? 100 * p->cover / x->total : 0;
            p->s1 = W_COVER * pct + kind_bonus[p->c.kind & 3] + W_PROM * p->c.prom - W_TYPO * p->typo;
            acc[na++] = i;
        }
    if (!na)
        return -1;
    for (int i = 1; i < na; i++) { /* stable: s1 desc, ord asc (pool order == ord order) */
        int v = acc[i], j = i;
        while (j > 0 && x->pool[acc[j - 1]].s1 < x->pool[v].s1)
            acc[j] = acc[j - 1], j--;
        acc[j] = v;
    }
    int nt = na < k ? na : k;
    for (int i = 0; i < nt; i++)
        x->pool[acc[i]].s2 = x->pool[acc[i]].s1 + rel_score(&x->pool[acc[i]], rel);
    for (int i = 1; i < nt; i++) {
        int v = acc[i], j = i;
        while (j > 0 && (x->pool[acc[j - 1]].s2 < x->pool[v].s2 ||
                         (x->pool[acc[j - 1]].s2 == x->pool[v].s2 && x->pool[acc[j - 1]].ord > x->pool[v].ord)))
            acc[j] = acc[j - 1], j--;
        acc[j] = v;
    }
    int best = acc[0];
    res->n_alt = 0;
    if (nt >= 2 && x->pool[acc[1]].cover == x->pool[best].cover && x->pool[best].s2 - x->pool[acc[1]].s2 <= AMBIG_GAP) {
        *st = 1;
        for (int i = 1; i < nt; i++)
            res->alt_recoff[res->n_alt++] = x->pool[acc[i]].c.recoff;
    }
    return best;
}

static int full(const struct cds4_ctx *x) {
    for (int i = 0; i < x->npool; i++)
        if (x->pool[i].cover == x->total && 2 * x->pool[i].cover > x->total)
            return 1;
    return 0;
}

static int skip_gram(const struct cds4_ctx *x, int i, int n) { return n == 1 && x->wl[i] < 3; }

static int exact_round(struct cds4_ctx *x, cds4_kb *kb, cds4_result *res) {
    int tried = 0;
    cds4_cand cands[CDS4_CAND_MAX];
    for (int g = 0; g < x->ng; g++) {
        int c = G_C(x->grams[g]), n = G_N(x->grams[g]), i = G_I(x->grams[g]);
        if (tried >= MAX_KEYS)
            break;
        if (join(x, i, n, -1, NULL, x->key) < 0 || skip_gram(x, i, n))
            continue;
        tried++;
        int got = lookup_key(x, kb, res, x->key, cands);
        if (got < 0)
            return -1;
        pool_add(x, cands, got, c, 0);
        if (got && c == x->total)
            break;
    }
    return 0;
}

/* corrections for word j from x->fz[0..ncand); returns -1 error, 1 = stop this word (budget or key too long), 0 continue */
static int fix(struct cds4_ctx *x, cds4_kb *kb, cds4_result *res, int j, int ncand) {
    cds4_cand cands[CDS4_CAND_MAX];
    for (int cw = 0; cw < ncand; cw++) {
        for (int g = 0; g < x->ng; g++) {
            int c = G_C(x->grams[g]), n = G_N(x->grams[g]), i = G_I(x->grams[g]);
            if (!(i <= j && j < i + n))
                continue;
            if (x->tried >= MAX_FKEYS || join(x, i, n, j, x->fz[cw], x->key) < 0)
                return 1;
            x->tried++;
            int got = lookup_key(x, kb, res, x->key, cands);
            if (got < 0)
                return -1;
            pool_add(x, cands, got, c, 1);
        }
        if (full(x))
            return 1;
    }
    return 0;
}

/* words[i..i+n) joined with word j1 -> a and word j2 -> b; -1 if over CDS4_KEY_MAX */
static int join2(const struct cds4_ctx *x, int i, int n, int j1, const char *a, int j2, const char *b, char *key) {
    size_t k = 0;
    for (int t = i; t < i + n; t++) {
        const char *w = t == j1 ? a : t == j2 ? b : x->w[t];
        size_t l = t == j1 ? strlen(a) : t == j2 ? strlen(b) : x->wl[t];
        if (k + (t > i) + l > CDS4_KEY_MAX)
            return -1;
        if (t > i)
            key[k++] = ' ';
        memcpy(key + k, w, l);
        k += l;
    }
    key[k] = 0;
    return (int)k;
}

static int expand_round(struct cds4_ctx *x, cds4_kb *kb, cds4_result *res, int cue_entity) {
    cds4_cand cands[CDS4_CAND_MAX];
    int seen[FZ_WORDS], nseen = 0, later[FZ_WORDS], nlater = 0;
    x->tried = 0;
    x->nunk = 0;
    if (cue_entity) {
        for (int g = 0; g < x->ng; g++) {
            int c = G_C(x->grams[g]), n = G_N(x->grams[g]), i = G_I(x->grams[g]);
            if (x->tried >= MAX_FKEYS || join(x, i, n, -1, NULL, x->key) < 0 || skip_gram(x, i, n))
                continue;
            x->tried++;
            int got = lookup_key(x, kb, res, x->key, cands);
            if (got < 0)
                return -1;
            pool_add(x, cands, got, c, 0);
        }
        if (full(x))
            return 0;
    }
    for (int j = 0; j < x->nw; j++) {
        if (!x->isent[j] || x->wl[j] < kb->fzmin || x->wl[j] < CONTENT_MIN || x->wl[j] > CDS4_KEY_MAX)
            continue;
        int dup = 0;
        for (int s = 0; s < nseen; s++)
            dup |= x->wl[seen[s]] == x->wl[j] && memcmp(x->w[seen[s]], x->w[j], x->wl[j]) == 0;
        if (dup)
            continue;
        if (nseen >= FZ_WORDS || full(x))
            break;
        seen[nseen++] = j;
        char word[CDS4_KEY_MAX + 1];
        memcpy(word, x->w[j], x->wl[j]);
        word[x->wl[j]] = 0;
        int known, nc = cds4_fuzzy(kb, word, x->fz, &known);
        if (nc < 0)
            return -1;
        if (known)
            later[nlater++] = j;
        else {
            if (nc > 0 && x->nunk < 2) {
                memcpy(x->unk[x->nunk], x->fz, sizeof x->fz);
                x->unk_j[x->nunk] = j, x->unk_n[x->nunk++] = nc;
            }
            if (fix(x, kb, res, j, nc) < 0)
                return -1;
        }
    }
    for (int a = 0; a < nlater; a++) {
        int j = later[a];
        if (full(x) || x->tried >= MAX_FKEYS)
            break;
        char word[CDS4_KEY_MAX + 1];
        memcpy(word, x->w[j], x->wl[j]);
        word[x->wl[j]] = 0;
        int known, nc = cds4_fuzzy(kb, word, x->fz, &known);
        if (nc < 0)
            return -1;
        if (fix(x, kb, res, j, nc) < 0)
            return -1;
    }
    if (x->nunk == 2 && !full(x)) { /* two typos in the entity name: both corrected at once, <= MAX_F2KEYS lookups */
        int j1 = x->unk_j[0], j2 = x->unk_j[1], t2 = 0;
        for (int a = 0; a < x->unk_n[0]; a++) {
            for (int b = 0; b < x->unk_n[1]; b++) {
                for (int g = 0; g < x->ng; g++) {
                    int c = G_C(x->grams[g]), n = G_N(x->grams[g]), i = G_I(x->grams[g]);
                    if (!(i <= j1 && j1 < i + n && i <= j2 && j2 < i + n))
                        continue;
                    if (join2(x, i, n, j1, x->unk[0][a], j2, x->unk[1][b], x->key) < 0 || t2 >= MAX_F2KEYS)
                        continue;
                    t2++;
                    int got = lookup_key(x, kb, res, x->key, cands);
                    if (got < 0)
                        return -1;
                    pool_add(x, cands, got, c, 2);
                }
                if (full(x))
                    return 0;
            }
        }
    }
    return 0;
}

static int edit1(const char *a, size_t na, const char *b, size_t nb) {
    if (na == nb && memcmp(a, b, na) == 0)
        return 0;
    if (na > nb + 1 || nb > na + 1)
        return 0;
    if (na == nb) {
        size_t d[3], nd = 0;
        for (size_t i = 0; i < na; i++)
            if (a[i] != b[i]) {
                if (nd == 3)
                    return 0;
                d[nd++] = i;
            }
        return nd == 1 || (nd == 2 && d[1] == d[0] + 1 && a[d[0]] == b[d[1]] && a[d[1]] == b[d[0]]);
    }
    if (na < nb) {
        const char *t = a;
        a = b, b = t;
        size_t tn = na;
        na = nb, nb = tn;
    }
    size_t i = 0;
    while (i < nb && a[i] == b[i])
        i++;
    return memcmp(a + i + 1, b + i, nb - i) == 0; /* a without a[i] == b */
}

/* repair one-typo relation words ('borrn') that are not KB words into x->cw; recomputes nothing else.
 * Returns 1 if cw changed, 0 if not, -1 on a KB error. Leaves cw == w when the repair would leave no entity word. */
static int cue_typos(struct cds4_ctx *x, cds4_kb *kb) {
    int changed = 0;
    for (int j = 0; j < x->nw; j++) {
        x->cw[j] = x->w[j], x->cwl[j] = x->wl[j];
    }
    for (int j = 0; j < x->nw; j++) {
        if (!x->isent[j] || x->wl[j] < 4)
            continue;
        for (const char *const *c = CUE_TYPO; *c; c++) {
            if (strlen(*c) >= 4 && edit1(x->w[j], x->wl[j], *c, strlen(*c))) {
                char word[CDS4_KEY_MAX + 1];
                int known;
                memcpy(word, x->w[j], x->wl[j]);
                word[x->wl[j]] = 0;
                if (cds4_fuzzy(kb, word, x->fz, &known) < 0)
                    return -1;
                if (!known)
                    x->cw[j] = *c, x->cwl[j] = (unsigned char)strlen(*c), changed = 1;
                break;
            }
        }
    }
    if (changed) {
        int ent = 0;
        for (int j = 0; j < x->nw; j++)
            ent += !(in_list(STOP, x->cw[j], x->cwl[j]) || in_list(REL_WORDS, x->cw[j], x->cwl[j]) || in_list(AUX, x->cw[j], x->cwl[j]) ||
                     in_list(FILL, x->cw[j], x->cwl[j]));
        if (!ent) {
            for (int j = 0; j < x->nw; j++)
                x->cw[j] = x->w[j], x->cwl[j] = x->wl[j];
            return 0;
        }
    }
    return changed;
}

static cds4_status finish(cds4_kb *kb, cds4_result *res, uint32_t r0, uint32_t l0, cds4_status st) {
    if (kb->err)
        st = kb->err == CDS4_E_IO ? CDS4_IO_ERROR : CDS4_CORRUPT_KB;
    res->status = st;
    res->sector_reads = kb->sector_reads - r0;
    res->lookups = kb->lookups - l0;
    return st;
}

static int is_stopish(const struct cds4_ctx *x, int j) {
    return in_list(STOP, x->cw[j], x->cwl[j]) || in_list(REL_WORDS, x->cw[j], x->cwl[j]) || in_list(AUX, x->cw[j], x->cwl[j]) ||
           in_list(FILL, x->cw[j], x->cwl[j]);
}

cds4_status cds4_retrieve(cds4_ctx *x, cds4_kb *kb, const char *question, int k, int expand, int routed, cds4_result *res) {
    uint32_t r0 = kb->sector_reads, l0 = kb->lookups;
    memset(res, 0, sizeof *res);
    res->keys_hash = 2166136261u;
    res->status = CDS4_NO_MATCH;
    kb->err = 0;
    if (k < 1)
        k = 1;
    x->npool = x->ord = 0;
    if (strlen(question) > CDS4_QUESTION_MAX || cds_normalize(question, x->norm, sizeof x->norm) < 0) {
        res->reason = "too_long";
        return finish(kb, res, r0, l0, CDS4_GATED);
    }
    x->nw = 0;
    for (char *p = x->norm; *p;) {
        char *e = strchr(p, ' ');
        size_t n = e ? (size_t)(e - p) : strlen(p);
        if (x->nw >= CDS4_MAX_WORDS) {
            res->reason = "too_long";
            return finish(kb, res, r0, l0, CDS4_GATED);
        }
        x->w[x->nw] = p, x->wl[x->nw++] = (unsigned char)n;
        p += n + (e != NULL);
    }
    const char *g = gate(question, x);
    if (g) {
        res->reason = g;
        return finish(kb, res, r0, l0, CDS4_GATED);
    }
    for (int i = 0; i < x->nw; i++) {
        x->cw[i] = x->w[i], x->cwl[i] = x->wl[i];
        x->isent[i] = !is_stopish(x, i);
    }
    int ch = cue_typos(x, kb);
    if (ch < 0)
        return finish(kb, res, r0, l0, CDS4_NO_MATCH);
    x->total = 0;
    for (int i = 0; i < x->nw; i++) {
        x->isent[i] = !is_stopish(x, i);
        x->total += x->isent[i];
    }
    if (!routed && !cue_ok(x)) {
        res->reason = "no_cue";
        return finish(kb, res, r0, l0, CDS4_GATED);
    }
    int rel = parse_relation(x);
    res->field = rel;
    x->total = 0;
    for (int j = 0; j < x->nw; j++) {
        const char *glue = rel == C4R_OCCUPATION ? "kind work" : rel == C4R_QUANTITY ? "big large" : "";
        if (in_list(glue, x->cw[j], x->cwl[j])) x->isent[j] = 0;
        x->total += x->isent[j];
    }
    int cue_entity = x->total == 0;
    if (cue_entity) {
        x->total = 0;
        for (int i = 0; i < x->nw; i++) {
            x->isent[i] = !((in_list(STOP, x->w[i], x->wl[i]) || in_list(FILL, x->w[i], x->wl[i])) && !in_list(REL_WORDS, x->w[i], x->wl[i]));
            x->total += x->isent[i];
        }
    }
    build_grams(x);
    if (x->total && !cue_entity && exact_round(x, kb, res))
        return finish(kb, res, r0, l0, CDS4_NO_MATCH);
    int st, best = decide(x, rel, k, &st, res);
    int content_long = 0;
    for (int j = 0; j < x->nw; j++) content_long |= x->isent[j] && x->wl[j] >= CONTENT_MIN;
    if (expand && (best < 0 || x->pool[best].cover < x->total) && x->total && content_long) {
        res->expansion = 1;
        if (expand_round(x, kb, res, cue_entity))
            return finish(kb, res, r0, l0, CDS4_NO_MATCH);
        best = decide(x, rel, k, &st, res);
    }
    res->candidates = x->npool;
    if (best < 0) {
        res->reason = x->npool ? "coverage_below_majority" : "no_candidate";
        return finish(kb, res, r0, l0, CDS4_NO_MATCH);
    }
    if (cds4_record(kb, x->pool[best].c.recoff, rel, &x->rec))
        return finish(kb, res, r0, l0, CDS4_NO_MATCH);
    res->recoff = x->pool[best].c.recoff;
    res->eid = x->rec.eid;
    memcpy(res->title, x->rec.title, sizeof res->title);
    if (st == 1) {
        res->reason = "close_candidates";
        return finish(kb, res, r0, l0, CDS4_AMBIGUOUS);
    }
    const cds4_field *f = rel != C4R_DEFINITION && x->rec.found ? &x->rec.f : NULL;
    if (rel != C4R_DEFINITION && (!f || (f->flags & 1))) {
        res->reason = f ? "field_marked_missing" : "field_not_applicable";
        return finish(kb, res, r0, l0, CDS4_FIELD_MISSING);
    }
    const char *v = rel == C4R_DEFINITION ? x->rec.def : f->value;
    res->prov = rel == C4R_DEFINITION ? 4 : (uint8_t)((f->flags >> 1) & 7);
    res->field_flags = rel == C4R_DEFINITION ? 0 : f->flags;
    res->source_sid = rel == C4R_DEFINITION || kb->version == 4 ? UINT16_MAX : f->source_sid;
    res->end_sid = rel == C4R_DEFINITION || kb->version == 4 ? UINT16_MAX : f->end_sid;
    size_t vl = strlen(v); /* <= 111: the reader caps definitions and values */
    memcpy(res->value, v, vl < sizeof res->value ? vl + 1 : sizeof res->value - 1);
    res->value[sizeof res->value - 1] = 0;
    if (render(&x->rec, rel, v, res->context, sizeof res->context)) {
        kb->err = CDS4_E_CORRUPT;
        return finish(kb, res, r0, l0, CDS4_CORRUPT_KB);
    }
    return finish(kb, res, r0, l0, CDS4_ANSWER_PRESENT);
}

#include "entres4.inc"
