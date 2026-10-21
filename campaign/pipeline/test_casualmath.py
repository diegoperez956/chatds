# SPDX-License-Identifier: MIT
import pathlib
import sys
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'clean/product'))
import host_pipeline as hp
import casualmath as cm
from test_narrowfix import facts  # noqa: F401

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
    assert cm.answer(q, hp.rt.apply_calc) == expected

@pytest.mark.parametrize('q,expected', [
    ('now double it', 'calc((20*2)) = 40'),
    ('and minus 3', 'calc(20-3) = 17'),
    ('what about 9', 'calc(12+9) = 21'),
    ('now add seven', 'calc((20)+(7)) = 27'),
    ('split it 4 ways', 'calc((20)/(4)) = 5'),
])
def test_follow(q, expected):
    assert cm.answer(q, hp.rt.apply_calc, 'calc(12+8) = 20') == expected
    assert cm.answer(q, hp.rt.apply_calc) is None

@pytest.mark.parametrize('q', ['catch 22', 'what is 1984 about', 'Is 5 in words?', 'who is 42', 'write python 8 plus 2',
    '9 apples minus 4 oranges', '5 and 7', 'one', 'split it ways', 'seven plus', 'minus',
    '10 plus 3 not 4', 'what about 7 plus 9', 'multiply it', 'print(3+2)', 'reverse words 3 plus 4'])
def test_decline(q):
    assert cm.answer(q, hp.rt.apply_calc) is None


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
    assert cm.answer(q, hp.rt.apply_calc) is None
    if '-' in q or '/' in q:
        assert cm.answer(q, hp.rt.apply_calc, 'calc(12+8) = 20') is None


@pytest.mark.parametrize('q', ['1984', '42', '18.25 ugh', '42 please'])
def test_numeric_echo_needs_verified_context(q):
    expected = 'calc(' + q.split()[0] + ') = ' + q.split()[0]
    assert cm.answer(q, hp.rt.apply_calc, 'calc(12+8) = 20') == expected
    assert cm.answer(q, hp.rt.apply_calc, 'calc(12+8) = 99') is None


def test_half_precedence():
    assert cm.answer('half of 10 plus 4', hp.rt.apply_calc) == 'calc((10/2)+4) = 9'
    assert cm.answer('half of a dozen minus 2', hp.rt.apply_calc) == 'calc((12/2)-2) = 4'


@pytest.mark.parametrize('q,decoded', [
    ('555-1234', 'calc(555-1234) = -679'),
    ('2024-03-05', 'calc(2024-03-05) = 2016'),
    ('2024/03/05', 'calc(2024/03/05) = 134.9333'),
    ('1-800-555-0199', 'calc(1-800-555-0199) = -1553'),
    ('what is 555-1234', 'calc(555-1234) = -679'),
    ('1984', 'calc(1984) = 1984'),
    ('42', 'calc(42) = 42'),
])
def test_pipeline_no_legacy_or_decoder_bypass(facts, q, decoded):
    class Gen:
        def gen(self, ctx, q):
            return dict(output=decoded, status='OK', stop='', prompt_tokens=0,
                        ctx_tokens=0, gen_tokens=0, trimmed=0, calc=1, prompt='')
    pl = hp.Pipeline(hp.CONDS[43], kb4_path=str(facts), gen=Gen())
    try:
        row = hp.run_case(pl, dict(case_id='guard', turns=[dict(user=q)]))['outputs'][0]
        assert row['output'] != decoded
        assert row['path'] != 'calculator'
    finally:
        pl.kb4.close()


def test_pipeline_context_and_frozen42(facts):
    class Gen:
        def gen(self, ctx, q):
            return dict(output='fallback', status='OK', stop='', prompt_tokens=0,
                        ctx_tokens=0, gen_tokens=0, trimmed=0, calc=0, prompt='')
    old = hp.Pipeline(hp.CONDS[42], kb4_path=str(facts), gen=Gen())
    new = hp.Pipeline(hp.CONDS[43], kb4_path=str(facts), gen=Gen())
    try:
        assert hp.run_case(old, dict(case_id='old', turns=[dict(user='split 84 between seven')]))['outputs'][0]['output'] != 'calc((84)/(7)) = 12'
        case = dict(case_id='follow', turns=[dict(user=q) for q in ['12 plus 8', 'now double it', 'and minus 3', 'are you sure', 'now double it', 'thanks', 'and minus 4']])
        rows = hp.run_case(new, case)['outputs']
        assert [r['output'] for r in rows[:3]] == ['calc(12+8) = 20', 'calc((20*2)) = 40', 'calc(40-3) = 37']
        assert '40-3 = 37' in rows[3]['output']
        assert rows[4]['output'] == 'calc((37*2)) = 74'
        assert rows[6]['output'] == 'calc(74-4) = 70'
    finally:
        old.kb4.close(); new.kb4.close()
