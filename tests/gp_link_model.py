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
takes `max_players`, a refusal and close if more joined."""
import struct
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_BLOCK

BIT = 16777216 / 115200                  # CPU cycles a bit at 115,200 baud
MASTER_HS, SLAVE_HS = 0x8FFF, 0xB9A0
RCNT, TM0, VCOUNT = 0x04000134, 0x04000100, 0x04000006
P_SC, P_SD, P_SI, P_SO = 1, 2, 4, 8


class GpLinkGame:
    def __init__(self, hw, cycles_per_block=20, delay_bits=0.5, window=3.0, max_players=2, game_version=2,
                 link_player=None, garble=0.0):
        self.hw, self.cpb = hw, cycles_per_block
        self.delay, self.window, self.max_players = delay_bits, window, max_players
        self.version = game_version
        self.blocks = 0
        self.rcnt = 0
        self.sd_edges = []                    # (t, level) of the SD line, as driven by the DUO
        self.duo_driving = False
        self.in_transfer, self.t_start, self.t_so_low = False, 0, None
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
        hw.mu.hook_add(UC_HOOK_BLOCK, self.on_block)
        hw.mu.hook_add(UC_HOOK_MEM_WRITE, self.on_write, begin=RCNT, end=RCNT + 1)
        hw.mu.hook_add(UC_HOOK_MEM_READ, self.on_read, begin=RCNT, end=RCNT + 1)
        hw.mu.hook_add(UC_HOOK_MEM_READ, self.on_read, begin=TM0, end=TM0 + 1)
        hw.mu.hook_add(UC_HOOK_MEM_READ, self.on_read, begin=VCOUNT, end=VCOUNT + 1)

    # ------------------------------------------------------------ the lines
    def t(self):
        return self.blocks * self.cpb

    def on_block(self, mu, addr, size, _):
        self.blocks += 1

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
            mu.mem_write(RCNT, struct.pack("<H", v))

    def on_write(self, mu, access, addr, size, value, _):
        if addr != RCNT or size < 2:
            return
        t, old, v = self.t(), self.rcnt, value & 0xFFFF
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
            self.in_transfer, self.t_start, self.sd_edges = True, t, [(t, None)]
            self.t_so_low, self.game_t0 = None, None
        if self.in_transfer and not so and self.t_so_low is None:
            self.t_so_low = t
            self.game_t0 = t + self.delay * BIT          # the game's start bit, its turn given
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
            if start is None:
                words += [0xFFFF] * (4 - slot)
                break
            w = 0
            for i in range(16):
                if self.level_at(start + (i + 1.5) * BIT):
                    w |= 1 << i
            if not self.level_at(start + 17.5 * BIT):
                self.errors.append(f"slot {slot}: no stop bit")
            words.append(w)
            t = start + 18 * BIT
        self.transfers.append(words)
        self.on_words(words)

    # ------------------------------------------------------------ the game's link layer (link.c)
    def on_words(self, w):
        if not self.linked:
            n = 0
            for x in w:
                if (x & ~3) == SLAVE_HS or x == MASTER_HS:
                    n += 1
                else:
                    break
            if n > 1 and n == self.prev_count and w[0] == MASTER_HS:
                self.linked, self.player_count = True, n
                self.result["handshake_players"] = n
                self.send_idx, self.recv_idx, self.checksum_ready = 0, 0, False
                self.game_word = 0
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
                self.current = self.queue.pop(0) if self.queue else [0] * 8
            self.game_word = self.current[self.send_idx]
            self.send_idx += 1

    def send(self, *words):
        self.queue.append(list(words) + [0] * (8 - len(words)))

    def command(self):
        for i in range(self.player_count):
            c = self.frame[0][i]
            if c == 0x2222:
                block = bytearray(self.lp)
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
                    if size == 60 and i != 1:
                        self.result["link_players"][i] = bytes(data[:60])
                        if len(self.result["link_players"]) == self.player_count - 1 and self.result["refused"] is None:
                            self.result["refused"] = self.player_count > self.max_players
                            if self.result["refused"]:
                                self.send(0x5FFF)               # (WRONG_NUM_PLAYERS: SetCloseLinkCallback)
            elif c == 0x5FFF and i != 1:
                self.result["closed"] = True
