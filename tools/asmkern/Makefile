# SPDX-License-Identifier: MIT
export WONDERFUL_TOOLCHAIN ?= $(HOME)/opt/wonderful
export BLOCKSDS ?= $(WONDERFUL_TOOLCHAIN)/thirdparty/blocksds/core
PREFIX ?= $(WONDERFUL_TOOLCHAIN)/toolchain/gcc-arm-none-eabi/bin/arm-none-eabi-
TIMING ?= 0
BUILD := $(if $(filter 1,$(TIMING)),build-timing,build)
ARM := -std=gnu23 -O3 -g -Wall -Wextra -Werror -marm -mcpu=arm946e-s+nofp \
 -ffunction-sections -fdata-sections -DARM9 -D__NDS__ -D__BLOCKSDS__ \
 -I$(BLOCKSDS)/libs/libnds/include -I../../clean/src -I../../clean/include \
 -specs=$(BLOCKSDS)/sys/crts/ds_arm9.specs
OBJS := $(addprefix $(BUILD)/,probe.o thumb.o dot32_arm.o kernels.o format.o engine.o)
ifeq ($(TIMING),1)
ARM += -DCDS_TIMING_PROBE
else
ARM += -DCDS_TEST_ASM
OBJS += $(BUILD)/test_asm.o
WRAP := -Wl,--wrap=cds_dot32_arm
endif
.PHONY: all
all: $(BUILD)/asmkern.nds
$(OBJS): Makefile
$(BUILD):
	mkdir -p $@
$(BUILD)/probe.o: probe.c ../../clean/src/internal.h | $(BUILD)
	$(PREFIX)gcc $(ARM) -c $< -o $@
$(BUILD)/thumb.o: thumb.c | $(BUILD)
	$(PREFIX)gcc $(ARM) -mthumb -c $< -o $@
$(BUILD)/test_asm.o: ../../clean/tests/test_asm.c ../../clean/src/internal.h | $(BUILD)
	$(PREFIX)gcc $(ARM) -c $< -o $@
$(BUILD)/dot32_arm.o: ../../clean/src/dot32_arm.S | $(BUILD)
	$(PREFIX)gcc $(ARM) -c $< -o $@
$(BUILD)/kernels.o: ../../clean/src/kernels.c ../../clean/src/internal.h | $(BUILD)
	$(PREFIX)gcc $(ARM) -c $< -o $@
$(BUILD)/format.o: ../../clean/src/format.c ../../clean/src/internal.h | $(BUILD)
	$(PREFIX)gcc $(ARM) -c $< -o $@
# Only diagnostic dispatch instrumentation. Production engine.c stays untouched.
$(BUILD)/engine.c: ../../clean/src/engine.c Makefile | $(BUILD)
	python3 -c 'from pathlib import Path; p=Path("../../clean/src/engine.c"); s=p.read_text(); Path("$@").write_text(s.replace("#include \"internal.h\"", "#include \"internal.h\"\nextern void probe_matvec(int32_t *, const cds_matrix *, const int32_t *, uint32_t, int16_t *, uint64_t *);").replace("cds_matvec_fast(", "probe_matvec("))'
$(BUILD)/engine.o: $(BUILD)/engine.c ../../clean/src/internal.h
	$(PREFIX)gcc $(ARM) -c $< -o $@
$(BUILD)/asmkern.elf: $(OBJS)
	$(PREFIX)gcc $(ARM) $^ -o $@ -L$(BLOCKSDS)/libs/libnds/lib \
	 $(WRAP) -Wl,--defsym=__usr_stack_size=4096 -Wl,-Map,$(BUILD)/asmkern.map \
	 -Wl,--start-group -lnds9 -lc -lm -Wl,--end-group
$(BUILD)/asmkern.nds: $(BUILD)/asmkern.elf check_layout.py
	python3 check_layout.py --prefix $(PREFIX) --elf $< --map $(BUILD)/asmkern.map --out $(BUILD)/layout.json
	$(BLOCKSDS)/tools/ndstool/ndstool -c $@ \
	 -7 $(BLOCKSDS)/sys/arm7/main_core/arm7_maxmod.elf -9 $< \
	 -b $(BLOCKSDS)/sys/icon.gif 'ASMKERN probe;EMULATED diagnostic;Not product ROM'
