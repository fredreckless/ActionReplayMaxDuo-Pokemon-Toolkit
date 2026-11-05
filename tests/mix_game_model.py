"""A Pokemon Ruby/Sapphire mixing records in a Cable Club Record Corner, over the GBA link cable
(docs/RECORD_MIXING.md). Written for this project from pret/pokeruby (cable_club.c, overworld.c,
record_mixing.c, secret_base.c, data/scripts/cable_club.inc, the Record Corner's map and layout). Like
trade_game_model.py it is a generator driven by hwsim's multi-player link model, and it plays one
player through:

  1. the Cable Club (link type 0x3311): link players, the trainer cards (0xCCCC 2), then the same
     link carries on into the Record Corner: lockstep, one 0xCAFE key a frame from each player,
     walking to a seat and waiting (key 22) until both are seated;
  2. Task_RecordMixing_Main on that same link: the room keys stop, 20 + 60 frames, then 24 rounds of
     200 bytes (the master asks with 0xCCCC 1; each game copies its next chunk the frame after a
     round completes); then the merge (ReceiveSecretBasesData and the gift item), the save, and
     the link closes;
  3. the room again (0x3322, sub_8083664): everyone still "seated" (0x82) until they send 26; the
     player gets up, and someone walks out of the door (23), the other follows.

The game is either end of the cable. The merge is ported here on its own from secret_base.c
(sub_80BD610 and what it calls), independently of the tool's copy in secret_bases.py, so the two
check each other. `result` says what the game ended up with.
"""
import struct
from link_game_model import LinkError, LANG_ENGLISH, LANG_JAPANESE
from trade_game_model import (RubyTrade, BLOCK_REQUEST_SIZES, KEY_NONE, KEY_DOWN, KEY_UP, KEY_LEFT, KEY_RIGHT,
                              KEY_SEATED, KEY_EXIT, KEY_FREE, KEY_UNSEAT, STEP_FRAMES, DIRS)

LT_MIX, LT_AFTER = 0x3311, 0x3322
RECORD_SIZE = 0x1230                                  # struct PlayerRecords (pokeruby record_mixing.c)
CHUNK, ROUNDS = 200, 24
BASE_SIZE, BASES = 160, 20
TV_AT, NEWS_AT, OLDMAN_AT, TRENDS_AT, MAIL_AT, BT_AT, GIFT_AT = 0xC80, 0x1004, 0x1044, 0x1084, 0x10AC, 0x1124, 0x11C8
ITEM_EON_TICKET = 0x113
KEY_ITEMS = {ITEM_EON_TICKET, 0x103, 0x104, 0x105, 0x10D}     # (a few, enough for the tests)

# The Record Corner (layout RecordCorner, 20 x 10): '#' blocked; the table in the middle.
ROOM = ["####################",
        "####################",
        "####............####",
        "####............####",
        "####...######...####",
        "####....####....####",
        "####...######...####",
        "####............####",
        "####............####",
        "########....########"]
SEATS = {(6, 4): 0, (13, 4): 1, (6, 6): 2, (13, 6): 3}        # coordinate triggers, VAR_TEMP_0 == 0
SPAWN = {0: (8, 9), 1: (9, 9)}                                # side by side on the door row
DOOR = {(8, 9), (9, 9), (10, 9), (11, 9)}                     # south-arrow warps
WALK_TO_SEAT = {0: [KEY_UP, KEY_UP, KEY_LEFT, KEY_LEFT, KEY_UP], 1: [KEY_UP, KEY_UP] + [KEY_RIGHT] * 4 + [KEY_UP]}
WALK_TO_DOOR = {0: [KEY_DOWN, KEY_RIGHT, KEY_RIGHT, KEY_DOWN, KEY_DOWN], 1: [KEY_DOWN] + [KEY_LEFT] * 4 + [KEY_DOWN, KEY_DOWN]}


class CornerRoom:
    """overworld.c, as far as the lockstep sees it (the same rules as the Trade Center's)."""
    def __init__(self):
        self.pos, self.prev = dict(SPAWN), dict(SPAWN)
        self.moving = {0: 0, 1: 0}
        self.status = {0: 0x80, 1: 0x80}
        self.seated_at = {}
        self.facing = {0: KEY_UP, 1: KEY_UP}
        self.asked_to_leave = set()
        self.seats_on = True                          # VAR_TEMP_0 == 0: the seats' scripts can run

    def blocked(self, who, x, y):
        if not (0 <= y < len(ROOM) and 0 <= x < len(ROOM[0])) or ROOM[y][x] == "#":
            return True
        other = 1 - who
        return (x, y) in (self.pos[other], self.prev[other])

    def apply(self, keys):
        for who in (0, 1):
            k = keys[who]
            if self.status[who] == 0x80 and 0x83 in self.status.values():
                self.status[who] = 0x81               # someone left: TerminateLink runs
            if self.status[who] == 0x80 and not self.moving[who] and k == KEY_DOWN and \
                    self.pos[who] in DOOR and self.facing[who] == KEY_DOWN:
                self.status[who] = 0x81               # "Will the link be terminated?"
                self.asked_to_leave.add(who)
                k = KEY_NONE
            if self.seats_on and self.status[who] == 0x80 and not self.moving[who] and self.pos[who] in SEATS:
                self.status[who] = 0x81               # the seat's coordinate script runs
                self.seated_at[who] = self.pos[who]
            if k == KEY_SEATED:
                self.status[who] = 0x82
            elif k == KEY_EXIT:
                self.status[who] = 0x83
            elif k == KEY_FREE:
                self.status[who] = 0x80
            elif k == KEY_UNSEAT and self.status[who] == 0x82:
                self.status[who] = 0x81
            if self.moving[who]:
                self.moving[who] -= 1
                if not self.moving[who]:
                    self.prev[who] = self.pos[who]
            elif self.status[who] == 0x80 and k in DIRS:
                self.facing[who] = k
                dx, dy = DIRS[k]
                x, y = self.pos[who][0] + dx, self.pos[who][1] + dy
                if not self.blocked(who, x, y):
                    self.prev[who], self.pos[who] = self.pos[who], (x, y)
                    self.moving[who] = STEP_FRAMES


# ---------------------------------------------------------------- secret_base.c, ported
def _fields(b):
    return dict(id=b[0], to_register=b[1] & 0xF, gender=b[1] >> 4 & 1, battled=b[1] >> 5 & 1, registry=b[1] >> 6,
                name=bytes(b[2:9]), tid=bytes(b[9:13]), received=struct.unpack_from("<H", b, 0x0E)[0])


def _set_bits(b, to_register=None, battled=None, registry=None):
    f = b[1]
    if to_register is not None:
        f = (f & ~0x0F) | to_register
    if battled is not None:
        f = (f & ~0x20) | battled << 5
    if registry is not None:
        f = (f & ~0xC0) | registry << 6
    b[1] = f


def _clear(b):
    """ClearSecretBase: all zero, but the name 0xFF."""
    b[:] = bytes(BASE_SIZE)
    b[2:9] = b"\xff" * 7


def _names_match(a, b):
    for i in range(7):
        if a[i] == 0xFF and b[i] == 0xFF:
            break
        if a[i] != b[i]:
            return False
    return True


def _same_trainer(a, b):                              # sub_80BD0EC
    fa, fb = _fields(a), _fields(b)
    return fa["gender"] == fb["gender"] and fa["tid"] == fb["tid"] and _names_match(fa["name"], fb["name"])


def mix_bases(own, records, my_id, players, player, has_secret_power=True):
    """ReceiveSecretBasesData: `own` the game's 20 bases (bytearrays, changed in place), `records`
    every player's 20 received bases (lists of bytearrays, by player number), `player` the game's
    own (gender, trainer ID bytes, name bytes). Returns the indexes saved, in order."""
    if not has_secret_power:
        return []
    recs = [[bytearray(b) for b in r] for r in records] + [[bytearray(BASE_SIZE) for _ in range(BASES)]] * (4 - len(records))
    for k in range(players, 4):
        recs[k] = [bytearray(BASE_SIZE) for _ in range(BASES)]
    a, b, c = ([recs[(my_id + d) % 4] for d in (1, 2, 3)])
    gender, tid, name = player

    def mine(x):                                      # sub_80BD358
        f = _fields(x)
        return bool(f["id"]) and f["gender"] == gender and f["tid"] == bytes(tid) and _names_match(f["name"], name)

    flags = [False, False, False]                     # sub_80BD3DC: each partner's first base of ours
    for i in range(BASES):
        for k, lst in enumerate((a, b, c)):
            if not flags[k] and mine(lst[i]):
                _clear(lst[i])
                flags[k] = True
        if all(flags):
            break

    def dedupe(base, lst, outer):                     # sub_80BD494
        for i in range(BASES):
            if lst[i][0] and _same_trainer(base, lst[i]):
                if outer == 0:
                    _clear(lst[i])
                    return False
                if _fields(base)["received"] > _fields(lst[i])["received"]:
                    _clear(lst[i])
                    return False
                _set_bits(lst[i], to_register=_fields(base)["to_register"])
                _clear(base)
                return True
        return False

    for i in range(1, BASES):                         # sub_80BD514
        if own[i][0]:
            if _fields(own[i])["registry"] == 1:
                _set_bits(own[i], to_register=1)
            if not dedupe(own[i], a, i):
                if not dedupe(own[i], b, i):
                    dedupe(own[i], c, i)
    for i in range(BASES):
        if a[i][0]:
            _set_bits(a[i], battled=0)
            if not dedupe(a[i], b, i):
                dedupe(a[i], c, i)
    for i in range(BASES):
        if b[i][0]:
            _set_bits(b[i], battled=0)
            dedupe(b[i], c, i)
        if c[i][0]:
            _set_bits(c[i], battled=0)

    saved = []

    def save(base):                                   # sub_80BD1FC
        bid = base[0]
        if not bid:
            return 0
        idx = next((i for i in range(BASES) if own[i][0] == bid), -1)
        if idx == 0:
            return 0
        if idx != -1:
            f = _fields(own[idx])
            if f["to_register"] == 1:
                return 0
            if f["registry"] != 2 or _fields(base)["to_register"] == 1:
                own[idx][:] = base
                _set_bits(own[idx], registry=2)
                saved.append(idx)
                return idx
            return 0
        idx = next((i for i in range(1, BASES) if own[i][0] == 0), 0)
        if not idx:
            idx = next((i for i in range(1, BASES) if _fields(own[i])["registry"] == 0
                        and _fields(own[i])["to_register"] == 0), 0)
        if idx:
            own[idx][:] = base
            _set_bits(own[idx], registry=2)
            saved.append(idx)
        return idx

    for lst in (a, b, c):
        save(lst[0])
    for status in (1, 0):                             # sub_80BD328: registered, then the rest
        for lst in (a, b, c):
            for i in range(1, BASES):
                if _fields(lst[i])["registry"] == status:
                    save(lst[i])
    for i in range(1, BASES):
        if _fields(own[i])["to_register"] == 1:
            _set_bits(own[i], registry=1, to_register=0)
    for i in range(1, BASES - 1):                     # sub_80BD280
        for j in range(i + 1, BASES):
            ri, rj = _fields(own[i])["registry"], _fields(own[j])["registry"]
            if (ri == 0 and rj == 1) or (ri == 2 and rj != 2):
                own[i], own[j] = own[j], own[i]
    for i in range(1, BASES):
        if _fields(own[i])["registry"] == 2:
            _set_bits(own[i], registry=0)
    n = _fields(own[0])["received"]
    if n != 0xFFFF:
        struct.pack_into("<H", own[0], 0x0E, n + 1)
    return saved


class RubyRecordCorner(RubyTrade):
    def __init__(self, master=True, language=LANG_ENGLISH, bases=None, player=None, tail=None, gift=0,
                 secret_power=True, leaves_first=False, has_items=(), pace=300, frame_blocks=25 * 228, version=2,
                 in_the_way=None):
        """bases: the game's own 20 Secret Bases (160 bytes each); player: its (gender, trainer ID
        bytes, name bytes); tail: the rest of its record (0x5B0 bytes: TV shows to the filler);
        gift: the Record Mixing gift it holds (it gives it only as player 0)."""
        super().__init__(master=master, language=language, party=[bytes(100)], pace=pace,
                         frame_blocks=frame_blocks, version=version, leaves_first=leaves_first,
                         in_the_way=in_the_way)
        self.bases = [bytearray(b) for b in (bases or [bytes(BASE_SIZE)] * BASES)]
        assert len(self.bases) == BASES and all(len(b) == BASE_SIZE for b in self.bases)
        self.player = player or (0, b"\x01\x02\x03\x04", b"\xbb\xbc\xbd\xff\xff\xff\xff")
        self.tail = bytes(tail if tail is not None else bytes(RECORD_SIZE - TV_AT))
        assert len(self.tail) == RECORD_SIZE - TV_AT
        self.gift = gift
        self.secret_power = secret_power
        self.has_items = set(has_items)
        self.result.update(partner_record=None, bases_before=[bytes(b) for b in self.bases], bases_after=None,
                           saved_indexes=None, gift_received=None, mixed=False, keys_while_mixing=0)

    def patch_link_player(self, block):
        """link.c InitLocalLinkPlayer: this game's trainer ID, name and (Ruby) gender."""
        gender, tid, name = self.player
        block[16 + 4:16 + 8] = tid
        block[16 + 8:16 + 16] = (bytes(name) + b"\xff")[:8]
        block[16 + 0x10] = gender

    def own_record(self):
        rec = bytearray(b"".join(self.bases) + self.tail)
        struct.pack_into("<H", rec, GIFT_AT, self.gift if self.my_id == 0 else 0)
        return bytes(rec)

    def run(self):
        yield ("until_ready",)
        yield from self._session(LT_MIX, self._corner, max_frames=12000)
        yield from self._session(LT_AFTER, self._after, max_frames=8000)
        return self.result

    def _corner(self, s):
        s.stage = "Record Corner: waiting for link players"
        while not s.players_checked:
            yield
        lps = self.link_players
        if self.language != LANG_JAPANESE and any(lp["language"] == LANG_JAPANESE for lp in lps.values()):
            raise LinkError("a Japanese partner: the Record Corner refuses (sub_808353C)")
        s.stage = "Record Corner: trainer cards"
        s.send_buffer = bytes(100)
        if self.master:
            s.link.send(0xCCCC, 2)
        while len(s.blocks_in) < 2:
            yield
        if len(s.blocks_in[self.other]) != BLOCK_REQUEST_SIZES[2]:
            raise LinkError(f"the partner's trainer card was {len(s.blocks_in[self.other])} bytes")
        self.result["partner_card"] = s.blocks_in[self.other]
        s.blocks_in = {}
        s.stage = "Record Corner: warping in"
        for _ in range(90):
            yield
        # the fade-in after a cable-club warp (field_fadetransition.c sub_8080A5C): the screen stays
        # black, music playing, until every player has sent "ready" (0x2FFE, link.c sub_80084A4)
        s.stage = s.stage.replace("warping in", "the room's fade-in: waiting for every player's ready (0x2FFE)")
        yield from s.barrier()
        room = self.room = CornerRoom()
        mine = list(WALK_TO_SEAT[self.my_id])
        wait, sent_seated = 0, False
        s.stage = "Record Corner: walking"
        for frame in range(3000):
            if room.status[self.my_id] == 0x81 and not sent_seated:
                key, sent_seated = KEY_SEATED, True
            elif wait:
                key, wait = KEY_NONE, wait - 1
            elif mine and room.status[self.my_id] == 0x80:
                key, wait = mine.pop(0), STEP_FRAMES + 2
            else:
                key = KEY_NONE
            s.link.send(0xCAFE, key)
            keys = s.keys_this_frame()
            if keys is not None:
                room.apply(keys)
            yield
            if all(v == 0x82 for v in room.status.values()):
                break
        else:
            raise LinkError(f"the partner never sat down (at {room.pos[self.other]}, status {room.status[self.other]:#x})")
        self.result["partner_seat"] = room.seated_at.get(self.other)
        room.seats_on = False                         # VAR_TEMP_0 = 1 from here
        # Task_RecordMixing_Main: ClearLinkCallback_2 (no more room keys), 20 + 60 frames
        s.stage = "mixing: getting ready"
        for _ in range(81):
            if s.cmd is not None and s.cmd[0][self.other] == 0xCAFE:
                self.result["keys_while_mixing"] += 1
            yield
        mine_rec = self.own_record()
        got = {}
        for r in range(ROUNDS):
            s.stage = f"mixing: round {r + 1} of {ROUNDS}"
            s.send_buffer = mine_rec[CHUNK * r:CHUNK * r + CHUNK].ljust(CHUNK, b"\0")   # state 0: copy
            yield
            if self.master:
                s.link.send(0xCCCC, 1)                # state 1: ask
            while len(s.blocks_in) < 2:
                if s.cmd is not None and s.cmd[0][self.other] == 0xCAFE:
                    self.result["keys_while_mixing"] += 1
                yield
            if len(s.blocks_in[self.other]) != CHUNK:
                raise LinkError(f"the partner's chunk was {len(s.blocks_in[self.other])} bytes")
            got[r] = s.blocks_in[self.other]
            s.blocks_in = {}
            # Task_RecordMixing_CopyReceiveBuffer bumps the sender's state this frame (2 -> 3); state 3
            # moves to the next chunk the frame after, and state 0 copies it the frame after that
            yield
            yield
        partner = b"".join(got[r] for r in range(ROUNDS))[:RECORD_SIZE]
        self.result["partner_record"] = partner
        # Task_RecordMixing_ReceivePacket: the bases, then the gift (the other sections are taken
        # as they come; what the DUO sends there is checked by the tests)
        records = {self.my_id: [bytes(b) for b in self.bases],
                   self.other: [partner[BASE_SIZE * i:BASE_SIZE * (i + 1)] for i in range(BASES)]}
        self.result["saved_indexes"] = mix_bases(self.bases, [records[0], records[1]], self.my_id, 2, self.player,
                                                 self.secret_power)
        self.result["bases_after"] = [bytes(b) for b in self.bases]
        gift = struct.unpack_from("<H", (partner if self.other == 0 else self.own_record()), GIFT_AT)[0]
        if self.my_id != 0 and gift:                  # ReceiveGiftItem
            if gift in KEY_ITEMS:
                if gift not in self.has_items:
                    self.result["gift_received"] = gift
            else:
                self.result["gift_received"] = gift
        self.result["mixed"] = True
        # sub_80BA00C: two frames, the save (by itself), ten frames, then the link closes
        s.stage = "mixing: saving"
        for _ in range(2 + 6 + 11):
            yield
        self.result["saved"] = True
        s.stage = "mixing: closing"
        s.close()

    def _after(self, s):
        s.stage = "back in the room: link players"
        waited = 0
        while not s.players_checked:
            waited += 1
            if waited > 300:
                raise LinkError("back in the room, no link players within 300 frames: link error")
            yield
        room = self.room
        # Main state 4: "Mixing complete" for 60 frames, then the script; a gift's message waits for A
        busy = 60 + (120 if self.result["gift_received"] else 0)
        mine = list(WALK_TO_DOOR[self.my_id]) if self.leaves_first else list(self.in_the_way)
        left_at, wait, told, exit_at, freed = {}, 0, False, None, False
        s.stage = "back in the room"
        for frame in range(5000):
            key = KEY_NONE
            if frame == busy and not freed:
                key, freed = KEY_FREE, True           # sub_80553E4: controls back, 26
            elif freed:
                if room.status[self.my_id] == 0x81 and exit_at is None:
                    exit_at = frame + 40
                if exit_at is not None and frame == exit_at:
                    key = KEY_EXIT
                elif exit_at is None and (self.leaves_first or self.in_the_way):
                    if wait:
                        wait -= 1
                    elif mine:
                        key, wait = mine.pop(0), STEP_FRAMES + 2
                    elif self.leaves_first and room.status[self.my_id] == 0x80 and not told:
                        key, told = KEY_DOWN, True
            s.link.send(0xCAFE, key)
            keys = s.keys_this_frame()
            if keys is not None:
                room.apply(keys)
                for w in (0, 1):
                    if room.status[w] == 0x83:
                        left_at.setdefault(w, frame)
            if all(v == 0x83 for v in room.status.values()):
                self.result["positions_at_exit"] = dict(room.pos)
                self.result["partner_left_after"] = left_at[self.other] - left_at.get(self.my_id, left_at[self.other])
                self.result["left_room"] = True
                self.result["partner_left_by_door"] = room.pos[self.other] in DOOR
                s.stage = "leaving: closing the link"
                s.close()
                return
            yield
        raise LinkError(f"nobody left the room (partner at {room.pos[self.other]}, status {room.status[self.other]:#x})")
