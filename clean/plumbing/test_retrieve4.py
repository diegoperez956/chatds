"""Parity (Python reference vs C), corrupt-file fuzz under ASan, I/O fault injection and word-list sync for KB4 retrieval."""
import os, random, struct, subprocess, sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "corpus", "kb"))
import build_kb4, kb4, kb4_scan, retrieve4 as R  # noqa: E402

EXE = os.path.join(HERE, "build", "test-retrieve4")
FIX = os.path.join(ROOT, "corpus", "kb", "fixtures", "kb4_mini.xml")
REAL = os.environ.get("CHATDS_KB4", "")
PROBES = os.environ.get("CHATDS_KB4_PROBES", "")
STATUS = list(R.STATUSES)

TEMPL = ["what is {n}", "what did {n} do", "what does {n} do", "when did {n} die", "when was {n} born", "where was {n} born", "what year was {n} born", "who is {n}", "tell me about {n}", "define {n}", "when was {n}", "what years {n}", "when was {n} born",
         "where was {n} born", "when did {n} die", "where did {n} die", "{n} last name", "what is the capital of {n}", "{n} capital",
         "where is {n}", "what is the population of {n}", "what was {n} job", "how old is {n}", "how long did {n} last",
         "what year did {n} start", "{n} birthday", "explain {n}", "describe {n} please"]
NAMES = ["ww2", "wwii", "world war ii", "world war 2", "second world war", "world war i", "napoleon", "napoleon bonaparte", "michael jackson",
         "michael johnson", "python", "mercury", "france", "paris", "lutetia", "albert einstein", "plato", "barack obama", "battle of hastings",
         "mount everest", "ada lovelace", "isaac newton", "leonardo da vinci", "tokyo", "titanic", "the titanic", "hurricane katrina", "zorblax",
         "world war", "michael", "jackson", "einstein", "the battle of hastings"]
GATED = ["print hello", "what is 5 + 3", "hello there", "", "   ", "what is five plus six", "ls -la", "x = 1", "it's what it's", "what's 12*7",
         "what is the", "capital", "last name", "when", "what are you", "a " * 40, "what is " + "x" * 130, "who is " + " ".join("ab" for _ in range(40))]


def typo(rng, w):
    if len(w) < 2:
        return w
    i = rng.randrange(len(w))
    k = rng.randrange(4)
    if k == 0:
        return w[:i] + w[i + 1:]
    if k == 1:
        return w[:i] + rng.choice("abcdefghijklmnopqrstuvwxyz") + w[i + 1:]
    if k == 2 and i + 1 < len(w):
        return w[:i] + w[i + 1] + w[i] + w[i + 2:]
    return w[:i] + rng.choice("abcdefghijklmnopqrstuvwxyz") + w[i:]


def make_queries(names, n, seed):
    rng = random.Random(seed)
    qs = []
    while len(qs) < n:
        nm = rng.choice(names)
        q = rng.choice(TEMPL).replace("{n}", nm)
        r = rng.random()
        if r < 0.3:
            ws = q.split()
            j = rng.randrange(len(ws))
            ws[j] = typo(rng, ws[j])
            q = " ".join(ws)
        elif r < 0.4:
            q = q.upper()
        elif r < 0.5:
            q = q + rng.choice(["?", "!", ".", " ?!"])
        elif r < 0.6:
            ws = q.split()
            rng.shuffle(ws)
            q = " ".join(ws)
        elif r < 0.7:
            ws = q.split()
            q = " ".join(ws[:max(1, len(ws) - 1)])
        elif r < 0.78:
            q = q + " and " + rng.choice(names)
        elif r < 0.85:
            q = rng.choice(GATED)
        elif r < 0.90:
            q = rng.choice(["hi, ", "thanks now ", "good morning, ", "hello "]) + q
        elif r < 0.94:
            q = q.replace("born", rng.choice(["borrn", "bon", "bonr"])).replace("capital", "captial").replace("die", "dei").replace("last name", "last nmae")
        elif r < 0.98:
            ws = q.split()
            ix = [i for i, x in enumerate(ws) if len(x) >= 5]
            for i in rng.sample(ix, min(2, len(ix))):
                ws[i] = typo(rng, ws[i])
            q = " ".join(ws)
        else:
            q = q.replace("die", "pass away").replace("when", "how many people live in")
        qs.append(q)
    return qs


def kbhash(keys):
    h = 2166136261
    for k in keys:
        for c in (k + "\n").encode():
            h = ((h ^ c) * 16777619) & 0xFFFFFFFF
    return h


def py_rows(path, queries, k, expand, fault=None, routed=False):
    kb = kb4.KB4(path)
    rows = []
    for q in queries:
        kb.sector = None
        kb.fault_after = None if fault is None else kb.sector_reads + fault
        r = R.retrieve(kb, q, k=k, expand=expand, routed=routed)
        lg = r.log
        st = r.status
        rec = r.rec
        shown = st in ("answer_present", "field_missing", "ambiguous")
        if st in ("io_error", "corrupt_kb"):
            rows.append([st])
            continue
        rows.append([st, "-" if (st == "gated" or r.field is None) else r.field, str(rec["eid"] if shown else 0), rec["title"] if shown else "",
                     r.value or "", r.context, str(lg["sector_reads"]), str(lg["lookups"]), str(len(lg["keys_tried"])), str(kbhash(lg["keys_tried"])),
                     str(lg["candidates"]), str(int(lg["expansion"])), lg["fallback_reason"] or "",
                     str(kb4.PROV.get(r.prov, 0)),
                     str(rec.get('field_sources', {}).get(r.field, {}).get('sid', 65535) if st == 'answer_present' else 0),
                     str(int(rec.get('field_sources', {}).get(r.field, {}).get('conflict', False))) if st == 'answer_present' else '0',
                     str(rec.get('field_sources', {}).get(r.field, {}).get('end_sid', 65535) if st == 'answer_present' else 0)])
    return rows


def c_rows(path, queries, k, expand, fault=None, routed=False, timeout=300):
    args = [EXE, path, str(k), str(int(expand)), str(-1 if fault is None else fault), str(int(routed))]
    p = subprocess.run(args, input="\n".join(queries) + "\n", capture_output=True, text=True, timeout=timeout)
    assert p.returncode == 0 and not p.stderr, p.stderr[:2000]
    lines = p.stdout.split("\n")
    assert lines[-1] == ""
    lines = lines[:-1]
    if lines and lines[0].startswith("open_failed"):
        return None, lines[0], None
    meta = lines[0].split("\t")
    out = [l.split("\t") for l in lines[1:]]
    out = [r[:1] if r[0] in ("io_error", "corrupt_kb") else r for r in out]  # fields after a runtime error are not defined
    return out, meta, p


@pytest.fixture(scope="session", autouse=True)
def build_c():
    subprocess.check_call(["make", "-s", "-f", "Makefile.kb4", "build/test-retrieve4"], cwd=HERE)


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    d = tmp_path_factory.mktemp("kb4c")
    kb4_scan.scan(FIX, str(d / "p.jsonl.gz"))
    build_kb4.build(str(d / "p.jsonl.gz"), str(d / "k.bin"), "test")
    return str(d / "k.bin")


def compare(path, queries, k, expand, routed=False):
    a = py_rows(path, queries, k, expand, routed=routed)
    b, meta, _ = c_rows(path, queries, k, expand, routed=routed)
    assert len(a) == len(b) == len(queries)
    bad = [(q, x, y) for q, x, y in zip(queries, a, b) if x != y]
    assert not bad, "%d/%d differ, first: %r" % (len(bad), len(queries), bad[:3])
    return meta


def test_parity_mini_2400_queries(mini):
    qs = make_queries(NAMES, 2400, 7)
    assert len(set(qs)) >= 1500
    for k, e in ((3, True), (1, False), (5, True), (2, False)):
        meta = compare(mini, qs, k, e)
    meta = compare(mini, qs, 3, True, routed=True)
    assert int(meta[1]) + int(meta[3]) <= 4096  # ctx + kb handle: the retrieval's working RAM (result is separate)


def test_all_statuses_exercised(mini):
    qs = make_queries(NAMES, 2400, 7)
    seen = {r[0] for r in py_rows(mini, qs, 3, True)}
    assert {"answer_present", "field_missing", "ambiguous", "no_match", "gated"} <= seen


@pytest.mark.skipif(not os.path.exists(REAL), reason="real KB4 not built")
def test_parity_real_kb():
    import json
    qs = []
    if os.path.exists(PROBES):
        qs = [json.loads(l)["question"] for l in open(PROBES)]
    rng = random.Random(3)
    qs = qs + make_queries(["ww2", "napoleon", "michael jackson", "python", "france", "mercury", "paris", "george washington", "mount everest"], 800, 11)
    rng.shuffle(qs)
    qs = qs[:3000]
    assert len(qs) >= 3000
    compare(REAL, qs, 3, True)
    compare(REAL, qs[:1200], 1, False)


def test_io_fault_injection(mini):
    qs = ["when was ww2", "napoleon last name", "who was michael jacjson", "what is the capital of france", "hello"]
    for fault in (0, 1, 2, 5):
        a = py_rows(mini, qs, 3, True, fault)
        b, _, _ = c_rows(mini, qs, 3, True, fault)
        assert a == b, (fault, a, b)
        assert a[0][0] == "io_error" if fault == 0 else True
    assert py_rows(mini, ["hello"], 3, True, 0)[0][0] == "gated"  # gated questions never touch the card


def mutate(data, rng):
    b = bytearray(data)
    kind = rng.randrange(6)
    if kind == 0:
        return bytes(b[:rng.randrange(len(b))])
    hot = (struct.unpack_from("<I", b, 20)[0], struct.unpack_from("<I", b, 24)[0], struct.unpack_from("<I", b, 28)[0], 0, 8, 20, 24, 28, 32, 36, 40, 44, 48)
    for _ in range(rng.randrange(1, 9)):
        at = rng.choice(hot) + rng.randrange(0, 64) if rng.random() < 0.6 else rng.randrange(len(b))
        if at < len(b):
            b[at] = rng.choice([0, 0xFF, 0x7F, 0x80, rng.randrange(256)])
    if kind == 5:
        b += bytes(rng.randrange(256) for _ in range(rng.randrange(1, 600)))
    return bytes(b)


def test_corrupt_fuzz_asan(mini, tmp_path):
    data = open(mini, "rb").read()
    rng = random.Random(99)
    qs = make_queries(NAMES, 60, 5)
    n_open_fail = n_runtime_err = 0
    for i in range(250):
        p = tmp_path / "f.bin"
        p.write_bytes(mutate(data, rng))
        b, meta, _ = c_rows(str(p), qs, 3, True)  # asserts exit 0 and empty stderr: no ASan/UBSan report
        if b is None:
            n_open_fail += 1
            continue
        assert all(r[0] in STATUS for r in b)
        n_runtime_err += any(r[0] in ("corrupt_kb", "io_error") for r in b)
        try:  # the Python reader must also only ever fail with KB4Error
            py_rows(str(p), qs, 3, True)
        except kb4.KB4Error:
            pass
    assert n_open_fail > 10 and n_runtime_err > 5
