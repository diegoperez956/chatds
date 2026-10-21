# pretrained weights release review

## v0.2.0: provenance-clean model and tokenizer

checked 2026-10-21 UTC. v0.2.0 replaces `chatds/model.bin` and `chatds/tok.bin`
with a retrain on permitted pairs only. same shape as v0.1.0, new vocabulary.
KB4 and the three round3 heads are unchanged from c24. the two files must ship
together; the v0.1.0 tokenizer with this model is wrong.

### artifacts

| file | bytes | sha256 |
|---|---:|---|
| `chatds/model.bin` (DSQ8, dim 192, 6 layers, 2,755,008 params) | 2,986,240 | `ff0a3e8289845f7f9906103e8405f1b2044ed2711f06825837b40f26c3e95eb9` |
| `chatds/tok.bin` (2048-token SentencePiece BPE, runtime form) | 25,339 | `582766d0ff7962690aa51e52dfdddaa9efcde220015ff7a84952342bb72d7203` |
| `chatds/kb4.bin` (c14 KB4, unchanged) | 61,838,552 | `08d4ce833e91fbf49c610075d25e55a79c915797f9504e72d6ea77385b209ba7` |
| `chatds/round3-act.cdsr` (unchanged) | 22,660 | `e46781ffcdbff485f33fcc918dffc5994d3da826241ae54a712befb38a1a7a86` |
| `chatds/round3-op.cdsr` (unchanged) | 11,452 | `aa825e492e45b537df09150e64915636cba777ca7e9e2ddbaadc2c9e30db5dd1` |
| `chatds/round3-tag.cdsr` (unchanged) | 5,224 | `6b7bd4db559fd936f1a260a45003da88135e69dc61814b2ec51451ba5cccacf4` |
| `chatds.nds` | 371,712 | `b2e7a47ba0c4509fdbefa6401261f6717810ec6bfad8f447ea2b92d88e1b100a` |

the heads are byte-identical to `campaign/router/models/`; KB4 matches
[PRODUCT-C14.md](PRODUCT-C14.md). the ROM is rebuilt from this tree, see
[RELEASE-v0.2.0.md](RELEASE-v0.2.0.md).

### training data

275,272 question/answer pairs, about 11.5M tokens. the builder is fail-closed:
an exact author allowlist (deterministic generator, human-licensed corpus,
Claude, GPT); any GLM or DeepSeek string in author or source metadata drops the
row, and so does an unknown author. 29,562 DeepSeek-answered rows and 2,373
unknown-author rows were dropped. the model starts from scratch; no v0.1.0 or
other teacher weights are inherited.

| question author / answer author | rows | rights |
|---|---:|---|
| deterministic generator / deterministic generator | 229,906 | project-authored generators, MIT |
| deterministic generator / Simple English Wikipedia text | 39,998 | MIT phrasing; answers CC BY-SA 4.0 |
| GPT / GPT | 4,514 | provider terms, see below |
| Claude / Claude | 854 | provider terms, see below |

no GLM- or DeepSeek-authored question or answer is in the set. held-out dev,
audit and sealed eval questions were gated out by normalized hash and a near
duplicate check (0 exact, 0 normalized, 0 near duplicates).

the tokenizer was trained only on text from these same 275,272 pairs. unlike
v0.1.0, no TinyStories text and no old tokenizer corpus went in.

### rights

- generator pairs: the repo's own MIT scripts, same as v0.1.0's python and
  arithmetic generators.
- Wikipedia-derived answers: CC BY-SA 4.0, Simple English Wikipedia
  contributors, same September 1, 2026 dump as KB4. the MIT model grant does
  not relicense that text. KB4 and retrieved text stay CC BY-SA 4.0 with
  `chatds/kb-ATTRIBUTION.txt` and `licenses/CC-BY-SA-4.0.txt`.
- Claude-authored rows: [Anthropic commercial terms](https://www.anthropic.com/legal/commercial-terms)
  (effective June 17, 2025, checked October 21, 2026), section B: the customer
  owns its outputs. section D.4 bars using the services "to build a competing
  product or service, including to train competing AI models". a 2.75M-parameter
  offline DS model trained on 854 such rows is not a competing AI service in any
  practical sense, but that is the project's reading, not a provider grant.
- GPT-authored rows: OpenAI's terms page returned 403 to an automated fetch on
  2026-10-21 and was not re-read for this review. OpenAI's terms assign output
  ownership to the user and restrict using output to develop competing models;
  the same reading as above applies. **open item: re-check the exact current
  OpenAI terms text before publishing.**
- no DeepSeek-authored data is in v0.2.0, so v0.1.0's DeepSeek terms check no
  longer applies to the model.

license: **MIT for `model.bin` and `tok.bin`**, the same grant the owner chose
for v0.1.0, carried over here (`licenses/MODEL-TOKENIZER-MIT.txt`). the
Wikipedia text and index stay CC BY-SA 4.0. the heads ship under the root MIT
license with the code, as [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
says; their training rows (project request phrasing, partly LLM-assisted) were
not re-audited under the GLM/DeepSeek rule. the "provenance-clean" claim covers
`model.bin` and `tok.bin` only.

### validation

all of this is emulator or host evidence, except the owner's demo.

- dev, host, grader v3, vs the v0.1.0-lineage model shipped in c24: dev-v1
  1830 -> 1963/2158, dev-v2 flat (1117/1598), dev-v3 44 -> 59/400. blind
  re-rating with arms hidden: owner-style semantic 28 -> 58 of 156, code leaks
  56 -> 21.
- blind sealed sets, aggregate only, never used for tuning: Claude-authored
  .655 -> .675, GPT-authored .415 -> .430, GLM-authored .210 -> .260,
  DeepSeek-authored .615 -> .670 (c24 shipped -> v0.2.0 product).
- trade-off seen on a 402-turn GLM-written casual set: fewer code leaks
  (97 -> 76) but more confident-wrong answers (55 -> 67, +20 from the model,
  -8 from rules). good answers flat (74 -> 77, not significant).
- single training seed; a 3-seed check was stable.
- ROM gates on this tree: see [RELEASE-v0.2.0.md](RELEASE-v0.2.0.md#validation).
- hardware: the owner ran this exact ROM (sha above) on a real DS via DSpico on
  2026-10-21 and liked how it ran. qualitative, no timings.

the sealed sets, dev sets, grader and training data are private and not
shipped.

## v0.1.0

v0.1.0's review (DeepSeek terms, TinyStories CDLA-Sharing-1.0 results clause,
KB3 attribution, compression, packaging) was done before this public tree was
cut and lives with the [v0.1.0 release](https://github.com/papayuh/chatds/releases/tag/v0.1.0)
notes and its `README.txt`. its model `cf2f9e9e…818b` and tokenizer
`c890d56f…9c1a` are not in v0.2.0.
