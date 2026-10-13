/* SPDX-License-Identifier: MIT
 * Host driver for textops.c. stdin: one question per line -> "op\tanswer" or "-" per line (parity test).
 * `test-textops --fuzz N SEED`: N random strings built from the phrase vocabulary and raw bytes; ASan/UBSan must stay quiet. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "textops.h"
#include "textops_tab.h"

static unsigned long long rs;
static unsigned rnd(void) {
    rs = rs * 6364136223846793005ULL + 1442695040888963407ULL;
    return (unsigned)(rs >> 33);
}

static int fuzz(int n, unsigned long long seed) {
    int nv = 0, hits = 0;
    while (TO_VOCAB[nv])
        nv++;
    rs = seed;
    for (int it = 0; it < n; it++) {
        char q[300], out[CDS_TEXTOPS_OUT_CAP];
        int len = 0, mode = (int)(rnd() % 4), target = (int)(rnd() % 140);
        if (mode == 0) { /* raw bytes, including NUL-free control and high bytes */
            for (; len < target; len++)
                q[len] = (char)(1 + rnd() % 255);
        } else {
            while (len < target) {
                const char *w;
                unsigned r = rnd() % 10;
                if (mode == 1 || r < 6)
                    w = TO_VOCAB[rnd() % (unsigned)nv];
                else if (r == 6)
                    w = "\"";
                else if (r == 7)
                    w = "'x y'";
                else if (r == 8)
                    w = ":";
                else
                    w = "hello";
                size_t wl = strlen(w);
                if (len + (int)wl + 1 >= (int)sizeof q)
                    break;
                if (len && rnd() % 8)
                    q[len++] = ' ';
                memcpy(q + len, w, wl);
                len += (int)wl;
            }
        }
        q[len] = 0;
        int op = -1, n2 = cds_textops(q, out, sizeof out, &op);
        if (n2 > 0) {
            hits++;
            if ((size_t)n2 != strlen(out) || n2 > 255 || op < 0 || op >= TO_NOPS) {
                fprintf(stderr, "bad result for [%s]\n", q);
                return 1;
            }
        }
    }
    printf("fuzz ok %d inputs, %d answered\n", n, hits);
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 4 && !strcmp(argv[1], "--fuzz"))
        return fuzz(atoi(argv[2]), strtoull(argv[3], NULL, 10));
    char line[1024], out[CDS_TEXTOPS_OUT_CAP];
    while (fgets(line, sizeof line, stdin)) {
        size_t l = strlen(line);
        if (l && line[l - 1] == '\n')
            line[--l] = 0;
        int op = -1, n = cds_textops(line, out, sizeof out, &op);
        if (n > 0)
            printf("%s\t%s\n", cds_textops_name(op), out);
        else
            printf("-\n");
    }
    return 0;
}
