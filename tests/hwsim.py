"""
hwsim.py - a faithful-as-we-know-it simulation of the Action Replay MAX DUO in
USB SERVER MODE, for testing firmware v3 and the PC tool together.

Models what we learned on real hardware:
  * mapping register 0x0800009C: 0x0120 = DUO program, 0x0101/0x0007/0x0001 =
    game cartridge (the DUO's program vanishes; executing it is a test failure)
  * the save chip SLEEPS after every swap-in and only answers once the game's
    ROM has been read (reads return 0xFF, writes are ignored, until then)
  * save chips: Sanyo / Macronix 128 KB Flash (ID mode, F0 reset, AA55F0 exit,
    bank switch), 64 KB Flash, 32 KB SRAM, EEPROM (nothing at 0x0E000000), none
  * ANY write that could change save data is recorded as a violation
    (Flash erase/program prefixes, any SRAM write, writes to EEPROM carts)
  * USB: Datel's 8-byte send/receive routines are replaced by queues. The link
    is STRICTLY ALTERNATING, as every Datel transfer is and as v3's failure on
    real hardware showed: a PC packet, then a GBA packet, then a PC packet...
    A second PC packet in a row is never accepted (the PC's write times out,
    the GBA never sees it); a second GBA packet in a row hangs the GBA inside
    Datel's send routine. Both are recorded in hw.link_errors and fail tests.
    Optional fault injection: corrupted packets during streams.
  * the on-screen USB log: every line Datel's logger receives is captured
  * (v4, from lab sessions 1-4) the Actel overlays 0x08000020-0x0800009F in
    BOTH modes: zeros, with the mapping register reading F0 0F at 0x9C. The
    DUO's flash has no Nintendo logo; it borrows the game's at power-on. So a
    BIOS HardReset (logo check) freezes at "GAME BOY"; a BIOS SoftReset skips
    the check and restarts the DUO program, whose start-up looks once for a
    waiting hello (Datel's routine 0x080073F4, run for real here): hello
    waiting -> USB SERVER MODE, otherwise the menu (USB not served).
  * the USB chip runs on the cable's power: with the GBA off it still takes a
    packet and holds it (Hw(powered=False), then power_on()); old packets from
    an interrupted run can be waiting (inject_stale()).
  * games are padded with FF inside their ROM chip; open bus starts at the
    chip size (rom_size=). The DUO's 512 KB flash appears twice below 1 MB.
  * the save area is an 8-bit bus: 16/32-bit reads are a failure (v4's first
    real-hardware save found this)
  * WAITCNT with 2-cycle first ROM access corrupts game ROM reads (Ruby's chip
    did on real hardware); slower settings read correctly.

Since 11 November 2026 every DUO-hardware decision above (the Actel's mapping, overlay and
control area; the flash, its mirror, ID mode and open bus; the save chips with sleep and wake;
the USB link's alternation) is made by the shared C core, virtual/core/duocore.c, the same
model the mGBA cartridge device will use. This file keeps the CPU (Unicorn), the checks only a
simulator can make (which code wrote the mapping register, IME and WAITCNT at a save read), the
fault injection, the PC's side of USB, the BIOS and the link cable, and refreshes Unicorn's copy
of the cartridge whenever the core reports that it reads differently.

Since 12 November 2026 Datel's own USB routines run (0x0800C1DC, 0x0800C1FC, 0x0800C29C): the
control area 0x09FE0000-0x09FFFFFF is mapped as MMIO into the core, whose link registers
(0x09FE01C0 in, 0x09FE01E0 out) and model of the USB chip carry each packet a byte at a time.
"""
import os, queue, random, struct, sys, threading, time
from unicorn import *
from unicorn.arm_const import *

# the shared core lives in virtual/core (VIRTUAL_DUO_CORE names another place)
_CORE_DIR = os.environ.get("VIRTUAL_DUO_CORE") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "virtual", "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)
try:
    import duocore
    duocore.lib()
except Exception as e:                               # (no C compiler here, most likely)
    raise SystemExit(
        "The tests run the Virtual DUO's C core (virtual/core), which needs a C compiler to build.\n"
        "Run them in Ubuntu (WSL) on Windows, or anywhere with cc/gcc/clang: see virtual/README.md.\n"
        f"({type(e).__name__}: {e})")

ROM, ROMSZ = 0x08000000, 0x02000000
CTRL, CTRLSZ = 0x09FE0000, 0x00020000     # the DUO's control area: MMIO, answered by the core
ROM_MAPPED = CTRL - ROM                   # the part of the ROM space kept in Unicorn's memory
SAVE = 0x0E000000
STOP = 0x02000F00
VIEW = 0x100000                      # bytes of ROM view swapped on mapping changes

F_CARD_DETECT = 0x0800BF2C
F_USB_AVAIL = 0x0800C1DC
F_USB_RECV8 = 0x0800C1FC
F_USB_SEND8 = 0x0800C29C
F_IDLE = 0x080006A8
F_FRAME = 0x08000708
F_LOG_DRAW = 0x08006604
F_LOG_LINE = 0x080066E0
DISPATCHER = 0x08007444
GAME_MAPS = (0x0101, 0x0007, 0x0001)
FRAME_S = 0.002                      # emulated seconds per idle frame (scaled)
LOG_STALL_LINES = 300                # a screen log line: drawing, then up to a frame's wait (~1.3 frames)

FLASH_IDS = {"sanyo": (0x62, 0x13), "macronix": (0xC2, 0x09), "flash512": (0xBF, 0xD4)}
BOOT_CHECK = 0x080073F4              # Datel: if a hello is waiting, answer it and return 1
BOOT_RET = 0x02000F20                # where the simulated start-up returns to
MENU_LOOP = 0x02000F30               # 'the DUO is showing its menu' (USB not served)
OVERLAY = (0x20, 0xA0)               # Actel register window over the header
MAPREG_READ = b"\xf0\x0f\x00\x00"

# The 156-byte logo every licensed GBA game carries at 0x04 (the BIOS checks it
# at power-on). Used here only to build test ROMs and to model the BIOS check.
LOGO = bytes.fromhex(
    "24FFAE51699AA2213D84820A84E409AD11248B98C0817F21A352BE199309CE2010464A4AF82731EC58C7E833"
    "82E3CEBF85F4DF94CE4B09C194568AC01372A7FC9F844D73A3CA9A615897A327FC039876231DC7610304AE56"
    "BF38840040A70EFDFF52FE036F9530F197FBC08560D68025A963BE03014E38E2F9A234FFBB3E0344780090CB"
    "88113A9465C07C6387F03CAFD625E48B380AAC7221D4F807")
assert len(LOGO) == 156


_OPEN_BUS = {}
_BEYOND = {}


def beyond_cartridge(core, view):
    """What reads above the cartridge return (open bus), as the core renders it. It's the same for
    every DUO with the same span, so it's rendered once per process and reused, as the original
    reused its open-bus image. (Rendering two fresh 31 MB buffers for every simulated DUO shifts the
    heap enough to expose a crash inside Unicorn's own memory code: 11 failures in 28 runs of one
    test stretch, against none in 20 with this cache.)"""
    if view not in _BEYOND:
        _BEYOND[view] = core.render(ROM + view, ROM_MAPPED - view)
    return _BEYOND[view]


def open_bus(start, length):
    key = (start, length)
    if key not in _OPEN_BUS:
        import array
        a = array.array("H", (((start + i) >> 1) & 0xFFFF for i in range(0, length, 2)))
        _OPEN_BUS[key] = a.tobytes()
    return _OPEN_BUS[key]


def make_game_rom(title=b"POKEMON RUBY", code=b"AXVE", tag=b"FLASH1M_V103", size=0x80000, tag_at=0x40000, seed=1,
                  rom_size=None, revision=0):
    """A test game: `size` bytes of data, FF-padded to `rom_size` (the chip size)."""
    rng = random.Random(seed)
    rom = bytearray(rng.getrandbits(8) for _ in range(size))
    rom[0:4] = b"\x2e\x00\x00\xea"
    rom[4:0xA0] = LOGO
    rom[0xA0:0xAC] = title.ljust(12, b"\0")[:12]
    rom[0xAC:0xB0] = code
    rom[0xB0:0xB2] = b"01"
    rom[0xB2] = 0x96
    rom[0xB3:0xBC] = bytes(9)
    rom[0xBC] = revision
    for t in (b"FLAS", b"SRAM", b"EEPR"):          # make sure no accidental tags
        i = rom.find(t)
        while i >= 0:
            rom[i] ^= 0x20
            i = rom.find(t)
    if tag:
        rom[tag_at:tag_at + len(tag)] = tag
    rom[0xBD] = (-(sum(rom[0xA0:0xBD])) - 0x19) & 0xFF
    if rom_size:
        rom += b"\xFF" * (rom_size - len(rom))
    return bytes(rom)


class Hw:
    def __init__(self, fw, game_rom, save_type="sanyo", save=None, faults=None, log_lines=True, powered=True):
        self.fw = fw
        self.game = game_rom
        self.save_type = save_type
        size = {"sanyo": 0x20000, "macronix": 0x20000, "flash512": 0x10000, "sram": 0x8000}.get(save_type, 0)
        contents = bytearray(save[:size] if save else bytes(random.Random(7).getrandbits(8) for _ in range(size)))
        if len(contents) < size:
            contents += b"\xFF" * (size - len(contents))
        self.original_save = bytes(contents)
        # the DUO's hardware: flash, the Actel, the game in the slot and its save chip, the USB chip
        self.core = duocore.Core(fw, game_rom, save_type, contents)
        self.faults = faults or {}
        self.violations = []
        self.bad = []
        self.log = []
        self.log_stalls = []
        self.map_writes = []
        self.save_reads = 0
        self.wake_hook = None
        self.d2h = queue.Queue()             # GBA packets on their way to the PC
        self.done = threading.Event()
        self.sent_packets = 0
        self.rng = random.Random(self.faults.get("seed", 3))
        self.link_errors = []
        self.pc_packets = 0
        self.powered = powered
        self.boots = []                      # 'usb' / 'menu' per simulated start-up
        self.restarts = 0
        self.usb_latency = 0.0               # seconds before a PC packet is visible to the GBA (real USB: ~8-10 ms polling)
        self.link_idle_reads = 0             # the GBA polling the link with nothing there (paced, see on_ctrl_read)
        self.view = self.core.rom_span       # the span that differs between the DUO and the game

        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        mu.ctl_set_cpu_model(UC_CPU_ARM_926)       # Thumb-1 only, like the GBA's ARM7TDMI
        mu.mem_map(0x02000000, 0x40000)
        mu.mem_map(0x03000000, 0x8000)
        mu.mem_map(0x04000000, 0x1000)
        mu.mem_map(0x05000000, 0x1000)
        mu.mem_map(0x06000000, 0x18000)
        mu.mem_map(0x07000000, 0x1000)
        mu.mem_map(ROM, ROM_MAPPED, UC_PROT_READ | UC_PROT_EXEC)
        mu.mmio_map(CTRL, CTRLSZ, self.on_ctrl_read, None, self.on_ctrl_write, None)
        mu.mem_map(SAVE, 0x10000, UC_PROT_READ)
        # beyond the cartridge (open bus: the GBA returns the address bits), as the core reads it
        mu.mem_write(ROM + self.view, beyond_cartridge(self.core, self.view))
        self.show_duo()
        self.save_view()
        mu.mem_write(0x04000208, struct.pack("<H", 1))
        mu.mem_write(0x04000204, struct.pack("<H", 0x4314))
        mu.mem_write(0x03001C3C, struct.pack("<I", 0x0203C000))
        mu.mem_write(0x03000000, fw[0xCCF4:0xCE6C])
        self.boot_iwram = bytes(mu.mem_read(0x03000000, 0x178))

        mu.hook_add(UC_HOOK_MEM_WRITE_PROT, self.on_rom_write, begin=ROM, end=ROM + ROM_MAPPED - 1)
        mu.hook_add(UC_HOOK_MEM_WRITE_PROT, self.on_save_write, begin=SAVE, end=SAVE + 0xFFFF)
        mu.hook_add(UC_HOOK_MEM_READ, self.on_save_read, begin=SAVE, end=SAVE + 0xFFFF)
        mu.hook_add(UC_HOOK_CODE, self.on_rom_code, begin=ROM, end=ROM + 0x40000)
        mu.hook_add(UC_HOOK_INTR, self.on_swi)
        mu.hook_add(UC_HOOK_CODE, self.on_boot_ret, begin=BOOT_RET, end=MENU_LOOP + 2)
        mu.hook_add(UC_HOOK_MEM_WRITE, self.on_waitcnt, begin=0x04000204, end=0x04000205)
        mu.mem_write(BOOT_RET, b"\xfe\xe7")     # b . (never really executed)
        mu.mem_write(MENU_LOOP, b"\xfe\xe7")
        self.flip_at = set(self.faults.get("flip_save_read", ()))
        self.restore = None
        self.link_partner = None             # a second GBA on the link port (see attach_link_partner)
        self.link_words = []                 # (word sent by the DUO's GBA, word sent by the partner)

    # ------------------------------------------------------------ link port
    def attach_link_partner(self, partner, delay_blocks=40):
        """A second GBA on the link port, as the clock master in Normal 32-bit mode
        (as a Pokemon game is when it looks for a Wireless Adapter). partner.out is
        the word it sends next; partner.intr(word) receives ours. A transfer happens
        only once our side has armed SIOCNT (start bit) with an external clock."""
        self.link_partner = partner
        self.sio_armed = None
        self.blocks = 0
        self.sio_delay = delay_blocks
        self.mu.hook_add(UC_HOOK_MEM_WRITE, self.on_siocnt, begin=0x04000128, end=0x04000129)
        self.mu.hook_add(UC_HOOK_BLOCK, self.on_block)

    # ------------------------------------------------------------ link port, line by line
    def attach_link_game(self, gen, blocks_per_line=25, xfer_blocks=6, lag_bits=0, first_bit=False,
                         flick=None):
        """A second GBA running librfu (tests/rfu_game_model.py): either side can be the
        clock master, and both see each other's SO line (SIOCNT bit 3 -> the other's bit 2).
        A word only arrives if the receiving side was armed (start bit set) when the clock
        ran; otherwise it sees its partner's idle SO level and the word is lost, as on
        hardware. VCOUNT advances one line every blocks_per_line blocks."""
        self.lg = gen
        self.lg_bpl, self.lg_x = blocks_per_line, xfer_blocks
        # lag_bits=1: what lab session 11 suggests - the DUO, as clock slave at 2 MHz, answers one
        # clock late, so the game reads the DUO's idle SO level first, then its word minus the last bit
        self.lg_lag = lag_bits
        # first_bit=True: what lab session 12 measured - at 2 MHz the clock slave's FIRST bit is
        # read from its SO resting level (SIOCNT bit 3) instead of the word; the rest arrive intact
        self.lg_first = first_bit
        self.duo_low_seen = False         # the DUO dropped SO low, however briefly, while armed
        # flick=(address of flick_w, narrowest width the game notices, widest width that is over
        # before its first clock edge): the cable/timing window lab sessions 12-14 point to
        self.lg_flick = flick
        self.last_pulse_w = None
        self.armed_low_since = None
        self.blocks = 0
        self.game_so, self.game_armed, self.game_got = 0, None, []
        self.lg_op, self.lg_deadline, self.lg_xfer = None, 0, None
        self.duo_xfer = None
        self.lg_result, self.lg_error, self.lg_done = None, None, False
        self.link_trouble = []
        self.mu.hook_add(UC_HOOK_MEM_WRITE, self.lg_on_siocnt, begin=0x04000128, end=0x04000129)
        self.mu.hook_add(UC_HOOK_MEM_READ, self.lg_on_read, begin=0x04000006, end=0x04000007)
        self.mu.hook_add(UC_HOOK_MEM_READ, self.lg_on_read, begin=0x04000128, end=0x04000129)
        self.mu.hook_add(UC_HOOK_BLOCK, self.lg_on_block)
        self.lg_resume(None)

    def lg_cnt(self):
        return struct.unpack("<H", self.mu.mem_read(0x04000128, 2))[0]

    def lg_duo_so(self):
        cnt = self.lg_cnt()
        if self.lg_first and cnt & 0x80 and not cnt & 0x1 and cnt & 0x1000:
            # lab session 15: while armed, SO shows the loaded word's first bit, not SIOCNT bit 3;
            # lab session 17: but armed straight from resting high, it stays high
            if getattr(self, "armed_from_high", False):
                return 1
            return struct.unpack("<I", self.mu.mem_read(0x04000120, 4))[0] >> 31
        return (cnt >> 3) & 1

    def lg_on_read(self, mu, access, addr, size, value, _):
        if addr in (0x04000006, 0x04000007):
            mu.mem_write(0x04000006, struct.pack("<H", (self.blocks // self.lg_bpl) % 228))
        else:
            c = self.lg_cnt() & ~4 | (4 if self.game_so else 0)
            mu.mem_write(0x04000128, struct.pack("<H", c))

    def lg_pin_model(self, mu, old, v):
        """Lab sessions 15 and 17's reading of the hardware. Armed, a low written to bit 3 shows
        nothing: arming while SO rests high keeps it high, even for a top-bit-0 word. Disarmed, SO is bit 3: a 'ready' flick
        must disarm for a moment. If the game's clock starts before the DUO re-arms, the word is
        lost."""
        armed_now = v & 0x80 and not v & 0x1 and v & 0x1000
        was_armed = old & 0x80 and not old & 0x1 and old & 0x1000
        if armed_now and not was_armed:
            self.armed_from_high = bool(old & 0x8)
        if armed_now:
            msb = struct.unpack("<I", mu.mem_read(0x04000120, 4))[0] >> 31
            if not msb and not was_armed and not old & 0x8:
                self.duo_low_seen = True              # a plain armed low (top bit 0): ready
                self.armed_low_since = self.blocks
            # Lab session 17: arming from "resting high" with bit 3 low leaves SO high - the game
            # never sees 'ready' (it took the 0x1D header, then never clocked answer word 1)
            return
        if v & 0x8:
            return
        if was_armed:                                 # disarmed and low: a flick starts
            if self.armed_low_since is None or self.blocks - self.armed_low_since >= 60:
                self.armed_low_since = self.blocks    # (the game's clock follows its FIRST sighting)
            elif self.duo_low_seen:
                self.link_trouble.append("the DUO flicked again just before the game's clock")
                self.flick_mid_word = True
            if self.lg_flick:
                w = struct.unpack("<I", mu.mem_read(self.lg_flick[0], 4))[0]
                self.last_pulse_w = w
                self.duo_low_seen = w >= self.lg_flick[1]
            else:
                self.duo_low_seen = True
        else:
            self.duo_low_seen = True                  # a steady low (end of a command, or the low
            if self.armed_low_since is None or self.blocks - self.armed_low_since >= 60:
                self.armed_low_since = self.blocks    # before arming a top-bit-0 word): the game's
                                                      # clock follows a little after, as for a flick

    def lg_on_siocnt(self, mu, access, addr, size, value, _):
        old = self.lg_cnt()
        v = value & 0xFFFF if addr == 0x04000128 and size >= 2 else \
            (old & 0xFF00 | value & 0xFF) if addr == 0x04000128 else (old & 0xFF | (value << 8) & 0xFF00)
        if self.lg_first:
            self.lg_pin_model(mu, old, v)
        elif v & 0x8 or not v & 0x80:
            self.armed_low_since = None
        if self.lg_first:
            pass
        elif not v & 0x8:
            if self.lg_flick and v & 0x80:     # an armed low: a flick of flick_w spin steps
                addr, wmin, wmax = self.lg_flick
                w = struct.unpack("<I", mu.mem_read(addr, 4))[0]
                self.last_pulse_w = w
                self.duo_low_seen = w >= wmin
            else:
                self.duo_low_seen = True        # a real GBA polling SI could catch even a brief low
            if v & 0x80 and not (old & 0x80 and not old & 0x8):
                self.armed_low_since = self.blocks
            elif not v & 0x80 and old & 0x88:           # disarmed and low: a flick (or the low
                self.armed_low_since = self.blocks      # before arming a top-bit-0 word) starts
        if self.lg_first and self.lg_xfer is not None and isinstance(self.lg_xfer[1], int):
            # touching SIOCNT while the game clocks a word loses that word (lab session 13)
            self.lg_xfer = (self.lg_xfer[0], self.lg_xfer[1] ^ 0x0000FFFF)
            self.link_trouble.append("the DUO wrote SIOCNT in the middle of a word")
        if v & 0x80 and v & 0x1 and not (old & 0x80 and old & 0x1):        # the DUO clocks a word
            if self.lg_xfer is not None:
                self.link_trouble.append("both sides started a transfer as clock master")
            word = struct.unpack("<I", mu.mem_read(0x04000120, 4))[0]
            self.duo_xfer = (self.blocks + self.lg_x, word, bool(v & 0x2))

    def lg_resume(self, value):
        try:
            self.lg_op = self.lg.send(value)
        except StopIteration as e:
            self.lg_op, self.lg_result, self.lg_done = None, e.value, True
            self.lg_done_at = self.blocks
            return
        except Exception as e:                     # the game's own error (LinkError etc.)
            self.lg_op, self.lg_error, self.lg_done = None, e, True
            self.lg_done_at = self.blocks
            return
        op = self.lg_op
        if op[0] not in ("delay", "now", "until_ready") and getattr(self, "lg_first_at", None) is None:
            self.lg_first_at = self.blocks          # the game's first move on the link
        if op[0] == "wait_si":
            self.duo_low_seen = False
        if op[0] in ("wait_si", "wait_xfer", "delay"):
            self.lg_deadline = self.blocks + (op[1] if op[0] == "delay" else op[2] if op[0] == "wait_si" else op[1])
        self.lg_xfer = None

    def lg_finish_duo_xfer(self, mu):
        done_at, word, fast = self.duo_xfer
        if self.blocks < done_at:
            return
        self.duo_xfer = None
        if self.game_armed is not None:
            got_back, self.game_armed = self.game_armed, None
            if self.lg_first and fast:              # the game is the late clock slave now
                got_back = (self.game_so << 31) | (got_back & 0x7FFFFFFF)
            self.game_got.append(word)
        else:
            got_back = 0xFFFFFFFF if self.game_so else 0
            self.link_trouble.append(f"the DUO clocked {word:#010x} but the game wasn't ready")
        self.link_words.append((word, got_back))
        mu.mem_write(0x04000120, struct.pack("<I", got_back))
        mu.mem_write(0x04000128, struct.pack("<H", self.lg_cnt() & ~0x80))

    def lg_on_block(self, mu, addr, size, _):
        self.blocks += 1
        if self.duo_xfer is not None:
            self.lg_finish_duo_xfer(mu)
        for _ in range(64):
            op = self.lg_op
            if op is None:
                return
            k = op[0]
            if k == "so":
                self.game_so = op[1]; self.lg_resume(None); continue
            if k == "arm":
                self.game_armed, self.game_so = op[1], 0; self.game_got = []; self.lg_resume(None); continue
            if k == "delay":
                if self.blocks >= self.lg_deadline:
                    self.lg_resume(None); continue
                return
            if k == "wait_si":
                level = self.lg_duo_so()
                if (op[1] == 0 and level == 0 and self.lg_flick and self.armed_low_since is not None
                        and self.blocks - self.armed_low_since < 60):
                    level = 1                       # a flick in progress: only its width decides
                if level == op[1] or (op[1] == 0 and self.duo_low_seen):
                    self.lg_resume(True); continue
                if self.blocks >= self.lg_deadline:
                    self.lg_resume(False); continue
                return
            if k == "until_ready":                       # the player switches the game on
                cnt = self.lg_cnt()
                if cnt & 0x80 and not cnt & 0x1 and cnt & 0x1000:
                    self.lg_resume(True); continue
                return
            if k == "wait_xfer":
                if self.game_got:
                    self.lg_resume(self.game_got.pop(0)); continue
                if self.blocks >= self.lg_deadline:
                    self.lg_resume(None); continue
                return
            if k == "xfer":
                if (self.lg_xfer is None and self.armed_low_since is not None
                        and self.blocks - self.armed_low_since < 60):
                    return      # the game's clock starts a little after it sees the flick (librfu: stop
                                # the timer, two SIOCNT writes); the flick window decides the first bit
                if self.lg_xfer is None:
                    cnt = self.lg_cnt()
                    armed = cnt & 0x80 and not cnt & 0x1 and cnt & 0x1000
                    duo_word = struct.unpack("<I", mu.mem_read(0x04000120, 4))[0] if armed else None
                    if armed and self.lg_lag and len(op) > 2 and op[2] == 2:
                        duo_word = ((cnt >> 3 & 1) << 31) | (duo_word >> 1)
                    if armed and self.lg_first and len(op) > 2 and op[2] == 2:
                        duo_word = ((cnt >> 3 & 1) << 31) | (duo_word & 0x7FFFFFFF)
                        if self.lg_flick and self.last_pulse_w is not None and self.last_pulse_w > self.lg_flick[2]:
                            duo_word = "lost"           # still disarmed at the first clock edge
                    if armed and getattr(self, "flick_mid_word", False):
                        duo_word = "lost"               # a second flick landed on the clock edges
                    self.flick_mid_word = False
                    self.last_pulse_w = None
                    self.lg_xfer = (self.blocks + self.lg_x, duo_word)
                    return
                done_at, duo_word = self.lg_xfer
                if self.blocks < done_at:
                    return
                if duo_word == "lost":
                    got = 0                             # it read our low SO; our own word never ran
                    self.link_trouble.append(f"the game clocked {op[1]:#010x} while the DUO was disarmed")
                elif duo_word is None:
                    got = 0xFFFFFFFF if self.lg_duo_so() else 0
                    self.link_trouble.append(f"the game clocked {op[1]:#010x} but the DUO wasn't ready")
                else:
                    got = duo_word
                    mu.mem_write(0x04000120, struct.pack("<I", op[1]))
                    mu.mem_write(0x04000128, struct.pack("<H", self.lg_cnt() & ~0x80))
                self.link_words.append((got, op[1]))
                self.lg_resume(got); continue
            return

    def on_siocnt(self, mu, access, addr, size, value, _):
        v = value & 0xFFFF if addr == 0x04000128 else (value << 8) & 0xFF00
        if v & 0x80 and not v & 0x1 and v & 0x1000 and not v & 0x2000:
            self.sio_armed = self.blocks + self.sio_delay      # external clock, 32-bit normal, start
        elif not v & 0x80:
            self.sio_armed = None

    def on_block(self, mu, addr, size, _):
        self.blocks += 1
        if self.sio_armed is not None and self.blocks >= self.sio_armed:
            self.sio_armed = None
            ours = struct.unpack("<I", mu.mem_read(0x04000120, 4))[0]
            theirs = self.link_partner.out
            self.link_partner.intr(ours)
            self.link_words.append((ours, theirs))
            mu.mem_write(0x04000120, struct.pack("<I", theirs))
            cnt = struct.unpack("<H", mu.mem_read(0x04000128, 2))[0]
            mu.mem_write(0x04000128, struct.pack("<H", cnt & ~0x80))

    # ------------------------------------------------------------ the core's state, as tests see it
    mapped = property(lambda self: self.core.mapped)          # None = DUO, else the map value
    awake = property(lambda self: self.core.awake)
    bank = property(lambda self: self.core.bank)
    id_mode = property(lambda self: self.core.id_mode)
    save_writes = property(lambda self: self.core.save_writes)
    ignored = property(lambda self: self.core.ignored)
    waitcnt = property(lambda self: self.core.waitcnt)
    save = property(lambda self: self.core.save)              # the save chip's contents

    @property
    def turn(self):                                           # whose packet the link expects next
        return self.core.turn

    # ------------------------------------------------------------ views
    def refresh_rom(self, lo, hi):
        """Unicorn keeps the cartridge in memory: copy in what the core now reads there."""
        hi = min(hi, ROM_MAPPED)                 # the control area is MMIO: always the core's
        if hi > lo:
            self.mu.mem_write(ROM + lo, self.core.render(ROM + lo, hi - lo))

    def show_duo(self):
        self.refresh_rom(0, self.view)

    show_game = show_duo                                      # the core knows which is mapped

    def apply(self, r):
        """Carry out what a core result says changed."""
        if r.flags & duocore.F_ROM_CHANGED:
            self.refresh_rom(r.rom_lo, r.rom_hi)
            self.refresh_rom(r.rom_lo2, r.rom_hi2)
        if r.flags & duocore.F_SAVE_CHANGED:
            self.save_view()
        if r.flags & duocore.F_VIOLATION:
            self.violations.append(r.msg)
        if r.flags & duocore.F_FLASH_CHANGED:
            # the toolkit must never program or erase the DUO's own flash (on hardware it's
            # Datel's program and the user's codes); only Datel's own start-up does, outside tests
            self.bad.append("the DUO's own flash was programmed or erased")

    def on_waitcnt(self, mu, access, addr, size, value, _):
        # Rewriting ROM memory inside an ordinary write hook crashes unicorn, so pause
        # the CPU after this instruction; run() applies the new view and resumes.
        if addr == 0x04000204 and size >= 2:
            r = self.core.set_waitcnt(value)
            if r.flags & duocore.F_ROM_CHANGED:
                self.pending_view = True
                mu.emu_stop()

    def inject_stale(self, pkt):
        """A packet the DUO sent during an earlier, interrupted run, still held by the USB chip."""
        self.d2h.put(bytes(pkt))

    # ------------------------------------------------------------ start-up / reset
    def visible(self):
        """Is a PC packet waiting that the GBA can see yet?"""
        return self.core.usb_pending

    def boot(self, mu):
        """Datel's start-up, from the point where it checks for a waiting hello. Modelled as
        happening the instant the GBA resets (the worst case: on real hardware Datel's
        start-up takes a little while first, which only helps). Its look at the link is
        Datel's own code reading the core's link register."""
        mu.reg_write(UC_ARM_REG_SP, 0x03007E00)
        mu.reg_write(UC_ARM_REG_LR, BOOT_RET | 1)
        mu.reg_write(UC_ARM_REG_PC, BOOT_CHECK | 1)

    def on_boot_ret(self, mu, addr, size, _):
        if addr == BOOT_RET:
            if mu.reg_read(UC_ARM_REG_R0) == 1:
                self.boots.append("usb")
                mu.reg_write(UC_ARM_REG_SP, 0x03007E00)
                mu.reg_write(UC_ARM_REG_LR, STOP | 1)
                mu.reg_write(UC_ARM_REG_PC, DISPATCHER | 1)
            else:
                self.boots.append("menu")
                mu.reg_write(UC_ARM_REG_PC, MENU_LOOP | 1)
        elif addr == MENU_LOOP:
            if self.done.is_set():
                mu.emu_stop()
            time.sleep(FRAME_S)

    def on_swi(self, mu, intno, _):
        if intno != 2:
            return self.fail(f"unexpected CPU exception {intno}")
        pc = mu.reg_read(UC_ARM_REG_PC)
        num = mu.mem_read(pc - 2, 1)[0]
        if num == 0x00:                                         # SoftReset
            ime = struct.unpack("<H", mu.mem_read(0x04000208, 2))[0]
            flag = mu.mem_read(0x03007FFA, 1)[0]
            if ime:
                return self.fail("SoftReset with interrupts still enabled")
            if flag != 0:
                return self.fail("SoftReset flag not 0: the BIOS would jump into RAM, not the DUO")
            if self.mapped is not None:
                return self.fail("SoftReset with the game mapped: the DUO program would not be found")
            self.restarts += 1
            mu.mem_write(0x03007E00, bytes(0x200))
            self.boot(mu)
        elif num == 0x26:                                       # HardReset: BIOS replays the logo check
            seen = bytes(mu.mem_read(ROM + 4, len(LOGO)))
            if seen != LOGO:
                return self.fail('HardReset: the BIOS logo check reads the masked header and stops at "GAME BOY"')
            self.restarts += 1
            self.boot(mu)
        else:
            self.fail(f"unexpected BIOS call SWI {num:#x}")

    def power_on(self):
        """The person switches the GBA on: the DUO starts and checks once for a waiting hello."""
        assert not self.powered
        self.powered = True
        self.thread = threading.Thread(target=self.run, args=(True,), daemon=True)
        self.thread.start()
        return self

    def save_view(self):
        self.mu.mem_write(SAVE, self.core.render(SAVE, 0x10000))

    # ------------------------------------------------------------ hooks
    def ret(self, value=None):
        if value is not None:
            self.mu.reg_write(UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.mu.reg_write(UC_ARM_REG_PC, self.mu.reg_read(UC_ARM_REG_LR))

    def fail(self, msg):
        self.bad.append(msg)
        self.mu.emu_stop()

    def cstr(self, addr, n=80):
        b = bytes(self.mu.mem_read(addr, n))
        return b.split(b"\0")[0].decode("latin-1")

    def on_rom_code(self, mu, addr, size, _):
        if self.mapped is not None:
            return self.fail(f"executed ROM at {addr:#x} while the game was mapped")
        if addr == F_CARD_DETECT:
            self.ret(0)
        elif addr == F_USB_SEND8 and self.core.turn != "gba":
            # A simulator-only check: a second GBA packet in a row waits in Datel's SEND8 for the
            # USB chip to ask for a byte, which it never does (v3's back-to-back stall).
            pkt = bytes(mu.mem_read(mu.reg_read(UC_ARM_REG_R0), 8))
            self.link_errors.append(f"GBA sent two packets in a row ({pkt.hex()}) - it would hang here")
            return self.fail(self.link_errors[-1])
        elif addr == F_IDLE:
            if self.done.is_set():
                mu.emu_stop()
            time.sleep(FRAME_S)
            self.ret()
        elif addr in (F_FRAME, F_LOG_DRAW):
            self.ret()
        elif addr == F_LOG_LINE:
            self.log.append(self.cstr(mu.reg_read(UC_ARM_REG_R0)))
            # On hardware a log line redraws the screen and then waits for the next frame
            # (0x08006604 -> 0x08000708): the GBA looks away from the link for over a frame. With a
            # multi-player game attached, let the game run on meanwhile, so a program that logs in
            # the middle of a link session misses transfers here as it would there.
            if getattr(self, "mp_op", None) is not None or hasattr(self, "mp_frame_blocks"):
                self.log_stalls.append(self.blocks)
                for _ in range(LOG_STALL_LINES * self.lg_bpl):
                    self.mp_on_block(mu, 0, 0, None)
            elif hasattr(self, "lg"):                     # the wireless adapter's game, likewise
                self.log_stalls.append(self.blocks)
                for _ in range(LOG_STALL_LINES * self.lg_bpl):
                    self.lg_on_block(mu, 0, 0, None)
            self.ret()

    def deliver(self, pkt):
        """USB itself is reliable; faults model the DUO's chip during fast streams only."""
        self.sent_packets += 1
        f = self.faults
        if pkt[:4] == b"SBW\x30":
            self.stream_n = 0
            self.d2h.put(pkt)
            return
        if pkt[:4] == b"SBW\x32" or getattr(self, "stream_n", None) is None:
            self.stream_n = None if pkt[:4] == b"SBW\x32" else getattr(self, "stream_n", None)
            self.d2h.put(pkt)
            return
        self.stream_n += 1
        n = self.stream_n
        if n in f.get("corrupt_at", ()) or (f.get("corrupt_p") and self.rng.random() < f["corrupt_p"]):
            b = bytearray(pkt)
            b[self.rng.randrange(8)] ^= 1 << self.rng.randrange(8)
            pkt = bytes(b)
        self.d2h.put(pkt)

    def on_rom_write(self, mu, access, addr, size, value, _):
        if addr == 0x0800009C:
            # A simulator-only check (the Actel can't see the CPU): Datel swaps from RAM, since
            # the DUO's program vanishes from the bus the moment the game is mapped.
            pc = mu.reg_read(UC_ARM_REG_PC)
            if not (0x02000000 <= pc < 0x02040000 or 0x03000000 <= pc < 0x03008000):
                self.fail(f"mapping register written from {pc:#x}, not RAM")
                return False
            self.map_writes.append(value & 0xFFFF)
        r = self.core.write(addr, size, value)
        if r.failed:
            self.fail(r.msg)
            return False
        self.apply(r)
        if self.wake_hook is None and self.core.wants_rom_reads:
            # the save chip sleeps until the game's ROM is read: the core needs to hear of it
            self.wake_hook = mu.hook_add(UC_HOOK_MEM_READ, self.on_rom_read, begin=ROM, end=ROM + ROMSZ - 1)
        return True

    def on_rom_read(self, mu, access, addr, size, value, _):
        if self.core.wants_rom_reads:
            _, r = self.core.read(addr, size)
            if r.flags & duocore.F_SAVE_CHANGED:
                self.save_view()
        if self.wake_hook is not None:
            mu.hook_del(self.wake_hook)
            self.wake_hook = None

    def on_ctrl_read(self, mu, offset, size, _):
        """The control area, read: the core answers (the link register live)."""
        v, r = self.core.read(CTRL + offset, size)
        if r.flags & duocore.F_SAVE_CHANGED:
            self.save_view()
        if r.flags & duocore.F_BAD:
            self.bad.append(r.msg)
        if CTRL + offset == duocore.LINK_IN and not ((v ^ self.core.link_out) & 0x100):
            # Nothing from the USB chip: the GBA is polling. Pace it, so the PC's thread gets
            # the interpreter, and let it be stopped.
            self.link_idle_reads += 1
            if self.done.is_set():
                mu.emu_stop()
            elif self.link_idle_reads % 64 == 0:
                time.sleep(0.0005)
        return v

    def on_ctrl_write(self, mu, offset, size, value, _):
        """The control area, written: the link register (or a failure: anything else here)."""
        r = self.core.write(CTRL + offset, size, value)
        if r.failed:
            self.fail(r.msg)
            return
        self.apply(r)
        if r.flags & duocore.F_USB_SENT:
            self.deliver(self.core.usb_take())

    def on_save_read_after(self, mu, access, addr, size, value, _):
        if self.restore:
            a, b = self.restore
            self.restore = None
            mu.mem_write(a, bytes([b]))

    def on_save_read(self, mu, access, addr, size, value, _):
        _, r = self.core.read(addr, size)
        if r.flags & duocore.F_BAD:
            self.bad.append(r.msg)
        self.save_reads += 1
        if self.restore:
            a, b = self.restore
            self.restore = None
            mu.mem_write(a, bytes([b]))
        if self.save_reads in self.flip_at:
            old = bytes(mu.mem_read(addr, 1))[0]
            mu.mem_write(addr, bytes([old ^ 0x10]))          # one bad read, then the chip is fine
            self.restore = (addr, old)
        ime = struct.unpack("<H", mu.mem_read(0x04000208, 2))[0]
        wc = struct.unpack("<H", mu.mem_read(0x04000204, 2))[0]
        if self.mapped is not None and ime:
            self.bad.append("save read with interrupts enabled")
        if self.mapped is not None and wc & 3 != 3:
            self.bad.append(f"save read with WAITCNT {wc:#x}")

    def on_save_write(self, mu, access, addr, size, value, _):
        # the save chip's command decoder, its sleep and every save-changing write: the core
        self.apply(self.core.write(addr, size, value))
        return True

    # ------------------------------------------------------------ run
    def run(self, from_power_on=False):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, 0x03007E00)
        if from_power_on:
            mu.reg_write(UC_ARM_REG_LR, BOOT_RET | 1)
            entry = BOOT_CHECK
        else:
            mu.reg_write(UC_ARM_REG_LR, STOP | 1)
            entry = DISPATCHER
        try:
            self.pending_view = False
            mu.emu_start(entry | 1, STOP)
            while self.pending_view and not self.bad:
                self.pending_view = False
                self.show_game()
                mu.emu_start(mu.reg_read(UC_ARM_REG_PC) | 1, STOP)
        except UcError as e:
            self.bad.append(f"CPU fault: {e} at {mu.reg_read(UC_ARM_REG_PC):#x}")
        self.d2h.put(None)

    # ------------------------------------------------------------ link port, multi-player mode
    def attach_mp_game(self, gen, game_master=True, blocks_per_line=25, xfer_blocks=125, slave_latency=240, race_window=0, si_flicker=0):
        """A second GBA in the four-player link mode (SIOCNT multi-player, 115 kbit/s), running a
        game's link layer (tests/link_game_model.py) - the e-Reader route. Every transfer moves
        one 16-bit word from each console at once: each loads SIOMLT_SEND, the master starts it,
        and both then read SIOMULTI0-3 (player 0 = master, absent players 0xFFFF). The cable
        decides who is master: game_master=True puts the game on the purple (player 0) plug.
        The DUO sees completion as IF bit 7 (SIOCNT bit 14 set), cleared by writing 1 to IF,
        and reads SIOCNT bit 2 (SI: 0 = master) and bit 3 (SD: all ready).
        Timing, as on hardware (lab session 24): a transfer takes about 5 scanlines (xfer_blocks),
        and a game that is slave needs time after each transfer before its next word is loaded
        (slave_latency, ~0.6 ms here; Ruby's own master allows 0.75 ms). A transfer the DUO starts
        sooner carries the game's stale word, and the game misses it (counted in mp_missed).
        race_window > 0 (the DUO as master): a transfer due within that many blocks finishes at the
        moment the DUO reads SIOCNT - the worst moment, between its look at IF and at the busy bit.
        si_flicker = N > 0 (the game as master): every Nth read of SIOCNT shows SI low, as the
        game's SO pulls it during its transfers - one look then says "master" (lab session 27)."""
        self.mp = gen
        self.mp_master, self.lg_bpl, self.mp_x = game_master, blocks_per_line, xfer_blocks
        self.blocks = 0
        self.mp_if = 0
        self.mp_op, self.mp_deadline, self.mp_game_word = None, 0, 0xFFFF
        self.mp_duo_start = None              # block at which a DUO-started transfer completes
        self.mp_result, self.mp_error, self.mp_done = None, None, False
        self.mp_words = []                    # (player 0 word, player 1 word) per transfer
        self.mp_latency, self.mp_ready_at, self.mp_wire_word, self.mp_missed = slave_latency, 0, 0xFFFF, 0
        self.mp_start_blocks, self.mp_frame_blocks = [], blocks_per_line * 228
        self.mp_race_window, self.mp_races = race_window, 0
        self.mp_si_flicker, self.mp_si_reads = si_flicker, 0
        self.lg_result = self.lg_error = None
        self.lg_done = False
        self.mu.hook_add(UC_HOOK_MEM_READ, self.mp_on_read, begin=0x04000006, end=0x04000007)
        self.mu.hook_add(UC_HOOK_MEM_READ, self.mp_on_read, begin=0x04000128, end=0x04000129)
        self.mu.hook_add(UC_HOOK_MEM_READ, self.mp_on_read, begin=0x04000202, end=0x04000203)
        self.mu.hook_add(UC_HOOK_MEM_WRITE, self.mp_on_write, begin=0x04000202, end=0x04000203)
        self.mu.hook_add(UC_HOOK_MEM_WRITE, self.mp_on_write, begin=0x04000128, end=0x04000129)
        self.mu.hook_add(UC_HOOK_BLOCK, self.mp_on_block)
        self.mp_resume(None)

    def mp_cnt(self):
        return struct.unpack("<H", self.mu.mem_read(0x04000128, 2))[0]

    def mp_duo_ready(self):
        rcnt = struct.unpack("<H", self.mu.mem_read(0x04000134, 2))[0]
        return self.mp_cnt() & 0x3000 == 0x2000 and not rcnt & 0x8000

    def mp_on_read(self, mu, access, addr, size, value, _):
        if addr in (0x04000006, 0x04000007):
            mu.mem_write(0x04000006, struct.pack("<H", (self.blocks // self.lg_bpl) % 228))
        elif addr in (0x04000202, 0x04000203):
            mu.mem_write(0x04000202, struct.pack("<H", self.mp_if))
        else:                                              # SI: 0 on the master's plug; SD: ready
            op = self.mp_op
            if (self.mp_race_window and op is not None and op[0] == "mp_slave" and self.mp_duo_start is not None
                    and self.blocks >= self.mp_duo_start - self.mp_race_window):
                self.mp_duo_start = self.blocks            # finish it now, just as SIOCNT is read
                self.mp_races += 1
                self.mp_slave_step()
            si = 4 if self.mp_master else 0                               # the DUO's SI: 1 unless it's master
            if si and self.mp_si_flicker:
                self.mp_si_reads += 1
                if self.mp_si_reads % self.mp_si_flicker == 0:
                    si = 0                                                 # the game's SO pulling it low
            c = self.mp_cnt() & ~0xC | si | 8
            mu.mem_write(0x04000128, struct.pack("<H", c))

    def mp_on_write(self, mu, access, addr, size, value, _):
        if addr in (0x04000202, 0x04000203):              # IF: writing 1 clears that flag
            v = value & 0xFFFF if addr == 0x04000202 else (value << 8) & 0xFF00
            self.mp_if &= ~v
            return
        v = value & 0xFFFF if addr == 0x04000128 and size >= 2 else \
            (self.mp_cnt() & 0xFF00 | value & 0xFF) if addr == 0x04000128 else (self.mp_cnt() & 0xFF | (value << 8) & 0xFF00)
        if not self.mp_master and v & 0x80 and v & 0x3000 == 0x2000 and self.mp_duo_start is None:
            self.mp_duo_start = self.blocks + self.mp_x     # the DUO, as master, starts a transfer
            self.mp_duo_started = self.blocks               # (each side's word is taken at the start)
            self.mp_start_blocks.append(self.blocks)

    def mp_transfer(self, game_word):
        """One transfer: returns the four words as everyone sees them."""
        duo_word = struct.unpack("<H", self.mu.mem_read(0x0400012A, 2))[0] if self.mp_duo_ready() else 0xFFFF
        words = [game_word, duo_word] if self.mp_master else [duo_word, game_word]
        words += [0xFFFF, 0xFFFF]
        self.mp_words.append(tuple(words[:2]))
        if self.mp_duo_ready():
            self.mu.mem_write(0x04000120, struct.pack("<4H", *words))
            cnt = self.mp_cnt() & ~0x00F0 | ((1 if self.mp_master else 0) << 4)   # id; busy (bit 7) off
            self.mu.mem_write(0x04000128, struct.pack("<H", cnt))
            if cnt & 0x4000:
                self.mp_if |= 0x80
        return words

    def mp_resume(self, value):
        try:
            self.mp_op = self.mp.send(value)
        except StopIteration as e:
            self.mp_op, self.mp_result, self.mp_done = None, e.value, True
            self.lg_result, self.lg_done = e.value, True
            return
        except Exception as e:                     # the game's own error
            self.mp_op, self.mp_error, self.mp_done = None, e, True
            self.lg_error, self.lg_done, self.lg_error_at = e, True, self.blocks
            return
        op = self.mp_op
        if op[0] == "delay":
            self.mp_deadline = self.blocks + op[1]
        elif op[0] == "mp_slave":
            self.mp_game_word = op[1]                       # loaded once the game's interrupt has run
            self.mp_ready_at = self.blocks + self.mp_latency
            self.mp_deadline = self.blocks + op[2]

    def mp_slave_step(self):
        """A DUO-started transfer completes (the game is the slave). True if the game took its word."""
        self.mp_duo_start = None
        if self.mp_duo_started >= self.mp_ready_at:
            self.mp_wire_word = self.mp_game_word
        else:                                       # started too soon: the game wasn't ready
            self.mp_transfer(self.mp_wire_word)
            self.mp_missed += 1
            return False
        self.mp_resume(self.mp_transfer(self.mp_wire_word))
        return True

    def mp_on_block(self, mu, addr, size, _):
        self.blocks += 1
        for _ in range(16):
            op = self.mp_op
            if op is None:
                return
            k = op[0]
            if k == "delay":
                if self.blocks < self.mp_deadline:
                    return
                self.mp_resume(None); continue
            if k == "now":
                self.mp_resume(self.blocks); continue
            if k == "until_ready":
                if not self.mp_duo_ready():
                    return
                self.mp_resume(True); continue
            if k == "mp_xfer":                       # the game, as master, starts a transfer
                self.mp_resume(self.mp_transfer(op[1])); continue
            if k == "mp_slave":                      # the game, as slave, waits for the DUO's transfer
                if self.mp_duo_start is not None and self.blocks >= self.mp_duo_start:
                    if self.mp_slave_step():
                        continue
                    return
                if self.blocks >= self.mp_deadline:
                    self.mp_resume(None); continue
                return
            raise RuntimeError(f"unknown multi-player op {op!r}")

    def start(self):
        if not self.powered:
            return self                      # GBA off: only the USB chip is alive
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.done.set()                          # the dispatcher's idle and the link's polling both stop on it
        if not hasattr(self, "thread"):
            return
        self.thread.join(15)


class Transport:
    def __init__(self, hw):
        self.hw = hw

    def write(self, data, timeout=5000):
        hw = self.hw
        if hw.usb_latency:
            time.sleep(hw.usb_latency)           # USB polling: the packet reaches the DUO's chip later
        status, r = hw.core.usb_from_pc(data)
        if status != duocore.OK:
            hw.link_errors.append(r.msg)
            time.sleep(min(timeout, 300) / 1000)
            import usb.core
            raise usb.core.USBTimeoutError("timeout")
        hw.pc_packets += 1

    def read(self, timeout=5000):
        if self.hw.faults.get("pc_delay"):
            time.sleep(self.hw.faults["pc_delay"])
        try:
            pkt = self.hw.d2h.get(timeout=max(0.05, timeout / 1000))
        except queue.Empty:
            import usb.core
            raise usb.core.USBTimeoutError("timeout")
        if pkt is None:
            import maxduo_saves as M
            raise M.DuoError("emulated device stopped: " + "; ".join(self.hw.bad))
        return pkt

    def close(self):
        pass
