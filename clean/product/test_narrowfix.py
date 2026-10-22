# SPDX-License-Identifier: MIT
"""Executable product contrasts: explicit self-capabilities and literal lengths."""
import importlib.util
import random
import subprocess
import sys

import pytest

from test_product import ROOT, invoke, executable  # noqa: F401

CAPABILITIES = "i can help with facts, math, python, shell and text."
BARE_LENGTH_FACTS = [
    'how long is the ming', 'how long is the blorp', 'how long is the zzyzx',
    'how long is the durn', 'how long is the vorpal', 'how long is the snark',
    'how long is the quux', 'how long is the flindle', 'how long is the wobble',
    'how long is the danub', 'HOW LONG IS THE NIL?',
]


@pytest.fixture(scope='module')
def facts(tmp_path_factory):
    sys.path.insert(0, str(ROOT / 'corpus/kb'))
    import build_kb4, kb4_scan
    work = tmp_path_factory.mktemp('narrowfix-kb')
    pages, kb = work / 'pages.jsonl.gz', work / 'kb4.bin'
    xml = work / 'fixture.xml'
    original = (ROOT / 'corpus/kb/fixtures/kb4_mini.xml').read_text()
    xml.write_text(original.replace('</mediawiki>', '''
<page><title>Nile</title><ns>0</ns><id>1000</id><revision><text>
''' + "'''Nile''' is a major river in northeastern Africa. It flows north into the Mediterranean Sea." + '''
</text></revision></page></mediawiki>'''))
    kb4_scan.scan(str(xml), str(pages))
    build_kb4.build(str(pages), str(kb), 'test', entities_path=str(work / 'entities.jsonl.gz'))
    return kb


def answers(executable, tmp_path, facts, queries):
    result, _ = invoke(executable, tmp_path, 'steps=2\ninstruct=1\nprompt=hello\n', kb=facts,
                       serve=''.join(f'R\nQ\t{q}\n' for q in queries))
    assert result.returncode == 0, result.stderr
    return [line.split('\t')[1:3] for line in result.stdout.splitlines()]


@pytest.mark.parametrize('query', [
    'how do you work!', 'HOW DO YOU WORK?', 'what do you help with',
    'what can you help me with?', 'what are your capabilities?',
])
def test_explicit_capabilities(executable, tmp_path, facts, query):
    assert answers(executable, tmp_path, facts, [query]) == [['template', CAPABILITIES]]


@pytest.mark.parametrize('query,expected', [
    ('length of blorp', None),
    ('Length of blorp?', None),
    ('how long is the word blorp', '5 characters'),
    ('length of the string "a b!"', '4 characters'),
    ('how long is the word france', '6 characters'),
    ('how long is the word nile', '4 characters'),
    ('length of the text "World War II"', '12 characters'),
])
def test_explicit_literal_length(executable, tmp_path, facts, query, expected):
    got = answers(executable, tmp_path, facts, [query])[0]
    if expected is None:
        # Tiny test model cannot generate len(...); assert the real dispatch
        # reaches that backend rather than publishing a missing-fact template.
        assert got[0] == 'transformer'
    else:
        assert got == ['text_exact', expected]


@pytest.mark.parametrize('query,path,answer', [
    ('help()', 'template', CAPABILITIES),
    ('what does help do in python', 'transformer', None),
    ('how does python work', 'transformer', None),
    ('what do you help with in python', 'transformer', None),
    ('how do you work with lists', 'transformer', None),
    ('how long is france', 'template', "i don't have that detail in my offline facts."),
    ('how long is the nile', 'template', "i don't have that detail in my offline facts."),
    ('length of the nile', 'template', "i don't have that detail in my offline facts."),
    ('how long is "the nile"', 'transformer', None),
    ('length of world war ii', 'template', "i don't have that detail in my offline facts."),
    ('how long did world war ii last', 'kb_direct', 'from 1 September 1939 to 2 September 1945.'),
])
def test_must_not_change(executable, tmp_path, facts, query, path, answer):
    got = answers(executable, tmp_path, facts, [query])[0]
    assert got[0] == path
    if 'nile' in query:
        debug = dict(field.split('=', 1) for field in (tmp_path / 'out/debug.log').read_text().split())
        assert debug['handler'] == '0'  # H_FACTS, not the len/code backend
    if answer is not None:
        assert got[1] == answer
    else:
        assert got[1] != CAPABILITIES


@pytest.mark.parametrize('query', BARE_LENGTH_FACTS)
def test_bare_length_stays_factual(executable, tmp_path, facts, query):
    got = answers(executable, tmp_path, facts, [query])[0]
    debug = dict(field.split('=', 1) for field in (tmp_path / 'out/debug.log').read_text().split())
    assert debug['handler'] == '0'  # H_FACTS; never len/code extraction
    assert got[0] == 'transformer'  # unresolved fixture entity retains factual fallback


# Dropped test_bare_length_python_pipeline_unchanged: it diffed two private harness conditions;
# test_bare_length_stays_factual above already pins the shipped product's facts route.


def test_length_literal_twin_and_bounds(tmp_path):
    """ASan/UBSan parser contrasts, malformed bytes, capacities and editor limit."""
    spec = importlib.util.spec_from_file_location('narrowfix_textops', ROOT / 'campaign/pipeline/textops.py')
    twin = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = twin
    spec.loader.exec_module(twin)
    source = tmp_path / 'length.c'
    source.write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "textops.h"
int main(void) {
    char q[512];
    while (fgets(q, sizeof q, stdin)) {
        unsigned cap; int used;
        assert(sscanf(q, "%u\t%n", &cap, &used) == 1 && cap <= 128);
        q[strcspn(q, "\n")] = 0;
        unsigned char out[132]; memset(out, 0xa5, sizeof out);
        int kind = cds_textops_length_literal(q + used, (char *)out + 2, cap);
        assert(out[0] == 0xa5 && out[1] == 0xa5);
        for (unsigned i = cap + 2; i < sizeof out; i++) assert(out[i] == 0xa5);
        printf("%d\t", kind);
        if (kind) for (unsigned i = 2; out[i]; i++) printf("%02x", out[i]);
        puts("");
    }
}
''')
    executable = tmp_path / 'length'
    low = ['nice', '-n', '19', 'ionice', '-c3']
    subprocess.run(low + ['cc', '-std=c99', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-no-pie',
        '-I' + str(ROOT / 'clean/plumbing'), str(source), str(ROOT / 'clean/plumbing/textops.c'),
        '-o', str(executable)], check=True)
    rng = random.Random(912527)
    heads = ['length of ', 'the length of ', 'how long is ', 'length ', 'how long did ', '']
    nouns = ['', 'the ', 'word ', 'the word ', 'string ', 'text ', 'the text ']
    tails = ['blorp', 'nile', 'it', 'python', 'hello world', '"a b!"', "'a b?'", '"unterminated',
             '[1,2]', '  ', 'x' * 110, 'x' * 127, 'x' * 128, '\x01', '\x7f']
    queries = [(rng.choice([0, 1, 5, 128]), rng.choice(heads) + rng.choice(nouns) + rng.choice(tails)
                + rng.choice(['', '?', '!', '. ', '??'])) for _ in range(6000)]
    queries += [(128, 'how long is the word ' + 'x' * n) for n in range(100, 130)]
    queries += [(128, q) for q in BARE_LENGTH_FACTS]
    for q in BARE_LENGTH_FACTS:
        assert twin.length_literal(q) is None
    p = subprocess.run(low + [str(executable)], input=''.join(f'{cap}\t{q}\n' for cap, q in queries),
                       text=True, capture_output=True, timeout=30)
    assert p.returncode == 0, p.stderr
    actual = p.stdout.splitlines()
    expected = []
    for cap, q in queries:
        parsed = twin.length_literal(q)
        if parsed and len(parsed[0]) < cap:
            expected.append(f'{1 if parsed[1] else 2}\t{parsed[0].encode().hex()}')
        else:
            expected.append('0\t')
    assert actual == expected
