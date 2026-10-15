/* SPDX-License-Identifier: MIT
 * Twin of campaign/router/round3.py. Models are independent flat CDSR heads.
 * No floating point, heap, generator, or synthesized argument bytes. */
#include <stdio.h>
#include <string.h>
#include "round3.h"
#include "prestep.h"
#include "textops_tab.h"

int cds_round3_act_eligible(const char *q) {
    if (!q || !*q || strlen(q) > 127) return 0;
    for (const unsigned char *p = (const unsigned char *)q; *p; p++)
        if (*p < 32 || *p > 126) return 0;
    return 1;
}

int cds_round3_act(const cds_round3 *r, cds_router_work *work, const char *q,
                  int rules_fired, int32_t *margin) {
    if (rules_fired || !cds_round3_act_eligible(q)) return 0;
    cds_route_result p;
    cds_router_run(&r->act, work, q, &p);
    if (margin) *margin = p.margin;
    return p.route && p.route <= R3_PUSHBACK && p.margin >= r->act_threshold ? p.route : 0;
}

static int in_list(const char *const *list, const char *word) {
    for (; *list; list++) if (!strcmp(*list, word)) return 1;
    return 0;
}
static int is_a(int c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
static int path(const char *q, cds_text_token t) {
    int d = -1;
    for (int i = t.s; i < t.e; i++) {
        if (q[i] == '/' || q[i] == '\\' || q[i] == '_') return 1;
        if (q[i] == '.') d = i;
    }
    if (d <= t.s || d == t.e - 1 || t.e - d - 1 > 4) return 0;
    for (int i = d + 1; i < t.e; i++) if (!is_a(q[i])) return 0;
    for (int i = t.s; i < d; i++) if (is_a(q[i])) return 1;
    return 0;
}
static const char *word(const cds_text_token *T, int n, int i) {
    return i < 0 || i >= n ? "edge" : T[i].q ? "quoted" : T[i].lw;
}
static int num(const char *w) {
    static const char *const words[] = {"one","two","three","four","five","six","seven","eight","nine","ten"};
    size_t n = strlen(w);
    if (n <= 2 && n && w[0] >= '0' && w[0] <= '9' && (n == 1 || (w[1] >= '0' && w[1] <= '9')))
        return n == 1 ? w[0] - '0' : (w[0] - '0') * 10 + w[1] - '0';
    for (int i = 0; i < 10; i++) if (!strcmp(w, words[i])) return i + 1;
    return 0;
}
static void literal(const char *q, int a, int b, char *out) {
    memcpy(out, q + a, (size_t)(b - a)); out[b - a] = 0;
}

int cds_round3_textop_lazy(const cds_round3 *r, cds_router_work *work, const char *q,
                          cds_round3_text *result, char *out, size_t cap,
                          cds_round3_load_head ensure, void *ctx) {
    cds_text_token T[130];
    if (!result || !out || cap < 256) return 0;
    memset(result, 0, sizeof *result); out[0] = 0;
    if (!cds_round3_act_eligible(q) || cds_textops_guard(q)) return 0;
    int n = cds_textops_tokens(q, T, 130);
    if (!n || n > 64) return 0;
    for (int i = 0; i < n; i++)
        if (!T[i].q && (in_list(TO_BLOCK, T[i].lw) || path(q, T[i]))) return 0;
    if (ensure && ensure(ctx, 1)) return -1;
    cds_route_result p;
    cds_router_run(&r->op, work, q, &p);
    if (!p.route || p.route > TO_NOPS || p.margin < r->op_threshold) return 0;
    if (ensure && ensure(ctx, 2)) return -1;
    int op = p.route - 1, labs[64];
    int32_t min_margin = 0x7fffffff;
    for (int i = 0; i < n; i++) {
        char context[128];
        snprintf(context, sizeof context, "t %s p %s n %s pp %s nn %s first %d last %d",
                 word(T,n,i),word(T,n,i-1),word(T,n,i+1),word(T,n,i-2),word(T,n,i+2),i==0,i==n-1);
        cds_route_result tag;
        cds_router_run(&r->tag, work, context, &tag);
        labs[i] = tag.route;
        if (tag.margin < min_margin) min_margin = tag.margin;
    }
    if (min_margin < r->tag_threshold) return 0;
    int first[3] = {-1,-1,-1}, last[3] = {-1,-1,-1};
    for (int i = 0; i < n; i++) {
        int role = labs[i] == 1 || labs[i] == 2 ? 0 : labs[i] == 3 ? 1 : labs[i] == 4 ? 2 : -1;
        if (role < 0) continue;
        if (last[role] >= 0 && last[role] != i-1) return 0;
        if (first[role] < 0) {
            if (role == 0 && labs[i] != 1) return 0;
            first[role] = i;
        } else if (role == 0 && labs[i] != 2) return 0;
        last[role] = i;
    }
    if (first[0] < 0) return 0;
    for (int role = 0; role < 3; role++) {
        if (first[role] < 0) continue;
        int quoted = 0;
        for (int i = first[role]; i <= last[role]; i++) quoted |= T[i].q;
        if (quoted && first[role] != last[role]) return 0;
    }
    int a = T[first[0]].s, b = T[last[0]].e, arg_s, arg_l;
    if (!cds_textops_arg(q, T + first[0], last[0] - first[0] + 1, op, &arg_s, &arg_l) || arg_s != a || arg_l != b-a) return 0;
    char text[128], x[128] = "", y[128] = "";
    literal(q,a,b,text);
    int repeat = 0;
    if (op == TO_REPEAT) {
        int count = 0;
        for (int i = 0; i < n; i++) {
            if (T[i].q) continue;
            int v = num(T[i].lw);
            if (!strcmp(T[i].lw,"twice")) v=2;
            if (!strcmp(T[i].lw,"thrice")) v=3;
            if (v) repeat=v, count++;
        }
        if (count != 1 || repeat < 1 || repeat > 10) return 0;
    } else if (op == TO_REPLACE) {
        if (first[1] < 0 || first[2] < 0) return 0;
        literal(q,T[first[1]].s,T[last[1]].e,x);
        literal(q,T[first[2]].s,T[last[2]].e,y);
    } else if (first[1] >= 0 || first[2] >= 0) return 0;
    int len = cds_textops_literal(op,text,repeat,x,y,out,cap);
    if (!len) return 0;
    result->op=op; result->start=a; result->end=b; result->repeat=repeat;
    if (first[1]>=0) result->xstart=T[first[1]].s, result->xend=T[last[1]].e;
    if (first[2]>=0) result->ystart=T[first[2]].s, result->yend=T[last[2]].e;
    result->margin=p.margin; result->tag_margin=min_margin;
    return len;
}

int cds_round3_textop(const cds_round3 *r, cds_router_work *work, const char *q,
                     cds_round3_text *result, char *out, size_t cap) {
    return cds_round3_textop_lazy(r, work, q, result, out, cap, NULL, NULL);
}
