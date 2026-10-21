/* SPDX-License-Identifier: MIT
 * Shared host/ARM test. Host double counts leaf calls; ARM --wrap calls the
 * actual assembly and permits fault injection without touching product code.
 */
#include "internal.h"
#include <assert.h>
#include <stdio.h>

unsigned cds_test_calls, cds_test_c_dispatches, cds_test_asm_dispatches;
int cds_test_fault;
#ifdef ARM9
extern int32_t __real_cds_dot32_arm(const int8_t *, const int16_t *);
int32_t __wrap_cds_dot32_arm(const int8_t *w, const int16_t *x) {
    ++cds_test_calls;
    return __real_cds_dot32_arm(w, x) + cds_test_fault;
}
#else
int32_t cds_dot32_arm(const int8_t *w, const int16_t *x) {
    int32_t sum = 0;
    ++cds_test_calls;
    for (unsigned i = 0; i < 32; ++i) sum += w[i] * x[i];
    return sum + cds_test_fault;
}
#endif
static int32_t input[1056];
static int16_t scratch[1060] __attribute__((aligned(4)));
static unsigned char rows[4 * 1130] __attribute__((aligned(4)));
static unsigned rng = 611;
static unsigned random32(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }

static void check(unsigned width, unsigned gs, unsigned offset, unsigned row_offset, int use_asm) {
    unsigned stride = width + 2 * (width / gs) + 4;
    cds_matrix m = {(const int8_t *)rows + row_offset, 4, width, stride};
    for (unsigned trial = 0; trial < 48; ++trial) {
        for (unsigned i = 0; i < width; ++i) {
            unsigned v = random32(); memcpy(input + i, &v, 4);
            if (trial == 0) input[i] = 0;
            if (trial == 1) input[i] = INT32_MIN;
            if (trial == 2) input[i] = INT32_MAX;
            if (trial == 3) input[i] = i & 1 ? 16383 : -16384;
            if (trial == 4) input[i] = i & 1 ? 32767 : -32768;
            if (trial >= 5 && trial < 24) input[i] /= 1 << (trial - 5);
        }
        for (unsigned r = 0; r < 4; ++r) {
            unsigned char *w = rows + row_offset + stride * r;
            for (unsigned i = 0; i < width; ++i) w[i] = trial < 5 ? 128 : (unsigned char)random32();
            for (unsigned g = 0; g < width / gs; ++g) {
                unsigned scale = trial == 0 ? 0 : trial == 1 ? 1 : trial < 5 ? 32767 : random32() & 32767;
                w[width + 2*g] = scale; w[width + 2*g + 1] = scale >> 8;
            }
            unsigned rs = trial == 0 ? 0 : trial < 5 ? INT32_MAX : random32() & INT32_MAX;
            for (unsigned i = 0; i < 4; ++i) w[width + 2*(width/gs) + i] = rs >> (8*i);
        }
        int32_t a[6], b[6], c[6]; uint64_t sa = 7, sb = 7, sc = 7;
        for (unsigned i = 0; i < 6; ++i) a[i] = b[i] = c[i] = 0x12345678;
        memset(scratch, 0x65, sizeof scratch);
        int16_t *q = scratch + 2 + offset;
        unsigned before = cds_test_calls, c_before = cds_test_c_dispatches;
        unsigned asm_before = cds_test_asm_dispatches;
        cds_matvec_fast(a + 1, &m, input, gs, q, &sa);
        assert(cds_test_calls - before == (use_asm ? 4 * (width/gs) : 0));
        assert(cds_test_c_dispatches - c_before == (use_asm ? 0u : 1u));
        assert(cds_test_asm_dispatches - asm_before == (use_asm ? 1u : 0u));
        assert(q[-1] == 0x6565 && q[width] == 0x6565);
        cds_matvec_c(b + 1, &m, input, gs, q, &sb);
        cds_matvec_reference(c + 1, &m, input, gs, q, &sc);
        assert(sa == sb && sb == sc);
        assert(!memcmp(a, b, sizeof a) && !memcmp(b, c, sizeof b));
    }
}

void cds_test_asm_shapes(void) {
    /* Every guard independently forced, including invalid-loader widths. C's
     * historical floor(width/gs) behavior is preserved, not redefined here. */
    check(48, 32, 0, 0, 0);  /* width%32 */
    check(33, 32, 0, 1, 0);  /* odd byte rows/scales too */
    check(0, 32, 0, 0, 0);   /* below minimum */
    check(16, 32, 0, 0, 0);
    check(1056, 32, 0, 0, 0);/* above maximum */
    check(64, 16, 0, 0, 0);  /* group !=32, otherwise eligible */
    check(64, 64, 0, 0, 0);
    check(32, 32, 1, 0, 0);  /* legal int16*, not word aligned */
    check(192, 32, 1, 0, 0);
    check(512, 32, 1, 0, 0);
    check(32, 32, 0, 0, 1);
    check(192, 32, 0, 1, 1); /* byte-aligned serialized weights safe */
    check(512, 32, 0, 2, 1);
    check(1024, 32, 0, 0, 1);
    assert(cds_matvec_self_check());
}

void cds_test_asm_disable(void) {
    cds_test_fault = 65536; /* visible after scale/floor, unlike +1 */
    assert(!cds_matvec_self_check());
    unsigned before = cds_test_calls;
    cds_test_fault = 0;
    assert(!cds_matvec_self_check()); /* failure stays latched */
    check(192, 32, 0, 0, 0);
    assert(cds_test_calls == before);
}
#ifndef ARM9
int main(void) {
    cds_test_asm_shapes();
    cds_test_asm_disable();
    puts("PASS: 2880 rows; forced guards + scratch fallback + boot fault latch; C == reference == seam");
    return 0;
}
#endif
