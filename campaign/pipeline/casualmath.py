# SPDX-License-Identifier: MIT
"""c43 bounded casual arithmetic. No decoder expressions supply evidence."""
import re
import prestep as ps

LEAD = set(('hi hello hey yo uh um well so ok okay now and please pls whats what is how much many '
            'calculate calc compute solve evaluate tell me can could would will you u do math arithmetic '
            'quick question q just again but').split())
TAIL = set(('please pls plz thanks thx tho though rn lol lmao haha nice ok okay right ugh broke '
            'exactly altogether total for me equals equal what').split())
BLOCK = set(ps.CODEW) | set('who where when wrote made born capital about reverse flip caps uppercase lowercase sort words list quote song band book movie power root factorial not except instead'.split())
# "about" is consumed only by the explicit contextual replacement production.
UNITS = set('buck bucks dollar dollars'.split())
OPERATOR_WORDS = set(('plus minus times x over mod modulo less divided multiplied multiply divide '
                      'add subtract sum product percent pct squared cubed square cube remainder '
                      'half double twice triple quarter split out equals equal').split())


def nonmath(q):
    """Only phone/date-shaped runs veto arithmetic; two-group fractions stay math."""
    if re.search(r'[0-9]+-[0-9]+-[0-9]+', q):
        return True
    if re.search(r'(?<![0-9])[0-9]{4}/[0-9]{2}/[0-9]{2}(?![0-9])', q):
        return True
    phone = re.search(r'(?<![0-9])[0-9]{3}-[0-9]{4}(?![0-9])', q)
    words = set(re.findall(r'[a-z]+', q.lower()))
    return bool(phone and not words & OPERATOR_WORDS)


def previous(answer, apply_calc):
    m = re.fullmatch(r'calc\(([0-9.+*/%()\-]+)\) = (-?[0-9]+(?:\.[0-9]+)?)', answer or '')
    if m and apply_calc('calc(' + m[1] + ')') == answer:
        return m[1], m[2]
    return None


def expression(q, prior=None):
    if not ps.ascii_ok(q) or nonmath(q):
        return None
    # Only digit-adjacent x is split; identifiers and ordinal suffixes stay invalid.
    q = re.sub(r'(?<=\d)[xX](?=\d)', ' x ', q)
    try:
        t = ps.calc_lex(q)
        replace = False
        a = 0
        while a < len(t) and t[a][0] == 'W' and t[a][1] in LEAD:
            if t[a][1] in ('what', 'how') and t[a+1:a+2] == [('W', 'about')]:
                replace = True; a += 2; break
            a += 1
        t = t[a:]
        while t and t[-1][0] == 'W' and t[-1][1] in TAIL:
            t.pop()
        if not t or any(k == 'W' and v in BLOCK for k, v in t):
            return None
        # Rewrite exact multiword operators, not arbitrary intervening prose.
        u, i = [], 0
        while i < len(t):
            if t[i:i+2] == [('W', 'a'), ('W', 'dozen')]:
                u.append(('N', '12')); i += 2
            elif t[i] == ('W', 'dozen'):
                u.append(('N', '12')); i += 1
            elif t[i:i+2] == [('W', 'out'), ('W', 'of')]:
                u.append(('S', '/')); i += 2
            else:
                u.append(t[i]); i += 1
        t = u
        def literal(i):
            if i < len(t) and t[i] in [('W', 'it'), ('W', 'that')]:
                if not prior: raise ps.Decline
                return prior[1], i + 1
            return ps._literal(t, i)
        if replace:
            b, i = literal(0)
            m = re.fullmatch(r'(-?\d+(?:\.\d+)?)([+*/%\-])(-?\d+(?:\.\d+)?)', prior[0] if prior else '')
            return m[1] + m[2] + b if m and i == len(t) else None
        # split A [currency] between N [people] | split A N ways | A split between N
        split = t[0] == ('W', 'split')
        start = 1 if split else 0
        try:
            lhs, i = literal(start)
            if i < len(t) and t[i][0] == 'W' and t[i][1] in UNITS:
                i += 1
            if not split and t[i:i+2] == [('W', 'split'), ('W', 'between')]:
                split = True; i += 1
            if split:
                between = t[i:i+1] in [[('W', 'between')], [('W', 'among')]]
                if between: i += 1
                rhs, i = literal(i)
                end = t[i:]
                if end == [('W', 'ways')] or (between and end in [[], [('W', 'people')], [('W', 'friends')]]):
                    return '(' + lhs + ')/(' + rhs + ')'
                return None
        except ps.Decline:
            if split: return None
        # Explicit pronouns and operator-led continuations use verified prior result.
        if prior:
            if t[0][1] in ('plus', 'minus', 'times', 'x', 'over', 'divided', 'multiplied', '+', '-', '*', '/'):
                t.insert(0, ('N', prior[1]))
            elif t[0] in [('W', 'add'), ('W', 'subtract')]:
                verb = t[0][1]
                b, i = literal(1)
                if i == len(t):
                    return '(' + prior[1] + ')' + ('+' if verb == 'add' else '-') + '(' + b + ')'
            t = [('N', prior[1]) if k == 'W' and v in ('it', 'that') else (k, v) for k, v in t]
        # Preserve shared prefix binding: half of A + B is (A/2) + B.
        s = ' '.join(v for _, v in t)
        e = ps.calc_parse(s)
        if e:
            return e
        # Numeric confirmation requires a re-verified calculation in context.
        if prior and t[0][0] == 'N':
            b, i = ps._literal(t, 0)
            if i == len(t): return b
    except ps.Decline:
        pass
    return None


def answer(q, apply_calc, prev=None):
    e = expression(q, previous(prev, apply_calc))
    if not e or len(e) > 120:
        return None
    src = 'calc(' + e + ')'
    out = apply_calc(src)
    return out if out != src else None
