#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""All 33 frozen engine inputs: independent product C host == product ARM ROM.

Frozen fixture answers stay immutable. C24's accepted answer-policy differences
from the older fixtures are recorded, never used to excuse host/ROM differences.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import time
from headless import eg, SANDBOX, verify_live


def parse(work):
    lines = (work / 'out.txt').read_text().splitlines()
    keys = ('tokens', 'prompt_tokens', 'generated', 'stop', 'ms', 'status')
    assert len(lines) >= 6 and all(s.startswith(k+'=') for k,s in zip(keys, lines[-6:]))
    meta = dict(s.split('=', 1) for s in lines[-6:])
    ids = [int(s) for s in (work / 'ids.txt').read_text().split()]
    context = (work / 'ctx.txt').read_text().splitlines()[0]
    prompt, generated = int(meta['prompt_tokens']), int(meta['generated'])
    assert meta['status'] in ('OK', 'FAIL') and context.startswith('ctx=')
    assert 0 <= prompt <= 256 and generated == len(ids) and all(0 <= i < 2048 for i in ids)
    assert int(meta['tokens']) == (prompt - 1 + generated if prompt else 0)
    if meta['status'] == 'OK':
        assert (not prompt and not generated and meta['stop'] == 'none') or (prompt and meta['stop'] in ('bos','eos','budget'))
    return dict(status=meta['status'], text='\n'.join(lines[:-6]), ids=ids,
                prompt_tokens=int(meta['prompt_tokens']), generated=int(meta['generated']),
                tokens=int(meta['tokens']), stop=meta['stop'], context=context[4:],
                calc=(work / 'calc.txt').read_text() if (work / 'calc.txt').exists() else None)


def run_case(case, a, work):
    work.mkdir(); host = work / 'host'; host.mkdir(); device = work / 'device'; device.mkdir()
    run = work / 'run.txt'
    run.write_text(f'steps={case.get("steps",64)}\nkbd=0\ninstruct={int(case.get("instruct",True))}\nprompt={case["question"]}\n')
    p = sp.run([a.host, a.assets / 'model.bin', a.assets / 'tok.bin', a.kb, run, str(host) + '/'],
               env=dict(os.environ, CHATDS_ROUND3_DIR=str(a.assets) + '/'), capture_output=True, timeout=120)
    (host / 'stderr.txt').write_bytes(p.stderr)
    expected = parse(host)
    assert (p.returncode == 0) == (expected['status'] == 'OK'), 'host exit/status mismatch'
    for name in ('home', 'cache', 'config/melonDS'):
        (device / name).mkdir(parents=True)
    rom = device / 'boot.nds'; shutil.copyfile(a.rom, rom)
    image = device / 'sd.img'
    eg.pack_image(image, {'chatds/' + n: a.assets / n for n in ('model.bin', 'tok.bin', 'round3-act.cdsr', 'round3-op.cdsr', 'round3-tag.cdsr')} |
                  {'chatds/kb.bin': a.kb, 'chatds/run.txt': run})
    (device / 'config/melonDS/melonDS.toml').write_text('LimitFPS = false\n[Emu]\nDirectBoot = true\nExternalBIOSEnable = false\n[JIT]\nEnable = true\n[Screen]\nUseGL = false\n[3D]\nRenderer = 0\n[DLDI]\nEnable = true\nImagePath = ' + json.dumps(str(image)) + '\nImageSize = 0\nReadOnly = false\nFolderSync = false\nFolderPath = ""\n')
    shim = device / 'io.so'
    eg.command(['cc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                eg.ROOT / 'tools/melon-image-io.c', '-ldl', '-o', shim])
    launch = 'export XDG_CONFIG_HOME="$1" HOME="$2" XDG_CACHE_HOME="$3"; exec melonDS "$4"'
    args = ['flatpak', 'run', *SANDBOX, '--filesystem=' + str(work), '--env=LD_PRELOAD=' + str(shim),
            '--env=MELON_UNBUFFERED_IMAGE=' + str(image), '--command=sh', eg.APP, '-c', launch, 'sh',
            str(device / 'config'), str(device / 'home'), str(device / 'cache'), str(rom)]
    with (device / 'emulator.log').open('w') as log:
        proc = sp.Popen(args, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                p = sp.run(['mcopy', '-o', '-i', str(image), '::/chatds/out.txt', str(device / 'out.txt')], capture_output=True, timeout=5)
                if p.returncode == 0 and (device / 'out.txt').read_text().endswith(('status=OK\n', 'status=FAIL\n')):
                    break
                assert proc.poll() is None, 'emulator exited'
                time.sleep(.1)
            else:
                raise TimeoutError(case['name'])
            verify_live(rom, device)
            assert '[melon-image] unbuffered: ' + str(image) in (device / 'emulator.log').read_text()
            names = ['ids.txt', 'ctx.txt', 'heap.txt', 'kernel.txt']
            if case.get('instruct', True):
                names.append('calc.txt')
            for name in names:
                eg.command(['mcopy', '-o', '-i', image, '::/chatds/' + name, device / name], capture_output=True)
            actual = parse(device)
            assert (device / 'kernel.txt').read_text() == 'gs32 boot self-check PASS\n'
        finally:
            eg.kill_owned(rom)
            try:
                proc.wait(timeout=5)
            except sp.TimeoutExpired:
                proc.kill(); proc.wait(timeout=5)
            eg.kill_owned(rom)
    image.unlink()
    mismatch = [k for k in expected if expected[k] != actual[k]]
    result = dict(name=case['name'], expected=expected, actual=actual, mismatch=mismatch,
                  fixture_answer_delta=[] if case.get('class') else eg.compare(case['expected'], actual))
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('rom', 'host', 'assets', 'kb', 'work'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--resume', action='store_true', help='resume only hash-matching completed case records')
    a = ap.parse_args()
    for name in ('rom', 'host', 'assets', 'kb', 'work'):
        setattr(a, name, getattr(a, name).resolve())
    fixture = json.loads(eg.DEFAULT_FIXTURES.read_text()); eg.validate_fixture_set(fixture)
    for name, path in [('model', a.assets / 'model.bin'), ('tokenizer', a.assets / 'tok.bin'), ('kb', a.kb)]:
        assert eg.sha256(path) == fixture['provenance'][name + '_sha256'], 'frozen asset mismatch'
    a.work.mkdir(parents=True, exist_ok=a.resume)
    result = dict(rom_sha256=eg.sha256(a.rom), host_sha256=eg.sha256(a.host),
                  fixture_sha256=eg.sha256(eg.DEFAULT_FIXTURES), cases=[])
    for case in fixture['cases']:
        saved = a.work / case['name'] / 'result.json'
        if saved.exists():
            old = json.loads((a.work / 'golden.json').read_text())
            assert old['rom_sha256'] == result['rom_sha256'] and old['host_sha256'] == result['host_sha256']
            row = json.loads(saved.read_text())
        else:
            row = run_case(case, a, a.work / case['name'])
        result['cases'].append(row)
        (a.work / 'golden.json').write_text(json.dumps(result, indent=2) + '\n')
        print(case['name'], 'mismatch', row['mismatch'], flush=True)
    assert len(result['cases']) == 33 and not any(r['mismatch'] for r in result['cases'])


if __name__ == '__main__':
    main()
