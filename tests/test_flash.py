"""test_flash.py - the core's SST 39VF400A (the DUO's own flash) command set.

    python3 test_flash.py
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
import duocore

ROM = 0x08000000
A1, A2 = ROM + 0xAAAA, ROM + 0x5554          # word addresses 0x5555 and 0x2AAA


def new(fw=None):
    return duocore.Core(fw if fw is not None else bytes(range(256)) * 0x800, bytes(0x1000), "none", b"")


def seq(c, *pairs):
    flags = 0
    for a, v in pairs:
        r = c.write(a, 2, v)
        assert not r.failed, (hex(a), hex(v), r.msg)
        flags |= r.flags
    return flags


def rd(c, a, n=2):
    return c.render(a, n)


def test_id_mode():
    c = new()
    before = rd(c, ROM, 4)
    seq(c, (A1, 0xAAAA), (A2, 0x5555), (A1, 0x9090))
    assert rd(c, ROM, 4) == bytes([0xBF, 0xBF, 0x82, 0x27]) and c.flash_id_mode
    seq(c, (ROM + 0x1234, 0xF0F0))                 # exit: F0 at any address
    assert rd(c, ROM, 4) == before and not c.flash_id_mode
    seq(c, (A1, 0xAAAA), (A2, 0x5555), (A1, 0x9090), (A1, 0xAAAA), (A2, 0x5555), (A1, 0xF0F0))
    assert not c.flash_id_mode


def test_program_word_and_mirror():
    c = new(b"\xFF" * 0x80000)
    f = seq(c, (A1, 0xAAAA), (A2, 0x5555), (A1, 0xA0A0), (ROM + 0x30000, 0x1234))
    assert f & duocore.F_FLASH_CHANGED and f & duocore.F_ROM_CHANGED
    assert rd(c, ROM + 0x30000) == b"\x34\x12" and rd(c, ROM + 0xB0000) == b"\x34\x12"   # and its mirror
    seq(c, (A1, 0xAAAA), (A2, 0x5555), (A1, 0xA0A0), (ROM + 0x30000, 0xFF0F))
    assert rd(c, ROM + 0x30000) == b"\x04\x12"     # program only clears bits


def test_sector_block_chip_erase():
    c = new(b"\x00" * 0x80000)
    seq(c, (A1, 0xAA), (A2, 0x55), (A1, 0x80), (A1, 0xAA), (A2, 0x55), (ROM + 0x31234, 0x3030))
    assert rd(c, ROM + 0x31000, 0x1000) == b"\xFF" * 0x1000
    assert rd(c, ROM + 0x30FFE) == b"\0\0" and rd(c, ROM + 0x32000) == b"\0\0"          # just that 4 KB sector
    seq(c, (A1, 0xAA), (A2, 0x55), (A1, 0x80), (A1, 0xAA), (A2, 0x55), (ROM + 0x40000, 0x5050))
    assert rd(c, ROM + 0x40000, 0x10000) == b"\xFF" * 0x10000 and rd(c, ROM + 0x50000) == b"\0\0"
    seq(c, (A1, 0xAA), (A2, 0x55), (A1, 0x80), (A1, 0xAA), (A2, 0x55), (A1, 0x1010))
    assert rd(c, ROM, 0x20) == b"\xFF" * 0x20 and rd(c, ROM + 0xA0, 0x80000 - 0xA0) == b"\xFF" * (0x80000 - 0xA0)
    assert rd(c, ROM + 0x9C, 4) == bytes([0xF0, 0x0F, 0, 0])      # the Actel's overlay stays on top
    assert c.lib.duo_flash_erases(c.h) == 3


def test_stray_writes_still_fail():
    c = new()
    assert c.write(ROM + 0x1234, 2, 0x5678).failed                 # nothing to do with the flash
    assert c.write(A2, 2, 0x5555).failed                           # an unlock out of order
    assert c.write(ROM + 0x200000, 2, 0xAAAA).failed               # above the flash's mirror
    c.write(0x0800009C, 2, 0x0101)                                 # the game mapped: no flash at all
    assert c.write(A1, 2, 0xAAAA).failed


if __name__ == "__main__":
    n = 0
    for name, f in sorted(globals().items()):
        if name.startswith("test_") and callable(f):
            f(); n += 1
            print("PASS", name)
    print(f"{n} flash tests passed")
