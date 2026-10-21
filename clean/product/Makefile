# SPDX-License-Identifier: MIT
# Product ROM and host runner: explicit clean-only source allowlist.
export WONDERFUL_TOOLCHAIN ?= $(HOME)/opt/wonderful
export BLOCKSDS ?= $(WONDERFUL_TOOLCHAIN)/thirdparty/blocksds/core
PREFIX ?= $(WONDERFUL_TOOLCHAIN)/toolchain/gcc-arm-none-eabi/bin/arm-none-eabi-
BUILD := build
CORE := ../src/format.c ../src/kernels.c ../src/engine.c
PLUMBING := $(addprefix ../plumbing/,calc.c mathnb.c mathnb_render.c generate.c io.c kb.c retrieve.c kb4.c retrieve4.c entres_index.c prestep.c textops.c router.c round3.c)
UI := $(wildcard ../ui/src/*.c) ../ui/adapter/ui_engine_gen.c ../ui/shell/ui_script.c
SOURCES := main.c dispatch.c rules.c learned.c ../../ds/tokenizer/tok.c $(CORE) $(PLUMBING) $(UI)
HEADERS := $(wildcard *.h ../include/*.h ../src/*.h ../plumbing/*.h ../ui/include/*.h ../ui/src/*.h ../../ds/tokenizer/*.h)
COMMON := -std=c99 -O3 -g -Wall -Wextra -Werror -fstack-usage \
 -I../include -I../src -I../plumbing -I../ui/include -I../../ds/tokenizer
ARM := -std=gnu23 -marm -mcpu=arm946e-s+nofp -ffunction-sections -fdata-sections \
 -DARM9 -D__NDS__ -D__BLOCKSDS__ \
 -I$(BLOCKSDS)/libs/libnds/include -specs=$(BLOCKSDS)/sys/crts/ds_arm9.specs
.PHONY: all host clean
all: $(BUILD)/chatds.nds
host: $(BUILD)/chatds-host
$(BUILD):
	mkdir -p $@
HOST_OBJS := $(addprefix $(BUILD)/host/,$(notdir $(SOURCES:.c=.o)))
ARM_OBJS := $(addprefix $(BUILD)/nds/,$(notdir $(SOURCES:.c=.o))) $(BUILD)/nds/dot32_arm.o
$(BUILD)/nds/dot32_arm.o: ../src/dot32_arm.S Makefile
	@mkdir -p $(BUILD)/nds
	$(PREFIX)gcc $(ARM) -c $< -o $@
define COMPILE
$(BUILD)/host/$(notdir $(1:.c=.o)): $(1) $(HEADERS) Makefile
	@mkdir -p $(BUILD)/host
	$(CC) $(COMMON) -c $$< -o $$@
$(BUILD)/nds/$(notdir $(1:.c=.o)): $(1) $(HEADERS) Makefile
	@mkdir -p $(BUILD)/nds
	$(PREFIX)gcc $(COMMON) $(ARM) $$(MODULE_FLAGS) -c $$< -o $$@
endef
$(foreach src,$(SOURCES),$(eval $(call COMPILE,$(src))))
# Size tuning is restricted to fallback integration/execution modules. Engine,
# retrieval, existing rule/prestep arithmetic, and UI keep their shipped flags.
SIZE_MODULES := dispatch learned router round3 textops mathnb mathnb_render
$(addprefix $(BUILD)/nds/,$(addsuffix .o,$(SIZE_MODULES))): MODULE_FLAGS := -Os -mthumb
$(BUILD)/chatds-host: $(HOST_OBJS) | $(BUILD)
	$(CC) $^ -Wl,-Map,$(BUILD)/chatds-host.map -lm -o $@
$(BUILD)/chatds.elf: $(ARM_OBJS) | $(BUILD)
	$(PREFIX)gcc $(ARM) $^ -o $@ \
	 -L$(BLOCKSDS)/libs/libnds/lib -Wl,--defsym=__usr_stack_size=4096 -Wl,-Map,$(BUILD)/chatds.map \
	 -Wl,--start-group -lnds9 -lc -lm -Wl,--end-group
$(BUILD)/layout.ok: $(BUILD)/chatds.elf $(BUILD)/chatds.map ../../tools/asmkern/check_layout.py
	python3 ../../tools/asmkern/check_layout.py --prefix $(PREFIX) --elf $(BUILD)/chatds.elf --map $(BUILD)/chatds.map --out $(BUILD)/layout.json
	touch $@
$(BUILD)/chatds.map: $(BUILD)/chatds.elf
	@test -f $@
$(BUILD)/chatds.nds: $(BUILD)/chatds.elf $(BUILD)/layout.ok
	$(BLOCKSDS)/tools/ndstool/ndstool -c $@ \
	 -7 $(BLOCKSDS)/sys/arm7/main_core/arm7_maxmod.elf -9 $< \
	 -b $(BLOCKSDS)/sys/icon.gif 'ChatDS;Clean DSQ8 engine;ChatDS'
clean:
	rm -rf build
