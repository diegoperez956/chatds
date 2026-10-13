# KB4 format (little-endian)

Optional ER1 source-alias sidecar and entity resolution are documented in
[FORMAT-ENTRES.md](FORMAT-ENTRES.md); baseline retrieval remains default.

KB4 is a new format, not a KB3 extension. It keeps KB3's bucket/hash/delete-index machinery and its 512-byte sector
discipline, but a key no longer points at one finished sentence. A key points at a bounded **candidate list**
(entity records), and a record holds **typed fields** with provenance and explicit "missing" markers.
Built by `build_kb4.py` (stage 1 `kb4_scan.py`, field extraction `kb4_extract.py`); read by `kb4.py` (reference) and
`clean/plumbing/kb4.c`; ranked retrieval in `retrieve4.py` / `clean/plumbing/retrieve4.c`.

Source: Simple English Wikipedia dump (CC BY-SA 4.0). The dump URL, Last-Modified and sha1 go into the header text and
`ATTRIBUTION.txt`. The tested build used sha1 `1bdd97642b5f511def336cce8afd34996db52d49` (Last-Modified 2026-09-01).
Per article only one definition sentence (<= 110 chars) and short fields are kept; the KB is a modified, derived work and must ship with the attribution file.

## Design: key -> candidates -> record
1. **key**: normalized text (same rule as KB3: ASCII-transliterate, lowercase, non `[a-z0-9]` runs -> one space, <= 63 bytes), FNV-1a 32 hash, `bucket = hash & (n_buckets-1)`.
2. **candidate list**: <= 4 (`CAND_MAX`) entries per key, best first. Each carries enough summary to rank without reading a record: key kind, prominence, entity type, bitmask of fields present and bitmask of fields marked missing.
3. **record**: read only for the chosen candidate (<= 512 bytes, usually one sector).

Working RAM for the reader: one 512 B sector buffer, one 512 B record buffer, 4 candidates x 16 B per lookup, pool of 8 candidates, key buffers: well under 4 KiB (`CDS_KB4_WORK_RAM` in `kb4.h`).

## Layout
Header 512 B, bucket table, key area, record area, fuzzy words, fuzzy buckets, fuzzy entries; each area starts 512-aligned and zero padded.

| offset | field |
|---|---|
| 0 | `"KB4\0"` |
| 4 | u32 version = 4 |
| 8..32 | u32 n_buckets (pow2, >= n_keys/3), n_keys, n_records, bucket_table_offset, keys_offset, records_offset |
| 32 | u32 file_size (must equal the real size) |
| 36..60 | u32 fz_n_buckets, fz_bucket_offset, fz_entries_offset, fz_words_offset, fz_n_entries, fz_n_words |
| 60 | u32 fz_min_word: shortest word in the delete index (4 in this build; 0 = 5, KB3-style). The reader uses it as the shortest query word it may repair |
| 64 | ASCII source / licence / dump sha1 string |

Bucket table: `(n_buckets+1)` u32 offsets relative to `keys_offset`; bucket b = `[off[b], off[b+1])`.

**Key entry** (sorted by hash within a bucket):
`u32 hash, u8 keylen, u8 ncand (1..4), key bytes, ncand x cand`
**cand** (11 bytes): `u32 record_offset (relative to records_offset), u8 kind, u8 prominence (0..63), u8 etype, u16 present_mask, u16 missing_mask`.
Putting `ncand` in the 6-byte entry head lets a bucket scan skip a non-matching entry after one read.

- `kind`: 0 title, 1 redirect, 2 title with its "(qualifier)" removed, 3 derived alias (leading "the", roman numeral -> digit, initialism of an event title: `ww2`, `wwii`).
- `prominence = min(63, floor(4*log2(1 + article_length/32)))`, article_length in wikitext bytes (a size prior used only for ranking and ambiguity).
- `etype`: 0 other, 1 person, 2 event, 3 place, 4 country.
- mask bit r = relation code r (below). Bit 0 (definition) is always present.

**Record** (at `records_offset + record_offset`):
`u16 len (<= 510), u32 eid, u8 etype, u8 prominence, u8 title_len, title, u8 def_len, definition, u8 nfields, nfields x field`
**field**: `u8 rel, u8 flags, u8 vlen, value`. flags: bit0 = missing marker (vlen = 0), bits1..3 = provenance.
`eid` is the canonical entity id (rank by article length, stable per build); the title is the canonical name; aliases are the other keys that point at the same record.

Relation codes: 0 definition (always the record's definition sentence), 1 date_range, 2 birth_date, 3 birth_place, 4 death_date, 5 death_place, 6 location, 7 surname, 8 capital, 9 occupation, 10 quantity (population).
Campaign vocabulary mapping: birth_* -> `birth`, death_* -> `death`, the rest keep their name.

Value formats (ASCII): dates `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, a leading `-` means BC; `date_range` is `start/end` or a single date for a one-day event; `quantity` is digits; the rest is short text.
Provenance codes: 1 title, 2 infobox, 3 lead_text, 4 lead_sentence (definition), 5 lead_reverse ("Paris is the capital of France" fills France's capital), 6 lead_bold (bold name in the first line).

**Missing markers.** Per entity type the builder lists the fields that should exist: person (birth_date, birth_place, death_date, death_place, surname, occupation), event (date_range, location), country (capital, quantity), place (location, quantity). An expected field that could not be parsed gets a marker. A dead-end like `death_date` for a living person is also a marker: the KB says "no value", not "not asked". A field that is not expected for the type and absent (e.g. the capital of a person) has neither a value nor a marker: the retriever reports `field_missing` with reason `field_not_applicable`.

Surname: only for people, from the title when it is "Given Family" (particles kept: `van Beethoven`), otherwise from the infobox full/birth name or the bold lead name that contains the title (`Napoleon` -> `Bonaparte`). Mononymous people (Plato) get a missing marker rather than a guess.

## Fuzzy (typo) section
Same mechanism as KB3, with the length floor lowered to `fz_min_word` = 4 (KB3: 5; 4-letter names such as Pugh could not be repaired): every key word of 4..20 chars (not all digits), frequency-ranked; variants = word plus each single-character deletion; entries `u32 fnv1a(variant), u32 word_offset`. A query word's candidates are the indexed words sharing a variant with it (substitution, insertion, deletion, adjacent transposition), best (most frequent) 4, from at most 16 offsets. The probe also reports whether the query word itself is indexed (`known`).
Known failure cases: words shorter than `fz_min_word` (`ww2`, `usa`, `pugh` typo'd to `pugg` is fine but `wwi2` is not); two edits inside one word; a typo that is itself an indexed word is never corrected (`francs`); the correct word losing to more frequent neighbours (only 4 candidates are kept per word); two typos in different words are repaired only through the bounded two-word pass (<= 16 extra lookups) and never three.

## Lookup cost
bucket (8 B) + key head (6 B) per entry until the match + key + cand list. Every read goes through the one-sector buffer; both implementations count sector reads. Header is read once at mount.

## Retrieval policy (summary; code is authoritative)
See `retrieve4.py`: gate, relation cue, entity words, candidate n-grams (<= 12 exact lookups), pool of 8, integer scores
(`6*cover%` + kind bonus + prominence - 40 per fuzzy-corrected word; relation stage +60 field present, +20 explicit missing),
ambiguous when the top two candidates have equal coverage and a score gap <= 12, one optional expansion (cue words as entity, delete-index corrections of one word <= 16 lookups, then of two words at once <= 16 more). Relation-word typos (`borrn`, `captial`, `lsat name`) are repaired when the word is not itself a KB word. Leading greetings (`hi,`, `thanks now`) are skipped before the question-word test; `routed=True` lets the router bypass that test.
