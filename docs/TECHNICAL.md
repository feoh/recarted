# ReCarted technical notes

## Boundaries

This is a recipe converter, not an Atari CPU emulator, a tape decoder for audio, or a general filesystem-to-ROM converter. `images.py` sniffs container magic and parses bounded input (4 MiB maximum). It matches SHA-256 of the **program the tape boot header requests** the **entire ATR sector payload**, or the **whole ATX file**. A structurally valid unknown image can be inspected but not converted. Recognition does not depend on a filename or network lookup. No commercial input, captured memory, or proprietary OS is shipped.

- **CAS:** Walk little-endian FUJI chunks, allow the FUJI description, 600-baud declarations and standard 132-byte data records. Verify the two sync bytes, record framing and the Atari end-around-carry checksum. The recognized games are one-stage boot tapes; some dumps have one extra full block beyond the requested count. Timing gaps, descriptions and that unused block are not part of the game fingerprint. FSK, custom loaders, partial records and additional stages aren't interchangeable with this format. Don't discard a second stage to make the first stage match.
- **ATR:** Validate the paragraph count against file size and account for short boot sectors when inspecting double-density media. Only exact, single-density images in the catalog convert. Bruce Lee's boot sector and relocation stage describe a contiguous RAM program. Jumpman and Pinball Construction Set still read sectors after startup, so a bare RAM dump is not a substitute for a disk reader.
- **ATX v1:** Walk bounded track records and their length-prefixed chunks. Read each physical sector header without deduplicating it; report repeated IDs and controller error flags. Recognition hashes the original bytes, not a normalized sector map. Exact Jumpman maps cleanly to 40 single-density tracks of 18 unique sectors: reject exceptional geometry, extension chunks and flagged/missing sectors, order by logical sector, then require the existing ATR payload digest as a second check. The generated colour-bar ATX exercises a one-track variant. Other unrecognized images are never linearized for conversion.
- **Emulator-assisted ATX:** `capture.py` boots the three catalogued protected disks unmodified, from a read-only temporary copy. Atari800 must support ATX, headless SDL and the text monitor. We use a private config and NTSC 800XL, no BASIC or OS patches. The caller supplies stock XL/XE OS rev. 2 (SHA-256 `a77050b2d81db2d11eaa3dbafd8ec2531b478abcc3bcc4b0d846b634e885edb1`). No shell or caller-supplied paths enter the monitor commands. The game's own loader handles timing and error checks before handing off at `$4E8D` (Lyrae), `$0418` (Bruce Lee) or `$0680` (O'Riley's Mine). Require the breakpoint transcript, a complete `$0400–$BFFF` RAM dump and a matching fingerprint of 128 bytes at the entry point. Package only the game RAM with the memory loader, **not** a CPU snapshot or the OS ROM. Abort on timeout, emulator errors or signature mismatch; remove temporary media and RAM on exit. The output does not emulate the original disk drive or persist disk writes.
- **ROM:** Only fall back to the `.rom` suffix after checking all container signatures. Compare the entire raw payload's SHA-256 with verified cartridge types. For an unmatched dump, require an explicit `--rom-type` and validate its length; never infer a bank-switching scheme from size. The wrapper adds only the `CART` header with type, checksum and zero reserved bytes. No loader, padding, emulated disk, or compatibility patches are inserted.
- **CAR:** Check the `CART` signature and big-endian additive payload checksum. Verify length for types 1, 2, 41 and 42. Inspection does not imply every other mapper is supported or that the contents are executable. [A8PicoCart firmware mapper table](https://github.com/robinhedwards/A8PicoCart/blob/fb0b36137a969a71b9258841c46676701125699d/source/Pico%20VSCode%20Project/a8_pico_cart/atari_cart.c#L418-L451).

## Output and 6502 boot code

For disk and tape recipes `convert.py` writes a 16-byte CAR header followed by sixteen 8 KiB banks. Bank zero has ReCarted's original boot code, parameters at `$BF00`, and cartridge vectors. Payload starts in bank one. Access `$D500 + bank` to select a bank, `$D510` to release the cartridge. The loader synchronizes the XL cartridge interlock after release. This is **not** a resized type-42 DiskCart image. No DiskCart code or third-party boot binary is included.

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

Linux Atari800 5.2.0, PAL 800XL, stock XL OS, no attached tape or disk: startup checked for the six game CAR recipes. Observed the Minter titles/attract screens, Bruce Lee title, Jumpman start/attract screen and Pinball Construction Set editor. The cassette regression inputs for this pass were standard CAS streams reconstructed from the known boot payloads, not fresh reads of the historical tape containers. Jumpman was also checked against its archived original ATR. In separate Atari800 runs, all four game XEX outputs reached an identifiable game screen and the built-in CAS example displayed colour bars. These are startup checks, **not** full playthroughs, save tests or physical A8PicoCart certification. Test a real supported device before claiming hardware verification. The project's synthetic colour-bar tape and disks can be freely shared for reproductions.

ATX checks in 0.2: all three commercial ATX inputs were converted locally. Booting only the new CARs under Atari800 5.2.0 (NTSC 800XL) reached the Cadet Mission after pressing START in The Tail of Beta Lyrae, Bruce Lee's title and first playfield, and Jumpman's Epyx title sequence. These are separate tests from booting the disks during conversion; later levels and physical hardware were not tested.

O'Riley's Mine (Datasoft ATX, SHA-256 `f8e2c9cbfd5fa73ed911ce10ec0804778da72382460731e3fa958666e5d404e8`): its boot loader reads a sector list from a duplicated sector 17, so the image cannot be linearized. Three conversions produced identical RAM captures. Booting only the new CAR under Atari800 5.2.0 (NTSC 800XL, stock XL OS rev. 2, no disk attached) reached the title and high-score screen; holding START reached the level 1 mine shaft playfield. Checked from monitor RAM dumps of the display list, not a playthrough or hardware test.

For a new release, inspect the actual loading path and what it does *after* startup. Confirm any extra reads, writes, bank switching and later stages; add a digest only after validating the conversion. Add a generated regression case for the new behavior. Test with no source media mounted, check an identifiable title/editor, and launch a game if possible. Record exactly which features, machine, OS and mapper were tested. Keep emulator screenshots of commercial games and all third-party media out of this repository.
