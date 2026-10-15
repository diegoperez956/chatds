/* SPDX-License-Identifier: MIT */
#ifndef CDS_PRODUCT_RULES_H
#define CDS_PRODUCT_RULES_H
#include <stddef.h>
enum { H_FACTS, H_PYTHON, H_SHELL, H_CALC, H_TEXT, H_CONVERSATION, H_CLARIFY, H_UNSUPPORTED, H_UNCLEAR, H_MATHNB };
enum { A_NONE, A_GREETING, A_THANKS, A_BYE, A_HOW_ARE_YOU, A_ACK, A_IDENTITY, A_CAPABILITIES, A_REPEAT, A_PUSHBACK, A_COMPLIMENT, A_INSULT };
typedef struct { int handler, act; } c14_decision;
c14_decision c14_rules(const char *q);
void c14_plain(const char *q, char *out);
int c14_has(const char *text, const char *words);
int c14_entity_words(const char *q);
int c14_pronoun(const char *q);
int c14_cue(const char *q);
int c24_primary_fact(const char *q);
const char *c14_ambig(const char *q);
#endif
