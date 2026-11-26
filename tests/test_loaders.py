"""Execute the released machine code; do not just assert on host-side headers."""

from struct import pack

import pytest
from py65.devices.mpu6502 import MPU

from recarted.convert import convert_image, hybrid_car
from recarted.images import Image, Recipe


class Bus:
    def __init__(self, rom):
        self.ram = bytearray(65536)
        self.rom = rom
        self.os = bytes(range(256)) * 64
        self.bank = 0
        self.ram[0xD301] = 0xFF

    def __getitem__(self, addr):
        if 0xA000 <= addr < 0xC000 and self.bank is not None:
            return self.rom[8192 * self.bank + addr - 0xA000]
        if (0xC000 <= addr < 0xD000 or addr >= 0xD800) and self.ram[0xD301] & 1:
            return self.os[addr - 0xC000]
        return self.ram[addr]

    def __setitem__(self, addr, val):
        if 0xD500 <= addr < 0xD520:
            self.bank = (addr & 15) if addr < 0xD510 else None
        elif 0xA000 <= addr < 0xC000 and self.bank is not None:
            pass
        else:
            self.ram[addr] = val


def until(cpu, target, limit=250_000):
    for _ in range(limit):
        if cpu.pc == target:
            return
        cpu.step()
    pytest.fail(f"6502 stopped at {cpu.pc:04x}, expected {target:04x}")


def machine(mode, payload):
    image = Image("fixture", "", payload, Recipe("synthetic", "fixture", mode, ""))
    bus = Bus(convert_image(image)[16:])
    return bus, MPU(memory=bus, pc=0xA000)


def request(bus, cpu, sector, command=0x52):
    """Call DSKINV the way a program does and return the status in Y."""
    bus.ram[0x302] = command
    bus.ram[0x304:0x306] = pack("<H", 0xAFF3)
    bus.ram[0x30A:0x30C] = pack("<H", sector)
    cpu.pc = 0xE453
    cpu.stPushWord(0x1FFF)
    until(cpu, 0x2000)
    return cpu.y


def test_memory_copy_across_bank_and_under_cart():
    payload = bytearray((i * 13 + i // 8192) & 255 for i in range(9000))
    payload[:6] = pack("<BBHH", 0, 71, 0x9783, 0xA234)
    bus, cpu = machine("tape", bytes(payload))
    until(cpu, 0x9789)
    assert bus.bank is None
    assert bus.ram[0x9783 : 0x9783 + len(payload)] == payload
    assert bus.ram[12:14] == b"\x34\xa2" and bus.ram[9] == 2


def test_disk_sector_reader():
    disk = bytearray((i // 128 + i // 8192 + i % 128) & 255 for i in range(720 * 128))
    disk[:6] = pack("<BBHH", 0, 3, 0x780, 0x780)
    bus, cpu = machine("disk", bytes(disk))
    until(cpu, 0x786)
    assert bus.bank is None and bus.ram[0x780:0x900] == disk[:384]
    assert bus.ram[0xC100:0xC200] == bus.os[0x100:0x200]

    for sector in (1, 64, 65, 256, 257, 512, 720):
        assert request(bus, cpu, sector) == 1 and bus.bank is None
        assert bus.ram[0xAFF3 : 0xAFF3 + 128] == disk[(sector - 1) * 128 : sector * 128]
    before = bus.ram[0xAFF3 : 0xAFF3 + 128]
    assert all(request(bus, cpu, s) > 127 for s in (0, 721, 65535))
    assert request(bus, cpu, 1, 0x57) > 127 and bus.ram[0xAFF3 : 0xAFF3 + 128] == before


def test_hybrid_capture_with_sector_window():
    # Same shape as the Whistler's Brother recipe: $0400-$47FF, then 604
    # sectors from 109 starting part-way through a bank's worth of pages.
    ram = bytes((i * 7 + i // 256) & 255 for i in range(0x4400))
    first, count = 109, 604
    window = bytes((i // 128 * 3 + i % 128) & 255 for i in range(count * 128))
    bus = Bus(hybrid_car(0x400, ram, 0x0800, first, window)[16:])
    bus.ram[0x4800:0xC000] = b"\x55" * (0xC000 - 0x4800)
    cpu = MPU(memory=bus, pc=0xA000)
    until(cpu, 0x0800, limit=1_000_000)
    assert bus.bank is None and bus.ram[0x400:0x4800] == ram
    assert not any(bus.ram[0x4800:0xC000])  # zero above the capture, as captured
    assert bus.ram[0xC100:0xC200] == bus.os[0x100:0x200]
    assert bus.ram[0x300:0x302] == b"\x31\x01" and bus.ram[0x6A] == 0xC0
    for sector in (109, 172, 173, 236, 237, 300, 712):
        assert request(bus, cpu, sector) == 1 and bus.bank is None
        i = (sector - first) * 128
        assert bus.ram[0xAFF3 : 0xAFF3 + 128] == window[i : i + 128]
    before = bus.ram[0xAFF3 : 0xAFF3 + 128]
    assert all(request(bus, cpu, s) > 127 for s in (0, 1, 108, 713, 720, 65535))
    assert (
        request(bus, cpu, 676, 0x57) > 127 and bus.ram[0xAFF3 : 0xAFF3 + 128] == before
    )


@pytest.mark.parametrize(
    "load,ram,sectors",
    [
        (0x401, b"x", bytes(128)),
        (0x400, b"", bytes(128)),
        (0x400, bytes(0xBD00), bytes(128)),
        (0x400, b"x", bytes(100)),
        (0x400, bytes(0x8000), bytes(720 * 128)),  # 4+1 RAM banks + 11.25 disk
    ],
)
def test_hybrid_layout_limits(load, ram, sectors):
    with pytest.raises(ValueError):
        hybrid_car(load, ram, 0x800, 1, sectors)
