# release gates

This branch prepares the MIT-licensed, code-only public repository `chatds`.
Publishing it is separate: the private repository will be named `chatds-private`.
Use one initial
commit from the reviewed tracked tree; keep full history private. Do not change
the private repository's visibility, mirror its refs, or copy the worktree with
`cp -r`: ignored assets, logs and private history are not publication inputs.

MIT is the approved public code license. Trained tokenizers, weights, KB
indexes, FAT images and ROM binaries are excluded from the source snapshot.
Review
[PUBLIC_RELEASE_AUDIT.md](PUBLIC_RELEASE_AUDIT.md) before export.

## binary/data release is a separate gate

- establish model-weight and tokenizer redistribution rights;
- attach the KB's Wikipedia attribution, CC BY-SA terms and modification notice;
- inventory linked libnds, FatFs, picolibc/libm and ARM7 runtime notices;
- boot the exact clean kit on physical DS lite + DSpico, including stack canary;
- obtain explicit publication approval. A local kit is not a public release.

## c14 validation flow

The c14 release gate is the flow recorded in
[PRODUCT-C14.md](PRODUCT-C14.md#validation-2026-10-13-this-tree). All of it
must pass on the exact tree being released:

1. host tests: `python3 tools/run_host_tests.py` (prestep, textops and KB4
   C-vs-Python parity, sanitizer fuzz).
2. golden parity: the 33 frozen golden inputs (frozen KB2, see
   [ENGINE-GOLDEN.md](ENGINE-GOLDEN.md)), c14 ROM in headless melonDS vs c14
   host product, 33/33 identical `out`/`ids`/`ctx`.
3. dev-set parity: host product vs the c14 reference pipeline on every dev
   turn, 0 answer and 0 metadata mismatches.
4. headless melonDS screen: ROM vs host on stratified dev cases, 0 mismatches,
   with display sockets denied (Qt offscreen, no GPU).
5. RAM gate: heap-break margin against the conservative limit must be
   >= 64 KiB, and the stack guard must pass.
6. kit rebuild and ROM hash:

```sh
source tools/env.sh
make
bash ds/hwkit/make-kit.sh --mode assistant \
  --model path/to/model.bin --tokenizer path/to/tok.bin \
  --kb4 path/to/kb4.bin --kb-attribution path/to/ATTRIBUTION.txt \
  --out build/release-kit
sha256sum build/release-kit/chatds.nds
```

The ROM sha256 must match the `chatds.nds` row in
[PRODUCT-C14.md](PRODUCT-C14.md#hardware-build-and-provenance); check the
staged assets against the same table.

The dev-set parity, melonDS screen and RAM runs use a private validation
harness and eval sets that are not shipped here, as PRODUCT-C14.md says.

`ds/hwkit/smoke-test.sh` and `ds/hwkit/test-publication.sh` are legacy
transformer-only checks. They expect nonzero prompt tokens, which c14
deterministic paths do not produce, and they only look for `chatds/kb.bin`, so
they are not used for c14.

All emulator gates are isolated/offscreen. The default ROM is `chatds.nds`,
with only the independent engine, tokenizer, plumbing and UI. Its data
directory is `chatds/`. No unsupported older ROM can be relabeled as the clean
product.

Use [ENGINE-BENCHMARK.md](ENGINE-BENCHMARK.md) for timing boundaries and identities.
The c14 kit uses KB4 (hash in PRODUCT-C14.md). The older demo uses release KB3 (`f0326927caf6d8e508aa19e3efe65a3f615c53295c24841a8bf4125eb22faefc`);
compatibility uses frozen KB2 (`4eff3ac8d99a738cc0789809764e7f5b197e2eee4ed7f7628bd3a3ec9e803203`).
Do not substitute one while retaining the other's claims.

Host workflow tests do not supply private assets, emulator or physical hardware.
The requested shipping pipeline skips CI; report that as skipped, not a claim
that device gates ran in GitHub Actions.
