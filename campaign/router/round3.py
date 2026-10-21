"""Round 3 int8 fallbacks: Python twin of clean/plumbing/{router,round3}.c.

Rules remain primary; learned spans never invent bytes. Integer-exact: hashed
word+char n-gram features, int8 weights, int16 biases, Q8 margins.
"""
import functools
import hashlib
import pathlib
import struct
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent/'pipeline'))
import textops as to  # noqa: E402
import prestep as ps  # noqa: E402

ACTS = ['none','greeting','thanks','bye','identity','capabilities','how_are_you','compliment','insult','repeat','pushback']
OPS = ['none'] + to.OPS
TAGS = ['O','B','I','X','Y']
MODELS = HERE/'models'
HEADS = ('act', 'op', 'tag')
# Must match clean/product/learned.c.
THRESHOLDS = dict(act=1793, op=386, tag=0)

# ---- featurizer (router.h documents the recipe)
QMAX, CLIP, FNV_OFF, FNV_PRIME = 127, 7, 2166136261, 16777619


def norm_bytes(s):
    b, gap = bytearray(), False
    for ch in s:
        o = ord(ch)
        if o >= 0x80:
            continue
        if o in (32, 9, 10, 11, 12, 13):
            gap = len(b) > 0
            continue
        if 65 <= o <= 90:
            o += 32
        if gap:
            b.append(32)
            gap = False
        b.append(o)
    return bytes(b[:QMAX]).rstrip(b' ')


def _isword(c):
    return 97 <= c <= 122 or 48 <= c <= 57 or c == 95


def shape(t):
    out = bytearray()
    for c in t:
        k = 86 if c in b'aeiouy' else 68 if 48 <= c <= 57 else 95 if c == 95 else 67
        if not out or out[-1] != k:
            out.append(k)
    out.append(min(len(t), 12))
    return bytes(out)


def fnv(tag, payload):
    h = ((FNV_OFF ^ tag) * FNV_PRIME) & 0xFFFFFFFF
    for c in payload:
        h = ((h ^ c) * FNV_PRIME) & 0xFFFFFFFF
    return h


def hashes(s):
    b, toks, i = norm_bytes(s), [], 0
    while i < len(b):
        if b[i] == 32:
            i += 1
        elif _isword(b[i]):
            j = i
            while j < len(b) and _isword(b[j]):
                j += 1
            toks.append(b[i:j])
            i = j
        else:
            toks.append(b[i:i+1])
            i += 1
    out = []
    for k, t in enumerate(toks):
        out.append(fnv(0x77, t))
        if _isword(t[0]):
            out.append(fnv(0x53, shape(t)))
        if t.isdigit():
            out.append(fnv(0x23, b''))
        if k + 1 < len(toks):
            out.append(fnv(0x62, t + b' ' + toks[k+1]))
    p = b' ' + b + b' '
    for n in (3, 4):
        out += [fnv(0x63, p[i:i+n]) for i in range(len(p) - n + 1)]
    return out


def features(s, dims):
    acc = {}
    for h in hashes(s):
        acc[h & (dims-1)] = acc.get(h & (dims-1), 0) + (-1 if (h >> 24) & 1 else 1)
    return {k: max(-CLIP, min(CLIP, v)) for k, v in acc.items() if v}


# ---- flat single-head CDSR sidecar (layout in router.h)
def read_head(blob):
    assert blob[:4] == b'CDSR' and hashlib.sha256(blob[64:]).digest() == blob[20:52]
    no, dims = blob[10], struct.unpack_from('<H', blob, 12)[0]
    p = 64 + ((2*no + blob[11] + 3) & ~3)
    assert struct.unpack_from('<BB', blob, p)[1] == no
    p += 8 + ((no + 3) & ~3)
    W = np.frombuffer(blob, np.int8, no*dims, p).reshape(dims, no).astype(np.int64)
    p += no*dims
    return W, np.frombuffer(blob, '<i2', no, p).astype(np.int64)


@functools.lru_cache(maxsize=1)
def load():
    return {k: read_head((MODELS/f'round3-{k}.cdsr').read_bytes()) for k in HEADS}


def predict(head, q):
    """-> (best output, Q8 margin over the runner-up). Ties keep the lowest index, as in C."""
    W, b = head
    acc = features(q, W.shape[0])
    n = max(1, sum(abs(v) for v in acc.values()))
    s = n*b + (np.array(list(acc.values()), np.int64) @ W[list(acc)] if acc else 0)
    order = np.argsort(-s, kind='stable')
    return int(order[0]), int(((s[order[0]] - s[order[1]]) << 8) // n)


# ---- round3 fallbacks
@functools.lru_cache(maxsize=32768)
def heads(q):
    hs = load()
    a, am = predict(hs['act'], q)
    o, om = predict(hs['op'], q)
    return dict(act=(ACTS[a], am), op=(OPS[o], om))


def act_allowed(q, dec, hp):
    """No theft from explicit tasks; default-facts is not a fired fact rule."""
    if (ps.dlg_kind(q) or dec.get('act')
            or hp.r4.conversation_act(hp.kb3.normalize(q).split())
            or dec['handler'] in ('text', 'calc', 'python', 'shell', 'conversation')
            or to.textops(q) or ps.calc_parse(q)):
        return False
    if dec['handler'] == 'facts' and (hp.rules.v0_gate(q) or hp.re.search(hp.rules.FACT_CUE, hp.plain_of(q))):
        return False
    if hp.ambig_term(hp.plain_of(q)) or ps.textops_guard(q):
        return False
    return ps.ascii_ok(q)


def act(q, *, raw=False):
    """Caller vetoes when c14 rules/dialogue fired. raw bypasses the threshold."""
    label, margin = heads(q)['act']
    ok = ps.ascii_ok(q) and label != 'none' and margin >= (0 if raw else THRESHOLDS['act'])
    return (label, margin) if ok else None


def tokens(q):
    return to.tokenize(q) if ps.ascii_ok(q) else []


def tag_query(T, i):
    word = lambda k: ('quoted' if T[k].q else T[k].lw) if 0 <= k < len(T) else 'edge'
    return 't %s p %s n %s pp %s nn %s first %d last %d' % (word(i),word(i-1),word(i+1),word(i-2),word(i+2),i==0,i==len(T)-1)


def extract(q, threshold):
    T = tokens(q)
    if not T or len(T) > 64:
        return None
    tags = [predict(load()['tag'], tag_query(T, i)) for i in range(len(T))]
    labs = [TAGS[p] for p, _ in tags]
    if not any(l != 'O' for l in labs) or min(m for _, m in tags) < threshold:
        return None
    spans = {}
    for role, allowed in (('text', ('B','I')), ('X', ('X',)), ('Y', ('Y',))):
        ix = [i for i, l in enumerate(labs) if l in allowed]
        if not ix:
            continue
        if ix != list(range(ix[0], ix[-1]+1)):
            return None
        if role == 'text' and (labs[ix[0]] != 'B' or any(labs[i] != 'I' for i in ix[1:])):
            return None
        A = [T[i] for i in ix]
        if any(t.q for t in A) and len(A) != 1:
            return None
        spans[role] = (A[0].s, A[-1].e)
    if 'text' not in spans:
        return None
    return spans, min(m for _, m in tags)


def text(q, *, raw=False):
    """Only called after regex decline, on original user bytes. raw bypasses thresholds."""
    if not ps.ascii_ok(q) or ps.textops_guard(q):
        return None
    T = tokens(q)
    if any(not t.q and (t.lw in to.BLOCK or to.is_path(q[t.s:t.e])) for t in T):
        return None
    op, margin = heads(q)['op']
    if op == 'none' or (not raw and margin < THRESHOLDS['op']):
        return None
    parsed = extract(q, 0 if raw else THRESHOLDS['tag'])
    if parsed is None:
        return None
    spans, tm = parsed
    a, b = spans['text']
    literal = q[a:b]
    A = [t for t in T if a <= t.s and t.e <= b]
    if not literal or to.arg_text(q, A, op) != literal:
        return None
    arg = 0
    if op == 'repeat':
        numbers = [to.parse_num(t.lw) for t in T if not t.q and to.parse_num(t.lw)]
        numbers += [2 if t.lw == 'twice' else 3 for t in T if not t.q and t.lw in ('twice', 'thrice')]
        if len(numbers) != 1 or not 1 <= numbers[0] <= 10:
            return None
        arg = numbers[0]
        out = ' '.join([literal]*arg)
    elif op == 'replace':
        if not {'X','Y'} <= spans.keys():
            return None
        x, y = q[slice(*spans['X'])], q[slice(*spans['Y'])]
        if not x or x not in literal:
            return None
        out = literal.replace(x, y)
    else:
        if spans.keys() != {'text'}:
            return None
        if op == 'acronym' and len(literal.split()) < 2:
            return None
        out = to.do_op(op, literal)
    if not 0 < len(out) <= 255:
        return None
    return dict(op=op, output=out, span=[a,b], spans={k: list(v) for k, v in spans.items()}, margin=margin, tag_margin=tm, arg=arg)
