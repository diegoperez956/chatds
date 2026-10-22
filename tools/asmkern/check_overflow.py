#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Negative-link tests using real product objects, without touching product output."""
import argparse
import json
import os
from pathlib import Path
import subprocess as sp


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build', type=Path, required=True)
    ap.add_argument('--work', type=Path, required=True)
    a = ap.parse_args(); a.work.mkdir(parents=True, exist_ok=True)
    wonderful = Path(os.environ.get('WONDERFUL_TOOLCHAIN', str(Path.home() / 'opt/wonderful')))
    blocks = Path(os.environ.get('BLOCKSDS', str(wonderful / 'thirdparty/blocksds/core')))
    gcc = wonderful / 'toolchain/gcc-arm-none-eabi/bin/arm-none-eabi-gcc'
    env = dict(os.environ, BLOCKSDS=str(blocks))
    flags = ['-marm', '-mcpu=arm946e-s+nofp', '-specs=' + str(blocks / 'sys/crts/ds_arm9.specs')]
    results = []
    for section in ('itcm', 'dtcm'):
        source = a.work / (section + '.S'); obj = source.with_suffix('.o')
        source.write_text(f'.section .{section},"aw",%progbits\n.balign 4\n.global asmkern_overflow\nasmkern_overflow:\n.space {32768 if section == "itcm" else 16384}\n')
        sp.run([gcc, *flags, '-c', source, '-o', obj], check=True, capture_output=True, timeout=30, env=env)
        cmd = [gcc, *flags, *sorted((a.build / 'nds').glob('*.o')), obj, '-o', a.work / (section + '.elf'),
               '-L' + str(blocks / 'libs/libnds/lib'), '-Wl,-u,asmkern_overflow', '-Wl,--defsym=__usr_stack_size=4096',
               '-Wl,--start-group', '-lnds9', '-lc', '-lm', '-Wl,--end-group']
        p = sp.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        (a.work / (section + '.log')).write_text(p.stdout + p.stderr)
        assert p.returncode != 0, section + ' overflow incorrectly linked'
        assert ('overflow' in p.stderr.lower() or 'will not fit' in p.stderr.lower()), p.stderr
        results.append(dict(section=section, overflow_rejected=True, returncode=p.returncode))
    (a.work / 'overflow.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
