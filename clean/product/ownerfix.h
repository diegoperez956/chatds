/* SPDX-License-Identifier: MIT */
#ifndef CHATDS_OWNERFIX_H
#define CHATDS_OWNERFIX_H
#include <stddef.h>
int owner_identity(const char *q);
int owner_text(const char *q, char *out, size_t cap, int *op);
int owner_calc(const char *q, char *out, size_t cap);
int owner_grounded(const char *q, const char *answer);
int owner_fact(const char *q, char *out, size_t cap);
#endif
