# Product ARMv5TE gs32 seam

CPU-only. All timings **emulated melonDS**, not physical DS or cycle-exact ARM9.
No Rust runtime, extra weight copy, DTCM pool, routing change, or model change.

## Product contract

`clean/src/kernels.c` retains `cds_matvec_c`; ARM9 FAST dispatches to the packed
assembly leaf only for gs32, width 32..1024 divisible by 32, and 4-byte-aligned
scratch. Otherwise it calls C. Host FAST always uses C. Both preserve dynamic
quantization, group-by-group floor shifts, row scaling and saturation counts.
Byte-aligned weight rows are supported. The existing loader/buffer contract
still applies; an odd-byte `int16_t *`, zero group size, invalid extents or invalid
scales are not newly supported. Widths 48/33 are diagnostic off-loader inputs:
the seam preserves C's historical floor-group behavior by taking C, not asm.

The boot-only two-row check includes saturation and a nonsaturating row. Failure
permanently disables asm for this process, logs console + `chatds/kernel.txt`,
and leaves inference available through C. There is no allocation in the check.
GCC `noinline,noclone` avoids duplicating the kernels inside the smoke check and
spending unbudgeted ITCM/main RAM. Normal forward/reset remain allocation-free.

## Build and host tests

```sh
source tools/env.sh
nice -n 19 ionice -c3 make -C clean/product -j2 all host
nice -n 19 ionice -c3 make -C clean -j2 test sanitize
nice -n 19 ionice -c3 python3 -m pytest -q tools/asmkern/test_layout.py
nice -n 19 ionice -c3 python3 tools/asmkern/check_overflow.py \
  --build clean/product/build --work build/asmkern/overflow
MAKEFLAGS=-j2 CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  nice -n 19 ionice -c3 python3 tools/run_host_tests.py
```

Packaging depends on `clean/product/build/layout.ok`. `check_layout.py` reads the
**linked map**, ELF ARM/Thumb mapping symbols and disassembly. It rejects ITCM
above 32 KiB or DTCM data encroaching on reserved stacks/system space, and checks
direct calls plus literal-address BX/BLX kernel calls. Same-state ARM BL is safe
without a veneer. Cross-state immediate calls must be BLX. Computed arbitrary
function-pointer dispatch is not proved by this checker and must not be added
without extending the gate. Current product has only ARM engine callers;
Thumb-sized dispatch/router modules do not call this seam. The overflow test
forces live oversized ITCM/DTCM sections into real product links and requires
linker rejection. It never replaces product ROM/map/ELF outputs.

## Actual ARM tests and timing

```sh
nice -n 19 ionice -c3 make -C tools/asmkern -j2
nice -n 19 ionice -c3 python3 tools/asmkern/run_probe.py "$MODEL" \
  --work build/asmkern/probe
nice -n 19 ionice -c3 make -C tools/asmkern -j2 TIMING=1
nice -n 19 ionice -c3 python3 tools/asmkern/run_probe.py "$MODEL" \
  --timing --work build/asmkern/timing
```

Default diagnostic executes the same `clean/tests/test_asm.c` as host, but its
counted leaf wrapper calls **actual ARM assembly**. Ten individual fallback
shapes/alignment cells plus four asm cells, 48 trials each, check output/canaries
and saturation counts against both C kernels. Correctness-only C/ASM dispatch
counters additionally prove the C branch for width zero (leaf counts alone
cannot distinguish an empty ASM loop). These counters do not enter product or
`TIMING=1` builds. Injected leaf error must latch C;
restoring the leaf must not re-enable asm. A separate `-mthumb` unit calls the
ARM leaf, verified in disassembly and execution. Every shipped matrix also runs
8 input modes, 99,328 rows per boot, against wide reference and C fast.

**Never use counted-wrapper timing as a performance result.** `TIMING=1` removes
`--wrap` and the counter entirely. Both builds compare 32 paired forwards /
65,536 logits plus cumulative saturations per boot. Timings use actual history
(prefill 224 deterministic token IDs for long context), 16 classified forwards
at positions 0..15 and 224..239 per kernel, two boots, 32 samples per cell.
Forced IDs are identical, not a quality benchmark. Activations stay main-RAM;
keys use VRAM D/E, as product. Only the private diagnostic engine copy's matvec
call dispatch changes between C and asm. Product engine source is not generated
or modified by this probe. Percentiles are nearest rank; DS bus clock 33,513,982
Hz. Logging/comparison/prefix load and model/card startup are outside forward
timing; attention, all layers and classification are inside.

Every emulator has private ROM, FAT, config, HOME and cache; denied X11/Wayland sockets,
`QT_QPA_PLATFORM=offscreen`, `--nodevice=all`, software renderer. Live `/proc`
evidence checks the loaded Qt offscreen plugin, private config, absent display
environment and GPU descriptors. Cleanup matches only the private ROM's exact
emulator argv and the owned launcher. Timeouts fail, never count as parity.

## Full product golden inputs

```sh
nice -n 19 ionice -c3 python3 tools/asmkern/golden.py \
  --rom "$KIT/chatds.nds" --host clean/product/build/chatds-host \
  --assets "$KIT/chatds" --kb "$FROZEN_KB2" --work build/asmkern/golden
```

Requires the exact model/tokenizer/**KB2** hashes in the 33-case fixture. The
release KB3/KB4 is not the frozen KB2. Every input executes independently through
C product host and product ROM, including raw/story mode and five explicit clean
failures. Compare text, IDs, counts, stop, context, calculator output and status;
require boot check PASS. Historical pre-c24 fixture-answer differences are
recorded separately, never waived as a host/ROM mismatch. `--resume` reuses only
completed records tied to identical host/ROM hashes; failed partial directories
must be preserved/moved manually. Frozen fixtures are never rewritten.

The fixed 60-case screen, four frozen notebook framebuffer captures, 12-turn
stress/mixed protocols and 885-turn route-mix decoder exposure use a private
dev-only harness and eval assets that are not shipped here. No sealed or
held-out scoring data is needed by these tools.
