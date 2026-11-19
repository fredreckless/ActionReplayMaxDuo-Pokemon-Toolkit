"""A GBA with no cartridge in, switched on, waiting in its BIOS for a multiboot program over the link
cable (docs/MULTIBOOT.md), as player 1 of a MultiPlay link at 115 kbit/s; and the master's BIOS
transfer (SWI 25h) that hwsim runs for the DUO when its program calls MultiBoot.

Where each part comes from - and how sure it is:
  - The master's handshake is the DUO's program (firmware/programs/mbsend.c), pret's multiboot.c,
    so what this model answers is checked against Nintendo's own library word for word. As on the
    cable, the slave's word in a transfer is the one it loaded after the transfer before: GBATEK's
    rows ("610y 720x", then header words seeing 60 0x down to 01 0x, "6200 000x") read that way, and
    the library's checks (MultiBootMain's default case) agree.
  - The BIOS's own part on both sides (the length, the main block, the CRC exchange) follows
    GBATEK's "BIOS Multi Boot" table and pseudo-code. Two details GBATEK leaves open are fixed here
    the same way on both sides: the byte order of dword(pp,cc,cc,cc) and dword(hh,rr,rr,rr) (taken
    lowest byte first) and which half of a 32-bit unit goes first in MultiPlay (the lower). On
    hardware both ends run the real BIOS, so these choices never reach the cable from our code.
  - The last handshake (MultiBootHandShake, probe_count 0xE0-0xE8) is answered by the received
    program, not the BIOS (GBATEK: "not part of the BIOS"). The answers here are the only ones the
    master's checks accept: each word echoed one transfer later, then the program's own game code
    (header bytes 0xAC-0xAF) in two halves after 0x0001, 0x0000.

`result` says what arrived: the header, the program, whether the CRC matched, and the game code.
"""
import random

C_INIT, X_KEY, K_KEY = 0xFFF8, 0xA517, 0x6465646F      # GBATEK: MultiPlay c, x, k
M_MUL = 0x6F646573


def crc_step(c, data, x=X_KEY):
    """GBATEK: c = c xor data, then 32 times: carry = c and 1, c = c shr 1, if carry: c = c xor x."""
    c ^= data
    for _ in range(32):
        carry = c & 1
        c >>= 1
        if carry:
            c ^= x
    return c


def encode(body, pp, cc, hh, rr):
    """The BIOS master's main block (GBATEK pseudo-code): [(half-word, ...)], and its final CRC.
    body: the bytes after the 0xC0-byte header, a multiple of 16; cc and rr: 3 bytes each."""
    c = C_INIT
    m = pp | cc[0] << 8 | cc[1] << 16 | cc[2] << 24
    f = hh | rr[0] << 8 | rr[1] << 16 | rr[2] << 24
    halves = []
    for off in range(0, len(body), 4):
        ptr = 0xC0 + off
        data = int.from_bytes(body[off:off + 4], "little")
        c = crc_step(c, data)
        m = (M_MUL * m + 1) & 0xFFFFFFFF
        enc = data ^ ((-0x2000000 - ptr) & 0xFFFFFFFF) ^ m ^ K_KEY
        halves += [enc & 0xFFFF, enc >> 16]
    c = crc_step(c, f)
    return halves, c & 0xFFFF


class MultibootSlave:
    """Player 1, waiting in the BIOS: a generator for hwsim's attach_mp_game (game_master=False)."""
    def __init__(self, seed=1, on_after=30, boot_transfers=4, slot=1, refuse_header=False):
        self.rng = random.Random(seed)
        self.on_after = on_after                  # transfers before it's in MultiPlay mode (FFFF until then)
        self.boot_transfers = boot_transfers      # transfers its new program takes to start answering
        self.bit = 1 << slot
        self.refuse_header = refuse_header
        self.cc = self.rng.randrange(256)
        self.rr = self.rng.randrange(256)
        self.cc_sent = False
        self.result = dict(header=None, program=None, crc_ok=None, game_code=None, booted=False,
                           handshake_done=False, pp=None, hh=None, hh_ok=None, log=[])

    def run(self):
        reply, n = 0xFFFF, 0
        r = self.result
        header, phase, hdr_n, length, halves, crc, k, boot_n = bytearray(), "info", 0, 0, [], None, 0, 0
        prev, after = None, []
        while True:
            words = yield ("mp_slave", reply, 10 ** 9)
            if words is None:
                continue
            w = words[0]
            n += 1
            if n < self.on_after:
                reply = 0xFFFF
                continue
            if n == self.on_after:
                reply = 0x0000                    # in MultiPlay mode now
                continue
            if phase == "info":
                hi = w >> 8
                if hi == 0x62:
                    reply = 0x7200 | self.bit
                elif hi == 0x61:                  # 610y: the first header word will see 60 0x
                    reply, phase, hdr_n = 0x6000 | self.bit, "header", 0
                elif hi == 0x63:                  # 63pp: 73cc the first time, then 73uu (GBATEK's rows;
                    r["pp"] = w & 0xFF            # each word is seen by the master one transfer later)
                    reply = 0x7300 | (self.rng.randrange(256) if self.cc_sent else self.cc)
                    self.cc_sent = True
                elif hi == 0x64:                  # 64hh: 73rr, the random byte for the encryption
                    r["hh"] = w & 0xFF
                    r["hh_ok"] = r["hh"] == (0x11 + self.cc + 0xFF + 0xFF) & 0xFF
                    reply, phase = 0x7300 | self.rr, "length"
                else:
                    reply = 0x7200 | self.bit
            elif phase == "header":
                header += w.to_bytes(2, "little")
                hdr_n += 1
                reply = ((0x60 - hdr_n) << 8 | self.bit) if not self.refuse_header else 0x7200 | self.bit
                if hdr_n == 0x60:                 # (the 6200 that ends the header sees 000x)
                    phase = "header_end"
                    r["header"] = bytes(header)
            elif phase == "header_end":           # then 620y -> 720x as before
                reply, phase = 0x7200 | self.bit, "info"
            elif phase == "length":               # the BIOS: llll (the master saw 73rr in that transfer)
                length = ((w + 0x34) * 4) & 0xFFFFFFFF
                reply, phase, halves = 0x00C0, "data", []
            elif phase == "data":
                halves.append(w)
                reply = (0xC0 + 2 * len(halves)) & 0xFFFF
                if len(halves) == length // 2:
                    phase, k = "crc_wait", 0
            elif phase == "crc_wait":
                if w == 0x0065:
                    k += 1
                    reply = 0x0074 if k < 2 else 0x0075
                elif w == 0x0066:                 # 0066 -> its own CRC, ready for the exchange
                    body, crc = self._decode(halves, length)
                    r["program"] = body
                    reply, phase = crc, "crc"
            elif phase == "crc":                  # zzzz <-> zzzz: the same on both sides, or no boot
                r["crc_ok"] = w == crc
                reply, phase, boot_n = 0xFFFF, "booting", 0
            elif phase == "booting":              # the program starts (if the CRC matched)
                boot_n += 1
                reply = 0xFFFF
                if boot_n >= self.boot_transfers and r["crc_ok"]:
                    r["booted"], phase, reply, prev = True, "client", 0x0000, None
            elif phase == "client":               # the received program's own handshake (see above)
                gc = r["header"][0xAC:0xB0]
                after = (after + [w])[-2:]
                if prev == "gc_lo":
                    reply, prev = int.from_bytes(gc[2:4], "little"), "gc_hi"
                elif prev == "gc_hi":
                    r["handshake_done"], r["game_code"] = True, bytes(gc)
                    reply = 0x0000
                elif after == [0x0001, 0x0000]:
                    reply, prev = int.from_bytes(gc[0:2], "little"), "gc_lo"
                else:
                    reply = w

    def _decode(self, halves, length):
        """The slave's side of GBATEK's pseudo-code: the program as it lands at 0x020000C0, and its CRC."""
        r = self.result
        m = r["pp"] | self.cc << 8 | 0xFF << 16 | 0xFF << 24
        f = r["hh"] | self.rr << 8 | 0xFF << 16 | 0xFF << 24
        c, out = C_INIT, bytearray()
        for i in range(0, len(halves) - 1, 2):
            ptr = 0xC0 + 2 * i
            enc = halves[i] | halves[i + 1] << 16
            m = (M_MUL * m + 1) & 0xFFFFFFFF
            data = enc ^ ((-0x2000000 - ptr) & 0xFFFFFFFF) ^ m ^ K_KEY
            c = crc_step(c, data)
            out += data.to_bytes(4, "little")
        c = crc_step(c, f)
        return bytes(out), c & 0xFFFF
