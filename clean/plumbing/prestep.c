/* SPDX-License-Identifier: MIT
 * Twin of campaign/pipeline/prestep.py: keep the two in lockstep (test_prestep.py diffs them on generated + fuzzed input). */
#include <stdio.h>
#include <string.h>
#include "plumbing.h"
#include "prestep.h"
#include "prestep_tab.h"
#include "textops.h"

#define MAXQ CDS_PS_QMAX
#define MAXT 130

/* ------------------------------------------------------------------ small helpers */
static int is_d(int c) { return c >= '0' && c <= '9'; }
static int is_a(int c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
static int lc(int c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }

static int ascii_ok(const char *q) {
    size_t n = strlen(q);
    if (!n || n > MAXQ)
        return 0;
    for (size_t i = 0; i < n; i++)
        if ((unsigned char)q[i] < 0x20 || (unsigned char)q[i] > 0x7e)
            return 0;
    return 1;
}

static int in_list(const char *const *L, const char *w) {
    for (; *L; L++)
        if (!strcmp(*L, w))
            return 1;
    return 0;
}

static int eq_lc(const char *a, const char *b) { /* a lowercased == b */
    for (; *a && *b; a++, b++)
        if (lc((unsigned char)*a) != *b)
            return 0;
    return !*a && !*b;
}

/* ---- word tokens: runs of [a-z0-9'] plus ':' tokens (Python wtoks) */
typedef struct {
    unsigned char s, e;
} ptok;

static int wtoks(const char *q, ptok *T) {
    int n = 0;
    size_t len = strlen(q);
    for (size_t i = 0; i < len;) {
        int c = (unsigned char)q[i];
        if (is_d(c) || is_a(c) || c == '\'') {
            size_t j = i;
            while (j < len && (is_d((unsigned char)q[j]) || is_a((unsigned char)q[j]) || q[j] == '\''))
                j++;
            T[n].s = (unsigned char)i, T[n].e = (unsigned char)j, n++;
            i = j;
        } else {
            if (c == ':')
                T[n].s = (unsigned char)i, T[n].e = (unsigned char)(i + 1), n++;
            i++;
        }
    }
    return n;
}

static int tok_is(const char *q, ptok t, const char *w) {
    size_t l = (size_t)(t.e - t.s);
    if (strlen(w) != l)
        return 0;
    for (size_t k = 0; k < l; k++)
        if (lc((unsigned char)q[t.s + k]) != (unsigned char)w[k])
            return 0;
    return 1;
}

static int tok_in(const char *q, ptok t, const char *const *L) {
    for (; *L; L++)
        if (tok_is(q, t, *L))
            return 1;
    return 0;
}

/* token count if phrase ph (space-joined words) matches T at i, else 0 */
static int match_ph(const char *q, const ptok *T, int n, int i, const char *ph) {
    int k = 0;
    const char *p = ph;
    while (*p) {
        const char *e = strchr(p, ' ');
        size_t l = e ? (size_t)(e - p) : strlen(p);
        if (i + k >= n)
            return 0;
        ptok t = T[i + k];
        if ((size_t)(t.e - t.s) != l)
            return 0;
        for (size_t m = 0; m < l; m++)
            if (lc((unsigned char)q[t.s + m]) != (unsigned char)p[m])
                return 0;
        k++;
        p += l;
        if (*p == ' ')
            p++;
    }
    return k;
}

static int match_any(const char *q, const ptok *T, int n, int i, const char *const *L) {
    int best = 0;
    for (; *L; L++) {
        int k = match_ph(q, T, n, i, *L);
        if (k > best)
            best = k;
    }
    return best;
}

static int match_style(const char *q, const ptok *T, int n, int i, int *style) {
    for (int k = 0; PS_STYLE[k].p; k++) {
        int m = match_ph(q, T, n, i, PS_STYLE[k].p);
        if (m) {
            *style = PS_STYLE[k].style;
            return m;
        }
    }
    return 0;
}

/* ------------------------------------------------------------------ 1. style */
void cds_style_apply(int style, const char *in, char *out) {
    int prev = 0;
    size_t i = 0;
    for (; in[i]; i++) {
        int ch = (unsigned char)in[i], a = is_a(ch), r = ch;
        if (a) {
            if (style == CDS_STYLE_UPPER)
                r = ch >= 'a' ? ch - 32 : ch;
            else if (style == CDS_STYLE_LOWER)
                r = lc(ch);
            else if (style == CDS_STYLE_TITLE)
                r = prev ? lc(ch) : (ch >= 'a' ? ch - 32 : ch);
        }
        out[i] = (char)r;
        prev = a;
    }
    out[i] = 0;
}

/* copy s[0..len) to out with the Python strip: rstrip(" ,;:-(") then strip(" ") */
static int trim_inner(const char *s, size_t len, char *out, size_t cap) {
    size_t a = 0, b = len;
    while (b > a && (s[b - 1] == ' ' || s[b - 1] == ',' || s[b - 1] == ';' || s[b - 1] == ':' || s[b - 1] == '-' || s[b - 1] == '('))
        b--;
    while (a < b && s[a] == ' ')
        a++;
    while (b > a && s[b - 1] == ' ')
        b--;
    if (b - a + 1 > cap)
        return -1;
    memcpy(out, s + a, b - a);
    out[b - a] = 0;
    return (int)(b - a);
}

/* "say X in caps": tails stripped, one pair of quotes removed; 0 when empty or a placeholder (it / that / something ...) */
static int lit_norm(const char *s, size_t len, char *out, size_t cap) {
    char tmp[MAXQ + 2];
    if (trim_inner(s, len, tmp, sizeof tmp) < 0)
        return 0;
    size_t ll = strlen(tmp);
    if (ll >= 3 && (tmp[0] == '"' || tmp[0] == '\'' || tmp[0] == '`') && tmp[ll - 1] == tmp[0]) {
        size_t a = 1, bb = ll - 1;
        while (bb > a && tmp[bb - 1] == ' ')
            bb--;
        while (a < bb && tmp[a] == ' ')
            a++;
        memmove(tmp, tmp + a, bb - a);
        tmp[bb - a] = 0;
    }
    if (!tmp[0])
        return 0;
    for (const char *const *L = PS_LIT_BAD; *L; L++)
        if (eq_lc(tmp, *L))
            return 0;
    if (strlen(tmp) + 1 > cap)
        return 0;
    strcpy(out, tmp);
    return 1;
}

int cds_style_detect(const char *q0, int *style, char *inner, size_t cap) {
    static char q[MAXQ + 1];
    ptok T[MAXT];
    inner[0] = 0;
    if (!ascii_ok(q0))
        return CDS_ST_NONE;
    {
        size_t a = 0, b = strlen(q0);
        while (b > a && q0[b - 1] == ' ')
            b--;
        while (a < b && q0[a] == ' ')
            a++;
        memcpy(q, q0 + a, b - a);
        q[b - a] = 0;
    }
    int n = wtoks(q, T), i = 0, st = 0, k;
    if (n < 2)
        return CDS_ST_NONE;
    while (i < n && tok_in(q, T[i], PS_LEADS))
        i++;
    if (i < n && tok_in(q, T[i], PS_SHOUT_VERBS)) {
        if (!lit_norm(q + T[i].e, strlen(q) - T[i].e, inner, cap))
            return CDS_ST_NONE;
        *style = CDS_STYLE_UPPER;
        return CDS_ST_LITERAL;
    }
    /* ---- prefix */
    int j = i, verb = 0;
    while ((k = match_any(q, T, n, j, PS_LEAD_PH)) != 0)
        j += k;
    if (j < n && tok_in(q, T[j], PS_VERBS_S)) {
        verb = 1;
        j++;
        while ((k = match_any(q, T, n, j, PS_MODS)) != 0)
            j += k;
    }
    if (j < n && tok_in(q, T[j], PS_PREPS))
        j++;
    while (j < n && tok_in(q, T[j], (const char *const[]){"all", "only", "just", "entirely", "completely", 0}))
        j++;
    k = match_style(q, T, n, j, &st);
    if (k) {
        j += k;
        while ((k = match_any(q, T, n, j, PS_TRAIL)) != 0)
            j += k;
        int delim = 0;
        if (j < n && T[j].e - T[j].s == 1 && q[T[j].s] == ':')
            delim = 1, j++;
        else if (j < n && memchr(q + T[j - 1].e, ',', (size_t)(T[j].s - T[j - 1].e)))
            delim = 1;
        if (verb || delim) {
            const char *rest = j < n ? q + T[j].s : "";
            int all_free = 1;
            for (int m = j; m < n; m++)
                if (!tok_in(q, T[m], PS_FREE_OK))
                    all_free = 0;
            if (all_free) {
                *style = st;
                return CDS_ST_FREE;
            }
            if (trim_inner(rest, strlen(rest), inner, cap) < 0)
                return CDS_ST_NONE;
            if (!inner[0])
                return CDS_ST_NONE;
            *style = st;
            return verb ? CDS_ST_WRAP : CDS_ST_PREFIX;
        }
    }
    /* ---- suffix */
    int e = n;
    while (e > 1 && tok_in(q, T[e - 1], PS_SUFF_TRAIL))
        e--;
    int litk = match_any(q, T, n, i, PS_LIT_VERBS);
    for (int m = 0; PS_STYLE[m].p; m++) {
        int kk = 1;
        for (const char *c = PS_STYLE[m].p; *c; c++)
            kk += *c == ' ';
        int b = e - kk;
        if (b < 1 || match_ph(q, T, n, b, PS_STYLE[m].p) != kk)
            continue;
        int has_all = tok_is(q, T[b - 1], "all");
        if (has_all)
            b--;
        long pre = -1;
        if (b >= 1 && tok_in(q, T[b - 1], PS_SUFF_PREPS) && i < b - 1) {
            int t = b - 1;
            if (t - 1 > i && tok_in(q, T[t - 1], PS_VERBS_S)) {
                long h = T[t - 1].s;
                while (h > 0 && q[h - 1] == ' ')
                    h--;
                if (h > 0 && q[h - 1] == '(')
                    t--; /* "(reply in all caps)" */
            }
            pre = T[t].s;
        } else {
            long h = T[b].s;
            while (h > 0 && q[h - 1] == ' ')
                h--;
            if (h > 0 && q[h - 1] == '(' && b > i)
                pre = h - 1; /* "(lowercase answer please)" */
            else if (has_all && litk && b > i)
                pre = T[b].s; /* "give me X all lowercase" */
        }
        if (pre < 0)
            continue;
        char tmp[MAXQ + 2];
        if (trim_inner(q + T[i].s, (size_t)pre - T[i].s, tmp, sizeof tmp) < 0 || !tmp[0])
            return CDS_ST_NONE;
        if (litk) {
            int le = T[i + litk - 1].e;
            if (!lit_norm(q + le, pre > le ? (size_t)pre - (size_t)le : 0, inner, cap))
                return CDS_ST_NONE;
            *style = PS_STYLE[m].style;
            return CDS_ST_LITERAL;
        }
        if (strlen(tmp) + 1 > cap)
            return CDS_ST_NONE;
        strcpy(inner, tmp);
        *style = PS_STYLE[m].style;
        return CDS_ST_SUFFIX;
    }
    return CDS_ST_NONE;
}

/* ------------------------------------------------------------------ 2. calc */
typedef struct {
    char k;
    const char *t;
} ctok;

static ctok CT[68];
static char pool[320];
static int cn, pl;
static char qb[MAXQ + 2];
#define DECLINE (-1)

static int edit1(const char *a, const char *b) {
    int la = (int)strlen(a), lb = (int)strlen(b);
    if (la - lb > 1 || lb - la > 1 || !strcmp(a, b))
        return 0;
    int i = 0;
    while (i < la && i < lb && a[i] == b[i])
        i++;
    if (la == lb) {
        if (!strcmp(a + i + 1, b + i + 1))
            return 1;
        return i + 1 < la && a[i] == b[i + 1] && a[i + 1] == b[i] && !strcmp(a + i + 2, b + i + 2);
    }
    if (la < lb)
        return !strcmp(a + i, b + i + 1);
    return !strcmp(a + i + 1, b + i);
}

static int ctok_add(char k, const char *s, size_t len, int lower) {
    if (cn >= 65 || pl + (int)len + 1 > (int)sizeof pool)
        return DECLINE;
    char *d = pool + pl;
    for (size_t i = 0; i < len; i++)
        d[i] = (char)(lower ? lc((unsigned char)s[i]) : s[i]);
    d[len] = 0;
    pl += (int)len + 1;
    CT[cn].k = k, CT[cn].t = d, cn++;
    return 0;
}

static int calc_lex(const char *q0) {
    size_t n = 0;
    cn = pl = 0;
    if (!ascii_ok(q0))
        return DECLINE;
    size_t L = strlen(q0);
    for (size_t i = 0; i < L; i++) { /* nocommas */
        if (q0[i] == ',' && i > 0 && is_d(q0[i - 1]) && i + 3 < L && is_d(q0[i + 1]) && is_d(q0[i + 2]) && is_d(q0[i + 3]) &&
            !(i + 4 < L && is_d(q0[i + 4])))
            continue;
        qb[n++] = q0[i];
    }
    qb[n] = 0;
    for (size_t i = 0; i < n;) {
        int c = (unsigned char)qb[i];
        if (is_d(c) || (c == '.' && i + 1 < n && is_d(qb[i + 1]))) {
            size_t j = i;
            while (j < n && is_d(qb[j]))
                j++;
            if (j < n && qb[j] == '.' && j + 1 < n && is_d(qb[j + 1])) {
                j++;
                while (j < n && is_d(qb[j]))
                    j++;
            }
            if (j < n && (is_a(qb[j]) || qb[j] == '\''))
                return DECLINE;
            if (ctok_add('N', qb + i, j - i, 0))
                return DECLINE;
            i = j;
        } else if (is_a(c) || c == '\'') {
            size_t j = i;
            char w[MAXQ + 2];
            size_t wl = 0;
            while (j < n && (is_a(qb[j]) || qb[j] == '\'')) {
                if (qb[j] != '\'')
                    w[wl++] = (char)lc((unsigned char)qb[j]);
                j++;
            }
            if (j < n && is_d(qb[j]))
                return DECLINE;
            if (wl && ctok_add('W', w, wl, 0))
                return DECLINE;
            i = j;
        } else if (strchr("+*/%()^=", c)) {
            if (ctok_add('S', qb + i, 1, 0))
                return DECLINE;
            i++;
        } else if (c == '-') {
            if (i > 0 && i + 1 < n && is_a(qb[i - 1]) && is_a(qb[i + 1])) {
                i++;
            } else {
                if (ctok_add('S', qb + i, 1, 0))
                    return DECLINE;
                i++;
            }
        } else if (strchr(" ,?!;:\"`.", c)) {
            i++;
        } else {
            return DECLINE;
        }
    }
    return 0;
}

static int cw(int i, const char *w) { return CT[i].k == 'W' && !strcmp(CT[i].t, w); }

static int unit_idx(const char *w) { /* 0..19, or -1 */
    for (int k = 0; PS_UNITS[k]; k++)
        if (!strcmp(PS_UNITS[k], w))
            return k;
    return -1;
}
static int tens_idx(const char *w) { /* 0..7 (twenty..ninety), or -1 */
    for (int k = 0; PS_TENS[k]; k++)
        if (!strcmp(PS_TENS[k], w))
            return k;
    return -1;
}

static int is_numword(int i) {
    return CT[i].k == 'W' && (unit_idx(CT[i].t) >= 0 || tens_idx(CT[i].t) >= 0 || !strcmp(CT[i].t, "hundred") || !strcmp(CT[i].t, "thousand"));
}

/* number words at CT[i..] -> text in buf, *next = next token index; DECLINE on an invalid run */
static int nw_len;
static const char *nw_r[64];
static int nw_pos;

static int nw_grp(void) {
    int k = nw_pos, val = 0, got = 0, u;
    if (k + 1 < nw_len && (u = unit_idx(nw_r[k])) >= 1 && u <= 9 && !strcmp(nw_r[k + 1], "hundred"))
        val = u * 100, k += 2, got = 1;
    else if (k < nw_len && !strcmp(nw_r[k], "hundred"))
        val = 100, k += 1, got = 1;
    if (got && k + 1 < nw_len && !strcmp(nw_r[k], "and"))
        k++;
    int t;
    if (k < nw_len && (t = tens_idx(nw_r[k])) >= 0) {
        val += 20 + 10 * t, k++, got = 1;
        if (k < nw_len && (u = unit_idx(nw_r[k])) >= 1 && u <= 9)
            val += u, k++;
    } else if (k < nw_len && (u = unit_idx(nw_r[k])) >= 0 && (strcmp(nw_r[k], "zero") || nw_len == 1)) {
        val += u, k++, got = 1;
    }
    if (!got)
        return -1;
    nw_pos = k;
    return val;
}

static int numword_run(int i, char *buf, int *next) {
    int j = i;
    nw_len = 0;
    while (j < cn && CT[j].k == 'W') {
        const char *w = CT[j].t;
        if (unit_idx(w) >= 0 || tens_idx(w) >= 0 || !strcmp(w, "hundred") || !strcmp(w, "thousand")) {
            nw_r[nw_len++] = w, j++;
        } else if (!strcmp(w, "and") && nw_len && (!strcmp(nw_r[nw_len - 1], "hundred") || !strcmp(nw_r[nw_len - 1], "thousand")) && j + 1 < cn &&
                   CT[j + 1].k == 'W' && (unit_idx(CT[j + 1].t) >= 0 || tens_idx(CT[j + 1].t) >= 0)) {
            nw_r[nw_len++] = w, j++;
        } else
            break;
    }
    if (!nw_len)
        return DECLINE;
    int total = 0;
    nw_pos = 0;
    if (nw_len == 1 && !strcmp(nw_r[0], "zero")) {
        nw_pos = 1;
    } else {
        if (!strcmp(nw_r[0], "thousand")) {
            total = 1000, nw_pos = 1;
        } else {
            int a = nw_grp();
            if (a < 0)
                return DECLINE;
            if (nw_pos < nw_len && !strcmp(nw_r[nw_pos], "thousand")) {
                total = a * 1000, nw_pos++;
                if (nw_pos < nw_len && !strcmp(nw_r[nw_pos], "and"))
                    nw_pos++;
                if (nw_pos < nw_len) {
                    int b = nw_grp();
                    if (b < 0)
                        return DECLINE;
                    total += b;
                }
            } else
                total = a;
        }
        if (nw_pos != nw_len)
            return DECLINE;
    }
    int l = sprintf(buf, "%d", total);
    if (j < cn && cw(j, "point")) {
        int k = j + 1, nd = 0, u;
        while (k < cn && CT[k].k == 'W' && (u = unit_idx(CT[k].t)) >= 0 && u <= 9) {
            if (!nd)
                buf[l++] = '.';
            buf[l++] = (char)('0' + u), nd++, k++;
        }
        if (!nd)
            return DECLINE;
        buf[l] = 0;
        j = k;
    }
    *next = j;
    return 0;
}

static int literal(int i, char *buf, int *next) {
    if (i < cn && CT[i].k == 'N') {
        strcpy(buf, CT[i].t);
        *next = i + 1;
        return 0;
    }
    if (i < cn && is_numword(i))
        return numword_run(i, buf, next);
    return DECLINE;
}

static int repair(void) {
    for (int k = 0; k < cn; k++) {
        if (CT[k].k != 'W' || in_list(PS_CALC_KNOWN, CT[k].t))
            continue;
        size_t l = strlen(CT[k].t);
        if (l < 3 || l > 15)
            continue;
        int c = 0;
        const char *hit = 0;
        for (const char *const *R = PS_REPAIR; *R; R++)
            if (edit1(CT[k].t, *R))
                c++, hit = *R;
        if (c > 1)
            return DECLINE;
        if (c)
            CT[k].t = hit;
    }
    return 0;
}

static const char *prefix_op(const char *w) {
    for (int k = 0; PS_PREFIX[k].w; k++)
        if (!strcmp(PS_PREFIX[k].w, w))
            return PS_PREFIX[k].s;
    return 0;
}
static int infix_op(const char *w) {
    for (int k = 0; PS_INFIX[k].w; k++)
        if (!strcmp(PS_INFIX[k].w, w))
            return PS_INFIX[k].c;
    return 0;
}

/* returns expression length, 0 declines.  Static ex buffer is cap-checked by the caller copy. */
static char ex[400];
static int exl;

static int ex_add(const char *s) {
    size_t l = strlen(s);
    if (exl + (int)l > 300)
        return DECLINE;
    memcpy(ex + exl, s, l + 1);
    exl += (int)l;
    return 0;
}

static int head_form(int *used) {
    static const char *const HW[] = {"add", "sum", "product", "multiply", "divide", "subtract", "remainder", 0};
    *used = 0;
    if (cn < 1 || CT[0].k != 'W' || !in_list(HW, CT[0].t))
        return 0;
    const char *w = CT[0].t;
    char a[MAXT], b[MAXT];
    int i = 1;
    *used = 1;
    if (!strcmp(w, "remainder")) { /* remainder when A is divided by B | remainder of A divided by B | remainder of A by B */
        if (i < cn && CT[i].k == 'W' && (!strcmp(CT[i].t, "when") || !strcmp(CT[i].t, "of")))
            i++;
        if (literal(i, a, &i))
            return DECLINE;
        if (i < cn && cw(i, "is"))
            i++;
        if (i < cn && cw(i, "divided"))
            i++;
        if (!(i < cn && cw(i, "by")))
            return DECLINE;
        if (literal(i + 1, b, &i) || i != cn)
            return DECLINE;
        exl = 0, ex[0] = 0;
        if (ex_add(a) || ex_add("%") || ex_add(b))
            return DECLINE;
        return 1;
    }
    if (!strcmp(w, "sum") || !strcmp(w, "product")) {
        if (!(i < cn && cw(i, "of")))
            return DECLINE;
        i++;
    }
    if (literal(i, a, &i))
        return DECLINE;
    static const char *const C_ADD[] = {"and", "to", "plus", 0}, *const C_SUM[] = {"and", 0}, *const C_PROD[] = {"and", "times", 0},
                            *const C_MUL[] = {"by", "and", "with", "times", 0}, *const C_DIV[] = {"by", 0}, *const C_SUB[] = {"from", 0};
    const char *const *conn = !strcmp(w, "add") ? C_ADD : !strcmp(w, "sum") ? C_SUM : !strcmp(w, "product") ? C_PROD : !strcmp(w, "multiply") ? C_MUL
                              : !strcmp(w, "divide") ? C_DIV : C_SUB;
    if (!(i < cn && CT[i].k == 'W' && in_list(conn, CT[i].t)))
        return DECLINE;
    if (literal(i + 1, b, &i))
        return DECLINE;
    if (i != cn)
        return DECLINE;
    char op = !strcmp(w, "add") || !strcmp(w, "sum") ? '+' : !strcmp(w, "subtract") ? '-' : !strcmp(w, "divide") ? '/' : '*';
    char t[2] = {op, 0};
    exl = 0, ex[0] = 0;
    if (!strcmp(w, "subtract")) {
        if (ex_add(b) || ex_add(t) || ex_add(a))
            return DECLINE;
    } else if (ex_add(a) || ex_add(t) || ex_add(b))
        return DECLINE;
    return 1;
}

int cds_calc_parse(const char *q, char *expr, size_t cap) {
    if (calc_lex(q) || repair())
        return 0;
    for (int k = 0; k < cn; k++)
        if (CT[k].k == 'W' && in_list(PS_CODEW, CT[k].t))
            return 0;
    int a = 0, e = cn;
    while (a < e && CT[a].k == 'W' && in_list(PS_CALC_FILL, CT[a].t))
        a++;
    while (e > a && ((CT[e - 1].k == 'W' && in_list(PS_CALC_TAIL, CT[e - 1].t)) || (CT[e - 1].k == 'S' && CT[e - 1].t[0] == '=')))
        e--;
    if (a >= e)
        return 0;
    /* shift the window to index 0 so the helpers above see T[a:e] */
    for (int k = a; k < e; k++)
        CT[k - a] = CT[k];
    cn = e - a;
    int used, h = head_form(&used);
    (void)used;
    if (h < 0)
        return 0;
    if (h > 0)
        goto done;
    {
        int depth = 0, ops = 0, operand = 1, i = 0, ln_s = -1, ln_e = -1;
        char num[MAXT], num2[MAXT];
        exl = 0, ex[0] = 0;
        while (i < cn) {
            char k = CT[i].k;
            const char *v = CT[i].t;
            if (operand) {
                const char *po;
                if (k == 'S' && v[0] == '(') {
                    if (ex_add("(")) return 0;
                    depth++, i++, ln_s = -1;
                } else if (k == 'S' && (v[0] == '+' || v[0] == '-')) {
                    if (ex_add(v)) return 0;
                    i++;
                } else if (k == 'W' && (!strcmp(v, "minus") || !strcmp(v, "negative"))) {
                    if (ex_add("-")) return 0;
                    i++;
                } else if (k == 'W' && (!strcmp(v, "square") || !strcmp(v, "cube"))) {
                    if (i + 1 >= cn || !cw(i + 1, "of")) return 0;
                    if (literal(i + 2, num, &i)) return 0;
                    int reps = !strcmp(v, "square") ? 2 : 3;
                    if (ex_add("(")) return 0;
                    for (int r = 0; r < reps; r++)
                        if ((r && ex_add("*")) || ex_add(num)) return 0;
                    if (ex_add(")")) return 0;
                    ops++, operand = 0, ln_s = -1;
                } else if (k == 'W' && (po = prefix_op(v)) != 0) {
                    i++;
                    if (i < cn && cw(i, "of"))
                        i++;
                    if (literal(i, num, &i)) return 0;
                    if (ex_add("(") || ex_add(num) || ex_add(po) || ex_add(")")) return 0;
                    ops++, operand = 0, ln_s = -1;
                } else {
                    if (literal(i, num, &i)) return 0;
                    ln_s = exl;
                    if (ex_add(num)) return 0;
                    ln_e = exl, operand = 0;
                }
            } else {
                int io;
                if (k == 'S' && v[0] == ')') {
                    if (depth == 0) return 0;
                    if (ex_add(")")) return 0;
                    depth--, i++, ln_s = -1;
                } else if (k == 'S' && (v[0] == '+' || v[0] == '-' || v[0] == '*' || v[0] == '/')) {
                    if (ex_add(v)) return 0;
                    ops++, operand = 1, i++;
                } else if ((k == 'S' && v[0] == '%') || (k == 'W' && (!strcmp(v, "percent") || !strcmp(v, "pct")))) {
                    if (i + 1 < cn && cw(i + 1, "of")) {
                        if (ln_s < 0) return 0;
                        if (literal(i + 2, num, &i)) return 0;
                        char a0[MAXT];
                        memcpy(a0, ex + ln_s, (size_t)(ln_e - ln_s));
                        a0[ln_e - ln_s] = 0;
                        exl = ln_s, ex[exl] = 0;
                        if (ex_add("(") || ex_add(a0) || ex_add("*") || ex_add(num) || ex_add("/100)")) return 0;
                        ops++, ln_s = -1;
                    } else if (k == 'S') {
                        if (ex_add("%")) return 0;
                        ops++, operand = 1, i++;
                    } else
                        return 0;
                } else if (k == 'W' && (!strcmp(v, "squared") || !strcmp(v, "cubed"))) {
                    if (ln_s < 0) return 0;
                    char a0[MAXT];
                    memcpy(a0, ex + ln_s, (size_t)(ln_e - ln_s));
                    a0[ln_e - ln_s] = 0;
                    exl = ln_s, ex[exl] = 0;
                    int reps = !strcmp(v, "squared") ? 2 : 3;
                    if (ex_add("(")) return 0;
                    for (int r = 0; r < reps; r++)
                        if ((r && ex_add("*")) || ex_add(a0)) return 0;
                    if (ex_add(")")) return 0;
                    ops++, ln_s = -1, i++;
                } else if (k == 'W' && (io = infix_op(v)) != 0) {
                    char t[2] = {(char)io, 0};
                    if (ex_add(t)) return 0;
                    ops++, operand = 1, i++;
                } else if (k == 'W' && (!strcmp(v, "divided") || !strcmp(v, "multiplied"))) {
                    if (i + 1 >= cn || !cw(i + 1, "by")) return 0;
                    if (ex_add(!strcmp(v, "divided") ? "/" : "*")) return 0;
                    ops++, operand = 1, i += 2;
                } else if (k == 'W' && (!strcmp(v, "take") || !strcmp(v, "taken")) && i + 1 < cn && cw(i + 1, "away")) {
                    if (ex_add("-")) return 0;
                    ops++, operand = 1, i += 2;
                } else
                    return 0;
            }
        }
        (void)num2;
        if (operand || depth || !ops)
            return 0;
    }
done:
    if ((size_t)exl + 1 > cap)
        return 0;
    memcpy(expr, ex, (size_t)exl + 1);
    return exl;
}

int cds_calc_answer(const char *q, char *out, size_t cap) {
    char e[CDS_PS_EXPR_CAP], s[CDS_PS_EXPR_CAP + 8];
    if (!cds_calc_parse(q, e, sizeof e))
        return 0;
    snprintf(s, sizeof s, "calc(%s)", e);
    return cds_apply_calc(s, out, cap);
}

/* Ground decoded math without requiring request prose to be parser filler.
 * Keep every number, symbol and math word in order. Never synthesize operands. */
static int calc_prose_answer(const char *q, char *out, size_t cap, int edges_only) {
    char math[MAXQ + 1];
    size_t n = 0;
    int prose = 0;
    if (calc_lex(q)) return 0;
    for (int i = 0; i < cn; i++) {
        const char *v = CT[i].t;
        if (CT[i].k == 'W') {
            if (in_list(PS_CODEW, v)) return 0;
            if (!in_list(PS_CALC_KNOWN, v) || in_list(PS_CALC_FILL, v) || in_list(PS_CALC_TAIL, v)) {
                if (n) prose = 1;
                continue;
            }
        }
        if (edges_only && prose) return 0;
        size_t k = strlen(v);
        if (n + (n != 0) + k > MAXQ) return 0;
        if (n) math[n++] = ' ';
        memcpy(math + n, v, k); n += k;
    }
    math[n] = 0;
    return cds_calc_answer(math, out, cap);
}
int cds_calc_prose_answer(const char *q, char *out, size_t cap) {
    return calc_prose_answer(q, out, cap, 1);
}
int cds_calc_grounded(const char *q, const char *answer) {
    char expected[256];
    return calc_prose_answer(q, expected, sizeof expected, 0) && !strcmp(expected, answer);
}

/* c43 shares the bounded lexer/literal grammar, never the old entry points. */
#include "casualmath.inc"

/* ------------------------------------------------------------------ 3. textops negative guard */
static void unquote(const char *q, char *o) {
    size_t n = strlen(q);
    memcpy(o, q, n + 1);
    for (size_t i = 0; i < n; i++) {
        char c = q[i];
        if ((c == '"' || c == '`' || c == '\'') && (i == 0 || q[i - 1] == ' ')) {
            for (size_t k = i + 1; k < n; k++)
                if (q[k] == c && (k + 1 == n || strchr(" ,.;:!?)", q[k + 1]))) {
                    if (k > i + 1) {
                        for (size_t m = i; m <= k; m++)
                            o[m] = ' ';
                        i = k;
                    }
                    break;
                }
        }
    }
}

/* words (colon tokens dropped) as ptok list; contiguous phrase test over them */
static int contig(const char *q, const ptok *W, int n, const char *ph) {
    for (int i = 0; i < n; i++) {
        int k = match_ph(q, W, n, i, ph);
        if (k)
            return 1;
    }
    return 0;
}

int cds_textops_guard(const char *q0) {
    char q[MAXQ + 1];
    ptok T[MAXT], W[MAXT];
    if (!ascii_ok(q0))
        return 0;
    unquote(q0, q);
    int n = wtoks(q, T), m = 0;
    for (int i = 0; i < n; i++)
        if (!(T[i].e - T[i].s == 1 && q[T[i].s] == ':'))
            W[m++] = T[i];
    int i = 0;
    while (i < m && tok_in(q, W[i], PS_LEADS))
        i++;
    for (const char *const *H = PS_NEG_HEAD; *H; H++) {
        int k = match_ph(q, W, m, i, *H);
        if (k)
            return 1;
    }
    for (const char *const *A = PS_NEG_ANY; *A; A++)
        if (contig(q, W, m, *A))
            return 1;
    return 0;
}

int cds_textops_guarded(const char *q, char *out, size_t cap, int *op) {
    if (cds_textops_guard(q))
        return CDS_NOT_TEXT_OP;
    return cds_textops(q, out, cap, op);
}

/* ------------------------------------------------------------------ 4. dialogue state */
void cds_dlg_reset(cds_dlg *d) { memset(d, 0, sizeof *d); }

static int phrase_eq(const char *s, const char *ph) { return !strcmp(s, ph); }

/* dlg_kind works on a normalized "w1 w2 ..." string: apostrophes removed, leading fillers and trailing please/pls/thanks stripped */
static int word_is(const char *b, int s, int e, const char *w) { return (int)strlen(w) == e - s && !memcmp(b + s, w, (size_t)(e - s)); }
static int word_is_n(const char *b, int s, int e, const char *w, size_t n) { return (size_t)(e - s) == n && !memcmp(b + s, w, n); }
static int word_in(const char *b, int s, int e, const char *const *L) {
    for (; *L; L++)
        if (word_is(b, s, e, *L))
            return 1;
    return 0;
}

static int dk_norm(const char *q, char *s, size_t cap) {
    ptok T[MAXT];
    static char b[2 * MAXQ + 8];
    unsigned char ws[MAXT], we[MAXT]; /* offsets into b: at most 127 chars + 64 separators < 256 */
    int nw = 0, bl = 0;
    if (!ascii_ok(q))
        return -1;
    int n = wtoks(q, T);
    for (int i = 0; i < n; i++) {
        if (T[i].e - T[i].s == 1 && q[T[i].s] == ':')
            continue;
        int st = bl;
        for (int k = T[i].s; k < T[i].e; k++)
            if (q[k] != '\'')
                b[bl++] = (char)lc((unsigned char)q[k]);
        if (bl > st) {
            ws[nw] = (unsigned char)st, we[nw] = (unsigned char)bl, nw++;
            b[bl++] = ' ';
        }
    }
    int a = 0, e = nw;
    for (;;) {
        if (a < e && word_in(b, ws[a], we[a], PS_DLG_FILL)) {
            a++;
            continue;
        }
        if (a + 1 < e) {
            int hit = 0;
            for (const char *const *F = PS_DLG_FILL2; *F && !hit; F++) {
                const char *sp = strchr(*F, ' ');
                hit = sp && word_is_n(b, ws[a], we[a], *F, (size_t)(sp - *F)) && word_is(b, ws[a + 1], we[a + 1], sp + 1);
            }
            if (hit) {
                a += 2;
                continue;
            }
        }
        break;
    }
    while (e > a && (word_is(b, ws[e - 1], we[e - 1], "please") || word_is(b, ws[e - 1], we[e - 1], "pls") || word_is(b, ws[e - 1], we[e - 1], "thanks")))
        e--;
    if (e - a <= 0 || e - a > 10)
        return -1;
    size_t l = (size_t)(we[e - 1] - ws[a]);
    if (l + 1 > cap)
        return -1;
    memcpy(s, b + ws[a], l); /* words are stored back to back, one space apart: the run a..e-1 is already the joined string */
    s[l] = 0;
    return 0;
}

static int s_contig(const char *s, const char *ph) { /* ph as a contiguous run of whole words inside s */
    size_t pl2 = strlen(ph), sl = strlen(s);
    for (size_t i = 0; i + pl2 <= sl; i++)
        if (!memcmp(s + i, ph, pl2) && (i == 0 || s[i - 1] == ' ') && (i + pl2 == sl || s[i + pl2] == ' '))
            return 1;
    return 0;
}

static int dk_has(const char *s, const char *const *L) {
    for (; *L; L++)
        if ((strchr(*L, ' ') && s_contig(s, *L)) || phrase_eq(s, *L))
            return 1;
    return 0;
}

int cds_dlg_kind(const char *q) {
    char s[160];
    if (dk_norm(q, s, sizeof s))
        return CDS_DK_NONE;
    if (dk_has(s, PS_DLG_STYLE_OFF))
        return CDS_DK_STYLE_OFF;
    for (const char *const *L = PS_DLG_CANCEL; *L; L++)
        if (phrase_eq(s, *L))
            return CDS_DK_CANCEL;
    if (dk_has(s, PS_DLG_PUSH))
        return CDS_DK_PUSHBACK;
    for (const char *const *L = PS_DLG_REPEAT; *L; L++)
        if (phrase_eq(s, *L))
            return CDS_DK_REPEAT;
    for (const char *const *L = PS_DLG_ORD1; *L; L++)
        if (phrase_eq(s, *L))
            return CDS_DK_FIRST;
    for (const char *const *L = PS_DLG_ORD2; *L; L++)
        if (phrase_eq(s, *L))
            return CDS_DK_OTHER;
    return CDS_DK_NONE;
}

int cds_dlg_subst_pronoun(const char *q, const char *entity, char *out, size_t cap) {
    ptok T[MAXT];
    if (!entity[0] || !ascii_ok(q))
        return 0;
    int n = wtoks(q, T), has_p = 0;
    size_t el = strlen(entity);
    for (int i = 0; i < n; i++) {
        if (T[i].e - T[i].s == 1 && q[T[i].s] == ':')
            continue;
        if (tok_in(q, T[i], PS_DLG_PRON))
            has_p = 1;
        else if (!tok_in(q, T[i], PS_ENT_STOP))
            return 0;
    }
    if (!has_p)
        return 0;
    char buf[2 * MAXQ + 2 * 48 + 8];
    size_t l = 0, last = 0;
    for (int i = 0; i < n; i++) {
        if (T[i].e - T[i].s == 1 && q[T[i].s] == ':')
            continue;
        if (tok_in(q, T[i], PS_DLG_PRON)) {
            size_t seg = T[i].s - last;
            if (l + seg + el + 1 > sizeof buf)
                return 0;
            memcpy(buf + l, q + last, seg), l += seg;
            memcpy(buf + l, entity, el), l += el;
            last = T[i].e;
        }
    }
    size_t tail = strlen(q) - last;
    if (l + tail + 1 > sizeof buf)
        return 0;
    memcpy(buf + l, q + last, tail), l += tail;
    buf[l] = 0;
    size_t a = 0;
    while (l > a && buf[l - 1] == ' ')
        l--;
    while (a < l && buf[a] == ' ')
        a++;
    if (l - a > MAXQ || l - a + 1 > cap)
        return 0;
    memcpy(out, buf + a, l - a);
    out[l - a] = 0;
    return (int)(l - a);
}

static void capcpy(char *d, size_t cap1, const char *s) { /* cap1 = max bytes without NUL */
    size_t l = strlen(s);
    if (l > cap1)
        l = cap1;
    memcpy(d, s, l);
    d[l] = 0;
}

void cds_dlg_note(cds_dlg *d, int task, const char *entity, const char *answer, const char *lastq, int ok, int keep_answer) {
    if (!ok) {
        cds_dlg_reset(d);
        return;
    }
    d->task = (uint8_t)task;
    if (task == CDS_TASK_FACTS) {
        if (entity[0])
            capcpy(d->entity, CDS_DLG_ENT, entity);
    } else if (task == CDS_TASK_CALC || task == CDS_TASK_TEXT || task == CDS_TASK_OTHER) {
        d->entity[0] = 0, d->ncand = 0, d->cand[0] = d->cand[1] = 0; /* topic switch */
    }
    if (keep_answer) {
        capcpy(d->answer, CDS_DLG_ANS, answer);
        capcpy(d->lastq, CDS_DLG_Q, lastq);
    }
}

void cds_dlg_set_style(cds_dlg *d, int style) {
    d->style = (uint8_t)style;
    d->ttl = style ? CDS_PS_STYLE_TTL : 0;
}

int cds_dlg_style_take(cds_dlg *d) {
    int s = d->style;
    if (s && d->ttl > 0) {
        d->ttl--;
        if (d->ttl == 0)
            d->style = 0;
        return s;
    }
    d->style = 0;
    return 0;
}
