# ReCarted technical notes

## Boundaries

This is a recipe converter, not an Atari CPU emulator, a tape decoder for audio, or a general filesystem-to-ROM converter. `images.py` sniffs container magic and parses bounded input (4 MiB maximum). It matches SHA-256 of the **program the tape boot header requests** or the **entire ATR sector payload**. A structurally valid unknown image can be inspected but not converted. No filename, network lookup, downloaded tool, game-byte patch database, captured emulator RAM, or proprietary OS image is needed.

- **CAS:** Walk little-endian FUJI chunks, allow the FUJI description, 600-baud declarations and standard 132-byte data records. Verify the two sync bytes, record framing and the Atari end-around-carry checksum. The recognized games are one-stage boot tapes; some dumps have one extra full block beyond the requested count. Timing gaps, descriptions and that unused block are not part of the game fingerprint. FSK, custom loaders, partial records and additional stages aren't interchangeable with this format. Don't discard a second stage to make the first stage match.
- **ATR:** Validate the paragraph count against file size and account for short boot sectors when inspecting double-density media. Only exact, single-density images in the catalog convert. Bruce Lee's boot sector and relocation stage describe a contiguous RAM program. Jumpman and Pinball Construction Set still read sectors after startup, so a bare RAM dump is not a substitute for a disk reader.
- **ATX:** Reports the signature only; makes no statement about the tracks' integrity. An ATR-style extraction loses duplicate sectors, physical timing and error status. No automated ATX recipe ships yet.
- **CAR:** Check the `CART` signature and big-endian additive payload checksum. Verify length for types 41 and 42. Inspection does not imply every other mapper is supported or that the contents are executable. [A8PicoCart firmware mapper table](https://github.com/robinhedwards/A8PicoCart/blob/fb0b36137a969a71b9258841c46676701125699d/source/Pico%20VSCode%20Project/a8_pico_cart/atari_cart.c#L418-L451).

## Output and 6502 boot code

`convert.py` writes a 16-byte CAR header followed by sixteen 8 KiB banks. Bank zero has ReCarted's original boot code, parameters at `$BF00`, and cartridge vectors. Payload starts in bank one. Access `$D500 + bank` to select a bank, `$D510` to release the cartridge. The loader synchronizes the XL cartridge interlock after release. This is **not** a resized type-42 DiskCart image. No DiskCart code or third-party boot binary is included.

- **Memory loader (`asm/memory.s`):** Relocates a small transfer loop to the low stack page, copies the program to its original address in RAM, disables the cart and enters the program with the boot variables it expects. An XEX output instead uses load segments, sets boot variables and supplies RUNAD. Payload data is taken from the user's input at conversion time.
- **Disk reader (`asm/disk.s`):** For the two 720-sector recipes, copies the host machine's XL/XE OS to RAM underneath ROM, skipping the I/O hole. Patches **DSKINV**, not all of SIO, to a small D1: read-only handler in shadow RAM in the international character set area. Copies the requested boot sectors, then enters the disk program. Each subsequent 128-byte sector is addressed as `(sector-1) / 64` banks past bank one and `(sector-1) % 64` sectors into that bank. Writes, other units and invalid sector numbers fail. Programs that bank the ROM OS back in, need the international font, use RAM underneath the OS, bypass DSKINV, or depend on write/status/timing semantics cannot assume this works. Do not enable this path just because an unknown disk is 90 KiB.

Both loaders are shipped **preassembled** as package resources. Users don't need a compiler. To change them, install cc65 (`ca65` and `ld65` on PATH), edit the corresponding `.s` file and `make -B loaders`. Commit both source and regenerated blobs. Linux CI checks byte-for-byte reproducibility.

## Local development

```sh
git clone https://github.com/feoh/recarted.git
cd recarted
uv sync --locked --python 3.11
uv run recarted --help
uv run prek run --all-files
uv run mypy src
uv run pytest
uv build
```

Unit tests generate their own tapes/disks. Nothing in `tests` requires commercial media. A small 6502 harness exercises the mapper and the assembled code with synthetic RAM, ROM and input sectors. It isn't a substitute for Atari800 or hardware tests.

## Verification and adding recipes

Linux Atari800 5.2.0, PAL 800XL, stock XL OS, no attached tape or disk: startup checked for the six game CAR recipes. Observed the Minter titles/attract screens, Bruce Lee title, Jumpman start/attract screen and Pinball Construction Set editor. The cassette regression inputs for this pass were standard CAS streams reconstructed from the known boot payloads, not fresh reads of the historical tape containers. Jumpman was also checked against its archived original ATR. In separate Atari800 runs, all four game XEX outputs reached an identifiable game screen and the built-in CAS example displayed colour bars. These are startup checks, **not** full playthroughs, save tests or physical A8PicoCart certification. Test a real supported device before claiming hardware verification. The project's synthetic colour-bar tape and disk can be freely shared for reproductions.

For a new release, inspect the actual loading path and what it does *after* startup. Confirm any extra reads, writes, bank switching and later stages; add a digest only after validating the conversion. Add a generated regression case for the new behavior. Test with no source media mounted, check an identifiable title/editor, and launch a game if possible. Record exactly which features, machine, OS and mapper were tested. Keep emulator screenshots of commercial games and all third-party media out of this repository.
