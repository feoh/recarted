"""Package recognized payloads with ReCarted's own 6502 loaders."""

from importlib.resources import files
from pathlib import Path
from struct import pack

from . import atx
from .capture import LOAD, capture_program, find
from .images import STANDARD_ROM_SIZES, Image


def save_new(path: Path, contents: bytes) -> None:
    try:
        stream = path.open("xb")
    except FileExistsError as exc:
        raise ValueError(
            f"Will not overwrite {path}. Choose a new output filename."
        ) from exc
    try:
        with stream:
            stream.write(contents)
    except OSError:
        path.unlink(missing_ok=True)
        raise


def segment(addr: int, data: bytes) -> bytes:
    return pack("<HH", addr, addr + len(data) - 1) + data


def _car(mapper: int, payload: bytes | bytearray) -> bytes:
    return pack(">4sIII", b"CART", mapper, sum(payload) & 0xFFFFFFFF, 0) + payload


def _type41(loader: str, params: bytes, *banks: tuple[int, bytes]) -> bytes:
    """Bank 0: ReCarted boot code, params at $BF00 and vectors; data from bank N."""
    boot = files("recarted").joinpath("loaders", loader + ".bin").read_bytes()
    if len(boot) > 0x1F00 or any(
        bank < 1 or bank * 8192 + len(data) > 131072 for bank, data in banks
    ):
        raise ValueError("Loader or payload does not fit a type-41 cartridge.")
    rom = bytearray([0xFF]) * 131072
    rom[: len(boot)] = boot
    rom[0x1F00 : 0x1F00 + len(params)] = params
    rom[0x1FF9:8192] = bytes.fromhex("60 00 a0 00 04 f9 bf")
    for bank, data in banks:
        rom[bank * 8192 : bank * 8192 + len(data)] = data
    return _car(41, rom)


def hybrid_car(load: int, ram: bytes, entry: int, first: int, sectors: bytes) -> bytes:
    """Captured RAM from bank 1, then a read-only window of 128-byte sectors."""
    pages = (len(ram) + 255) // 256
    if load & 255 or not 1 <= pages <= 255 or load + pages * 256 > 0xC000:
        raise ValueError("Program is outside supported Atari RAM.")
    if not sectors or len(sectors) % 128:
        raise ValueError("Incomplete sector window.")
    disk_bank = 1 + (pages + 31) // 32
    params = pack(
        "<BBHBHH", load >> 8, pages, entry, disk_bank, first, len(sectors) // 128
    )
    return _type41("hybrid", params, (1, ram), (disk_bank, sectors))


def convert_image(
    image: Image,
    kind: str = "car",
    *,
    os_rom: Path | None = None,
    rom_type: int | None = None,
) -> bytes:
    if image.medium == "ROM":
        if kind != "car":
            raise ValueError(
                "A cartridge ROM can be wrapped as .car, not converted to .xex."
            )
        mapper = image.mapper if rom_type is None else rom_type
        if mapper is None:
            raise ValueError(image.detail)
        if mapper not in STANDARD_ROM_SIZES:
            raise ValueError(
                "--rom-type supports only 1 (standard 8 KiB) and 2 (standard 16 KiB)."
            )
        if len(image.payload) != STANDARD_ROM_SIZES[mapper]:
            raise ValueError(
                f"Type {mapper} requires {STANDARD_ROM_SIZES[mapper]:,} bytes; file has {len(image.payload):,}."
            )
        return _car(mapper, image.payload)
    if rom_type is not None:
        raise ValueError(
            "--rom-type is only for headerless .rom input, not a file with a recognized header."
        )
    if image.medium == "CAR":
        raise ValueError("Already a CART-format cartridge; no conversion needed.")
    recipe = image.recipe
    if recipe is None:
        raise ValueError(
            f"No conversion recipe for this {image.medium}. No file written. Run recarted recipes to see supported revisions."
        )
    if kind not in ("car", "xex"):
        raise ValueError("Choose .car or .xex as the output extension.")
    payload = image.payload
    loader = "memory"
    if recipe.loader == "disk":
        if kind != "car":
            raise ValueError(
                "This program reads sectors after startup. Choose a .car output, not .xex."
            )
        loader = "disk"
        params = payload[2:4] + payload[1:2]
    else:
        if recipe.loader in ("capture", "capture-disk"):
            if kind != "car":
                raise ValueError("This ATX recipe produces a .car, not an .xex.")
            spec = find(payload)
            window = spec.sectors if spec else None
            # Check the clean tracks before spending time in the emulator.
            sectors = atx.sd_sector_window(payload, *window) if window else b""
            payload, run = capture_program(payload, os_rom)
            if window:
                return hybrid_car(LOAD, payload, run, window[0], sectors)
            load, casini = LOAD, 0
        elif recipe.loader == "bruce":
            # The first sector is the disk reader; the next $7400 bytes are
            # relocated to $0400 by the original final-stage loader.
            payload = payload[128 : 128 + 0x7400]
            load, run, casini = 0x400, 0x400, 0
        else:
            load = int.from_bytes(payload[2:4], "little")
            casini = int.from_bytes(payload[4:6], "little")
            run = load + 6
        if not (0x400 <= load and load + len(payload) <= 0xC000):
            raise ValueError("Program is outside supported Atari RAM.")
        if kind == "xex":
            return (
                b"\xff\xff"
                + segment(load, payload)
                + segment(9, b"\x02")
                + segment(0x244, b"\0")
                + segment(0x0C, pack("<H", casini))
                + segment(0x2E0, pack("<H", run))
            )
        payload = bytes(load & 255) + payload
        params = pack("<BBHH", load >> 8, (len(payload) + 255) // 256, run, casini)
    return _type41(loader, params, (1, payload))
