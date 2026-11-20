"""An original, redistributable one-sector program: ANTIC scanline colour bars."""

from struct import pack

# Boot header: one record at $2000, init $2006. Disable NMI and playfield DMA,
# then feed VCOUNT to GTIA's background register. No Atari ROM bytes here.
SECTOR = bytes.fromhex(
    "00 01 00 20 06 20 78 a9 00 8d 0e d4 8d 00 d4 ad 0b d4 8d 1a d0 4c 0f 20"
).ljust(128, b"\0")


def tape_checksum(data: bytes) -> int:
    total = sum(data)
    return (total - 1) % 255 + 1 if total else 0


def example_image(kind: str) -> bytes:
    if kind == "atr":
        return pack("<HHH", 0x296, 8, 128) + bytes(10) + SECTOR
    if kind != "cas":
        raise ValueError("Choose a .cas or .atr filename for the example.")
    tape = bytearray(b"FUJI" + bytes(4) + b"baud" + pack("<HH", 0, 600))
    for marker, body, gap in [(0xFC, SECTOR, 20000), (0xFE, bytes(128), 250)]:
        record = bytes((0x55, 0x55, marker)) + body
        tape += (
            b"data" + pack("<HH", 132, gap) + record + bytes([tape_checksum(record)])
        )
    return bytes(tape)
