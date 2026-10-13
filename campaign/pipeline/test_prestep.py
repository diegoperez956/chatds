"""Parity (C vs Python reference) + sanitizer fuzz + behaviour checks for prestep (style, calc parser, textops guard, dialogue).
Run: pytest -q campaign/pipeline/test_prestep.py"""
import pathlib, random, subprocess, sys
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (HERE, ROOT / "corpus"):
    sys.path.insert(0, str(p))
import prestep as ps, textops as to, gen_textops_negatives as neg, gen_textops_requests as gen  # noqa: E402
import chatds_runtime as rt  # noqa: E402

PL = ROOT / "clean" / "plumbing"
BIN = PL / "build" / "test-prestep"


def build():
    BIN.parent.mkdir(exist_ok=True)
    subprocess.run(["cc", "-std=c99", "-O1", "-g", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-fno-sanitize-recover=all", "-I" + str(PL), "-I" + str(ROOT / "clean/include"), str(PL / "prestep.c"), str(PL / "textops.c"),
                    str(PL / "calc.c"), str(PL / "test_prestep.c"), "-o", str(BIN)], check=True)


def run_c(cmds):
    p = subprocess.run(["nice", "-n", "19", str(BIN)], input=("".join(c + "\n" for c in cmds)).encode("latin-1"), capture_output=True, check=True)
    return p.stdout.decode("latin-1").split("\n")[:-1]


def dump(st):
    return "%s|%s|%s|%s|%d,%d|%d|%d|%d|%d|%d" % (st["entity"], st["answer"], st["lastq"], st["term"], st["cand"][0], st["cand"][1], st["ncand"],
                                                   st["pend"], st["task"], st["style"], st["ttl"])


def py_style(q):
    r = ps.style_detect(q)
    return "-" if not r else "%d\t%d\t%s" % ({"wrap": 1, "prefix": 2, "suffix": 3, "literal": 4, "free": 5}[r[0]], r[1], r[2])


def py_calc(q):
    e = ps.calc_parse(q)
    if e is None:
        return "-"
    a = ps.calc_answer(q, rt.apply_calc)
    return "%s\t%s" % (e, a if a else "-")


def py_guard(q):
    g = ps.textops_guard(q)
    r = None if g else to.textops(q)
    return "%d\t%s\t%s" % (g, r[0], r[1]) if r else "%d\t-" % g


def py_subst(ent, q):
    r = ps.dlg_subst_pronoun(q, ent, __import__("retrieve4").ENT_STOP)
    return r if r else "-"


# ------------------------------------------------------------------ generators (own phrasings; never dev/calib)
INNER = ["whats the capital of peru", "when did mozart die", "what is 12 times 12", "hello world", "who is ada lovelace", "capital of chile?", "tell me a fact",
         "what is the weather", "reverse hello", "explain recursion", "how many days in a week", "i like apples"]
STY = ["all caps", "uppercase", "upper case", "caps", "capital letters", "capitals", "lowercase", "lower case", "title case", "no caps", "small letters"]
VERBS = ["answer", "reply", "respond", "say", "speak", "talk", "write", "type", "use", "be", "go", "switch to"]


def style_requests(n, seed):
    r = random.Random(seed)
    out = set()
    pre = ["", "", "please ", "hey, ", "ok so ", "can you ", "from now on ", "hi "]
    post = ["", "", " from now on", " please", " only", " pls"]
    while len(out) < n:
        s, v, i = r.choice(STY), r.choice(VERBS), r.choice(INNER)
        f = r.randrange(17)
        q = [
            "%s in %s: %s" % (v, s, i), "%s in %s %s" % (v, s, i), "%s in %s only: %s" % (v, s, i), "%s to me in %s%s" % (v, s, r.choice(post)),
            "%s in %s%s" % (v, s, r.choice(post)), "%s: %s" % (s, i), "%s in %s" % (i, s), "%s (in %s)" % (i, s), "say %s in %s" % (r.choice(["hi", "hello there", '"good night"', "it"]), s),
            "in %s please, %s" % (s, i), "%s (reply in %s)" % (i, s), "%s (%s answer please)" % (i, s), "say %s with %s" % (r.choice(["hi", "stay calm"]), s),
            "give me %s all %s" % (r.choice(["HELLO THERE", "ok"]), s), "shout %s" % r.choice(["hello", "the quick brown fox", "it"]),
            "always answer without %s" % r.choice(["capitals", "caps", "capital letters"]), "only use %s when you talk to me" % s,
        ][f]
        out.add((r.choice(pre) + q + r.choice(["", "", "?", "."])).strip())
    return sorted(out)


NW = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
      "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "and", "point"]
OPW = ["plus", "minus", "times", "divided by", "multiplied by", "over", "mod", "take away", "x", "+", "-", "*", "/", "%", "squared", "percent of", "% of", "of",
       "half", "double", "twice", "triple", "quarter of", "to", "from", "by", "(", ")", "and"]


def typo(r, w):
    if len(w) < 4 or r.random() < 0.7:
        return w
    i = r.randrange(len(w) - 1)
    k = r.randrange(4)
    return (w[:i] + w[i + 1:] if k == 0 else w[:i] + w[i + 1] + w[i] + w[i + 2:] if k == 1 else w[:i] + "x" + w[i + 1:] if k == 2 else w[:i] + w[i] + w[i:])


def num(r):
    k = r.random()
    if k < 0.4:
        return str(r.choice([0, 1, 7, 12, 45, 100, 999, 1234, 1000000, 3.5, 0.25, 99999999999999]))
    if k < 0.5:
        return "1,000" if r.random() < 0.5 else "12,345,678"
    ws = []
    for w in r.choice([["five"], ["twenty", "three"], ["one", "hundred", "and", "five"], ["two", "thousand"], ["ninety", "nine"], ["fifteen"], ["three", "point", "five"],
                       ["one", "hundred", "twenty", "one"], ["zero"], ["six", "hundred", "thousand"]]):
        ws.append(typo(r, w))
    return " ".join(ws)


def calc_requests(n, seed):
    r = random.Random(seed)
    out = set()
    pre = ["", "", "what is ", "whats ", "calculate ", "how much is ", "ok so what is ", "hi, ", "thanks, now ", "compute "]
    post = ["", "", "?", " please", " equals", "."]
    while len(out) < n:
        k = r.randrange(17)
        a, b, c = num(r), num(r), num(r)
        o1, o2 = typo(r, r.choice(OPW[:9])), r.choice(OPW[:9])
        q = [
            "%s %s %s" % (a, o1, b), "%s %s %s %s %s" % (a, o1, b, o2, c), "(%s %s %s) %s %s" % (a, o1, b, r.choice(OPW[:9]), c), "half of %s" % a, "%s %% of %s" % (a, b),
            "%s percent of %s" % (a, b), "%s squared" % a, "%s cubed" % a, "square of %s" % a, "cube of %s plus %s" % (a, b), "remainder when %s is divided by %s" % (a, b), "remainder of %s by %s" % (a, b),
            "add %s and %s" % (a, b), "subtract %s from %s" % (a, b), "double %s" % a,
            "%s" % " ".join(r.choice(NW + OPW + ["5", "x", "write", "python"]) for _ in range(r.randint(2, 8))), "write a python function that returns %s %s %s" % (a, o1, b),
        ][k]
        out.add((r.choice(pre) + q + r.choice(post)).strip())
    return sorted(out)


def soup(n, seed):
    r = random.Random(seed)
    lists = [ps.LEADS, ps.VERBS_S, ps.PREPS, ps.STYLE_PH and [p for p, _ in ps.STYLE_PH], ps.NEG_ANY, ps.DLG_PUSH, ps.DLG_REPEAT, ps.DLG_PRON, NW, OPW,
             ["5", "12", "3.5", ":", ",", "'", '"', "?", "!", "in", "of", "the", "hi"]]
    out = []
    for _ in range(n):
        ws = [r.choice(r.choice(lists)) for _ in range(r.randint(1, 12))]
        out.append(" ".join(ws)[:127])
    return out


def all_inputs():
    qs = style_requests(1500, 11) + calc_requests(2500, 12) + soup(3000, 13) + neg.make(600, 14) + neg.POS + [q for q in gen.make(1500, 15) if "\n" not in q]
    return [q for q in qs if "\t" not in q and "\n" not in q]


def test_tables_current():
    assert (PL / "prestep_tab.h").read_text() == ps.emit_h(), "regenerate: python3 campaign/pipeline/prestep.py --emit-h > clean/plumbing/prestep_tab.h"


def test_parity():
    build()
    qs = all_inputs()
    kinds = [("S", py_style), ("C", py_calc), ("G", py_guard)]
    bad, hits = [], {}
    for tag, fn in kinds:
        cs = run_c(["%s\t%s" % (tag, q) for q in qs])
        assert len(cs) == len(qs)
        hits[tag] = 0
        for q, c in zip(qs, cs):
            want = fn(q)
            hits[tag] += want != "-" and not want.endswith("\t-")
            if want != c:
                bad.append((tag, q, want, c))
    assert not bad, bad[:10]
    assert hits["S"] > 300 and hits["C"] > 400, hits
    cs = run_c(["K\t%s" % q for q in qs])
    assert [str(ps.dlg_kind(q)) for q in qs] == cs
    ent = __import__("retrieve4").ENT_STOP
    qs2 = ["when was he born", "what year was she born", "where did they live", "when did he die", "what is his job", "who was her father", "what about him", "when was it built",
           "tell me about his job", "is she alive?", "and he", "what is his name: ok"] + qs[:400]
    cs = run_c(["P\tAda Lovelace\t%s" % q for q in qs2])
    assert [py_subst("Ada Lovelace", q) for q in qs2] == cs


def test_apply_style():
    build()
    texts = ["hello world", "Don't STOP me now", "calc(2+3) = 5", "a1b2 c3-d4", "", "x", "it's O'Neil's"]
    cmds = ["A\t%d\t%s" % (s, t) for s in (0, 1, 2, 3) for t in texts]
    assert run_c(cmds) == [ps.apply_style(s, t) for s in (0, 1, 2, 3) for t in texts]
    assert ps.apply_style(3, "don't stop") == "Don'T Stop"  # Python str.title() quirk, shared with textops


def test_dialogue_state_machine():
    build()
    r = random.Random(5)
    st, cmds, want = ps.dlg_new(), ["R"], [dump(ps.dlg_new())]
    for _ in range(3000):
        k = r.randrange(5)
        if k == 0:
            t, ent, a, lq = r.randrange(6), r.choice(["", "Ada", "x" * 60]), r.choice(["", "ok", "y" * 250]), r.choice(["q", "z" * 150])
            ok, keep = r.randrange(2) if r.random() < 0.2 else 1, r.randrange(2)
            cmds.append("N\t%d\t%s\t%s\t%s\t%d\t%d" % (t, ent, a, lq, ok, keep))
            ps.dlg_note(st, t, ent, a, lq, ok, keep)
            want.append(dump(st))
        elif k == 1:
            s = r.randrange(4)
            cmds.append("Y\t%d" % s)
            ps.dlg_set_style(st, s)
            want.append(dump(st))
        elif k == 2:
            cmds.append("T")
            want.append("take %d" % ps.dlg_style_take(st))
            want.append(dump(st))
        elif k == 3:
            cmds.append("R")
            ps.dlg_reset(st)
            want.append(dump(st))
        else:
            st["pend"], st["term"] = 0, ""  # pending fields are set by the integration layer, not by the pure helpers
            cmds.append("T")
            want.append("take %d" % ps.dlg_style_take(st))
            want.append(dump(st))
    assert run_c(cmds) == want


def test_fuzz():
    build()
    for seed in (1, 2, 3):
        p = subprocess.run(["nice", "-n", "19", str(BIN), "--fuzz", "30000", str(seed)], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr[-2000:]


def test_state_size():
    build()
    n = int(subprocess.run([str(BIN), "--size"], capture_output=True, text=True, check=True).stdout)
    assert n <= 512


# ------------------------------------------------------------------ behaviour
def test_style_examples():
    assert ps.style_detect("respond to me in all caps") == ("free", 1, "")
    assert ps.style_detect("answer in uppercase: whats the capital of peru") == ("wrap", 1, "whats the capital of peru")
    assert ps.style_detect("say hi in all caps") == ("literal", 1, "hi")
    assert ps.style_detect("talk in caps from now on")[0] == "free"
    assert ps.apply_style(1, ps.ASK_SAY) == "OK. WHAT SHOULD I SAY?"
    assert ps.style_detect("make hello world all caps") is None and ps.style_detect("hello") is None


def test_calc_examples():
    cases = {"what is 12 plus 2 times 9": "12+2*9", "half of 22": "(22/2)", "17 mod 5": "17%5", "what is 20% of 150": "(20*150/100)",
             "two hundred and five minus ten": "205-10", "(2+3)*4": "(2+3)*4", "double 7": "(7*2)", "7 squared": "(7*7)", "subtract 4 from 10": "10-4",
             "what is 18 tkae aay 47": "18-47", "twenty-three plus 1,000": "23+1000", "three point five times two": "3.5*2"}
    for q, e in cases.items():
        assert ps.calc_parse(q) == e, (q, ps.calc_parse(q))
    for q in ["write a python function to add 3 and 4", "print(2+3) in python", "def f(): return 3*4", "x = 3 + 4", "what is 5", "solve 2x + 3 = 7", "how many days in 2 weeks",
              "five six plus two", "twenty twenty plus 1", "1 and 2", "what year was he born", "echo 5 + 3"]:
        assert ps.calc_parse(q) is None, q


def test_textops_hard_negatives():
    for seed in (7, 8, 9):
        fp = [q for q in neg.make(600, seed) if not ps.textops_guard(q) and to.textops(q)]
        assert not fp, fp[:5]
    for q in neg.POS:
        assert not ps.textops_guard(q), q
