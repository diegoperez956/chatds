#!/usr/bin/env python3
"""Python reference for clean/plumbing/prestep.c: the c14 pre-routing steps.

  1. style     : "answer in all caps: X", "X in uppercase", "respond to me in all caps" -> strip the wrapper, answer X, transform.
  2. calc      : deterministic calc() expression from digits / number words / operator words (same fixed-point calc as calc.c).
  3. dialogue  : bounded state record + pure helpers (classifier for repeat / pushback / cancel / ordinal / style-off, pronoun
                 substitution, style expiry).  The KB-bound parts (entity resolution) stay in the host pipeline / the DS shell.
  4. neg guard : lives in textops.py (textops_guard) so it shares the textops tokenizer tables.

Every function is ASCII-only, input <= 127 bytes, declines (returns None) when unsure.  The C twin mirrors the logic line by line;
vocabulary tables are emitted to clean/plumbing/prestep_tab.h by `prestep.py --emit-h`, so only logic can drift (test_prestep.py
diffs both on generated + fuzzed input).
"""
import sys

MAXQ = 127

# ------------------------------------------------------------------ tables
STYLE_PH = [("capital letters", 1), ("block capitals", 1), ("block letters", 1), ("upper case", 1), ("uppercase", 1), ("capitals", 1),
            ("caps lock", 1), ("capslock", 1), ("caps", 1),
            ("lower case", 2), ("lowercase", 2), ("small letters", 2), ("no capitals", 2), ("no caps", 2),
            ("title case", 3), ("titlecase", 3),
            ("uppercase letters", 1), ("upper case letters", 1), ("lowercase letters", 2), ("lower case letters", 2), ("without capital letters", 2),
            ("without capitals", 2), ("without caps", 2)]
STYLE_PH.sort(key=lambda x: -len(x[0].split()))  # stable: longest phrase first
STYLE_NAME = {0: "none", 1: "upper", 2: "lower", 3: "title"}
LEADS = "hi hello hey please pls ok okay so now then can could you would will thanks thank yo and quick question btw um uh well hmm".split()
VERBS_S = "answer reply respond say speak talk write type use switch go be".split()
MODS = ["to me", "to you", "me", "back", "only", "always", "just"]
PREPS = ["in", "using", "with", "into", "as", "to"]
TRAIL = ["only", "please", "pls", "always", "thanks", "thx", "from now on", "from here on", "now", "for me", "for now", "ok", "okay",
         "when you talk to me", "when you talk", "when you answer", "when you reply", "when you respond", "when you speak", "when you write"]
LEAD_PH = ["from now on", "from here on", "for now", "always", "only", "just"]
SUFF_PREPS = ["in", "using", "into", "with"]
SUFF_TRAIL = ["please", "pls", "thanks", "thx", "only", "answer", "reply"]
LIT_VERBS = ["say", "write", "type", "print", "shout", "yell", "give me"]
SHOUT_VERBS = ["shout", "yell", "scream"]
LIT_BAD = "it that this something anything everything them one".split()
FREE_OK = "from now on here always please pls thanks thx for me now on okay ok and nothing else just".split()

CALC_FILL = ("hi hello hey thanks thank you ok okay so now please pls what whats is calculate calc compute solve evaluate work out how much does do "
             "equal equals the result answer tell me can could give find i need want to know let lets quick just then good morning afternoon evening "
             "yo").split()
CALC_TAIL = "equal equals please pls thanks thx".split()
UNITS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
         "nineteen").split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
PREFIX_OPS = {"half": "/2", "double": "*2", "twice": "*2", "triple": "*3", "quarter": "/4"}
INFIX_W = {"plus": "+", "minus": "-", "times": "*", "x": "*", "over": "/", "mod": "%", "modulo": "%", "less": "-"}
CALC_OTHER = ("and of by from to away take taken divided multiplied multiply divide add subtract sum product percent pct squared cubed square cube "
              "remainder when point negative hundred thousand with").split()
CODEW = ("python py code coding function def script program bash shell java javascript js sql regex loop variable array list dict string "
         "return print echo import class lambda numpy pandas snippet").split()
REPAIR = sorted(set(UNITS + TENS + list(PREFIX_OPS) + ["plus", "minus", "times", "divided", "multiplied", "multiply", "divide", "modulo", "subtract",
                    "squared", "percent", "away", "take", "less", "over", "mod", "add", "sum", "product", "hundred", "thousand", "point",
                    "calculate", "compute", "whats", "what", "negative", "equals"]))
CALC_KNOWN = sorted(set(CALC_FILL) | set(CALC_TAIL) | set(UNITS) | set(TENS) | set(PREFIX_OPS) | set(INFIX_W) | set(CALC_OTHER) | set(REPAIR))

DLG_REPEAT = ["say that again", "repeat that", "what was that", "come again", "pardon", "sorry what", "huh", "can you repeat that", "can you repeat",
              "repeat", "repeat it", "again", "once more", "one more time", "say it again", "what did you say", "say again", "repeat please",
              "could you repeat that", "say that one more time", "what", "what did you just say", "what did you say", "what did you say just now",
              "can you say that again", "could you say that again", "what was that again", "can you repeat that again", "sorry could you repeat that"]
DLG_PUSH = ["thats wrong", "that is wrong", "thats not right", "that is not right", "thats incorrect", "that is incorrect", "wrong", "are you sure",
            "you sure", "i dont think so", "i do not think so", "that doesnt sound right", "thats not true", "that is not true", "thats not correct",
            "that is not correct", "try again", "check again", "double check", "recheck", "you are wrong", "youre wrong", "that cant be right",
            "i think you made a mistake", "you made a mistake", "you are mistaken", "youre mistaken", "that doesnt sound correct", "that doesnt sound right",
            "that does not sound correct", "that does not sound right", "that sounds wrong", "that isnt right", "that isnt correct", "i think thats wrong",
            "i think that is wrong", "no that is wrong", "no thats wrong", "no thats not right", "not right", "not correct", "incorrect", "i dont think thats right", "are you certain", "is that right",
            "is that correct", "really", "nope", "thats not what i heard"]
DLG_CANCEL = ["never mind", "nevermind", "cancel", "forget it", "scratch that", "start over", "reset", "clear", "new topic", "lets start over",
              "forget that", "ignore that", "disregard that", "stop"]
DLG_STYLE_OFF = ["stop shouting", "stop using caps", "stop the caps", "normal case", "back to normal", "normal text", "no more caps", "dont shout",
                 "stop using uppercase", "stop using lowercase", "normal mode", "talk normally", "talk normal", "stop using title case", "normal again"]
DLG_ORD1 = ["the first one", "first one", "the first", "the former", "former", "1st one", "the first option"]
DLG_ORD2 = ["the other one", "other one", "the other", "another one", "the second one", "second one", "the second", "the latter", "latter",
            "2nd one", "the other option", "the second option", "and the other meaning", "the other meaning", "other meaning", "another meaning",
            "the other meaning please"]
DLG_PRON = "he she him her his hers it its they them their there".split()
DLG_FILL = "no sorry i mean meant please um uh yeah yes ok okay just".split()
DLG_FILL2 = ["what about", "how about"]
ENT_STOP = None  # filled from retrieve4 by the host (emit_h imports it)

NOANS = "i haven't said anything yet. what do you want to ask?"
ASK_SAY = "ok. what should i say?"
STYLE_TTL = 8        # a style preference applies to the next 8 answers, then expires
D_ANS, D_Q, D_ENT, D_TERM = 200, 127, 47, 23  # state field caps (bytes, excluding NUL)


# ------------------------------------------------------------------ word tokenizer
def ascii_ok(q):
    return bool(q) and len(q) <= MAXQ and all(0x20 <= ord(c) <= 0x7e for c in q)


def wtoks(q):
    """[(word, start, end)] runs of [a-z0-9'] lowercased, plus ':' tokens; everything else separates."""
    T, i, n = [], 0, len(q)
    while i < n:
        c = q[i]
        if c.isalnum() or c == "'":
            j = i
            while j < n and (q[j].isalnum() or q[j] == "'"):
                j += 1
            T.append((q[i:j].lower(), i, j))
            i = j
        else:
            if c == ":":
                T.append((":", i, i + 1))
            i += 1
    return T


def match_ph(T, i, ph):
    """token count if phrase ph (space-joined words) matches T at i, else 0"""
    ws = ph.split()
    if i + len(ws) > len(T):
        return 0
    for k, w in enumerate(ws):
        if T[i + k][0] != w:
            return 0
    return len(ws)


def match_any(T, i, phs):
    best = 0
    for p in phs:
        k = match_ph(T, i, p)
        if k > best:
            best = k
    return best


def match_style(T, i):
    for p, s in STYLE_PH:
        k = match_ph(T, i, p)
        if k:
            return s, k
    return 0, 0


# ------------------------------------------------------------------ 1. style
def apply_style(style, text):
    """ASCII-only transform; title follows Python str.title() (letter after a non-letter is upper, others lower)."""
    o, prev = [], False
    for ch in text:
        a = ("a" <= ch <= "z") or ("A" <= ch <= "Z")
        if style == 1:
            o.append(ch.upper() if a else ch)
        elif style == 2:
            o.append(ch.lower() if a else ch)
        elif style == 3:
            o.append((ch.lower() if prev else ch.upper()) if a else ch)
        else:
            o.append(ch)
        prev = a
    return "".join(o)


def _strip_tail(s):
    return s.rstrip(" ,;:-(")


def _lit(s):
    """literal text of "say X in caps": tails stripped, one pair of quotes removed; "" when it is a pronoun-ish placeholder"""
    lit = _strip_tail(s.strip(" ")).strip(" ")
    if len(lit) >= 3 and lit[0] in "\"'`" and lit[-1] == lit[0]:
        lit = lit[1:-1].strip(" ")
    return "" if not lit or lit.lower() in LIT_BAD else lit


def style_detect(q):
    """-> None | (kind, style, inner).  kind: 'wrap' (verb-led prefix: inner goes through the normal pipeline), 'prefix' (verbless
    "all caps: X" / "in caps please, X"; textops gets the whole request first), 'suffix' ("X in all caps", "X (reply in all caps)";
    textops first), 'literal' ("say X in caps", "shout X": X is the answer), 'free' (no content: ask what to say; inner is "")."""
    if not ascii_ok(q):
        return None
    q = q.strip(" ")
    T = wtoks(q)
    n = len(T)
    if n < 2:
        return None
    i = 0
    while i < n and T[i][0] in LEADS:
        i += 1
    if i < n and T[i][0] in SHOUT_VERBS:
        lit = _lit(q[T[i][2]:])
        return ("literal", 1, lit) if lit else None
    # ---- prefix
    j = i
    while True:
        k = match_any(T, j, LEAD_PH)
        if not k:
            break
        j += k
    verb = False
    if j < n and T[j][0] in VERBS_S:
        verb = True
        j += 1
        while True:
            k = match_any(T, j, MODS)
            if not k:
                break
            j += k
    if j < n and T[j][0] in PREPS:
        j += 1
    while j < n and T[j][0] in ("all", "only", "just", "entirely", "completely"):
        j += 1
    st, k = match_style(T, j)
    if k:
        j += k
        while True:
            k = match_any(T, j, TRAIL)
            if not k:
                break
            j += k
        delim = False
        if j < n and T[j][0] == ":":
            delim, j = True, j + 1
        elif j < n and "," in q[T[j - 1][2]:T[j][1]]:
            delim = True
        if verb or delim:
            rest = q[T[j][1]:] if j < n else ""
            words = [t[0] for t in T[j:]]
            if all(w in FREE_OK for w in words):
                return ("free", st, "")
            inner = _strip_tail(rest.strip(" ")).strip(" ")
            if not inner:
                return None
            return ("wrap" if verb else "prefix", st, inner)
    # ---- suffix
    e = n
    while e > 1 and T[e - 1][0] in SUFF_TRAIL:
        e -= 1
    litk = match_any(T, i, LIT_VERBS)
    for p, s in STYLE_PH:
        k = len(p.split())
        b = e - k
        if b < 1 or match_ph(T, b, p) != k:
            continue
        has_all = T[b - 1][0] == "all"
        if has_all:
            b -= 1
        pre = None
        if b >= 1 and T[b - 1][0] in SUFF_PREPS and i < b - 1:
            t = b - 1
            if t - 1 > i and T[t - 1][0] in VERBS_S and q[:T[t - 1][1]].rstrip(" ").endswith("("):
                t -= 1  # "(reply in all caps)"
            pre = T[t][1]
        else:
            h = q[:T[b][1]].rstrip(" ")
            if h.endswith("(") and b > i:  # "(lowercase answer please)"
                pre = len(h) - 1
            elif has_all and litk and b > i:  # "give me X all lowercase"
                pre = T[b][1]
        if pre is None:
            continue
        inner = _strip_tail(q[T[i][1]:pre].rstrip(" ")).strip(" ")
        if not inner:
            return None
        if litk:
            lit = _lit(q[T[i + litk - 1][2]:pre])
            return ("literal", s, lit) if lit else None
        return ("suffix", s, inner)
    return None


# ------------------------------------------------------------------ 2. calc
class Decline(Exception):
    pass


def edit1(a, b):
    la, lb = len(a), len(b)
    if abs(la - lb) > 1 or a == b:
        return False
    i = 0
    while i < la and i < lb and a[i] == b[i]:
        i += 1
    if la == lb:
        if a[i + 1:] == b[i + 1:]:
            return True
        return i + 1 < la and a[i] == b[i + 1] and a[i + 1] == b[i] and a[i + 2:] == b[i + 2:]
    if la < lb:
        return a[i:] == b[i + 1:]
    return a[i + 1:] == b[i:]


def nocommas(q):
    """drop thousands separators: a comma after a digit, followed by exactly 3 digits and no 4th digit"""
    o, n = [], len(q)
    for i, c in enumerate(q):
        if c == "," and i > 0 and q[i - 1].isdigit() and q[i + 1:i + 4].isdigit() and len(q[i + 1:i + 4]) == 3 \
                and not (i + 4 < n and q[i + 4].isdigit()):
            continue
        o.append(c)
    return "".join(o)


def calc_lex(q):
    """-> [(kind, text)] kind N (number), W (word), S (symbol) or raises Decline."""
    if not ascii_ok(q):
        raise Decline
    q = nocommas(q)
    T, i, n = [], 0, len(q)
    while i < n:
        c = q[i]
        if c.isdigit() or (c == "." and i + 1 < n and q[i + 1].isdigit()):
            j = i
            while j < n and q[j].isdigit():
                j += 1
            if j < n and q[j] == "." and j + 1 < n and q[j + 1].isdigit():
                j += 1
                while j < n and q[j].isdigit():
                    j += 1
            if j < n and (q[j].isalpha() or q[j] == "'"):
                raise Decline  # glued 5x / 20th
            T.append(("N", q[i:j]))
            i = j
        elif c.isalpha() or c == "'":
            j, s = i, ""
            while j < n and (q[j].isalpha() or q[j] == "'"):
                if q[j] != "'":
                    s += q[j].lower()
                j += 1
            if j < n and q[j].isdigit():
                raise Decline
            if s:
                T.append(("W", s))
            i = j
        elif c in "+*/%()^=":
            T.append(("S", c))
            i += 1
        elif c == "-":
            if i > 0 and i + 1 < n and q[i - 1].isalpha() and q[i + 1].isalpha():
                i += 1  # twenty-three
            else:
                T.append(("S", "-"))
                i += 1
        elif c in " ,?!;:\"`.":
            i += 1
        else:
            raise Decline  # $ # & < > _ [ ] { } | \\ @ ~
        if len(T) > 64:
            raise Decline
    return T


def _numword_run(T, i):
    """number words at T[i:] -> (text, next index) or Decline.  Grammar: [g thousand] [g] with g < 1000, optional 'point' + digit words."""
    n = len(T)
    r, j = [], i
    while j < n and T[j][0] == "W":
        w = T[j][1]
        if w in UNITS or w in TENS or w in ("hundred", "thousand"):
            r.append(w)
            j += 1
        elif w == "and" and r and r[-1] in ("hundred", "thousand") and j + 1 < n and T[j + 1][0] == "W" and \
                (T[j + 1][1] in UNITS or T[j + 1][1] in TENS):
            r.append(w)
            j += 1
        else:
            break
    if not r:
        raise Decline
    pos = [0]

    def grp():
        k, val, got = pos[0], 0, False
        if k + 1 < len(r) and r[k] in UNITS[1:10] and r[k + 1] == "hundred":
            val, k, got = UNITS.index(r[k]) * 100, k + 2, True
        elif k < len(r) and r[k] == "hundred":
            val, k, got = 100, k + 1, True
        if got and k + 1 < len(r) and r[k] == "and":
            k += 1
        if k < len(r) and r[k] in TENS:
            val, k, got = val + 20 + 10 * TENS.index(r[k]), k + 1, True
            if k < len(r) and r[k] in UNITS[1:10]:
                val, k = val + UNITS.index(r[k]), k + 1
        elif k < len(r) and r[k] in UNITS and (r[k] != "zero" or len(r) == 1):
            val, k, got = val + UNITS.index(r[k]), k + 1, True
        if not got:
            return None
        pos[0] = k
        return val

    total = 0
    if r == ["zero"]:
        pos[0] = 1
    else:
        if r[0] == "thousand":
            total, pos[0] = 1000, 1
        else:
            a = grp()
            if a is None:
                raise Decline
            if pos[0] < len(r) and r[pos[0]] == "thousand":
                total, pos[0] = a * 1000, pos[0] + 1
                if pos[0] < len(r) and r[pos[0]] == "and":
                    pos[0] += 1
                if pos[0] < len(r):
                    b = grp()
                    if b is None:
                        raise Decline
                    total += b
            else:
                total = a
        if pos[0] != len(r):
            raise Decline
    s = str(total)
    if j < n and T[j] == ("W", "point"):
        d, k = "", j + 1
        while k < n and T[k][0] == "W" and T[k][1] in UNITS[:10]:
            d += str(UNITS.index(T[k][1]))
            k += 1
        if not d:
            raise Decline
        s, j = s + "." + d, k
    return s, j


def _literal(T, i):
    if i < len(T) and T[i][0] == "N":
        return T[i][1], i + 1
    if i < len(T) and T[i][0] == "W" and (T[i][1] in UNITS or T[i][1] in TENS or T[i][1] in ("hundred", "thousand")):
        return _numword_run(T, i)
    raise Decline


def _repair(T):
    out = []
    for k, t in enumerate(T):
        if t[0] == "W" and t[1] not in CALC_KNOWN and len(t[1]) >= 3 and len(t[1]) <= 15:
            c = [r for r in REPAIR if edit1(t[1], r)]
            if len(c) > 1:
                raise Decline
            if c:
                t = ("W", c[0])
        out.append(t)
    return out


def _head_form(T):
    """verb-led two-operand forms: add A and B | sum of A and B | product of A and B | multiply A by B | divide A by B | subtract A from B"""
    w = T[0][1] if T and T[0][0] == "W" else ""
    if w not in ("add", "sum", "product", "multiply", "divide", "subtract", "remainder"):
        return None
    i = 1
    if w == "remainder":  # remainder when A is divided by B | remainder of A divided by B | remainder of A by B
        if i < len(T) and T[i][0] == "W" and T[i][1] in ("when", "of"):
            i += 1
        a, i = _literal(T, i)
        if i < len(T) and T[i] == ("W", "is"):
            i += 1
        if i < len(T) and T[i] == ("W", "divided"):
            i += 1
        if not (i < len(T) and T[i] == ("W", "by")):
            raise Decline
        b, i = _literal(T, i + 1)
        if i != len(T):
            raise Decline
        return "%s%%%s" % (a, b)
    if w in ("sum", "product"):
        if i >= len(T) or T[i] != ("W", "of"):
            raise Decline
        i += 1
    a, i = _literal(T, i)
    conn = {"add": ("and", "to", "plus"), "sum": ("and",), "product": ("and", "times"), "multiply": ("by", "and", "with", "times"),
            "divide": ("by",), "subtract": ("from",)}[w]
    if i >= len(T) or T[i][0] != "W" or T[i][1] not in conn:
        raise Decline
    b, i = _literal(T, i + 1)
    if i != len(T):
        raise Decline
    op = {"add": "+", "sum": "+", "product": "*", "multiply": "*", "divide": "/", "subtract": "-"}[w]
    return "%s%s%s" % ((b, op, a) if w == "subtract" else (a, op, b))


def calc_parse(q):
    """-> expression string for calc() or None.  Full-match only: any unknown word, symbol or ambiguity declines."""
    try:
        T = _repair(calc_lex(q))
        if any(t[0] == "W" and t[1] in CODEW for t in T):
            return None
        a, e = 0, len(T)
        while a < e and T[a][0] == "W" and T[a][1] in CALC_FILL:
            a += 1
        while e > a and ((T[e - 1][0] == "W" and T[e - 1][1] in CALC_TAIL) or T[e - 1] == ("S", "=")):
            e -= 1
        T = T[a:e]
        if not T:
            return None
        h = _head_form(T)
        if h:
            return h
        out, last_num, depth, ops, operand, i, n = [], -1, 0, 0, True, 0, len(T)
        while i < n:
            k, v = T[i]
            if operand:
                if (k, v) == ("S", "("):
                    out.append("("); depth += 1; i += 1; last_num = -1
                elif k == "S" and v in "+-":
                    out.append(v); i += 1
                elif k == "W" and v in ("minus", "negative"):
                    out.append("-"); i += 1
                elif k == "W" and v in ("square", "cube"):
                    if i + 1 >= n or T[i + 1] != ("W", "of"):
                        raise Decline
                    num, i = _literal(T, i + 2)
                    out.append("(%s)" % "*".join([num] * (2 if v == "square" else 3))); ops += 1; operand = False; last_num = -1
                elif k == "W" and v in PREFIX_OPS:
                    i += 1
                    if i < n and T[i] == ("W", "of"):
                        i += 1
                    num, i = _literal(T, i)
                    out.append("(%s%s)" % (num, PREFIX_OPS[v])); ops += 1; operand = False; last_num = -1
                else:
                    num, i = _literal(T, i)
                    out.append(num); last_num = len(out) - 1; operand = False
            else:
                if (k, v) == ("S", ")"):
                    if depth == 0:
                        raise Decline
                    out.append(")"); depth -= 1; i += 1; last_num = -1
                elif k == "S" and v in "+-*/":
                    out.append(v); ops += 1; operand = True; i += 1
                elif k == "S" and v == "%" or (k == "W" and v in ("percent", "pct")):
                    if i + 1 < n and T[i + 1] == ("W", "of"):
                        if last_num < 0:
                            raise Decline
                        num, i = _literal(T, i + 2)
                        out[last_num] = "(%s*%s/100)" % (out[last_num], num); ops += 1; last_num = -1
                    elif k == "S":
                        out.append("%"); ops += 1; operand = True; i += 1
                    else:
                        raise Decline
                elif k == "W" and v in ("squared", "cubed"):
                    if last_num < 0:
                        raise Decline
                    out[last_num] = "(%s)" % "*".join([out[last_num]] * (2 if v == "squared" else 3)); ops += 1; last_num = -1; i += 1
                elif k == "W" and v in INFIX_W:
                    out.append(INFIX_W[v]); ops += 1; operand = True; i += 1
                elif k == "W" and v in ("divided", "multiplied"):
                    if i + 1 >= n or T[i + 1] != ("W", "by"):
                        raise Decline
                    out.append("/" if v == "divided" else "*"); ops += 1; operand = True; i += 2
                elif k == "W" and v in ("take", "taken") and i + 1 < n and T[i + 1] == ("W", "away"):
                    out.append("-"); ops += 1; operand = True; i += 2
                else:
                    raise Decline
        if operand or depth or not ops:
            return None
        e = "".join(out)
        return e if len(e) <= 300 else None
    except Decline:
        return None


def calc_answer(q, apply_calc):
    """'calc(expr) = value' via the shared fixed-point evaluator, or None.  apply_calc: chatds_runtime.apply_calc."""
    e = calc_parse(q)
    if e is None:
        return None
    s = "calc(%s)" % e
    r = apply_calc(s)
    return None if r == s else r


# ------------------------------------------------------------------ 3. dialogue state
def dlg_new():
    return dict(entity="", answer="", lastq="", term="", cand=[0, 0], ncand=0, pend=0, task=0, style=0, ttl=0)


TASK = dict(none=0, facts=1, calc=2, text=3, conv=4, other=5)


def dlg_reset(st):
    st.clear()
    st.update(dlg_new())


def _contig(T, p):
    ws = p.split()
    return any(T[i:i + len(ws)] == ws for i in range(len(T) - len(ws) + 1))


def dlg_kind(q):
    """classify a follow-up utterance: 0 none, 1 repeat, 2 pushback, 3 cancel, 4 style-off, 5 first, 6 other/second.
    Whole-utterance (after filler) for one-word phrases, contiguous for longer ones; > 10 words is never a follow-up cue."""
    if not ascii_ok(q):
        return 0
    T = [t[0].replace("'", "") for t in wtoks(q) if t[0] != ":"]
    T = [t for t in T if t]
    while T and (T[0] in DLG_FILL + ["hey", "hi", "uh", "um"] or T[:2] in [f.split() for f in DLG_FILL2]):
        T = T[2:] if T[:2] in [f.split() for f in DLG_FILL2] else T[1:]
    while T and T[-1] in ("please", "pls", "thanks"):
        T = T[:-1]
    n = len(T)
    if not n or n > 10:
        return 0

    def has(L):
        return any((len(p.split()) > 1 and _contig(T, p)) or T == p.split() for p in L)
    if has(DLG_STYLE_OFF):
        return 4
    if any(T == p.split() for p in DLG_CANCEL):
        return 3
    if has(DLG_PUSH):
        return 2
    if any(T == p.split() for p in DLG_REPEAT):
        return 1
    if any(T == p.split() for p in DLG_ORD1):
        return 5
    if any(T == p.split() for p in DLG_ORD2):
        return 6
    return 0


def dlg_subst_pronoun(q, entity, ent_stop):
    """'when was he born' + entity -> 'when was <entity> born' when the question has a pronoun and no entity words of its own."""
    if not entity or not ascii_ok(q):
        return None
    T = [t for t in wtoks(q) if t[0] != ":"]
    has_p = False
    for w, s, e in T:
        if w in DLG_PRON:
            has_p = True
        elif w not in ent_stop:
            return None
    if not has_p:
        return None
    o, last = [], 0
    for w, s, e in T:
        if w in DLG_PRON:
            o.append(q[last:s])
            o.append(entity)
            last = e
    o.append(q[last:])
    r = "".join(o).strip(" ")
    return r if len(r) <= MAXQ else None


def dlg_note(st, task, entity, answer, lastq, ok, keep_answer=True):
    """after a turn.  ok=0 (error / cancel) resets everything, style included."""
    if not ok:
        dlg_reset(st)
        return
    st["task"] = task
    if task == TASK["facts"]:
        if entity:
            st["entity"] = entity[:D_ENT]
    elif task in (TASK["calc"], TASK["text"], TASK["other"]):
        st["entity"], st["ncand"], st["cand"] = "", 0, [0, 0]  # topic switch
    if keep_answer:
        st["answer"] = answer[:D_ANS]
        st["lastq"] = lastq[:D_Q]


def dlg_set_style(st, style):
    st["style"], st["ttl"] = style, (STYLE_TTL if style else 0)


def dlg_style_take(st):
    """style to apply to this answer (0 none); each use spends one unit of the ttl, 0 left clears the preference."""
    s = st.get("style", 0)
    if s and st["ttl"] > 0:
        st["ttl"] -= 1
        if st["ttl"] == 0:
            st["style"] = 0
        return s
    st["style"] = 0
    return 0


def dlg_bytes():
    return 0  # the C sizeof is reported by test_prestep.c


# ------------------------------------------------------------------ 4. textops negative guard
NEG_HEAD = ["how do", "how can", "how to", "how would", "how should", "how does", "how did", "how come", "why", "who", "when", "where", "which",
            "does", "did", "is it", "is there", "are there", "what is the best", "whats the best", "best way", "whats the difference",
            "what is the difference"]
NEG_ANY = ["vs", "versus", "difference between", "differences between", "the difference", "difference in", "different from", "compare",
           "compared to", "comparison", "explain", "explains", "explanation", "tutorial", "tutorials", "example of", "examples of", "rules for",
           "rules of", "history of", "origin of", "origins of", "stand for", "stands for", "capitalize on", "capitalise on", "count on",
           "counting on", "reverse engineer", "reverse engineering", "reverse psychology", "reverse course", "reverse mortgage", "reverse gear",
           "reverse osmosis", "reverse lookup", "reverse proxy", "title of", "title page", "titles of", "upper hand", "upper body",
           "upper class", "upper limit", "upper bound", "lower back", "lower the", "lower price", "lower prices", "lower limit",
           "lower bound", "lower class", "uppercase or lowercase", "lowercase or uppercase", "upper or lower", "lower or upper",
           "uppercase and lowercase", "lowercase and uppercase", "upper and lower", "tell me about", "tell me more about", "what is a",
           "what is an", "whats a", "whats an", "what does", "what do", "what did", "what are the rules", "what are the benefits",
           "does it matter", "good practice", "best practice", "best practices", "is it ok", "is it okay", "is it rude", "is it bad",
           "is it better", "which is better", "better than", "should i", "should we", "meaning of", "definition of", "define"]


def _unquote(q):
    """blank quoted spans ("...", `...`, '...' opened at a word start and closed before a space/punctuation)"""
    n, o, i = len(q), list(q), 0
    while i < n:
        c = q[i]
        if c in "\"`'" and (i == 0 or q[i - 1] == " "):
            for k in range(i + 1, n):
                if q[k] == c and (k + 1 == n or q[k + 1] in " ,.;:!?)"):
                    if k > i + 1:
                        for m in range(i, k + 1):
                            o[m] = " "
                        i = k
                    break
        i += 1
    return "".join(o)


def textops_guard(q):
    """True when q looks like a question ABOUT a text operation (or a look-alike), not a request to run one."""
    if not ascii_ok(q):
        return False
    W = [t[0] for t in wtoks(_unquote(q)) if t[0] != ":"]
    i = 0
    while i < len(W) and W[i] in LEADS:
        i += 1
    for p in NEG_HEAD:
        ws = p.split()
        if W[i:i + len(ws)] == ws:
            return True
    return any(_contig(W, p) for p in NEG_ANY)


# ------------------------------------------------------------------ header emitter / CLI
def emit_h():
    def cs(s): return '"%s"' % s
    def arr(name, L): return "static const char *const PS_%s[] = {%s, 0};" % (name, ", ".join(cs(x) for x in L))
    o = ["/* GENERATED by campaign/pipeline/prestep.py --emit-h; do not edit. */"]
    o.append("static const struct { const char *p; int style; } PS_STYLE[] = {%s, {0, 0}};" % ", ".join("{%s, %d}" % (cs(p), s) for p, s in STYLE_PH))
    for nm, L in (("LEADS", LEADS), ("VERBS_S", VERBS_S), ("MODS", MODS), ("PREPS", PREPS), ("TRAIL", TRAIL), ("SUFF_PREPS", SUFF_PREPS), ("LEAD_PH", LEAD_PH), ("SHOUT_VERBS", SHOUT_VERBS),
                  ("SUFF_TRAIL", SUFF_TRAIL), ("LIT_VERBS", LIT_VERBS), ("LIT_BAD", LIT_BAD), ("FREE_OK", FREE_OK), ("CALC_FILL", CALC_FILL),
                  ("CALC_TAIL", CALC_TAIL), ("UNITS", UNITS), ("TENS", TENS), ("CODEW", CODEW), ("REPAIR", REPAIR), ("CALC_KNOWN", CALC_KNOWN),
                  ("DLG_REPEAT", DLG_REPEAT), ("DLG_PUSH", DLG_PUSH), ("DLG_CANCEL", DLG_CANCEL), ("DLG_STYLE_OFF", DLG_STYLE_OFF),
                  ("DLG_ORD1", DLG_ORD1), ("DLG_ORD2", DLG_ORD2), ("NEG_HEAD", NEG_HEAD), ("NEG_ANY", NEG_ANY), ("DLG_PRON", DLG_PRON), ("DLG_FILL", DLG_FILL + ["hey", "hi", "uh", "um"]), ("DLG_FILL2", DLG_FILL2)):
        o.append(arr(nm, L))
    o.append("static const struct { const char *w; const char *s; } PS_PREFIX[] = {%s, {0, 0}};" % ", ".join("{%s, %s}" % (cs(k), cs(v)) for k, v in PREFIX_OPS.items()))
    o.append("static const struct { const char *w; char c; } PS_INFIX[] = {%s, {0, 0}};" % ", ".join("{%s, '%s'}" % (cs(k), v) for k, v in INFIX_W.items()))
    sys.path[:0] = [str(__import__("pathlib").Path(__file__).resolve().parents[2] / "corpus/kb")]
    import retrieve4 as r4
    o.append(arr("ENT_STOP", sorted(r4.ENT_STOP)))
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    if "--emit-h" in sys.argv:
        sys.stdout.write(emit_h())
