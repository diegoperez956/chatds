# product condition 14 (c14)

c14 is the assistant-mode product. **hardware-tested: ran on a real Nintendo DS
via a DSpico flashcart (2026-10-13).** the ROM built from this tree is
byte-identical to that card's `chatds.nds`.

## what it does

`clean/product/main.c` hands assistant questions to `dispatch.c`:
style wrapper -> rules decision (`rules.c`, generated NFAs in `rules_tab.h`) ->
bounded dialogue -> guarded textops -> calc parser -> fixed templates or ranked
KB4 (k=3, one expansion) -> direct field rendering -> transformer only where
c14 falls through. no libc regex, no heap in dispatch or retrieval. story mode
stays raw generation.

`kb4.bin` on the card supersedes KB3. only a missing `kb4.bin` (ENOENT) permits
the `kb.bin` fallback; a corrupt or unreadable KB4 fails closed. the shipped kit
uses original KB4 (version 4), not KB4.1 or ER1.

dialogue is a fixed 420-byte record, separate from model KV. every transformer
question resets KV. startup, Stop/B, errors and publication failures reset
dialogue. pending clarification lives one turn; calc/text/code turns clear entity
state. a style preference lasts eight styled answers. path tags go to
`chatds/debug.log`, never the UI.

python twins of the C steps live in `campaign/pipeline/{prestep,textops}.py`
and `campaign/router/rules.py`; they generate `prestep_tab.h`, `textops_tab.h`
and `rules_tab.h` (`clean/product/gen_rules.py`) and back the parity/fuzz tests.

## hardware build and provenance

| file | sha256 |
|---|---|
| `chatds.nds` | `63453424927d64dffe7dd6bca2dd6308baad2814f8323eb178a476601dffc6ad` |
| `chatds/model.bin` | `cf2f9e9e1928d61834937959759623a6cf512e2378bceba3660bf763b2d9818b` |
| `chatds/tok.bin` | `c890d56f5d251765c79a9c7a1145fcd4852c0bcfc065e5d75257ebd17ce19c1a` |
| `chatds/kb4.bin` | `08d4ce833e91fbf49c610075d25e55a79c915797f9504e72d6ea77385b209ba7` |

model and tokenizer are the v0.1.0 release assets. `kb4.bin` (61,838,552 bytes)
is built by `corpus/kb/build_kb4.py` from the Simple English Wikipedia dump of
2026-09-01 (CC BY-SA 4.0); it is not committed and not yet published. ship
its attribution with any redistributed copy.

the card ROM was built from an earlier development tree plus an additive textops
seam (`cds_textops_tokens`/`_arg`/`_literal`) that was in that working tree.
the seam has no product caller; it is kept so this tree reproduces the card ROM
byte for byte. `ds/hwkit/make-kit.sh --kb4 --kb-attribution` from this tree reproduces the card
kit's ROM, assets, `run.txt`, `LICENSE` and host golden with identical hashes.
it also stages `chatds/kb-ATTRIBUTION.txt`, which the card copy lacked, and the
current `THIRD_PARTY_NOTICES.md`, which now names KB4.

## validation (2026-10-13, this tree)

- host tests: `python3 tools/run_host_tests.py` passes, including prestep,
  textops and KB4 C-vs-Python parity and sanitizer fuzz.
- engine golden: new engine on the pre-c14 product ROM gives 26 exact, 5 safety
  passes and 2 pinned known divergences, the documented expectation. on the c14
  ROM the fixture fact case keeps its IDs, stop, prompt count and context; only
  the rendered answer differs, and calculator questions now take the
  deterministic path, so the legacy fixtures are not whole-answer c14 goldens.
- legacy golden inputs (33, frozen KB2): c14 ROM in headless melonDS vs c14
  host product, 33/33 identical `out`/`ids`/`ctx` (the 5 over-long raw prompts
  fail identically on both, as `baseline-fails` expects).
- host product vs c14 reference pipeline, every dev turn: dev-v1 2,236 turns and
  dev-v2 2,058 turns, 0 answer and 0 metadata mismatches.
- headless melonDS screen: 60 stratified dev cases (10 multi-turn), 71 turns,
  ROM vs host 0 mismatches. no display sockets, Qt offscreen, no GPU.
- RAM gate: heap-break proxy 3,604,480 B against a conservative 3,670,016 B
  limit, margin **65,536 B (64 KiB): PASS**. stack guard PASS.

the dev-set parity, melonDS screen and memory runs use a private validation
harness and eval sets that are not shipped here. emulator timings are not
physical DS timings.

## memory

main-RAM static end 328,940 B. model arena 2,997,308 B (no second weight copy).
session heap 216,576 B, context 256, int16 Q8.8 KV 393,216 B: values in heap,
keys (196,608 B) in caller-owned VRAM D/E; UI keeps A/C. DTCM workspace pooling
is off to leave stack for card I/O. application frame-chain bounds from `.su`:
pending resolution 4,120 B, calc depth 3,936 B, rules 2,688 B, publication
3,064 B. this is measured headroom, not a proof of fragmentation safety.

the legacy `smoke-test.sh`/`test-publication.sh` expect transformer-only
results (nonzero prompt tokens); c14 deterministic paths use zero tokens and
`stop=none`, so those scripts are not c14 validators.
