"""Round3 fallback parity (C vs Python twin) + sanitizer fuzz. Run: pytest -q campaign/router/test_round3.py"""
import hashlib, pathlib, random, re, subprocess, sys
HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent/'pipeline')]
import round3 as r3, gen_textops_requests as gen, gen_textops_negatives as neg  # noqa: E402

ROOT = HERE.parents[1]
PL = ROOT/'clean/plumbing'
BIN = PL/'build/test-round3'
SOURCES = ['router.c', 'round3.c', 'textops.c', 'prestep.c', 'calc.c', 'test_round3.c']
CHAT = ["hi there", "hello chatds", "thanks a lot", "thank u so much", "bye for now", "see ya", "who are you", "what are you",
        "what can you do", "how are you doing", "you're great", "nice job", "you are dumb", "that's useless", "say that again",
        "repeat that", "are you sure", "that's wrong", "no it isn't", "good morning", "cheers mate", "lol ok"]


def build():
    BIN.parent.mkdir(exist_ok=True)
    subprocess.run(['cc', '-std=c99', '-O1', '-g', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-I' + str(ROOT/'clean/include'),
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-sanitize-recover=all',
                    *[str(PL/s) for s in SOURCES], '-o', str(BIN)], check=True)


def args(raw):
    t = dict(act=0, op=0, tag=0) if raw else r3.THRESHOLDS
    return [str(BIN)] + [str(r3.MODELS/f'round3-{k}.cdsr') for k in r3.HEADS] + [str(t[k]) for k in r3.HEADS]


def queries():
    rng = random.Random(24)
    qs = gen.make(4000, 2024) + neg.make(1500, 24) + CHAT
    qs += [p + ' ' + q for p in ('hey', 'please', 'ok so') for q in rng.sample(qs, 300)]
    qs += [''.join(chr(32 + rng.randrange(95)) for _ in range(rng.randrange(1, 140))) for _ in range(800)]
    return [q for q in dict.fromkeys(qs) if '\n' not in q and '\t' not in q]


def esc(s):
    return ''.join('\\\\' if c == '\\' else c if 32 <= ord(c) <= 126 else '\\x%02x' % ord(c) for c in s)


def test_learned_c_pins_committed_heads():
    src = (ROOT/'clean/product/learned.c').read_text()
    for k in r3.HEADS:
        blob = (r3.MODELS/f'round3-{k}.cdsr').read_bytes()
        assert ''.join('0x%02x,' % b for b in hashlib.sha256(blob).digest())[:-1] in src.replace(' ', ''), k
        assert '%s_BYTES = %d' % (k.upper(), len(blob)) in src, k
    t = r3.THRESHOLDS
    assert 'act_threshold = %d; r->op_threshold = %d; r->tag_threshold = %d;' % (t['act'], t['op'], t['tag']) in src
    assert len(re.findall(r'act_threshold = %d;' % t['act'], src)) == 2


def test_parity():
    build()
    qs = queries()
    assert len(qs) >= 6000
    for raw in (False, True):
        # Alternate the caller's rules veto: a vetoed act must decline, the raw head output is unchanged.
        payload = ''.join('%d\t%s\n' % (i % 2, esc(q)) for i, q in enumerate(qs))
        lines = subprocess.run(args(raw), input=payload, capture_output=True, text=True, check=True).stdout.splitlines()
        assert len(lines) == len(qs)
        acts = texts = 0
        for i, (q, line) in enumerate(zip(qs, lines)):
            f = line.split('\t')
            label, margin = r3.heads(q)['act']
            assert [int(f[0]), int(f[1])] == [r3.ACTS.index(label), margin], q
            a = None if i % 2 else r3.act(q, raw=raw)
            assert int(f[2]) == (r3.ACTS.index(a[0]) if a else 0), q
            t = r3.text(q, raw=raw)
            assert bool(int(f[3])) == bool(t), q
            if t:
                want = [r3.to.OPID[t['op']], *t['span'], *t['spans'].get('X', [0, 0]), *t['spans'].get('Y', [0, 0]),
                        t['arg'], t['margin'], t['tag_margin']]
                assert list(map(int, f[4:14])) == want, q
                assert f[14] == esc(t['output']), q
            acts += bool(a)
            texts += bool(t)
        assert acts >= 5 and texts >= 100, (raw, acts, texts)  # both fallbacks fire and decline


def test_fuzz():
    build()
    for seed in (1, 2, 3):
        p = subprocess.run(['nice', '-n', '19', *args(False), '--fuzz', str(seed), '30000'], capture_output=True, text=True)
        assert p.returncode == 0 and p.stdout.strip() == 'fuzz OK', p.stderr[-2000:]
