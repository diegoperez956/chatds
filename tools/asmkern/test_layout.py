# SPDX-License-Identifier: MIT
"""Exercise the build gate's linker-map/disassembly protocol, including rejects."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('asmkern_layout', Path(__file__).with_name('check_layout.py'))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def map_text(itcm=3744, data=0, top=0x02ff6dc0):
    values = {'__itcm_start': 0x01000000, '__itcm_end': 0x01000000 + itcm,
              '__dtcm_start': 0x02ff4000, '__dtcm_top': 0x02ff8000,
              '__sbss_end': 0x02ff4000 + data, '__dtcm_data_top': top, '__end__': 0x0204effc}
    return 'Linker script and memory map\n' + ''.join(f' 0x{value:08x} {name} = expression\n' for name,value in values.items())


def symbols(thumb=False):
    rows = [(0x01000000, 'NOTYPE', '$a'), (0x01000000, 'FUNC', 'cds_dot32_arm'),
            (0x01000100, 'FUNC', 'cds_matvec_c'), (0x01000200, 'FUNC', 'cds_matvec_fast'),
            (0x02002000, 'NOTYPE', '$t' if thumb else '$a'),
            (0x02002001 if thumb else 0x02002000, 'FUNC', 'cds_matvec_self_check'),
            (0x0200200c, 'NOTYPE', '$d')]
    return '\n'.join(f'{i}: {addr:08x} 0 {kind} LOCAL DEFAULT 1 {name}' for i,(addr,kind,name) in enumerate(rows))


DOT = '''01000000 <cds_dot32_arm>:
 1000000: e1023182 smlabb r2, r2, r1, r3
 1000004: e10231c2 smlabt r2, r2, r1, r3
 1000008: e12fff1e bx lr

'''


def test_headroom_includes_dtcm_stack_reservations():
    assert gate.layout(map_text()) == dict(itcm_used=3744, itcm_free=29024,
        dtcm_data_used=0, dtcm_reserved_stacks_system=4672,
        dtcm_free_after_reservations=11712, main_static_end=0x4effc)


@pytest.mark.parametrize('text', [map_text(itcm=32769), map_text(data=11713),
                                map_text(top=0x03000000), 'missing map'])
def test_bad_linker_layout_rejected(text):
    with pytest.raises((AssertionError, IndexError)):
        gate.layout(text)


@pytest.mark.parametrize('thumb,op', [(False,'bl'), (True,'blx')])
def test_same_arm_and_thumb_blx_accepted(thumb, op):
    dis = DOT + f'''02002000 <cds_matvec_self_check>:
 2002000: {'f000 e800' if thumb else 'eb000000'} {op} 1000200 <cds_matvec_fast>

'''
    result = gate.interworking(symbols(thumb), dis)
    assert result['direct_calls'][0]['isa'] == ('t->a' if thumb else 'a->a')


def test_thumb_plain_bl_to_arm_rejected():
    dis = DOT + '''02002000 <cds_matvec_self_check>:
 2002000: f000 f800 bl 1000200 <cds_matvec_fast>

'''
    with pytest.raises(AssertionError, match='unsafe ISA transition'):
        gate.interworking(symbols(True), dis)


@pytest.mark.parametrize('op,value,ok', [('blx','01000200',True), ('bx','01000200',True),
                                       ('mov pc,','01000200',False), ('blx','01000201',False)])
def test_literal_address_long_calls(op, value, ok):
    dis = DOT + f'''02002000 <cds_matvec_self_check>:
 2002000: e59fc004 ldr ip, [pc, #4] @ 200200c <cds_matvec_self_check+0xc>
 2002004: e12fff3c {op} ip
 200200c: {value} .word 0x{value}

'''
    if ok:
        result = gate.interworking(symbols(), dis)
        assert result['direct_calls'][0]['instruction'] == op
        assert result['direct_calls'][0]['literal_load'] == '0x2002000'
    else:
        with pytest.raises(AssertionError):
            gate.interworking(symbols(), dis)


def test_missing_asm_or_noninterworking_return_rejected():
    with pytest.raises(AssertionError):
        gate.interworking('', DOT)
    with pytest.raises(AssertionError, match='BX LR'):
        gate.interworking(symbols(), DOT.replace('bx lr', 'mov pc, lr') + '''02002000 <cds_matvec_self_check>:
 2002000: eb000000 bl 1000200 <cds_matvec_fast>
''')
