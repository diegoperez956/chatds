# SPDX-License-Identifier: MIT
import pathlib
import sys
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'clean/product'))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'corpus'))
import chatds_runtime as rt
import casualmath as cm
from test_narrowfix import answers, facts  # noqa: F401
from test_product import executable, invoke  # noqa: F401

CALCS = [
    ('one plus twenty', 'calc(1+20) = 21'),
    ('two hundred and thirty minus nineteen', 'calc(230-19) = 211'),
    ('one thousand two hundred divided by twenty', 'calc(1200/20) = 60'),
    ('a dozen times seven', 'calc(12*7) = 84'),
    ('half of 5/8', 'calc((5/2)/8) = 0.3125'),
    ('hey uh can u do 18x7 for me lol', 'calc(18*7) = 126'),
    ('9 out of 12', 'calc(9/12) = 0.75'),
    ('six squared', 'calc((6*6)) = 36'),
    ('four multiplied by eight', 'calc(4*8) = 32'),
    ('12 percent of 75', 'calc((12*75/100)) = 9'),
    ('split 84 bucks 7 ways', 'calc((84)/(7)) = 12'),
    ('84 split between seven people', 'calc((84)/(7)) = 12'),
    ('63 split between 9', 'calc((63)/(9)) = 7'),
    ('what is 12/4', 'calc(12/4) = 3'),
    ('12 - 5', 'calc(12-5) = 7'),
    ('555 minus 1234', 'calc(555-1234) = -679'),
    ('24/3', 'calc(24/3) = 8'),
    ('11-3?', 'calc(11-3) = 8'),
    ('12/25', 'calc(12/25) = 0.48'),
    ('506-32', 'calc(506-32) = 474'),
    ('67.04-14.5', 'calc(67.04-14.5) = 52.54'),
    ('555-1234 plus 2', 'calc(555-1234+2) = -677'),
    ('555-12345', 'calc(555-12345) = -11790'),
    ('5555-1234', 'calc(5555-1234) = 4321'),
]

@pytest.mark.parametrize('q,expected', CALCS)
def test_casual(q, expected):
    assert cm.answer(q, rt.apply_calc) == expected

@pytest.mark.parametrize('q,expected', [
    ('now double it', 'calc((20*2)) = 40'),
    ('and minus 3', 'calc(20-3) = 17'),
    ('what about 9', 'calc(12+9) = 21'),
    ('now add seven', 'calc((20)+(7)) = 27'),
    ('split it 4 ways', 'calc((20)/(4)) = 5'),
])
def test_follow(q, expected):
    assert cm.answer(q, rt.apply_calc, 'calc(12+8) = 20') == expected
    assert cm.answer(q, rt.apply_calc) is None

@pytest.mark.parametrize('q', ['catch 22', 'what is 1984 about', 'Is 5 in words?', 'who is 42', 'write python 8 plus 2',
    '9 apples minus 4 oranges', '5 and 7', 'one', 'split it ways', 'seven plus', 'minus',
    '10 plus 3 not 4', 'what about 7 plus 9', 'multiply it', 'print(3+2)', 'reverse words 3 plus 4'])
def test_decline(q):
    assert cm.answer(q, rt.apply_calc) is None


# Shared with full-product parity/ROM and the sanitized C twin.
NONCALCS = ['1984', '42', '18.25 ugh', '555-1234', '2024-03-05', '2024/03/05',
            'please 555-1234 thanks', 'what is 2024-03-05', 'calculate 555-123-4567',
            'call 444-9876', '42 please', '1-800-555-0199',
            'what is 555-1234', 'what is 2024/03/05', '1-2-3 plus 4']


@pytest.mark.parametrize('q,blocked', [
    ('2024-03-05', True), ('1-800-555-0199', True), ('1-2-3', True),
    ('2024/03/05', True), ('calculate 2024/03/05', True),
    ('555-1234', True), ('what is 555-1234', True),
    ('555-1234 PLUS 2', False), ('555 minus 1234', False),
    ('24/3', False), ('11-3?', False), ('12/25', False), ('12 - 5', False),
    ('5555-1234', False), ('555-12345', False), ('12024/03/05', False),
    ('2024/03/055', False), ('2024/3/5', False),
])
def test_shape_only_veto(q, blocked):
    assert cm.nonmath(q) is blocked


@pytest.mark.parametrize('q', NONCALCS)
def test_numeric_guards(q):
    assert cm.answer(q, rt.apply_calc) is None
    if '-' in q or '/' in q:
        assert cm.answer(q, rt.apply_calc, 'calc(12+8) = 20') is None


@pytest.mark.parametrize('q', ['1984', '42', '18.25 ugh', '42 please'])
def test_numeric_echo_needs_verified_context(q):
    expected = 'calc(' + q.split()[0] + ') = ' + q.split()[0]
    assert cm.answer(q, rt.apply_calc, 'calc(12+8) = 20') == expected
    assert cm.answer(q, rt.apply_calc, 'calc(12+8) = 99') is None


def test_half_precedence():
    assert cm.answer('half of 10 plus 4', rt.apply_calc) == 'calc((10/2)+4) = 9'
    assert cm.answer('half of a dozen minus 2', rt.apply_calc) == 'calc((12/2)-2) = 4'


@pytest.mark.parametrize('q,decoded', [
    ('555-1234', 'calc(555-1234) = -679'),
    ('2024-03-05', 'calc(2024-03-05) = 2016'),
    ('2024/03/05', 'calc(2024/03/05) = 134.9333'),
    ('1-800-555-0199', 'calc(1-800-555-0199) = -1553'),
    ('what is 555-1234', 'calc(555-1234) = -679'),
    ('1984', 'calc(1984) = 1984'),
    ('42', 'calc(42) = 42'),
])
def test_pipeline_no_legacy_or_decoder_bypass(executable, tmp_path, facts, q, decoded):
    # The shipped product has no decoder-injection seam, so only the route is checked.
    path, output = answers(executable, tmp_path, facts, [q])[0]
    assert path != 'calculator'
    assert output != decoded


def test_pipeline_context_and_frozen42(executable, tmp_path, facts):
    # Frozen cond-42 comparison needs the private harness; dropped. Follow-up context runs through the product.
    qs = ['12 plus 8', 'now double it', 'and minus 3', 'are you sure', 'now double it', 'thanks', 'and minus 4']
    result, _ = invoke(executable, tmp_path, 'steps=2\ninstruct=1\nprompt=hello\n', kb=facts,
                       serve='R\n' + ''.join(f'Q\t{q}\n' for q in qs))
    assert result.returncode == 0, result.stderr
    outputs = [line.split('\t')[2] for line in result.stdout.splitlines()]
    assert outputs[:3] == ['calc(12+8) = 20', 'calc((20*2)) = 40', 'calc(40-3) = 37']
    assert '40-3 = 37' in outputs[3]
    assert outputs[4] == 'calc((37*2)) = 74'
    assert outputs[6] == 'calc(74-4) = 70'
