# training

`train_instruct.py` trains instruction models with PyTorch, grouped-query
attention and masked prompt loss. It needs the MIT `RileyGreiff/ds-llm` model,
export and tokenizer modules under `reference/ds-llm/` (ignored by git).
`tools/fetch-refs.sh` fetches that optional dependency. See
[third-party notices](../THIRD_PARTY_NOTICES.md).

```sh
python3 -m pip install torch numpy sentencepiece
bash tools/fetch-refs.sh
python3 train/train_instruct.py --selftest=True --device=cpu --compile=False
```

Train a tokenizer on licensed UTF-8 text using `tools/train_tokenizer.py`,
then export its runtime binary with `ds/tokenizer/tokbin.py`; see the root
README. No pretrained tokenizer, model weights or full dataset is shipped.
Prepare instruction pairs with `corpus/` and export training shards with
`corpus/export_train.py` using that same `.model`. The trainer accepts `--key=value` overrides; its
module documentation lists data, checkpoint and tokenizer-provenance checks.
Do not load untrusted PyTorch checkpoints.

`retain-checkpoints.py`, `select-checkpoint.py` and `soup_ckpt.py` handle local
checkpoint selection. `qat4.py` is experimental fake-quant math; the product
supports DSQ8, not DSQ4. `export_dsq8.py` is the standalone MIT clean-room
float-checkpoint -> resident DSQ8 converter; it requires only PyTorch and NumPy,
not the optional upstream trainer/converter modules. It runs on CPU and emits
`model.bin` plus a `.json` model/runtime-tokenizer SHA256 sidecar.

```sh
python3 train/export_dsq8.py --ckpt build/training/ckpt.pt \
  --tok build/tok.bin --tok-model build/tokenizer.model --out build/model.bin
python3 -m pytest -q train/test_export_dsq8.py
```

Use trusted checkpoints only. `--tok-model` checks the tokenizer fingerprint
recorded by training; `--expect-tok-sha256` additionally pins `tok.bin`. Shared
embedding/classifier weights, loader-supported dimensions and group sizes are
required. See [export provenance](EXPORT-PROVENANCE.md) and the root README's
[train -> export -> host -> melonDS workflow](../README.md#train---export---host-check---melonds).
Synthetic tests need no private files; release byte-parity testing is opt-in
through the three `CHATDS_EXPORT_*` paths documented in the test file.
No capacity planner or end-to-end training campaign wrapper is shipped.
Compatible DSQ8 assets can be evaluated with `eval/run_eval.py` and packaged
with `ds/hwkit/make-kit.sh`. Keep checkpoints and binary assets out of git.
