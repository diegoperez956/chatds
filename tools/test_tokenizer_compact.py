# SPDX-License-Identifier: MIT
"""Packed tokenizer: exact one-allocation layout, byte lengths and failure cleanup."""
from pathlib import Path
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parents[1] / 'ds/tokenizer'


@pytest.fixture(scope='module')
def probe(tmp_path_factory):
    work = tmp_path_factory.mktemp('tokenizer-compact')
    source = work / 'probe.c'
    source.write_text(r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static size_t allocated;
static int refuse, calls, reads;
static void *file_malloc(size_t n) {
    allocated = n;
    ++calls;
    return refuse == 1 ? NULL : malloc(n);
}
static size_t file_read(void *p, size_t n, size_t z, FILE *f) {
    ++reads;
    if (refuse == 2 && reads == 264) return 0; /* second-pass header I/O */
    if (refuse == 3 && reads == 265) return 0; /* second-pass payload I/O */
    size_t got = fread(p, n, z, f);
    if (refuse == 4 && reads == 786 && got == 8) {
        /* Last record changed between passes: valid byte length, but exceeds
         * the remaining packed capacity. Must reject before writing payload. */
        unsigned char *h = p;
        h[4] = 254; h[5] = h[6] = h[7] = 0;
    }
    return got;
}
#define malloc file_malloc
#define fread file_read
#include "tok.c"
#undef malloc
#undef fread
int main(int argc, char **argv) {
    assert(argc == 3);
    refuse = atoi(argv[2]);
    for (int repeat = 0; repeat < 3; ++repeat) {
        tok_t t;
        calls = reads = 0;
        if (tok_load(&t, argv[1])) {
            assert(!t.buf && !t.piece && !t.len && !t.score && !t.sorted && !t.n);
            return 2;
        }
        assert(calls == 1 && sizeof *t.len == 1 && t.n == 262);
        size_t offset = 0;
        for (int i = 0; i < t.n; ++i) {
            assert(t.piece[i] == t.buf + offset);
            assert(t.score[i] == (float)i);
            offset += t.len[i];
        }
        size_t aligned = (offset + sizeof(void *) - 1) & ~(sizeof(void *) - 1);
        assert(allocated == aligned + (size_t)t.n *
               (sizeof *t.piece + sizeof *t.score + sizeof *t.sorted + sizeof *t.len));
        assert((uintptr_t)t.piece % sizeof(void *) == 0);
        assert((uintptr_t)t.score % sizeof(float) == 0);
        assert(t.len[259] == 255 && t.len[260] == 0 && t.len[261] == 3);
        for (int j = 0; j < 255; ++j) assert(t.piece[259][j] == (unsigned char)j);
        assert(!memcmp(t.piece[261], "a\0b", 3));
        int n = 0;
        const char *p = tok_piece(&t, 259, &n);
        assert(n == 255 && !memcmp(p, t.piece[259], 255));
        tok_free(&t);
        assert(!t.buf && !t.piece && !t.len && !t.score && !t.sorted && !t.n);
    }
    return 0;
}
''')
    binary = work / 'probe'
    subprocess.run(['cc', '-std=c99', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-no-pie',
                    '-I' + str(HERE), source, '-o', binary], check=True)
    return binary


def blob():
    pieces = [b'<unk>', b'<s>', b'</s>']
    pieces += [f'<0x{i:02X}>'.encode() for i in range(256)]
    pieces += [bytes(range(255)), b'', b'a\0b']
    return struct.pack('<I', 255) + b''.join(
        struct.pack('<fI', float(i), len(p)) + p for i, p in enumerate(pieces))


def test_compact_views_and_max_length(probe, tmp_path):
    path = tmp_path / 'tok.bin'
    path.write_bytes(blob())
    subprocess.run([probe, path, '0'], check=True)


@pytest.mark.parametrize('kind', ['oom', 'header-io', 'payload-io', 'changed-length',
                                  'truncated', 'length256', 'max256', 'fallback', 'empty'])
def test_compact_failure_cleanup(probe, tmp_path, kind):
    data = bytearray(blob())
    if kind == 'truncated':
        data = data[:-1]
    elif kind == 'length256':
        struct.pack_into('<I', data, 8, 256)
    elif kind == 'max256':
        struct.pack_into('<I', data, 0, 256)
    elif kind == 'fallback':
        data[data.index(b'<0x00>') + 4] = ord('1')
    elif kind == 'empty':
        data = b''
    path = tmp_path / 'tok.bin'
    path.write_bytes(data)
    mode = {'oom': 1, 'header-io': 2, 'payload-io': 3, 'changed-length': 4}.get(kind, 0)
    result = subprocess.run([probe, path, str(mode)], capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
    assert 'AddressSanitizer' not in result.stderr and 'runtime error:' not in result.stderr
