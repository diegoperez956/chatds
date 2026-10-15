# product condition 24 (c24)

c24 is the assistant-mode product: [c14](PRODUCT-C14.md) plus two learned
fallbacks. **emulator-tested only; not yet run on DS hardware.** c14 is the
build that ran on a real DS.

## what changed from c14

two hashed char+word n-gram int8 models fire only when the c14 rules decline:

- a conversation-act head (greeting, thanks, bye, identity, capabilities, how
  are you, compliment, insult, repeat, pushback). it runs only when no c14
  rule, dialogue step, textops, calculator, ambiguity or fact cue fired.
  repeat/pushback still execute against the bounded dialogue record.
- a text-operation classifier plus per-token literal-span tagger. it runs after
  the guarded regex textops and calculator decline, on the original user bytes.
  spans only index those bytes; the existing textops executor does the work.

act/op/tag Q8 thresholds: 1793/386/0. model, tokenizer, KB4, prompt and
dialogue reset rules are unchanged. story mode does not load the heads.

`clean/plumbing/router.c` (int8 classifier) and `round3.c` (fallback logic) are
twins of `campaign/router/round3.py`. `clean/product/learned.c` loads the three
CDSR heads from the card, checks their sha256 and borrows 49,448 B of idle
main-RAM KV values for them (39,336 B heads + 10,112 B hash scratch). the
loader keeps validated heads across deterministic turns and loads only the
needed head after eligibility checks (tag only after op acceptance). It checks
the pinned whole-file SHA once per card load; cached use does not rehash.
Before generator reset/prefill, dispatch invalidates every cached view because
KV will overwrite those bytes. The next eligible turn reloads only what it needs.
Missing, corrupt or truncated heads fail closed on demand, not back to c14;
insufficient arena capacity still fails startup. The heads are committed
in `campaign/router/models/`; `make-kit.sh` stages them in assistant kits.

## blind scores vs c14

grader v3, completion, aggregate-only scoring on sealed sets held out from tuning;
each set was written blind by a different model family.

| set | c14 | c24 | delta |
|---|---:|---:|---:|
| Claude-authored | .630 | .655 | +.025 |
| GPT-authored | .380 | .415 | +.035 |
| GLM-authored | .200 | .210 | +.010 |
| DeepSeek-authored | .615 | .615 | ±0 |

no set regresses. gains come mostly from conversation and text operations on
Claude and GPT phrasing; GLM and DeepSeek phrasing are flat. the sealed sets and
grader are private and not shipped here.

## build and provenance

| file | sha256 |
|---|---|
| `chatds.nds` | `04151f196e6af5d088db52aa986d0068cafe081fc087f9cd442c6426081e132c` |
| `chatds/round3-act.cdsr` | `e46781ffcdbff485f33fcc918dffc5994d3da826241ae54a712befb38a1a7a86` |
| `chatds/round3-op.cdsr` | `aa825e492e45b537df09150e64915636cba777ca7e9e2ddbaadc2c9e30db5dd1` |
| `chatds/round3-tag.cdsr` | `6b7bd4db559fd936f1a260a45003da88135e69dc61814b2ec51451ba5cccacf4` |
| `kit.json` | `5eacc768cc092b980d4424f6ee68b1f4f701d7d11320552b60fc384d949a8892` |

model, tokenizer and `kb4.bin` are the c14 files. `ds/hwkit/make-kit.sh --kb4
--kb-attribution` from this tree reproduces the original c24 kit: the ROM and
every manifest entry (including `chatds/kb-ATTRIBUTION.txt`, the three heads and
the host golden) are byte-identical except `THIRD_PARTY_NOTICES.md`, which now
also names KB4 and the learned heads; `kit.json` differs only by that hash.

## validation (2026-10-13, this tree)

- host tests: `python3 tools/run_host_tests.py` passes. new: round3 C vs Python
  parity on 6,000+ generated requests at deployed and zero thresholds, ASan/UBSan
  fuzz, head pinning, and fail-closed product tests for missing/corrupt heads and
  too little borrowed workspace.
- host product vs c24 reference pipeline, every dev turn: dev-v1 2,236 turns and
  dev-v2 2,058 turns, 0 answer and 0 metadata mismatches (learned head ids and
  margins included).
- headless melonDS screen: 60 stratified dev cases (10 multi-turn), 71 turns,
  ROM vs host 0 mismatches, including learned head ids/margins. 4 learned-act and
  3 learned-text turns ran on the ROM. no display sockets, Qt offscreen, no GPU.
- RAM/stop stress on the ROM: 12 turns (maximum editor length, budget stops,
  cancellation/reset), ROM vs host 0 mismatches.
- RAM gate: maximum heap-break proxy 3,596,288 B across screen and stress against
  the conservative 3,670,016 B limit, margin **73,728 B (72 KiB): PASS**
  (required >= 64 KiB). minimum user-stack free 5,388 B; guard PASS.
- legacy golden fixtures (33 inputs, frozen KB2, heads on the card): c24 ROM vs
  c24 host 33/33 identical (5 over-long raw prompts fail identically on both, as
  `baseline-fails` expects). c24 ROM vs the c14 card ROM: 31/33 identical. the two
  differences are the one-character inputs `a` and `?`, which the learned act
  head now answers with the identity line instead of c14's model reply and
  clarification. the stricter `tools/benchmark_product.py` gate cannot score
  c14 or c24: zero-token deterministic answers fail its transformer-only checks.

emulated per-answer time on the screen: p50 229 ms, p95 12.4 s, max 16.1 s.
these are melonDS milliseconds, not physical DS time. the dev-set parity, screen
and memory runs use the private validation harness and eval sets, as for c14.

## lazy-loader validation

Same fixed 60-case screen (71 turns): host == ROM, zero mismatches including
learned IDs/margins. All dev-v1 (2,236) and dev-v2 (2,058) turns match reference
condition 24, zero answer/metadata mismatches. Instrumented host tests count
one read and one whole-file SHA per head load, no warm-turn reads/hashes, and
reload after KV invalidation. Corrupt/truncated/missing/re-signed files still
publish the same empty failed answer and IDs as before (12/12 host checks).

Before/after **emulated melonDS ms per answer**, nearest-rank percentiles on
71 turns: p50 **229 -> 92**, p95 **12,405 -> 12,111**, max **16,097 -> 15,727**.
Both runs deny display sockets and GPU access, verify Qt offscreen, and use
private FAT/config/ROM copies with bounded timeouts and owned-PID cleanup.
Screen peak heap-break proxy stays **3,596,288 B** (72 KiB margin). The same
12-turn stop/RAM stress also has zero host/ROM mismatches; its peak increases
**3,596,288 -> 3,600,384 B**. Worst conservative allocator margin is therefore
**69,632 B (68 KiB)**, above the 64 KiB gate. Minimum observed stack free is
6,088 B after the change. Heap break is not live-allocation peak or physical DS
timing. Context remains 256; no new head-sized allocation.

## memory

main-RAM static end 323,532 B (c14: 328,940 B): dispatch, learned loader, router,
round3 and textops build with `-Os -mthumb`; engine, retrieval, rules, prestep
and UI keep their flags. model arena, session heap, context 256 and int16 KV are
unchanged. application frame-chain bounds from `.su`: learned text 9,184 B,
pending resolution 4,424 B, calc depth 4,176 B, learned act loading 3,672 B,
publication 3,320 B, rules 2,928 B. this is measured headroom, not a proof of
fragmentation safety.
