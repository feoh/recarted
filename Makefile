LOADERS := src/recarted/loaders/memory.bin src/recarted/loaders/disk.bin
.PHONY: loaders
loaders: $(LOADERS)

src/recarted/loaders/%.bin: asm/%.s asm/loader.cfg
	mkdir -p build $(@D)
	ca65 $< -o build/$*.o
	ld65 -C asm/loader.cfg build/$*.o -o $@
