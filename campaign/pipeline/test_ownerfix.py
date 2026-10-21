# SPDX-License-Identifier: MIT
"""Owner grammar behavior and full-product tests, with generated contrasts."""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'router'))
import pytest
import ownerfix


@pytest.mark.parametrize('q', ['who r u?', 'whats ur name', 'yo who are u pls', 'who built u',
                               'WHO R YOU?', 'hey what is ur name tho', 'introduce yourself please'])
def test_identity(q):
    assert ownerfix.identity(q)


@pytest.mark.parametrize('q', ['who are ur friends', 'who r ada', 'who made ubuntu',
                               'python who r u', 'who are you working with', 'who are you()'])
def test_identity_contrasts(q):
    assert not ownerfix.identity(q)


@pytest.mark.parametrize('q,expected', [("caps 'fern8' pls", ('upper', 'FERN8')),
    ('CAPITALS "a b!" please', ('upper', 'A B!')),
    ('caps france', None), ('caps python "a"', None), ('caps \'broken', None),
    ('caps "a" and lowercase "b"', None)])
def test_caps(q, expected):
    assert ownerfix.text(q) == expected


@pytest.mark.parametrize('head', ['reverse words', 'flip words', 'reverse the words in',
    'reverse word order of', 'flip the order of the words in', 'reverse words:'])
def test_reverse_words(head):
    assert ownerfix.text(head + " 'zebra apple kite7' pls") == ('reverse_words', 'kite7 apple zebra')


@pytest.mark.parametrize('q', ['reverse psychology', 'flip words in python',
    'what does reverse words mean', 'reverse words in the bible'])
def test_reverse_contrasts(q):
    assert ownerfix.text(q) is None


@pytest.mark.parametrize('verb', ['put', 'place', 'arrange'])
def test_reverse_tail(verb):
    assert ownerfix.text(f'{verb} the words of "zebra apple kite7" in reverse order pls') == ('reverse_words', 'kite7 apple zebra')


@pytest.mark.parametrize('a,b', [(17, 6), (40, 9), (3, 12)])
def test_grounded_math(a, b):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'corpus'))
    import chatds_runtime as rt
    q = f'whats {a} plus {b} tho'
    answer = f'calc({a}+{b}) = {a+b}'
    assert ownerfix.calc(q, rt.apply_calc) == answer
    assert ownerfix.grounded(q, answer, rt.apply_calc)
    assert not ownerfix.grounded(q, f'calc({a}+{b}{b}) = {a+int(str(b)*2)}', rt.apply_calc)
    assert ownerfix.calc(f'what is {a} apples plus {b} tho', rt.apply_calc) is None
    assert ownerfix.calc(f'could you {a}+{b} for me', rt.apply_calc) == answer
    assert ownerfix.calc(f'math: {a}+{b}', rt.apply_calc) == answer
    assert ownerfix.calc(f'arithmetic: {a} plus {b} pls', rt.apply_calc) == answer


GROUNDED_CALCS = [
    ('what is 7 times 8 in total', 'calc(7*8) = 56'),
    ('7 times 8 equals what', 'calc(7*8) = 56'),
    ('20 minus 7 lol', 'calc(20-7) = 13'),
    ('um what is 4 plus 4', 'calc(4+4) = 8'),
    ('what is 7 times 8 in words', 'calc(7*8) = 56'),
    ('How many is 150 divided by 5?', 'calc(150/5) = 30'),
    ('what is 20 minus 7 lol', 'calc(20-7) = 13'),
    ('9 apples minus 4 oranges', 'calc(9-4) = 5'),
]
UNGROUNDED_CALCS = [
    ('whats 9 minus 4 exactly', 'calc(9-4-44) = -39'),
    ('catch 22', 'calc(22/2) = 11'),
    ('what is catch 22 about', 'calc(22/2) = 11'),
    ('9 minus 4', 'calc(9+4) = 13'),
    ('9 minus 4 and 44', 'calc(9-4) = 5'),
    ('9 minus 4', 'calc(9-4) = 6'),
    ('write python 9 minus 4', 'calc(9-4) = 5'),
]


@pytest.mark.parametrize('q,answer,expected',
    [(q, a, True) for q, a in GROUNDED_CALCS] + [(q, a, False) for q, a in UNGROUNDED_CALCS])
def test_decoded_grounding(q, answer, expected):
    import host_pipeline as hp
    assert ownerfix.grounded(q, answer, hp.rt.apply_calc) is expected


def test_calc_prefix():
    import host_pipeline as hp
    assert ownerfix.calc('um what is 4 plus 4', hp.rt.apply_calc) == 'calc(4+4) = 8'
    assert ownerfix._prefix('hey um so 4 plus 4') is None
    # General math-span parsing can still prove the complete arithmetic.
    assert ownerfix.calc('hey um so 4 plus 4', hp.rt.apply_calc) == 'calc(4+4) = 8'
    for q, answer in GROUNDED_CALCS[:7]:
        assert ownerfix.calc(q, hp.rt.apply_calc) == answer


@pytest.mark.parametrize('q,expected', [('quick question capital of peru?', 'capital of peru?'),
    ('hey, uh what is oxygen?', 'what is oxygen?'), ('yo capital of egypt', 'capital of egypt'),
    ('uh reverse words "a b"', None), ('quick q who r u', None), ('hey python print 3', None),
    ('hey so uh capital of peru', None), ('quick queen', None)])
def test_fact_prefix(q, expected):
    import host_pipeline as hp
    assert ownerfix.fact(q, hp) == expected


def test_asan_twin_fuzz(tmp_path):
    import random
    import subprocess
    import host_pipeline as hp
    root = pathlib.Path(__file__).resolve().parents[2]
    source = tmp_path / 'owner-fuzz.c'
    source.write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "ownerfix.h"
#include "textops.h"
int main(void) {
    char q[600];
    while (fgets(q, sizeof q, stdin)) {
        q[strcspn(q, "\n")] = 0;
        unsigned cap; int used;
        assert(sscanf(q, "%u\t%n", &cap, &used) == 1 && cap <= 256);
        unsigned char mem[260]; memset(mem, 0xa5, sizeof mem);
        char *out = (char *)mem + 2, *s = q + used + 2;
        int op = -1, got = 0;
        switch (q[used]) {
        case 'I': got = owner_identity(s); break;
        case 'T': got = owner_text(s, out, cap, &op); break;
        case 'C': got = owner_calc(s, out, cap); break;
        case 'F': got = owner_fact(s, out, cap); break;
        case 'G': {
            char *a = strchr(s, '\t'); assert(a); *a++ = 0;
            got = owner_grounded(s, a); break;
        }
        }
        assert(mem[0] == 0xa5 && mem[1] == 0xa5);
        for (unsigned i = cap + 2; i < sizeof mem; i++) assert(mem[i] == 0xa5);
        printf("%d\t", got != 0);
        if (got && q[used] != 'I' && q[used] != 'G') {
            if (op >= 0) printf("%s:", cds_textops_name(op));
            for (unsigned char *p = mem + 2; *p; p++) printf("%02x", *p);
        }
        puts("");
    }
}
''')
    exe = tmp_path / 'owner-fuzz'
    low = ['nice', '-n', '19', 'ionice', '-c3']
    subprocess.run(low + ['cc', '-std=c99', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-no-pie',
        '-I' + str(root / 'clean/product'), '-I' + str(root / 'clean/plumbing'), '-I' + str(root / 'clean/include'),
        str(source), *[str(root / p) for p in ('clean/product/ownerfix.c', 'clean/product/rules.c',
            'clean/plumbing/prestep.c', 'clean/plumbing/textops.c', 'clean/plumbing/calc.c', 'clean/plumbing/retrieve.c')],
        '-ffunction-sections', '-Wl,--gc-sections', '-o', str(exe)], check=True)
    rng = random.Random(420087)
    queries = []
    for i in range(12000):
        literal = ''.join(rng.choices('abcdefgXYZ 0123_-.', k=rng.randrange(1, 100)))
        tail = rng.choice(['', '?', ' pls', ' please!', ' tho', ' for me', ' and python', '()', '\x01', '\x7f'])
        q = rng.choice(['caps ', 'CAPITALS ', 'reverse words ', 'flip words: ', 'reverse the word order of ',
                        'reverse the order of the words in ', 'hey quick q capital of ', 'who r ', 'whats ', ''])
        q += rng.choice([f'"{literal}"', literal, f'{rng.randrange(90)} plus {rng.randrange(9)}', 'u', 'ur name']) + tail
        queries.append((rng.choice('ITCF'), rng.choice([0, 1, 16, 128, 256]), q))
    queries += [(kind, 256, q) for kind in 'ITCF' for q in ['who r u?', 'introduce yourself please',
        'hey, uh what is oxygen?', 'hey so uh capital of peru', 'caps "fern8" pls', "flip words 'zebra apple kite' pls",
        'whats 17 plus 6 tho', 'math: 17+6', 'arithmetic: 19 minus 8', 'python ' + 'x' * 125, 'x' * 128]]
    queries += [('G', 256, q + '\t' + a) for q, a in GROUNDED_CALCS + UNGROUNDED_CALCS]
    for _ in range(1000):
        a, b = rng.randrange(1, 999), rng.randrange(1, 99)
        q = f'um what is {a} times {b} in total'
        queries += [('G', 256, q + f'\tcalc({a}*{b}) = {a*b}'),
                    ('G', 256, q + f'\tcalc({a}*{b}+1) = {a*b+1}')]
    p = subprocess.run(low + [str(exe)], input=''.join(f'{cap}\t{kind}\t{q}\n' for kind, cap, q in queries),
        text=True, capture_output=True, timeout=90)
    assert p.returncode == 0, p.stderr
    expected = []
    for kind, cap, q in queries:
        op = ''
        if kind == 'G': value = ownerfix.grounded(*q.split('\t'), hp.rt.apply_calc)
        elif kind == 'I': value = ownerfix.identity(q)
        elif kind == 'T':
            r = ownerfix.text(q) if cap >= 256 else None
            value = r[1] if r else None
            op = r[0] + ':' if r else ''
        elif kind == 'C': value = ownerfix.calc(q, hp.rt.apply_calc)
        else: value = ownerfix.fact(q, hp)
        if isinstance(value, str) and len(value) >= cap: value = None
        expected.append(('1\t' + op + value.encode().hex()) if isinstance(value, str) else '1\t' if value else '0\t')
    actual = p.stdout.splitlines()
    assert len(actual) == len(expected)
    errors = [(queries[i], a, e) for i, (a, e) in enumerate(zip(actual, expected)) if a != e]
    assert not errors, errors[:12]
