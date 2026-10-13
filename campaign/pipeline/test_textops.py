"""Parity (C vs Python reference) + sanitizer fuzz for textops. Run: pytest -q campaign/pipeline/test_textops.py"""
import pathlib, subprocess, sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import textops as py, gen_textops_requests as gen  # noqa: E402

PL = HERE.parents[1] / "clean" / "plumbing"
BIN = PL / "build" / "test-textops"


def build():
    BIN.parent.mkdir(exist_ok=True)
    subprocess.run(["cc", "-std=c99", "-O1", "-g", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-fno-sanitize-recover=all", "-I" + str(PL), str(PL / "textops.c"), str(PL / "test_textops.c"), "-o", str(BIN)], check=True)


def run_c(qs):
    p = subprocess.run(["nice", "-n", "19", str(BIN)], input="".join(q.replace("\n", " ") + "\n" for q in qs), capture_output=True, text=True, check=True)
    return p.stdout.split("\n")[:-1]


def test_table_current():
    assert (PL / "textops_tab.h").read_text() == py.emit_h(), "regenerate: python3 campaign/pipeline/textops.py --emit-h > clean/plumbing/textops_tab.h"


def test_parity():
    build()
    qs = [q for q in gen.make(6000, 20260101) if "\n" not in q]
    cs = run_c(qs)
    assert len(cs) == len(qs)
    bad, hits = [], 0
    for q, c in zip(qs, cs):
        r = py.textops(q)
        want = "%s\t%s" % r if r else "-"
        hits += bool(r)
        if want != c:
            bad.append((q, want, c))
    assert not bad, bad[:10]
    assert len(qs) >= 3000 and 500 < hits < len(qs)  # both answered and declined are exercised


def test_fuzz():
    build()
    for seed in (1, 2, 3):
        p = subprocess.run(["nice", "-n", "19", str(BIN), "--fuzz", "30000", str(seed)], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr[-2000:]
