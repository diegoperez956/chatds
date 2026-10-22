# SPDX-License-Identifier: MIT
"""Bounded owner-language grammar. Only condition 42 enables these rules."""
import re


def identity(q):
    if not q or len(q) > 127 or re.search(r"[^a-zA-Z0-9 '\?!,\.]+", q):
        return False
    words = re.sub(r"[^a-z0-9 ]", "", q.lower()).split()
    aliases = {'u': 'you', 'r': 'are', 'ur': 'your', 'ure': 'youre'}
    words = [aliases.get(w, w) for w in words]
    while words and words[0] in ('hey', 'hi', 'hello', 'yo', 'so', 'ok', 'okay'):
        words.pop(0)
    while words and words[-1] in ('please', 'pls', 'plz', 'tho'):
        words.pop()
    import rules
    plain = ' '.join(words)
    return bool(re.fullmatch(rules.ACT['identity'], plain) or
                ('introduce' in plain and re.fullmatch(rules.ACT['x'], plain)))


def text(q):
    import prestep
    import textops
    if not prestep.ascii_ok(q):
        return None
    m = re.match(r"^ *(?:caps|capitals) +(?=['\"`])", q, re.I)
    if m:
        canonical = 'uppercase ' + q[m.end():]
        tokens = textops.tokenize(canonical)
        if len(tokens) != 2 or not tokens[1].q:
            return None
    else:
        m = re.match(r'^ *(?:reverse|flip) +(?:the +)?(?:words|word +order|order +of +(?:the +)?words)(?= |:)', q, re.I)
        if m:
            tail = q[m.end():].lstrip(' ')
            tail = re.sub(r'^(?:in|of) +', '', tail, count=1, flags=re.I)
            tail = tail.lstrip(': ')
        else:
            m = re.match(r'^ *(?:put|place|arrange) +(?:the +)?words +(?:of|in) +(.+?) +in reverse order(?=$|[ ?!.])(.*)$', q, re.I)
            if not m:
                return None
            tail = m.group(1) + m.group(2)
        canonical = 'reverse words in ' + tail
    if len(canonical) > 127 or prestep.textops_guard(canonical):
        return None
    return textops.textops(canonical)


def _prefix(q):
    tail = q.lstrip(' ')
    changed = False
    for _ in range(3):
        m = re.match(r'^(?:quick question|quick q|hey|hi|hello|yo|uh|um|well|so)(?:[ ,!:]+)', tail, re.I)
        if not m:
            break
        if _ == 2:
            return None
        tail = tail[m.end():]
        changed = True
    return tail if changed and tail else None


def calc(q, apply_calc):
    import prestep
    if not prestep.ascii_ok(q):
        return None
    # Bounded prefix groups and terminal particles; unknown internal words decline.
    q = _prefix(q) or q
    q = re.sub(r'^ *(?:can|could|would|will) +you +', '', q, count=1, flags=re.I)
    q = re.sub(r'^ *(?:math|arithmetic) *: *', '', q, count=1, flags=re.I).rstrip(' ?!.,')
    for _ in range(2):
        m = re.search(r' +(?:for me|tho|though|rn|please|pls|plz)$', q, re.I)
        if not m:
            break
        q = q[:m.start()].rstrip(' ?!.,')
    return prestep.calc_answer(q, apply_calc) or prestep.calc_prose_answer(q, apply_calc)


def grounded(q, answer, apply_calc):
    import prestep
    return calc(q, apply_calc) == answer or prestep.calc_grounded(q, answer, apply_calc)


def fact(q, hp):
    import prestep
    if not prestep.ascii_ok(q):
        return None
    tail = _prefix(q)
    if (not tail or identity(tail) or
            hp.rules_decide(tail)['handler'] != 'facts'):
        return None
    return tail if (hp.rules.v0_gate(tail) or re.search(hp.rules.FACT_CUE, hp.plain_of(tail))) else None
