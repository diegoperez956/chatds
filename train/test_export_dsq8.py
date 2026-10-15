"""Public synthetic round trips; optional release parity with explicitly supplied assets.
No upstream converter, private campaign harness, checkpoint or GPU is required.
"""
import ctypes, hashlib, json, os, pathlib, struct, subprocess, sys

import numpy as np
import pytest

torch = pytest.importorskip('torch', reason='optional CPU exporter dependency')

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import export_dsq8  # noqa: E402

@pytest.mark.skipif(not all(os.environ.get(k) for k in
                           ('CHATDS_EXPORT_CKPT', 'CHATDS_EXPORT_TOK', 'CHATDS_EXPORT_RELEASE')),
                    reason='optional release checkpoint/tokenizer/model not supplied')
def test_byte_identical_to_release():
    ckpt, tok, release = (pathlib.Path(os.environ[k]) for k in
                         ('CHATDS_EXPORT_CKPT', 'CHATDS_EXPORT_TOK', 'CHATDS_EXPORT_RELEASE'))
    blob, _ = export_dsq8.export(ckpt, tok)
    assert blob == release.read_bytes()
    assert export_dsq8.export(ckpt, tok)[0] == blob


# ---------------------------------------------------------------- (c) synthetic model, always runs
DIM, HID, LAYERS, HEADS, KV, VOCAB, CTX = 64, 128, 2, 4, 2, 128, 32


def make_ckpt(path, seed=0):
    g = torch.Generator().manual_seed(seed)
    r = lambda *s: torch.randn(*s, generator=g) * 0.15
    kvd = DIM // HEADS * KV
    sd = {"tok_embeddings.weight": torch.randn(VOCAB, DIM, generator=g) * 0.5}
    for l in range(LAYERS):
        p = f"layers.{l}."
        sd.update({p + "attention.wq.weight": r(DIM, DIM), p + "attention.wk.weight": r(kvd, DIM),
                   p + "attention.wv.weight": r(kvd, DIM), p + "attention.wo.weight": r(DIM, DIM),
                   p + "feed_forward.w1.weight": r(HID, DIM), p + "feed_forward.w2.weight": r(DIM, HID),
                   p + "feed_forward.w3.weight": r(HID, DIM),
                   p + "attention_norm.weight": 1 + 0.2 * torch.randn(DIM, generator=g),
                   p + "ffn_norm.weight": 1 + 0.2 * torch.randn(DIM, generator=g)})
    sd["norm.weight"] = 1 + 0.2 * torch.randn(DIM, generator=g)
    sd["output.weight"] = sd["tok_embeddings.weight"]
    torch.save({"model": sd, "model_args": dict(dim=DIM, n_layers=LAYERS, n_heads=HEADS, n_kv_heads=KV,
                vocab_size=VOCAB, multiple_of=32, max_seq_len=CTX, dropout=0.0)}, path)
    return sd


def fake_tok(path, n=VOCAB):
    path.write_bytes(struct.pack("<I", 2) + b"".join(struct.pack("<fI", 0.0, 2) + b"%02d" % (i % 100) for i in range(n)))


def float_forward(sd, toks):
    f = lambda k: sd[k].double().numpy()
    hs = DIM // HEADS
    inv = 10000.0 ** (-np.arange(0, hs, 2) / hs)
    rms = lambda x, w: x / np.sqrt((x * x).mean() + 1e-5) * w
    def rope(v, pos):
        v = v.reshape(-1, hs // 2, 2).copy(); a = pos * inv
        c, s = np.cos(a), np.sin(a)
        x, y = v[..., 0].copy(), v[..., 1].copy()
        v[..., 0], v[..., 1] = x * c - y * s, x * s + y * c
        return v.reshape(-1)
    kc = [[] for _ in range(LAYERS)]; vc = [[] for _ in range(LAYERS)]; out = []
    for pos, t in enumerate(toks):
        x = f("tok_embeddings.weight")[t].copy()
        for l in range(LAYERS):
            p = f"layers.{l}."
            h = rms(x, f(p + "attention_norm.weight"))
            q = rope(f(p + "attention.wq.weight") @ h, pos)
            kc[l].append(rope(f(p + "attention.wk.weight") @ h, pos)); vc[l].append(f(p + "attention.wv.weight") @ h)
            K, V = np.array(kc[l]).reshape(len(kc[l]), KV, hs), np.array(vc[l]).reshape(len(vc[l]), KV, hs)
            att = np.zeros((HEADS, hs))
            for hd in range(HEADS):
                kv = hd // (HEADS // KV)
                sc = K[:, kv] @ q.reshape(HEADS, hs)[hd] / np.sqrt(hs)
                e = np.exp(sc - sc.max()); att[hd] = (e / e.sum()) @ V[:, kv]
            x = x + f(p + "attention.wo.weight") @ att.reshape(-1)
            h = rms(x, f(p + "ffn_norm.weight"))
            a, b = f(p + "feed_forward.w1.weight") @ h, f(p + "feed_forward.w3.weight") @ h
            x = x + f(p + "feed_forward.w2.weight") @ (a / (1 + np.exp(-a)) * b)
        out.append(f("tok_embeddings.weight") @ rms(x, f("norm.weight")))
    return np.array(out)


def build_lib(tmp):
    so = tmp / "libchatds.so"
    subprocess.run(["nice", "-n", "19", "gcc", "-std=c99", "-O2", "-shared", "-fPIC", f"-I{ROOT}/clean/include",
                    f"-I{ROOT}/clean/src", *(str(ROOT / "clean/src" / s) for s in ("format.c", "kernels.c", "engine.c")),
                    "-lm", "-o", str(so)], check=True)
    lib = ctypes.CDLL(str(so))
    lib.chatds_model_from_memory.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
    lib.chatds_session_create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    lib.chatds_session_forward.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    lib.chatds_session_destroy.argtypes = [ctypes.c_void_p]
    lib.chatds_model_destroy.argtypes = [ctypes.c_void_p]
    return lib


class Out(ctypes.Structure):
    _fields_ = [("logits", ctypes.POINTER(ctypes.c_int32)), ("count", ctypes.c_uint32), ("argmax", ctypes.c_uint32)]


def test_c_random_model_vs_float_reference(tmp_path):
    sd = make_ckpt(tmp_path / "ckpt.pt"); fake_tok(tmp_path / "tok.bin")
    blob, _ = export_dsq8.export(tmp_path / "ckpt.pt", tmp_path / "tok.bin")
    lib = build_lib(tmp_path)
    m, s = ctypes.c_void_p(), ctypes.c_void_p()
    assert lib.chatds_model_from_memory(blob, len(blob), ctypes.byref(m)) == 0  # loader accepts size/layout
    assert lib.chatds_session_create(m, None, ctypes.byref(s)) == 0
    toks = [int(t) for t in np.random.RandomState(1).randint(0, VOCAB, CTX)]
    got, o = [], Out()
    for t in toks:
        assert lib.chatds_session_forward(s, t, ctypes.byref(o)) == 0
        got.append(np.ctypeslib.as_array(o.logits, (o.count,)).astype(np.float64) / 65536)
    got, ref = np.array(got), float_forward(sd, toks)
    agree = float((got.argmax(1) == ref.argmax(1)).mean()); err = float(np.abs(got - ref).max())
    print(f"argmax agreement {agree:.3f}, max |logit err| {err:.4f}, logit range {np.ptp(ref):.2f}")
    lib.chatds_session_destroy(s)
    lib.chatds_model_destroy(m)
    assert agree >= 0.9 and err < 0.1 * np.ptp(ref)


def test_zero_rows_and_rounding():
    assert export_dsq8.quant_matrix(np.zeros((2, 64), dtype=np.float32), 32) == bytes(2 * (64 + 4 + 4))
    assert export_dsq8.rha(np.array([-1.5, -0.5, 0.5, 1.5], dtype=np.float32)).tolist() == [-2, -1, 1, 2]


def test_cli_hashes_and_tokenizer_pin(tmp_path):
    ckpt, tok, out = (tmp_path / n for n in ('ckpt.pt', 'tok.bin', 'model.bin'))
    make_ckpt(ckpt); fake_tok(tok)
    cmd = [sys.executable, str(HERE / 'export_dsq8.py'), '--ckpt', str(ckpt),
           '--tok', str(tok), '--out', str(out)]
    expected, tok_bytes = export_dsq8.export(ckpt, tok)
    subprocess.run(cmd, check=True, timeout=30, capture_output=True)
    assert out.read_bytes() == expected
    meta = json.loads(pathlib.Path(str(out) + '.json').read_text())
    assert meta == dict(model_sha256=hashlib.sha256(expected).hexdigest(), size=len(expected),
                        tok_sha256=hashlib.sha256(tok_bytes).hexdigest())
    out.unlink(); pathlib.Path(str(out) + '.json').unlink()
    failed = subprocess.run(cmd + ['--expect-tok-sha256', '0' * 64], timeout=30, capture_output=True)
    assert failed.returncode != 0 and b'!= expected' in failed.stderr
    assert not out.exists() and not pathlib.Path(str(out) + '.json').exists()


@pytest.mark.parametrize('problem', ['heads', 'groups', 'shape', 'untied', 'nan_weight', 'nan_norm', 'large_norm', 'large_scale'])
def test_invalid_checkpoint_refused(tmp_path, problem):
    ckpt, tok = tmp_path / 'ckpt.pt', tmp_path / 'tok.bin'
    make_ckpt(ckpt); fake_tok(tok)
    ck = torch.load(ckpt, map_location='cpu', weights_only=False)
    sd, gs = ck['model'], 32
    if problem == 'heads': ck['model_args']['n_heads'] = 0
    elif problem == 'groups': gs = 7
    elif problem == 'shape': sd['layers.0.attention.wq.weight'] = torch.zeros(1, 1)
    elif problem == 'untied': sd['output.weight'] = sd['output.weight'] + 1
    elif problem == 'nan_weight': sd['layers.0.attention.wq.weight'][0, 0] = float('nan')
    elif problem == 'nan_norm': sd['norm.weight'][0] = float('nan')
    elif problem == 'large_norm': sd['norm.weight'][0] = 32768
    elif problem == 'large_scale': sd['layers.0.attention.wq.weight'][0, 0] = 20000
    torch.save(ck, ckpt)
    with pytest.raises(SystemExit):
        export_dsq8.export(ckpt, tok, gs=gs)


def test_refusals(tmp_path):
    make_ckpt(tmp_path / "ckpt.pt"); fake_tok(tmp_path / "tok.bin", VOCAB - 1)
    with pytest.raises(SystemExit):  # tok.bin piece count != vocab
        export_dsq8.export(tmp_path / "ckpt.pt", tmp_path / "tok.bin")
    fake_tok(tmp_path / "tok.bin"); (tmp_path / "t.model").write_bytes(b"x")
    ck = torch.load(tmp_path / "ckpt.pt", weights_only=False)
    ck["config"] = {"tokenizer": {"sha256": "0" * 64, "size": 1}}; torch.save(ck, tmp_path / "ckpt.pt")
    with pytest.raises(SystemExit):  # fingerprint mismatch
        export_dsq8.export(tmp_path / "ckpt.pt", tmp_path / "tok.bin", tmp_path / "t.model")
