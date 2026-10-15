# SPDX-License-Identifier: MIT
"""Lossless table decoding and independently owned lazy KB3 storage.

All probes use ASan/UBSan. No release assets or private evaluation fixtures.
"""
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
NICE = ['nice', '-n', '19', 'ionice', '-c3']
SAN = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']


def run(argv, **kw):
    result = subprocess.run([*NICE, *map(str, argv)], capture_output=True, text=True, timeout=120, **kw)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def fixture_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nfa_exhaustive_decode_and_poison(tmp_path):
    # Obtain the uncompressed Thompson graph, not expected values from the
    # packed table. --check also pins deterministic regeneration.
    code = """
import json, runpy, sys
sys.argv = ['gen_rules.py', '--check']
g = runpy.run_path(sys.argv[0])
print(json.dumps(dict(nodes=g['nodes'], patterns=g['patterns'])))
"""
    result = run([sys.executable, '-c', code], cwd=ROOT/'clean/product',
                 env=dict(os.environ, PYTHONHASHSEED='0'))
    expected = json.loads(result.stdout.splitlines()[-1])
    source = tmp_path/'nfa.c'
    source.write_text(r'''
#include <assert.h>
#include <stdio.h>
#include "rules.c"
int main(int argc, char **argv) {
    (void)argv;
    if (argc == 1) {
        for (unsigned i = 0; i < sizeof rx_nodes / sizeof *rx_nodes; ++i) {
            rx_node first = rx_decode(i), second = rx_decode(i);
            /* Poison one returned value. Neither immutable backing tables nor
             * another live decoded value may alias it. */
            first.a = first.b = 0xa5a5;
            rx_node again = rx_decode(i);
            assert(again.a == second.a && again.b == second.b);
            assert(first.a == 0xa5a5 && first.b == 0xa5a5);
            printf("%u %u\n", again.a, again.b);
        }
    } else {
        char line[256];
        while (fgets(line, sizeof line, stdin)) {
            unsigned id; int n;
            assert(sscanf(line, "%u\t%n", &id, &n) == 1 && id < RX_COUNT);
            line[strcspn(line, "\n")] = 0;
            printf("%d\n", rx((int)id, line + n));
        }
    }
    return 0;
}
''')
    executable = tmp_path/'nfa'
    run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', *SAN,
         '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
         '-I'+str(ROOT/'clean/product'), '-I'+str(ROOT/'clean/plumbing'),
         '-I'+str(ROOT/'clean/include'), source, '-o', executable])
    actual = [tuple(map(int, line.split())) for line in run([executable]).stdout.splitlines()]
    assert actual == [(a | (op << 13), arg if op == 1 else b)
                      for a, b, arg, op in expected['nodes']]
    assert len(actual) == 4060
    # Regex oracle exercises the packed decoder on authored/random ASCII,
    # including boundary assertions and cyclic split closures.
    rng = random.Random(240608)
    phrases = ['hello', 'what is 2+3', 'python [1]', 'thanks a lot',
               'tell me about mercury', 'graph sin x', 'plot x squared',
               'reverse words hello world', 'good morning', 'file.txt']
    phrases += [''.join(rng.choices('abxyz0123 _+*/().-', k=rng.randrange(128))) for _ in range(200)]
    cases = [(i, phrase, bool(re.search(pattern, phrase)))
             for i, pattern in enumerate(expected['patterns'].values()) for phrase in phrases]
    result = run([executable, 'regex'], input=''.join(f'{i}\t{s}\n' for i, s, _ in cases))
    assert list(map(int, result.stdout.splitlines())) == [int(ok) for _, _, ok in cases]


@pytest.fixture(scope='module')
def sanitized_product(tmp_path_factory):
    work = tmp_path_factory.mktemp('stack-product-asan')
    source = work/'product_probe.c'
    source.write_text(r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static void *tracked_calloc(size_t n, size_t size);
static void tracked_free(void *p);
#define calloc tracked_calloc
#define free tracked_free
#define main product_main
#include "main.c"
#undef calloc
#undef free
#undef main
static void *legacy;
static unsigned allocations, releases;
static void disjoint(const void *p, size_t size, const void *q, size_t other) {
    uintptr_t a = (uintptr_t)p, b = (uintptr_t)q;
    assert(a + size <= b || b + other <= a);
}
static void *tracked_calloc(size_t n, size_t size) {
    void *p = calloc(n, size);
    if (p && n * size == sizeof(cds_kb)) {
        assert(!legacy);
        legacy = p; ++allocations;
        disjoint(p, sizeof(cds_kb), &runtime, sizeof runtime);
        disjoint(p, sizeof(cds_kb), &generator, sizeof generator);
        disjoint(p, sizeof(cds_kb), answer_text, sizeof answer_text);
        disjoint(p, sizeof(cds_kb), output_ids, sizeof output_ids);
    }
    return p;
}
static void tracked_free(void *p) {
    if (p && p == legacy) {
        /* Close already completed. Poison on release; ASan catches any later
         * legacy-reader access or a dangling generator/publication alias. */
        memset(p, 0xa5, sizeof(cds_kb)); legacy = NULL; ++releases;
    }
    free(p);
}
int main(int argc, char **argv) {
    int rc = product_main(argc, argv);
    unsigned expected = (unsigned)atoi(getenv("STACK_EXPECT_KB3"));
    assert(allocations == expected && releases == expected && !legacy);
    fprintf(stderr, "KB3 allocations=%u releases=%u; disjoint/poison passed\n", allocations, releases);
    return rc;
}
''')
    # Read the public build's explicit source allowlist from its dry-run compile
    # commands rather than silently adding a different pipeline to the probe.
    commands = run(['make', '-j2', '-B', '-n', 'host'], cwd=ROOT/'clean/product').stdout.splitlines()
    sources = []
    for line in commands:
        args = shlex.split(line)
        if '-c' in args:
            p = (ROOT/'clean/product'/args[args.index('-c')+1]).resolve()
            sources.append(source if p.name == 'main.c' else p)
    assert len(sources) > 30
    executable = work/'product'
    includes = [ROOT/'clean'/p for p in ('include', 'src', 'plumbing', 'ui/include')]
    includes += [ROOT/'ds/tokenizer', ROOT/'clean/product']
    run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', *SAN,
         *['-I'+str(p) for p in includes], *sources, '-lm', '-o', executable])
    return executable


@pytest.mark.parametrize('kind', ['kb4', 'kb3', 'missing', 'corrupt-kb4', 'corrupt-kb3'])
def test_lazy_kb3_owned_lifetime(sanitized_product, tmp_path, kind, monkeypatch):
    sys.path.insert(0, str(ROOT/'corpus/kb'))
    import build_kb, build_kb4, kb4_scan
    product = fixture_module(ROOT/'clean/product/test_product.py', 'stack_product_fixture')
    kb = tmp_path/('kb4.bin' if 'kb4' in kind else 'kb.bin')
    if kind == 'kb4':
        pages = tmp_path/'pages.jsonl.gz'
        kb4_scan.scan(str(ROOT/'corpus/kb/fixtures/kb4_mini.xml'), str(pages))
        build_kb4.build(str(pages), str(kb), 'test', entities_path=str(tmp_path/'entities.jsonl.gz'))
    elif kind == 'kb3':
        build_kb.build(str(ROOT/'corpus/kb/fixtures/mini.xml'), str(kb), 'test')
    elif kind.startswith('corrupt'):
        kb.write_bytes(b'broken')
    expected = int(kind in ('kb3', 'missing', 'corrupt-kb3'))
    monkeypatch.setenv('STACK_EXPECT_KB3', str(expected))
    script = 'R\nQ\twhat is paris\nQ\tgraph sin x\nQ\twhat is 2+3\nQ\tpython hello\nQ\twhat is paris\n'
    result, _ = product.invoke(sanitized_product, tmp_path,
                              'steps=2\nkbd=0\ninstruct=1\nprompt=hello\n', kb=kb, serve=script)
    assert f'KB3 allocations={expected} releases={expected}; disjoint/poison passed' in result.stderr
    assert ('AddressSanitizer' not in result.stderr and 'runtime error:' not in result.stderr)
    if kind.startswith('corrupt'):
        assert result.returncode != 0
    else:
        assert result.returncode == 0, result.stderr
        rows = [line.split('\t') for line in result.stdout.splitlines()]
        assert len(rows) == 5
        assert rows[1][1:3] == ['mathnb', 'Pocket math: plot (129 points).']
        assert rows[2][1] == 'calculator'
        if kind == 'kb3':
            assert rows[0][3] and rows[0][3] == rows[4][3]
