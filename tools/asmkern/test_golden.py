# SPDX-License-Identifier: MIT
"""Validate the C24 publication protocol, not transformer-only assumptions."""
import importlib.util
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location('asmkern_golden', Path(__file__).with_name('golden.py'))
golden = importlib.util.module_from_spec(spec)
spec.loader.exec_module(golden)


def publish(path, *, prompt=0, ids=(), stop='none', status='OK', tokens=None):
    if tokens is None:
        tokens = prompt - 1 + len(ids) if prompt else 0
    (path / 'out.txt').write_text(f'answer\ntokens={tokens}\nprompt_tokens={prompt}\ngenerated={len(ids)}\nstop={stop}\nms=42\nstatus={status}\n')
    (path / 'ids.txt').write_text(''.join(str(i)+'\n' for i in ids))
    (path / 'ctx.txt').write_text('ctx=evidence\nkb=ok\n')


def test_deterministic_zero_token_answer(tmp_path):
    publish(tmp_path)
    (tmp_path / 'calc.txt').write_text('calc=17\n')
    actual = golden.parse(tmp_path)
    assert actual['ids'] == [] and actual['status'] == 'OK' and actual['prompt_tokens'] == 0
    assert actual['calc'] == 'calc=17\n' and actual['text'] == 'answer'


def test_raw_story_needs_no_calc_file(tmp_path):
    publish(tmp_path, prompt=13, ids=(1885, 332), stop='eos')
    actual = golden.parse(tmp_path)
    assert actual['tokens'] == 14 and actual['ids'] == [1885, 332] and actual['calc'] is None


def test_clean_failed_raw_prompt_is_explicit(tmp_path):
    publish(tmp_path, status='FAIL')
    assert golden.parse(tmp_path)['status'] == 'FAIL'


@pytest.mark.parametrize('kwargs', [dict(prompt=1, ids=(2048,), stop='eos'),
                                   dict(prompt=1, ids=(-1,), stop='eos'),
                                   dict(tokens=1), dict(prompt=257, stop='eos'),
                                   dict(prompt=0, ids=(1,)), dict(prompt=1, stop='none'),
                                   dict(status='MAYBE')])
def test_invalid_publication_rejected(tmp_path, kwargs):
    publish(tmp_path, **kwargs)
    with pytest.raises(AssertionError):
        golden.parse(tmp_path)


def test_incomplete_publication_is_not_completion(tmp_path):
    publish(tmp_path)
    (tmp_path / 'out.txt').write_text('answer\ntokens=0\n')
    with pytest.raises(AssertionError):
        golden.parse(tmp_path)
