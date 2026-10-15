/* SPDX-License-Identifier: MIT
 * Pocket notebook prototype: no heap, no model, caller-owned spec/results. */
#ifndef CDS_MATHNB_H
#define CDS_MATHNB_H
#include <stdint.h>
#include <stddef.h>
#define MNB_SCALE 10000
#define MNB_LIMIT 100000000 /* +/-10000 real units, including intermediates */
#define MNB_NODES 32
#define MNB_DEPTH 8
#define MNB_POINTS 129
#define MNB_BARS 16
#define MNB_REFUSAL "Sorry, this notebook supports bounded expressions, ranges and lists only."
enum mnb_kind { MNB_PLOT=1, MNB_BAR, MNB_TABLE };
enum mnb_op { MNB_CONST, MNB_X, MNB_ADD, MNB_SUB, MNB_MUL, MNB_DIV,
              MNB_POW, MNB_NEG, MNB_SIN, MNB_COS, MNB_SQRT, MNB_ABS };
typedef struct { int32_t value; uint8_t op, left, right, reserved; } mnb_node;
typedef struct {
    uint8_t kind, nodes, root, reserved;
    uint16_t points;
    int32_t lo, hi;
    mnb_node ast[MNB_NODES];
    int32_t bars[MNB_BARS];
} mnb_spec;
typedef struct { int32_t x[MNB_POINTS], y[MNB_POINTS]; } mnb_values;
/* 0=not mine (prose or unsupported syntax), 1=validated spec,
 * -1=unambiguous notebook request exceeds bounds; polite refusal required.
 * Domain/overflow samples refuse the whole request; no hidden gaps. */
int mnb_parse(const char *query, mnb_spec *spec);
int mnb_validate(const mnb_spec *spec);
int mnb_evaluate(const mnb_spec *spec, mnb_values *values);
/* ARGB1555, exactly 256x192. Existing UI font; invalid inputs leave fb alone. */
int mnb_render(const mnb_spec *spec, const mnb_values *values, uint16_t *fb);
#endif
