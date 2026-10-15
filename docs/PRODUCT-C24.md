# product condition 24 (c24)

c24 is the assistant-mode product: [c14](PRODUCT-C14.md) plus two learned
fallbacks, a pocket math notebook and the RAM reclaim that lets both fit.
**the current ROM, sha256
`4a6ee86ec91e4806537f393c20767b7a0fe1426fab1ff45ff85a229cee6a20e1`, ran on a
real Nintendo DS** and felt almost instant, especially on math. that is the only
c24 ROM tested on hardware; no physical timing was recorded. earlier c24 ROMs,
including the original `04151f19…132c`, were emulator-tested only. c14 also ran
on a real DS.

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
model, tokenizer, KB4 and the three heads are byte-identical to the original
c24 kit.

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
| `chatds.nds` (current, hardware-tested) | `4a6ee86ec91e4806537f393c20767b7a0fe1426fab1ff45ff85a229cee6a20e1` |
| `chatds.nds` (original c24) | `04151f196e6af5d088db52aa986d0068cafe081fc087f9cd442c6426081e132c` |
| `chatds/round3-act.cdsr` | `e46781ffcdbff485f33fcc918dffc5994d3da826241ae54a712befb38a1a7a86` |
| `chatds/round3-op.cdsr` | `aa825e492e45b537df09150e64915636cba777ca7e9e2ddbaadc2c9e30db5dd1` |
| `chatds/round3-tag.cdsr` | `6b7bd4db559fd936f1a260a45003da88135e69dc61814b2ec51451ba5cccacf4` |
| `kit.json` (original c24) | `5eacc768cc092b980d4424f6ee68b1f4f701d7d11320552b60fc384d949a8892` |

model, tokenizer and `kb4.bin` are the c14 files. `ds/hwkit/make-kit.sh --kb4
--kb-attribution` from this tree builds the current ROM above and stages the
same model, tokenizer, KB4 and heads as the original c24 kit; `kit.json` changes
with the ROM hash. the notebook needs no extra card files.

## notebook + reclaim validation (2026-10-13, current ROM)

- host tests: `python3 tools/run_host_tests.py` 623 passed, 3 skipped (327 before),
  including 290 notebook tests and the reclaim probes; engine, tokenizer and UI
  (724 checks) pass. notebook ASan/UBSan: 30,000 malformed query/spec iterations.
- host product vs c24 reference pipeline: dev-v1 2,236 turns and dev-v2 2,058
  turns, 0 answer and 0 metadata mismatches.
- headless melonDS: the same 60-case screen (71 turns), 12-turn stress and a
  12-turn mixed learned/notebook/transformer/KB/repeat run, ROM vs host 0
  mismatches. four notebook captures (square, sine, bars, table): ROM top screen
  byte-identical to the host render, 0 generated tokens.
- RAM gate: maximum heap-break proxy 3,596,288 B across screen, stress, mixed
  and notebook runs, margin **73,728 B (72 KiB): PASS** (required >= 64 KiB;
  notebook before reclaim: 61,440 B, FAIL). minimum user-stack free 6,080 B.
  melonDS proxies, not physical DS measurements.
- hardware: the ROM above ran on a real Nintendo DS. no physical timing,
  RAM or stack measurement was recorded.

## original c24 validation (2026-10-13)

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

## lazy-loader validation (before the notebook)

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

## pocket math notebook

`clean/plumbing/mathnb.c` parses, `mathnb_render.c` draws. dispatch runs it
after the calculator declines and before the round3 text fallback. a valid
request evaluates every sample, answers `Pocket math: plot (129 points).` (or
bars/table) and draws a 256x192 plot, bar chart or table on the top screen.
zero model tokens; no heap, card files or learned heads. examples: `graph sin
x`, `plot x squared from -5 to 5`, `show bars for 3, 8, 2, 6`, `table of 2^n
for n 1 to 8`.

bounds: at most 127 input characters, 32 AST nodes, depth 8, ranges within
±100, 2..129 plot points, 1..16 bars or table rows, values within ±10000 at
four decimal places. leading/trailing prose and unknown words return "not
mine" and continue the normal pipeline (`plot 2001 a space odyssey`, `table of
12 for dinner`, `graph x marks the spot`). only an unambiguous notebook request
over its bounds, or one hitting division by zero, a negative square root or
overflow, gets the fixed refusal. no partial plots. the integer contract,
including sine and square root, is in
[ARITHMETIC.md](../clean/ARITHMETIC.md#pocket-math-notebook-prototype);
`campaign/pipeline/mathnb.py` is its Python twin.

the notebook does not change c24 dispatch on the dev sets: 0 captures across
all 4,294 dev-v1/v2 turns, and full parity below still holds against reference
condition 24.

## RAM reclaim

the notebook alone cost about 7.6 KB static and left a 60 KiB worst margin,
below the 64 KiB gate. two lossless reclaims bring it back:

- **rule packing, 5,940 B.** `gen_rules.py` packs 4,060 four-byte NFA nodes
  (16,240 B) into halfwords plus 545 split pairs (10,300 B). same rule graph,
  decoded by value. `test_ram_reclaim.py` compares every decoded node against the
  unpacked Thompson graph and runs 6,300 regex searches against Python `re`
  under ASan/UBSan.
- **shared KB3/KB4 workspace, 3,068 B net.** the 3,168 B KB3 reader moves into
  the existing typed KB4 retrieval/resolution union. KB4 presence is decided once
  at open and never changes; KB3 opens only when `kb4.bin` is absent, and every
  scratch writer needs an open KB4. KB4 corruption stays fatal, never a KB3
  fallback. notebook, dialogue, evidence and published state stay outside the
  union. no new allocation. **any future reopen or card-swap path must
  re-establish this disjointness.** ASan/UBSan probes of the real product poison
  both members and check missing/corrupt KB3/KB4 behavior.

net static reclaim 8,896 B. context 256, int16 KV, the 64 KiB gate and the
model are unchanged. the ROM refuses to boot with less than 64 KiB left after
resident initialization.

## memory

current main-RAM static end 323,004 B (notebook before reclaim: 331,900 B).
Original c24 main-RAM static end 323,532 B (c14: 328,940 B): dispatch, learned loader, router,
round3 and textops build with `-Os -mthumb`; engine, retrieval, rules, prestep
and UI keep their flags. model arena, session heap, context 256 and int16 KV are
unchanged. application frame-chain bounds from `.su`: learned text 9,184 B,
pending resolution 4,424 B, calc depth 4,176 B, learned act loading 3,672 B,
publication 3,320 B, rules 2,928 B. this is measured headroom, not a proof of
fragmentation safety.

### #18 context-64 borrowing claim: CONFIRMED

The shipped shape is dim 192, 6 layers, 6 attention heads, 2 KV heads,
context 256. `engine.c:session_create` reserves each int16 KV arena as
`layers * context * kv_heads * (dim / heads) * 2`:

- values at 256: `6 * 256 * 2 * 32 * 2 = 196,608 B`;
- hypothetical values at 64: `6 * 64 * 2 * 32 * 2 = 49,152 B`;
- loader heads: `22,660 + 11,452 + 5,224 = 39,336 B`;
- router scratch: `4096 * 2 + 10 * 48 * 4 = 10,112 B`;
- required borrowed values: `39,336 + 10,112 = 49,448 B`;
- shortfall at 64: `49,448 - 49,152 = 296 B`.

`test_workspace.py` compiles a host probe using the real session allocator,
external-key API and the loader's actual private constants/arena check. It
observes 393,216/98,304 total KV bytes, 196,608/49,152 value bytes and loader
init success/failure at 256/64 respectively. The same probe also confirms these
numbers when loading the shipped DSQ8 file. Lazy loading does not shrink the
fixed reservation. This verifies the review claim; **production context stays
256**, with no model-header or engine/KV precision change.
