#!/usr/bin/env python3
"""Build the KB4 knowledge index (typed answer-bearing records, alias keys, delete-index) from the Simple English
Wikipedia dump. Format: FORMAT-KB4.md. Run:  build_kb4.py [--pages P] [--dump D] [--out DIR] [--limit N]

stage 1 (kb4_scan.py): dump -> pages.jsonl.gz (title, redirect, length, pruned wikitext head)
stage 2 (here): per article typed fields (kb4_extract.py), keys, binary file. Source text is CC BY-SA 4.0."""
import argparse, collections, gzip, json, math, os, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_kb  # lead/definition cleaner shared with KB3 (same repo)
import kb4_extract as X
from kb import normalize, variants
from kb4 import CAND_MAX, ETYPE, KIND, KEY_MAX, PROV, REL, fnv1a, SECTOR

DEF_MAX = 110
KIND_BONUS = {0: 8, 1: 6, 2: 4, 3: -20}  # also used by retrieve4 (must match)
FZ_MIN_WORD, FZ_MAX_WORD = 4, 20  # KB3 used 5; 4-letter names (Pugh, Fakl-> Fall) were unrepairable
ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}
DAB = re.compile(r"\{\{\s*(disambig|disambiguation|dab|geodis|hndis|surname|given name)", re.I)


def prom_of(n):
    return min(63, int(4 * math.log2(1 + n / 32)))


def pad(n, a=SECTOR):
    return -n % a


def load(pages, limit=0):
    arts, reds = {}, {}
    with gzip.open(pages, "rt", encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            t = r["t"]
            if r["r"]:
                reds[t] = r["r"]
            elif not (t.lower().startswith("list of ") or t.endswith("(disambiguation)") or DAB.search(r["w"])):
                arts[t] = r
            if limit and len(arts) >= limit:
                break
    return arts, reds


def entity(title, r):
    """-> dict(title, etype, definition, fields {rel: (value, prov)}, missing set, n) or None"""
    wt = r["w"]
    lead = build_kb.extract_lead(wt)
    if len(lead) < build_kb.MIN_TEXT:  # same inclusion rule as KB3 (lead of >= 40 chars)
        return None
    d = build_kb.context_sentence(lead)
    et, f, expected, lead = X.extract(title, wt)
    d = d if len(d) <= DEF_MAX else d[:DEF_MAX].rsplit(" ", 1)[0].rstrip(" ,;:") + "."
    return dict(title=X.ascii_only(title), etype=et, definition=d, fields=f, expected=expected, n=r["n"], lead=lead)


def encode_record(eid, e):
    f = dict(e["fields"])
    miss = [r for r in e["expected"] if r not in f]
    out = None
    for cap in (60, 40, 24):
        body = bytearray()
        items = []
        for r in sorted(f, key=lambda x: REL[x]):
            v, prov = f[r]
            items.append((REL[r], PROV[prov] << 1, v[:cap].rstrip(" ,;").encode("ascii")))
        for r in sorted(miss, key=lambda x: REL[x]):
            items.append((REL[r], 1 | PROV["none"] << 1, b""))
        t = e["title"].encode("ascii")[:63]
        d = e["definition"].encode("ascii")
        body += struct.pack("<IBBB", eid, ETYPE[e["etype"]], prom_of(e["n"]), len(t)) + t + bytes([len(d)]) + d + bytes([len(items)])
        for rel, fl, v in items:
            body += bytes([rel, fl, len(v)]) + v
        if len(body) <= 510:
            out = bytes(body)
            break
    assert out, e["title"]
    pm = 1 | sum(1 << REL[r] for r in f)
    mm = sum(1 << REL[r] for r in miss)
    return struct.pack("<H", len(out)) + out, pm, mm


PERSON_ALIAS_PROM = 28  # given-name / family-name aliases only for well-covered people (article >= ~4.5k chars)


def keys_for(title, et, prom=0):
    """[(key, kind)] for one entity title"""
    ks = [(normalize(title), KIND["title"])]
    base = X.title_base(title)
    if base != title:
        ks.append((normalize(base), KIND["paren_base"]))
    k0 = ks[0][0]
    if k0.startswith("the "):
        ks.append((k0[4:], KIND["derived"]))
    if et == "person" and prom >= PERSON_ALIAS_PROM:
        w = normalize(base).split()
        if len(w) >= 2:
            sn = X.surname_from_name(X.ascii_only(base))
            for k in (w[0], normalize(sn) if sn else None):
                if k and len(k) >= 3 and k not in ("jr", "sr"):
                    ks.append((k, KIND["derived"]))
    if et == "event":
        w = normalize(base).split()
        if len(w) >= 2 and len(base) < 40:
            ar = [ROMAN.get(x, x) for x in w]
            if ar != w:
                ks.append((" ".join(ar), KIND["derived"]))
            for ws in (w, ar):
                ini = "".join(x if x.isdigit() or x in ROMAN else x[0] for x in ws if x not in ("of", "the", "and"))
                if len(ini) >= 3:
                    ks.append((ini, KIND["derived"]))
    return [(k, kd) for k, kd in ks if 0 < len(k) <= KEY_MAX]


def build(pages, out, source, lic="CC BY-SA 4.0", limit=0, aliases_path=None, entities_path=None,
          entity_fn=entity, record_fn=encode_record, version=4):
    arts, reds = load(pages, limit)
    ents = {}
    for i, (t, r) in enumerate(arts.items(), 1):
        e = entity_fn(t, r)
        if e:
            ents[t] = e
        if version == 41 and i % 25000 == 0:
            print('extracted', i, '/', len(arts), flush=True)
    # reverse capital: "Paris is the capital of France" fills France.capital when the infobox gave none
    by_key = {normalize(t): t for t in ents}
    nrev = 0
    for t, e in ents.items():
        rc = X.capital_reverse(e["lead"]) if e["etype"] in ("place", "other") else None
        if rc:
            tgt = by_key.get(normalize(rc[0]))
            if tgt and ents[tgt]["etype"] == "country" and "capital" not in ents[tgt]["fields"]:
                ents[tgt]["fields"]["capital"] = (rc[1], "lead_reverse")
                nrev += 1
    order = sorted(ents, key=lambda t: (-ents[t]["n"], t))
    tarea, recoff, meta = bytearray(), {}, {}
    for eid, t in enumerate(order):
        rec, pm, mm = record_fn(eid, ents[t])
        recoff[t], meta[t] = len(tarea), (pm, mm)
        tarea += rec
    cands = collections.defaultdict(dict)  # key -> {title: kind}

    def add(key, t, kind):
        if key and (t not in cands[key] or kind < cands[key][t]):
            cands[key][t] = kind
    for t, e in ents.items():
        for k, kd in keys_for(t, e["etype"], prom_of(e["n"])):
            add(k, t, kd)
    nred = 0
    for rt, tgt in reds.items():
        tgt = reds.get(tgt, tgt)
        if tgt in ents:
            k = normalize(rt)
            if 0 < len(k) <= KEY_MAX:
                add(k, tgt, KIND["redirect"]); nred += 1
    keymap = {}
    for k, d in cands.items():
        lst = sorted(d.items(), key=lambda x: (-(KIND_BONUS[x[1]] + prom_of(ents[x[0]]["n"])), x[0]))[:CAND_MAX]
        keymap[k] = [(recoff[t], kd, prom_of(ents[t]["n"]), ETYPE[ents[t]["etype"]], meta[t][0], meta[t][1], t) for t, kd in lst]
    nk = len(keymap)
    nb = 1
    while nb * 3 < nk:
        nb *= 2
    buckets = [[] for _ in range(nb)]
    for k, lst in keymap.items():
        kb = k.encode("ascii")
        h = fnv1a(kb)
        buckets[h & (nb - 1)].append((h, kb, lst))
    karea, offs = bytearray(), []
    for b in buckets:
        offs.append(len(karea))
        for h, kb, lst in sorted(b, key=lambda x: (x[0], x[1])):
            karea += struct.pack("<IBB", h, len(kb), len(lst)) + kb
            for ro, kd, pr, et, pm, mm, _ in lst:
                karea += struct.pack("<IBBBHH", ro, kd, pr, et, pm, mm)
    offs.append(len(karea))
    btab = struct.pack("<%dI" % len(offs), *offs)
    bt_off = SECTOR
    k_off = bt_off + len(btab) + pad(len(btab))
    r_off = k_off + len(karea) + pad(len(karea))
    # fuzzy section (word-level delete-1 index, identical to KB3)
    freq = collections.Counter(w for k in keymap for w in set(k.split())
                               if FZ_MIN_WORD <= len(w) <= FZ_MAX_WORD and not w.isdigit())
    fwords = sorted(freq, key=lambda w: (-freq[w], w))
    fw_area, fw_off = bytearray(), {}
    for w in fwords:
        fw_off[w] = len(fw_area)
        fw_area += bytes([len(w)]) + w.encode("ascii")
    ents_f = [(fnv1a(v.encode("ascii")), fw_off[w]) for w in fwords for v in variants(w)]
    fnb = 1
    while fnb * 4 < len(ents_f):
        fnb *= 2
    fb = [[] for _ in range(fnb)]
    for h, wo in ents_f:
        fb[h & (fnb - 1)].append((h, wo))
    fent, foffs = bytearray(), []
    for b in fb:
        foffs.append(len(fent))
        for h, wo in sorted(b):
            fent += struct.pack("<II", h, wo)
    foffs.append(len(fent))
    fbtab = struct.pack("<%dI" % len(foffs), *foffs)
    r_end = r_off + len(tarea)
    fw_abs = r_end + pad(r_end)
    fbt_abs = fw_abs + len(fw_area) + pad(len(fw_area))
    fent_abs = fbt_abs + len(fbtab) + pad(len(fbtab))
    size = fent_abs + len(fent)
    src = ("%s | %s | typed fields + definition sentence per article, ASCII-transliterated" % (source, lic)).encode("ascii")
    hdr = b"KB4\0" + struct.pack("<7I", version, nb, nk, len(order), bt_off, k_off, r_off) + struct.pack("<I", size) + \
        struct.pack("<6I", fnb, fbt_abs, fent_abs, fw_abs, len(ents_f), len(fwords)) + struct.pack("<I", FZ_MIN_WORD) + src
    assert len(hdr) <= SECTOR and hdr[:4] == b"KB4\0"
    with open(out, "wb") as f:
        f.write(hdr + bytes(SECTOR - len(hdr)))
        f.write(btab + bytes(pad(len(btab))))
        f.write(karea + bytes(pad(len(karea))))
        f.write(tarea + bytes(pad(r_end)))
        f.write(fw_area + bytes(pad(len(fw_area))))
        f.write(fbtab + bytes(pad(len(fbtab))))
        f.write(fent)
    assert os.path.getsize(out) == size
    if aliases_path:
        with open(aliases_path, "w") as f:
            for k, lst in sorted(keymap.items()):
                f.write("%s\t%s\n" % (k, "|".join("%s:%d" % (c[6], c[1]) for c in lst)))
    if entities_path:  # for probe generation / audits only (never shipped)
        redir_keys = collections.defaultdict(list)
        for k, d in sorted(cands.items()):
            for t, kd in d.items():
                if kd == KIND["redirect"]:
                    redir_keys[t].append(k)
        with gzip.open(entities_path, "wt") as f:
            for eid, t in enumerate(order):
                e = ents[t]
                f.write(json.dumps(dict(eid=eid, title=e["title"], etype=e["etype"], n=e["n"], definition=e["definition"],
                                        fields={r: v for r, v in e["fields"].items()},
                                        missing=[r for r in e["expected"] if r not in e["fields"]],
                                        aliases=redir_keys[t][:12],
                                        **({"sources": e["sources"], "conflicts": e["conflicts"]} if "sources" in e else {}))) + "\n")
    # ---- stats ----
    cov = collections.Counter()
    by_type = collections.Counter(e["etype"] for e in ents.values())
    prov = collections.Counter()
    miss = collections.Counter()
    for e in ents.values():
        for r, (v, p) in e["fields"].items():
            cov[r] += 1
            prov["%s/%s" % (r, p)] += 1
        for r in e["expected"]:
            if r not in e["fields"]:
                miss[r] += 1
    sizes = [offs[i + 1] - offs[i] for i in range(nb)]
    kinds = collections.Counter(c[1] for lst in keymap.values() for c in lst)
    return dict(n_entities=len(ents), n_articles=len(arts), n_redirects=len(reds), redirect_keys_added=nred, n_keys=nk,
                n_buckets=nb, file_size=size, key_area=len(karea), record_area=len(tarea), fuzzy_bytes=size - fw_abs,
                fuzzy_words=len(fwords), by_type=dict(by_type), field_present=dict(cov), field_missing_marker=dict(miss),
                provenance=dict(prov), reverse_capital=nrev, cand_kinds={KIND_NAME_[k]: v for k, v in kinds.items()},
                keys_multi_candidate=sum(len(l) > 1 for l in keymap.values()), keys_at_cap=sum(len(l) == CAND_MAX for l in keymap.values()),
                max_bucket_bytes=max(sizes), avg_bucket_bytes=sum(sizes) / nb, pct_buckets_le_512=100 * sum(s <= SECTOR for s in sizes) / nb,
                avg_record_bytes=len(tarea) / max(1, len(order)))


KIND_NAME_ = {v: k for k, v in KIND.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", required=True)
    ap.add_argument("--meta", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "meta.json"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    m = json.load(open(a.meta))
    os.makedirs(a.out, exist_ok=True)
    stats = build(a.pages, os.path.join(a.out, "kb4.bin"),
                  "Simple English Wikipedia dump %s (%s) sha1 %s" % (m["last_modified"], m["url"], m["sha1"]),
                  limit=a.limit, aliases_path=os.path.join(a.out, "aliases.tsv"),
                  entities_path=os.path.join(a.out, "entities.jsonl.gz"))
    stats["dump_sha1"] = m["sha1"]
    stats["dump_last_modified"] = m["last_modified"]
    open(os.path.join(a.out, "ATTRIBUTION.txt"), "w").write(
        "Text and facts in kb4.bin are derived from Simple English Wikipedia articles by Simple English Wikipedia\n"
        "contributors, licensed CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/).\n"
        "Source: %s\nDump date (Last-Modified): %s\nDump sha1: %s\n"
        "The material was modified: per article one definition sentence (<= 110 chars) and short typed fields\n"
        "(dates, places, surname, capital, occupation, population) parsed from the infobox or lead text, markup\n"
        "removed, transliterated to ASCII. Each field records whether it came from the infobox, the lead text or the title.\n"
        % (m["url"], m["last_modified"], m["sha1"]))
    json.dump(stats, open(os.path.join(a.out, "build_stats.json"), "w"), indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
