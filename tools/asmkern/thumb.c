/* SPDX-License-Identifier: MIT: force a real Thumb caller in diagnostic ROM. */
#include <stdint.h>
extern int32_t cds_dot32_arm(const int8_t *, const int16_t *);
__attribute__((noinline)) int32_t probe_thumb_dot(const int8_t *w, const int16_t *x) {
    return cds_dot32_arm(w, x);
}
