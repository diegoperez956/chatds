/* SPDX-License-Identifier: MIT: ARM execution/parity/timing diagnostic only. */
#include <nds.h>
#include <fat.h>
#include <stdio.h>
#include <stdlib.h>
#include "internal.h"

extern void cds_test_asm_shapes(void), cds_test_asm_disable(void);
extern unsigned cds_test_calls;
extern int32_t probe_thumb_dot(const int8_t *, const int16_t *);
unsigned probe_variant;
static int32_t input[1024], gold[2048], out[2048];
static int16_t scratch[1024] __attribute__((aligned(4)));
static int32_t logits[16][2048];
static uint64_t sats[16];
static unsigned rng = 611, checks;
static uint32_t random32(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
static void logline(const char *s) {
    static char published[256];
    snprintf(published, sizeof published, "%s\n", s);
    nocashMessage(published);
}
static void fail(const char *s) { logline(s); for (;;) swiWaitForVBlank(); }
void probe_matvec(int32_t *o, const cds_matrix *m, const int32_t *x, uint32_t gs, int16_t *q, uint64_t *sat) {
    if (probe_variant) cds_matvec_fast(o, m, x, gs, q, sat);
    else cds_matvec_c(o, m, x, gs, q, sat);
}
static void verify(const cds_matrix *m, unsigned mode) {
    for (unsigned i = 0; i < m->width; ++i) {
        unsigned v = random32(); memcpy(input + i, &v, 4);
        if (!mode) input[i] = 0;
        if (mode == 1) input[i] = INT32_MIN;
        if (mode == 2) input[i] = INT32_MAX;
        if (mode == 3) input[i] = i & 1 ? 16383 : -16384;
        if (mode == 4) input[i] = i & 1 ? 32767 : -32768;
    }
    uint64_t a = 7, b = 7, c = 7;
    cds_matvec_reference(gold, m, input, 32, scratch, &a);
    cds_matvec_c(out, m, input, 32, scratch, &b);
    if (a != b || memcmp(out, gold, m->height * 4)) fail("ASMKERN FAIL C rows");
    cds_matvec_fast(out, m, input, 32, scratch, &c);
    if (a != c || memcmp(out, gold, m->height * 4)) fail("ASMKERN FAIL ASM rows");
    checks += m->height;
}
int main(void) {
    consoleDemoInit(); cpuStartTiming(0);
    logline("ASMKERN START EMULATED");
    if (!fatInitDefault()) fail("ASMKERN FAIL mount");
#ifndef CDS_TIMING_PROBE
    cds_test_asm_shapes();
    logline("ASMKERN SHAPES rows=2688 fallback_guards=10 PASS");
#endif
    if (!cds_matvec_self_check()) fail("ASMKERN FAIL boot check");
    int8_t w[32]; int16_t x[32] __attribute__((aligned(4)));
    for (unsigned i = 0; i < 32; ++i) { w[i] = i - 16; x[i] = i * 511 - 8192; }
    int32_t dot = 0;
    for (unsigned i = 0; i < 32; ++i) dot += w[i] * x[i];
    if (probe_thumb_dot(w, x) != dot) fail("ASMKERN FAIL Thumb interworking");
    logline("ASMKERN THUMB PASS");
    chatds_model *m = NULL;
    if (chatds_model_load("/model.bin", &m) != CHATDS_OK) fail("ASMKERN FAIL load");
    for (unsigned mode = 0; mode < 8; ++mode) {
        verify(&m->embedding, mode);
        for (unsigned i = 0; i < 7 * m->config.layers; ++i) verify(m->matrices + i, mode);
    }
    char msg[180];
    snprintf(msg, sizeof msg, "ASMKERN ROWS rows=%u PASS", checks); logline(msg);
    vramSetBankD(VRAM_D_LCD); vramSetBankE(VRAM_E_LCD);
    chatds_session *s = NULL;
    if (chatds_session_create_with_keys(m, NULL, (int16_t *)0x06860000, 192*1024, &s) != CHATDS_OK)
        fail("ASMKERN FAIL session");
    /* Real history, not zero KV: same deterministic prefix and 16 forced IDs
     * per context, both variants. Main-RAM activations + VRAM keys as product.
     * Timed forward includes classification; comparisons/logging outside. */
    for (unsigned cohort = 0; cohort < 2; ++cohort) {
        unsigned start = cohort ? 224 : 0;
        for (probe_variant = 0; probe_variant < 2; ++probe_variant) {
            chatds_session_reset(s);
            for (unsigned i = 0; i < start; ++i)
                if (chatds_session_forward(s, 16 + i%100, NULL) != CHATDS_OK) fail("ASMKERN FAIL prefix");
            for (unsigned i = 0; i < 16; ++i) {
                chatds_output result;
                uint32_t t = cpuGetTiming();
                if (chatds_session_forward(s, 16 + i, &result) != CHATDS_OK) fail("ASMKERN FAIL forward");
                uint32_t elapsed = cpuGetTiming() - t;
                if (!probe_variant) { memcpy(logits[i], result.logits_q16, sizeof logits[i]); sats[i] = s->saturations; }
                else if (memcmp(logits[i], result.logits_q16, sizeof logits[i]) || sats[i] != s->saturations)
                    fail("ASMKERN FAIL logits/saturations");
                snprintf(msg, sizeof msg, "ASMKERN TOKEN k=%s start=%u i=%u ticks=%lu",
                         probe_variant ? "ASM" : "C", start, i, (unsigned long)elapsed); logline(msg);
            }
        }
    }
    logline("ASMKERN LOGITS forwards=32 logits=65536 PASS");
    chatds_session_destroy(s); chatds_model_destroy(m);
#ifndef CDS_TIMING_PROBE
    cds_test_asm_disable();
    logline("ASMKERN FAULT-LATCH rows=192 PASS");
#endif
    logline("ASMKERN DONE PASS");
    for (;;) swiWaitForVBlank();
}
