"""Synthetic media only; never depend on a game image or an OS ROM in CI."""

import subprocess
from hashlib import sha256
from pathlib import Path
from struct import pack_into

import pytest

from recarted import atx, capture
from recarted.convert import convert_image
from recarted.example import SECTOR, example_image
from recarted.images import identify


@pytest.mark.parametrize(
    "offset,value,fmt",
    [
        (28, 2, "I"),
        (32, 4000, "I"),
        (48, 0, "I"),
        (48 + 20, 0, "I"),
        (48 + 10, 17, "H"),
        (80, 0xFFFFFFFF, "I"),
        (80 + 8 + 4, 48, "I"),
        (80 + 8 + 4, 2504, "I"),
    ],
)
def test_reject_bad_bounds(offset, value, fmt):
    image = bytearray(example_image("atx"))
    pack_into("<" + fmt, image, offset, value)
    with pytest.raises(ValueError, match="ATX"):
        identify(image)


def test_no_silent_flattening():
    b = bytearray(example_image("atx"))
    b[88] = 2
    b[89] = 0x28
    image = identify(b)
    assert image.recipe is None
    assert "1 duplicate IDs" in image.detail and "1 flagged records" in image.detail
    with pytest.raises(ValueError, match="No conversion recipe"):
        convert_image(image)
    with pytest.raises(ValueError, match="losslessly"):
        atx.linear_sd_disk(b, 1)


def test_physical_order_not_logical_order():
    b = bytearray(example_image("atx"))
    b[88:104] = b[96:104] + b[88:96]
    assert atx.linear_sd_disk(b, 1)[:128] == SECTOR
    assert (
        identify(b).recipe is None
    )  # full-image fingerprint, not a filename or normalized digest


def test_example_workflow(tmp_path):
    def cli(*args):
        return subprocess.run(
            ["recarted", *args],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )

    assert cli("example", "demo.atx").returncode == 0
    assert cli("convert", "demo.atx").returncode == 0
    assert "Type 41" in cli("inspect", "demo.car").stdout
    b = bytearray((tmp_path / "demo.atx").read_bytes())
    b[-9] ^= 1
    (tmp_path / "unknown.atx").write_bytes(b)
    r = cli("convert", "unknown.atx")
    assert (
        r.returncode
        and "No conversion recipe" in r.stderr
        and not (tmp_path / "unknown.car").exists()
    )


@pytest.fixture
def synthetic_capture(monkeypatch, tmp_path):
    disk = example_image("atx")
    body = b"\xaa" * (capture.END - capture.LOAD)
    entry = 0x1400
    spec = capture.Capture(
        "synthetic", sha256(disk).hexdigest(), entry, sha256(body[:128]).hexdigest()
    )
    monkeypatch.setattr(capture, "CAPTURES", (spec,))
    rom = tmp_path / "OS with spaces.rom"
    rom.write_bytes(b"X" * 16384)
    monkeypatch.setattr(capture, "OS_REV2", sha256(rom.read_bytes()).hexdigest())
    monkeypatch.setattr(capture.shutil, "which", lambda name: "/fake/atari800")
    return disk, rom, body, entry


@pytest.mark.parametrize(
    "fault",
    ["ok", "missing-break", "short-dump", "wrong-code", "timeout", "emulator-error"],
)
def test_monitor_protocol(monkeypatch, synthetic_capture, fault):
    disk, rom, body, entry = synthetic_capture
    directories = []

    def monitor(cmd, *, cwd, env, input, stdout, stderr, timeout, check):
        root = Path(cwd)
        directories.append(root)
        assert (
            root != rom.parent
            and (root / "disk.atx").read_bytes() == disk
            and env["SDL_VIDEODRIVER"] == "dummy"
        )
        assert (
            (root / "private.cfg").exists()
            and cmd[-1] == "disk.atx"
            and b"bpc 1400" in input
        )
        if fault == "timeout":
            raise subprocess.TimeoutExpired(cmd, timeout)
        if fault != "missing-break":
            stdout.write(b"(breakpoint at 1400)\n")
        (root / "game.bin").write_bytes(
            b""
            if fault == "short-dump"
            else bytes(len(body))
            if fault == "wrong-code"
            else body
        )
        return subprocess.CompletedProcess(cmd, int(fault == "emulator-error"))

    monkeypatch.setattr(subprocess, "run", monitor)
    if fault == "ok":
        assert capture.capture_program(disk, rom) == (body, entry)
    else:
        with pytest.raises(ValueError):
            capture.capture_program(disk, rom)
    assert directories and not directories[0].exists()


def test_capture_prerequisites(monkeypatch, synthetic_capture):
    disk, rom, _, _ = synthetic_capture
    with pytest.raises(ValueError, match="hand-off"):
        capture.capture_program(b"other revision", rom)
    with pytest.raises(ValueError, match="--os-rom"):
        capture.capture_program(disk, None)
    monkeypatch.setattr(capture.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="Install Atari800"):
        capture.capture_program(disk, rom)
    rom.write_bytes(bytes(16384))
    with pytest.raises(ValueError, match="Unrecognized OS"):
        capture.capture_program(disk, rom)
