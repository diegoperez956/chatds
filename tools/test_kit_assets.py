# SPDX-License-Identifier: MIT
"""External asset-pair validation through the executable kit builder."""
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def invoke(tmp_path, manifest, extra=()):
    assets = tmp_path / 'assets'
    assets.mkdir()
    for name in ('model.bin', 'tok.bin'):
        (assets / name).write_bytes(name.encode())
    if manifest is not None:
        (assets / 'SHA256SUMS').write_text(manifest)
    # A valid pair must reach make, not fail validation. Stop there without
    # building a ROM or loading the intentionally tiny fake model.
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    make = bin_dir / 'make'
    make.write_text('#!/bin/sh\necho reached-build >&2\nexit 73\n')
    make.chmod(0o755)
    return subprocess.run(
        ['bash', str(ROOT / 'ds/hwkit/make-kit.sh'), '--asset-dir', str(assets),
         '--out', str(tmp_path / 'out'), *extra],
        env=dict(os.environ, PATH=str(bin_dir) + ':' + os.environ['PATH']),
        text=True, capture_output=True, timeout=20)


def sums():
    return ''.join(hashlib.sha256(n.encode()).hexdigest() + '  ' + n + '\n'
                   for n in ('model.bin', 'tok.bin'))


def test_valid_pair_reaches_build(tmp_path):
    p = invoke(tmp_path, sums())
    assert p.returncode == 73 and 'reached-build' in p.stderr


@pytest.mark.parametrize('manifest', [None, '', sums().splitlines()[0] + '\n',
    sums().replace(hashlib.sha256(b'tok.bin').hexdigest(), '0' * 64),
    sums() + sums().splitlines()[0] + '\n'])
def test_invalid_pair_never_builds(tmp_path, manifest):
    p = invoke(tmp_path, manifest)
    assert p.returncode != 0 and 'reached-build' not in p.stderr
    assert not (tmp_path / 'out').exists()


def test_explicit_pair_conflicts(tmp_path):
    p = invoke(tmp_path, sums(), ('--model', 'unused', '--tokenizer', 'unused'))
    assert p.returncode == 2 and 'conflicts' in p.stderr
    assert 'reached-build' not in p.stderr
