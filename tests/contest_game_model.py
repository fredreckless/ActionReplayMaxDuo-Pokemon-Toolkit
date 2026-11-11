"""Emerald's link Contest in E mode, for the simulator (8 November 2026): the game's side of the link
as pret's pokeemerald plays it, the game the leader (player 0), the DUO player 1. From
contest_link.c, contest_link_util.c, contest.c, contest_util.c, cable_club.c and the Contest
Lobby's scripts:

  1. the link-up (LINKTYPE_CONTEST_EMODE 0x6602, 2-4 players, Emerald only): link players, the
     trainer cards (the leader's 0xCCCC 2);
  2. the set-up (Task_LinkContest_StartCommunicationEm), each step after a "ready" barrier: each
     player's struct ContestPokemon (64 bytes), the leader's random seed (4), each player's leader ID
     (2, 0x6E), each player's category (2), the leader's AI contestants (2 x 64), each player's
     round-1 points (8) and turn order (4). Blocks are sent straight away (SendBlock), not asked for;
  3. the contest: each player's contestant number (1 byte); five rounds of each player's move (2)
     and the appeals' state (Task_LinkContest_CommunicateAppealsState: four blocks, 112, 18, 3 and 4
     bytes, every player's own copy, the leader's used) after each appeal, at the end of the round
     and before the next; the final standings (8, 8, 8, 4);
  4. the results: each player's contestant number again, then the link closed.

What the partner sends is checked: its contestant (the Pokemon's species, moves, condition, the
names in the link's form), its moves (one of its own each round), every block's size, and nothing
where only the leader sends."""
import struct
from link_game_model import LinkError, LANG_ENGLISH
from trade_game_model import RubyTrade

LT_EMODE = 0x6602
MON_SIZE, APPEALS = 64, (112, 18, 3, 4)
STANDINGS = (8, 8, 8, 4)
LEADER_ID = 0x6E
CATEGORIES = ("cool", "beauty", "cute", "smart", "tough")


def contest_mon(species, moves, cond=(10, 20, 30, 40, 50, 5), name=b"\xbb\xbc\xbd\xff"):
    mon = bytearray(MON_SIZE)
    struct.pack_into("<H", mon, 0, species)
    mon[2:13] = name.ljust(11, b"\xff")
    mon[13:21] = b"\xc7\xbb\xd3\xff".ljust(8, b"\xff")
    mon[21] = 216
    struct.pack_into("<4H", mon, 30, *moves)
    mon[38:44] = bytes(cond)
    mon[45] = 1
    return bytes(mon)


class EmeraldLinkContest(RubyTrade):
    def __init__(self, category="cool", player_mon=None, partner_species=None, partner_moves=None, rounds=5,
                 duo_place=1, language=LANG_ENGLISH, master=True, **kw):
        """category: the player's choice at the counter; partner_species / partner_moves: what the
        DUO's contestant must be (from its .pk3); duo_place: where the leader's figures put the DUO
        (0 first ... 3 fourth)."""
        # master False (11 November): the DUO is player 0 - it asks for the cards and sends the seed and
        # the AI contestants - while the game, by the leader IDs, still works out the contest
        super().__init__(master=master, language=language, party=[bytes(100)], game="emerald", **kw)
        self.category = CATEGORIES.index(category)
        self.player_mon = player_mon or contest_mon(25, (85, 86, 98, 0))
        self.partner_species, self.partner_moves = partner_species, partner_moves
        self.rounds, self.duo_place = rounds, duo_place
        self.result.update(partner_mon=None, partner_moves=[], partner_index=[], standings=None, closed=False,
                           blocks_answered=0)

    def run(self):
        yield ("until_ready",)
        yield from self._session(LT_EMODE, self._contest, max_frames=60000)
        return self.result

    # ------------------------------------------------------------ helpers
    def _partner_block(self, s, size, frames=900):
        for _ in range(frames):
            s.blocks_in.pop(self.my_id, None)
            if self.other in s.blocks_in:
                b = s.blocks_in.pop(self.other)
                if len(b) != size:
                    raise LinkError(f"the partner sent {len(b)} bytes, not {size} ({s.stage})")
                return b
            yield
        raise LinkError(f"waiting for the partner's block ({s.stage})")

    def _leader_only(self, s, data, frames=200):
        """A block only the leader sends: the partner must send nothing back."""
        while s.link.queue:
            yield
        s.link.send_block(data)
        for _ in range(frames):
            s.blocks_in.pop(self.my_id, None)
            if self.other in s.blocks_in:
                raise LinkError(f"the partner sent a block where only the leader sends ({s.stage})")
            yield

    def _exchange(self, s, data):
        """Every player's own block: ours, then the partner's (its size checked)."""
        while s.link.queue:
            yield
        s.link.send_block(data)
        got = yield from self._partner_block(s, len(data))
        self.result["blocks_answered"] += 1
        return got

    def _barrier(self, s, frames=1500):
        """A "ready" barrier, as Session.barrier, but a partner that never answers fails it in time."""
        s.link.send(0x2FFE)
        for _ in range(frames):
            if s.barrier_seen >= {0, 1}:
                s.barrier_seen = set()
                return
            yield
        raise LinkError(f"the partner never answered a \"ready\" barrier ({s.stage})")

    def _wait(self, frames):
        for _ in range(frames):
            yield

    # ------------------------------------------------------------ the contest
    def _contest(self, s):
        s.stage = "Contest link-up: link players"
        while not s.players_checked:
            yield
        partner = self.link_players[self.other]
        if partner["version"] & 0xFF != 3:
            raise LinkError(f"the partner's game is version {partner['version'] & 0xFF}: E mode is Emerald only")
        s.stage = "Contest link-up: trainer cards"
        s.send_buffer = bytes(100)
        if self.master:
            s.link.send(0xCCCC, 2)
        yield from self._partner_block(s, 100, frames=900 if self.master else 2000)
        yield from self._wait(60)
        # the set-up
        s.stage = "Contest set-up: the contestants"
        yield from self._barrier(s)
        theirs = yield from self._exchange(s, self.player_mon)
        self._check_mon(theirs)
        s.stage = "Contest set-up: the random seed"
        yield from self._barrier(s)
        if self.master:
            yield from self._leader_only(s, struct.pack("<I", 0x1234ABCD))
        else:
            seed = yield from self._partner_block(s, 4)
            self.result["seed"] = seed
        s.stage = "Contest set-up: leader IDs"
        yield from self._barrier(s)
        lid = yield from self._exchange(s, struct.pack("<H", LEADER_ID))
        ids = {self.my_id: LEADER_ID, self.other: struct.unpack("<H", lid)[0]}
        leader = max((0, 1), key=lambda i: (ids[i], -i))             # LinkContest_GetLeaderIndex: the highest, the first on a tie
        if leader != self.my_id:
            raise LinkError(f"the leader IDs {ids} make the partner the leader: it would have to work out the contest")
        s.stage = "Contest set-up: the category"
        yield from self._barrier(s)
        cat = yield from self._exchange(s, struct.pack("<H", self.category))
        if struct.unpack("<H", cat)[0] != self.category:
            raise LinkError(f"the partner chose category {struct.unpack('<H', cat)[0]}, not {self.category}")
        s.stage = "Contest set-up: the AI contestants"
        yield from self._barrier(s)
        if self.master:
            yield from self._leader_only(s, contest_mon(300, (1, 2, 3, 4)) + contest_mon(301, (5, 6, 7, 8)))
        else:
            ai = yield from self._partner_block(s, 2 * MON_SIZE)
            for k in (0, 1):
                m = ai[k * MON_SIZE:(k + 1) * MON_SIZE]
                if not struct.unpack_from("<H", m, 0)[0] or m[7] != 0xFF or not any(struct.unpack_from("<4H", m, 30)):
                    raise LinkError(f"AI contestant {k + 1} from player 0 isn't a whole contestant: {m.hex()}")
            self.result["ai_mons"] = ai
        s.stage = "Contest set-up: round-1 points"
        yield from self._barrier(s)
        yield from self._exchange(s, struct.pack("<4h", 40, 30, 20, 10))
        s.stage = "Contest set-up: the turn order"
        yield from self._barrier(s)
        yield from self._exchange(s, bytes([0, 1, 2, 3]))
        yield from self._wait(240)                                  # the walk to the hall, the warp, the curtain
        # the contest
        s.stage = "Contest: contestant numbers"
        got = yield from self._exchange(s, bytes([self.my_id]))
        self.result["partner_index"].append(got[0])
        for r in range(self.rounds):
            s.stage = f"Contest round {r + 1}: the moves"
            yield from self._wait(90)                               # (the player choosing)
            got = yield from self._exchange(s, struct.pack("<H", 85))
            move = struct.unpack("<H", got)[0]
            if move not in [m for m in self.partner_moves if m]:
                raise LinkError(f"the partner's move {move} isn't one of its contestant's {self.partner_moves}")
            self.result["partner_moves"].append(move)
            for turn in range(4):
                s.stage = f"Contest round {r + 1}: appeal {turn + 1}"
                yield from self._appeals_state(s)
                yield from self._wait(60)
            s.stage = f"Contest round {r + 1}: the round's end"
            yield from self._appeals_state(s)
            if r + 1 < self.rounds:
                s.stage = f"Contest round {r + 1}: before the next"
                yield from self._appeals_state(s)
        s.stage = "Contest: the final standings"
        yield from self._wait(100)
        places = [0, 0, 0, 0]
        others = [p for p in range(4) if p != self.duo_place]
        places[self.other] = self.duo_place
        for i, c in zip((self.my_id, 2, 3), others):
            places[i] = c
        for size in STANDINGS[:3]:
            yield from self._exchange(s, bytes(size))
            yield from self._wait(11)
        yield from self._exchange(s, bytes(places))
        self.result["standings"] = places
        # the results
        yield from self._wait(200)
        s.stage = "Contest results: contestant numbers"
        got = yield from self._exchange(s, bytes([self.my_id]))
        self.result["partner_index"].append(got[0])
        yield from self._wait(300)
        s.stage = "Contest results: closing the link"
        s.close()
        self.result["closed"] = True

    def _appeals_state(self, s):
        for size in APPEALS:
            yield from self._exchange(s, bytes(range(size)))
            yield from self._wait(11)

    def _check_mon(self, b):
        species = struct.unpack_from("<H", b, 0)[0]
        moves = list(struct.unpack_from("<4H", b, 30))
        if self.partner_species is not None and species != self.partner_species:
            raise LinkError(f"the partner's contestant is species {species}, not {self.partner_species}")
        if self.partner_moves is not None and moves != list(self.partner_moves):
            raise LinkError(f"the partner's contestant's moves are {moves}, not {self.partner_moves}")
        if b[2 + 5] != 0xFF or b[13 + 5] != 0xFF:
            raise LinkError("the partner's names aren't in the link's form (an end after five characters)")
        if b[21] not in (216, 217):
            raise LinkError(f"the partner's trainer picture is {b[21]}, not the link Brendan or May")
        self.result["partner_mon"] = b
