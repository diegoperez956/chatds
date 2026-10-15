# DSQ8 exporter provenance

`train/export_dsq8.py` is MIT, clean-room, and standalone from the optional
upstream training modules. Ported from `campaign/routing`; the original was
written from `clean/ARITHMETIC.md`, `clean/src/format.c`, `train/qat4.py`
(quantizer description) and `train/train_instruct.py` (checkpoint format).
The old exporter and upstream converter source were not opened for that work;
only CLI help was read. Row-scale/rounding details were checked against released
model bytes, not converter source. The original reproduced the v0.1.0 DSQ8
model byte for byte.

This public port preserves quantization and layout, adds early rejection of
invalid head counts and unrepresentable norms/scales, and removes test reliance
on the private campaign harness. Synthetic pytest tests create CPU checkpoints,
load exports into the clean C engine, compare logits to float inference, and
exercise CLI manifests and refusals. An optional byte-parity test accepts
explicit `CHATDS_EXPORT_CKPT`, `CHATDS_EXPORT_TOK`, and `CHATDS_EXPORT_RELEASE`
paths. No checkpoints or model binaries are included.

Checkpoints must be trusted: PyTorch deserialization can execute code. Export
uses CPU tensors only. Equal vocabulary sizes do not prove tokenizer pairing;
supply `--tok-model` to check the trainer's recorded tokenizer fingerprint and
`--expect-tok-sha256` to pin the runtime tokenizer. The `.json` sidecar records
full model and runtime-tokenizer hashes; it is not an authentication signature.
