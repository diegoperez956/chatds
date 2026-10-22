/* SPDX-License-Identifier: MIT
 * Deterministic text operations (uppercase, reverse, counts, replace, ...) for requests a small LM gets wrong.
 * C twin of campaign/pipeline/textops.py (same parser, phrase tables generated into textops_tab.h).
 * ASCII only, input <= 127 bytes, no malloc, small stack, ~3 KiB of static scratch, not reentrant. Declines (CDS_NOT_TEXT_OP) when unsure. */
#ifndef CDS_TEXTOPS_H
#define CDS_TEXTOPS_H
#include <stddef.h>

#define CDS_NOT_TEXT_OP 0
#define CDS_TEXTOPS_OUT_CAP 256 /* output buffer size the caller must provide; answers are <= 255 bytes, never truncated */

enum {
    TO_UPPER, TO_LOWER, TO_TITLE, TO_CAPITALIZE, TO_REVERSE, TO_REVERSE_WORDS, TO_COUNT_LETTERS, TO_COUNT_CHARS,
    TO_COUNT_CHARS_NOSPACE, TO_COUNT_WORDS, TO_COUNT_VOWELS, TO_REMOVE_SPACES, TO_REPEAT, TO_REPLACE, TO_INITIALS,
    TO_ACRONYM, TO_SORT_WORDS, TO_FIRST_WORD, TO_LAST_WORD, TO_PALINDROME, TO_SPELL, TO_NOPS
};

/* Returns the answer length (> 0) with the NUL-terminated answer in out and the op id in *op (may be NULL),
 * or CDS_NOT_TEXT_OP (0) when the request is not a confident text operation. cap must be >= CDS_TEXTOPS_OUT_CAP. */
int cds_textops(const char *question, char *out, size_t cap, int *op);
const char *cds_textops_name(int op);
/* Extract an explicit length literal: 1 = word/string/text named, 2 = caller
 * must exclude KB entities, 0 = decline. cap includes the terminating NUL. */
int cds_textops_length_literal(const char *question, char *literal, size_t cap);

/* Round 3 learned-span seam, called by round3.c. Offsets index the ORIGINAL request, never normalized.
 * cds_textops_tokens has a ~2.9 KiB frame; the c24 ARM9 stack gate covers it. */
typedef struct {
    unsigned short s, e;
    unsigned char q;
    char lw[16];
} cds_text_token;
int cds_textops_tokens(const char *question, cds_text_token *tokens, size_t capacity);
int cds_textops_arg(const char *question, const cds_text_token *tokens, int n, int op, int *start, int *length);
/* Bounded executor for already-extracted literal substrings. No routing or parsing. */
int cds_textops_literal(int op, const char *literal, int repeat, const char *x, const char *y, char *out, size_t cap);
#endif
