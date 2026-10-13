"""KB4 ranked entity + relation retrieval (reference for clean/plumbing/retrieve4.c).

query -> gate -> relation cue + entity words -> candidate keys (exact; one optional fuzzy/cue expansion)
      -> bounded candidate pool -> integer scoring -> (record, field, evidence status).

Statuses: answer_present, field_missing, ambiguous, no_match, gated; runtime-only: io_error, corrupt_kb.
Every integer weight is a module constant (documented in FORMAT-KB4.md). Nothing here uses floats or sets with
undefined order, so the C port can match it exactly."""
import re
import os

from kb import normalize
from kb4 import KB4, KB4Error, KIND_NAME, REL, REL_NAME, VOCAB, ETYPE_NAME, PROV_NAME, KEY_MAX, CAND_MAX

# ---- weights (integers) ----
W_COVER = 6        # per percent of the entity words the matched key covers (0..600)
W_KIND = {0: 8, 1: 6, 2: 4, 3: -20}  # key kind: title, redirect, title minus qualifier, derived alias (a name that is not a title never makes a title ambiguous)
W_TYPO = 40        # per fuzzy-corrected word
W_PROM = 1         # times prominence 0..63
W_REL_PRESENT = 60  # requested field has a value
W_REL_MISSING = 20  # requested field is an explicit "missing" marker (entity type fits the relation)
AMBIG_GAP = 12     # top two candidates this close (same coverage) -> ambiguous
POOL = 8           # distinct candidates kept
MAX_KEYS = 12      # exact key lookups in the first round
MAX_FKEYS = 16     # lookups in the expansion round (single-word corrections)
MAX_F2KEYS = 16    # extra lookups for corrections of two words at once
FZ_WORDS = 8       # distinct query words sent to the delete index
MAX_WORDS = 32
QUESTION_MAX = 127
CONTENT_MIN = 4  # expansion never repairs short entity words

STOP = set("""what who where when why how is are was were the a an of in on to do does can i you me my your
tell about whats which whom this that it its and or for with at by from be as if so please explain define
describe give say know mean means there their they he she we us our
continent currency language capital country city money name main official primary spoken speak located called
use used people plus minus times divided multiply add subtract percent calculate much""".split())
CUES = set("who what whats where when which define explain describe".split())
# relation words: kept as cues, not entity words
REL_WORDS = set("""last surname family capital born birth birthday birthdate birthplace died die dies death dead job occupation
profession career population years year date dates start started begin began end ended lasted happen happened occur
occurred located location situated country continent place state town live lives living pass passed away""".split())
GATE_REL = set("""surname capital born birth birthday birthplace died die dies death population occupation profession job
years year date dates lasted located location happened""".split())
AUX = set("did has have had will would old long many".split())  # question glue: never part of an entity name
FILL = set("hi hello hey thanks thank now good morning afternoon evening ok okay yo".split())  # greeting/filler: skipped before the cue test
ENT_STOP = STOP | REL_WORDS | AUX | FILL
# relation words that a one-character typo can still be recognized as (len >= 4; only when the typo word is not a KB word)
CUE_TYPO = ["born", "died", "birth", "death", "birthday", "capital", "population", "surname", "occupation", "profession", "last", "name", "family", "where", "birthplace", "started", "founded", "established"]
CONVERSATION = set("hi hello hey heyy hii hello chatds thanks thank thx thankyou ok okay cool fine good great nice yep yup yeah yes no nah lol lmao haha hehe sup wassup yo bye goodbye cya see ya later for now you too morning evening afternoon well doing im i am alright awesome sure dude bro mate much not nm nothing bored tired sad happy hiya howdy greetings friend k understood then laters tomorrow".split())
WHERE = set("where place birthplace city town country state".split())
CODE_OPS = set("print return sort reverse loop function variable command dict".split())
CODE_CHARS = set("()[]{}=\"`_")
NUM_WORDS = set("""zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen
seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million""".split())
MATH_WORDS = set("""half double twice triple quarter over sum product added add subtract subtracted multiply divide difference
squared cubed and away take more less than""".split())
ARITH_WORDS = set("plus minus times divided multiplied percent".split())

REL_WORDS |= set('author authored inventor invented creator created wrote written founded established known tall height length long'.split())
ENT_STOP = STOP | REL_WORDS | AUX | FILL


def conversation_act(w):
    """Whole short utterance only; never swallow a greeting followed by a fact question."""
    return bool(w) and len(w) <= 4 and all(x in CONVERSATION or re.fullmatch(r'hey+|hi+|hello+|ha(?:ha)+', x) for x in w)


STATUSES = ("answer_present", "field_missing", "ambiguous", "no_match", "gated", "io_error", "corrupt_kb")


def _arith(q):
    """digit next to an operator, optional whitespace between (kb chatds_runtime: \\d\\s*[-+*/%^] | [-+*/%^]\\s*\\d)"""
    ops = "-+*/%^"
    sp = " \t\n\r\v\f\x1c\x1d\x1e\x1f"
    for i, c in enumerate(q):
        if not (c.isdigit() and c in "0123456789") and c not in ops:
            continue
        j = i + 1
        while j < len(q) and q[j] in sp:
            j += 1
        nxt = q[j] if j < len(q) else ""
        if c in "0123456789":
            if nxt and nxt in ops:
                return True
        elif nxt and nxt in "0123456789":
            return True
    return False


def _bad_quote(q):
    for i, c in enumerate(q):
        if c == "'" and (i == 0 or not q[i - 1].isalpha() or i + 1 >= len(q) or not q[i + 1].isalpha() or not q[i - 1].isascii() or not q[i + 1].isascii()):
            return True
    return False


def gate(q, w):
    """None if the text may reach the KB (code/arithmetic checks), else a reason. The cue test is cue_ok()."""
    if conversation_act(w):
        return 'conversation'
    if any(c in CODE_CHARS for c in q):
        return "code_chars"
    if _bad_quote(q):
        return "quote"
    if _arith(q):
        return "arith"
    ws = set(w)
    if ws & CODE_OPS:
        return "code_op"
    hasnum = any(c in "0123456789" for c in q) or bool(ws & NUM_WORDS)
    if (ws & NUM_WORDS) and (ws & MATH_WORDS):
        return "arith_words"
    if hasnum and (ws & ARITH_WORDS):
        return "arith_words"
    return None


def cue_ok(w):
    """a question word, 'tell me about', or a relation word (after leading greetings/filler)"""
    ws = set(w)
    pairs = {(w[i], w[i + 1]) for i in range(len(w) - 1)}
    rel = bool(ws & GATE_REL) or ("last", "name") in pairs or ("family", "name") in pairs or ("many", "people") in pairs
    i0 = 0
    while i0 < len(w) and w[i0] in FILL:
        i0 += 1
    return bool(i0 < len(w) and (w[i0] in CUES or rel) or " ".join(w[i0:]).startswith("tell me about "))


def parse_relation(w):
    """requested field name from the question words (relation cue; the cue words stay out of the entity)."""
    ws = set(w)
    pairs = {(w[i], w[i + 1]) for i in range(len(w) - 1)}
    where = bool(ws & WHERE)
    if "surname" in ws or ("last", "name") in pairs or ("family", "name") in pairs:
        return "surname"
    if "capital" in ws:
        return "capital"
    if ws & {"born", "birth", "birthday", "birthdate", "birthplace"}:
        return "birth_place" if where else "birth_date"
    if ws & {"died", "die", "dies", "death", "dead"} or ("pass", "away") in pairs or ("passed", "away") in pairs:
        return "death_place" if where else "death_date"
    if ws & {"job", "occupation", "profession", "career"} or {"did", "do"} <= ws or {"does", "do"} <= ws:  # "what did X do"
        return "occupation"
    if ws & {'author', 'authored', 'inventor', 'invented', 'creator', 'created', 'wrote', 'written'} and not ws & {'when', 'year', 'date'}:
        return 'creator'
    if ws & {'tall', 'height'}:
        return 'height'
    if 'length' in ws or 'long' in ws and 'how' in ws and 'did' not in ws:
        return 'length'
    if "population" in ws or ("many", "people") in pairs:
        return "quantity"
    if "old" in ws:
        return "birth_date"
    if ws & {"years", "year", "date", "long", "dates", "start", "started", "begin", "began", "end", "ended", "lasted", "happen", "happened",
             "occur", "occurred", "when", "founded", "established"}:
        return "date_range"
    if ws & {"where", "located", "location", "situated", "country", "continent"}:
        return "location"
    return "definition"


class _Cand:
    __slots__ = ("c", "cover", "typo", "key", "s1", "s2", "ord", "pop", "weak")


def _s1(c, total):
    pct = 100 * c.cover // total if total else 0
    return W_COVER * pct + W_KIND[c.c.kind] + W_PROM * c.c.prom - W_TYPO * c.typo


def _rel_score(c, rel):
    b = 1 << REL[rel]
    return W_REL_PRESENT if c.c.pmask & b else (W_REL_MISSING if c.c.mmask & b else 0)


class Result:
    def __init__(self):
        self.status = "no_match"
        self.field = None          # requested field name
        self.relation = None       # vocabulary relation
        self.rec = None
        self.value = None
        self.prov = None
        self.context = ""
        self.alts = []             # recoffs of the other considered candidates (ambiguous)
        self.log = {}


def grams(isent, total, widx=None):
    """candidate n-grams (start, n, cover) in try order: cover desc, length desc, position asc."""
    n_w = len(isent)
    out = []
    for n in range(1, 5):
        for i in range(0, n_w - n + 1):
            if not (isent[i] and isent[i + n - 1]):
                continue
            c = sum(isent[i:i + n])
            if 2 * c > total:
                out.append((i, n, c))
    out.sort(key=lambda g: (-g[2], -g[1], g[0]))
    return out


def _decide(pool, total, rel, k, ambig):
    """-> (best _Cand or None, status class str, alts)"""
    acc = [c for c in pool if 2 * c.cover > total]
    if not acc:
        return None, "no_match", []
    for c in acc:
        c.s1 = _s1(c, total)
    acc.sort(key=lambda c: (-c.s1, c.ord))
    top = acc[:k]
    for c in top:
        c.s2 = c.s1 + _rel_score(c, rel)
    top.sort(key=lambda c: (-c.s2, c.ord))
    best = top[0]
    if ambig and len(top) >= 2 and top[1].cover == best.cover and best.s2 - top[1].s2 <= AMBIG_GAP:
        return best, "ambiguous", [t.c.recoff for t in top[1:]]
    return best, "ok", []


def _add(pool, cands, cover, typo, key, order):
    for c in cands:
        for p in pool:
            if p.c.recoff == c.recoff:
                break
        else:
            if len(pool) >= POOL:
                continue
            x = _Cand()
            x.c, x.cover, x.typo, x.key, x.ord = c, cover, typo, key, order[0]
            order[0] += 1
            pool.append(x)
            continue
        # same entity again: keep the better route (more coverage, then fewer typos, then better key kind)
        if (cover, -typo, -c.kind) > (p.cover, -p.typo, -p.c.kind):
            p.c, p.cover, p.typo, p.key = c, cover, typo, key


def retrieve(kb, question, k=3, expand=True, ambig=True, routed=False, entres=None, index=None):
    """k: candidates re-ranked by the requested relation (1 = entity score only). expand: allow the one bounded expansion.
    routed: the caller (router) already decided this is a facts question, so a missing question word is not a reason to gate."""
    enabled = os.environ.get('CHATDS_ENTRES') == '1' if entres is None else entres
    if enabled:
        import entres as ER
        return ER.retrieve(kb, question, k, expand, ambig, routed, index)
    r = Result()
    log = r.log = dict(question=question, keys_tried=[], candidates=0, sector_reads=0, lookups=0, chosen_field=None,
                       fallback_reason=None, expansion=False, k=k, relation=None, gate=None)
    kb.sector_reads_start = kb.sector_reads
    kb.lookups_start = kb.lookups
    try:
        return _retrieve(kb, question, k, expand, ambig, routed, r, log)
    except KB4Error as e:
        r.status = "io_error" if e.kind == "io" else "corrupt_kb"
        log["fallback_reason"] = str(e)
        return _fin(kb, r)


def _fin(kb, r):
    r.log["sector_reads"] = kb.sector_reads - kb.sector_reads_start
    r.log["lookups"] = kb.lookups - kb.lookups_start
    return r


def _lookup(kb, key, log):
    log["keys_tried"].append(key)
    return kb.lookup(key)


def _retrieve(kb, question, k, expand, ambig, routed, r, log):
    if len(question) > QUESTION_MAX:
        r.status, log["fallback_reason"] = "gated", "too_long"
        return _fin(kb, r)
    w = normalize(question).split()
    if len(w) > MAX_WORDS:
        r.status, log["fallback_reason"] = "gated", "too_long"
        return _fin(kb, r)
    g = gate(question, w)
    log["gate"] = g
    if g:
        r.status, log["fallback_reason"] = "gated", g
        return _fin(kb, r)
    isent = [0 if x in ENT_STOP else 1 for x in w]
    wc = _cue_typos(kb, w, isent)  # w with one-character typos of relation words repaired
    if wc is not w:
        isent = [0 if x in ENT_STOP else 1 for x in wc]
    if not routed and not cue_ok(wc):
        r.status, log["fallback_reason"] = "gated", "no_cue"
        return _fin(kb, r)
    rel = parse_relation(wc)
    r.field, r.relation = rel, VOCAB[rel]
    log["relation"] = rel
    glue = {'kind', 'work'} if rel == 'occupation' else {'big', 'large'} if rel == 'quantity' else set()
    isent = [0 if x in glue else e for x, e in zip(wc, isent)]
    cue_entity = sum(isent) == 0  # the question is only relation words ("what is the capital"): they become the entity
    if cue_entity:
        isent = [0 if (x in STOP or x in FILL) and x not in REL_WORDS else 1 for x in w]
    total = sum(isent)
    pool, order = [], [0]
    if total and not cue_entity:
        _exact_round(kb, w, isent, total, pool, order, log)
    best, st, alts = _decide(pool, total, rel, k, ambig)
    need = best is None or best.cover < total
    if expand and need and total and any(isent[j] and len(x) >= CONTENT_MIN for j, x in enumerate(w)):
        log["expansion"] = True
        _expand(kb, w, isent, total, pool, order, log, cue_entity)
        best, st, alts = _decide(pool, total, rel, k, ambig)
    log["candidates"] = len(pool)
    if best is None:
        r.status = "no_match"
        log["fallback_reason"] = "no_candidate" if not pool else "coverage_below_majority"
        return _fin(kb, r)
    return _answer(kb, r, best, st, alts, rel, log)


def edit1(a, b):
    """a != b and they differ by one substitution, insertion, deletion or adjacent transposition"""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        d = [i for i in range(len(a)) if a[i] != b[i]]
        return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])
    if len(a) < len(b):
        a, b = b, a
    i = 0
    while i < len(b) and a[i] == b[i]:
        i += 1
    return a[:i] + a[i + 1:] == b


def _cue_typos(kb, w, isent):
    """Words that are one typo away from a relation word ('borrn', 'captial') and are not KB words become that word.
    Returns w itself when nothing changed (or when repairing would leave no entity word)."""
    out, changed = list(w), False
    for j, x in enumerate(w):
        if not isent[j] or len(x) < 4:
            continue
        for c in CUE_TYPO:
            if len(c) >= 4 and edit1(x, c):
                known, _ = kb.fuzzy(x)
                if not known:
                    out[j], changed = c, True
                break
    if changed and sum(0 if x in ENT_STOP else 1 for x in out) == 0:
        return w
    return out if changed else w


def _exact_round(kb, w, isent, total, pool, order, log):
    tried = 0
    for i, n, c in grams(isent, total):
        if tried >= MAX_KEYS:
            break
        key = " ".join(w[i:i + n])
        if len(key) > KEY_MAX or (n == 1 and len(w[i]) < 3):
            continue
        tried += 1
        got = _lookup(kb, key, log)
        _add(pool, got, c, 0, key, order)
        if got and c == total:
            break


def _expand(kb, w, isent, total, pool, order, log, cue_entity):
    """the one bounded expansion: relation words as entity words (if nothing else was left), then delete-index
    corrections of the entity words. Unknown words are corrected first, known words only if still unresolved.
    Stops at the first full-coverage hit."""
    tried = 0
    seen = []
    gs = grams(isent, total)

    def full():
        return any(p.cover == total and 2 * p.cover > total for p in pool)

    if cue_entity:
        for i, n, c in gs:
            key = " ".join(w[i:i + n])
            if tried >= MAX_FKEYS or len(key) > KEY_MAX or (n == 1 and len(w[i]) < 3):
                continue
            tried += 1
            _add(pool, _lookup(kb, key, log), c, 0, key, order)
        if full():
            return
    later = []  # known words: corrected only if still unresolved (the probe is repeated, not cached: no RAM for 8 x 4 words)

    def fix(j, cands):
        nonlocal tried
        for cw in cands:
            for i, n, c in gs:
                if not (i <= j < i + n):
                    continue
                key = " ".join(cw if x == j else w[x] for x in range(i, i + n))
                if tried >= MAX_FKEYS or len(key) > KEY_MAX:
                    return
                tried += 1
                _add(pool, _lookup(kb, key, log), c, 1, key, order)
            if full():
                return

    unk = []  # first two unknown words with candidates, kept for the two-word pass

    for j, word in enumerate(w):
        if not isent[j] or len(word) < max(kb.fzmin, CONTENT_MIN) or len(word) > KEY_MAX or word in seen:
            continue
        if len(seen) >= FZ_WORDS or full():
            break
        seen.append(word)
        known, cands = kb.fuzzy(word)
        if known:
            later.append(j)
        else:
            if cands and len(unk) < 2:
                unk.append((j, cands))
            fix(j, cands)
    for j in later:
        if full() or tried >= MAX_FKEYS:
            break
        fix(j, kb.fuzzy(w[j])[1])
    if len(unk) == 2 and not full():
        (j1, c1), (j2, c2) = unk
        t2 = 0
        for a in c1:
            for b in c2:
                for i, n, c in gs:
                    if not (i <= j1 < i + n and i <= j2 < i + n):
                        continue
                    key = " ".join(a if x == j1 else b if x == j2 else w[x] for x in range(i, i + n))
                    if t2 >= MAX_F2KEYS or len(key) > KEY_MAX:
                        continue
                    t2 += 1
                    _add(pool, _lookup(kb, key, log), c, 2, key, order)
                if full():
                    return


def _answer(kb, r, best, st, alts, rel, log):
    rec = kb.record(best.c.recoff)
    r.rec = rec
    r.alts = alts
    r.log["chosen_key"] = best.key
    log["chosen_field"] = rel
    if st == "ambiguous":
        r.status, log["fallback_reason"] = "ambiguous", "close_candidates"
        return _fin(kb, r)
    f = rec["fields"].get(rel)
    if f is None or f[2]:
        r.status = "field_missing"
        log["fallback_reason"] = "field_marked_missing" if f else "field_not_applicable"
        return _fin(kb, r)
    r.status, r.value, r.prov = "answer_present", f[0], PROV_NAME[f[1]]
    r.context = render(rec, rel, f[0])
    return _fin(kb, r)


# ---- rendering (the evidence context text) ----
MONTH = "January February March April May June July August September October November December".split()


_ISO_RE = re.compile(r"-?\d{1,4}(?:-\d\d){0,2}")


def date_text(iso):
    if not _ISO_RE.fullmatch(iso):
        raise KB4Error("corrupt", "bad date")
    bc = iso.startswith("-")
    p = iso.lstrip("-").split("-")
    if len(p) > 1 and not 1 <= int(p[1]) <= 12 or len(p) > 2 and not 1 <= int(p[2]) <= 31:
        raise KB4Error("corrupt", "bad date")
    y = str(int(p[0])) + (" BC" if bc else "")
    if len(p) == 1:
        return y
    if len(p) == 2:
        return "%s %s" % (MONTH[int(p[1]) - 1], y)
    return "%d %s %s" % (int(p[2]), MONTH[int(p[1]) - 1], y)


def _in_on(iso):
    return "on" if iso.lstrip("-").count("-") == 2 else "in"


def render(rec, rel, v):
    t = rec["title"]
    if t.endswith(")") and " (" in t:
        t = t[:t.rindex(" (")]
    if rel == "definition":
        return v
    if rel == "date_range":
        if "/" in v:
            a, *b = v.split("/")
            if len(b) != 1:
                raise KB4Error("corrupt", "bad date")
            b = b[0]
            if not a:
                return '%s ended %s %s.' % (t, _in_on(b), date_text(b))
            return "%s was from %s to %s." % (t, date_text(a), date_text(b))
        return "%s was %s %s." % (t, _in_on(v), date_text(v))
    if rel == "birth_date":
        return "%s was born %s %s." % (t, _in_on(v), date_text(v))
    if rel == "death_date":
        return "%s died %s %s." % (t, _in_on(v), date_text(v))
    if rel == "birth_place":
        return "%s was born in %s." % (t, v)
    if rel == "death_place":
        return "%s died in %s." % (t, v)
    if rel == "location":
        return "%s is in %s." % (t, v)
    if rel == "surname":
        return "The last name of %s is %s." % (t, v)
    if rel == "capital":
        return "The capital of %s is %s." % (t, v)
    if rel == "occupation":
        return "%s was %s %s." % (t, "an" if v[:1].lower() in "aeiou" else "a", v)
    if rel == 'creator':
        return '%s was created by %s.' % (t, v)
    if rel in ('height', 'length'):
        return '%s is %s %s.' % (t, v, 'tall' if rel == 'height' else 'long')
    if rel == "quantity":
        return "%s has a population of %s." % (t, v)
    raise ValueError(rel)
