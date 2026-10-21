#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Build the clean product and stage files; never write to a physical card.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE=assistant MODEL="" TOK="" ASSET_DIR="" KB="" KB4="" KB_ATTRIBUTION="" STEPS="" PROMPT=""
OUT="$ROOT/ds/hwkit/sdcard"
while (($#)); do
    case "$1" in
        --mode|--asset-dir|--model|--tokenizer|--kb|--kb4|--kb-attribution|--steps|--prompt|--out)
            (($# >= 2)) || { echo "Missing value: $1" >&2; exit 2; }
            case "$1" in
                --mode) MODE=$2;; --asset-dir) ASSET_DIR=$2;;
                --model) MODEL=$2;; --tokenizer) TOK=$2;; --kb) KB=$2;; --kb4) KB4=$2;;
                --kb-attribution) KB_ATTRIBUTION=$2;;
                --steps) STEPS=$2;; --prompt) PROMPT=$2;; --out) OUT=$2;;
            esac; shift 2;;
        *) echo 'Usage: make-kit.sh (--asset-dir DIR | --model PATH --tokenizer PATH) [--mode assistant|story] [(--kb PATH | --kb4 PATH) --kb-attribution PATH] [--steps N] [--prompt TEXT] [--out DIR]' >&2; exit 2;;
    esac
done
if [[ -n "$ASSET_DIR" ]]; then
    [[ -z "$MODEL" && -z "$TOK" ]] || { echo '--asset-dir conflicts with --model/--tokenizer' >&2; exit 2; }
    ASSET_DIR=$(realpath -e "$ASSET_DIR")
    # Verify the pair only. Never follow manifest paths or accept a missing entry.
    python3 - "$ASSET_DIR" <<'PY'
import hashlib, pathlib, re, sys
root = pathlib.Path(sys.argv[1])
entries = {}
for line in (root / 'SHA256SUMS').read_text().splitlines():
    match = re.fullmatch(r'([0-9a-fA-F]{64}) [ *](model\.bin|tok\.bin)', line)
    if match:
        digest, name = match.groups()
        if name in entries:
            raise SystemExit('duplicate asset checksum: ' + name)
        entries[name] = digest.lower()
for name in ('model.bin', 'tok.bin'):
    if name not in entries or hashlib.sha256((root / name).read_bytes()).hexdigest() != entries[name]:
        raise SystemExit('asset checksum missing or mismatched: ' + name)
PY
    MODEL="$ASSET_DIR/model.bin"; TOK="$ASSET_DIR/tok.bin"
fi
[[ -n "$MODEL" && -n "$TOK" ]] || { echo 'Supply --asset-dir or both --model and --tokenizer; no implicit model fallback.' >&2; exit 2; }
case "$MODE" in
    story) STEPS=${STEPS:-200}; PROMPT=${PROMPT:-Once upon a time}; INSTRUCT=0;;
    assistant) STEPS=${STEPS:-64}; PROMPT=${PROMPT:-whats 38 times 47}; INSTRUCT=1;;
    *) echo 'Mode must be story or assistant' >&2; exit 2;;
esac
[[ "$STEPS" =~ ^[1-9][0-9]*$ ]] && ((STEPS <= 256)) || { echo 'steps must be 1..256' >&2; exit 2; }
MODEL=$(realpath -e "$MODEL"); TOK=$(realpath -e "$TOK")
[[ -z "$KB" || -z "$KB4" ]] || { echo 'Choose --kb or --kb4, not both' >&2; exit 2; }
KB_NAME=kb.bin
if [[ -n "$KB4" ]]; then KB=$KB4; KB_NAME=kb4.bin; fi
if [[ -n "$KB" ]]; then
    ((INSTRUCT)) || { echo '--kb only makes sense in assistant mode' >&2; exit 2; }
    KB=$(realpath -e "$KB"); [[ -f "$KB" ]] || exit 2
fi
if [[ -n "$KB_ATTRIBUTION" ]]; then
    [[ -n "$KB" ]] || { echo '--kb-attribution requires --kb or --kb4' >&2; exit 2; }
    KB_ATTRIBUTION=$(realpath -e "$KB_ATTRIBUTION")
elif [[ -n "$KB" ]]; then
    # CC BY-SA index: never stage it without its attribution.
    echo '--kb/--kb4 requires --kb-attribution (the ATTRIBUTION.txt written by the KB builder)' >&2; exit 2
fi
[[ -f "$MODEL" && -f "$TOK" ]] || exit 2
python3 - "$PROMPT" <<'PY'
import sys
p = sys.argv[1]
if not p or not p.isascii() or len(p) > 127 or any(c in p for c in '\n\r\0'):
    raise SystemExit('prompt must be one nonempty ASCII line, at most 127 bytes')
PY
OUT=$(realpath -m "$OUT")
mkdir -p "$(dirname "$OUT")"
[[ ! -e "$OUT.previous" ]] || { echo "Move $OUT.previous aside first; refusing to overwrite backup" >&2; exit 2; }
STAGE=$(mktemp -d "$(dirname "$OUT")/.kit-stage.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/chatds" "$STAGE/.host"
source "$ROOT/tools/env.sh"
make -j2 -C "$ROOT/clean/product" all host
cp "$ROOT/clean/product/build/chatds.nds" "$STAGE/chatds.nds"
cp "$MODEL" "$STAGE/chatds/model.bin"
cp "$TOK" "$STAGE/chatds/tok.bin"
[[ -z "$KB" ]] || cp "$KB" "$STAGE/chatds/$KB_NAME"
if ((INSTRUCT)); then
    for head in act op tag; do
        cp "$ROOT/campaign/router/models/round3-$head.cdsr" "$STAGE/chatds/"
    done
fi
[[ -z "$KB_ATTRIBUTION" ]] || cp "$KB_ATTRIBUTION" "$STAGE/chatds/kb-ATTRIBUTION.txt"
cp "$ROOT/LICENSE" "$STAGE/LICENSE"
cp "$ROOT/THIRD_PARTY_NOTICES.md" "$STAGE/THIRD_PARTY_NOTICES.md"
printf 'steps=%s\nkbd=1\ninstruct=%s\nprompt=%s\n' "$STEPS" "$INSTRUCT" "$PROMPT" > "$STAGE/chatds/run.txt"
# Clean host/device smoke expectation, distinct from the frozen legacy goldens.
CHATDS_ROUND3_DIR="$STAGE/chatds/" "$ROOT/clean/product/build/chatds-host" "$MODEL" "$TOK" "${KB:--}" \
    "$STAGE/chatds/run.txt" "$STAGE/.host/"
cp "$STAGE/.host/ids.txt" "$STAGE/.host-golden.ids"
cp "$STAGE/.host/out.txt" "$STAGE/.host-golden.txt"
tail -n 6 "$STAGE/.host/out.txt" > "$STAGE/.host-golden.ids.meta"
rm -r "$STAGE/.host"
python3 - "$STAGE" "$MODE" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
files = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())
manifest = {'mode': sys.argv[2], 'engine': 'clean-dsq8-kv16',
            'quality': 'experimental; not a capability certification',
            'sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in files}}
(root / 'kit.json').write_text(json.dumps(manifest, indent=2) + '\n')
PY
if [[ -e "$OUT" ]]; then mv "$OUT" "$OUT.previous"; fi
mv "$STAGE" "$OUT"
trap - EXIT
printf '\nStaged clean %s kit: %s\nPrevious kit preserved at %s.previous (if present).\nNo physical SD card touched.\n' "$MODE" "$OUT" "$OUT"
