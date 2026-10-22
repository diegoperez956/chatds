/* SPDX-License-Identifier: MIT: process-local diagnostic stdout flushing. */
#include <stdio.h>
__attribute__((constructor)) static void flush_logs(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
}
