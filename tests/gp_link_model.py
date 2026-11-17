"""The four-player cable experiment, for the simulator (8 November 2026; docs/MULTI.md, section 2):
a game's GBA as child 1 in the multi-player serial mode, modelled at the level of the link port's
lines, against the DUO driving the port bit by bit in general-purpose mode (firmware/programs/lab4p.c).

The lines (GBATEK, "SIO Multi-Player Mode"): the master's SI is held low; SC low marks a transfer;
each unit sends, on the one shared SD line, a low start bit, 16 data bits from the lowest and a high
stop bit; the master's SO going low gives child 1 its turn; every unit's hardware reads every
unit's word off SD into SIOMULTI0-3 (0xFFFF for a unit that doesn't send in time); SC high ends it.
This model reads SD as each GBA's hardware would: it samples the middle of each bit, and a unit's
start bit must come within `window` bits of the previous stop bit, or that slot and the rest stay
0xFFFF. Time is the DUO's: every basic block the emulator runs is `cycles_per_block` CPU cycles
(timer 0 and VCOUNT follow it), so the program's own bit timing is what's tested, not the real
GBA's speed - hardware decides that.

Above the lines, the game's link layer (link.c) as child 1: the handshake (DoHandshake: the
handshake words in a row from slot 0 are the players), then commands of eight words and a checksum
over its player count (a mismatch is a link error), link players on 0x2222 and, for a link-up that
takes `max_players`, a refusal and close if more joined.

hblank_stall models an HBlank DMA left running on the DUO's GBA (14 November, hardware): the CPU
stops for so many cycles at each line's HBlank while a DMA channel is enabled with HBlank timing,
so a sample due then is taken late."""
import struct
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_BLOCK

BIT = 16777216 / 115200                  # CPU cycles a bit at 115,200 baud
MASTER_HS, SLAVE_HS = 0x8FFF, 0xB9A0
RCNT, TM0, VCOUNT = 0x04000134, 0x04000100, 0x04000006
P_SC, P_SD, P_SI, P_SO = 1, 2, 4, 8


class GpLinkGame:
    def __init__(self, hw, cycles_per_block=20, delay_bits=0.5, window=3.0, max_players=2, game_version=2,
                 link_player=None, garble=0.0, hblank_stall=0, miss_master=0, lead_window=None, silent_lead=None, hardware=True, gap_window=None):
        self.hw, self.cpb = hw, cycles_per_block
        self.delay, self.window, self.max_players = delay_bits, window, max_players
        self.version = game_version
        self.blocks = 0
        self.rcnt = 0
        self.sd_edges = []                    # (t, level) of the SD line, as driven by the DUO
        self.duo_driving = False
        self.in_transfer, self.t_start, self.t_so_low = False, 0, None
        # (14 November, hardware: English Ruby sent 0xB9A0 itself, the low bits clear)
        self.game_word, self.game_t0 = SLAVE_HS | 1, None
        self.transfers = []                   # SIOMULTI0-3 as the game's hardware read each transfer
        self.errors = []
        # the game's link layer
        self.player_count, self.prev_count, self.linked = 0, 0, False
        self.send_idx = self.recv_idx = 0
        self.checksum, self.checksum_ready = 0, False
        self.frame = [[0] * 4 for _ in range(8)]
        self.queue, self.current = [], [0] * 8
        self.blocks_in, self.rx = {}, {}
        self.result = dict(handshake_players=None, link_players={}, refused=None, closed=False, checksum_errors=0)
        self.lp = link_player or bytes(60)
        # garble (12 November, hardware: the DUO read the game's handshake only now and then): the share of
        # the game's words whose bit 5 the DUO reads wrongly (the game itself reads its own word right)
        import random
        self.garble, self.rng, self.garbled_t0 = garble, random.Random(5), {}
        # hblank_stall (14 November, hardware: one bit read late at the same place every transfer): while a DMA
        # channel is enabled with HBlank timing, the DUO's CPU loses this many cycles at each line's HBlank
        self.stall, self.next_hblank, self.stalls = hblank_stall, 960, 0
        # miss_master (14 November, hardware: the game never left its handshake): the game misreads the
        # DUO's first so many master handshakes (0x8FFF), as if the bits came out wrong
        self.miss_master = miss_master
        self.after_players, self.patience, self.cards_asked, self.cards_from, self.in_room = 0, 300, False, set(), False
        # lead_window (15 November, hardware: the game never took the DUO's 0x8FFF in 374 tries): the game reads
        # the DUO's word right only if its start bit comes within (lo, hi) cycles of SC going low
        self.lead_window, self.lead0, self.leads = lead_window, None, set()
        # silent_lead (15 November, late: leads of 146 and 220 silenced the game): no answer at all when the DUO's
        # start bit comes more than this many cycles after SC going low
        self.silent_lead = silent_lead
        # gap_window (16 November, night, hardware: the game read the DUO's hand-sent slots as garbage): the
        # game reads a hand-sent slot right only if its start bit comes (lo, hi) cycles after the word before
        # it ends; otherwise it reads garbage (and DoHandshake counts no players)
        self.gap_window, self.gaps = gap_window, set()
        hw.mu.hook_add(UC_HOOK_BLOCK, self.on_block)
        hw.mu.hook_add(UC_HOOK_MEM_WRITE, self.on_write, begin=RCNT, end=RCNT + 1)
        hw.mu.hook_add(UC_HOOK_MEM_READ, self.on_read, begin=RCNT, end=RCNT + 1)
        hw.mu.hook_add(UC_HOOK_MEM_READ, self.on_read, begin=TM0, end=TM0 + 1)
        hw.mu.hook_add(UC_HOOK_MEM_READ, self.on_read, begin=VCOUNT, end=VCOUNT + 1)
        # the hybrid (16 November): the DUO's own link hardware sends slot 0 - a start on SIOCNT in the
        # serial mode puts the hardware master's word on SD (`hw_lead` cycles in), SO low after it
        self.hw_lead, self.hw_end, self.hw_busy_until, self.hw_sends, self.hw_word1 = 20, None, 0, 0, None
        self.hw_stuck = None                                 # (what SIOMULTI1 sticks at once the pins are taken)
        if hardware:                                         # (not with the scope's own model of it)
            hw.mu.hook_add(UC_HOOK_MEM_WRITE, self.on_siocnt, begin=0x04000128, end=0x04000129)
            hw.mu.hook_add(UC_HOOK_MEM_READ, self.on_siocnt_read, begin=0x04000128, end=0x04000129)
            hw.mu.hook_add(UC_HOOK_MEM_READ, self.on_siomulti_read, begin=0x04000120, end=0x04000127)

    # ------------------------------------------------------------ the lines
    def t(self):
        return self.blocks * self.cpb

    def on_block(self, mu, addr, size, _):
        self.blocks += 1
        if self.stall and self.t() >= self.next_hblank:
            self.next_hblank = (self.t() // 1232 + 1) * 1232 + 960
            if any(struct.unpack("<H", bytes(mu.mem_read(0x040000BA + 12 * k, 2)))[0] & 0xB000 == 0xA000
                   for k in range(4)):
                self.blocks += max(1, self.stall // self.cpb)        # the bus taken: time passes, the CPU stands still
                self.stalls += 1

    def on_siocnt(self, mu, access, addr, size, value, _):
        if size < 2 or self.rcnt & 0x8000 or value & 0x3083 != 0x2083 or self.in_transfer:
            return
        t = self.t()
        w = struct.unpack("<H", bytes(mu.mem_read(0x0400012A, 2)))[0]
        s0 = t + self.hw_lead
        self.in_transfer, self.t_start = True, t
        self.sd_edges = [(t, None), (s0, 0)] + [(s0 + (i + 1) * BIT, w >> i & 1) for i in range(16)] + \
            [(s0 + 17 * BIT, 1), (s0 + 18 * BIT, None)]
        self.hw_end = s0 + 18 * BIT
        self.t_so_low = self.hw_end
        self.game_t0 = self.hw_end + self.delay * BIT
        self.hw_busy_until = self.hw_end + 24 * BIT
        self.hw_sends += 1
        self.hw_word1 = None
        mu.mem_write(0x04000120, b"\xff" * 8)                 # (SIOMULTI0-3: 0xFFFF from the start)

    def on_siomulti_read(self, mu, access, addr, size, value, _):
        # (16 November, hardware: the game's word was in SIOMULTI1 as soon as the DUO looked, just after
        # the game's stop bit, though the transfer was still running - so the hardware latches each word
        # as it ends)
        if not self.rcnt & 0x8000 and self.hw_end is not None and self.in_transfer:
            t = self.t()
            w0 = struct.unpack("<H", bytes(mu.mem_read(0x0400012A, 2)))[0]
            w1 = self.game_word if self.game_t0 is not None and t >= self.game_t0 + 17.5 * BIT else 0xFFFF
            mu.mem_write(0x04000120, struct.pack("<2H", w0 if t >= self.hw_end else 0xFFFF, w1))
            if w1 != 0xFFFF and self.hw_stuck is None:
                self.hw_stuck = w1
        elif self.hw_end is not None and self.rcnt & 0x8000 and self.hw_word1 is not None:
            # (16 November, evening, hardware: read after the DUO took the pins, SIOMULTI1 gave the game's
            # handshake every time, 3476 in a row, long after the game had linked - stale. Read just after
            # the game's stop bit, before the pins are taken, it was right: 3693 of 3693)
            mu.mem_write(0x04000122, struct.pack("<H", self.hw_stuck if self.hw_stuck is not None else 0xFFFF))

    def on_siocnt_read(self, mu, access, addr, size, value, _):
        t = self.t()
        if t >= self.hw_busy_until and self.in_transfer and not self.rcnt & 0x8000 and self.hw_end is not None:
            self.in_transfer = False                         # the hardware's own end: its timeout over
            self.end_transfer(self.hw_busy_until)
            mu.mem_write(0x04000120, struct.pack("<4H", *self.transfers[-1]))
        mu.mem_write(0x04000128, struct.pack("<H", 0x2003 | (0x80 if t < self.hw_busy_until else 0) | 8))

    def game_level(self, t):
        """SD as the game drives it at time t: its word's bits, or None (not driving)."""
        if self.game_t0 is None or t < self.game_t0:
            return None
        k = int((t - self.game_t0) / BIT)
        if k == 0:
            return 0
        if 1 <= k <= 16:
            return self.game_word >> (k - 1) & 1
        if k == 17:
            return 1
        return None

    def sd(self, t):
        g = self.game_level(t)
        if not self.rcnt & 0x8000 and self.in_transfer and self.hw_end is not None and t < self.hw_end:
            return self.level_at(t)                          # (the hardware's word)
        if self.duo_driving:
            if g is not None:
                self.errors.append(f"both GBAs drive SD at {t}")
            return self.rcnt >> 1 & 1
        return 1 if g is None else g

    def on_read(self, mu, access, addr, size, value, _):
        t = self.t()
        if addr in (TM0, TM0 + 1):
            mu.mem_write(TM0, struct.pack("<H", int(t) & 0xFFFF))
        elif addr in (VCOUNT, VCOUNT + 1):
            mu.mem_write(VCOUNT, struct.pack("<H", int(t // 1232) % 228))
        else:
            level = self.sd(t)
            if self.garble and self.game_t0 is not None and not self.duo_driving:
                if self.game_t0 not in self.garbled_t0:
                    self.garbled_t0[self.game_t0] = self.rng.random() < self.garble
                if self.garbled_t0[self.game_t0] and int((t - self.game_t0) / BIT) == 6:
                    level ^= 1
            v = self.rcnt & ~(P_SD | P_SI) | (P_SD if level else 0)    # (the master's SI: low)
            if not self.rcnt & 0x8000 and self.in_transfer and self.hw_end is not None:
                v = v & ~(P_SO | P_SC) | (P_SO if t < self.hw_end else 0)    # (the hardware's SC and SO)
            if getattr(self, "si_high", False):                          # (the DUO on the cable's other end)
                v |= P_SI
            mu.mem_write(RCNT, struct.pack("<H", v))

    def on_write(self, mu, access, addr, size, value, _):
        if addr != RCNT or size < 2:
            return
        t, old, v = self.t(), self.rcnt, value & 0xFFFF
        if v & 0x8000 and not old & 0x8000 and self.in_transfer and self.hw_end is not None:
            done = self.game_t0 is not None and t >= self.game_t0 + 17.5 * BIT   # (the pins taken: what's latched stays)
            self.hw_word1 = self.game_word if done else 0xFFFF
        self.rcnt = v
        if not v & 0x8000:
            return
        driving = bool(v & (P_SD << 4))
        level = v >> 1 & 1 if driving else None
        if driving != self.duo_driving or (driving and (old >> 1 & 1) != level):
            self.sd_edges.append((t, level))
        self.duo_driving = driving
        sc = v & P_SC if v & (P_SC << 4) else 1
        so = v & P_SO if v & (P_SO << 4) else 1
        if not sc and not self.in_transfer:
            self.in_transfer, self.t_start, self.sd_edges = True, t, [(t, level)]   # (a start bit with SC: kept)
            self.t_so_low, self.game_t0 = None, None
        if self.in_transfer and not so and self.t_so_low is None:
            self.t_so_low = t
            self.game_t0 = t + self.delay * BIT          # the game's start bit, its turn given
            if self.silent_lead is not None:
                first = next((et for et, el in self.sd_edges if el == 0), None)
                if first is None or first - self.t_start > self.silent_lead:
                    self.game_t0 = None                      # the game never saw a word it could take: quiet
        if self.in_transfer and sc:
            self.in_transfer = False
            self.end_transfer(t)

    def level_at(self, t):
        """SD at time t from the DUO's recorded edges and the game's word."""
        lvl = None
        for et, el in self.sd_edges:
            if et > t:
                break
            lvl = el
        g = self.game_level(t)
        if lvl is None:
            return 1 if g is None else g
        return lvl

    def end_transfer(self, t_end):
        words, t = [], self.t_start
        for slot in range(4):
            start = None
            limit = t + self.window * BIT if slot >= 2 else t + 40 * BIT   # (slot 1 is the game's own word)
            probe = t
            while probe < min(limit, t_end):
                if self.level_at(probe) == 0:
                    start = probe
                    break
                probe += BIT / 16
            if slot == 0 and start is not None:
                self.lead0 = start - self.t_start
                self.leads.add(round(self.lead0))
            if start is None:
                words += [0xFFFF] * (4 - slot)
                break
            w = 0
            for i in range(16):
                if self.level_at(start + (i + 1.5) * BIT):
                    w |= 1 << i
            if slot >= 2:
                d = start - t
                self.gaps.add(round(d))
                if self.gap_window and not self.gap_window[0] <= d <= self.gap_window[1]:
                    w = 0x1234                               # garbage
            if not self.level_at(start + 17.5 * BIT):
                self.errors.append(f"slot {slot}: no stop bit")
            words.append(w)
            t = start + 18 * BIT
        self.transfers.append(words)
        self.on_words(words)

    # ------------------------------------------------------------ the game's link layer (link.c)
    def on_words(self, w):
        if not self.linked:
            if w[0] == MASTER_HS and self.miss_master > 0:
                self.miss_master -= 1
                w = [0x8FFE] + list(w[1:])                  # misread: not a handshake word, so no players
            elif w[0] == MASTER_HS and self.lead_window and not self.lead_window[0] <= self.lead0 <= self.lead_window[1]:
                w = [0x8FFE] + list(w[1:])
            n = 0
            for x in w:
                if (x & ~3) == SLAVE_HS or x == MASTER_HS:
                    n += 1
                else:
                    if x != 0xFFFF:                     # (DoHandshake: a slot that's neither counts no one at all)
                        n = 0
                    break
            if n > 1 and n == self.prev_count and w[0] == MASTER_HS:
                self.linked, self.player_count = True, n
                self.result["handshake_players"] = n
                self.send_idx, self.recv_idx, self.checksum_ready = 0, 0, False
                # DoHandshake loaded SIOMLT_SEND with the handshake before it decided: the next
                # transfer still carries it (pret link.c; 15 November, the hardware's ~1000 retries)
                self.game_word = SLAVE_HS
                return
            self.prev_count = n
            self.game_word = SLAVE_HS | 1
            return
        if self.send_idx == 0:                           # DoRecv: the checksum slot
            if self.checksum_ready and any(w[i] != self.checksum for i in range(self.player_count)):
                self.result["checksum_errors"] += 1
            self.checksum, self.checksum_ready = 0, True
        else:
            for i in range(self.player_count):
                self.frame[self.recv_idx][i] = w[i]
                self.checksum = (self.checksum + w[i]) & 0xFFFF
            self.recv_idx += 1
            if self.recv_idx == 8:
                self.command()
                self.recv_idx = 0
        if self.send_idx == 8:                           # DoSend
            self.game_word, self.send_idx = self.checksum, 0
        else:
            if self.send_idx == 0:
                idle = [0xCAFE, 17] + [0] * 6 if self.in_room else [0] * 8   # (in the room: its keys every frame)
                self.current = self.queue.pop(0) if self.queue else idle
            self.game_word = self.current[self.send_idx]
            self.send_idx += 1

    def send(self, *words):
        self.queue.append(list(words) + [0] * (8 - len(words)))

    def command(self):
        # the Trade Center after the link players (16 November, hardware: the control's link error): the
        # leader asks for the trainer cards (0xCCCC 2) and every player sends one (100 bytes); with all of
        # them in, both go into the room and send keys every frame (0xCAFE). A leader that never asks:
        # the game gives up (a link error) - as the real one did
        if self.result["refused"] is False and not self.in_room and "link_error" not in self.result:
            self.after_players += 1
            if self.after_players > self.patience and not self.cards_asked:
                self.result["link_error"] = "the leader never asked for the trainer cards"
        for i in range(self.player_count):
            c = self.frame[0][i]
            if c == 0xCCCC and i == 0:
                self.cards_asked = True
                size = {2: 100, 3: 220, 4: 40}.get(self.frame[1][i], 200)
                self.send(0xBBBB, size, 1 + 128)
                for at in range(0, size, 14):
                    self.send(0x8888)
            elif c == 0xCAFE and i != 1:
                self.result["room_keys"] = self.result.get("room_keys", 0) + 1
            if c == 0x2222:
                block = bytearray(self.lp)
                if not any(block):                      # (as the real one, 16 November: the markers, link type 0x1133)
                    block[0:14] = block[44:58] = b"GameFreak inc."
                    block[16 + 0x14:16 + 0x16] = (0x1133).to_bytes(2, "little")
                    block[16 + 0x1A] = 2
                block[16] = self.version
                self.send(0xBBBB, 60, 1 + 128)
                for at in range(0, 60, 14):
                    chunk = bytes(block[at:at + 14]).ljust(14, b"\0")
                    self.send(0x8888, *[chunk[j] | chunk[j + 1] << 8 for j in range(0, 14, 2)])
            elif c == 0xBBBB:
                self.rx[i] = [self.frame[1][i], bytearray()]
            elif c == 0x8888 and i in self.rx:
                size, data = self.rx[i]
                for j in range(1, 8):
                    data += self.frame[j][i].to_bytes(2, "little")
                if len(data) >= size:
                    del self.rx[i]
                    if size == 100 and i != 1 and self.cards_asked:
                        self.cards_from.add(i)
                        if len(self.cards_from) == self.player_count - 1:
                            self.in_room = True
                            self.result["room"] = True
                    if size == 60 and i != 1:
                        self.result["link_players"][i] = bytes(data[:60])
                        if len(self.result["link_players"]) == self.player_count - 1 and self.result["refused"] is None:
                            self.result["refused"] = self.player_count > self.max_players
                            if self.result["refused"]:
                                self.send(0x5FFF)               # (WRONG_NUM_PLAYERS: SetCloseLinkCallback)
            elif c == 0x5FFF and i != 1:
                self.result["closed"] = True


SIOCNT, SIOMULTI1 = 0x04000128, 0x04000122


class SioHardwareMaster:
    """The scope (16 November), for the simulator: the DUO's own multi-player hardware as master, as
    far as the program sees it - SIOCNT busy from the start until the game's word is in and the
    master's timeout after it, SD showing the master's word (a start bit `lead` cycles after the start,
    16 bits from the lowest, a stop bit) and then the game's, `child_delay` cycles after the master's
    stop bit. The game answers its handshake and, from transfer `takes_at` on, link data (0)."""
    def __init__(self, hw, clock, lead=20, child_delay=90, takes_at=5, timeout=3 * BIT):
        self.hw, self.clock, self.lead, self.child_delay = hw, clock, lead, child_delay
        self.takes_at, self.timeout, self.n, self.t0, self.busy = takes_at, timeout, 0, None, False
        hw.mu.hook_add(UC_HOOK_MEM_WRITE, self.on_write, begin=SIOCNT, end=SIOCNT + 1)
        hw.mu.hook_add(UC_HOOK_MEM_READ, self.on_read, begin=SIOCNT, end=SIOCNT + 1)

    def word(self):
        return SLAVE_HS if self.n <= self.takes_at else 0

    def on_write(self, mu, access, addr, size, value, _):
        if value & 0x80 and value & 0x3000 == 0x2000 and not self.busy:
            self.busy, self.t0, self.n = True, self.clock.t(), self.n + 1
            mu.mem_write(SIOMULTI1, struct.pack("<H", self.word()))

    def level(self, t, start, w):
        k = int((t - start) / BIT)
        return None if t < start or k > 17 else 0 if k == 0 else 1 if k == 17 else w >> (k - 1) & 1

    def on_read(self, mu, access, addr, size, value, _):
        v = 0x2003
        if self.busy:
            t = self.clock.t() - self.t0
            child = self.lead + 18 * BIT + self.child_delay
            if t >= child + 18 * BIT + self.timeout:
                self.busy = False
            else:
                v |= 0x80
            sd = self.level(t, self.lead, MASTER_HS)
            if sd is None:
                sd = self.level(t, child, self.word())
            v |= 8 if sd is None or sd else 0
        else:
            v |= 8
        mu.mem_write(SIOCNT, struct.pack("<H", v))
