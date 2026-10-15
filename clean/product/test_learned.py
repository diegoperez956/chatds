"""Instrument the real loader: lazy reads, one SHA/load, cache and KV ownership."""
import ctypes as C
from pathlib import Path
import subprocess

import pytest

from test_product import assets

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / 'campaign/router/models'


class Text(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('op', 'start', 'end', 'xstart', 'xend',
                                      'ystart', 'yend', 'repeat', 'margin', 'tag_margin')]


@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    work = tmp_path_factory.mktemp('loader')
    wrapper = work / 'counts.c'
    wrapper.write_text('''
#include <stdio.h>
#include <string.h>
#include "router.h"
int reads[3], hashes;
FILE *__real_fopen(const char *, const char *);
FILE *__wrap_fopen(const char *p, const char *mode) {
    const char *names[] = {"round3-act.cdsr", "round3-op.cdsr", "round3-tag.cdsr"};
    for (int i = 0; i < 3; i++) if (strstr(p, names[i])) reads[i]++;
    return __real_fopen(p, mode);
}
void __real_cds_router_sha256(const uint8_t *, size_t, uint8_t *);
void __wrap_cds_router_sha256(const uint8_t *p, size_t n, uint8_t *out) {
    hashes++;
    __real_cds_router_sha256(p, n, out);
}
''')
    so = work / 'loader.so'
    sources = ['clean/src/format.c', 'clean/src/kernels.c', 'clean/src/engine.c',
               'clean/plumbing/router.c', 'clean/plumbing/round3.c',
               'clean/plumbing/textops.c', 'clean/plumbing/prestep.c',
               'clean/plumbing/calc.c', 'clean/product/learned.c']
    subprocess.run(['cc', '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-shared', '-fPIC', '-I' + str(ROOT / 'clean/include'),
                    '-I' + str(ROOT / 'clean/src'), '-I' + str(ROOT / 'clean/plumbing'),
                    *(str(ROOT / s) for s in sources), str(wrapper), '-lm',
                    '-Wl,--wrap=fopen,--wrap=cds_router_sha256', '-o', str(so)],
                   check=True, timeout=60)
    dll = C.CDLL(str(so))
    dll.chatds_model_load.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
    dll.chatds_session_create.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(C.c_void_p)]
    dll.chatds_session_reset.argtypes = [C.c_void_p]
    dll.chatds_session_destroy.argtypes = [C.c_void_p]
    dll.chatds_model_destroy.argtypes = [C.c_void_p]
    dll.c24_models_init.argtypes = [C.c_void_p, C.c_char_p]
    dll.c24_models_invalidate.argtypes = [C.c_void_p]
    dll.c24_act.argtypes = [C.c_void_p, C.c_char_p, C.POINTER(C.c_int32)]
    dll.c24_text.argtypes = [C.c_void_p, C.c_char_p, C.POINTER(Text), C.c_char_p, C.c_size_t]
    return dll


@pytest.fixture
def session(lib, tmp_path):
    model_path, _ = assets(tmp_path)
    m, s = C.c_void_p(), C.c_void_p()
    assert lib.chatds_model_load(str(model_path).encode(), C.byref(m)) == 0
    assert lib.chatds_session_create(m, None, C.byref(s)) == 0
    reads = (C.c_int * 3).in_dll(lib, 'reads')
    for i in range(3):
        reads[i] = 0
    C.c_int.in_dll(lib, 'hashes').value = 0
    # Keep directory bytes alive: product owns this string for its lifetime.
    directory = (str(MODELS) + '/').encode()
    assert lib.c24_models_init(s, directory) == 0
    yield s
    lib.c24_models_invalidate(s)
    lib.chatds_session_destroy(s)
    lib.chatds_model_destroy(m)


def counts(lib):
    return list((C.c_int * 3).in_dll(lib, 'reads')), C.c_int.in_dll(lib, 'hashes').value


def text(lib, s, q, cap=4096):
    result, out = Text(), C.create_string_buffer(cap)
    n = lib.c24_text(s, q, C.byref(result), out, cap)
    return n, bytes(result), out.value


def test_lazy_cache_and_reset(lib, session):
    s, margin = session, C.c_int32()
    assert counts(lib) == ([0, 0, 0], 0)  # initialization never touches card
    assert lib.c24_act(s, b'\x01', C.byref(margin)) == 0
    for q in (b'python print hello', b'open /tmp/file.txt', b'\x01', b''):
        assert text(lib, s, q)[0] == 0
    assert text(lib, s, b'hello', cap=128)[0] == 0
    assert counts(lib) == ([0, 0, 0], 0)

    assert lib.c24_act(s, b'u good?', C.byref(margin)) == 6
    first_margin = margin.value
    assert counts(lib) == ([1, 0, 0], 1)
    assert text(lib, s, b'hello')[0] == 0  # op declines: no tag read
    assert counts(lib) == ([1, 1, 0], 2)
    q = b"put the words of 'castle bridge' in reverse order"
    expected = text(lib, s, q)
    assert expected[0] > 0 and expected[2] == b'bridge castle'
    assert counts(lib) == ([1, 1, 1], 3)
    for _ in range(3):
        assert lib.c24_act(s, b'u good?', C.byref(margin)) == 6
        assert margin.value == first_margin
        assert text(lib, s, q) == expected
    assert counts(lib) == ([1, 1, 1], 3)  # no reread or SHA on warm turns

    # Same boundary used immediately before cds_gen_begin in dispatch.c.
    lib.c24_models_invalidate(s)
    lib.chatds_session_reset(s)
    assert text(lib, s, q) == expected
    assert counts(lib) == ([1, 2, 2], 5)  # only needed heads restored
    assert lib.c24_act(s, b'u good?', C.byref(margin)) == 6
    assert margin.value == first_margin
    assert counts(lib) == ([2, 2, 2], 6)


def test_cached_bytes_not_card_mutations(lib, session, tmp_path):
    # A validated in-memory snapshot survives card removal; reinitialization
    # starts a new load lifetime and must reject the now-truncated file.
    directory = (str(tmp_path) + '/').encode()
    dest = tmp_path / 'round3-act.cdsr'
    dest.write_bytes((MODELS / dest.name).read_bytes())
    assert lib.c24_models_init(session, directory) == 0
    margin = C.c_int32()
    assert lib.c24_act(session, b'u good?', C.byref(margin)) == 6
    dest.write_bytes(b'CDSR')
    assert lib.c24_act(session, b'u good?', C.byref(margin)) == 6
    assert counts(lib) == ([1, 0, 0], 1)
    assert lib.c24_models_init(session, directory) == 0
    assert lib.c24_act(session, b'u good?', C.byref(margin)) == -1
    assert counts(lib) == ([2, 0, 0], 1)  # short read rejected before SHA
