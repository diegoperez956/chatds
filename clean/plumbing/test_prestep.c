/* SPDX-License-Identifier: MIT
 * Host driver for prestep.c (parity test with campaign/pipeline/prestep.py).  stdin: one command per line (tab separated):
 *   S q            style_detect          -> kind style inner | -
 *   A style text   style_apply           -> text
 *   C q            calc_parse + answer   -> expr answer | -
 *   G q            textops guard + guarded textops -> guard op output | guard -
 *   K q            dlg_kind              -> n
 *   P entity q     subst_pronoun         -> text | -
 *   R | N task entity answer lastq ok keep | Y style | T       dialogue state ops, each prints the state dump
 * `test-prestep --size` prints sizeof(cds_dlg); `test-prestep --fuzz N SEED` random/vocabulary soup under ASan/UBSan. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "prestep.h"
#include "prestep_tab.h"
#include "textops.h"

static cds_dlg D;

static void dump(void) {
    printf("%s|%s|%s|%s|%u,%u|%u|%u|%u|%u|%u\n", D.entity, D.answer, D.lastq, D.term, D.cand[0], D.cand[1], D.ncand, D.pend, D.task, D.style, D.ttl);
}

static unsigned long long rs;
static unsigned rnd(void) {
    rs = rs * 6364136223846793005ULL + 1442695040888963407ULL;
    return (unsigned)(rs >> 33);
}

static void one(const char *q) {
    char inner[200], out[600], e[400];
    int style = 0, op = 0;
    cds_style_detect(q, &style, inner, sizeof inner);
    cds_calc_parse(q, e, sizeof e);
    cds_calc_answer(q, out, sizeof out);
    cds_textops_guarded(q, out, CDS_TEXTOPS_OUT_CAP, &op);
    cds_dlg_kind(q);
    cds_dlg_subst_pronoun(q, "Ada Lovelace", out, sizeof out);
}

static int fuzz(int n, unsigned long long seed) {
    static const char *const *LISTS[] = {PS_LEADS, PS_VERBS_S, PS_MODS, PS_PREPS, PS_TRAIL, PS_CALC_FILL, PS_UNITS, PS_TENS, PS_REPAIR, PS_NEG_ANY,
                                         PS_NEG_HEAD, PS_DLG_PUSH, PS_DLG_REPEAT, PS_DLG_PRON, PS_ENT_STOP, PS_SUFF_PREPS, PS_FREE_OK};
    static const char *const SYM[] = {"+", "-", "*", "/", "%", "(", ")", ":", "\"", "'", ",", ".", "=", "5", "12", "3.5", "1,000", "caps", "all caps",
                                      "in uppercase", "plus", "times", "of", "percent", "squared", "half", "point", "and", "x", "hundred", "thousand"};
    rs = seed;
    for (int it = 0; it < n; it++) {
        char q[400];
        int len = 0, mode = (int)(rnd() % 4), target = (int)(rnd() % 140);
        if (mode == 0) {
            for (; len < target; len++)
                q[len] = (char)(1 + rnd() % 255);
        } else {
            while (len < target) {
                const char *w;
                unsigned r = rnd() % 10;
                if (r < 5) {
                    const char *const *L = LISTS[rnd() % (sizeof LISTS / sizeof *LISTS)];
                    int c = 0;
                    while (L[c])
                        c++;
                    w = L[rnd() % (unsigned)c];
                } else
                    w = SYM[rnd() % (sizeof SYM / sizeof *SYM)];
                size_t wl = strlen(w);
                if (len + (int)wl + 1 >= (int)sizeof q)
                    break;
                if (len && rnd() % 6)
                    q[len++] = ' ';
                memcpy(q + len, w, wl);
                len += (int)wl;
            }
        }
        q[len] = 0;
        one(q);
    }
    printf("fuzz ok %d inputs\n", n);
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--size")) {
        printf("%zu\n", sizeof(cds_dlg));
        return 0;
    }
    if (argc == 4 && !strcmp(argv[1], "--fuzz"))
        return fuzz(atoi(argv[2]), strtoull(argv[3], NULL, 10));
    char line[2048];
    cds_dlg_reset(&D);
    while (fgets(line, sizeof line, stdin)) {
        size_t l = strlen(line);
        if (l && line[l - 1] == '\n')
            line[--l] = 0;
        char *f[8] = {0};
        int nf = 0;
        for (char *p = line; nf < 8;) {
            f[nf++] = p;
            char *t = strchr(p, '\t');
            if (!t)
                break;
            *t = 0;
            p = t + 1;
        }
        char out[600], inner[200], e[400];
        int style = 0, op = 0;
        switch (line[0]) {
        case 'S': {
            int k = cds_style_detect(f[1], &style, inner, sizeof inner);
            if (k)
                printf("%d\t%d\t%s\n", k, style, inner);
            else
                printf("-\n");
            break;
        }
        case 'A':
            cds_style_apply(atoi(f[1]), f[2], out);
            printf("%s\n", out);
            break;
        case 'C': {
            int a = cds_calc_parse(f[1], e, sizeof e), b = cds_calc_answer(f[1], out, sizeof out);
            if (a)
                printf("%s\t%s\n", e, b ? out : "-");
            else
                printf("-\n");
            break;
        }
        case 'G': {
            int g = cds_textops_guard(f[1]);
            int n = cds_textops_guarded(f[1], out, CDS_TEXTOPS_OUT_CAP, &op);
            if (n > 0)
                printf("%d\t%s\t%s\n", g, cds_textops_name(op), out);
            else
                printf("%d\t-\n", g);
            break;
        }
        case 'K':
            printf("%d\n", cds_dlg_kind(f[1]));
            break;
        case 'P': {
            int n = cds_dlg_subst_pronoun(f[2], f[1], out, sizeof out);
            printf("%s\n", n ? out : "-");
            break;
        }
        case 'R':
            cds_dlg_reset(&D);
            dump();
            break;
        case 'N':
            cds_dlg_note(&D, atoi(f[1]), f[2], f[3], f[4], atoi(f[5]), atoi(f[6]));
            dump();
            break;
        case 'Y':
            cds_dlg_set_style(&D, atoi(f[1]));
            dump();
            break;
        case 'T':
            printf("take %d\n", cds_dlg_style_take(&D));
            dump();
            break;
        }
    }
    return 0;
}
