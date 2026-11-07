"""A Pokemon Ruby/Sapphire battling in a Cable Club Colosseum, over the GBA link cable
(docs/BATTLE.md). Written for this project from pret/pokeruby (cable_club.c, battle_main.c
CB2_HandleStartBattle, battle_controllers.c, battle_controller_link_opponent.c, link.c,
data/scripts/cable_club.inc, the Colosseum's map and layout). Like trade_game_model.py it is a
generator driven by hwsim's multi-player link model, and it plays one player through:

  1. the Cable Club (0x2233 single, 0x2244 double): link players, the trainer cards (0xCCCC 2),
     then the same link carries on into the Colosseum (SingleBattleColosseum for both): the
     fade-in's 0x2FFE, lockstep room keys, walking to a spot ((3,5) or (10,5)) and waiting (22) until
     both are seated; sub_808382C then stops the keys, waits and closes the link;
  2. the battle's link (0x2211): link players; each side's header (signature, fit Pokemon, Enigma
     Berry), who runs the battle (CB2_HandleStartBattle case 1, ported as it is); the parties, two
     Pokemon a block, each turn once both blocks of the last are in; then a battle engine as the
     master runs it, at the level of its controller commands: every command goes to everyone as
     a block (struct LinkBattleCommunicationHeader + data); the GBA whose battler it is answers
     (state 1) where the command asks for something; every GBA reports "done" (state 2, its
     multiplayer ID) and the engine waits for all of them. The fighting itself is a stand-in (each
     hit takes a fixed share of the target's HP): enough for faints, a switch-in and an end. Then
     CONTROLLER_ENDLINKBATTLE, and the link closes;
  3. the Colosseum again (the attendant's link type, sub_8083664): the same partner as before
     (sub_800826C), everyone standing on their spot; someone walks out of the door (23).

This game must run the battle (the DUO only plays a follower): if the partner's header would make
the partner the master, that is an error here. What the partner sends is checked as the game would
use it: a "done" with the wrong ID, an answer for a battler that isn't the partner's, a move slot
with no move or no PP, a fainted Pokemon sent in, and so on.
"""
import struct
from link_game_model import LinkError, LANG_ENGLISH
from trade_game_model import (RubyTrade, Room, BLOCK_REQUEST_SIZES, KEY_NONE, KEY_DOWN, KEY_UP, KEY_LEFT, KEY_RIGHT,
                              KEY_SEATED, KEY_EXIT, STEP_FRAMES, DIRS, PK3_ORDERS)

LT_SINGLE, LT_DOUBLE, LT_BATTLE = 0x2233, 0x2244, 0x2211
# The Colosseum (layout SingleBattleColosseum, 14 x 9): '#' blocked, 'A' the attendant.
ROOM = ["##############",
        "##############",
        "##############",
        "#........A...#",
        "#............#",
        "#............#",
        "#............#",
        "#............#",
        "######..######"]
SPOTS = {(3, 5): 0, (10, 5): 1}                       # coordinate triggers, VAR_0x8005 = 0 / 1
SPAWN = {0: (6, 8), 1: (7, 8)}
DOOR = {(6, 8), (7, 8)}

# controller commands (battle_controllers.h)
GETMONDATA, SETMONDATA, SWITCHINANIM, DRAWTRAINERPIC, FAINTANIMATION, MOVEANIMATION, PRINTSTRING = 0, 2, 5, 7, 10, 15, 16
REQUEST_HP_BATTLE = 42
CHOOSEACTION, CHOOSEMOVE, CHOOSEPOKEMON, HEALTHBARUPDATE = 18, 20, 22, 24
TWORETURNVALUES, CHOSENMONRETURNVALUE = 33, 34
INTROSLIDE, INTROTRAINERBALLTHROW, ENDLINKBATTLE = 46, 47, 55
ASKS = {CHOOSEACTION, CHOOSEMOVE, CHOOSEPOKEMON}       # commands whose battler's GBA answers (state 1)
B_OUTCOME_WON, B_OUTCOME_LOST = 1, 2


def battle_block(state, battler, data, attacker=0, target=0, absent=0, effect=0):
    """PrepareBufferDataTransferLink: the header, then the data in a size rounded up past a multiple of 4."""
    size = len(data) - len(data) % 4 + 4
    head = bytes([state, battler, attacker, target]) + struct.pack("<H", size) + bytes([absent, effect])
    return head + bytes(data).ljust(size, b"\0")


def mon_battle_fields(mon):
    """(species, moves, PP, HP, max HP) of a party Pokemon in the game's form."""
    pid, otid = struct.unpack_from("<II", mon, 0)
    plain = struct.pack("<12I", *[w ^ pid ^ otid for w in struct.unpack_from("<12I", mon, 0x20)])
    order = PK3_ORDERS[pid % 24]
    g = plain[12 * order.index("G"):][:12]
    a = plain[12 * order.index("A"):][:12]
    hp, max_hp = struct.unpack_from("<HH", mon, 0x56)
    return dict(species=struct.unpack_from("<H", g, 0)[0], moves=list(struct.unpack_from("<4H", a, 0)),
                pp=list(a[8:12]), hp=hp, max_hp=max_hp)


class ColosseumRoom(Room):
    """Room (trade_game_model) with the Colosseum's walls, spots and door; the attendant blocks."""
    def __init__(self):
        super().__init__()
        self.pos, self.prev = dict(SPAWN), dict(SPAWN)
        self.bad_seat = None

    def back_from_trade(self):
        """overworld.c sub_805465C (the way back from a battle too): standing again on the spots,
        whose scripts don't run again until the player has stepped off."""
        super().back_from_trade()
        self.on_seat_already = set(w for w in (0, 1) if self.pos[w] in SPOTS)

    def blocked(self, who, x, y):
        if not (0 <= y < len(ROOM) and 0 <= x < len(ROOM[0])) or ROOM[y][x] != ".":
            return True
        other = 1 - who
        return (x, y) in (self.pos[other], self.prev[other])

    def apply(self, keys):
        for who in (0, 1):
            k = keys[who]
            if self.status[who] == 0x80 and 0x83 in self.status.values():
                self.status[who] = 0x81
            if self.status[who] == 0x80 and not self.moving[who] and k == KEY_DOWN and \
                    self.pos[who] in DOOR and self.facing[who] == KEY_DOWN:
                self.status[who] = 0x81
                self.asked_to_leave.add(who)
                k = KEY_NONE
            if self.status[who] == 0x80 and not self.moving[who] and self.pos[who] in SPOTS \
                    and who not in getattr(self, "on_seat_already", ()):
                self.status[who] = 0x81
                self.seated_at[who] = self.pos[who]
            if k == KEY_SEATED:
                if self.status[who] != 0x81 or self.pos[who] not in SPOTS:
                    self.bad_seat = (who, self.pos[who], self.status[who])
                self.status[who] = 0x82
            elif k == KEY_EXIT:
                self.status[who] = 0x83
            if self.moving[who]:
                self.moving[who] -= 1
                if not self.moving[who]:
                    self.prev[who] = self.pos[who]
            elif self.status[who] == 0x80 and k in DIRS:
                self.facing[who] = k
                getattr(self, "on_seat_already", set()).discard(who)
                dx, dy = DIRS[k]
                x, y = self.pos[who][0] + dx, self.pos[who][1] + dy
                if not self.blocked(who, x, y):
                    self.prev[who], self.pos[who] = self.pos[who], (x, y)
                    self.moving[who] = STEP_FRAMES

    def step_towards(self, who, goal):
        """The first key of a shortest way to goal around walls and the other player (or None)."""
        start = self.pos[who]
        if start == goal:
            return None
        seen, frontier = {start: None}, [start]
        while frontier:
            nxt = []
            for p in frontier:
                for k, (dx, dy) in DIRS.items():
                    q = (p[0] + dx, p[1] + dy)
                    if q in seen or self.blocked(who, *q):
                        continue
                    seen[q] = (p, k)
                    nxt.append(q)
            frontier = nxt
        if goal not in seen:
            return None
        p = goal
        while seen[p][0] != start:
            p = seen[p][0]
        return seen[p][1]


class RubyColosseum(RubyTrade):
    def __init__(self, master=True, language=LANG_ENGLISH, party=None, double=False, spot=None, duo_wins=False,
                 hit_share=0.6, partner_hit_share=0.35, leaves_first=False, pace=300, frame_blocks=25 * 228, version=2,
                 player=None, game_move=None, answer_delay=0):
        """party: the game's party (100-byte Pokemon, game form); double: a double battle; spot:
        where the player sits ((3,5) or (10,5); default: player 0 left, player 1 right); hit_share:
        the share of a Pokemon's max HP each hit takes from the partner's side, partner_hit_share
        from the game's (the stand-in for the damage calculation)."""
        super().__init__(master=master, language=language, party=party or [bytes(100)], pace=pace,
                         frame_blocks=frame_blocks, version=version, leaves_first=leaves_first)
        self.double = double
        self.room_type = LT_DOUBLE if double else LT_SINGLE
        self.spot = spot or (3, 5) if self.my_id == 0 else spot or (10, 5)
        self.hit_share, self.partner_hit_share = hit_share, partner_hit_share
        self.player = player or (0, b"\x39\x30\x12\x34", b"\xc7\xbb\xd3\xff\xff\xff\xff")
        self.first_players = None
        # game_move(turn, battler) -> the move slot the player chooses (default 0); answer_delay: frames
        # the player takes to choose each time (8 November: the impossible level waits for it)
        self.game_move = game_move or (lambda turn, b: 0)
        self.answer_delay = answer_delay
        self.result.update(partner_voluntary=[], answer_frames=[],
                           partner_header=None, partner_party=None, battle_master=None, commands=0,
                           partner_choices=[], partner_switches=[], partner_dones=0, outcome=None,
                           battled=False, partner_spot=None, game_spot=None, same_partner=None)

    def patch_link_player(self, block):
        gender, tid, name = self.player
        block[16 + 4:16 + 8] = tid
        block[16 + 8:16 + 16] = (bytes(name) + b"\xff")[:8]
        block[16 + 0x10] = gender
        block[16 + 0x18] = SPOTS.get(self.spot, 0) if self.first_players else 0      # id: the spot (sub_8007270)

    def run(self):
        yield ("until_ready",)
        yield from self._session(self.room_type, self._club, max_frames=9000)
        yield from self._session(LT_BATTLE, self._battle, max_frames=40000)
        yield from self._session(self.room_type, self._after, max_frames=8000)
        return self.result

    # ------------------------------------------------------------ 1. the Cable Club and the Colosseum
    def _club(self, s):
        s.stage = "Cable Club: waiting for link players"
        while not s.players_checked:
            yield
        self.first_players = {i: dict(lp) for i, lp in self.link_players.items()}
        s.stage = "Cable Club: trainer cards"
        s.send_buffer = bytes(100)
        if self.master:
            s.link.send(0xCCCC, 2)
        while len(s.blocks_in) < 2:
            yield
        if len(s.blocks_in[self.other]) != BLOCK_REQUEST_SIZES[2]:
            raise LinkError(f"the partner's trainer card was {len(s.blocks_in[self.other])} bytes")
        self.result["partner_card"] = s.blocks_in[self.other]
        s.blocks_in = {}
        s.stage = "Colosseum: warping in"
        for _ in range(90):
            yield
        s.stage = "Colosseum: the room's fade-in (0x2FFE)"
        yield from s.barrier()
        room = self.room = ColosseumRoom()
        wait, sent_seated = 0, False
        s.stage = "Colosseum: walking"
        for frame in range(4000):
            key = KEY_NONE
            if room.status[self.my_id] == 0x81 and not sent_seated:
                key, sent_seated = KEY_SEATED, True
            elif wait:
                wait -= 1
            elif room.status[self.my_id] == 0x80 and not room.moving[self.my_id] and frame > 20:
                k = room.step_towards(self.my_id, self.spot)
                if k is not None:
                    key, wait = k, STEP_FRAMES + 2
            s.link.send(0xCAFE, key)
            keys = s.keys_this_frame()
            if keys is not None:
                room.apply(keys)
                if room.bad_seat:
                    raise LinkError(f"a player sent 'seated' off a spot: {room.bad_seat}")
            yield
            if all(v == 0x82 for v in room.status.values()):
                break
        else:
            raise LinkError(f"the partner never sat down (at {room.pos[self.other]}, status {room.status[self.other]:#x})")
        self.result["partner_spot"] = room.seated_at.get(self.other)
        self.result["game_spot"] = room.seated_at.get(self.my_id)
        if self.result["partner_spot"] == self.result["game_spot"]:
            raise LinkError("both players on the same spot")
        # sub_808382C: the fade, gLinkType = 0x2211, no more room keys, 20 frames, the link closes
        s.stage = "Colosseum: both seated, closing"
        for _ in range(30):
            yield
        s.close()

    # ------------------------------------------------------------ 2. the battle
    def _battle(self, s):
        s.stage = "battle: link players"
        while not s.players_checked:
            yield
        me, other = self.my_id, self.other
        # CB2_HandleStartBattle case 0: the header (versionSignature 0x0101, the fit Pokemon, the berry)
        fit = 0
        for i, mon in enumerate(self.party):
            f = mon_battle_fields(mon) if any(mon) else None
            if f and f["species"] and f["hp"]:
                fit |= 1 << 2 * i
        header = bytes([1, 1]) + struct.pack("<H", fit) + bytes(27)
        s.link.send_block(header)
        s.stage = "battle: headers"
        got = yield from self._blocks(s, 1)
        partner = got[0]
        self.result["partner_header"] = partner
        if len(partner) < 4:
            raise LinkError(f"the partner's header was {len(partner)} bytes")
        sig = {me: 0x0101, other: struct.unpack_from("<H", partner, 0)[0]}
        flags = self._find_master(sig, me)
        self.result["battle_master"] = me if flags == 12 else other
        if flags != 12:
            raise LinkError(f"the partner's header (signature {sig[other]:#06x}) makes the partner run the battle")
        # cases 2-7: the parties, two Pokemon a block
        party = b"".join(self.party).ljust(600, b"\0")
        theirs = b""
        for k in range(3):
            s.stage = f"battle: parties, block {k + 1} of 3"
            s.link.send_block(party[200 * k:200 * k + 200])
            got = yield from self._blocks(s, 1)
            if len(got[0]) != 200:
                raise LinkError(f"the partner's party block was {len(got[0])} bytes")
            theirs += got[0]
        self.result["partner_party"] = theirs
        self.theirs = [theirs[100 * i:100 * i + 100] for i in range(6)]
        self.battle_party = {me: [mon_battle_fields(m) if any(m) else None for m in party_list(party)],
                             other: [mon_battle_fields(m) if any(m) else None for m in self.theirs]}
        for side in (me, other):
            for f in self.battle_party[side]:
                if f is not None and not f["species"]:
                    self.battle_party[side][self.battle_party[side].index(f)] = None
        if not any(self.battle_party[other]):
            raise LinkError("the partner sent no Pokemon")
        # (Task_HandleSendLinkBuffersData waits 100 frames before its first block)
        for _ in range(100):
            yield
        yield from self._engine(s)
        s.stage = "battle: over, closing"
        for _ in range(20):
            yield
        self.result["battled"] = True
        s.close()

    def _find_master(self, sig, me):
        """CB2_HandleStartBattle case 1 (pokeruby): the flags this game takes (12: master, 8: not)."""
        buf = [sig[0], sig[1]]
        if buf[0] == 0x100:
            return 12 if me == 0 else 8
        if buf[0] == buf[1]:
            return 12 if me == 0 else 8
        i = 0
        while i < 2:
            if buf[i] > 0x0101 and i != me:
                break
            i += 1
        return 12 if i == 2 else 8

    def _blocks(self, s, n, frames=900):
        """Wait for n blocks from the partner (each taken as it arrives)."""
        got = []
        for _ in range(frames):
            if self.other in s.blocks_in:
                got.append(s.blocks_in.pop(self.other))
                s.blocks_in.pop(self.my_id, None)
                if len(got) == n:
                    return got
            yield
        raise LinkError(f"waiting for the partner's block ({s.stage})")

    def _battler_side(self, b):
        """Battler b's GBA: the master's are the even ones (InitLinkBtlControllers)."""
        return self.my_id if b % 2 == 0 else self.other

    def _engine(self, s):
        me, other = self.my_id, self.other
        battlers = [0, 1, 2, 3] if self.double else [0, 1]
        party = self.battle_party
        active = {b: (b >> 1) for b in battlers}               # party slots on the field
        for side in (me, other):                               # (a double with one Pokemon: battler 2/3 absent)
            for b in battlers:
                if self._battler_side(b) == side and party[side][active[b]] is None:
                    active[b] = None
        hp = {side: [f["hp"] if f else 0 for f in party[side]] for side in (me, other)}
        self.result["hp"] = hp
        live = lambda b: active[b] is not None and hp[self._battler_side(b)][active[b]] > 0

        s.stage = "battle: the intro"
        yield from self._emit(s, [(b, [GETMONDATA, 0, 0, 0]) for b in battlers])
        yield from self._emit(s, [(0, [INTROSLIDE, 0, 0, 0])])
        yield from self._emit(s, [(b, [DRAWTRAINERPIC, 0, 0, 0]) for b in battlers if b < 2])
        yield from self._emit(s, [(0, [PRINTSTRING, 0, 0, 0])])
        yield from self._emit(s, [(b, [INTROTRAINERBALLTHROW, 0, 0, 0]) for b in battlers if b < 2])
        turn = 0
        while True:
            turn += 1
            if turn > 60:
                raise LinkError("the battle went on for 60 turns")
            s.stage = f"battle: turn {turn}, choosing"
            acting = [b for b in battlers if live(b)]
            self.turn = turn
            # the player's own battlers: CHOOSEACTION, then at once CHOOSEMOVE (each battler goes on by
            # itself in HandleTurnActionSelectionState; the partner's choices don't hold it up)
            self._own_moves = {}
            for b in acting:
                if self._battler_side(b) == me:
                    f = party[me][active[b]]
                    self._own_moves[b] = [CHOOSEMOVE, 0, 0, 0] + list(struct.pack("<4H", *f["moves"])) + f["pp"] + \
                        [35] * 4 + list(struct.pack("<H", f["species"])) + [0, 0]
            answers = yield from self._emit(s, [(b, [CHOOSEACTION, 0, 0, 0]) for b in acting])
            moves = {}
            ask = []
            switching = []
            for b in acting:
                if self._battler_side(b) == me:
                    continue
                r = answers.get(b)
                if r is None or r[0] != TWORETURNVALUES or r[1] not in (0, 2):
                    raise LinkError(f"battler {b}: the partner's action was {r!r}, not 'fight' or 'switch'")
                if r[1] == 2:
                    switching.append(b)
                    continue
                f = party[other][active[b]]
                ask.append((b, [CHOOSEMOVE, 0, 0, 0] + list(struct.pack("<4H", *f["moves"])) + f["pp"] +
                            [35] * 4 + list(struct.pack("<H", f["species"])) + [0, 0]))
            for b in switching:                           # (a switch: which Pokemon, B_ACTION_SWITCH)
                ask.append((b, [CHOOSEPOKEMON, 0, 6, 0, 0, 0, 0, 0]))
            for b in self._own_moves:
                moves[b] = (self.game_move(turn, b), b ^ 1)
            self._own_moves = {}
            answers = yield from self._emit(s, ask) if ask else {}
            for b in switching:
                r = answers.get(b)
                side = other
                on_field = {active[x] for x in battlers if self._battler_side(x) == side}
                bench = [i for i, f in enumerate(party[side]) if f and hp[side][i] > 0 and i not in on_field]
                if r is None or r[0] != CHOSENMONRETURNVALUE or r[1] not in bench:
                    raise LinkError(f"battler {b}: the partner switched to {r!r}, not one of {bench}")
                active[b] = r[1]
                self.result["partner_voluntary"].append((turn, b, r[1]))
                yield from self._emit(s, [(b, [SWITCHINANIM, r[1], 0, 5])])
            ask = [(b, d) for b, d in ask if d[0] == CHOOSEMOVE]
            for b, _ in ask:
                r = answers.get(b)
                if r is None or r[0] != TWORETURNVALUES or r[1] != 10:
                    raise LinkError(f"battler {b}: the partner's move answer was {r!r}")
                slot, target = r[2], r[3]
                f = party[other][active[b]]
                if not (0 <= slot < 4 and f["moves"][slot] and f["pp"][slot]):
                    raise LinkError(f"battler {b}: move slot {slot} has no move or no PP ({f['moves']}, {f['pp']})")
                if self._battler_side(target) != me:
                    raise LinkError(f"battler {b}: aimed at battler {target}, on its own side")
                f["pp"][slot] -= 1
                moves[b] = (slot, target)
                self.result["partner_choices"].append((turn, b, slot, target))
            s.stage = f"battle: turn {turn}, moves"
            for b in sorted(moves, key=lambda x: (self._battler_side(x) != me, x)):   # (the game first)
                if not live(b):
                    continue
                slot, target = moves[b]
                if not live(target):                           # (a double: the other foe instead)
                    target = next((t for t in battlers if self._battler_side(t) != self._battler_side(b) and live(t)), None)
                    if target is None:
                        continue
                move = party[self._battler_side(b)][active[b]]["moves"][slot]
                yield from self._emit(s, [(b, [MOVEANIMATION] + list(struct.pack("<H", move)) + [1, 0, 0])],
                                      attacker=b, target=target)
                side, idx = self._battler_side(target), active[target]
                share = self.hit_share if side == other else self.partner_hit_share
                f = party[side][idx]
                dmg = min(hp[side][idx], max(1, int(f["max_hp"] * share + 0.999)))
                hp[side][idx] -= dmg
                # Cmd_healthbarupdate (the damage), then Cmd_datahpupdate (the new HP, REQUEST_HP_BATTLE)
                yield from self._emit(s, [(target, [HEALTHBARUPDATE, 0] + list(struct.pack("<h", dmg)))],
                                      attacker=b, target=target)
                yield from self._emit(s, [(target, [SETMONDATA, REQUEST_HP_BATTLE, 0] + list(struct.pack("<H", hp[side][idx])))],
                                      attacker=b, target=target)
                yield from self._emit(s, [(b, [PRINTSTRING, 0, 0, 0])], attacker=b, target=target)
                if hp[side][idx] == 0:
                    yield from self._emit(s, [(target, [FAINTANIMATION] * 4)], attacker=b, target=target)
            # replacements, or the end
            for b in battlers:
                if active[b] is None or live(b):
                    continue
                side = self._battler_side(b)
                on_field = {active[x] for x in battlers if self._battler_side(x) == side}
                bench = [i for i, f in enumerate(party[side]) if f and hp[side][i] > 0 and i not in on_field]
                if not bench:
                    active[b] = None
                    continue
                s.stage = f"battle: turn {turn}, battler {b} chooses a Pokemon"
                answers = yield from self._emit(s, [(b, [CHOOSEPOKEMON, 0, 6, 0, 0, 0, 0, 0])])
                if side == me:
                    pick = bench[0]
                else:
                    r = answers.get(b)
                    if r is None or r[0] != CHOSENMONRETURNVALUE:
                        raise LinkError(f"battler {b}: the partner's Pokemon answer was {r!r}")
                    pick = r[1]
                    if pick not in bench:
                        raise LinkError(f"battler {b}: the partner sent in slot {pick}, not one of {bench}")
                    self.result["partner_switches"].append((turn, b, pick))
                active[b] = pick
                yield from self._emit(s, [(b, [SWITCHINANIM, pick, 0, 5])])
            alive = {side: any(active[b] is not None and live(b) for b in battlers if self._battler_side(b) == side)
                     for side in (me, other)}
            if alive[me] and alive[other]:
                continue
            outcome = B_OUTCOME_WON if alive[me] else B_OUTCOME_LOST
            self.result["outcome"] = outcome
            s.stage = "battle: the end"
            yield from self._emit(s, [(b, [ENDLINKBATTLE, outcome, 0, 0]) for b in battlers])
            return

    def _emit(self, s, cmds, attacker=0, target=0, frames=900):
        """Send these commands (as the engine does, each marked for every player) and wait until
        every GBA has reported each done; the answers (state 1) from the partner, by battler."""
        me, other = self.my_id, self.other
        pending, own = {}, []
        for b, data in cmds:
            s.link.send_block(battle_block(0, b, bytes(data), attacker, target))
            pending[b] = dict(cmd=data[0], answer=None, done=False, need=1, dones=0)
            self.result["commands"] += 1
            if self._battler_side(b) == me and data[0] in ASKS:   # the game's own controller answers (the player)
                if data[0] == CHOOSEMOVE:
                    ans = [TWORETURNVALUES, 10, self.game_move(getattr(self, "turn", 0), b), b ^ 1]
                elif data[0] == CHOOSEPOKEMON:
                    ans = [CHOSENMONRETURNVALUE, 0, 0, 0, 0]
                else:
                    ans = [TWORETURNVALUES, 0, 0, 0]
                own.append((b, ans))
            else:
                s.link.send_block(battle_block(2, b, bytes([me, 0, 0, 0])))
        for k in range(frames + 2 * self.answer_delay):
            if own and k >= (self.answer_delay if any(pending[b]["cmd"] in (CHOOSEACTION, CHOOSEMOVE) for b, _ in own) else 0):
                for b, ans in own:                       # (the player has chosen)
                    s.link.send_block(battle_block(1, b, bytes(ans)))
                    s.link.send_block(battle_block(2, b, bytes([me, 0, 0, 0])))
                    self.result["answer_frames"].append(("game", b, pending[b]["cmd"], self.result["commands"], k))
                    move_cmd = getattr(self, "_own_moves", {}).get(b) if pending[b]["cmd"] == CHOOSEACTION else None
                    if move_cmd:                         # (fight: its move next, straight away)
                        pending[b]["need"] += 1          # (everyone reports done to that one too)
                        pending[b]["done"] = False
                        s.link.send_block(battle_block(0, b, bytes(move_cmd)))
                        self.result["commands"] += 1
                        slot = self.game_move(getattr(self, "turn", 0), b)
                        s.link.send_block(battle_block(1, b, bytes([TWORETURNVALUES, 10, slot, b ^ 1])))
                        s.link.send_block(battle_block(2, b, bytes([me, 0, 0, 0])))
                        self.result["answer_frames"].append(("game", b, CHOOSEMOVE, self.result["commands"], k))
                own = []
            blk = s.blocks_in.pop(other, None)
            s.blocks_in.pop(me, None)
            if blk is not None:
                if len(blk) < 8:
                    raise LinkError(f"a battle block of {len(blk)} bytes")
                state, b = blk[0], blk[1]
                size = blk[4] | blk[5] << 8
                if len(blk) != 8 + size:
                    raise LinkError(f"a battle block of {len(blk)} bytes says its data is {size}")
                p = pending.get(b)
                if state == 0:
                    raise LinkError("the partner sent a controller command (only the master's engine does)")
                if p is None or p["done"]:
                    raise LinkError(f"the partner sent state {state} for battler {b}, with no command outstanding for it")
                if state == 1:
                    if self._battler_side(b) != other:
                        raise LinkError(f"the partner answered (state 1) for battler {b}, the game's own")
                    if p["cmd"] not in ASKS:
                        raise LinkError(f"the partner answered command {p['cmd']} (battler {b}), which asks for nothing")
                    if p["answer"] is not None:
                        raise LinkError(f"two answers for battler {b}'s command {p['cmd']}")
                    p["answer"] = list(blk[8:8 + size])
                    self.result["answer_frames"].append(("partner", b, p["cmd"], self.result["commands"], k))
                elif state == 2:
                    if blk[8] != other:
                        raise LinkError(f"the partner's done carried player {blk[8]}, not its own ({other})")
                    if self._battler_side(b) == other and p["cmd"] in ASKS and p["answer"] is None:
                        raise LinkError(f"the partner said done to command {p['cmd']} (battler {b}) without answering")
                    p["dones"] += 1
                    p["done"] = p["dones"] >= p["need"]
                    self.result["partner_dones"] += 1
                else:
                    raise LinkError(f"a battle block with state {state}")
            if not own and all(p["done"] for p in pending.values()):
                return {b: p["answer"] for b, p in pending.items()}
            yield
        raise LinkError(f"waiting for the partner's done ({s.stage}: {pending})")

    # ------------------------------------------------------------ 3. the Colosseum again
    def _after(self, s):
        s.stage = "back in the Colosseum: link players"
        waited = 0
        while not s.players_checked:
            waited += 1
            if waited > 300:
                raise LinkError("back in the Colosseum, no link players within 300 frames: link error")
            yield
        before, now = self.first_players[self.other], self.link_players[self.other]
        same = before["trainer_id"] == now["trainer_id"] and before["name"][:7] == now["name"][:7]
        self.result["same_partner"] = same
        if not same:
            raise LinkError("sub_800826C: a different partner after the battle: link error")
        room = self.room
        room.back_from_trade()
        left_at, wait, told, exit_at = {}, 0, False, None
        s.stage = "back in the Colosseum"
        for frame in range(4000):
            key = KEY_NONE
            if room.status[self.my_id] == 0x81 and exit_at is None:
                exit_at = frame + 40
            if exit_at is not None and frame == exit_at:
                key = KEY_EXIT
            elif exit_at is None and self.leaves_first:
                if wait:
                    wait -= 1
                elif not room.moving[self.my_id] and room.status[self.my_id] == 0x80:
                    if room.pos[self.my_id] in DOOR:
                        if not told:
                            key, told = KEY_DOWN, True
                    else:
                        goal = min(DOOR, key=lambda d: abs(d[0] - room.pos[self.my_id][0]))
                        k = room.step_towards(self.my_id, goal)
                        if k is not None:
                            key, wait = k, STEP_FRAMES + 2
            s.link.send(0xCAFE, key)
            keys = s.keys_this_frame()
            if keys is not None:
                room.apply(keys)
                for w in (0, 1):
                    if room.status[w] == 0x83:
                        left_at.setdefault(w, frame)
            if all(v == 0x83 for v in room.status.values()):
                self.result["left_room"] = True
                self.result["partner_left_by_door"] = room.pos[self.other] in DOOR
                s.stage = "leaving: closing the link"
                s.close()
                return
            yield
        raise LinkError(f"nobody left the Colosseum (partner at {room.pos[self.other]}, status {room.status[self.other]:#x})")


def party_list(party):
    return [party[100 * i:100 * i + 100] for i in range(6)]
