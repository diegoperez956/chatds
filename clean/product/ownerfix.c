/* SPDX-License-Identifier: MIT
 * Bounded owner-language grammar; twin of campaign/pipeline/ownerfix.py. */
#include <string.h>
#include "ownerfix.h"
#include "rules.h"
#include "prestep.h"
#include "textops.h"

static int lower(int c) { return c >= 'A' && c <= 'Z' ? c + 32 : c; }
static int prefix(const char *q, const char *p) {
    for (; *p; p++, q++) if (!*q || lower((unsigned char)*q) != *p) return 0;
    return 1;
}
static __attribute__((noinline)) int quoted_arg(const char *q) {
    cds_text_token t[2];
    int n = cds_textops_tokens(q, t, 2);
    return n == 2 && t[1].q;
}

int owner_identity(const char *q) {
    char plain[128], normalized[128] = "";
    if (!*q || strlen(q) > 127) return 0;
    for (const unsigned char *p = (const unsigned char *)q; *p; p++)
        if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
              (*p >= '0' && *p <= '9') || strchr(" '\?!,.", *p))) return 0;
    c14_plain(q, plain);
    size_t n = 0;
    for (char *p = plain; *p;) {
        char *e = strchr(p, ' '); if (e) *e = 0;
        const char *w = !strcmp(p, "u") ? "you" : !strcmp(p, "r") ? "are" :
            !strcmp(p, "ur") ? "your" : !strcmp(p, "ure") ? "youre" : p;
        if (n || !c14_has(w, "hey hi hello yo so ok okay")) {
            size_t k = strlen(w);
            if (n + (n != 0) + k >= sizeof normalized) return 0;
            if (n) normalized[n++] = ' ';
            memcpy(normalized + n, w, k + 1); n += k;
        }
        if (!e) break;
        p = e + 1;
    }
    while (n) {
        char *last = strrchr(normalized, ' '), *w = last ? last + 1 : normalized;
        if (!c14_has(w, "please pls plz tho")) break;
        if (!last) normalized[0] = 0; else *last = 0;
        n = strlen(normalized);
    }
    return c14_rules(normalized).act == A_IDENTITY;
}

/* Consume complete instruction words, never search inside the literal. */
static int take(const char **q, const char *w) {
    size_t n = strlen(w);
    if (!prefix(*q, w) || ((*q)[n] && (*q)[n] != ' ' && (*q)[n] != ':')) return 0;
    *q += n; while (**q == ' ') (*q)++;
    return 1;
}
static int reverse_tail(const char *q, char *canonical) {
    if (!take(&q, "put") && !take(&q, "place") && !take(&q, "arrange")) return 0;
    take(&q, "the");
    if (!take(&q, "words") || (!take(&q, "of") && !take(&q, "in"))) return 0;
    for (const char *p = q; *p; p++) {
        if (!prefix(p, " in reverse order") || (p[17] && !strchr(" ?!.", p[17]))) continue;
        const char *end = p; while (end > q && end[-1] == ' ') end--;
        size_t n = (size_t)(end - q), tail = strlen(p + 17);
        if (!n || 17 + n + tail > 127) return 0;
        memcpy(canonical, "reverse words in ", 17);
        memcpy(canonical + 17, q, n); strcpy(canonical + 17 + n, p + 17);
        return 1;
    }
    return 0;
}
int owner_text(const char *q, char *out, size_t cap, int *op) {
    if (strlen(q) > 127) return 0;
    while (*q == ' ') q++;
    int caps = take(&q, "caps") || take(&q, "capitals");
    const char *head = "uppercase ";
    char canonical[128];
    if (!caps) {
        if (reverse_tail(q, canonical)) return cds_textops_guarded(canonical, out, cap, op);
        if (!take(&q, "reverse") && !take(&q, "flip")) return 0;
        take(&q, "the");
        if (take(&q, "word")) { if (!take(&q, "order")) return 0; }
        else if (take(&q, "order")) {
            if (!take(&q, "of")) return 0;
            take(&q, "the"); if (!take(&q, "words")) return 0;
        } else if (!take(&q, "words")) return 0;
        if (!take(&q, "in")) take(&q, "of");
        while (*q == ':' || *q == ' ') q++;
        head = "reverse words in ";
    } else if (!*q || !strchr("'\"`", *q)) return 0;
    if (strlen(head) + strlen(q) > 127) return 0;
    strcpy(canonical, head); strcat(canonical, q);
    if (caps && !quoted_arg(canonical)) return 0;
    return cds_textops_guarded(canonical, out, cap, op);
}

/* Shared bounded prefix grammar; NULL means unchanged or over limit. */
static const char *owner_prefix(const char *q) {
    static const char *const fillers[] = {"quick question", "quick q", "hey", "hi", "hello", "yo", "uh", "um", "well", "so"};
    while (*q == ' ') q++;
    int changed = 0;
    for (int i = 0; i < 3; i++) {
        int found = 0;
        for (unsigned j = 0; j < sizeof fillers / sizeof *fillers; j++) {
            size_t n = strlen(fillers[j]);
            if (prefix(q, fillers[j]) && q[n] && strchr(" ,!:", q[n])) {
                if (i == 2) return NULL;
                q += n; while (*q && strchr(" ,!:", *q)) q++;
                found = changed = 1; break;
            }
        }
        if (!found) break;
    }
    return changed && *q ? q : NULL;
}

int owner_calc(const char *q, char *out, size_t cap) {
    size_t n = strlen(q); if (n > 127) return 0;
    const char *tail = owner_prefix(q); if (tail) q = tail;
    const char *p = q; while (*p == ' ') p++;
    if ((take(&p, "can") || take(&p, "could") || take(&p, "would") || take(&p, "will")) && take(&p, "you")) q = p;
    p = q; while (*p == ' ') p++;
    if ((take(&p, "math") || take(&p, "arithmetic")) && *p == ':') {
        p++; while (*p == ' ') p++; q = p;
    }
    n = strlen(q);
    char clean[128]; memcpy(clean, q, n + 1);
    for (int i = 0; i < 2; i++) {
        while (n && strchr(" ?!.,", clean[n - 1])) clean[--n] = 0;
        if (n >= 7 && prefix(clean + n - 7, " for me")) { n -= 7; clean[n] = 0; continue; }
        char *p = strrchr(clean, ' '); if (!p) break;
        char w[128]; size_t k = strlen(p + 1);
        for (size_t j = 0; j <= k; j++) w[j] = (char)lower((unsigned char)p[j + 1]);
        if (!c14_has(w, "tho though rn please pls plz")) break;
        n = (size_t)(p - clean); clean[n] = 0;
    }
    while (n && strchr(" ?!.,", clean[n - 1])) clean[--n] = 0;
    return cds_calc_answer(clean, out, cap) || cds_calc_prose_answer(clean, out, cap);
}
int owner_grounded(const char *q, const char *answer) {
    char expected[256];
    return (owner_calc(q, expected, sizeof expected) && !strcmp(expected, answer)) || cds_calc_grounded(q, answer);
}

int owner_fact(const char *q, char *out, size_t cap) {
    if (strlen(q) > 127) return 0;
    for (const unsigned char *s = (const unsigned char *)q; *s; s++) if (*s < 32 || *s > 126) return 0;
    q = owner_prefix(q);
    if (!q || strlen(q) >= cap || owner_identity(q) || c14_rules(q).handler != H_FACTS || !c24_primary_fact(q)) return 0;
    memmove(out, q, strlen(q) + 1); return 1;
}
