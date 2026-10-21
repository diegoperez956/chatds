#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fail closed on TCM overflow or unsafe direct kernel ISA transitions.

Uses final linked ARM mapping symbols, not source flags. Direct same-state BL/B
is safe (and needs no veneer). Cross-state calls require BLX or a linker veneer
whose instructions change state. Register-indirect function calls cannot be
proved generally. Constant-pool loads followed by BX/BLX are checked too;
unknown/computed kernel function-pointer dispatch is outside this contract.
"""
import argparse
import bisect
import json
from pathlib import Path
import re
import subprocess

if not __debug__:
    raise SystemExit('layout gate requires Python assertions; unset PYTHONOPTIMIZE')

SEAM = {'cds_dot32_arm', 'cds_matvec_fast', 'cds_matvec_c', 'cds_matvec_self_check'}


def layout(text):
    text = text.split('Linker script and memory map', 1)[1]
    def sym(name):
        values = re.findall(r'^\s+0x([0-9a-f]+)\s+' + re.escape(name) + r'\s*=', text, re.M)
        assert len(values) == 1, 'missing/ambiguous linker symbol: ' + name
        return int(values[0], 16)
    start, end = sym('__itcm_start'), sym('__itcm_end')
    assert start == 0x01000000 and start <= end <= start + 32768, 'ITCM overflow'
    base, top, data_end = sym('__dtcm_start'), sym('__dtcm_top'), sym('__sbss_end')
    data_top = sym('__dtcm_data_top')
    assert base == 0x02ff4000 and top == base + 16384
    assert base <= data_end <= data_top <= top, 'DTCM data/stack overlap'
    reserved = top - data_top
    return {'itcm_used': end - start, 'itcm_free': start + 32768 - end,
            'dtcm_data_used': data_end - base, 'dtcm_reserved_stacks_system': reserved,
            'dtcm_free_after_reservations': data_top - data_end,
            'main_static_end': sym('__end__') - 0x02000000}


def interworking(symbols, disassembly, require_asm=True):
    mapping = {}
    functions = {}
    for line in symbols.splitlines():
        f = line.split()
        if len(f) < 8 or not re.fullmatch(r'\d+:', f[0]):
            continue
        addr, name = int(f[1], 16), f[7]
        if re.fullmatch(r'\$[atd](?:\..*)?', name):
            mapping[addr] = name[1]
        if f[3] == 'FUNC':
            functions[name] = addr & ~1
    points = sorted(mapping)
    def state(addr):
        i = bisect.bisect_right(points, addr) - 1
        assert i >= 0, 'missing ISA mapping'
        return mapping[points[i]]
    if require_asm:
        assert SEAM <= functions.keys(), 'assembly seam missing'
        assert state(functions['cds_dot32_arm']) == 'a'
    calls = []
    current = ''
    for line in disassembly.splitlines():
        label = re.match(r'^([0-9a-f]+) <([^>]+)>:', line)
        if label:
            current = label[2]
            continue
        ins = re.match(r'^\s*([0-9a-f]+):\s+(?:[0-9a-f]+\s+)+\s*(b(?:l|lx)?(?:eq|ne|cs|cc|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?)\s+([0-9a-f]+) <([^>]+)>', line)
        if not ins:
            continue
        src, op, dst, target = int(ins[1], 16), ins[2], int(ins[3], 16), ins[4]
        if not any(name in target for name in SEAM):
            continue
        if '+' in target:
            assert target.split('+', 1)[0] == current, 'external branch into kernel interior'
            continue
        a, b = state(src), state(dst)
        assert a in 'at' and b in 'at', 'branch into data'
        assert (a == b and not op.startswith('blx')) or (a != b and op.startswith('blx')), (
            f'unsafe ISA transition {current} {src:x}: {op} {target} ({a}->{b})')
        calls.append({'caller': current, 'address': hex(src), 'instruction': op,
                      'target': target, 'isa': a + '->' + b})
    # ITCM_CODE includes GCC long_call. The self-check and fallback therefore
    # use literal-address LDR + register BX/BLX, not a labelled direct BL.
    words = {int(a, 16): int(v, 16) for a, v in re.findall(
        r'^\s*([0-9a-f]+):\s+[0-9a-f]+\s+\.word\s+0x([0-9a-f]+)', disassembly, re.M)}
    entries = {addr: name for name, addr in functions.items() if name in SEAM}
    pending = {}
    loaded, consumed = set(), set()
    for line in disassembly.splitlines():
        label = re.match(r'^([0-9a-f]+) <([^>]+)>:', line)
        if label:
            current = label[2]
            pending = {}
            continue
        ins = re.match(r'^\s*([0-9a-f]+):\s+(?:[0-9a-f]+\s+)+\s*([a-z][a-z0-9.]*)\s+(.*)', line)
        if not ins:
            continue
        src, op, operands = int(ins[1], 16), ins[2], ins[3]
        literal = re.match(r'(\w+),\s*\[pc[^]]*\].*@\s*([0-9a-f]+)\s+<', operands)
        if op == 'ldr' and literal:
            reg, pool = literal[1], int(literal[2], 16)
            value = words.get(pool, 0)
            if (value & ~1) in entries:
                pending[reg] = (src, value)
                # CRT/MPU also load ITCM's numeric origin, which happens to
                # equal the first leaf address; those are data, not calls.
                if current in SEAM or current == 'main' or current.startswith(('chatds_', 'probe_')):
                    loaded.add(src)
                continue
        reg = operands.split(',', 1)[0].strip()
        if op in ('bx', 'blx') and reg in pending:
            load, value = pending.pop(reg)
            target = value & ~1
            assert state(target) == ('t' if value & 1 else 'a'), 'wrong kernel function-pointer ISA bit'
            if load in loaded:
                consumed.add(load)
            calls.append({'caller': current, 'address': hex(src), 'instruction': op,
                          'target': entries[target], 'isa': state(src) + '->' + state(target),
                          'literal_load': hex(load)})
        elif reg in pending and not op.startswith(('str', 'cmp', 'tst', 'b')):
            del pending[reg]
    assert loaded == consumed, 'unverified kernel literal-address call: ' + ','.join(hex(a) for a in loaded - consumed)
    assert calls, 'no kernel callsites found'
    # A Thumb linker stub may enter ARM with BX PC before its B to the seam;
    # mapping symbols above verify the B itself executes as ARM. Record stubs.
    veneers = [name for name in functions if any(s in name for s in SEAM) and
               ('veneer' in name or 'from_thumb' in name)]
    if require_asm:
        dot = disassembly.split('<cds_dot32_arm>:', 1)[1].split('\n\n', 1)[0]
        assert re.search(r'\bbx\s+lr', dot), 'assembly leaf lacks BX LR'
        assert 'smlabb' in dot and 'smlabt' in dot and not re.search(r'\bsmlad\b', dot)
    return {'direct_calls': calls, 'veneers': veneers,
            'scope': 'direct and literal-address BX/BLX calls to kernel seam; final mapping symbols checked'}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--prefix', required=True)
    ap.add_argument('--elf', type=Path, required=True)
    ap.add_argument('--map', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--no-asm', action='store_true')
    a = ap.parse_args()
    symbols = subprocess.check_output([a.prefix + 'readelf', '-sW', a.elf], text=True)
    disassembly = subprocess.check_output([a.prefix + 'objdump', '-d', a.elf], text=True)
    report = layout(a.map.read_text()) | {'interworking': interworking(symbols, disassembly, not a.no_asm)}
    a.out.write_text(json.dumps(report, indent=2) + '\n')
    a.out.with_suffix('.dis').write_text(disassembly)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
