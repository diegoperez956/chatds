#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Clean-room exporter: trained checkpoint -> resident layer-major shared-classifier DSQ8 model.bin.

  python3 train/export_dsq8.py --ckpt ckpt.pt --tok tok.bin --out model.bin [--tok-model tokenizer.model]

Written only from clean/ARITHMETIC.md, clean/src/format.c and train/qat4.py (see EXPORT-PROVENANCE.md).
Layout: 512-byte TIE1 header (zero padded), fp32 norms (all attention norms, all FFN norms, final),
embedding at the next 512 boundary, then one 512-aligned block per layer: wq wk wv wo w1 w2 w3.
Row: cols int8, cols/gs uint16 Q1.15 group scales, one uint32 Q8.24 row scale.
Quantizer: rowmax -> rsc = rowmax/127 (Q8.24, half away); group scale = round(gmax/rowmax*32767);
q = round_half_away(w / (rowmax/127*gscale/32768))  (float rsc, not the Q8.24-rounded one), clamped to +-127. All math float32. Deterministic.
Writes OUT + ".json" sidecar holding sha256 of the model and tok.bin (the header has no spare field
that is allowed to be nonzero without breaking byte parity with the v0.1.0 release).
"""
import argparse, hashlib, json, os, struct, sys
import numpy as np
import torch

HDR = 512
MAX_W, MAX_L, MAX_V, MAX_CTX, MAX_BYTES = 8192, 128, 65536, 4096, 64 << 20
FLAGS = 257  # 0x101 layer-major + shared embedding/classifier


def rha(x):  # round half away from zero, float32 in -> float32 out
    return np.trunc(x + np.where(x >= 0, np.float32(0.5), np.float32(-0.5)).astype(np.float32))


def quant_matrix(w, gs):
    """w: float32 [rows, cols] -> bytes of rows*(cols+2*cols/gs+4)."""
    w = np.ascontiguousarray(w, dtype=np.float32)
    rows, cols = w.shape
    g = cols // gs
    rmax = np.abs(w).max(axis=1)
    if not np.isfinite(rmax).all():
        raise SystemExit("export_dsq8: nonfinite weights")
    rsc_f = rmax / np.float32(127.0)
    if (rsc_f >= 128).any():
        raise SystemExit("export_dsq8: row scale exceeds Q8.24 range")
    rounded_rsc = rha(rsc_f * np.float32(1 << 24))
    if (rounded_rsc.astype(np.float64) > 2147483647).any():
        raise SystemExit("export_dsq8: row scale exceeds Q8.24 range")
    rsc = rounded_rsc.astype(np.uint32)
    gmax = np.abs(w).reshape(rows, g, gs).max(axis=2)
    safe = np.where(rmax > 0, rmax, np.float32(1))[:, None]
    s16 = np.where(rmax[:, None] > 0, np.trunc(gmax / safe * np.float32(32767) + np.float32(0.5)), 0).astype(np.uint16)
    eff = rsc_f[:, None] * s16.astype(np.float32) / np.float32(32768)  # unrounded float rsc, as the release export
    inv = np.where(eff > 0, np.float32(1) / np.maximum(eff, np.float32(1e-30)), 0).astype(np.float32)
    q = np.clip(rha(w.reshape(rows, g, gs) * inv[:, :, None]), -127, 127).astype(np.int8).reshape(rows, cols)
    out = np.empty((rows, cols + 2 * g + 4), np.uint8)
    out[:, :cols] = q.view(np.uint8)
    out[:, cols:cols + 2 * g] = s16.astype('<u2').view(np.uint8).reshape(rows, 2 * g)
    out[:, cols + 2 * g:] = rsc.astype('<u4').view(np.uint8).reshape(rows, 4)
    return out.tobytes()


def tok_pieces(blob):
    """Count pieces in tok.bin (u32 maxlen, then {f32 score,u32 len,bytes}*)."""
    n, p = 0, 4
    while p < len(blob):
        if p + 8 > len(blob):
            raise SystemExit("export_dsq8: truncated tok.bin")
        p += 8 + struct.unpack_from("<I", blob, p + 4)[0]
        n += 1
    if p != len(blob):
        raise SystemExit("export_dsq8: malformed tok.bin")
    return n


def pad(buf, a=512):
    buf.extend(b"\0" * (-len(buf) % a))


def export(ckpt_path, tok_path, tok_model=None, gs=32):
    # PyTorch checkpoint deserialization can execute code: trusted inputs only.
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    sd = {k.removeprefix("_orig_mod."): v for k, v in ck["model"].items()}
    ma = ck["model_args"]
    tok = open(tok_path, "rb").read()
    dim, L, H, KV, V, ctx = ma["dim"], ma["n_layers"], ma["n_heads"], ma.get("n_kv_heads") or ma["n_heads"], ma["vocab_size"], ma["max_seq_len"]
    hid = sd["layers.0.feed_forward.w1.weight"].shape[0]
    # --- tokenizer pairing
    if tok_pieces(tok) != V:
        raise SystemExit(f"export_dsq8: tok.bin has {tok_pieces(tok)} pieces, checkpoint vocab_size={V}")
    if tok_model:
        rec = (ck.get("config") or {}).get("tokenizer") or {}
        sha = hashlib.sha256(open(tok_model, "rb").read()).hexdigest()
        n = min(len(sha), len(rec.get("sha256", "")))
        if n < 16:
            raise SystemExit("export_dsq8: checkpoint records no tokenizer fingerprint")
        if sha[:n] != rec["sha256"][:n]:
            raise SystemExit("export_dsq8: tokenizer.model does not match the checkpoint fingerprint")
    # --- limits (mirror clean/src/format.c)
    if not (0 < dim <= MAX_W and 0 < hid <= MAX_W and 0 < L <= MAX_L and 0 < V <= MAX_V and 0 < ctx <= MAX_CTX):
        raise SystemExit("export_dsq8: dimensions outside loader limits")
    if gs <= 0 or gs % 8 or gs > 256 or dim % gs or hid % gs:
        raise SystemExit("export_dsq8: bad group size")
    if H <= 0 or KV <= 0 or dim % H or H % KV or (dim // H) % 2:
        raise SystemExit("export_dsq8: bad head configuration")
    emb = sd["tok_embeddings.weight"].float().numpy()
    if "output.weight" in sd and not torch.equal(sd["output.weight"], sd["tok_embeddings.weight"]):
        raise SystemExit("export_dsq8: classifier is not tied to the embedding")
    kvd = dim // H * KV
    exp = {"tok_embeddings.weight": (V, dim)}
    for l in range(L):
        p = f"layers.{l}."
        exp.update({p + "attention.wq.weight": (dim, dim), p + "attention.wk.weight": (kvd, dim),
                    p + "attention.wv.weight": (kvd, dim), p + "attention.wo.weight": (dim, dim),
                    p + "feed_forward.w1.weight": (hid, dim), p + "feed_forward.w2.weight": (dim, hid),
                    p + "feed_forward.w3.weight": (hid, dim), p + "attention_norm.weight": (dim,),
                    p + "ffn_norm.weight": (dim,)})
    exp["norm.weight"] = (dim,)
    for k, s in exp.items():
        if k not in sd or tuple(sd[k].shape) != s:
            raise SystemExit(f"export_dsq8: {k} missing or shape != {s}")
    f = lambda k: sd[k].float().numpy()
    buf = bytearray(struct.pack("<13I", 0x31454954, 1, 4, HDR, dim, hid, L, H, KV, V, ctx, gs, FLAGS))
    buf.extend(b"\0" * (HDR - len(buf)))
    def norm_bytes(key):
        w = f(key)
        fixed = w.astype(np.float64) * 65536
        rounded = np.where(fixed < 0, np.ceil(fixed - 0.5), np.floor(fixed + 0.5))
        if not np.isfinite(w).all() or (rounded > 2147483647).any() or (rounded < -2147483648).any():
            raise SystemExit("export_dsq8: norm outside Q16.16 range")
        return w.astype("<f4").tobytes()
    for name in ("attention_norm", "ffn_norm"):
        for l in range(L):
            buf += norm_bytes(f"layers.{l}.{name}.weight")
    buf += norm_bytes("norm.weight")
    pad(buf)
    buf += quant_matrix(emb, gs)
    for l in range(L):
        pad(buf)
        p = f"layers.{l}."
        for k in ("attention.wq", "attention.wk", "attention.wv", "attention.wo",
                  "feed_forward.w1", "feed_forward.w2", "feed_forward.w3"):
            buf += quant_matrix(f(p + k + ".weight"), gs)
    if len(buf) > MAX_BYTES:
        raise SystemExit("export_dsq8: model exceeds 64 MiB")
    return bytes(buf), tok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--tok", required=True, help="tok.bin")
    ap.add_argument("--tok-model", help="tokenizer.model; checked against the checkpoint fingerprint")
    ap.add_argument("--expect-tok-sha256", help="refuse unless sha256(tok.bin) starts with this")
    ap.add_argument("--out", required=True)
    ap.add_argument("--gs", type=int, default=32)
    a = ap.parse_args()
    blob, tok = export(a.ckpt, a.tok, a.tok_model, a.gs)
    tsha = hashlib.sha256(tok).hexdigest()
    if a.expect_tok_sha256 and not tsha.startswith(a.expect_tok_sha256.lower()):
        sys.exit(f"export_dsq8: tok.bin sha256 {tsha} != expected {a.expect_tok_sha256}")
    assert len(blob) >= HDR
    with open(a.out, "wb") as fh:
        fh.write(blob)
    with open(a.out + ".json", "w") as fh:
        json.dump({"model_sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob), "tok_sha256": tsha}, fh, indent=1)
        fh.write("\n")
    print(f"{a.out}: {len(blob)} bytes sha256 {hashlib.sha256(blob).hexdigest()[:16]}")


if __name__ == "__main__":
    main()
