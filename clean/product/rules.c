/* SPDX-License-Identifier: MIT
 * Exact c14 rules, using generated bounded NFAs instead of a platform regex library.
 * No heap; serialized calls only. Runtime O(input length * program states).
 */
#include <stdint.h>
#include <string.h>
#include "plumbing.h"
#include "rules.h"
/* Decoded node: opcode in a's high 3 bits, target in low 13.
 * Immutable storage uses two bytes per ordinary node, four per split pair.
 * Decode by value: no shared scratch, unaligned loads or live-data aliases. */
typedef struct { uint16_t a, b; } rx_node;
typedef struct { uint16_t offset, start, size; } rx_prog;
#include "rules_tab.h"
static rx_node rx_decode(unsigned index) {
    uint16_t packed = rx_nodes[index];
    unsigned code = packed >> 10, target = packed & 1023;
    if (code < 58) return (rx_node){(uint16_t)(8192 | target), (uint16_t)code};
    if (code == 60) {
        rx_node split = rx_splits[target];
        split.a |= 2u << 13;
        return split;
    }
    return (rx_node){(uint16_t)(((code - 58) << 13) | target), 0};
}
static unsigned char active[2][RX_MAX];
static uint16_t queue[RX_MAX];
static int word(int c) { return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'; }
static int lower(int c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }
static void closure(const rx_prog *p, unsigned char *set, int start, const char *s, size_t pos, size_t len) {
    unsigned n = 0, i = 0;
    if (set[start]) return;
    set[start] = 1; queue[n++] = (uint16_t)start;
    while (i < n) {
        rx_node v = rx_decode(p->offset + queue[i++]);
        int op = v.a >> 13, target = v.a & 8191;
        int follow = op == 2 || (op == 3 && pos == 0) || (op == 4 && pos == len) ||
            (op == 5 && (pos > 0 && word((unsigned char)s[pos - 1])) != (pos < len && word((unsigned char)s[pos])));
        if (follow) {
            if (!set[target]) { set[target] = 1; queue[n++] = (uint16_t)target; }
            if (op == 2 && !set[v.b]) { set[v.b] = 1; queue[n++] = v.b; }
        }
    }
}
static int rx(int id, const char *s) {
    const rx_prog *p = &rx_programs[id];
    size_t len = strlen(s);
    int cur = 0;
    memset(active, 0, sizeof active);
    for (size_t pos = 0; pos <= len; pos++) {
        closure(p, active[cur], p->start, s, pos, len); /* unanchored search */
        if (active[cur][0]) return 1;
        if (pos == len) break;
        memset(active[1 - cur], 0, p->size);
        for (int i = 0; i < p->size; i++) {
            rx_node v = rx_decode(p->offset + i);
            unsigned c = (unsigned char)s[pos];
            if (active[cur][i] && (v.a >> 13) == 1 && c < 128 && (rx_class[v.b][c / 8] & (1u << (c % 8))))
                closure(p, active[1 - cur], v.a & 8191, s, pos + 1, len);
        }
        cur = 1 - cur;
    }
    return 0;
}
int c14_has(const char *text, const char *words) {
    for (const char *p = text; *p;) {
        const char *e = strchr(p, ' '); size_t n = e ? (size_t)(e - p) : strlen(p);
        for (const char *w = words; *w;) {
            const char *v = strchr(w, ' '); size_t m = v ? (size_t)(v - w) : strlen(w);
            if (n == m && !memcmp(p, w, n)) return 1;
            w += m + (v != NULL);
        }
        p += n + (e != NULL);
    }
    return 0;
}
void c14_plain(const char *q, char *out) {
    /* host plain_of: replace disallowed runs by spaces, collapse, remove punctuation.
     * Punctuation that survives first regex must NOT become a separator ("what's" -> "whats"). */
    char t[CDS_QUESTION_MAX + 1]; size_t n = 0; int space = 0;
    for (; *q; q++) {
        int c = lower((unsigned char)*q);
        if (word(c) || strchr("%+*/^'._-[](){}=", c)) {
            if (space && n) t[n++] = ' ';
            space = 0; t[n++] = (char)c;
        } else space = 1;
    }
    t[n] = 0; n = 0;
    for (size_t i = 0; t[i]; i++) if ((t[i] >= 'a' && t[i] <= 'z') || (t[i] >= '0' && t[i] <= '9') || t[i] == ' ') out[n++] = t[i];
    while (n && out[n - 1] == ' ') n--;
    out[n] = 0;
    size_t a = 0; while (out[a] == ' ') a++;
    if (a) memmove(out, out + a, n - a + 1);
}
static void typed(const char *q, char *out) {
    size_t n = 0; int space = 0;
    for (; *q; q++) {
        int c = lower((unsigned char)*q);
        if (word(c) || strchr("%+*/^'._-[](){}=", c)) {
            if (space && n) out[n++] = ' ';
            space = 0; out[n++] = (char)c;
        } else space = 1;
    }
    out[n] = 0;
}
static int wc(const char *s) { int n = *s != 0; for (; *s; s++) n += *s == ' '; return n; }
static int act(const char *s) {
    if (rx(RX_ACT_X, s)) return strstr(s, "introduce") ? A_IDENTITY : strstr(s, "have a") ? A_BYE : A_ACK;
    for (int i = RX_ACT_GREETING; i <= RX_ACT_REPEAT; i++) if (rx(i, s)) return A_GREETING + i - RX_ACT_GREETING;
    return A_NONE;
}
static const char *greet_rest(const char *s, int now) {
    static const char *const g[] = {"hi", "hello", "hey", "yo", "howdy", "hiya", "heya", "greetings", "good morning", "good afternoon", "good evening", "sup", "thanks", "thank you", "thx", "ok", "okay", "ok thanks", "cool"};
    for (unsigned i = 0; i < sizeof g / sizeof *g; i++) {
        size_t n = strlen(g[i]);
        if (!strncmp(s, g[i], n) && s[n] == ' ') {
            const char *r = s + n; while (*r == ' ') r++;
            if (now && !strncmp(r, "now ", 4)) r += 4;
            return r;
        }
    }
    return NULL;
}
const char *c14_ambig(const char *q) {
    static char found[24]; char s[128]; c14_plain(q, s);
    for (char *p = s; *p;) {
        char *e = strchr(p, ' '); size_t n = e ? (size_t)(e - p) : strlen(p);
        if (n < sizeof found) { memcpy(found, p, n); found[n] = 0; if (c14_has(found, R_AMBIG)) return found; }
        p += n + (e != NULL);
    }
    return NULL;
}
static int improved(const char *question, int depth) {
    char q[128], s[128], t[128]; strcpy(q, question);
again:
    c14_plain(q, s); typed(q, t);
    if (!s[0] || (!strpbrk(s, "aeiouy") && wc(s) <= 2 && !rx(RX_DIGIT, s))) return H_UNSUPPORTED;
    int n = 0, same = 1, ch = 0;
    for (const char *p = s; *p; p++) if (*p != ' ') { if (n && ch != *p) same = 0; ch = *p; n++; }
    if (same && n >= 4) return H_UNSUPPORTED;
    if (act(s)) return H_FACTS;
    const char *rest = greet_rest(s, 0);
    if (rest && strlen(rest) > 2 && depth < 43) { strcpy(q, rest); depth++; goto again; }
    if ((wc(s) == 1 && c14_has(s, R_AMBIG)) || rx(RX_AMBIG, s)) return H_CLARIFY;
    if (rx(RX_UNSUP, s)) return H_UNSUPPORTED;
    if (rx(RX_MULTI, s) && rx(RX_CALC, s) + rx(RX_SHELL, s) + rx(RX_TEXT, s) + rx(RX_FACT_CUE, s) >= 2) return H_CLARIFY;
    if (rx(RX_PY_META, s) && rx(RX_PY_TERMS, s)) return H_PYTHON;
    if (rx(RX_SURNAME, s)) return H_FACTS;
    if (rx(RX_BASH, s) && !c14_has(s, "python")) return H_SHELL;
    if (rx(RX_PY_SYNTAX, t)) return c14_has(s, "python") && strstr(s, "what is") && wc(s) <= 3 ? H_CLARIFY : H_PYTHON;
    if (rx(RX_CALC, t) && !rx(RX_CALC_FACT, s)) return H_CALC;
    if (rx(RX_TEXT, s) && !rx(RX_LIST, s)) return H_TEXT;
    if (rx(RX_SHELL, s)) return H_SHELL;
    if (rx(RX_PYTHON, s) && !rx(RX_FACT_CUE, s)) return H_PYTHON;
    if (rx(RX_CLARIFY, s)) return H_CLARIFY;
    return H_FACTS;
}
static int stretched(const char *w, const char *base) {
    size_t n = strlen(base); if (strncmp(w, base, n)) return 0;
    for (const char *p = w + n; *p; p++) if (*p != base[n - 1]) return 0;
    return 1;
}
static int conversation(const char *s) {
    if (!*s || wc(s) > 4) return 0;
    for (const char *p = s; *p;) {
        const char *e = strchr(p, ' '); size_t n = e ? (size_t)(e - p) : strlen(p);
        char w[128]; memcpy(w, p, n); w[n] = 0;
        int haha = n >= 4 && n % 2 == 0;
        for (size_t i = 0; i < n && haha; i++) haha = w[i] == (i % 2 ? 'a' : 'h');
        if (!c14_has(w, R_CONVERSATION) && !stretched(w, "hey") && !stretched(w, "hi") && !stretched(w, "hello") && !haha) return 0;
        p += n + (e != NULL);
    }
    return 1;
}
static c14_decision decide(const char *question, int depth) {
    char q[128], s[128], norm[128]; strcpy(q, question);
again:
    c14_plain(q, s); cds_normalize(q, norm, sizeof norm);
    c14_decision d = {H_FACTS, A_NONE};
    const char *r = greet_rest(s, 1);
    if (r && wc(r) >= 2 && !act(r) && depth < 43) { strcpy(q, r); depth++; goto again; }
    d.act = act(s);
    if (d.act) { d.handler = H_CONVERSATION; return d; }
    if (rx(RX_MASH, s)) { d.handler = H_UNCLEAR; return d; }
    d.handler = improved(q, 0);
    if (d.handler == H_UNSUPPORTED) d.handler = rx(RX_UNSUP, s) ? H_UNSUPPORTED : H_UNCLEAR;
    if (d.handler == H_CLARIFY && rx(RX_FILE, q) && !rx(RX_PRON, s)) d.handler = H_SHELL;
    if (d.handler == H_FACTS && (rx(RX_ARITH, q) || (c14_has(norm, R_NUM) && c14_has(norm, R_MATH)) ||
        ((rx(RX_DIGIT, q) || c14_has(norm, R_NUM)) && c14_has(norm, "plus minus times divided multiplied percent half double twice triple quarter")))) d.handler = H_CALC;
    return d;
}
c14_decision c14_rules(const char *q) {
    c14_decision d = decide(q, 0); char norm[128]; cds_normalize(q, norm, sizeof norm);
    if (conversation(norm) && d.handler != H_CONVERSATION) {
        d.handler = H_CONVERSATION;
        d.act = c14_has(norm, "bye goodbye cya later laters") ? A_BYE :
            c14_has(norm, "thanks thank thx thankyou") ? A_THANKS : A_ACK;
        for (const char *p = norm; *p;) {
            const char *e = strchr(p, ' '); size_t n = e ? (size_t)(e - p) : strlen(p);
            char w[128]; memcpy(w, p, n); w[n] = 0;
            if (d.act == A_ACK && (stretched(w, "hey") || stretched(w, "hi") || stretched(w, "hello") || c14_has(w, "sup wassup yo hiya howdy greetings"))) d.act = A_GREETING;
            p += n + (e != NULL);
        }
    }
    return d;
}
int c24_primary_fact(const char *q) {
    char s[128]; c14_plain(q, s);
    return cds_wants_context(q) || rx(RX_FACT_CUE, s);
}
int c14_pronoun(const char *q) { char s[128]; c14_plain(q, s); return rx(RX_PRON, s); }
int c14_entity_words(const char *q) {
    char s[128]; cds_normalize(q, s, sizeof s);
    for (char *p = s; *p;) {
        char *e = strchr(p, ' '); size_t n = e ? (size_t)(e - p) : strlen(p);
        char w[128]; memcpy(w, p, n); w[n] = 0;
        if (!c14_has(w, R_ENT_STOP) && !rx(RX_PRON, w)) return 1;
        p += n + (e != NULL);
    }
    return 0;
}
int c14_cue(const char *q) {
    char s[128]; cds_normalize(q, s, sizeof s);
    if (c14_has(s, R_GATE_REL) || strstr(s, "last name") || strstr(s, "family name") || strstr(s, "many people")) return 1;
    char *p = s;
    while (*p) {
        char *e = strchr(p, ' '); size_t n = e ? (size_t)(e - p) : strlen(p);
        char w[128]; memcpy(w, p, n); w[n] = 0;
        if (!c14_has(w, R_FILL)) return c14_has(w, R_CUES) || !strncmp(p, "tell me about ", 14);
        p += n + (e != NULL);
    }
    return 0;
}
