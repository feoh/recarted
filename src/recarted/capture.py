"""Let a known disk's own loader run in Atari800. Never execute unknown disk images."""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from struct import pack

LOAD = 0x0400
END = 0xC000
OS_SCREEN = 0xBC00  # graphics 0 screen and display list below RAMTOP $C0


@dataclass(frozen=True)
class Capture:
    title: str
    disk_sha256: str
    entry: int
    code_sha256: str  # 128 bytes of loaded code at the hand-off
    end: int = END  # RAM from here to END was all zero at the hand-off
    # Sectors the program still reads after the hand-off, served read-only
    # from clean tracks of the original image.
    sectors: tuple[int, int] | None = None
    # ATX: digest of the whole file. ATR: digest of the sector payload, as
    # for every other ATR recipe; a plain header is rebuilt to boot it.
    medium: str = "ATX"


CAPTURES = (
    Capture(
        "The Tail of Beta Lyrae",
        "51ae8054c0acb775aa4f2805445750ec5cc6e3f3294d6137f95e5bd32f69e2f3",
        0x4E8D,
        "197c236b59c8cb5c5524896463b23ef2cfc5df5fe14c7665c7a04674b9d842c3",
    ),
    Capture(
        "Bruce Lee",
        "781081a971950cfcf5573341311bd6396abf5a9ce08124649edea66b00d5bf78",
        0x0418,
        "d46fba5c0e3fc344d1ef63c5708c61634367c2ffea80254757660780146a508b",
    ),
    # Datasoft: the boot loader XORs its sector list (sector 17, which has two
    # physical copies on track 0) with sector 16, reads that list, then hands
    # off at $0680. The captured RAM has no other DSKINV call.
    Capture(
        "O'Riley's Mine",
        "f8e2c9cbfd5fa73ed911ce10ec0804778da72382460731e3fa958666e5d404e8",
        0x0680,
        "4ce9c722ec016c1c4d1225db8a6b47c9ad8cf27f2e43362df61e31d89426466e",
    ),
    # Broderbund: sector 1 loads an obfuscated chain from track 5 (IDs 2-9
    # each have two physical copies), checks track 39, loads the game and
    # hands off at $0800. The game then loads title data (sectors 109-176)
    # and 36-sector levels (173-712) itself through DSKINV, and writes high
    # scores to sector 676. Nothing above $4700 but the OS screen was set.
    Capture(
        "Whistler's Brother",
        "f5a22b57ca193615abbdc0a898a061e2fc293a8978d4301dab92d08bce407549",
        0x0800,
        "83be1d3b6356a17a3cf9cf540fa9e047acbb26a5793fa8855c955b88763de48d",
        end=0x4800,
        sectors=(109, 712),
    ),
    # Broderbund: the same protection sequence as Whistler's Brother, then
    # sectors 3-90 and 109-274 decrypted with a key the protection computes
    # in zero page, 275-392 plain, all into $0600-$BFFF. It hands off at
    # $3010 and never reads the disk again.
    Capture(
        "Drol",
        "98b58846d3277f89a26969023702c5f4190882dde2c3a7b60c74354987783662",
        0x3010,
        "f21328a1b87f528b03faee23bb3323a11086068f957097bc184d1ed71676d584",
        medium="ATR",
    ),
)
OS_REV2 = "a77050b2d81db2d11eaa3dbafd8ec2531b478abcc3bcc4b0d846b634e885edb1"


def find(disk: bytes) -> Capture | None:
    digest = sha256(disk).hexdigest()
    return next((s for s in CAPTURES if s.disk_sha256 == digest), None)


def capture_program(disk: bytes, os_rom: Path | None) -> tuple[bytes, int]:
    spec = find(disk)
    if spec is None:
        raise ValueError("No verified emulator hand-off for this disk revision.")
    if os_rom is None or not os_rom.is_file():
        raise ValueError(
            f"This {spec.medium} needs Atari800 and --os-rom pointing to your stock Atari XL/XE OS revision 2 ROM."
        )
    with os_rom.open("rb") as stream:
        rom = stream.read(16385)
    if sha256(rom).hexdigest() != OS_REV2:
        raise ValueError(
            "Unrecognized OS ROM: this recipe requires the 16 KiB stock Atari XL/XE OS revision 2."
        )
    emulator = shutil.which("atari800")
    if not emulator:
        raise ValueError(
            f"Install Atari800 (with the text monitor) to convert this {spec.medium}."
        )
    media = "disk." + spec.medium.lower()
    if spec.medium == "ATR":
        paragraphs = len(disk) // 16
        disk = (
            pack("<HHHH8x", 0x0296, paragraphs & 0xFFFF, 128, paragraphs >> 16) + disk
        )
    with tempfile.TemporaryDirectory(prefix="recarted-") as tmp:
        root = Path(tmp)
        source = root / media
        source.write_bytes(disk)
        source.chmod(0o444)
        (root / "xl.rom").write_bytes(rom)
        (root / "private.cfg").write_text("Atari 800 Emulator, Version 5.2.0\n")
        cmd = [
            emulator,
            "-config",
            "private.cfg",
            "-no-autosave-config",
            "-monitor",
            "-xl",
            "-ntsc",
            "-nobasic",
            "-nopatchall",
            "-xlxe_rom",
            "xl.rom",
            "-no-video-accel",
            "-nosound",
            "-turbo",
            media,
        ]
        # Every monitor command and filename is ours, not derived from a user path.
        commands = (
            f"bpc {spec.entry:04x}\ncont\nwrite {LOAD:x} {END - 1:x} game.bin\nquit\n"
        )
        env = {
            **os.environ,
            "HOME": tmp,
            "SDL_VIDEODRIVER": "dummy",
            "SDL_AUDIODRIVER": "dummy",
        }
        try:
            with (root / "monitor.log").open("w+b") as log:
                result = subprocess.run(
                    cmd,
                    cwd=tmp,
                    env=env,
                    input=commands.encode("ascii"),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=30,
                    check=False,
                )
                log.seek(0)
                transcript = log.read(65536).lower()
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                "Timed out waiting for the disk's loader. Use an Atari800 build with the text monitor (tested: 5.2.0)."
            ) from exc
        dump = root / "game.bin"
        if (
            result.returncode
            or f"(breakpoint at {spec.entry:04x})".encode() not in transcript
            or not dump.is_file()
            or dump.stat().st_size != END - LOAD
        ):
            raise ValueError(
                "Atari800 did not reach the verified hand-off. Check that it has the text monitor (tested: 5.2.0)."
            )
        body = dump.read_bytes()
    i = spec.entry - LOAD
    if sha256(body[i : i + 128]).hexdigest() != spec.code_sha256:
        raise ValueError(
            "Unexpected program at the hand-off; refusing to build a cartridge."
        )
    # Below the OS's own text screen, RAM past a trimmed capture must be empty.
    if any(body[spec.end - LOAD : OS_SCREEN - LOAD]):
        raise ValueError(
            "Unexpected data above the captured program; refusing to build a cartridge."
        )
    return body[: spec.end - LOAD], spec.entry
