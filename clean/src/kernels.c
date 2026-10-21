/* SPDX-License-Identifier: MIT */
#include "internal.h"

/* Host stays independent C. CDS_TEST_ASM enables a counted host test double;
 * only ARM9 links the actual ARMv5TE leaf. No allocation or DTCM reservation. */
#if (defined(ARM9) && !defined(CDS_NO_ASM)) || defined(CDS_TEST_ASM)
#define CDS_USE_ASM 1
static int asm_disabled;
extern int32_t cds_dot32_arm(const int8_t *, const int16_t *);
#endif
#ifdef CDS_TEST_ASM
/* Test-only dispatch evidence: empty widths call no leaf even with a missing
 * lower-bound guard, so leaf counts alone cannot prove the C branch. */
extern unsigned cds_test_c_dispatches, cds_test_asm_dispatches;
#endif

static unsigned quantize(const int32_t *input, int16_t *out, uint32_t width) {
    uint32_t maximum = 0;
    for (uint32_t i = 0; i < width; ++i) {
        uint32_t magnitude = input[i] < 0 ? (uint32_t)(-(int64_t)input[i]) : (uint32_t)input[i];
        if (magnitude > maximum) maximum = magnitude;
    }
    unsigned shift = 0;
    while (maximum > 16383) { maximum >>= 1; ++shift; }
    for (uint32_t i = 0; i < width; ++i) out[i] = (int16_t)(input[i] >> shift);
    return shift; /* 0..18 for every int32 input, including INT32_MIN. */
}

static inline int32_t finish_row(int64_t sum, uint32_t row_scale, unsigned shift,
                                uint64_t *saturations) {
    /* An overflowing product necessarily saturates even after >>24.
     * Avoid overflowing first, including on hostile but valid scale values. */
    if ((sum > INT32_MAX || sum < INT32_MIN) && row_scale &&
        (sum > INT64_MAX / row_scale || sum < INT64_MIN / row_scale)) {
        ++*saturations;
        return sum < 0 ? INT32_MIN : INT32_MAX;
    }
    return cds_clamp((sum * row_scale) >> (24 - shift), saturations);
}

void cds_matvec_reference(int32_t *out, const cds_matrix *m,
                         const int32_t *input, uint32_t gs,
                         int16_t *scratch, uint64_t *saturations) {
    unsigned shift = quantize(input, scratch, m->width);
    uint32_t groups = m->width / gs;
    for (uint32_t r = 0; r < m->height; ++r) {
        const int8_t *w = m->rows + (size_t)r * m->stride;
        int64_t sum = 0;
        for (uint32_t j = 0; j < groups; ++j) {
            int64_t dot = 0;
            for (uint32_t i = 0; i < gs; ++i)
                dot += (int64_t)w[j * gs + i] * scratch[j * gs + i];
            sum += (dot * cds_u16(w + m->width + 2 * j)) >> 15;
        }
        out[r] = finish_row(sum, cds_u32(w + m->width + 2 * groups), shift, saturations);
    }
}

/* ARMv5TE compiler emits signed halfword MACs for the unrolled loop.
 * At gs<=256 each int32 dot is bounded by 2^29. For widths<=1024,
 * nonnegative Q1.15 scales make the row accumulator fit int32 too.
 * Larger shapes use the wide row sum, keeping the same rounding order. */
static inline int32_t dot_group(const int8_t *w, const int16_t *x, uint32_t gs) {
    int32_t sum = 0;
    if (gs == 32) {
#if defined(__GNUC__)
#pragma GCC unroll 32
#endif
        for (uint32_t i = 0; i < 32; ++i) sum += (int32_t)w[i] * x[i];
    } else {
        for (uint32_t i = 0; i < gs; ++i) sum += (int32_t)w[i] * x[i];
    }
    return sum;
}

CDS_HOT __attribute__((noinline, noclone)) void cds_matvec_c(int32_t *out, const cds_matrix *m,
                            const int32_t *input, uint32_t gs,
                            int16_t *scratch, uint64_t *saturations) {
    unsigned shift = quantize(input, scratch, m->width);
    uint32_t groups = m->width / gs;
    for (uint32_t r = 0; r < m->height; ++r) {
        const int8_t *w = m->rows + (size_t)r * m->stride;
        int64_t sum;
        if (m->width <= 1024) {
            int32_t narrow = 0;
            for (uint32_t j = 0; j < groups; ++j) {
                int32_t dot = dot_group(w + j * gs, scratch + j * gs, gs);
                narrow += (int32_t)(((int64_t)dot * cds_u16(w + m->width + 2 * j)) >> 15);
            }
            sum = narrow;
        } else {
            sum = 0;
            for (uint32_t j = 0; j < groups; ++j) {
                int32_t dot = dot_group(w + j * gs, scratch + j * gs, gs);
                sum += ((int64_t)dot * cds_u16(w + m->width + 2 * j)) >> 15;
            }
        }
        out[r] = finish_row(sum, cds_u32(w + m->width + 2 * groups), shift, saturations);
    }
}

/* Same valid-buffer/validated-scale contract as C. Shape/alignment are
 * specialization conditions, not permission to truncate or do unaligned LDR.
 * In particular, a halfword-aligned but not word-aligned scratch is C-safe.
 * Weight bytes/scales need no alignment: LDRSB and cds_u16/u32 are safe.
 */
CDS_HOT __attribute__((noinline, noclone)) void cds_matvec_fast(int32_t *out, const cds_matrix *m,
                            const int32_t *input, uint32_t gs,
                            int16_t *scratch, uint64_t *saturations) {
#ifdef CDS_USE_ASM
    if (!asm_disabled && gs == 32 && m->width >= 32 && m->width <= 1024 &&
        !(m->width % 32) && !((uintptr_t)scratch & 3)) {
#ifdef CDS_TEST_ASM
        ++cds_test_asm_dispatches;
#endif
        unsigned shift = quantize(input, scratch, m->width);
        uint32_t groups = m->width / 32;
        for (uint32_t r = 0; r < m->height; ++r) {
            const int8_t *w = m->rows + (size_t)r * m->stride;
            int32_t sum = 0;
            for (uint32_t j = 0; j < groups; ++j) {
                int32_t dot = cds_dot32_arm(w + 32 * j, scratch + 32 * j);
                sum += (int32_t)(((int64_t)dot * cds_u16(w + m->width + 2 * j)) >> 15);
            }
            out[r] = finish_row(sum, cds_u32(w + m->width + 2 * groups), shift, saturations);
        }
        return;
    }
#endif
#ifdef CDS_TEST_ASM
    ++cds_test_c_dispatches;
#endif
    cds_matvec_c(out, m, input, gs, scratch, saturations);
}

/* Boot-only, no heap. A failure latches C for the process/session lifetime.
 * Never clear an earlier failure. Test both signs, flooring and saturation;
 * this smoke check supplements, not replaces, exhaustive release validation.
 */
int cds_matvec_self_check(void) {
#ifdef CDS_USE_ASM
    if (asm_disabled) return 0;
    int32_t input[32], actual[2], expected[2];
    int16_t scratch[32] __attribute__((aligned(4)));
    unsigned char rows[76];
    for (unsigned i = 0; i < 32; ++i) {
        input[i] = i & 1 ? INT32_MIN : INT32_MAX;
        rows[i] = i & 1 ? 128 : 127;
        rows[38 + i] = (unsigned char)(i * 17);
    }
    rows[32] = rows[70] = 255; rows[33] = rows[71] = 127;
    for (unsigned i = 0; i < 4; ++i) {
        rows[34 + i] = (unsigned char)(UINT32_C(0x7fffffff) >> (8 * i));
        rows[72 + i] = i == 0 ? 1 : 0; /* Deliberately nonsaturating row. */
    }
    cds_matrix m = {(const int8_t *)rows, 2, 32, 38};
    uint64_t a = 7, b = 7;
    cds_matvec_c(expected, &m, input, 32, scratch, &a);
    cds_matvec_fast(actual, &m, input, 32, scratch, &b);
    asm_disabled = a != b || memcmp(expected, actual, sizeof actual) != 0;
    return !asm_disabled;
#else
    return 1;
#endif
}
