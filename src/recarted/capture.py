"""Let a known disk's own loader run in Atari800. Never execute unknown ATX images."""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class Capture:
    title: str
    disk_sha256: str
    entry: int
    code_sha256: str  # 128 bytes of loaded code at the hand-off


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
)
OS_REV2 = "a77050b2d81db2d11eaa3dbafd8ec2531b478abcc3bcc4b0d846b634e885edb1"
LOAD = 0x0400
END = 0xC000


def capture_program(disk: bytes, os_rom: Path | None) -> tuple[bytes, int]:
    digest = sha256(disk).hexdigest()
    spec = next((s for s in CAPTURES if s.disk_sha256 == digest), None)
    if spec is None:
        raise ValueError("No verified emulator hand-off for this ATX revision.")
    if os_rom is None or not os_rom.is_file():
        raise ValueError(
            "This ATX needs Atari800 and --os-rom pointing to your stock Atari XL/XE OS revision 2 ROM."
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
            "Install Atari800 (with the text monitor) to convert this ATX."
        )
    with tempfile.TemporaryDirectory(prefix="recarted-") as tmp:
        root = Path(tmp)
        source = root / "disk.atx"
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
            "disk.atx",
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
                "Timed out waiting for the ATX loader. Use an Atari800 build with the text monitor (tested: 5.2.0)."
            ) from exc
        dump = root / "game.bin"
        if (
            result.returncode
            or f"(breakpoint at {spec.entry:04x})".encode() not in transcript
            or not dump.is_file()
            or dump.stat().st_size != END - LOAD
        ):
            raise ValueError(
                "Atari800 did not reach the verified ATX hand-off. Check that it has the text monitor (tested: 5.2.0)."
            )
        body = dump.read_bytes()
    i = spec.entry - LOAD
    if sha256(body[i : i + 128]).hexdigest() != spec.code_sha256:
        raise ValueError(
            "Unexpected program at the ATX hand-off; refusing to build a cartridge."
        )
    return body, spec.entry
