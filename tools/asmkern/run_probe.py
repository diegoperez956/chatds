#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run real ARM seam tests and forward timing twice, software-only melonDS."""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess as sp
import time
from headless import eg, SANDBOX, verify_live


def boot(index, model, root, timing=False):
    work = root / ('boot-' + str(index)); work.mkdir()
    for name in ('home', 'cache', 'config/melonDS'):
        (work / name).mkdir(parents=True)
    rom = work / 'boot.nds'
    build = 'build-timing' if timing else 'build'
    shutil.copyfile(Path(__file__).parent / build / 'asmkern.nds', rom)
    image = work / 'sd.img'
    eg.pack_image(image, {'model.bin': model})
    (work / 'config/melonDS/melonDS.toml').write_text('LimitFPS = false\n[Emu]\nDirectBoot = true\nExternalBIOSEnable = false\n[JIT]\nEnable = true\n[Screen]\nUseGL = false\n[3D]\nRenderer = 0\n[DLDI]\nEnable = true\nImagePath = ' + json.dumps(str(image)) + '\nImageSize = 0\nReadOnly = false\nFolderSync = false\nFolderPath = ""\n')
    shim = work / 'flush.so'
    eg.command(['cc', '-shared', '-fPIC', '-O2', Path(__file__).parent / 'flush.c', '-o', shim])
    launch = 'export XDG_CONFIG_HOME="$1" HOME="$2" XDG_CACHE_HOME="$3" LD_PRELOAD="$4"; exec melonDS "$5"'
    args = ['flatpak', 'run', *SANDBOX, '--filesystem=' + str(work), '--command=sh', eg.APP,
            '-c', launch, 'sh', str(work / 'config'), str(work / 'home'), str(work / 'cache'), str(shim), str(rom)]
    start = time.monotonic(); peak = 0; verified = None
    with (work / 'emulator.log').open('w') as log:
        p = sp.Popen(args, stdout=log, stderr=log)
        try:
            while time.monotonic() - start < 300:
                text = (work / 'emulator.log').read_text(errors='replace')
                if 'ASMKERN FAIL' in text:
                    raise AssertionError(text)
                if 'ASMKERN START' in text:
                    verified = verify_live(rom, work)
                    rss = int(re.search(r'VmRSS:\s+(\d+)', Path(f'/proc/{verified["pid"]}/status').read_text())[1])
                    peak = max(peak, rss)
                    assert peak < 512 * 1024, 'emulator RSS exceeded 512 MiB'
                if 'ASMKERN DONE PASS' in text:
                    break
                assert p.poll() is None, 'emulator exited'
                time.sleep(.1)
            else:
                raise TimeoutError('300 second probe timeout')
        finally:
            eg.kill_owned(rom)
            try:
                p.wait(timeout=5)
            except sp.TimeoutExpired:
                p.kill(); p.wait(timeout=5)
            eg.kill_owned(rom)
    assert verified and not eg.owned_pids(rom)
    eg.command(['fsck.fat', '-n', image], capture_output=True)
    image.unlink()
    markers = ['THUMB PASS', 'ROWS rows=99328 PASS', 'LOGITS forwards=32 logits=65536 PASS']
    if not timing:
        markers += ['SHAPES rows=2688 fallback_guards=10 PASS', 'FAULT-LATCH rows=192 PASS']
    for marker in markers:
        assert 'ASMKERN ' + marker in text, marker
    samples = [dict(kernel=k, start=int(s), index=int(i), ticks=int(t)) for k,s,i,t in
               re.findall(r'ASMKERN TOKEN k=(\w+) start=(\d+) i=(\d+) ticks=(\d+)', text)]
    assert len(samples) == 64
    return dict(headless=verified, owned_pid_terminated=True, peak_rss_kib=peak,
                host_wall_seconds=round(time.monotonic() - start, 3), samples=samples)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('model', type=Path)
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--timing', action='store_true', help='uninstrumented leaf calls, no --wrap counter')
    a = ap.parse_args(); work = a.work.resolve(); work.mkdir(parents=True)
    boots = [boot(i, a.model.resolve(), work, a.timing) for i in range(2)]
    cells = []
    for k in ('C', 'ASM'):
        for start in (0, 224):
            ms = sorted(s['ticks'] * 1000 / 33513982 for b in boots for s in b['samples']
                        if s['kernel'] == k and s['start'] == start)
            cells.append(dict(kernel=k, context_start=start, samples=len(ms),
                              p50_ms=ms[math.ceil(len(ms)*.5)-1], p95_ms=ms[math.ceil(len(ms)*.95)-1]))
    result = dict(label='EMULATED melonDS, not physical DS or cycle-exact hardware',
                  model_sha256=eg.sha256(a.model), probe_rom_sha256=eg.sha256(Path(__file__).parent / ('build-timing' if a.timing else 'build') / 'asmkern.nds'),
                  call_counter_instrumented=not a.timing,
                  clock_hz=33513982, percentiles='nearest rank', boots=boots, timing=cells)
    (work / 'probe.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(cells, indent=2), flush=True)


if __name__ == '__main__':
    main()
