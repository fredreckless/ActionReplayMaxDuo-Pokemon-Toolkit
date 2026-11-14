"""Emerald's Battle Tower link multi battle, for the simulator (8 November 2026): the game's side of
the link, as pret's pokeemerald plays it, with the DUO as the player's partner.

The challenge (docs/MULTI.md, section 1):
  1. the lobby's link-up (LINKTYPE_BATTLE_TOWER_50 0x2266 / _OPEN 0x2277; cable_club.c
     TryBattleLinkup): link players, the trainer cards (the two chosen Pokemon's species at 0x54:
     the same species on both sides fails the link-up, FinishLinkup), the link save
     (Task_LinkFullSave: three "ready" barriers), the win streaks (4 bytes each) and the Tower
     trainers' list (40 bytes; everyone keeps player 0's: LoadLinkMultiOpponentsData), then closed;
  2. each battle links twice (13 November: found by rehearsing against the real game in the Virtual
     DUO). First (LINKTYPE_BATTLE_TOWER 0x2288; CB2_PreInitMultiBattle): link players, each side's
     two Pokemon as the party menu shows a partner's (three MultiPartnerMenuPokemon, 96 bytes), the
     party menu, closed. Then (HandleLinkBattleSetup again; CB2_HandleStartMultiPartnerBattle): link players,
     the header (signature 0x0300), the party (two Pokemon, then the third), the Tower trainers'
     party (three blocks; the follower's are ignored), the recorded battle's seed; then the battle,
     four battlers: the player 0, the partner 2, the Tower's trainers 1 and 3 (the game's AI);
  3. after a win that isn't the seventh (field_specials.c Task_LinkRetireStatusWithBattleTowerPartner):
     the link again, the follower's choice (2 bytes), the leader's verdict (2 bytes), a "ready"
     barrier, closed.
master=True: the game is player 0 (the leader and the battle's master), the DUO player 1.
master=False (11 November): the DUO is player 0. Then the DUO asks for the trainer cards; the game
keeps the DUO's trainers' list and Tower party (player 0's); the headers decide the battle's master
(FindLinkBattleMaster: the game must win it, so the DUO's signature must be below 0x0300); the
game's Pokemon are party slots 3-5 and battler 2, the DUO's 0-2 and battler 0; after a win the game
sends its choice and takes the DUO's verdict."""
import struct
from link_game_model import LinkError
from battle_game_model import (RubyColosseum, battle_block, mon_battle_fields, party_list, B_OUTCOME_WON,
                               B_OUTCOME_LOST, GETMONDATA, SETMONDATA, SWITCHINANIM, FAINTANIMATION, MOVEANIMATION,
                               PRINTSTRING, CHOOSEACTION, CHOOSEMOVE, CHOOSEPOKEMON, TWORETURNVALUES,
                               CHOSENMONRETURNVALUE, HEALTHBARUPDATE, ENDLINKBATTLE, REQUEST_HP_BATTLE)
from trade_game_model import BLOCK_REQUEST_SIZES

LT_TOWER_50, LT_TOWER_OPEN, LT_TOWER = 0x2266, 0x2277, 0x2288
LINK_CONTINUE, LINK_RETIRE = 0, 1
LINKSTAT_CONTINUE, LINKSTAT_BOTH_RETIRE, LINKSTAT_MEMBER_RETIRE, LINKSTAT_LEADER_RETIRE = 0, 1, 2, 3
PARTNER, MULTI_PARTY = 2, 3                      # the partner's battler; its Pokemon from party slot 3


class EmeraldTowerMulti(RubyColosseum):
    def __init__(self, party=None, enemy=None, open_level=False, battles=7, player_retires_after=None,
                 trainer_ids=None, master=True, **kw):
        """party: the player's two Pokemon (game form); enemy: the Tower trainers' Pokemon (four:
        trainer A's two, trainer B's two); player_retires_after: the battle after which the player
        retires (None: carries on); battles: how many the challenge is (7)."""
        super().__init__(master=master, party=party, game="emerald", **kw)
        # (the DUO's battler: always 2. The game runs the battle (the higher version signature), and
        # InitLinkBtlControllers gives the battle's master battler 0 and the other GBA battler 2 whatever
        # the link ids; with the DUO as player 0 its Pokemon are party slots 0-2, so the game's player
        # commands the DUO's Pokemon and the DUO the player's (14 November: the real game, in the Virtual DUO))
        self.partner = PARTNER
        # (link.c LINKCMD_SEND_LINK_TYPE: the game answers 0x2222 with its own link player whatever type
        # it names. A leader at the Tower can't tell the lobby's level before the game's link player,
        # so any of the Tower's three types is taken here)
        self.ask_types = (LT_TOWER_50, LT_TOWER_OPEN, LT_TOWER)
        self.tower_type = LT_TOWER_OPEN if open_level else LT_TOWER_50
        self.enemy = [bytes(m) for m in (enemy or [])]
        self.battles, self.retires_after = battles, player_retires_after
        self.trainer_ids = trainer_ids or list(range(1, 15)) + [0] * 6
        self.result.update(battles_won=0, battles_played=0, partner_status=[], retire_sessions=0,
                           partner_cards=None, challenge_status=None, partner_species=None,
                           trainers_used=None, enemy_used=None, partner_verdicts=[])

    def _battler_side(self, b):                   # (who answers for a battler: the partner only for its own)
        return self.other if b == self.partner else self.my_id

    # ------------------------------------------------------------ the challenge
    def run(self):
        yield ("until_ready",)
        yield from self._session(self.tower_type, self._lobby, max_frames=9000)
        for n in range(1, self.battles + 1):
            yield from self._session(LT_TOWER, self._partner_menu, max_frames=4000)
            yield from self._session(LT_TOWER, self._tower_battle, max_frames=40000)
            if self.result["outcome"] != B_OUTCOME_WON or n == self.battles:
                break
            yield from self._session(LT_TOWER, self._retire, max_frames=4000)
            if self.result["challenge_status"] != LINKSTAT_CONTINUE:
                break
        return self.result

    def _lobby(self, s):
        s.stage = "Tower lobby: link players"
        while not s.players_checked:
            yield
        s.stage = "Tower lobby: trainer cards"
        card = bytearray(100)
        for k, m in enumerate(self.party[:2]):
            f = mon_battle_fields(m)
            struct.pack_into("<H", card, 0x54 + 2 * k, f["species"])
        s.send_buffer = bytes(card)
        if self.master:
            s.link.send(0xCCCC, 2)
        for _ in range(900 if self.master else 2000):  # (as player 1: the leader, the DUO, asks)
            if len(s.blocks_in) >= 2:
                break
            yield
        else:
            raise LinkError("no trainer cards: " + ("the partner never answered" if self.master else
                                                    "the leader (the DUO) never asked for them"))
        theirs = s.blocks_in[self.other]
        if len(theirs) != BLOCK_REQUEST_SIZES[2]:
            raise LinkError(f"the partner's trainer card was {len(theirs)} bytes")
        s.blocks_in = {}
        mine = [struct.unpack_from("<H", card, 0x54 + 2 * k)[0] for k in range(2)]
        partner = [struct.unpack_from("<H", theirs, 0x54 + 2 * k)[0] for k in range(2)]
        self.result["partner_species"] = partner
        if set(mine) & set(partner) - {0}:          # (FinishLinkup: AreBattleTowerLinkSpeciesSame)
            raise LinkError("the partner chose a Pokemon of the same species: the link-up fails")
        s.stage = "Tower lobby: the link save"
        for _ in range(3):                          # (Task_LinkFullSave: three "ready" barriers)
            yield from s.barrier()
            for _ in range(20):
                yield
        s.stage = "Tower lobby: win streaks"
        s.link.send_block(struct.pack("<i", 0))
        got = yield from self._blocks(s, 1)
        if len(got[0]) < 4:
            raise LinkError(f"the partner's win streak block was {len(got[0])} bytes")
        s.stage = "Tower lobby: the trainers"
        s.link.send_block(struct.pack("<20H", *self.trainer_ids))
        got = yield from self._blocks(s, 1)
        if len(got[0]) < 40:
            raise LinkError(f"the partner's trainer list was {len(got[0])} bytes")
        used = list(struct.unpack_from("<20H", got[0] if not self.master else struct.pack("<20H", *self.trainer_ids)))
        if not self.master:                        # (everyone keeps player 0's list: the DUO's)
            first = used[:14]
            if len(set(first)) != 14 or 0 in first:
                raise LinkError(f"the leader's trainer list isn't one the game makes (14 different trainers): {first}")
        self.result["trainers_used"] = used
        s.close()

    def _partner_menu(self, s):
        """CB2_PreInitMultiBattle: the first of each battle's two links."""
        s.stage = "Tower battle: the party menu's summaries"
        while not s.players_checked:
            yield
        mine = bytearray(96)
        for k, m in enumerate(self.party[:3]):
            f = mon_battle_fields(m)
            struct.pack_into("<HH", mine, 32 * k, f["species"], 0)
            mine[32 * k + 0x0F] = f.get("level", 50)
        s.link.send_block(bytes(mine))
        got = yield from self._blocks(s, 1)
        if len(got[0]) != 96:
            raise LinkError(f"the partner's party menu summary was {len(got[0])} bytes, not 96 (CB2_PreInitMultiBattle)")
        species = [struct.unpack_from("<H", got[0], 32 * k)[0] for k in range(3)]
        if not any(species):
            raise LinkError("the partner's party menu summary has no Pokemon")
        self.result["partner_menu_species"] = species
        for _ in range(60):                         # (the party menu, showing the partner's)
            yield
        s.close()

    def _tower_battle(self, s):
        s.stage = "Tower battle: link players"
        while not s.players_checked:
            yield
        me, other = self.my_id, self.other
        self.result["battles_played"] += 1
        header = struct.pack("<HH", 0x0300, 0x0145) + bytes(27)
        s.link.send_block(header)
        s.stage = "Tower battle: headers"
        got = yield from self._blocks(s, 1)
        sig = {me: 0x0300, other: struct.unpack_from("<H", got[0], 0)[0]}
        self.result["partner_header"] = got[0]
        if self._find_master(sig, me) != 12:
            raise LinkError(f"the partner's header (signature {sig[other]:#06x}) makes the partner run the battle")
        mine = b"".join(self.party).ljust(300, b"\0")
        theirs = b""
        for k, size in enumerate((200, 100)):
            s.stage = f"Tower battle: parties, block {k + 1}"
            s.link.send_block(mine[:200] if k == 0 else mine[200:300])
            got = yield from self._blocks(s, 1)
            if len(got[0]) != size:
                raise LinkError(f"the partner's party block {k + 1} was {len(got[0])} bytes, not {size}")
            theirs += got[0]
        enemy = b"".join(self.enemy[:2]).ljust(300, b"\0") + b"".join(self.enemy[2:4]).ljust(300, b"\0")
        leaders = b""
        for k in range(3):
            s.stage = f"Tower battle: the Tower's trainers, block {k + 1}"
            s.link.send_block(enemy[200 * k:200 * k + 200])
            got = yield from self._blocks(s, 1)
            if len(got[0]) != 200:
                raise LinkError(f"the partner's enemy block was {len(got[0])} bytes")
            leaders += got[0]
        if not self.master:                        # (player 1 keeps player 0's: the DUO's)
            if not any(leaders[0:32]) or not any(leaders[300:332]):
                raise LinkError("the leader's Tower party has no Pokemon for one of the trainers")
            enemy = leaders
        self.result["enemy_used"] = enemy
        s.stage = "Tower battle: the seed"
        s.link.send_block(struct.pack("<I", 0x12345678))
        got = yield from self._blocks(s, 1)
        self.result["partner_party"] = theirs
        shown = [x for x in self.result.get("partner_menu_species", []) if x]
        sent = [mon_battle_fields(theirs[100 * i:100 * i + 100])["species"] for i in range(3) if any(theirs[100 * i:100 * i + 32])]
        if shown and shown != sent:
            raise LinkError(f"the party menu showed the partner's {shown}, but it brought {sent}")
        mons = lambda raw: [mon_battle_fields(raw[100 * i:100 * i + 100]) if any(raw[100 * i:100 * i + 32]) else None
                            for i in range(len(raw) // 100)]
        # party slots as the engine keeps them: link id 0's 0-2, id 2's 3-5; the trainers' 0-2, 3-5
        first, second = (mine, theirs) if self.master else (theirs, mine)
        self.tparty = {"player": (mons(first) + [None] * 3)[:3] + (mons(second) + [None] * 3)[:3],
                       "enemy": mons(enemy)}
        dslots = slice(3, 6) if self.master else slice(0, 3)
        if not any(self.tparty["player"][dslots]):
            raise LinkError("the partner sent no Pokemon")
        for _ in range(100):
            yield
        yield from self._multi_engine(s)
        for _ in range(20):
            yield
        s.close()

    def _retire(self, s):
        s.stage = "Tower: the link again, after the battle"
        while not s.players_checked:
            yield
        self.result["retire_sessions"] += 1
        ours = LINK_RETIRE if self.retires_after == self.result["battles_played"] else LINK_CONTINUE
        if not self.master:                        # (as member: our choice, then the leader's verdict)
            s.stage = "Tower: our choice, then the leader's verdict"
            for _ in range(10):
                yield
            s.link.send_block(struct.pack("<H", ours))
            got = yield from self._blocks(s, 1, frames=600)
            if len(got[0]) < 2:
                raise LinkError(f"the leader's verdict was {len(got[0])} bytes")
            verdict = struct.unpack_from("<H", got[0], 0)[0]
            allowed = (LINKSTAT_BOTH_RETIRE, LINKSTAT_MEMBER_RETIRE) if ours else (LINKSTAT_CONTINUE, LINKSTAT_LEADER_RETIRE)
            if verdict not in allowed:
                raise LinkError(f"the leader's verdict {verdict} doesn't fit the game's choice ({ours})")
            self.result["partner_verdicts"].append(verdict)
            self.result["challenge_status"] = verdict
        else:
            s.stage = "Tower: the partner's choice"
            got = yield from self._blocks(s, 1, frames=600)
            if len(got[0]) < 2:
                raise LinkError(f"the partner's choice was {len(got[0])} bytes")
            theirs = struct.unpack_from("<H", got[0], 0)[0]
            self.result["partner_status"].append(theirs)
            verdict = (LINKSTAT_BOTH_RETIRE if ours and theirs else LINKSTAT_MEMBER_RETIRE if theirs else
                       LINKSTAT_LEADER_RETIRE if ours else LINKSTAT_CONTINUE)
            self.result["challenge_status"] = verdict
            s.link.send_block(struct.pack("<H", verdict))
        for _ in range(30):
            yield
        yield from s.barrier()
        s.close()

    # ------------------------------------------------------------ the battle: four battlers
    def _multi_engine(self, s):
        p, e = self.tparty["player"], self.tparty["enemy"]
        team = {0: p, 2: p, 1: e, 3: e}
        active = {0: 0, 2: MULTI_PARTY, 1: 0, 3: MULTI_PARTY}
        for b in (0, 1, 2, 3):
            if team[b][active[b]] is None:
                active[b] = None
        hp = {id(p): [f["hp"] if f else 0 for f in p], id(e): [f["hp"] if f else 0 for f in e]}
        HP = lambda b, k=None: hp[id(team[b])][active[b] if k is None else k]
        live = lambda b: active[b] is not None and HP(b) > 0
        PARTNER = self.partner                     # (the DUO's battler)
        own = lambda b: b != PARTNER
        foes = lambda b: (1, 3) if b in (0, 2) else (0, 2)
        s.stage = "Tower battle: the intro"
        yield from self._emit(s, [(b, [GETMONDATA, 0, 0, 0]) for b in (0, 1, 2, 3)])
        yield from self._emit(s, [(0, [PRINTSTRING, 0, 0, 0])])
        turn = 0
        while True:
            turn += 1
            if turn > 60:
                raise LinkError("the battle went on for 60 turns")
            self.turn = turn
            acting = [b for b in (0, 1, 2, 3) if live(b)]
            self._own_moves = {}
            for b in acting:
                if own(b):
                    f = team[b][active[b]]
                    self._own_moves[b] = [CHOOSEMOVE, 0, 0, 0] + list(struct.pack("<4H", *f["moves"])) + f["pp"] + \
                        [35] * 4 + list(struct.pack("<H", f["species"])) + [0, 0]
            s.stage = f"Tower battle: turn {turn}, choosing"
            answers = yield from self._emit(s, [(b, [CHOOSEACTION, 0, 0, 0]) for b in acting])
            moves = {b: (self.game_move(turn, b), b ^ 1) for b in self._own_moves}
            self._own_moves = {}
            if PARTNER in acting:
                r = answers.get(PARTNER)
                if r is None or r[0] != TWORETURNVALUES or r[1] != 0:
                    raise LinkError(f"the partner's action was {r!r}, not 'fight'")
                f = team[PARTNER][active[PARTNER]]
                answers = yield from self._emit(s, [(PARTNER, [CHOOSEMOVE, 0, 0, 0] + list(struct.pack("<4H", *f["moves"])) +
                                                      f["pp"] + [35] * 4 + list(struct.pack("<H", f["species"])) + [0, 0])])
                r = answers.get(PARTNER)
                if r is None or r[0] != TWORETURNVALUES or r[1] != 10:
                    raise LinkError(f"the partner's move answer was {r!r}")
                slot, target = r[2], r[3]
                if not (0 <= slot < 4 and f["moves"][slot] and f["pp"][slot]):
                    raise LinkError(f"the partner's move slot {slot} has no move or PP")
                if target not in (1, 3):
                    raise LinkError(f"the partner aimed at battler {target}, on the player's side")
                f["pp"][slot] -= 1
                moves[PARTNER] = (slot, target)
                self.result["partner_choices"].append((turn, PARTNER, slot, target))
            s.stage = f"Tower battle: turn {turn}, moves"
            for b in sorted(moves):
                if not live(b):
                    continue
                slot, target = moves[b]
                if not live(target):
                    target = next((t for t in foes(b) if live(t)), None)
                    if target is None:
                        continue
                move = team[b][active[b]]["moves"][slot]
                yield from self._emit(s, [(b, [MOVEANIMATION] + list(struct.pack("<H", move)) + [1, 0, 0])], attacker=b, target=target)
                share = self.hit_share if target in (1, 3) else self.partner_hit_share
                f = team[target][active[target]]
                dmg = min(HP(target), max(1, int(f["max_hp"] * share + 0.999)))
                hp[id(team[target])][active[target]] -= dmg
                yield from self._emit(s, [(target, [HEALTHBARUPDATE, 0] + list(struct.pack("<h", dmg)))], attacker=b, target=target)
                yield from self._emit(s, [(target, [SETMONDATA, REQUEST_HP_BATTLE, 0] + list(struct.pack("<H", HP(target))))],
                                      attacker=b, target=target)
                if HP(target) == 0:
                    yield from self._emit(s, [(target, [FAINTANIMATION] * 4)], attacker=b, target=target)
            for b in (0, 1, 2, 3):
                if active[b] is None or live(b):
                    continue
                half = range(MULTI_PARTY, 6) if b in (2, 3) else range(0, MULTI_PARTY)
                bench = [i for i in half if team[b][i] and hp[id(team[b])][i] > 0 and i != active[b]]
                if not bench:
                    active[b] = None
                    continue
                answers = yield from self._emit(s, [(b, [CHOOSEPOKEMON, 0, 6, 0, 0, 0, 0, 0])])
                if own(b):
                    pick = bench[0]
                else:
                    r = answers.get(b)
                    if r is None or r[0] != CHOSENMONRETURNVALUE or r[1] not in bench:
                        raise LinkError(f"the partner sent in {r!r}, not one of {bench}")
                    pick = r[1]
                    self.result["partner_switches"].append((turn, b, pick))
                active[b] = pick
                yield from self._emit(s, [(b, [SWITCHINANIM, pick, 0, 5])])
            ours_alive = any(live(b) for b in (0, 2))
            theirs_alive = any(live(b) for b in (1, 3))
            if ours_alive and theirs_alive:
                continue
            outcome = B_OUTCOME_WON if ours_alive else B_OUTCOME_LOST
            self.result["outcome"] = outcome
            self.result["battles_won"] += outcome == B_OUTCOME_WON
            yield from self._emit(s, [(b, [ENDLINKBATTLE, outcome, 0, 0]) for b in (0, 1, 2, 3)])
            return
