import os, struct
import pytest
import build_kb4, kb4, kb4_scan, retrieve4 as R

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "kb4_mini.xml")


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    d = tmp_path_factory.mktemp("kb4")
    kb4_scan.scan(FIX, str(d / "p.jsonl.gz"))
    st = build_kb4.build(str(d / "p.jsonl.gz"), str(d / "k.bin"), "test", entities_path=str(d / "e.jsonl.gz"))
    return str(d / "k.bin"), st


def ask(path, q, **kw):
    kb = kb4.KB4(path)
    return R.retrieve(kb, q, **kw)


def test_format(mini):
    p, st = mini
    h = open(p, "rb").read(512)
    assert h[:4] == b"KB4\0" and struct.unpack("<I", h[4:8])[0] == 4
    assert struct.unpack("<I", h[32:36])[0] == os.path.getsize(p)
    assert st["n_entities"] == 24 and st["by_type"]["person"] >= 8
    assert st["max_bucket_bytes"] <= 512


def test_named_questions(mini):
    p, _ = mini
    r = ask(p, "when was ww2")
    assert (r.status, r.field, r.rec["title"]) == ("answer_present", "date_range", "World War II")
    assert "1939" in r.context and "1945" in r.context
    r = ask(p, "what years ww2")  # KB3 skips 'ww2' here: 'years' counted as a content word
    assert r.status == "answer_present" and "1945" in r.context
    r = ask(p, "napoleon last name")
    assert r.status == "answer_present" and r.value == "Bonaparte" and r.prov == "infobox"
    r = ask(p, "who was michael jacjson")
    assert r.status == "answer_present" and r.rec["title"] == "Michael Jackson" and r.log["expansion"]
    assert ask(p, "who was michael jacjson", expand=False).status == "no_match"
    r = ask(p, "what is python", k=3)
    assert r.status == "ambiguous" and len(r.alts) >= 1
    assert ask(p, "what is python", k=1).status == "answer_present"  # k=1 never sees the alternative
    r = ask(p, "what is the capital of france")
    assert r.status == "answer_present" and r.value == "Paris"
    r = ask(p, "where was albert einstein born")
    assert r.status == "answer_present" and r.value.startswith("Ulm")


def test_statuses_are_distinct(mini):
    p, _ = mini
    assert ask(p, "when did barack obama die").status == "field_missing"       # explicit marker
    assert ask(p, "plato last name").status == "field_missing"                 # mononym: no surname
    r = ask(p, "what is the capital of albert einstein")
    assert r.status == "field_missing" and r.log["fallback_reason"] == "field_not_applicable"
    assert ask(p, "who is zqxv blorpt").status == "no_match"
    assert ask(p, "print hello world in python").status == "gated"
    assert ask(p, "what is 5 + 3").status == "gated"
    assert ask(p, "hello there").status == "gated"
    assert ask(p, "tell me about mercury").status == "ambiguous"


def test_description_without_dates_is_not_an_answer(mini):
    # the Titanic page has a definition but no date field: a date question must not be 'answered'
    p, _ = mini
    r = ask(p, "when was the titanic")
    assert r.status != "answer_present"


def test_bounded_io(mini):
    p, _ = mini
    kb = kb4.KB4(p)
    kb.sector = None
    c = kb.lookup("france") or kb.lookup("paris")
    assert kb.sector_reads <= 3 and len(c) <= kb4.CAND_MAX
    r = R.retrieve(kb, "what is the capital of france")
    assert r.log["sector_reads"] <= 8


def test_corrupt_and_io(mini, tmp_path):
    p, _ = mini
    b = bytearray(open(p, "rb").read())
    for cut in (0, 100, 511, 512, len(b) // 2):
        q = tmp_path / ("t%d.bin" % cut)
        q.write_bytes(bytes(b[:cut]))
        with pytest.raises(kb4.KB4Error):
            kb4.KB4(str(q))
    kb = kb4.KB4(p, fault_after=0)
    assert R.retrieve(kb, "when was ww2").status == "io_error"
    bad = bytearray(b)
    ro = struct.unpack_from("<I", bad, 28)[0]
    bad[ro:ro + 2] = b"\xff\xff"  # first record: absurd length
    q = tmp_path / "bad.bin"
    q.write_bytes(bytes(bad))
    kb = kb4.KB4(str(q))
    st = {R.retrieve(kb, x).status for x in ("what is paris", "what is tokyo", "when was ww2", "what is the capital of france")}
    assert "corrupt_kb" in st


def test_typo_failure_cases(mini):
    p, _ = mini
    # the delete index needs a word of >= 5 chars: a typo in the 3-char alias 'ww2' is not repaired
    assert ask(p, "when was wwz2").status == "no_match"
    # a typo that is itself an indexed word is not corrected
    assert ask(p, "who was michael johnsen").rec is None or ask(p, "who was michael johnsen").rec["title"] != "Michael Jackson"
