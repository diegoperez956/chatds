"""Opt-in entity resolver ER1. Baseline remains untouched when disabled.
Limits: 32 words, 8 entities, 24 extra keys, 8 short-word signatures.
"""
import itertools
import os
import re
from kb import normalize
from kb4 import KB4Error, KEY_MAX
from entres_index import EntIndex

EXTRA_STOP = set('abt bout u ur ya pls plz wanna gonna cuz guy gal dude person thing stuff info information know anyone anybody someone somebody actually really basically quick question could would got gimme lemme reckon uh um definition get fought take'.split())
FOLD = {'abt':'about', 'bout':'about', 'u':'you', 'ur':'your', 'ya':'you', 'pls':'please', 'plz':'please',
        'whos':'who', 'whats':'what', 'wot':'what', 'whut':'what', 'whatsup':'what',
        'one':'1','two':'2','three':'3','four':'4','five':'5','six':'6','seven':'7','eight':'8','nine':'9','ten':'10',
        'ii':'2','iii':'3','iv':'4','v':'5','vi':'6','vii':'7','viii':'8','ix':'9','x':'10',
        'wwii':'ww2','wwiii':'ww3','wwi':'ww1'}


def content(w, stop):
    # 'us' as a country abbreviation, except the pronoun in request frames.
    return [int(x not in stop or x == 'us' and (i == 0 or w[i-1] not in {'tell','give','show'})) for i,x in enumerate(w)]


def normalized(q):
    q = re.sub(r"(?i)([a-z])'s\b", r'\1', q)
    q = re.sub(r"(?i)([a-z]s)'(?=\s|[?.!,]|$)", r'\1', q)
    w = normalize(q).split()
    return q, [FOLD.get(x, x) for x in w]


def index_for(kb):
    path = os.environ.get('CHATDS_ENTRES_INDEX')
    if not path:
        path = kb.f.name + '.entres'
    if not hasattr(kb, '_entres_index'):
        kb._entres_index = EntIndex(path, kb)
    return kb._entres_index


def retrieve(kb, question, k=3, expand=True, ambig=True, routed=False, index=None):
    import retrieve4 as R
    r = R.Result()
    log = r.log = dict(question=question, keys_tried=[], candidates=0, sector_reads=0, lookups=0,
                      chosen_field=None, fallback_reason=None, expansion=False, k=k, relation=None, gate=None,
                      policy='entres_v1')
    kb.sector_reads_start, kb.lookups_start = kb.sector_reads, kb.lookups
    idx = None
    s0 = l0 = 0
    def fin():
        if idx is not None:
            log['index_sector_reads'] = idx.sector_reads - s0
            kb.sector_reads += idx.sector_reads - s0
            kb.lookups += idx.lookups - l0
        return R._fin(kb, r)
    try:
        clean, w = normalized(question)
        if len(question) > R.QUESTION_MAX or len(w) > R.MAX_WORDS:
            r.status, log['fallback_reason'] = 'gated', 'too_long'
            return fin()
        # Arithmetic/code/conversation gate sees original number words, not folding.
        g = R.gate(clean, normalize(clean).split())
        log['gate'] = g
        if g:
            r.status, log['fallback_reason'] = 'gated', g
            return fin()
        idx = index if index is not None else index_for(kb)
        s0, l0 = idx.sector_reads, idx.lookups
        ent = content(w, R.ENT_STOP | EXTRA_STOP)
        wc = R._cue_typos(kb, w, ent)
        ent = content(wc, R.ENT_STOP | EXTRA_STOP)
        # Casual frames may bypass only the cue test, never the safety gate.
        casual = bool(set(normalize(clean).split()) & {'tell','know','gimme','lemme'})
        if not routed and not R.cue_ok(wc) and not casual:
            r.status, log['fallback_reason'] = 'gated', 'no_cue'
            return fin()
        rel = R.parse_relation(wc)
        r.field, r.relation, log['relation'] = rel, R.VOCAB[rel], rel
        glue = {'kind','work'} if rel == 'occupation' else {'big','large'} if rel == 'quantity' else set()
        ent = [0 if x in glue else e for x,e in zip(wc,ent)]
        cue_entity = sum(ent) == 0
        if cue_entity:
            ent = [int(not ((x in R.STOP or x in R.FILL or x in EXTRA_STOP) and x not in R.REL_WORDS)) for x in w]
        total = sum(ent)
        pool, order = [], [0]
        def lookup(key, cover, typo=0):
            log['keys_tried'].append(key)
            main = kb.lookup(key) if not key.startswith('~') else []
            R._add(pool, main, cover, typo, key, order)
            side = idx.lookup(key)
            if not any(c.kind == 0 for c in main):
                R._add(pool, side, cover, typo, key, order)
            for p in pool:
                p.pop = max(getattr(p, 'pop', 0), max((c.pop for c in side if c.recoff == p.c.recoff), default=0))
                if p.key == key:
                    p.weak = 0 if any(c.recoff == p.c.recoff and c.kind <= 2 for c in main) else min((c.weak for c in side if c.recoff == p.c.recoff), default=int(p.c.kind == 3 and cover == 1))
                    if key.startswith('~'):
                        p.weak = 1
            return main or side
        if total and not cue_entity:
            tried = 0
            for i,n,c in R.grams(ent,total):
                if tried >= R.MAX_KEYS:
                    break
                key = ' '.join(w[i:i+n])
                if len(key) <= KEY_MAX and not (n == 1 and len(w[i]) < 3):
                    tried += 1
                    got = lookup(key,c)
                    if got and c == total:
                        break
        # Compact stop/filler-separated content, then bounded order permutations.
        ew = [w[i] for i in range(len(w)) if ent[i]]
        extra = []
        def offer(key, cover, typo=0):
            if 0 < len(key) <= KEY_MAX and (key,cover,typo) not in extra:
                extra.append((key,cover,typo))
        if 1 <= len(ew) <= 4:
            offer(' '.join(ew),total)
            offer(' '.join(reversed(ew)),total)
            for perm in itertools.islice(itertools.permutations(ew),12):
                offer(' '.join(perm),total)
            # Conservative plural folding is an alternative, never overwrites titles.
            folded = [x[:-3]+'y' if len(x)>4 and x.endswith('ies') else x[:-1] if len(x)>3 and x.endswith('s') and not x.endswith(('ss','us','is')) else x for x in ew]
            if folded != ew:
                offer(' '.join(folded),total,1)
        for x in ew:
            if len(x) >= 3:
                offer(x,1)
        protected = any(p.cover == total and p.typo == 0 and not p.weak and p.c.kind <= 2 for p in pool)
        if not protected:
            for key,cover,typo in extra[:24]:
                if cover == total and key not in log['keys_tried']:
                    lookup(key,cover,typo)
        # Existing bounded typo machinery runs on compacted content too.
        if expand and total and not any(p.cover == total for p in pool):
            log['expansion'] = True
            R._expand(kb,w,ent,total,pool,order,log,cue_entity)
            if not any(p.cover == total for p in pool):
                R._expand(kb,ew,[1]*len(ew),total,pool,order,log,cue_entity)
            for p in pool:
                if not hasattr(p,'pop'):
                    p.pop, p.weak = 0, int(p.c.kind == 3)
            # Up to eight delete signatures for short source aliases. Always weak.
            sig = []
            for x in ew:
                if 2 <= len(x) <= 4:
                    for v in [x] + [x[:i]+x[i+1:] for i in range(len(x))]:
                        if '~'+v not in sig:
                            sig.append('~'+v)
            if not any(p.cover == total for p in pool):
                for key in sig[:8]:
                    lookup(key,1,1)
        if not any(p.cover == total for p in pool):
            for key,cover,typo in extra[:24]:
                if cover < total and key not in log['keys_tried']:
                    lookup(key,cover,typo)
        log['candidates'] = len(pool)
        if not pool:
            r.status, log['fallback_reason'] = 'no_match', 'no_candidate'
            return fin()
        for p in pool:
            p.pop = getattr(p,'pop',0)
            p.weak = getattr(p,'weak',int(p.c.kind == 3))
            p.s1 = R._s1(p,total)
            p.s2 = p.s1 + R._rel_score(p,rel)
        # Field availability must not select a different identity for weak aliases.
        ranked = sorted(pool, key=lambda p: (-p.s1,-p.pop,p.ord))[:max(2,k)]
        ranked.sort(key=lambda p: (-(p.s1 if p.weak else p.s2),-p.pop,p.ord))
        best = ranked[0]
        second = ranked[1] if len(ranked)>1 else None
        gap = (best.s1 + best.pop) - (second.s1 + second.pop) if second else 999
        close = second is not None and second.cover == best.cover and (best.s1 if best.weak else best.s2) - (second.s1 if second.weak else second.s2) <= R.AMBIG_GAP and best.pop - second.pop < 24
        floor = best.cover < total or best.s1 < 500 or best.weak and (best.pop < 16 or gap < 32 or best.typo)
        st = 'ambiguous' if ambig and (close or floor) else 'ok'
        alts = [second.c.recoff] if st == 'ambiguous' and second else []
        R._answer(kb,r,best,st,alts,rel,log)
        # c14 dialogue rec_off() reopens chosen_key in the base KB. Keep that
        # compatibility key canonical; retain the actual alias route separately.
        log['matched_key'] = best.key
        log['chosen_key'] = normalize(r.rec['title'])
        if st == 'ambiguous' and floor:
            log['fallback_reason'] = 'confidence_floor'
        log['confidence'] = dict(coverage=best.cover,total=total,popularity=best.pop,weak=bool(best.weak))
        return fin()
    except (KB4Error, OSError) as e:
        r.status = 'io_error' if isinstance(e,OSError) or e.kind == 'io' else 'corrupt_kb'
        log['fallback_reason'] = str(e)
        return fin()
