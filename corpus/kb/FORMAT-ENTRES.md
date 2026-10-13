# ER1: opt-in entity resolution for KB4

Baseline format/policy: [FORMAT-KB4.md](FORMAT-KB4.md). ER1 does not rewrite its records or keys.
Python entry point `retrieve4.retrieve(..., entres=True, index=...)`; omitted flag
uses `CHATDS_ENTRES=1`, otherwise baseline. `entres=False` explicitly selects
baseline even with that environment variable. `CHATDS_ENTRES_INDEX` supplies the
sidecar, default `<kb filename>.entres`. Missing/wrong-version sidecars fail closed
with an I/O/corruption status, not a silent baseline fallback.

C: mount base with `cds4_open`, sidecar with `cds4_ent_open`, then call
`cds4_retrieve_entres`; original `cds4_retrieve` remains baseline. Include
`entres_index.h` and link `entres_index.c` alongside `retrieve4.c`. Close both
handles. No product/device dispatch added. Host c14 still runs Python retrieval;
the C twin is validated independently.

## Query policy, version 1

- Original code/arithmetic/conversation gates run before number folding. ASCII
  possessive `'s` and plural apostrophes removed before the quote gate. Safety
  gates remain active with routed facts. Question limit 127 characters / 32 words.
- Casual frames (`abt`, `u`, `ur`, `pls`, `whos`, `wot`, etc.) normalize into
  existing vocabulary. Bounded filler set strips `guy`, `uh`, `quick question`,
  etc.; `tell/know/gimme/lemme` can satisfy the question-frame gate.
- Number words one through ten and Roman II through X fold to digits;
  `wwii/wwiii/wwi` fold to `ww2/ww3/ww1`. Title variants use the same mapping.
  Roman I is not globally folded because `I` is also a pronoun.
- Existing <=12 exact n-grams first. Protect a full, strong, zero-typo exact hit
  from unrelated singleton expansion. Otherwise compact non-contiguous content,
  reverse order, try first 12 positional permutations (up to four words).
  Singletons run only after full-name typo repair still fails, so weak aliases
  cannot occupy the pool ahead of a repaired full title. <=24 extra keys. Plural folding is an alternative, not destructive
  normalization: `ies -> y`, terminal `s -> ''` except `ss/us/is`.
- When still unresolved, existing <=16 single + <=16 two-word fuzzy key passes
  run on original words, then compact content only if needed. Up to eight
  additional short-name delete signatures allow clarification on short typos.
  At most 108 key attempts / query, each at most two index lookups. The actual
  extra-key generator emits fewer than its cap. Fuzzy bucket scans retain the
  existing KB4 bounds. Pool remains eight entities, four candidates per key.
- Canonical base title hits do not import unrelated sidecar candidates for that
  key. Aliases are merged/deduplicated by base record offset. Incoming popularity
  is a redirect-count prior, not the old article-length prominence. The prior
  breaks integer-score ties and contributes to weak-alias confidence margins;
  it does not arbitrarily override a higher entity score.
- Preserve integer coverage/kind/prominence/typo weights. Strong candidates get
  existing field availability scores; weak surname/initialism candidates do
  not choose identity by which one happens to have the requested field.
- Confidence floor: full coverage, entity score >=500; weak aliases additionally
  require popularity >=16, entity-score-plus-popularity margin >=32 and no typo.
  Equal-coverage candidates within 12 final score points still clarify unless
  popularity differs by at least 24. No posterior/probability calibration claim.
  An uncertain hit returns `ambiguous`, primary record plus at most one alternate
  (two identities total), no answer value/context. With only one uncertain
  candidate, c14 asks its generic clarification question. Zero candidates is
  `no_match`, not a fake ambiguity. The legacy Python `ambig=False` evaluation
  override remains possible; c14 and the C API always enable clarification.

## Offline source aliases and popularity

The offline builder (not shipped here) uses only existing KB identities/fields and the cached dump.
No evaluator extraction, curated entity table, blind data or external LLM.
Primary titles, redirects (<=8 hops, cycle guard), source lead subject names,
subject-bound `known as/called/nicknamed`, direct ordinal copular appositives /
subject-relative `who served as`, stored person surnames, and title initialisms.
Common short names must appear in the source/redirects; no guessed diminutives.
Generic professions, foreign-subject descriptions, given-name guessing and
category-to-entity guesses are excluded. Compact ordinal descriptions and
initials of explicit proper-name complements are source-derived alternatives.
No hand-written `red planet` or `first US president` entity mapping.

Up to 12 extracted aliases per article, plus bounded title/description variants
and source redirects. Hard limits: 1,000,000 keys, 64 MiB file, four candidates
per key, bucket <=4096 bytes. Oversized build fails rather than silently choosing
queries to retain. Candidate retention: redirect prior descending, strong before
weak, key kind then record offset. Truncated alias keys mark retained sidecar
candidates weak; exact canonical base titles remain strong. Redirect prior is
`min(63, 8 * floor(log2(1 + redirect_count)))`. This is redirect count from the
cached dump, not incoming links (pruned cached heads cannot provide full links).
The disk evidence sidecar records each alias's source/support; it is not loaded
at runtime. Offline build uses host-sized maps; bounded RAM claim is **runtime**.

## Binary layout (little endian)

Header one 512-byte sector:

| Offset | Value |
|---|---|
| 0 | `ER1\0` |
| 4 | u32 version = 1 |
| 8 | u32 exact file size (<=64 MiB) |
| 12,16 | u32 bucket count (power of two), key count |
| 20,24 | u32 bucket table offset =512, key area offset (512-aligned) |
| 28,32 | u32 base file size, FNV-1a of base's first 64 bytes |

Bucket table `(nb+1)` u32 relative key-area offsets. Entries, sorted by hash/key:
`u32 fnv1a(key), u8 keylen, u8 ncand, key[keylen], candidate[ncand]`.
Candidate 13 bytes: KB4's `u32 base_record_offset, u8 kind, u8 prominence,
u8 etype, u16 present, u16 missing`, then `u8 redirect_popularity, u8 weak`.
Reserved `~`-prefixed keys are delete signatures of source aliases of length 3..4;
query normalization cannot produce this prefix. Signature candidates always weak
and typo-costed; they cannot directly answer.

Each reader has one 512-byte cache. Offsets, spans, candidate masks/kinds,
record bounds and header dimensions checked before use. The header fingerprint
is an accidental wrong-build guard, **not authentication**; deployment must check
full SHA256s published with the artifact. It cannot detect every valid-looking
bit flip or source error. No runtime full-file hashing or RAM index load.

## Attribution and checks

Aliases/support text are modified Simple English Wikipedia content by Wikipedia
contributors, CC BY-SA 4.0. Ship the base build's `ATTRIBUTION.txt` with the sidecar.
Source dump identification, artifact SHA256s and measurements were recorded in the
private development tree and are not shipped here. ER1 is opt-in; the shipped c14
kit does not use it. Do not use the synthetic
probe as a blind benchmark: its intended identities/values come from the KB;
surnames and shortened descriptions can genuinely be underspecified.
