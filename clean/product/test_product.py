"""Execute the real clean host product with small self-contained DSQ8 assets."""
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / 'campaign/router'), str(ROOT / 'campaign/pipeline')]
import round3 as r3, gen_textops_requests as gen, gen_textops_negatives as neg  # noqa: E402
CHAT = ['hi there', 'hello chatds', 'thanks a lot', 'thank u so much', 'bye for now', 'see ya', 'who are you',
        'what are you', 'what can you do', 'say that again', 'repeat that', 'are you sure', 'good morning', 'cheers mate']


def assets(directory, window=2048):
    # One zero-transformer layer: all logits tie, so lowest ID (0) wins.
    dim, hidden, vocab, kv, gs = 32, 32, 260, 16, 8
    data = bytearray(512)
    struct.pack_into('<13I', data, 0, 0x31454954, 1, 4, 512,
                     dim, hidden, 1, 2, 1, vocab, window, gs, 257)
    data.extend(struct.pack('<96f', *([1.0] * 96)))
    data.extend(bytes((-len(data)) % 512))
    data.extend(bytes(vocab * (dim + 2 * (dim // gs) + 4)))
    data.extend(bytes((-len(data)) % 512))
    for rows, cols in [(dim, dim), (kv, dim), (kv, dim), (dim, dim),
                       (hidden, dim), (dim, hidden), (hidden, dim)]:
        data.extend(bytes(rows * (cols + 2 * (cols // gs) + 4)))
    model = directory / 'model.bin'
    model.write_bytes(data)
    pieces = [b'<unk>', b'<s>', b'</s>'] + [f'<0x{i:02X}>'.encode() for i in range(256)] + [b' ']
    tokenizer = directory / 'tok.bin'
    tokenizer.write_bytes(struct.pack('<I', 6) + b''.join(struct.pack('<fI', 0, len(p)) + p for p in pieces))
    return model, tokenizer


@pytest.fixture(scope='module')
def executable():
    subprocess.run(['make', '-C', HERE, 'host'], check=True)
    return HERE / 'build/chatds-host'


def invoke(executable, tmp_path, config, kb=None, output=None, learned_directory=None, window=2048, serve=None):
    model, tokenizer = assets(tmp_path, window)
    run = tmp_path / 'run.txt'
    run.write_text(config)
    out = output or tmp_path / 'out'
    if output is None:
        out.mkdir()
    result = subprocess.run([executable, model, tokenizer, kb or '-', run, str(out) + '/', *(['--serve'] if serve else [])],
                            input=serve, capture_output=True, text=True, timeout=60,
                            env=dict(os.environ, CHATDS_ROUND3_DIR=str(learned_directory or ROOT / 'campaign/router/models') + '/'))
    return result, out


def test_real_product_budget_publication(executable, tmp_path):
    result, out = invoke(executable, tmp_path, 'steps=2\nkbd=0\ninstruct=1\nprompt=python print hello\n')
    assert result.returncode == 0, result.stderr
    assert (out / 'ids.txt').read_text() == '0\n0\n'
    lines = (out / 'out.txt').read_text().splitlines()
    meta = dict(line.split('=', 1) for line in lines[-6:])
    assert meta['generated'] == '2' and meta['stop'] == 'budget' and meta['status'] == 'OK'
    assert not list(out.glob('*.tmp'))
    heap = dict(line.split('=', 1) for line in (out / 'heap.txt').read_text().splitlines())
    assert heap['kv_bits'] == '16'
    assert int(heap['kv_bytes']) == 1 * 2048 * 16 * 2 * 2
    assert 0 < int(heap['first_piece_ticks']) <= int(heap['total_ticks'])


@pytest.mark.parametrize('config', ['steps=257\n', 'steps=0\n', 'prompt=' + 'x' * 128 + '\n'])
def test_invalid_config_publishes_failure(executable, tmp_path, config):
    result, out = invoke(executable, tmp_path, config)
    assert result.returncode != 0
    assert (out / 'out.txt').read_text().endswith('status=FAIL\n')
    assert (out / 'ids.txt').read_text() == ''


def test_bad_kb_fails_cleanly(executable, tmp_path):
    kb = tmp_path / 'bad-kb.bin'
    kb.write_bytes(b'not a KB')
    result, out = invoke(executable, tmp_path, 'steps=2\nprompt=a\n', kb=kb)
    assert result.returncode != 0
    assert (out / 'out.txt').read_text().endswith('status=FAIL\n')


def test_unwritable_publication_is_not_success(executable, tmp_path):
    result, _ = invoke(executable, tmp_path, 'steps=2\nprompt=a\n', output=tmp_path / 'missing/dir')
    assert result.returncode != 0
    assert 'publication failed' in result.stderr


@pytest.mark.parametrize('head', ['act', 'op', 'tag'])
@pytest.mark.parametrize('failure', ['missing', 'corrupt', 'resigned'])
def test_round3_assets_fail_closed(executable, tmp_path, head, failure):
    models = tmp_path / 'models'; models.mkdir()
    for name in ('act', 'op', 'tag'):
        src = ROOT / f'campaign/router/models/round3-{name}.cdsr'
        dest = models / src.name
        if name != head:
            dest.symlink_to(src)
        elif failure == 'corrupt':
            blob = bytearray(src.read_bytes()); blob[-1] ^= 1; dest.write_bytes(blob)
        elif failure == 'resigned':
            # Internally consistent CDSR (valid body SHA) that is not the committed head.
            blob = bytearray(src.read_bytes()); blob[len(blob) // 2] ^= 1
            blob[20:52] = hashlib.sha256(blob[64:]).digest(); r3.read_head(bytes(blob)); dest.write_bytes(blob)
    result, out = invoke(executable, tmp_path, 'steps=2\ninstruct=1\nprompt=hello\n', learned_directory=models)
    assert result.returncode != 0
    assert (out / 'out.txt').read_text().endswith('status=FAIL\n')
    assert (out / 'ids.txt').read_text() == ''


def test_round3_thresholds_match_python_twin(executable, tmp_path):
    chat = [p + q + s for p in ('', 'hey ', 'ok so ', 'well ', 'um ') for q in CHAT for s in ('', '.', '!', ' pls')]
    # The 60 learnable acts closest to the threshold, on both sides.
    act = sorted((q for q in chat if r3.heads(q)['act'][0] != 'none'),
                 key=lambda q: abs(r3.heads(q)['act'][1] - r3.THRESHOLDS['act']))[:60]
    text = sorted((q for q in dict.fromkeys(gen.make(20000, 2024) + neg.make(8000, 24))
                   if len(q) <= 100 and '\n' not in q and '\t' not in q and r3.text(q, raw=True)),
                  key=lambda q: abs(r3.heads(q)['op'][1] - r3.THRESHOLDS['op']))[:400]
    qs = act + text
    result, out = invoke(executable, tmp_path, 'steps=2\ninstruct=1\nprompt=a\n', serve=''.join(f'R\nQ\t{q}\n' for q in qs))
    assert result.returncode == 0, result.stderr
    logs = [dict(f.split('=', 1) for f in line.split()) for line in (out / 'debug.log').read_text().splitlines()]
    assert len(logs) == len(qs)
    ran = {True: 0, False: 0}
    for q, log in zip(act, logs):
        if log['act_margin'] != '0':
            margin = r3.heads(q)['act'][1]
            fired = r3.act(q)
            assert int(log['act_margin']) == margin, q
            assert int(log['learned_act']) == (r3.ACTS.index(fired[0]) if fired else 0), q
            ran[margin >= r3.THRESHOLDS['act']] += 1
    assert ran[True] and ran[False], ran
    fired = declined = 0
    for q, log in zip(text, logs[len(act):]):
        if log['path'].startswith('style+') or log['path'] == 'calculator' or (log['path'] == 'text_exact' and log['learned_text'] == '0'):
            continue
        t = r3.text(q)
        assert log['learned_text'] == (str(r3.to.OPID[t['op']] + 1) if t else '0'), q
        if t:
            assert int(log['op_margin']) == t['margin'] and int(log['tag_margin']) == t['tag_margin'], q
        fired += bool(t)
        declined += not t
    assert fired and declined, (fired, declined)


def test_insufficient_borrowed_workspace_fails_closed(executable, tmp_path):
    result, out = invoke(executable, tmp_path, 'steps=2\ninstruct=1\nprompt=hello\n', window=32)
    assert result.returncode != 0
    assert 'insufficient fallback workspace' in result.stderr
    assert (out / 'out.txt').read_text().endswith('status=FAIL\n')


def test_story_echo_is_a_published_contract(executable, tmp_path):
    result, out = invoke(executable, tmp_path, 'steps=1\ninstruct=0\nprompt=hello\n')
    assert result.returncode == 0
    assert (out / 'out.txt').read_text().startswith('hello')


def test_rules_tab_matches_generator():
    subprocess.run([sys.executable, str(HERE / 'gen_rules.py'), '--check'], check=True, capture_output=True)
