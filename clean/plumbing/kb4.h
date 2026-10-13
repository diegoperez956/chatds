/* SPDX-License-Identifier: MIT
 * KB4 reader and ranked entity+relation retrieval. C twin of corpus/kb/kb4.py and corpus/kb/retrieve4.py
 * (layout: corpus/kb/FORMAT-KB4.md).
 * Fixed buffers, bounded loops, no malloc. Reads go through one 512-byte sector buffer; every read is bounds-checked. */
#ifndef CDS_KB4_H
#define CDS_KB4_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define CDS4_CAND_MAX 4
#define CDS4_KEY_MAX 63
#define CDS4_REC_MAX 510
#define CDS4_MAX_FIELDS 14 /* KB4.1 adds creator, height, length; KB4 accepts <=12 */
#define CDS4_POOL 8
#define CDS4_MAX_WORDS 32
#define CDS4_QUESTION_MAX 127
#define CDS4_CTX_CAP 256

/* relation codes (record fields / mask bits) */
enum { C4R_DEFINITION = 0, C4R_DATE_RANGE, C4R_BIRTH_DATE, C4R_BIRTH_PLACE, C4R_DEATH_DATE, C4R_DEATH_PLACE,
       C4R_LOCATION, C4R_SURNAME, C4R_CAPITAL, C4R_OCCUPATION, C4R_QUANTITY, C4R_CREATOR, C4R_HEIGHT, C4R_LENGTH, C4R_COUNT };
extern const char *const cds4_rel_name[C4R_COUNT];

typedef enum { CDS4_OPEN_OK = 0, CDS4_OPEN_MISSING = -1, CDS4_OPEN_CORRUPT = -2, CDS4_OPEN_IO = -3 } cds4_open_status;
enum { CDS4_E_NONE = 0, CDS4_E_IO = 1, CDS4_E_CORRUPT = 2 };

typedef struct {
    uint32_t recoff;
    uint8_t kind, prom, etype;
    uint16_t pmask, mmask;
} cds4_cand;

typedef struct {
    uint8_t rel, flags, vlen; /* flags bit0 = missing marker, bits 1..3 = provenance */
    uint16_t source_sid, end_sid; /* KB4.1 prose ordinals, 65535 infobox; flags bit4 conflict */
    char value[64];
} cds4_field;

/* A decoded record keeps the identity, the definition and ONE requested field (all fields are still validated). */
typedef struct {
    uint32_t eid;
    uint8_t etype, prom;
    char title[64];
    char def[112];
    int found;       /* requested field present in the record (value or missing marker) */
    cds4_field f;    /* the requested field */
} cds4_rec;

typedef struct {
    FILE *f;
    uint32_t size, nb, bt, ko, ro, fnb, fbt, fent, fwo, fzmin, version; /* fzmin: shortest word in the delete index */
    uint32_t sector; /* sector held in buf, UINT32_MAX = none */
    unsigned char buf[512];
    int err;         /* CDS4_E_* since err was last cleared */
    uint32_t lookups, sector_reads;
    long fault_after; /* tests: fail the Nth sector read from now on (<0 = never) */
} cds4_kb;

cds4_open_status cds4_open(cds4_kb *kb, const char *path);
void cds4_close(cds4_kb *kb);
/* exact lookup of an already-normalized key. n candidates (0 = miss), -1 on error (kb->err) */
int cds4_lookup(cds4_kb *kb, const char *key, cds4_cand out[CDS4_CAND_MAX]);
/* delete-index candidates for q: n words in out (most frequent first); *known = q itself is indexed. -1 on error */
int cds4_fuzzy(cds4_kb *kb, const char *q, char out[CDS4_CAND_MAX][CDS4_KEY_MAX + 1], int *known);
/* want_rel: relation code whose field is copied into r->f (C4R_DEFINITION: none). -1 on error */
int cds4_record(cds4_kb *kb, uint32_t recoff, int want_rel, cds4_rec *r);

/* ---- ranked retrieval ---- */
typedef enum { CDS4_ANSWER_PRESENT = 0, CDS4_FIELD_MISSING, CDS4_AMBIGUOUS, CDS4_NO_MATCH, CDS4_GATED, CDS4_IO_ERROR,
               CDS4_CORRUPT_KB } cds4_status;
extern const char *const cds4_status_name[7];

typedef struct {
    cds4_status status;
    int field;                 /* relation code requested (C4R_*) */
    uint32_t eid;              /* chosen entity (valid unless NO_MATCH/GATED/errors) */
    uint32_t recoff;           /* chosen record; bounded dialogue candidate handle */
    char title[64];
    char value[112];           /* field value (or definition) when answer_present */
    uint8_t prov, field_flags;
    uint16_t source_sid, end_sid;
    char context[CDS4_CTX_CAP]; /* rendered evidence sentence when answer_present */
    uint32_t alt_recoff[CDS4_POOL];
    int n_alt;
    /* log */
    uint32_t sector_reads, lookups;
    int keys_tried, candidates, expansion;
    uint32_t keys_hash;        /* FNV-1a over the tried keys, '\n'-joined */
    const char *reason;        /* fallback reason, NULL if none */
} cds4_result;

/* Working state of one retrieval; sizeof is the retrieval's whole RAM besides the kb handle and the result. */
typedef struct cds4_ctx cds4_ctx;
size_t cds4_ctx_size(void);
/* k = candidates re-ranked by the requested relation (1 = entity score only), expand = allow the one bounded expansion.
 * routed: the router already decided this is a facts question, so a missing question word does not gate it.
 * ctx must point at cds4_ctx_size() bytes (suitably aligned; use cds4_ctx_storage). Returns the status. */
cds4_status cds4_retrieve(cds4_ctx *ctx, cds4_kb *kb, const char *question, int k, int expand, int routed, cds4_result *res);

/* ISO date rendering shared by evidence and product direct-field answers. */
int cds4_date_text(char *out, size_t cap, const char *value);

/* aligned storage for a ctx on the caller's stack/static data */
#define CDS4_CTX_BYTES 3072
typedef union { unsigned char b[CDS4_CTX_BYTES]; void *align; } cds4_ctx_storage;

#endif
