"""The Berry Blender with a link partner, for the simulator (8 November 2026): the game's side of the
link as pret's pokeemerald (and pokeruby: the same protocol) plays it, the game the leader (player
0), the DUO player 1. From berry_blender.c, cable_club.c, link.c and data/scripts/berry_blender.inc:

  1. the link-up (LINKTYPE_BERRY_BLENDER_SETUP 0x4411, TryBerryBlenderLinkup): link players, the
     trainer cards (the leader's 0xCCCC 2); the link stays open;
  2. each blend (CB2_StartBlenderLink): the bag (the player chooses a berry), a "ready" barrier, the
     leader's 0xCCCC 4: a 40-byte struct BlenderBerry from each; the berries go in; a "ready"
     barrier; then the play: every frame each GBA sends 0x4444 (word 2: a hit), and each GBA runs
     the arrow itself from what arrives (UpdateBlenderCenter, HandlePlayerInput,
     UpdateOpponentScores: the same arithmetic as the firmware's own copy, written again here from
     the source); the end once the progress bar is full: the arrow slows to a stop, the leader's
     40-byte block (the time, the best RPM), each player's answer to "blend another berry?" (0x2FFF:
     0x7779 yes, 0x8888 no), the leader's verdict (0x2FFF: 0x2222 again, 0x1111 stop), "ready"
     barriers round the link save; then the next blend or the link closed.

What the partner does is checked as the game would and more: its berry (an item a blender takes,
its name and flavours as the games keep them), every hit it claims against the game's own arrow at
the moment it would have pressed (a few frames earlier: the link's delay), its answers."""
import struct
from link_game_model import LinkError, LANG_ENGLISH
from trade_game_model import RubyTrade

LT_SETUP = 0x4411
SEND_KEYS, HIT_BEST, HIT_GOOD, HIT_MISS = 0x4444, 0x4523, 0x5432, 0x2345
SEND_PACKET, PLAY_AGAIN, SAY_NO, NO_BERRIES, NO_SPACE = 0x2FFF, 0x7779, 0x8888, 0x9999, 0xAAAA
LEADER_GO, LEADER_STOP = 0x2222, 0x1111
MIN_SPEED, MAX_PROGRESS = 0x80, 1000
HIT_RANGE = {0: 224, 1: 96}            # sArrowHitRangeStart[playerIdToArrowId[i]]: two players, arrows 1 and 2
PROX = {0: None, 1: HIT_GOOD, 2: HIT_BEST}
FIRST_BERRY_ITEM = 133
# A few berries as pokeemerald's gBerries keeps them: name, spicy, dry, sweet, bitter, sour, smoothness
KNOWN_BERRIES = {133: ("CHERI", 10, 0, 0, 0, 0, 25), 134: ("CHESTO", 0, 10, 0, 0, 0, 25),
                 135: ("PECHA", 0, 0, 10, 0, 0, 25), 139: ("ORAN", 10, 10, 10, 10, 10, 20),
                 142: ("SITRUS", 10, 10, 10, 10, 10, 20), 165: ("WATMEL", 0, 0, 40, 10, 0, 70)}
NAME_CHARS = {c: 0xBB + i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}


def berry_block(item):
    name, *rest = KNOWN_BERRIES[item]
    raw = bytes(NAME_CHARS[c] for c in name).ljust(7, b"\xff")
    return (struct.pack("<H", item) + raw + bytes(rest)).ljust(40, b"\0")


def proximity(arrow, player):
    """GetArrowProximity: 2 BEST, 1 GOOD, 0 MISS."""
    pos, start = (arrow >> 8) + 24, HIT_RANGE[player]
    if start <= pos < start + 48:
        return 2 if start + 20 <= pos < start + 28 else 1
    return 0


class BerryBlenderLink(RubyTrade):
    def __init__(self, berries=(133,), answers=None, player_plan=None, game="emerald", language=LANG_ENGLISH,
                 choose_frames=120, **kw):
        """berries: the player's berry for each blend (item numbers); answers: the player's answer to
        "blend another berry?" after each (True: yes; default yes until the last); player_plan(n):
        what the player aims for on its n-th pass (HIT_BEST, HIT_GOOD or HIT_MISS; default BEST)."""
        super().__init__(master=True, language=language, party=[bytes(100)], game=game, **kw)
        self.berries = list(berries)
        self.answers = list(answers) if answers is not None else [True] * (len(self.berries) - 1) + [False]
        self.player_plan = player_plan or (lambda n: HIT_BEST)
        self.choose_frames = choose_frames
        self.result.update(blends=[], partner_berries=[], partner_answers=[], verdicts=[], partner_card=None,
                           closed=False)

    def run(self):
        yield ("until_ready",)
        yield from self._session(LT_SETUP, self._blender, max_frames=80000)
        return self.result

    # ------------------------------------------------------------ the link-up, then the blends
    def _blender(self, s):
        s.stage = "Berry Blender link-up: link players"
        while not s.players_checked:
            yield
        partner = self.link_players[self.other]
        if partner["link_type"] != LT_SETUP:
            raise LinkError(f"the partner's link type is {partner['link_type']:#06x}")
        s.stage = "Berry Blender link-up: trainer cards"
        s.send_buffer = bytes(100)
        s.link.send(0xCCCC, 2)
        got = yield from self._blocks(s, 100)
        self.result["partner_card"] = got
        for n, item in enumerate(self.berries):
            again = yield from self._blend(s, n, item)
            if not again:
                break
        for _ in range(30):
            yield
        s.stage = "Berry Blender: closing the link"
        s.close()
        self.result["closed"] = True

    def _blocks(self, s, size, frames=900):
        """The partner's next block of `size` bytes (the game's own echo dropped)."""
        for _ in range(frames):
            s.blocks_in.pop(self.my_id, None)
            if self.other in s.blocks_in:
                b = s.blocks_in.pop(self.other)
                if len(b) != size:
                    raise LinkError(f"the partner sent {len(b)} bytes, not {size} ({s.stage})")
                return b
            yield
        raise LinkError(f"waiting for the partner's block ({s.stage})")

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

    def _blend(self, s, n, item):
        s.stage = f"blend {n + 1}: the bag"
        yield from self._wait(self.choose_frames)
        s.stage = f"blend {n + 1}: the berries' barrier"
        s.send_buffer = berry_block(item)
        yield from self._barrier(s)
        s.link.send(0xCCCC, 4)
        s.stage = f"blend {n + 1}: the berries"
        theirs = yield from self._blocks(s, 40, frames=1200)
        their_item = struct.unpack_from("<H", theirs, 0)[0]
        if their_item not in KNOWN_BERRIES:
            raise LinkError(f"the partner's berry is item {their_item}, not a berry this model knows")
        if theirs[:15] != berry_block(their_item)[:15]:
            raise LinkError(f"the partner's berry block isn't the game's own for item {their_item}: {theirs[:15].hex()}")
        self.result["partner_berries"].append(their_item)
        yield from self._wait(2 * 61 + 44 + 30 + 180)          # the throws, the fall, the shake, the countdown
        s.stage = f"blend {n + 1}: the countdown's barrier"
        yield from self._barrier(s)
        blend = yield from self._play(s, n)
        blend.update(game_item=item, partner_item=their_item)
        self.result["blends"].append(blend)
        # the end (CB2_EndBlenderGame 3-13). ProcessLinkPlayerCmds gathers the answers to "blend another
        # berry?" every frame from here on, before the leader's own prompt is up too
        responses = {}

        def collect():
            cmd = s.cmd
            if cmd is not None:
                for i in (0, 1):
                    if cmd[0][i] == SEND_PACKET and cmd[1][i] in (PLAY_AGAIN, SAY_NO, NO_BERRIES, NO_SPACE):
                        responses.setdefault(i, cmd[1][i])
        s.stage = f"blend {n + 1}: the leader's time and RPM"
        while s.link.queue:
            collect()
            yield
        s.link.send_block(struct.pack("<IH", blend["frames"], blend["max_rpm"]).ljust(40, b"\0"))
        for _ in range(300):
            collect()
            s.blocks_in.pop(self.my_id, None)
            if self.other in s.blocks_in:
                raise LinkError("the partner sent a block where only the leader sends one (the time and RPM)")
            yield
        s.stage = f"blend {n + 1}: blend another berry?"
        mine = PLAY_AGAIN if self.answers[n] else SAY_NO
        s.link.send(SEND_PACKET, mine)
        for _ in range(1200):
            collect()
            if len(responses) == 2:
                break
            yield
        else:
            raise LinkError(f"no answer from the partner to 'blend another berry?' ({responses})")
        self.result["partner_answers"].append(responses[self.other])
        go = all(responses[i] == PLAY_AGAIN for i in (0, 1))
        stopper = next((i for i in (0, 1) if responses[i] != PLAY_AGAIN), 0)
        s.link.send(SEND_PACKET, LEADER_GO if go else LEADER_STOP, 0 if go else responses[stopper], 0 if go else stopper)
        self.result["verdicts"].append("again" if go else "stop")
        yield from self._wait(10)
        s.stage = f"blend {n + 1}: the link save"
        yield from self._barrier(s)
        yield from self._barrier(s)
        yield from self._wait(10)
        yield from self._barrier(s)
        yield from self._barrier(s)
        return go

    def _play(self, s, n):
        """CB2_PlayBlender, frame by frame, then the arrow slowing to a stop."""
        s.stage = f"blend {n + 1}: blending"
        arrow, speed, timer, progress, shown, frames, max_rpm = 0xC000, MIN_SPEED, 0, 0, 0, 0, 0
        history, partner_hits, game_hits, passes = [], [], [], {0: 0, 1: 0}
        inside, pressed, plan = {0: False, 1: False}, False, None
        s.link.send(SEND_KEYS, 0, 0)                          # (the callback starts a frame before the play)
        yield
        while True:
            frames += 1
            arrow = (arrow + speed) & 0xFFFF                  # UpdateBlenderCenter
            history.append(arrow)
            left = False
            for i in (0, 1):                                  # (passes over each player's spot)
                p = proximity(arrow, i)
                if p and not inside[i]:
                    inside[i] = True
                    if i == 0:
                        pressed, plan = False, self.player_plan(passes[0])
                elif not p and inside[i]:
                    inside[i] = False
                    passes[i] += 1
                    left = left or i == 0
            score = 0                                         # HandlePlayerInput: the player's press
            p = proximity(arrow, 0)
            if inside[0] and not pressed:
                if plan == HIT_BEST and (p == 2 or (p == 1 and (arrow >> 8) + 24 >= HIT_RANGE[0] + 28)):
                    score = PROX[p]
                elif plan == HIT_GOOD and p == 1:
                    score = HIT_GOOD
            elif left and not pressed and plan == HIT_MISS:   # (a touch late: the game scores a miss)
                score = HIT_MISS
            if score:
                pressed = True
            timer += 1
            if timer > 5:
                if speed > MIN_SPEED:
                    speed -= 1
                timer = 0
            cmd = s.cmd                                       # UpdateOpponentScores
            if cmd is not None:
                for i in (0, 1):
                    if cmd[0][i] != SEND_KEYS:
                        continue
                    hit = cmd[2][i]
                    if hit == HIT_BEST:
                        speed += 384 if speed < 1500 else 128
                        progress = min(MAX_PROGRESS, progress + speed // 55)
                    elif hit == HIT_GOOD:
                        if speed < 1500:
                            speed += 256
                        progress += speed // 70
                    elif hit == HIT_MISS:
                        speed = max(MIN_SPEED, speed - 256)
                    else:
                        continue
                    (partner_hits if i == self.other else game_hits).append((frames, hit))
                    if i == self.other:
                        claimed = {HIT_BEST: 2, HIT_GOOD: 1, HIT_MISS: 0}[hit]
                        back = [proximity(a, 1) for a in history[-8:-1]]
                        if claimed not in back:
                            raise LinkError(f"the partner claimed {hit:#06x} at frame {frames}, but its arrow was "
                                            f"{back} over the frames before (the game's own arrow)")
            max_rpm = max(max_rpm, 60 * 60 * 100 * speed // 0x10000)
            if shown < progress:                              # TryUpdateProgressBar
                shown += 2
            s.link.send(SEND_KEYS, 1 if score else 0, score)
            if shown >= MAX_PROGRESS:
                break
            if frames > 20000:
                raise LinkError("the blend went on for 20000 frames")
            yield
        while speed > 0:                                      # CB2_EndBlenderGame 1-2
            yield
            speed -= 32
            if speed > 0:
                s.link.send(SEND_KEYS, 0, 0)
        if len(partner_hits) > passes[1] + 1:
            raise LinkError(f"the partner pressed {len(partner_hits)} times in {passes[1]} passes over its spot")
        return dict(frames=frames, max_rpm=max_rpm, partner_hits=partner_hits, game_hits=game_hits,
                    passes=passes[1])
