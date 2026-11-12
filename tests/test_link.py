"""test_link.py - the core's USB link against Datel's own handshake.

    python3 test_link.py

RECV8 and SEND8 below are line-for-line transcriptions of Datel's routines at 0x0800C1FC and
0x0800C29C (firmware 1.06), including the RAM copy of LINK_OUT at 0x0300212C. They spin with a
limit, so a hang shows up as an exception rather than a stuck test.
"""
import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
import duocore

LINK_IN, LINK_OUT = duocore.LINK_IN, duocore.LINK_OUT


class Hang(Exception):
    pass


class GBA:
    def __init__(self, core):
        self.core = core
        self.shadow = 0                       # Datel's copy of LINK_OUT (0x0300212C)

    def rd(self):
        v, r = self.core.read(LINK_IN, 2)
        assert not r.failed and not r.flags & duocore.F_BAD, r.msg
        return v

    def wr(self, v):
        r = self.core.write(LINK_OUT, 2, v)
        assert not r.failed, r.msg
        return r.flags

    def wait(self, bit, spins=1000):
        for _ in range(spins):
            if (self.rd() >> 8 & 1) == bit:
                return
        raise Hang(f"waited for the USB chip's strobe to read {bit}")

    def avail(self):                           # 0x0800C1DC
        return self.rd() >> 8 & 1

    def recv8(self):                           # 0x0800C1FC
        out = bytearray()
        for _ in range(4):
            self.wait(1)
            out.append(self.rd() & 0xFF)
            self.shadow |= 0x100
            self.wr(self.shadow)
            self.wait(0)
            out.append(self.rd() & 0xFF)
            self.shadow &= 0xFEFF
            self.wr(self.shadow)
        return bytes(out)

    def send8(self, pkt):                      # 0x0800C29C
        flags = 0
        for i in range(4):
            self.wait(1)
            self.shadow = (self.shadow & 0xFF00) | pkt[2 * i] | 0x100
            flags |= self.wr(self.shadow)
            self.wait(0)
            self.shadow = ((self.shadow & 0xFF00) | pkt[2 * i + 1]) & 0xFEFF
            flags |= self.wr(self.shadow)
        return flags


def new():
    return duocore.Core(bytes(0x1000), bytes(0x1000), "sanyo", b"")


def test_exchange():
    c = new(); g = GBA(c)
    assert c.turn == "pc" and g.avail() == 0 and not c.usb_pending
    st, r = c.usb_from_pc(b"CBW\x01\x02\x03\x04\x05")
    assert st == duocore.OK and c.turn == "gba" and c.usb_pending and g.avail() == 1
    assert g.recv8() == b"CBW\x01\x02\x03\x04\x05"
    assert c.usb_take() is None                       # nothing from the GBA yet
    flags = g.send8(b"SBW\x10ABCD")
    assert flags & duocore.F_USB_SENT and c.turn == "pc"
    assert c.usb_take() == b"SBW\x10ABCD" and c.usb_take() is None
    assert g.avail() == 0


def test_many_exchanges_every_byte():
    c = new(); g = GBA(c)
    for n in range(300):
        pc = bytes((n + 7 * i) & 0xFF for i in range(8))
        gb = bytes((255 - n - 3 * i) & 0xFF for i in range(8))
        assert c.usb_from_pc(pc)[0] == duocore.OK
        assert g.recv8() == pc
        assert g.send8(gb) & duocore.F_USB_SENT
        assert c.usb_take() == gb


def test_pc_twice_in_a_row():
    c = new(); g = GBA(c)
    assert c.usb_from_pc(b"first...")[0] == duocore.OK
    st, r = c.usb_from_pc(b"second..")
    assert st == duocore.FAIL and "PC sent two packets in a row" in r.msg
    assert g.recv8() == b"first..."                   # the first is still intact


def test_gba_twice_in_a_row_hangs():
    """v3's back-to-back stall: a second GBA packet waits for an invitation that never comes."""
    c = new(); g = GBA(c)
    c.usb_from_pc(b"hello...")
    g.recv8()
    g.send8(b"reply 1.")
    try:
        g.send8(b"reply 2.")
        raise AssertionError("a second GBA packet in a row went through")
    except Hang:
        pass
    assert c.usb_take() == b"reply 1."


def test_hello_held_with_gba_off():
    """The chip is USB-powered: a PC packet written while the GBA is off waits for start-up."""
    c = new()
    c.usb_from_pc(b"CBW\x00helo")                      # nothing on the GBA side runs meanwhile
    g = GBA(c)                                        # the GBA powers on: Datel's RAM copy is 0
    g.wr(0)                                           # start-up writes LINK_OUT (0x0800BB54 and friends)
    assert g.avail() == 1 and g.recv8() == b"CBW\x00helo"


def test_restarts_into_server_mode():
    """13 of 13 in the lab: a hello waiting at the reset is always seen by Datel's start-up."""
    c = new()
    for i in range(13):
        g = GBA(c)                                    # each soft reset starts with Datel's copy at 0
        g.wr(0)
        c.usb_from_pc(b"CBW\x00" + bytes([i]) * 4)
        assert g.avail() == 1, i                      # 0x080073F4: AVAIL, then RECV8
        assert g.recv8()[4] == i
        g.send8(b"SBW\x00ok!!")
        assert c.usb_take() == b"SBW\x00ok!!"


def test_strobe_bits_only():
    """Writes to LINK_OUT's other bits (Datel's control lines 10-12) don't move the handshake."""
    c = new(); g = GBA(c)
    c.usb_from_pc(b"abcdefgh")
    for bit in (0x400, 0x800, 0x1000):
        g.shadow |= bit; g.wr(g.shadow)
    assert g.recv8() == b"abcdefgh"
    for bit in (0x400, 0x800, 0x1000):
        g.shadow &= ~bit; g.wr(g.shadow)
    assert g.send8(b"12345678") & duocore.F_USB_SENT and c.usb_take() == b"12345678"


def test_mapped_game_hides_the_link():
    c = new(); g = GBA(c)
    c.usb_from_pc(b"abcdefgh")
    c.write(0x0800009C, 2, 0x0101)                     # the game swaps in
    _, r = c.read(LINK_IN, 2)
    assert r.flags & duocore.F_BAD and "while the game was mapped" in r.msg
    r = c.write(LINK_OUT, 2, 0x100)
    assert r.failed                                    # an unexpected write to the game's ROM
    c.write(0x0800009C, 2, 0x0120)                     # back to the DUO: the packet is still there
    assert g.avail() == 1 and g.recv8() == b"abcdefgh"


def test_render_matches_read():
    c = new(); g = GBA(c)
    c.usb_from_pc(b"\x5a\xa5zzzzzz")
    v, _ = c.read(LINK_IN, 2)
    assert c.render(LINK_IN, 2) == v.to_bytes(2, "little") and v == 0x15A


if __name__ == "__main__":
    n = 0
    for name, f in sorted(globals().items()):
        if name.startswith("test_") and callable(f):
            f(); n += 1
            print("PASS", name)
    print(f"{n} link tests passed ({duocore.version()})")
