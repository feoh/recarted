"""Parse containers before consulting the small, content-addressed recipe table."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from struct import unpack_from

from . import atx
from .capture import CAPTURES
from .example import SECTOR, example_image, tape_checksum

MAX_INPUT = 4 * 1024 * 1024


@dataclass(frozen=True)
class Recipe:
    name: str
    medium: str
    loader: str
    digest: str


RECIPES = (
    *(Recipe(spec.title, "ATX", "capture", spec.disk_sha256) for spec in CAPTURES),
    Recipe(
        "Jumpman",
        "ATX",
        "disk",
        "496d3b2561c2b1154f3dea6bbca1f58715f95a10d598fe7a8755a2950eb0da79",
    ),
    Recipe(
        "ReCarted! colour bars", "ATX", "tape", sha256(example_image("atx")).hexdigest()
    ),
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


# Standard left-slot Atari computer cartridges. Size constrains the mapper;
# it does not distinguish these from OS ROMs or bank-switched cartridges.
STANDARD_ROM_SIZES = {1: 8192, 2: 16384}
KNOWN_ROMS = {
    "416d708a89529faecd497efff3a9db7c4c5f5266457c96fa0f365eddc3c54ee7": ("Kangaroo", 2),
    "2c4c7403941ea68c03d698221cc880bc24d366de8f2a92b7c02a0d2f320f7d5f": ("Dig Dug", 2),
    "7935c56f84757d8347f8724be7b0aa2e85bc6c3a0f33764a440db910b561c2e1": (
        "Journey to the Planets",
        2,
    ),
    "a3548a583b8890421f1203e6fec0632a3b95c39f014ae1b417442cc7ca8e1ff5": (
        "Pitfall! II - Lost Caverns",
        2,
    ),
    "7e37af6174a4b7d1b37c5f099efd1a9f502216b47482e74b0f3782721caf0812": ("Popeye", 2),
    "e4d4c08d47a48f61d089d6465608208893495417e72e13eaf91402bafc9596e8": ("Qix", 1),
}


def raw_rom(data: bytes) -> Image:
    detail = f"{len(data):,} bytes; raw .rom files have no cartridge-type header."
    known = KNOWN_ROMS.get(sha256(data).hexdigest())
    if known:
        title, mapper = known
        detail += f" Matched {title}: standard CAR type {mapper}."
        if title == "Kangaroo":
            detail += " This dump booted with Atari 800 OS-B but showed a blank screen with the stock 800XL OS."
        return Image("ROM", detail, data, mapper=mapper)
    for candidate, size in STANDARD_ROM_SIZES.items():
        if size == len(data):
            return Image(
                "ROM",
                f"{detail} Unknown mapping. If this is a standard {size // 1024} KiB Atari 8-bit computer cartridge, use convert with --rom-type {candidate}. Size alone cannot confirm that.",
                data,
            )
    return Image(
        "ROM",
        f"{detail} Only standard 8 KiB and 16 KiB cartridge dumps can be wrapped. For other layouts, use a CAR with the correct mapper.",
        data,
    )


# The two Atarimax formats are often confused: 1 Mbit != 1 MiB.
def cartridge(data: bytes) -> Image:
    if len(data) <= 16:
        raise ValueError("Truncated or empty CAR.")
    mapper, checksum = unpack_from(">II", data, 4)
    payload = data[16:]
    if checksum != sum(payload) & 0xFFFFFFFF:
        raise ValueError("Bad CAR checksum.")
    expected = {**STANDARD_ROM_SIZES, 41: 131072, 42: 1048576}.get(mapper)
    if expected is not None and expected != len(payload):
        raise ValueError(
            f"Type {mapper} needs {expected} payload bytes, not {len(payload)}."
        )
    support = {
        1: "Standard 8 KiB cartridge; supported by stock A8PicoCart.",
        2: "Standard 16 KiB cartridge; supported by stock A8PicoCart.",
        41: "Mapper supported by stock A8PicoCart.",
        42: "Unsupported by stock A8PicoCart. Changing the header is not a conversion.",
    }.get(mapper, "Compatibility not assessed by ReCarted.")
    return Image(
        "CAR",
        f"Type {mapper}; {len(payload)} bytes; checksum OK. {support}",
        mapper=mapper,
    )


def identify(data: bytes, *, suffix: str = "") -> Image:
    if data.startswith(b"FUJI"):
        return cassette(data)
    if data.startswith(b"\x96\x02"):
        return disk(data)
    if data.startswith(b"CART"):
        return cartridge(data)
    if data.startswith(b"AT8X"):
        image = match("ATX", atx.description(atx.tracks(data)), data)
        if image.recipe and image.recipe.loader in ("disk", "tape"):
            demo = image.recipe.loader == "tape"
            sectors = atx.linear_sd_disk(data, 1 if demo else 40)
            payload = sectors[:128] if demo else sectors
            # Prove this exact track layout yields the already-tested ATR program.
            equivalent = match("ATR", "", payload)
            if not equivalent.recipe or equivalent.recipe.name != image.recipe.name:
                raise ValueError("ATX sectors do not match the expected program.")
            return Image("ATX", image.detail, payload, image.recipe)
        return image
    if suffix.lower() == ".rom":
        return raw_rom(data)
    raise ValueError(
        "Unrecognized file signature. Expected CAS, ATR, ATX or CAR, or a headerless cartridge dump with a .rom extension."
    )
