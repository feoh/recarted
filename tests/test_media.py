import subprocess
from struct import pack, unpack

import pytest

from recarted.convert import convert_image, save_new
from recarted.example import SECTOR, example_image
from recarted.images import MAX_INPUT, identify, read_input


@pytest.mark.parametrize("kind", ["cas", "atr", "atx"])
def test_end_to_end(kind):
    image = identify(example_image(kind))
    assert image.recipe.name == "ReCarted! colour bars"
    car = convert_image(image)
    assert identify(car).mapper == 41
    assert unpack(">4sIII", car[:16]) == (b"CART", 41, sum(car[16:]), 0)
    assert len(car) == 131088
    assert car[16 + 8192 : 16 + 8192 + 128] == SECTOR
    xex = convert_image(image, "xex")
    assert xex.startswith(bytes.fromhex("ffff 0020 7f20") + SECTOR)
    assert xex.endswith(bytes.fromhex("e002 e102 0620"))


def test_unknown_release_is_not_converted():
    mutated = example_image("atr")[:-1] + b"!"
    img = identify(mutated)
    assert img.recipe is None
    with pytest.raises(ValueError, match="No conversion recipe"):
        convert_image(img)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"PK\x03\x04",
        b"CART",
        b"\x96\x02",
        example_image("atr")[:-1],
        b"FUJI",
        example_image("cas")[:-1],
    ],
)
def test_damaged(data):
    with pytest.raises(ValueError):
        identify(data)


def test_tape_validation_and_multiple_stages():
    tape = bytearray(example_image("cas"))
    tape[30] ^= 1
    with pytest.raises(ValueError, match="checksum"):
        identify(tape)
    tape = example_image("cas")
    with pytest.raises(ValueError, match="EOF"):
        identify(tape[:-140])
    assert identify(tape + tape[16:]).recipe is None
    assert identify(tape + b"fsk " + bytes(4)).recipe is None
    # Gap and tape description are metadata, not program bytes.
    assert identify(b"FUJI\x03\0\0\0abc" + tape[8:]).recipe == identify(tape).recipe
    assert identify(tape[:22] + b"\x42\x42" + tape[24:]).recipe == identify(tape).recipe
    assert (
        identify(tape[:-140] + tape[16:156] + tape[-140:]).recipe
        == identify(tape).recipe
    )


def test_other_formats():
    with pytest.raises(ValueError, match="ATX version"):
        identify(b"AT8X" + bytes(44))
    rom = bytes(1048576)
    assert "Unsupported" in identify(pack(">4sIII", b"CART", 42, 0, 0) + rom).detail
    with pytest.raises(ValueError, match="needs"):
        identify(pack(">4sIII", b"CART", 41, 0, 0) + rom)
    with pytest.raises(ValueError, match="checksum"):
        identify(pack(">4sIII", b"CART", 42, 1, 0) + rom)


def test_double_density():
    payload = bytes(3 * 128 + 256)
    data = pack("<HHH", 0x296, len(payload) // 16, 256) + bytes(10) + payload
    assert "4 sectors" in identify(data).detail and identify(data).recipe is None


def test_refuses_to_clobber_and_bounds_input(tmp_path):
    dest = tmp_path / "game.car"
    save_new(dest, b"keep me")
    with pytest.raises(ValueError, match="overwrite"):
        save_new(dest, b"new")
    assert dest.read_bytes() == b"keep me"
    with dest.open("wb") as stream:
        stream.truncate(MAX_INPUT + 1)
    with pytest.raises(ValueError, match="limit"):
        read_input(dest)


def test_cli(tmp_path):
    def cli(*args):
        return subprocess.run(
            ["recarted", *args],
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
        )

    assert cli("example", "demo.cas").returncode == 0
    tape = tmp_path / "demo.cas"
    tape.rename(tmp_path / "not-a-tape.img")
    assert "Matched:" in cli("inspect", "not-a-tape.img").stdout
    assert cli("convert", "not-a-tape.img", "--output", "game.car").returncode == 0
    assert "Type 41" in cli("inspect", "game.car").stdout
    error = cli("convert", "not-a-tape.img", "--output", "game.car")
    assert error.returncode != 0 and "overwrite" in error.stderr
    tape.write_bytes(b"broken input")
    assert (
        cli("convert", "demo.cas").returncode != 0
        and not (tmp_path / "demo.car").exists()
    )
