"""Verify #18 with the actual session allocator and learned arena check."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_context64_borrowing_shortfall(tmp_path):
    exe = tmp_path / 'workspace'
    sources = ['clean/product/test_workspace.c', 'clean/src/format.c',
               'clean/src/kernels.c', 'clean/src/engine.c', 'clean/plumbing/router.c',
               'clean/plumbing/round3.c', 'clean/plumbing/textops.c',
               'clean/plumbing/prestep.c', 'clean/plumbing/calc.c']
    subprocess.run(['cc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(ROOT / 'clean/include'), '-I' + str(ROOT / 'clean/src'),
                    '-I' + str(ROOT / 'clean/plumbing'), *(str(ROOT / p) for p in sources),
                    '-lm', '-o', str(exe)], check=True, timeout=60)
    run = subprocess.run([exe], check=True, capture_output=True, text=True, timeout=10)
    rows = [dict(f.split('=', 1) for f in line.split()) for line in run.stdout.splitlines()]
    assert rows == [
        dict(context='256', value_bytes='196608', kv_bytes='393216', external_key_bytes='196608',
             head_bytes='39336', scratch_bytes='10112', required_bytes='49448', shortfall='0', init='0'),
        dict(context='64', value_bytes='49152', kv_bytes='98304', external_key_bytes='49152',
             head_bytes='39336', scratch_bytes='10112', required_bytes='49448', shortfall='296', init='-1')]
    print(run.stdout, end='')
