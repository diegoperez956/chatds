/* SPDX-License-Identifier: MIT
 * c14 pre-routing steps: style wrappers, deterministic calc() parser, textops negative guard, bounded dialogue state.
 * C twin of campaign/pipeline/prestep.py (same logic; phrase tables generated into prestep_tab.h by `prestep.py --emit-h`).
 * ASCII only, input <= 127 bytes, no malloc, ~3 KiB of static scratch (not reentrant); every function declines (returns 0) when unsure. */
#ifndef CDS_PRESTEP_H
#define CDS_PRESTEP_H
#include <stddef.h>
#include <stdint.h>

#define CDS_PS_QMAX 127
#define CDS_PS_STYLE_TTL 8 /* a session style preference applies to the next 8 answers */
#define CDS_PS_EXPR_CAP 320 /* expression buffer for cds_calc_parse (expressions over 300 bytes decline) */

/* ---- 1. style wrappers.  kinds: */
enum { CDS_ST_NONE = 0, CDS_ST_WRAP, CDS_ST_PREFIX, CDS_ST_SUFFIX, CDS_ST_LITERAL, CDS_ST_FREE };
enum { CDS_STYLE_NONE = 0, CDS_STYLE_UPPER, CDS_STYLE_LOWER, CDS_STYLE_TITLE };
/* Returns the kind (0 = no style wrapper). *style = 1 upper / 2 lower / 3 title; inner (cap bytes) = the request to answer
 * normally (wrap/prefix/suffix), the literal text (literal) or "" (free: nothing to say, ask). */
int cds_style_detect(const char *q, int *style, char *inner, size_t cap);
/* ASCII transform, same length; title follows Python str.title().  in == out is allowed. */
void cds_style_apply(int style, const char *in, char *out);

/* ---- 2. calc parser: expression for calc() from digits / number words / operator words / % / parentheses.
 * Returns the expression length (0 = decline). cds_calc_answer returns "calc(expr) = value" (0 = decline or not evaluable). */
int cds_calc_parse(const char *q, char *expr, size_t cap);
int cds_calc_answer(const char *q, char *out, size_t cap);

/* ---- 3. textops negative guard: 1 when q is a question ABOUT a text operation (or a look-alike), not a request to run one */
int cds_textops_guard(const char *q);
int cds_textops_guarded(const char *q, char *out, size_t cap, int *op); /* guard, then cds_textops */

/* ---- 4. bounded dialogue state (fixed size, no pointers) */
#define CDS_DLG_ENT 47
#define CDS_DLG_ANS 200
#define CDS_DLG_Q 127
#define CDS_DLG_TERM 23
enum { CDS_TASK_NONE = 0, CDS_TASK_FACTS, CDS_TASK_CALC, CDS_TASK_TEXT, CDS_TASK_CONV, CDS_TASK_OTHER };
enum { CDS_DK_NONE = 0, CDS_DK_REPEAT, CDS_DK_PUSHBACK, CDS_DK_CANCEL, CDS_DK_STYLE_OFF, CDS_DK_FIRST, CDS_DK_OTHER };
typedef struct {
    char entity[CDS_DLG_ENT + 1];  /* last resolved entity title ("" none): pronoun follow-ups */
    char answer[CDS_DLG_ANS + 1];  /* capped last answer: "repeat" replays it exactly */
    char lastq[CDS_DLG_Q + 1];     /* the question that produced it (pronouns already substituted): pushback re-derives it */
    char term[CDS_DLG_TERM + 1];   /* pending clarification term ("" none) */
    uint32_t cand[2];              /* pending candidate record ids ("the first one" / "the other one") */
    uint8_t ncand, pend, task, style, ttl; /* ncand 0..2; pend 0/1; task CDS_TASK_*; style CDS_STYLE_*; ttl answers left for style */
} cds_dlg;
/* Expiry: a pending clarification and its candidates live one turn; entity, candidates and pending go on a calc/text/other topic
 * switch; everything (style included) goes on an error or cancel (cds_dlg_note ok=0, cds_dlg_reset); style after CDS_PS_STYLE_TTL answers. */
void cds_dlg_reset(cds_dlg *d);
int cds_dlg_kind(const char *q); /* CDS_DK_* for a follow-up utterance, 0 otherwise */
/* "when was he born" + entity -> "when was <entity> born" (pronoun and no entity words of its own).  Returns the length, 0 = no change. */
int cds_dlg_subst_pronoun(const char *q, const char *entity, char *out, size_t cap);
void cds_dlg_note(cds_dlg *d, int task, const char *entity, const char *answer, const char *lastq, int ok, int keep_answer);
void cds_dlg_set_style(cds_dlg *d, int style);
int cds_dlg_style_take(cds_dlg *d); /* style to apply to this answer (0 none); spends one unit of ttl */
#endif
