"""Execute the real clean host product with small self-contained DSQ8 assets."""
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


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


def invoke(executable, tmp_path, config, kb=None, output=None, learned_directory=None, window=2048):
    model, tokenizer = assets(tmp_path, window)
    run = tmp_path / 'run.txt'
    run.write_text(config)
    out = output or tmp_path / 'out'
    if output is None:
        out.mkdir()
    result = subprocess.run([executable, model, tokenizer, kb or '-', run, str(out) + '/'],
                            capture_output=True, text=True, timeout=10,
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
@pytest.mark.parametrize('failure', ['missing', 'corrupt'])
def test_round3_assets_fail_closed(executable, tmp_path, head, failure):
    models = tmp_path / 'models'; models.mkdir()
    for name in ('act', 'op', 'tag'):
        src = ROOT / f'campaign/router/models/round3-{name}.cdsr'
        dest = models / src.name
        if name != head:
            dest.symlink_to(src)
        elif failure == 'corrupt':
            blob = bytearray(src.read_bytes()); blob[-1] ^= 1; dest.write_bytes(blob)
    result, out = invoke(executable, tmp_path, 'steps=2\ninstruct=1\nprompt=hello\n', learned_directory=models)
    assert result.returncode != 0
    assert (out / 'out.txt').read_text().endswith('status=FAIL\n')
    assert (out / 'ids.txt').read_text() == ''


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
