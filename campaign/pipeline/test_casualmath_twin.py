# SPDX-License-Identifier: MIT
"""ASan/UBSan C/Python differential grammar tests with guarded capacities."""
import pathlib
import random
import subprocess
import casualmath
import host_pipeline as hp
from test_casualmath import CALCS, NONCALCS


def test_casual_sanitized_twin(tmp_path):
    root = pathlib.Path(__file__).resolve().parents[2]
    src = tmp_path / 'casual.c'
    src.write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "prestep.h"
int main(void) {
    char line[1024];
    while (fgets(line, sizeof line, stdin)) {
        unsigned cap; int used;
        line[strcspn(line, "\n")] = 0;
        assert(sscanf(line, "%u\t%n", &cap, &used) == 1 && cap <= 256);
        char *q = line + used, *prev = strchr(q, '\t'); assert(prev); *prev++ = 0;
        unsigned char mem[260]; memset(mem, 0xa5, sizeof mem);
        int got = cds_casual_answer(q, prev, (char *)mem + 2, cap);
        assert(mem[0] == 0xa5 && mem[1] == 0xa5);
        for (unsigned i = cap + 2; i < sizeof mem; i++) assert(mem[i] == 0xa5);
        printf("%d\t%d\t", cds_casual_nonmath(q), got != 0);
        if (got) for (unsigned char *p = mem + 2; *p; p++) printf("%02x", *p);
        puts("");
    }
}
''')
    exe = tmp_path / 'casual'
    low = ['nice', '-n', '19', 'ionice', '-c3']
    subprocess.run(low + ['cc', '-std=c99', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-no-pie',
        '-I' + str(root / 'clean/include'), '-I' + str(root / 'clean/plumbing'), str(src),
        *[str(root / 'clean/plumbing' / p) for p in ['prestep.c', 'calc.c', 'textops.c', 'retrieve.c']],
        '-ffunction-sections', '-Wl,--gc-sections', '-o', str(exe)], check=True)
    rng = random.Random(430019)
    rows = [(256, q, '') for q, _ in CALCS]
    rows += [(256, 'half of 10 plus 4', ''), (256, 'half of a dozen minus 2', '')]
    rows += [(cap, q, prev) for cap in [0, 1, 16, 128, 256]
             for q in NONCALCS + ['42', '18.25 ugh', '12/4 + 1', '12/4 - 1', '18x7/2']
             for prev in ['', 'calc(12+8) = 20', 'calc(12+8) = 99']]
    # Shape-only veto parity: random group widths, separators and operator words.
    for i in range(500):
        groups = [''.join(rng.choices('0123456789', k=rng.randrange(1, 7)))
                  for _ in range(rng.randrange(2, 5))]
        q = rng.choice(['-', '/']).join(groups)
        q = rng.choice(['', 'what is ', 'CALL ', 'plus ', 'surplus ']) + q
        rows.append((256, q, rng.choice(['', 'calc(12+8) = 20'])))
    for i in range(6500):
        a, b = rng.randrange(1, 99), rng.randrange(1, 20)
        prev = rng.choice(['', f'calc({a}+{b}) = {a+b}', 'calc(4+3) = 99', 'calc(3/0) = error', 'x'*300])
        q = rng.choice([f'{a}x{b}', f'half of {a}/{b}', f'split {a} bucks {b} ways',
            f'{a} split between {b} people', f'{a} out of {b}', 'a dozen times seven',
            'two thousand and thirty plus four', 'now double it', f'and minus {b}', f'what about {b}',
            f'now add {b}', f'split it {b} ways', f'{a} ugh', f'{a} apples plus {b} oranges',
            'catch 22', 'reverse words 3 plus 8', 'what is 1984 about', 'python 4+7',
            ''.join(rng.choices("abcXYZ019_ .-+*/()\x01\x7f", k=rng.randrange(1, 150)))])
        q = rng.choice(['', 'hey uh ', 'ok now ', 'can you ']) + q + rng.choice(['', ' lol', ' please', ' and 9', ' not 4'])
        rows.append((rng.choice([0, 1, 16, 128, 256]), q, prev))
    p = subprocess.run(low + [str(exe)], input=''.join(f'{cap}\t{q}\t{prev}\n' for cap, q, prev in rows),
                       text=True, capture_output=True, timeout=90)
    assert p.returncode == 0 and not p.stderr, p.stderr
    expected = []
    for cap, q, prev in rows:
        out = casualmath.answer(q, hp.rt.apply_calc, prev)
        expected.append(str(int(casualmath.nonmath(q))) + '\t' +
                        ('1\t' + out.encode().hex() if out and len(out) < cap else '0\t'))
    actual = p.stdout.splitlines()
    assert len(actual) == len(rows)
    errors = [(rows[i], a, e) for i, (a, e) in enumerate(zip(actual, expected)) if a != e]
    assert not errors, errors[:15]
