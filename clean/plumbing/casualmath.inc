/* c43 only. The historical c14/c42 entry points above are unchanged.
 * Twin: campaign/pipeline/casualmath.py. Serialized shared lexer scratch. */
static int cm_has(const char *list, const char *w) {
    size_t n = strlen(w);
    for (const char *p = list; *p;) {
        const char *e = strchr(p, ' '); size_t k = e ? (size_t)(e - p) : strlen(p);
        if (n == k && !memcmp(p, w, n)) return 1;
        if (!e) break;
        p = e + 1;
    }
    return 0;
}
static const char cm_lead[] = "hi hello hey yo uh um well so ok okay now and please pls whats what is how much many calculate calc compute solve evaluate tell me can could would will you u do math arithmetic quick question q just again but";
static const char cm_tail[] = "please pls plz thanks thx tho though rn lol lmao haha nice ok okay right ugh broke exactly altogether total for me equals equal what";
static const char cm_block[] = "who where when wrote made born capital about reverse flip caps uppercase lowercase sort words list quote song band book movie power root factorial not except instead";
int cds_casual_nonmath(const char *q) {
    int phone = 0, operator_word = 0;
    for (const char *p = q; *p; p++) {
        if ((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z')) {
            char word[32]; size_t n = 0;
            do {
                if (n + 1 < sizeof word) word[n++] = (char)lc((unsigned char)*p);
                p++;
            } while ((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z'));
            word[n] = 0; p--;
            if (cm_has("plus minus times x over mod modulo less divided multiplied multiply divide add subtract sum product percent pct squared cubed square cube remainder half double twice triple quarter split out equals equal", word)) operator_word = 1;
        } else if (is_d(*p)) {
            const char *end = p; while (is_d(*end)) end++;
            if ((*end == '-' || *end == '/') && is_d(end[1])) {
                const char *next = end + 1; while (is_d(*next)) next++;
                if (*end == '-') {
                    if (*next == '-' && is_d(next[1])) return 1;
                    if (end - p == 3 && next - end - 1 == 4) phone = 1;
                } else if (end - p == 4 && next - end - 1 == 2 && *next == '/' && is_d(next[1])) {
                    const char *last = next + 1; while (is_d(*last)) last++;
                    if (last - next - 1 == 2) return 1;
                }
            }
            p = end - 1;
        }
    }
    return phone && !operator_word;
}
static int cm_word(int i, const char *w) { return i < cn && cw(i, w); }
static int cm_literal(int i, char *out, int *next, const char *value) {
    if (cm_word(i, "it") || cm_word(i, "that")) {
        if (!value || !*value) return DECLINE;
        strcpy(out, value); *next = i + 1; return 0;
    }
    return literal(i, out, next);
}
static __attribute__((noinline)) int cm_previous(const char *prev, char *expr, char *value) {
    if (!prev || strncmp(prev, "calc(", 5)) return 0;
    const char *end = strstr(prev + 5, ") = ");
    if (!end || end - prev - 5 > 120 || end == prev + 5) return 0;
    size_t n = (size_t)(end - prev - 5);
    memcpy(expr, prev + 5, n); expr[n] = 0;
    if (strspn(expr, "0123456789.+*/%()-") != n) return 0;
    const char *v = end + 4, *p = v;
    if (*p == '-') p++;
    if (!is_d(*p)) return 0;
    while (is_d(*p)) p++;
    if (*p == '.') { p++; if (!is_d(*p)) return 0; while (is_d(*p)) p++; }
    if (*p || p - v >= 64) return 0;
    char src[128], check[256]; snprintf(src, sizeof src, "calc(%s)", expr);
    if (!cds_apply_calc(src, check, sizeof check) || strcmp(check, prev)) return 0;
    strcpy(value, v); return 1;
}
static __attribute__((noinline)) int cm_replace(const char *prev, const char *rhs, char *out, size_t cap) {
    /* A single binary operation has exactly one replaceable right operand. */
    const char *p = prev; if (*p == '-') p++;
    if (!is_d(*p)) return 0;
    while (is_d(*p)) p++;
    if (*p == '.') { p++; if (!is_d(*p)) return 0; while (is_d(*p)) p++; }
    if (!*p || !strchr("+*/%-", *p)) return 0;
    const char *end = p + 1; if (*end == '-') end++;
    if (!is_d(*end)) return 0;
    while (is_d(*end)) end++;
    if (*end == '.') { end++; if (!is_d(*end)) return 0; while (is_d(*end)) end++; }
    if (*end) return 0;
    int k = snprintf(out, cap, "%.*s%s", (int)(p + 1 - prev), prev, rhs);
    return k > 0 && (size_t)k < cap;
}
static __attribute__((noinline)) int cm_expression(const char *q, const char *prior, const char *value, char *expr, size_t cap) {
    if (!ascii_ok(q) || cds_casual_nonmath(q)) return 0;
    char normalized[128]; size_t n = 0;
    for (size_t i = 0; q[i]; i++) {
        int x = i && (q[i] == 'x' || q[i] == 'X') && is_d(q[i-1]) && is_d(q[i+1]);
        if (n + (x ? 3 : 1) >= sizeof normalized) return 0;
        if (x) normalized[n++] = ' ';
        normalized[n++] = q[i];
        if (x) normalized[n++] = ' ';
    }
    normalized[n] = 0;
    if (calc_lex(normalized)) return 0;
    int a = 0, replace = 0;
    while (a < cn && CT[a].k == 'W' && cm_has(cm_lead, CT[a].t)) {
        if ((cw(a, "what") || cw(a, "how")) && cm_word(a + 1, "about")) { replace = 1; a += 2; break; }
        a++;
    }
    cn -= a; memmove(CT, CT + a, (size_t)cn * sizeof *CT);
    while (cn && CT[cn-1].k == 'W' && cm_has(cm_tail, CT[cn-1].t)) cn--;
    if (!cn) return 0;
    for (int i = 0; i < cn; i++) if (CT[i].k == 'W' && (in_list(PS_CODEW, CT[i].t) || cm_has(cm_block, CT[i].t))) return 0;
    int dest = 0;
    for (int i = 0; i < cn; i++) {
        ctok t = CT[i];
        if (cw(i, "a") && cm_word(i + 1, "dozen")) { t = (ctok){'N', "12"}; i++; }
        else if (cw(i, "dozen")) t = (ctok){'N', "12"};
        else if (cw(i, "out") && cm_word(i + 1, "of")) { t = (ctok){'S', "/"}; i++; }
        CT[dest++] = t;
    }
    cn = dest;
    char lhs[128], rhs[128]; int i;
    if (replace) return !cm_literal(0, rhs, &i, value) && i == cn && prior && cm_replace(prior, rhs, expr, cap);
    int split = cm_word(0, "split"), start = split;
    if (!cm_literal(start, lhs, &i, value)) {
        if (i < cn && CT[i].k == 'W' && cm_has("buck bucks dollar dollars", CT[i].t)) i++;
        if (!split && cm_word(i, "split") && cm_word(i + 1, "between")) { split = 1; i++; }
        if (split) {
            int between = cm_word(i, "between") || cm_word(i, "among"); if (between) i++;
            if (cm_literal(i, rhs, &i, value)) return 0;
            if (!((i + 1 == cn && cm_word(i, "ways")) || (between && (i == cn || (i + 1 == cn && (cm_word(i, "people") || cm_word(i, "friends"))))))) return 0;
            int k = snprintf(expr, cap, "(%s)/(%s)", lhs, rhs); return k > 0 && (size_t)k < cap;
        }
    } else if (split) return 0;
    if (value && *value) {
        if (cm_has("plus minus times x over divided multiplied + - * /", CT[0].t)) {
            if (cn >= 65) return 0;
            memmove(CT + 1, CT, (size_t)cn * sizeof *CT); cn++; CT[0] = (ctok){'N', value};
        } else if (cm_word(0, "add") || cm_word(0, "subtract")) {
            int add = cm_word(0, "add");
            if (!cm_literal(1, rhs, &i, value) && i == cn) {
                int k = snprintf(expr, cap, "(%s)%c(%s)", value, add ? '+' : '-', rhs);
                return k > 0 && (size_t)k < cap;
            }
        }
        for (int j = 0; j < cn; j++) if (cm_word(j, "it") || cm_word(j, "that")) CT[j] = (ctok){'N', value};
    }
    /* Preserve the shared parser's prefix binding and operator precedence. */
    start = 0;
    int simple = !literal(start, lhs, &i) && i == cn;
    int echo = value && *value && CT[0].k == 'N' && simple;
    char body[128]; n = 0;
    for (int j = start; j < cn; j++) {
        size_t k = strlen(CT[j].t);
        if (n + (j != start) + k >= sizeof body) return 0;
        if (j != start) body[n++] = ' ';
        memcpy(body + n, CT[j].t, k); n += k;
    }
    body[n] = 0;
    if (cds_calc_parse(body, expr, cap)) return 1;
    if (echo && strlen(lhs) < cap) { strcpy(expr, lhs); return 1; }
    return 0;
}
int cds_casual_answer(const char *q, const char *previous, char *out, size_t cap) {
    char prior[128] = "", value[64] = "", expr[128], src[136];
    if (!cm_previous(previous, prior, value)) prior[0] = value[0] = 0;
    if (!cm_expression(q, prior[0] ? prior : NULL, value[0] ? value : NULL, expr, sizeof expr) || strlen(expr) > 120) return 0;
    snprintf(src, sizeof src, "calc(%s)", expr);
    return cds_apply_calc(src, out, cap);
}
