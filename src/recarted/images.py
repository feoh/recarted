"""Parse containers before consulting the small, content-addressed recipe table."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from struct import unpack_from

from .example import SECTOR, tape_checksum

MAX_INPUT = 4 * 1024 * 1024


@dataclass(frozen=True)
class Recipe:
    name: str
    medium: str
    loader: str
    digest: str


RECIPES = (
    Recipe(
        "Attack of the Mutant Camels",
        "CAS",
        "tape",
        "7d875a1c346baf8be767f3cdc98fd56ee55a71726b470d550ca8427155109926",
    ),
    Recipe(
        "Gridrunner",
        "CAS",
        "tape",
        "0d6a93ecb7bc0846878635d3a08bd4c065adb2fbff2763007df05bfdc100a7a5",
    ),
    Recipe(
        "Hover Bovver",
        "CAS",
        "tape",
        "dbd31fa69e7775d92c2ddfa8ea7ea782266ea898e8747ccc875f16657eb5ac86",
    ),
    Recipe(
        "Bruce Lee",
        "ATR",
        "bruce",
        "74b0f21a628b6233eae96ca164ccbf70b2e098bd79b01cc802414a381c19750f",
    ),
    Recipe(
        "Jumpman",
        "ATR",
        "disk",
        "cff56945c4b3cc3e4dd1ed3ab7f2176c0df4455624050b39a39cf8436db04d97",
    ),
    Recipe(
        "Pinball Construction Set",
        "ATR",
        "disk",
        "a7d08dab8436c1414186e38bd20243171d65b45732adffcd1dbbf81ca6eb5767",
    ),
    *(
        Recipe("ReCarted! colour bars", medium, "tape", sha256(SECTOR).hexdigest())
        for medium in ("CAS", "ATR")
    ),
)


@dataclass(frozen=True)
class Image:
    medium: str
    detail: str
    payload: bytes = b""
    recipe: Recipe | None = None
    mapper: int | None = None


def read_input(path: Path) -> bytes:
    if not path.is_file():
        raise ValueError(f"Not a regular file: {path}")
    with path.open("rb") as stream:
        data = stream.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        raise ValueError("File exceeds the 4 MiB inspection limit.")
    return data


def match(medium: str, detail: str, payload: bytes) -> Image:
    digest = sha256(payload).hexdigest()
    recipe = next(
        (r for r in RECIPES if r.medium == medium and r.digest == digest), None
    )
    return Image(medium, detail, payload, recipe)


def disk(data: bytes) -> Image:
    if len(data) < 16:
        raise ValueError("Truncated ATR header.")
    paragraphs, sector, high = unpack_from("<HHH", data, 2)
    payload = data[16:]
    if not payload or len(payload) != ((high << 16) | paragraphs) * 16:
        raise ValueError("ATR length does not match its header.")
    if sector not in (128, 256):
        return Image("ATR", f"{sector}-byte sectors are not supported.")
    boot_size = min(len(payload), 384)
    rest, tail = divmod(len(payload) - boot_size, sector)
    if tail or boot_size % 128:
        raise ValueError("Incomplete ATR sector.")
    detail = f"{boot_size // 128 + rest} sectors; {sector} bytes per data sector."
    if sector != 128:
        return Image("ATR", detail + " No double-density recipe.")
    return match("ATR", detail, payload)


def cassette(data: bytes) -> Image:
    pos = 0
    blocks = bytearray()
    records = 0
    eof = False
    reason = ""
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError("Truncated CAS chunk header.")
        kind, size, aux = unpack_from("<4sHH", data, pos)
        pos += 8
        if pos + size > len(data):
            raise ValueError("Truncated CAS chunk body.")
        chunk = data[pos : pos + size]
        pos += size
        if kind == b"FUJI" and pos == 8 + size:
            continue
        if kind == b"baud":
            if size or aux != 600:
                reason = "Nonstandard baud rate or baud chunk."
        elif kind == b"data":
            records += 1
            if len(chunk) != 132 or chunk[:2] != b"UU":
                reason = "Custom or nonstandard tape framing."
                continue
            if chunk[-1] != tape_checksum(chunk[:-1]):
                raise ValueError(f"Bad cassette checksum in record {records}.")
            if eof:
                reason = "Multiple tape stages."
            if chunk[2] == 0xFC:
                blocks.extend(chunk[3:131])
            elif chunk[2] == 0xFE:
                eof = True
            else:
                reason = "Partial or custom tape record."
        else:
            reason = f"Unsupported CAS chunk {kind!r}."
    if reason:
        return Image("CAS", reason + " No conversion recipe.")
    if not eof or len(blocks) < 128:
        raise ValueError("Incomplete cassette boot stream (missing data or EOF).")
    # Some mastering tools wrote one extra complete record beyond the count
    # requested by the Atari boot header. It is never loaded by these games.
    count = blocks[1] or 256
    if len(blocks) // 128 not in (count, count + 1):
        return Image("CAS", "Tape does not match a single-stage boot program.")
    return match(
        "CAS", f"600 baud; {count} boot records.", bytes(blocks[: 128 * count])
    )


# The two Atarimax formats are often confused: 1 Mbit != 1 MiB.
def cartridge(data: bytes) -> Image:
    if len(data) <= 16:
        raise ValueError("Truncated or empty CAR.")
    mapper, checksum = unpack_from(">II", data, 4)
    payload = data[16:]
    if checksum != sum(payload) & 0xFFFFFFFF:
        raise ValueError("Bad CAR checksum.")
    expected = {41: 131072, 42: 1048576}.get(mapper)
    if expected is not None and expected != len(payload):
        raise ValueError(
            f"Type {mapper} needs {expected} payload bytes, not {len(payload)}."
        )
    support = {
        41: "Mapper supported by stock A8PicoCart.",
        42: "Unsupported by stock A8PicoCart. Changing the header is not a conversion.",
    }.get(mapper, "Compatibility not assessed by ReCarted.")
    return Image(
        "CAR",
        f"Type {mapper}; {len(payload)} bytes; checksum OK. {support}",
        mapper=mapper,
    )


def identify(data: bytes) -> Image:
    if data.startswith(b"FUJI"):
        return cassette(data)
    if data.startswith(b"\x96\x02"):
        return disk(data)
    if data.startswith(b"CART"):
        return cartridge(data)
    if data.startswith(b"AT8X"):
        return Image(
            "ATX",
            "ATX signature detected; track-level disk conversion is not supported.",
        )
    raise ValueError(
        "Unrecognized file signature. Expected CAS, ATR, ATX or CAR (not a ZIP or WAV)."
    )
