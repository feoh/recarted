"""Synthetic media only; never depend on a game image or an OS ROM in CI."""

import subprocess
from hashlib import sha256
from pathlib import Path
from struct import pack, pack_into

import pytest

from recarted import atx, capture, convert, images
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


def atx_tracks(layout):
    """(track number, sector IDs) in physical order; each record holds its own tag."""
    body = b""
    for copy, (number, ids) in enumerate(layout):
        list_len = 8 + 8 * len(ids)
        listing = pack("<IB3x", list_len, 1) + b"".join(
            pack("<BBHI", sid, 0, 0, 32 + list_len + 8 + i * 128)
            for i, sid in enumerate(ids)
        )
        data = b"".join(bytes([number, sid, copy]) * 42 + b"\0\0" for sid in ids)
        chunks = listing + pack("<IB3x", 8 + len(data), 0) + data + bytes(8)
        track = bytearray(32)
        pack_into("<I", track, 0, 32 + len(chunks))
        track[8] = number
        pack_into("<H", track, 10, len(ids))
        pack_into("<I", track, 20, 32)
        body += track + chunks
    header = bytearray(48)
    header[:8] = pack("<4sHH", b"AT8X", 1, 1)
    pack_into("<II", header, 28, 48, 48 + len(body))
    return bytes(header + body)


def test_sector_window_skips_only_tracks_outside_it():
    clean = list(range(18, 0, -1))
    protected = [2, 8, 7, 4, 3, 9, 8, 5, 4, 1, 9, 6, 5, 2, 10, 7, 6, 3]
    image = atx_tracks([(0, clean), (1, protected), (2, clean), (3, clean)])
    window = atx.sd_sector_window(image, 38, 70)
    assert [tuple(window[i : i + 2]) for i in range(0, len(window), 128)] == [
        ((s - 1) // 18, (s - 1) % 18 + 1) for s in range(38, 71)
    ]
    with pytest.raises(ValueError, match="losslessly"):
        atx.sd_sector_window(image, 30, 40)  # reaches the duplicated track
    with pytest.raises(ValueError, match="Incomplete"):
        atx.sd_sector_window(image, 60, 80)  # track 4 is absent
    with pytest.raises(ValueError, match="losslessly"):
        atx.sd_sector_window(atx_tracks([(2, clean), (2, clean)]), 37, 40)
    with pytest.raises(ValueError, match="geometry"):
        atx.sd_sector_window(atx_tracks([(2, clean[:17])]), 37, 40)


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


@pytest.mark.parametrize("stray", [None, 0x1800, 0xBBFF, 0xBC20])
def test_trimmed_capture(monkeypatch, synthetic_capture, stray):
    disk, rom, body, entry = synthetic_capture
    spec = capture.CAPTURES[0]
    trimmed = capture.Capture(
        spec.title, spec.disk_sha256, entry, spec.code_sha256, end=0x1800
    )
    monkeypatch.setattr(capture, "CAPTURES", (trimmed,))
    dump = bytearray(body)
    dump[0x1800 - capture.LOAD :] = bytes(capture.END - 0x1800)
    if stray is not None:
        dump[stray - capture.LOAD] = 1

    def monitor(cmd, *, cwd, env, input, stdout, stderr, timeout, check):
        stdout.write(b"(breakpoint at 1400)\n")
        (Path(cwd) / "game.bin").write_bytes(dump)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", monitor)
    if stray in (0x1800, 0xBBFF):
        with pytest.raises(ValueError, match="above the captured program"):
            capture.capture_program(disk, rom)
    else:  # the OS's own text screen may differ; it is not stored
        assert capture.capture_program(disk, rom) == (
            bytes(dump[: 0x1800 - capture.LOAD]),
            entry,
        )


def test_capture_with_sector_window(monkeypatch):
    clean = list(range(1, 19))
    disk = atx_tracks([(0, [1, 1, 2]), (1, clean), (2, clean)])
    spec = capture.Capture(
        "synthetic", sha256(disk).hexdigest(), 0x0800, "", end=0x4800, sectors=(19, 54)
    )
    monkeypatch.setattr(capture, "CAPTURES", (spec,))
    recipe = images.Recipe("synthetic", "ATX", "capture-disk", spec.disk_sha256)
    monkeypatch.setattr(images, "RECIPES", (recipe,))
    ram = bytes(range(256)) * 0x44
    monkeypatch.setattr(convert, "capture_program", lambda d, rom: (ram, 0x0800))
    image = identify(disk)
    assert image.recipe and image.recipe.loader == "capture-disk"
    with pytest.raises(ValueError, match=r"\.car"):
        convert_image(image, "xex")
    car = convert_image(image)[16:]
    assert car[0x1F00:0x1F09] == pack("<BBHBHH", 4, 0x44, 0x0800, 4, 19, 36)
    assert car[8192 : 8192 + len(ram)] == ram
    assert car[4 * 8192 : 4 * 8192 + 36 * 128] == atx.sd_sector_window(disk, 19, 54)
