#!/usr/bin/env python3
"""Python reference for clean/plumbing/textops.c: deterministic text operations.

textops(q) -> (op, output) or None (= NOT_TEXT_OP, caller falls back). Every rule here is mirrored line by line in the C
file; the phrase tables are emitted to clean/plumbing/textops_tab.h by `textops.py --emit-h`, so the two cannot drift
on vocabulary, only on logic (test_textops.py diffs them on generated requests).

Principle: decline when unsure. Rules that decline: more than one reading, article/pronoun/wh-word arguments, code and
file context, a bare noun as the argument, "the ..." arguments for ops where the noun phrase is probably a topic.
Output is plain: the transformed text, or "N units", or yes/no. Never truncates: output over 255 bytes declines.
"""
import sys

MAXQ, MAXOUT, MAXTOK = 127, 255, 64
OPS = ["upper", "lower", "title", "capitalize", "reverse", "reverse_words", "count_letters", "count_chars", "count_chars_nospace",
       "count_words", "count_vowels", "remove_spaces", "repeat", "replace", "initials", "acronym", "sort_words", "first_word",
       "last_word", "palindrome", "spell"]
OPID = {o: i for i, o in enumerate(OPS)}
NO_THE = {"reverse", "reverse_words", "sort_words", "first_word", "last_word", "initials", "acronym", "count_letters", "count_chars",
          "count_chars_nospace", "count_words", "count_vowels"}  # "the X": X is probably a topic, not text

# ------------------------------------------------------------------ vocabulary tables
FILLER_SOFT = "hi hello hey hiya yo good morning afternoon evening thanks thank you please pls plz can could would will now ok okay so then just also and i want need wanna to me let lets us tell give show get take find chatds".split()
FILLER_Q = ["what", "whats", "is", "are"]
WRAP = "make convert turn change write put set transform render rewrite print show give type format say spell read sort order arrange".split()
REPL = {"replace": ["with", "by"], "change": ["to", "into"], "swap": ["for", "with"]}
REPEATV = ["repeat", "say", "write"]
VERBS = ("reverse flip uppercase lowercase capitalize capitalise count sort alphabetize alphabetise remove delete strip repeat replace swap spell convert make "
         "turn change write put show how what whats is are tell check acronym initials abbreviate title say").split()
DECL1 = ("a an my your our some any each every all it its them that those these something anything everything check checker correctly "
         "what whats who when where why how which is are do does did can could should would will").split()
BLOCK = ("python py java javascript js code coding function functions script scripts program programs programming file files folder folders "
         "directory directories linux bash shell terminal command commands sql regex array arrays list lists variable variables dictionary "
         "alphabet english spanish french german language languages book books bible wikipedia website page pages paragraph paragraphs essay "
         "document pdf csv json email data stack queue tree dict vector matrix table rows columns items elements values keys nums").split()
NOUNS = "text string word words sentence phrase letter letters character characters paragraph number numbers".split()
STOPW = "of the and a an for in on to".split()
CONN = [":", "of", "in", "from", "on"]
NOISE = ["the following text", "the following string", "the following", "this text", "this string", "this word", "this phrase",
         "this sentence", "the text", "the string", "the word", "the phrase", "the sentence", "the words in", "the words of", "words in",
         "words of", "the letters in", "the letters of", "letters in", "letters of", "the characters in", "the characters of",
         "the chars in", "this"]
RNOISE = ["all the", "every single", "all of the", "the letter", "the letters", "the character", "the char", "the word", "the string",
          "the text", "the substring", "all letters", "every", "all", "each", "the", "letter", "character", "char", "word"]
TYPO_KW = ("uppercase lowercase capitalize capitalise backwards reverse replace alphabetically characters remove repeat letters "
           "palindrome acronym initials alphabetize convert").split()
PAL_HEADS = ["check whether", "check if", "test if", "see if", "whether", "is", "if", "palindrome check", "palindrome test"]
PAL_TAILS = ["is a palindrome", "is palindrome", "a palindrome", "an palindrome", "palindrome", "palindromic"]
NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
SORT_MODS = ["alphabetically", "in alphabetical order", "in alphabetic order"]
CHARS_MODS = [("without spaces", 1), ("without the spaces", 1), ("excluding spaces", 1), ("excluding the spaces", 1), ("ignoring spaces", 1),
              ("not counting spaces", 1), ("not counting the spaces", 1), ("with no spaces", 1), ("with spaces", 0), ("including spaces", 0),
              ("including the spaces", 0), ("counting spaces", 0)]


def _build():
    H, T = [], []  # H: (phrase, op); T: (phrase, op, bare)
    units = {"words": "count_words", "word": "count_words", "letters": "count_letters", "letter": "count_letters",
             "vowels": "count_vowels", "vowel": "count_vowels", "characters": "count_chars", "character": "count_chars",
             "chars": "count_chars", "char": "count_chars"}
    for u, op in units.items():
        for p in ("how many %s in", "how many %s are in", "how many %s are there in", "how many %s is in", "count the %s in", "count %s in",
                  "count the %s of", "count the number of %s in", "number of %s in", "the number of %s in", "%s count of", "%s count in",
                  "%s count"):
            H.append((p % u, op))
        if u in ("words", "letters", "vowels", "characters"):
            H.append(("%s in" % u, op))
    for t in ("text", "string", "word", "phrase", "sentence"):
        for p in ("length of the %s", "the length of the %s", "length of this %s", "how long is the %s"):
            H.append((p % t, "count_chars"))
    for v in ("reverse", "flip"):
        H.append((v, "reverse"))
        for p in ("the words in", "the words of", "words in", "words of", "the word order of", "the word order in", "word order of",
                  "word order in", "the order of the words in", "the order of the words of", "the order of words in", "the order of words of"):
            H.append((v + " " + p, "reverse_words"))
    H += [("capitalize", "capitalize"), ("capitalise", "capitalize"), ("capitalize the first letter of", "capitalize"),
          ("capitalize first letter of", "capitalize"), ("capitalise the first letter of", "capitalize")]
    for v in ("capitalize", "capitalise"):
        for q in ("each", "every"):
            for p in ("of", "in"):
                H.append(("%s %s word %s" % (v, q, p), "title"))
    H += [("uppercase", "upper"), ("upper case", "upper"), ("all caps", "upper"), ("lowercase", "lower"), ("lower case", "lower"),
          ("all lowercase", "lower"), ("all lower case", "lower"), ("title case", "title"), ("titlecase", "title")]
    for v in ("remove", "delete", "strip", "eliminate"):
        for q in ("", "all", "the", "all the"):
            for o in ("spaces", "whitespace"):
                for p in ("from", "in", "of"):
                    H.append((" ".join(x for x in (v, q, o, p) if x), "remove_spaces"))
    for q in ("", "the", "all the", "all"):
        for p in ("in", "from"):
            H.append((" ".join(x for x in ("get rid of", q, "spaces", p) if x), "remove_spaces"))
    for p in ("initials of", "initials for", "initials in", "the initials of", "the initials for"):
        H.append((p, "initials"))
    for fl in ("first letter", "first letters"):
        for sq in ("each word", "every word", "each of the words", "the words", "all the words", "all words"):
            for pre in ("", "the "):
                H.append(("%s%s of %s" % (pre, fl, sq), "initials"))
                for p in ("in", "of", "from"):
                    H.append(("%s%s of %s %s" % (pre, fl, sq, p), "initials"))
    for v in ("", "make", "create", "form", "build", "generate"):
        for d in ("", "an", "the"):
            for p in ("of", "for", "from", "out of"):
                H.append((" ".join(x for x in (v, d, "acronym", p) if x), "acronym"))
    H.append(("abbreviate", "acronym"))
    for p in ("sort the words", "sort words", "sort the words in", "sort the words of", "sort words in", "sort words of"):
        H.append((p, "sort_words"))
    H += [("alphabetize", "sort_words"), ("alphabetise", "sort_words"), ("alphabetize the words in", "sort_words"),
          ("alphabetize the words of", "sort_words")]
    for w, op in (("first", "first_word"), ("last", "last_word")):
        for p in ("%s word of", "%s word in", "the %s word of", "the %s word in", "%s word", "the %s word"):
            H.append((p % w, op))
    for p in ("spell out", "spell", "letters of", "the letters of", "list the letters of", "list the letters in", "list letters of",
              "separate the letters of"):
        H.append((p, "spell"))
    # tails
    def prods(preps, nouns, op, bare, skip=()):
        for pr in preps:
            for n in nouns:
                ph = (pr + " " + n).strip()
                if ph not in skip:
                    T.append((ph, op, bare))
    preps = ["", "in", "into", "to", "in all", "into all", "to all", "all"]
    prods(preps, ["uppercase", "upper case", "capital letters", "caps", "capitals"], "upper", 1,
          skip=("caps", "capitals"))
    prods(preps, ["lowercase", "lower case", "small letters"], "lower", 1)
    prods(["", "in", "into", "to"], ["title case", "titlecase"], "title", 1)
    prods([""], ["capitalized", "capitalised"], "capitalize", 0)
    for p in ("backwards", "backward", "reversed", "in reverse"):
        T.append((p, "reverse", 1))
    for p in ("without spaces", "without any spaces", "with no spaces", "with spaces removed", "with the spaces removed",
              "with all spaces removed", "with all the spaces removed", "without the spaces", "without all spaces"):
        T.append((p, "remove_spaces", 1))
    for p in SORT_MODS + ["in order alphabetically"]:
        T.append((p, "sort_words", 0))
    ntok = lambda s: len(s.split())
    H.sort(key=lambda x: -ntok(x[0]))  # stable: longest phrase first
    T.sort(key=lambda x: -ntok(x[0]))
    seen = set()
    H = [h for h in H if not (h[0] in seen or seen.add(h[0]))]
    seen = set()
    T = [t for t in T if not (t[0] in seen or seen.add(t[0]))]
    return H, T


HEADS, TAILS = _build()
ALL_LISTS = dict(FILLER_SOFT=FILLER_SOFT, FILLER_Q=FILLER_Q, WRAP=WRAP, REPEATV=REPEATV, VERBS=VERBS, DECL1=DECL1, BLOCK=BLOCK, NOUNS=NOUNS,
                 STOPW=STOPW, CONN=CONN, NOISE=NOISE, RNOISE=RNOISE, TYPO_KW=TYPO_KW, PAL_HEADS=PAL_HEADS, PAL_TAILS=PAL_TAILS,
                 SORT_MODS=SORT_MODS, REPL_VERB=list(REPL), REPL_CONN=[" ".join(REPL[k]) for k in REPL])


def _vocab():
    v = set()
    for L in list(ALL_LISTS.values()) + [[h[0] for h in HEADS], [t[0] for t in TAILS], [m for m, _ in CHARS_MODS]]:
        for p in L:
            v.update(p.split())
    v.update(NUMW)
    v.update(["times", "time", "twice", "thrice", "me"])
    return sorted(v)


VOCAB = _vocab()
VOCAB_SET = set(VOCAB)


# ------------------------------------------------------------------ tokens
class Tok:
    __slots__ = ("s", "e", "q", "lw")

    def __init__(self, s, e, q, lw):
        self.s, self.e, self.q, self.lw = s, e, q, lw


def edit1(a, b):
    """True when a, b differ by exactly one substitution, insertion, deletion or adjacent transposition."""
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


def canon(w):
    if len(w) > 15:
        return "#"
    if len(w) >= 6 and w not in VOCAB_SET:
        c = [k for k in TYPO_KW if edit1(w, k)]
        if len(c) == 1:
            return c[0]
    return w


def tokenize(q):
    n = len(q)
    T, i = [], 0
    while i < n:
        if q[i] == " ":
            i += 1
            continue
        c = q[i]
        if c in "\"`'":
            j = -1
            for k in range(i + 1, n):
                if q[k] == c and (k + 1 == n or q[k + 1] in " ,.;:!?)"):
                    j = k
                    break
            if j > i + 1:
                T.append(Tok(i + 1, j, True, "\x01"))
                i = j + 1
                continue
        j = i
        while j < n and q[j] != " ":
            j += 1
        e = j
        while e > i and (q[e - 1] in ",;!?" or (e == n and q[e - 1] == ".")):
            e -= 1
        colon = False
        if e > i and q[e - 1] == ":":
            colon, e = True, e - 1
            while e > i and q[e - 1] in ",;!?":
                e -= 1
        if e > i:
            lw = q[i:e].lower().lstrip("([{").rstrip(".)]}")
            T.append(Tok(i, e, False, canon(lw if lw else "?")))
        if colon:
            T.append(Tok(e, e + 1, False, ":"))
        if e == i and not colon:  # pure punctuation token
            T.append(Tok(i, j, False, "?"))
        i = j
    while T and not T[-1].q and set(q[T[-1].s:T[-1].e]) <= set("?!."):
        T.pop()
    while T and not T[-1].q and T[-1].lw in ("please", "pls", "plz", "thanks", "thx"):
        T.pop()
    if len(T) >= 2 and not T[-1].q and not T[-2].q and T[-2].lw == "for" and T[-1].lw == "me":
        del T[-2:]
    return T


def pm(T, i, ph):
    """Token count if phrase ph matches T at i (unquoted tokens only), else 0."""
    k = 0
    for w in ph.split():
        if i + k >= len(T) or T[i + k].q or T[i + k].lw != w:
            return 0
        k += 1
    return k


def is_path(raw):
    if "/" in raw or "\\" in raw or "_" in raw:  # path or identifier
        return True
    d = raw.rfind(".")
    if d <= 0 or d == len(raw) - 1:
        return False
    ext = raw[d + 1:]
    return ext.isalpha() and ext.isascii() and len(ext) <= 4 and any(ch.isalpha() for ch in raw[:d])


# ------------------------------------------------------------------ operations on text
def _split(t):
    return t.split()


def do_op(op, t, n=0):
    if op == "upper": return t.upper()
    if op == "lower": return t.lower()
    if op == "title":
        o, prev = [], False
        for ch in t:
            a = ch.isalpha()
            o.append((ch.lower() if prev else ch.upper()) if a else ch)
            prev = a
        return "".join(o)
    if op == "capitalize": return t[:1].upper() + t[1:]
    if op == "reverse": return t[::-1]
    if op == "reverse_words": return " ".join(_split(t)[::-1])
    if op == "count_letters": return unit(sum(c.isalpha() for c in t), "letter")
    if op == "count_chars": return unit(len(t), "character")
    if op == "count_chars_nospace": return unit(sum(c != " " for c in t), "character")
    if op == "count_words": return unit(len(_split(t)), "word")
    if op == "count_vowels": return unit(sum(c in "aeiouAEIOU" for c in t), "vowel")
    if op == "remove_spaces": return t.replace(" ", "")
    if op == "initials": return "".join(w[0] for w in _split(t))
    if op == "acronym": return "".join(w[0].upper() for i, w in enumerate(_split(t)) if i == 0 or w.lower() not in STOPW)
    if op == "sort_words": return " ".join(sorted(_split(t)))
    if op in ("first_word", "last_word"):
        w = _split(t)
        return w[0 if op == "first_word" else -1].rstrip(",.;:!?")
    if op == "palindrome":
        a = [c.lower() for c in t if c.isalnum()]
        return "yes" if a == a[::-1] else "no"
    if op == "spell": return " ".join("-".join(w) for w in _split(t))
    raise ValueError(op)


def unit(n, u):
    return "%d %s%s" % (n, u, "" if n == 1 else "s")


# ------------------------------------------------------------------ parser
def strip_noise(A, noise=NOISE):
    for _ in range(4):
        if not A:
            break
        if not A[0].q and A[0].lw in CONN and len(A) > 1:
            A = A[1:]
            continue
        for ph in noise:
            k = pm(A, 0, ph)
            if k and len(A) > k:
                A = A[k:]
                break
        else:
            break
    return A


def arg_text(q, A, op):
    """Validated argument text or None."""
    if not A:
        return None
    if any(t.q for t in A):
        return q[A[0].s:A[0].e] if len(A) == 1 and q[A[0].s:A[0].e].strip(" ") else None
    w0 = A[0].lw
    if w0 in DECL1 or w0 in VERBS or (len(A) == 1 and w0 in NOUNS):
        return None
    if w0 == "the" and op in NO_THE:
        return None
    if len(A) == 1 and len(w0) >= 4 and w0.endswith("s") and not w0.endswith(("ss", "us", "is")):
        return None  # a lone plural is probably a collection ("reverse names"), not text
    return q[A[0].s:A[-1].e]


def ends_with_tail(T, a, b):
    """Does T[a:b] end with some tail phrase?"""
    for ph, _, _ in TAILS:
        k = len(ph.split())
        if b - k >= a and pm(T, b - k, ph) == k:
            return True
    return False


def parse_num(w):
    if w.isdigit() and len(w) <= 2:
        return int(w)
    return NUMW.get(w, 0)


def textops(q):
    if not q or len(q) > MAXQ or any(not (0x20 <= ord(c) <= 0x7e) for c in q):
        return None
    q = q.strip(" ")
    T = tokenize(q)
    n = len(T)
    if n < 2 or n > MAXTOK:
        return None
    for t in T:
        if not t.q and (t.lw in BLOCK or is_path(q[t.s:t.e])):
            return None
    # leading filler: s0 = soft fillers only, s1 = soft plus question words
    s0 = 0
    while s0 < n and not T[s0].q and T[s0].lw in FILLER_SOFT:
        s0 += 1
    s1 = s0
    while s1 < n and not T[s1].q and (T[s1].lw in FILLER_SOFT or T[s1].lw in FILLER_Q):
        s1 += 1
    for s in range(0, min(s1, n - 1) + 1):
        soft = s <= s0
        # replace
        if not T[s].q and T[s].lw in REPL and soft:
            r = try_replace(q, T, s)
            if r:
                return r
        # repeat
        if soft and not T[s].q and T[s].lw in REPEATV:
            r = try_repeat(q, T, s)
            if r:
                return r
        # palindrome
        r = try_pal(q, T, s) if soft else None
        if r:
            return r
        # head phrases
        for ph, op in HEADS:
            k = pm(T, s, ph)
            if not k:
                continue
            A, o = T[s + k:], op
            if op == "sort_words":
                for m in SORT_MODS:
                    mk = len(m.split())
                    if len(A) > mk and pm(A, len(A) - mk, m) == mk:
                        A = A[:-mk]
                        break
            elif op == "count_chars":
                for m, ns in CHARS_MODS:
                    mk = len(m.split())
                    if len(A) > mk and pm(A, len(A) - mk, m) == mk:
                        A, o = A[:-mk], ("count_chars_nospace" if ns else "count_chars")
                        break
            if ends_with_tail(A, 0, len(A)):
                break
            r = finish(q, o, strip_noise(A))
            if r:
                return r
            break  # longest matching head decides; no fallback to a shorter reading
        # tails
        if soft:
            for ph, op, bare in TAILS:
                k = len(ph.split())
                if n - k <= s or pm(T, n - k, ph) != k:
                    continue
                a0 = s
                if not T[s].q and T[s].lw in WRAP:
                    a0 = s + 1
                    if a0 < n and not T[a0].q and T[a0].lw == "me":
                        a0 += 1
                elif not bare:
                    continue
                A = strip_noise(T[a0:n - k])
                if any(not t.q and (t.lw in WRAP or t.lw in VERBS) for t in A):
                    break  # a second instruction inside the argument: ambiguous
                r = finish(q, op, A)
                if r:
                    return r
                break
    return None


def finish(q, op, A):
    t = arg_text(q, A, op)
    if t is None:
        return None
    if op == "acronym" and len(t.split()) < 2:
        return None
    out = do_op(op, t)
    return (op, out) if 0 < len(out) <= MAXOUT else None


def try_repeat(q, T, s):
    n = len(T)
    k = 0
    if n - 1 > s and not T[n - 1].q and T[n - 1].lw in ("twice", "thrice"):
        cnt, k = 2 if T[n - 1].lw == "twice" else 3, 1
    elif n - 2 > s and not T[n - 1].q and T[n - 1].lw in ("times", "time") and not T[n - 2].q:
        cnt, k = parse_num(T[n - 2].lw), 2
    if not k or cnt < 1:
        return None
    A = strip_noise(T[s + 1:n - k])
    t = arg_text(q, A, "repeat")
    if t is None or len(t) * cnt + cnt - 1 > MAXOUT:
        return None
    return ("repeat", " ".join([t] * cnt))


def try_pal(q, T, s):
    n = len(T)
    for h in PAL_HEADS:
        hk = pm(T, s, h)
        if not hk:
            continue
        for tl in PAL_TAILS:
            tk = len(tl.split())
            if n - tk > s + hk and pm(T, n - tk, tl) == tk:
                A = strip_noise(T[s + hk:n - tk])
                t = arg_text(q, A, "palindrome")
                if t is None or not any(c.isalnum() for c in t):
                    return None
                return ("palindrome", do_op("palindrome", t))
        if h.startswith("palindrome"):
            A = strip_noise(T[s + hk:])
            t = arg_text(q, A, "palindrome")
            if t is None or not any(c.isalnum() for c in t):
                return None
            return ("palindrome", do_op("palindrome", t))
        return None
    return None


def span_text(q, A):
    if not A:
        return None
    if any(t.q for t in A):
        return q[A[0].s:A[0].e] if len(A) == 1 else None
    return q[A[0].s:A[-1].e]


def try_replace(q, T, s):
    n, verb = len(T), T[s].lw
    c = next((i for i in range(s + 1, n) if not T[i].q and T[i].lw in REPL[verb]), -1)
    if c < 0:
        return None
    i = next((j for j in range(c + 1, n) if not T[j].q and T[j].lw == "in"), -1)
    if i < 0:
        return None
    A, B = strip_noise(T[s + 1:c], RNOISE), strip_noise(T[c + 1:i], RNOISE)
    X = strip_noise(T[i + 1:])
    a, b = span_text(q, A), span_text(q, B)
    x = arg_text(q, X, "replace")
    if a is None or b is None or x is None or a not in x:
        return None
    out = x.replace(a, b)
    return ("replace", out) if 0 < len(out) <= MAXOUT else None


# ------------------------------------------------------------------ header emitter / CLI
def emit_h():
    def cs(s): return '"%s"' % s
    o = ["/* GENERATED by campaign/pipeline/textops.py --emit-h; do not edit. */"]
    for k, v in ALL_LISTS.items():
        o.append("static const char *const TO_%s[] = {%s, 0};" % (k, ", ".join(cs(x) for x in v)))
    o.append("static const char *const TO_VOCAB[] = {%s, 0};" % ", ".join(cs(x) for x in VOCAB))
    o.append("static const struct { const char *p; int op; } TO_HEADS[] = {%s, {0, 0}};" % ", ".join(
        "{%s, TO_%s}" % (cs(p), op.upper()) for p, op in HEADS))
    o.append("static const struct { const char *p; int op; int bare; } TO_TAILS[] = {%s, {0, 0, 0}};" % ", ".join(
        "{%s, TO_%s, %d}" % (cs(p), op.upper(), b) for p, op, b in TAILS))
    o.append("static const struct { const char *p; int ns; } TO_CHARS_MODS[] = {%s, {0, 0}};" % ", ".join(
        "{%s, %d}" % (cs(p), ns) for p, ns in CHARS_MODS))
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    if "--emit-h" in sys.argv:
        sys.stdout.write(emit_h())
    else:  # batch: one question per line -> "op\toutput" or "-"
        for line in sys.stdin.read().split("\n")[:-1]:
            r = textops(line)
            print("%s\t%s" % r if r else "-")
