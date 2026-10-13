#!/usr/bin/env python3
"""KB4 stage 1: one streaming pass over the Simple English Wikipedia dump -> pages.jsonl.gz.
One line per main-namespace page: {"t": title, "r": redirect target|null, "n": full text length, "w": first WT_MAX chars of wikitext}.
Read-only on the dump. Independent of any other worker's extractor."""
import bz2, gzip, json, re, sys
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from kb4_extract import find_template, split_top
import xml.etree.ElementTree as ET

WT_MAX = int(__import__("os").environ.get("KB4_WT_MAX", 9000))
KEEP = {"date", "dates", "place", "location", "capital", "occupation", "birth_date", "death_date", "birth_place", "death_place",
        "born", "died", "name", "full_name", "birth_name", "start_date", "end_date", "formed", "dissipated", "population_total",
        "population", "subdivision_name", "subdivision_name1", "country", "state", "region", "conflict", "year", "began", "ended"}

def prune(wt):
    """drop refs/comments and oversized infobox params (images, long lists) so the lead survives the WT_MAX cut."""
    wt = re.sub(r"<!--.*?-->", "", wt, flags=re.S)
    wt = re.sub(r"<ref[^>/]*/>|<ref\b[^>]*>.*?</ref>", "", wt, flags=re.S | re.I)
    m = re.search(r"\{\{\s*infobox[ _]", wt, re.I)
    r = find_template(wt, r"infobox[ _]") if m else None
    if not r or not wt[m.start() + 2:].startswith(r[0]):
        return wt
    parts = split_top(r[0])
    keep = [parts[0]]
    for p in parts[1:]:
        k = p.split("=", 1)[0].strip().lower().replace(" ", "_") if "=" in p else ""
        if len(p) <= 300 or k in KEEP:
            keep.append(p[:1500])
    return wt[:m.start()] + "{{" + "|".join(keep) + "}}" + wt[m.start() + len(r[0]) + 4:]

def scan(dump, out):
    n = 0
    with (bz2.open(dump, "rb") if dump.endswith(".bz2") else open(dump, "rb")) as f, gzip.open(out, "wt", encoding="utf-8", compresslevel=3) as o:
        for _, e in ET.iterparse(f):
            if not e.tag.endswith("}page") and e.tag != "page":
                continue
            g = {c.tag.rsplit("}", 1)[-1]: c for c in e}
            if (g["ns"].text or "") == "0":
                rec = {"t": g["title"].text or "", "r": None, "n": 0, "w": ""}
                if "redirect" in g:
                    rec["r"] = g["redirect"].get("title", "").split("#")[0] or None
                else:
                    rev = g.get("revision")
                    tx = rev.find("{*}text") if rev is not None else None
                    wt = (tx.text or "") if tx is not None else ""
                    rec["n"], rec["w"] = len(wt), prune(wt)[:WT_MAX]
                o.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
            e.clear()
    return n

if __name__ == "__main__":
    print(scan(sys.argv[1], sys.argv[2]))
