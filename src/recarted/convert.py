"""Package recognized payloads with ReCarted's own 6502 loaders."""

from importlib.resources import files
from pathlib import Path
from struct import pack

from .capture import LOAD, capture_program
from .images import Image


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


def convert_image(
    image: Image, kind: str = "car", *, os_rom: Path | None = None
) -> bytes:
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
        if recipe.loader == "capture":
            if kind != "car":
                raise ValueError("This ATX recipe produces a .car, not an .xex.")
            payload, run = capture_program(payload, os_rom)
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
    boot = files("recarted").joinpath("loaders", loader + ".bin").read_bytes()
    if len(boot) > 0x1F00 or len(payload) > 15 * 8192:
        raise ValueError("Loader or payload does not fit a type-41 cartridge.")
    rom = bytearray([0xFF]) * 131072
    rom[: len(boot)] = boot
    rom[0x1F00 : 0x1F00 + len(params)] = params
    rom[0x1FF9:8192] = bytes.fromhex("60 00 a0 00 04 f9 bf")
    rom[8192 : 8192 + len(payload)] = payload
    return pack(">4sIII", b"CART", 41, sum(rom), 0) + rom
