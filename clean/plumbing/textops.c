/* SPDX-License-Identifier: MIT
 * Twin of campaign/pipeline/textops.py: keep the two in lockstep (test_textops.py diffs them). */
#include <stdio.h>
#include <string.h>
#include "textops.h"
#include "textops_tab.h"

#define MAXQ 127
#define MAXOUT 255
#define MAXTOK 64
#define TOKCAP 130
#define MAXWD 64 /* words in <= 127 bytes */

typedef cds_text_token tok;

static const char *const OPNAME[] = {"upper", "lower", "title", "capitalize", "reverse", "reverse_words", "count_letters",
    "count_chars", "count_chars_nospace", "count_words", "count_vowels", "remove_spaces", "repeat", "replace", "initials",
    "acronym", "sort_words", "first_word", "last_word", "palindrome", "spell"};

const char *cds_textops_name(int op) { return op >= 0 && op < TO_NOPS ? OPNAME[op] : "?"; }

/* ops where "the X" is probably a topic ("how many words in the bible"), not text */
static int no_the(int op) {
    switch (op) {
    case TO_REVERSE: case TO_REVERSE_WORDS: case TO_SORT_WORDS: case TO_FIRST_WORD: case TO_LAST_WORD: case TO_INITIALS:
    case TO_ACRONYM: case TO_COUNT_LETTERS: case TO_COUNT_CHARS: case TO_COUNT_CHARS_NOSPACE: case TO_COUNT_WORDS:
    case TO_COUNT_VOWELS:
        return 1;
    }
    return 0;
}

static int in_list(const char *const *L, const char *w) {
    for (; *L; L++)
        if (!strcmp(*L, w))
            return 1;
    return 0;
}

static int isal(int c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
static int isdg(int c) { return c >= '0' && c <= '9'; }
static int low(int c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }
static int upp(int c) { return c >= 'a' && c <= 'z' ? c - 32 : c; }

/* ---- typo canonicalisation */
static int edit1(const char *a, size_t la, const char *b, size_t lb) {
    if ((la > lb ? la - lb : lb - la) > 1 || (la == lb && !memcmp(a, b, la)))
        return 0;
    size_t i = 0;
    while (i < la && i < lb && a[i] == b[i])
        i++;
    if (la == lb) {
        if (!memcmp(a + i + 1, b + i + 1, la - i - 1))
            return 1;
        return i + 1 < la && a[i] == b[i + 1] && a[i + 1] == b[i] && !memcmp(a + i + 2, b + i + 2, la - i - 2);
    }
    if (la < lb)
        return !memcmp(a + i, b + i + 1, la - i);
    return !memcmp(a + i + 1, b + i, lb - i);
}

static void canon(char *w, size_t n) { /* w: n chars, NUL-terminated, n <= 15 */
    if (n < 6 || in_list(TO_VOCAB, w))
        return;
    const char *hit = NULL;
    int c = 0;
    for (const char *const *k = TO_TYPO_KW; *k; k++)
        if (edit1(w, n, *k, strlen(*k))) {
            hit = *k;
            c++;
        }
    if (c == 1)
        memcpy(w, hit, strlen(hit) + 1);
}

/* ---- tokens */
static int has(const char *set, int c) { return c && strchr(set, c) != NULL; }

static int tokenize(const char *b, int n, tok *T) {
    int i = 0, nt = 0;
#define PUSH(S, E, Q, STR) do { if (nt >= TOKCAP) return -1; T[nt].s = (unsigned short)(S); T[nt].e = (unsigned short)(E); \
        T[nt].q = (Q); strcpy(T[nt].lw, STR); nt++; } while (0)
    while (i < n) {
        if (b[i] == ' ') {
            i++;
            continue;
        }
        char c = b[i];
        if (c == '"' || c == '`' || c == '\'') {
            int j = -1;
            for (int k = i + 1; k < n; k++)
                if (b[k] == c && (k + 1 == n || has(" ,.;:!?)", b[k + 1]))) {
                    j = k;
                    break;
                }
            if (j > i + 1) {
                PUSH(i + 1, j, 1, "\x01");
                i = j + 1;
                continue;
            }
        }
        int j = i;
        while (j < n && b[j] != ' ')
            j++;
        int e = j, colon = 0;
        while (e > i && (has(",;!?", b[e - 1]) || (e == n && b[e - 1] == '.')))
            e--;
        if (e > i && b[e - 1] == ':') {
            colon = 1;
            e--;
            while (e > i && has(",;!?", b[e - 1]))
                e--;
        }
        if (e > i) {
            int ls = i, L = e;
            while (ls < L && has("([{", b[ls]))
                ls++;
            while (L > ls && has(".)]}", b[L - 1]))
                L--;
            L -= ls;
            char lw[16];
            if (L == 0) {
                strcpy(lw, "?");
            } else if (L > 15) {
                strcpy(lw, "#");
            } else {
                for (int k = 0; k < L; k++)
                    lw[k] = (char)low(b[ls + k]);
                lw[L] = 0;
                canon(lw, (size_t)L);
            }
            PUSH(i, e, 0, lw);
        }
        if (colon)
            PUSH(e, e + 1, 0, ":");
        if (e == i && !colon)
            PUSH(i, j, 0, "?");
        i = j;
    }
    while (nt > 0 && !T[nt - 1].q) {
        int all = 1;
        for (int k = T[nt - 1].s; k < T[nt - 1].e; k++)
            if (!has("?!.", b[k]))
                all = 0;
        if (!all)
            break;
        nt--;
    }
    while (nt > 0 && !T[nt - 1].q && in_list((const char *const[]){"please", "pls", "plz", "thanks", "thx", 0}, T[nt - 1].lw))
        nt--;
    if (nt >= 2 && !T[nt - 1].q && !T[nt - 2].q && !strcmp(T[nt - 2].lw, "for") && !strcmp(T[nt - 1].lw, "me"))
        nt -= 2;
    return nt;
}

/* phrase ph against T[i..n): token count, 0 if no match */
static int pm(const tok *T, int n, int i, const char *ph) {
    int k = 0;
    while (*ph) {
        const char *sp = strchr(ph, ' ');
        size_t wl = sp ? (size_t)(sp - ph) : strlen(ph);
        if (i + k >= n || T[i + k].q || strlen(T[i + k].lw) != wl || memcmp(T[i + k].lw, ph, wl))
            return 0;
        k++;
        ph += wl;
        if (*ph == ' ')
            ph++;
    }
    return k;
}

static int nwords(const char *ph) {
    int k = 1;
    for (; *ph; ph++)
        k += *ph == ' ';
    return k;
}

static int is_path(const char *r, int n) {
    int d = -1;
    for (int i = 0; i < n; i++) {
        if (r[i] == '/' || r[i] == '\\' || r[i] == '_')
            return 1;
        if (r[i] == '.')
            d = i;
    }
    if (d <= 0 || d == n - 1 || n - d - 1 > 4)
        return 0;
    for (int i = d + 1; i < n; i++)
        if (!isal(r[i]))
            return 0;
    for (int i = 0; i < d; i++)
        if (isal(r[i]))
            return 1;
    return 0;
}

/* ---- operations: write into o (cap MAXOUT+1), return length or -1 on overflow */
typedef struct { const char *p; int n; } wd;

static int split(const char *t, int n, wd *w) { /* spaces only (input is printable ASCII) */
    int k = 0, i = 0;
    while (i < n) {
        while (i < n && t[i] == ' ')
            i++;
        if (i >= n)
            break;
        w[k].p = t + i;
        int s = i;
        while (i < n && t[i] != ' ')
            i++;
        w[k++].n = i - s;
    }
    return k;
}

static int put_unit(char *o, int v, const char *u) {
    return snprintf(o, MAXOUT + 1, "%d %s%s", v, u, v == 1 ? "" : "s");
}

static int do_op(int op, const char *t, int n, char *o) {
    wd w[MAXWD];
    int i, k;
    switch (op) {
    case TO_UPPER: case TO_LOWER:
        for (i = 0; i < n; i++)
            o[i] = (char)(op == TO_UPPER ? upp(t[i]) : low(t[i]));
        o[n] = 0;
        return n;
    case TO_TITLE: {
        int prev = 0;
        for (i = 0; i < n; i++) {
            int a = isal(t[i]);
            o[i] = (char)(a ? (prev ? low(t[i]) : upp(t[i])) : t[i]);
            prev = a;
        }
        o[n] = 0;
        return n;
    }
    case TO_CAPITALIZE:
        memcpy(o, t, (size_t)n);
        o[n] = 0;
        if (n)
            o[0] = (char)upp(o[0]);
        return n;
    case TO_REVERSE:
        for (i = 0; i < n; i++)
            o[i] = t[n - 1 - i];
        o[n] = 0;
        return n;
    case TO_REVERSE_WORDS: case TO_SORT_WORDS: {
        k = split(t, n, w);
        if (op == TO_SORT_WORDS) { /* insertion sort, byte order = Python's str order for ASCII */
            for (i = 1; i < k; i++) {
                wd x = w[i];
                int j = i - 1;
                while (j >= 0) {
                    int m = w[j].n < x.n ? w[j].n : x.n, c = memcmp(w[j].p, x.p, (size_t)m);
                    if (c == 0)
                        c = w[j].n - x.n;
                    if (c <= 0)
                        break;
                    w[j + 1] = w[j];
                    j--;
                }
                w[j + 1] = x;
            }
        }
        int len = 0;
        for (i = 0; i < k; i++) {
            wd *x = op == TO_SORT_WORDS ? &w[i] : &w[k - 1 - i];
            if (i)
                o[len++] = ' ';
            memcpy(o + len, x->p, (size_t)x->n);
            len += x->n;
        }
        o[len] = 0;
        return len;
    }
    case TO_COUNT_LETTERS: case TO_COUNT_VOWELS: case TO_COUNT_CHARS: case TO_COUNT_CHARS_NOSPACE: {
        int v = 0;
        for (i = 0; i < n; i++) {
            char c = t[i];
            if (op == TO_COUNT_LETTERS)
                v += isal(c);
            else if (op == TO_COUNT_VOWELS)
                v += c && strchr("aeiouAEIOU", c) != NULL;
            else if (op == TO_COUNT_CHARS)
                v++;
            else
                v += c != ' ';
        }
        return put_unit(o, v, op == TO_COUNT_LETTERS ? "letter" : op == TO_COUNT_VOWELS ? "vowel" : "character");
    }
    case TO_COUNT_WORDS:
        return put_unit(o, split(t, n, w), "word");
    case TO_REMOVE_SPACES: {
        int len = 0;
        for (i = 0; i < n; i++)
            if (t[i] != ' ')
                o[len++] = t[i];
        o[len] = 0;
        return len;
    }
    case TO_INITIALS: case TO_ACRONYM: {
        k = split(t, n, w);
        int len = 0;
        for (i = 0; i < k; i++) {
            if (op == TO_ACRONYM && i) {
                char lw[8];
                int skip = 0;
                if (w[i].n < 8) {
                    for (int j = 0; j < w[i].n; j++)
                        lw[j] = (char)low(w[i].p[j]);
                    lw[w[i].n] = 0;
                    skip = in_list(TO_STOPW, lw);
                }
                if (skip)
                    continue;
            }
            o[len++] = (char)(op == TO_ACRONYM ? upp(w[i].p[0]) : w[i].p[0]);
        }
        o[len] = 0;
        return len;
    }
    case TO_FIRST_WORD: case TO_LAST_WORD: {
        k = split(t, n, w);
        if (!k)
            return -1;
        wd *x = op == TO_FIRST_WORD ? &w[0] : &w[k - 1];
        int len = x->n;
        while (len > 0 && has(",.;:!?", x->p[len - 1]))
            len--;
        memcpy(o, x->p, (size_t)len);
        o[len] = 0;
        return len;
    }
    case TO_PALINDROME: {
        char a[MAXQ + 1];
        int m = 0;
        for (i = 0; i < n; i++)
            if (isal(t[i]) || isdg(t[i]))
                a[m++] = (char)low(t[i]);
        int pal = 1;
        for (i = 0; i < m / 2; i++)
            pal &= a[i] == a[m - 1 - i];
        strcpy(o, pal ? "yes" : "no");
        return pal ? 3 : 2;
    }
    case TO_SPELL: {
        k = split(t, n, w);
        int len = 0;
        for (i = 0; i < k; i++) {
            if (i)
                o[len++] = ' ';
            for (int j = 0; j < w[i].n; j++) {
                if (j)
                    o[len++] = '-';
                o[len++] = w[i].p[j];
            }
        }
        o[len] = 0;
        return len;
    }
    }
    return -1;
}

/* ---- parser */
typedef struct {
    const char *q; /* normalised copy of the question; token offsets index into it */
    tok *T;
    int n;
    char *out;
    int op;
} ctx;

static void strip_noise(const tok **A, int *na, const char *const *noise) {
    for (int it = 0; it < 4 && *na; it++) {
        if (!(*A)[0].q && in_list(TO_CONN, (*A)[0].lw) && *na > 1) {
            (*A)++;
            (*na)--;
            continue;
        }
        int hit = 0;
        for (; *noise; noise++) {
            int k = pm(*A, *na, 0, *noise);
            if (k && *na > k) {
                *A += k;
                *na -= k;
                hit = 1;
                break;
            }
        }
        if (!hit)
            break;
    }
}

/* validated argument text -> *s,*l; 0 when the argument is not usable */
static int arg_text(const ctx *c, const tok *A, int na, int op, int *s, int *l) {
    if (na <= 0)
        return 0;
    int anyq = 0;
    for (int i = 0; i < na; i++)
        anyq |= A[i].q;
    if (anyq) {
        if (na != 1)
            return 0;
        int k = A[0].s;
        while (k < A[0].e && c->q[k] == ' ')
            k++;
        if (k == A[0].e)
            return 0;
        *s = A[0].s;
        *l = A[0].e - A[0].s;
        return 1;
    }
    const char *w0 = A[0].lw;
    if (in_list(TO_DECL1, w0) || in_list(TO_VERBS, w0) || (na == 1 && in_list(TO_NOUNS, w0)))
        return 0;
    if (!strcmp(w0, "the") && no_the(op))
        return 0;
    if (na == 1) { /* a lone plural is probably a collection ("reverse names"), not text */
        size_t wl = strlen(w0);
        if (wl >= 4 && w0[wl - 1] == 's' && w0[wl - 2] != 's' && w0[wl - 2] != 'u' && w0[wl - 2] != 'i')
            return 0;
    }
    *s = A[0].s;
    *l = A[na - 1].e - A[0].s;
    return 1;
}

/* run op on the argument; returns answer length or 0 */
static int finish(ctx *c, int op, const tok *A, int na) {
    int s, l;
    if (!arg_text(c, A, na, op, &s, &l))
        return 0;
    if (op == TO_ACRONYM) {
        wd w[MAXWD];
        if (split(c->q + s, l, w) < 2)
            return 0;
    }
    int n = do_op(op, c->q + s, l, c->out);
    if (n <= 0 || n > MAXOUT)
        return 0;
    c->op = op;
    return n;
}

static int ends_with_tail(const tok *A, int na) {
    for (int i = 0; TO_TAILS[i].p; i++) {
        int k = nwords(TO_TAILS[i].p);
        if (na - k >= 0 && pm(A, na, na - k, TO_TAILS[i].p) == k)
            return 1;
    }
    return 0;
}

static int parse_num(const char *w) {
    static const char *const nw[] = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"};
    size_t l = strlen(w);
    if (l >= 1 && l <= 2 && isdg(w[0]) && (l == 1 || isdg(w[1])))
        return l == 1 ? w[0] - '0' : (w[0] - '0') * 10 + (w[1] - '0');
    for (int i = 0; i < 10; i++)
        if (!strcmp(w, nw[i]))
            return i + 1;
    return 0;
}

static int try_repeat(ctx *c, int s) {
    const tok *T = c->T;
    int n = c->n, k = 0, cnt = 0;
    if (n - 1 > s && !T[n - 1].q && (!strcmp(T[n - 1].lw, "twice") || !strcmp(T[n - 1].lw, "thrice"))) {
        cnt = T[n - 1].lw[1] == 'w' ? 2 : 3;
        k = 1;
    } else if (n - 2 > s && !T[n - 1].q && (!strcmp(T[n - 1].lw, "times") || !strcmp(T[n - 1].lw, "time")) && !T[n - 2].q) {
        cnt = parse_num(T[n - 2].lw);
        k = 2;
    }
    if (!k || cnt < 1)
        return 0;
    const tok *A = T + s + 1;
    int na = n - k - (s + 1);
    strip_noise(&A, &na, TO_NOISE);
    int as, al;
    if (!arg_text(c, A, na, TO_REPEAT, &as, &al) || al * cnt + cnt - 1 > MAXOUT)
        return 0;
    int len = 0;
    for (int i = 0; i < cnt; i++) {
        if (i)
            c->out[len++] = ' ';
        memcpy(c->out + len, c->q + as, (size_t)al);
        len += al;
    }
    c->out[len] = 0;
    c->op = TO_REPEAT;
    return len;
}

/* palindrome answer for the argument A; 0 = decline (also the caller's final answer once a head matched) */
static int pal_finish(ctx *c, const tok *A, int na) {
    int s, l;
    if (!arg_text(c, A, na, TO_PALINDROME, &s, &l))
        return 0;
    int any = 0;
    for (int i = 0; i < l; i++)
        any |= isal(c->q[s + i]) || isdg(c->q[s + i]);
    if (!any)
        return 0;
    c->op = TO_PALINDROME;
    return do_op(TO_PALINDROME, c->q + s, l, c->out);
}

static int try_pal(ctx *c, int s) {
    const tok *T = c->T;
    int n = c->n;
    for (int h = 0; TO_PAL_HEADS[h]; h++) {
        int hk = pm(T, n, s, TO_PAL_HEADS[h]);
        if (!hk)
            continue;
        for (int t = 0; TO_PAL_TAILS[t]; t++) {
            int tk = nwords(TO_PAL_TAILS[t]);
            if (n - tk > s + hk && pm(T, n, n - tk, TO_PAL_TAILS[t]) == tk) {
                const tok *A = T + s + hk;
                int na = n - tk - (s + hk);
                strip_noise(&A, &na, TO_NOISE);
                return pal_finish(c, A, na);
            }
        }
        if (!strncmp(TO_PAL_HEADS[h], "palindrome", 10)) {
            const tok *A = T + s + hk;
            int na = n - (s + hk);
            strip_noise(&A, &na, TO_NOISE);
            return pal_finish(c, A, na);
        }
        return 0;
    }
    return 0;
}

static int span_text(const ctx *c, const tok *A, int na, int *s, int *l) {
    if (na <= 0)
        return 0;
    for (int i = 0; i < na; i++)
        if (A[i].q) {
            if (na != 1)
                return 0;
            *s = A[0].s;
            *l = A[0].e - A[0].s;
            return 1;
        }
    (void)c;
    *s = A[0].s;
    *l = A[na - 1].e - A[0].s;
    return 1;
}

static int try_replace(ctx *c, int s) {
    const tok *T = c->T;
    int n = c->n;
    const char *v = T[s].lw, *c1, *c2;
    if (!strcmp(v, "replace")) { c1 = "with"; c2 = "by"; }
    else if (!strcmp(v, "change")) { c1 = "to"; c2 = "into"; }
    else { c1 = "for"; c2 = "with"; } /* swap */
    int cn = -1, in = -1;
    for (int i = s + 1; i < n && cn < 0; i++)
        if (!T[i].q && (!strcmp(T[i].lw, c1) || !strcmp(T[i].lw, c2)))
            cn = i;
    if (cn < 0)
        return 0;
    for (int j = cn + 1; j < n && in < 0; j++)
        if (!T[j].q && !strcmp(T[j].lw, "in"))
            in = j;
    if (in < 0)
        return 0;
    const tok *A = T + s + 1, *B = T + cn + 1, *X = T + in + 1;
    int na = cn - s - 1, nb = in - cn - 1, nx = n - in - 1;
    strip_noise(&A, &na, TO_RNOISE);
    strip_noise(&B, &nb, TO_RNOISE);
    strip_noise(&X, &nx, TO_NOISE);
    int as, al, bs, bl, xs, xl;
    if (!span_text(c, A, na, &as, &al) || !span_text(c, B, nb, &bs, &bl) || !arg_text(c, X, nx, TO_REPLACE, &xs, &xl))
        return 0;
    const char *x = c->q + xs, *a = c->q + as, *b = c->q + bs;
    int found = 0, len = 0;
    for (int i = 0; i + al <= xl; i++)
        if (!memcmp(x + i, a, (size_t)al)) {
            found = 1;
            break;
        }
    if (!found)
        return 0;
    for (int i = 0; i < xl;) {
        if (i + al <= xl && !memcmp(x + i, a, (size_t)al)) {
            if (len + bl > MAXOUT)
                return 0;
            memcpy(c->out + len, b, (size_t)bl);
            len += bl;
            i += al;
        } else {
            if (len + 1 > MAXOUT)
                return 0;
            c->out[len++] = x[i++];
        }
    }
    c->out[len] = 0;
    if (len <= 0)
        return 0;
    c->op = TO_REPLACE;
    return len;
}

int cds_textops_tokens(const char *question, cds_text_token *tokens, size_t capacity) {
    tok tmp[TOKCAP];
    if (!question || !tokens || strlen(question) > MAXQ || !question[0])
        return 0;
    for (const unsigned char *p = (const unsigned char *)question; *p; p++)
        if (*p < 32 || *p > 126)
            return 0;
    int n = tokenize(question, (int)strlen(question), tmp);
    if (n <= 0 || (size_t)n > capacity)
        return 0;
    memcpy(tokens, tmp, (size_t)n * sizeof *tokens);
    return n;
}

int cds_textops_arg(const char *question, const cds_text_token *tokens, int n, int op, int *start, int *length) {
    if (!question || !tokens || !start || !length || n <= 0 || n > MAXTOK || op < 0 || op >= TO_NOPS)
        return 0;
    size_t len = strlen(question);
    if (!len || len > MAXQ) return 0;
    for (int i = 0; i < n; i++)
        if (tokens[i].s >= tokens[i].e || tokens[i].e > len || tokens[i].q > 1 ||
            !memchr(tokens[i].lw, 0, sizeof tokens[i].lw) || (i && tokens[i].s < tokens[i-1].e))
            return 0;
    ctx c = {question, NULL, n, NULL, op};
    return arg_text(&c, tokens, n, op, start, length);
}

int cds_textops_literal(int op, const char *literal, int repeat, const char *x, const char *y, char *out, size_t cap) {
    if (!literal || !out || cap < CDS_TEXTOPS_OUT_CAP)
        return 0;
    out[0] = 0;
    size_t len = strlen(literal);
    if (!len || len > MAXQ || op < 0 || op >= TO_NOPS)
        return 0;
    for (size_t i = 0; i < len; i++)
        if ((unsigned char)literal[i] < 32 || (unsigned char)literal[i] > 126)
            return 0;
    if (op == TO_REPEAT) {
        if (repeat < 1 || repeat > 10 || (len + 1) * (size_t)repeat - 1 > MAXOUT)
            return 0;
        size_t p = 0;
        for (int i = 0; i < repeat; i++) {
            if (i) out[p++] = ' ';
            memcpy(out + p, literal, len); p += len;
        }
        out[p] = 0;
        return (int)p;
    }
    if (op == TO_REPLACE) {
        if (!x || !y || !*x || strlen(x) > MAXQ || strlen(y) > MAXQ || !strstr(literal, x))
            return 0;
        size_t a = strlen(x), b = strlen(y), p = 0, i = 0;
        for (; i < len;) {
            if (i + a <= len && !memcmp(literal + i, x, a)) {
                if (p + b > MAXOUT) return 0;
                memcpy(out + p, y, b); p += b; i += a;
            } else {
                if (p >= MAXOUT) return 0;
                out[p++] = literal[i++];
            }
        }
        out[p] = 0;
        return (int)p;
    }
    if (op == TO_ACRONYM) {
        wd words[MAXWD];
        if (split(literal, (int)len, words) < 2) return 0;
    }
    int n = do_op(op, literal, (int)len, out);
    return n > 0 && n <= MAXOUT ? n : 0;
}

int cds_textops(const char *question, char *out, size_t cap, int *op) {
    static char b[MAXQ + 1]; /* static: keeps the DTCM stack small; not reentrant (the DS is single threaded) */
    static tok T[TOKCAP];
    if (!question || !out || cap < CDS_TEXTOPS_OUT_CAP)
        return CDS_NOT_TEXT_OP;
    out[0] = 0;
    size_t ql = strlen(question);
    if (ql == 0 || ql > MAXQ)
        return CDS_NOT_TEXT_OP;
    for (size_t i = 0; i < ql; i++)
        if ((unsigned char)question[i] < 0x20 || (unsigned char)question[i] > 0x7e)
            return CDS_NOT_TEXT_OP;
    size_t a = 0, e = ql;
    while (a < e && question[a] == ' ')
        a++;
    while (e > a && question[e - 1] == ' ')
        e--;
    memcpy(b, question + a, e - a);
    b[e - a] = 0;
    int nt = tokenize(b, (int)(e - a), T);
    if (nt < 2 || nt > MAXTOK)
        return CDS_NOT_TEXT_OP;
    for (int i = 0; i < nt; i++)
        if (!T[i].q && (in_list(TO_BLOCK, T[i].lw) || is_path(b + T[i].s, T[i].e - T[i].s)))
            return CDS_NOT_TEXT_OP;
    ctx c = {b, T, nt, out, -1};
    int n = nt, s0 = 0, s1;
    while (s0 < n && !T[s0].q && in_list(TO_FILLER_SOFT, T[s0].lw))
        s0++;
    s1 = s0;
    while (s1 < n && !T[s1].q && (in_list(TO_FILLER_SOFT, T[s1].lw) || in_list(TO_FILLER_Q, T[s1].lw)))
        s1++;
    int smax = s1 < n - 1 ? s1 : n - 1, r = 0;
    for (int s = 0; s <= smax && !r; s++) {
        int soft = s <= s0;
        if (soft && !T[s].q && (!strcmp(T[s].lw, "replace") || !strcmp(T[s].lw, "change") || !strcmp(T[s].lw, "swap")))
            r = try_replace(&c, s);
        if (r)
            break;
        if (soft && !T[s].q && in_list(TO_REPEATV, T[s].lw))
            r = try_repeat(&c, s);
        if (r)
            break;
        if (soft)
            r = try_pal(&c, s);
        if (r)
            break;
        /* head phrases */
        for (int h = 0; TO_HEADS[h].p; h++) {
            int k = pm(T, n, s, TO_HEADS[h].p);
            if (!k)
                continue;
            const tok *A = T + s + k;
            int na = n - s - k, o = TO_HEADS[h].op;
            if (o == TO_SORT_WORDS) {
                for (int m = 0; TO_SORT_MODS[m]; m++) {
                    int mk = nwords(TO_SORT_MODS[m]);
                    if (na > mk && pm(A, na, na - mk, TO_SORT_MODS[m]) == mk) {
                        na -= mk;
                        break;
                    }
                }
            } else if (o == TO_COUNT_CHARS) {
                for (int m = 0; TO_CHARS_MODS[m].p; m++) {
                    int mk = nwords(TO_CHARS_MODS[m].p);
                    if (na > mk && pm(A, na, na - mk, TO_CHARS_MODS[m].p) == mk) {
                        na -= mk;
                        o = TO_CHARS_MODS[m].ns ? TO_COUNT_CHARS_NOSPACE : TO_COUNT_CHARS;
                        break;
                    }
                }
            }
            if (ends_with_tail(A, na))
                break;
            strip_noise(&A, &na, TO_NOISE);
            r = finish(&c, o, A, na);
            break; /* the longest matching head decides */
        }
        if (r)
            break;
        /* tails */
        if (soft)
            for (int t = 0; TO_TAILS[t].p; t++) {
                int k = nwords(TO_TAILS[t].p);
                if (n - k <= s || pm(T, n, n - k, TO_TAILS[t].p) != k)
                    continue;
                int a0 = s;
                if (!T[s].q && in_list(TO_WRAP, T[s].lw)) {
                    a0 = s + 1;
                    if (a0 < n && !T[a0].q && !strcmp(T[a0].lw, "me"))
                        a0++;
                } else if (!TO_TAILS[t].bare) {
                    continue;
                }
                const tok *A = T + a0;
                int na = n - k - a0, bad = 0;
                strip_noise(&A, &na, TO_NOISE);
                for (int i = 0; i < na; i++)
                    if (!A[i].q && (in_list(TO_WRAP, A[i].lw) || in_list(TO_VERBS, A[i].lw)))
                        bad = 1;
                if (!bad)
                    r = finish(&c, TO_TAILS[t].op, A, na);
                break;
            }
    }
    if (r <= 0)
        return CDS_NOT_TEXT_OP;
    if (op)
        *op = c.op;
    return r;
}
