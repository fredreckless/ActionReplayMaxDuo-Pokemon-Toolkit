"""The Cable Club's link-up and the link rooms, ported from pokeruby (cable_club.c, overworld.c,
field_fadetransition.c) onto pret_link.Console. One copy, shared by every model that goes through a
Cable Club - the trade, record mixing, battles, the blender, contests, the lab4p leader.

What is not the game's own: the field message boxes are a number of frames (MESSAGE_FRAMES), the warp
into a room is WARP_FRAMES, and a link player walking a step is busy for STEP_FRAMES. Everything about
the link itself - which commands, when, and what the game waits for - follows the source.
"""

from pret_link import (Console, A_BUTTON, B_BUTTON, START_BUTTON, DPAD_RIGHT, DPAD_LEFT, DPAD_UP, DPAD_DOWN,
                       EXCHANGE_COMPLETE, EXCHANGE_TIMED_OUT, EXCHANGE_IN_PROGRESS)

MESSAGE_FRAMES = 40                       # ShowFieldAutoScrollMessage until the box hides (a guess)
WARP_FRAMES = 60                          # the warp into a room: fade, map load (a guess)
STEP_FRAMES = 16                          # a walking step (the object event's mode isn't idle meanwhile)

# the Cable Club's seats: (gLinkType, min players, max players)
TRADE_CENTER = (0x1133, 2, 2)             # pret:pokeruby/src/cable_club.c:583 sub_80834E4
RECORD_CORNER = (0x3311, 2, 4)            # pret:pokeruby/src/cable_club.c:590 sub_808350C
BERRY_BLENDER = (0x4411, 2, 4)            # pret:pokeruby/src/cable_club.c:644 sub_8083614
CONTEST = (0x6601, 4, 4)                  # pret:pokeruby/src/cable_club.c:651 sub_808363C
SINGLE_BATTLE, DOUBLE_BATTLE, MULTI_BATTLE = (0x2233, 2, 2), (0x2244, 2, 2), (0x2255, 4, 4)
                                          # pret:pokeruby/src/cable_club.c:558 sub_808347C

# gSpecialVar_Result when the link-up ends
RESULT_OK, RESULT_WRONG_COUNT, RESULT_IN_PROGRESS, RESULT_CANCELLED, RESULT_LINK_ERROR = 1, 4, 3, 5, 6


def player_count_ok(con, min_players, max_players):
    """pret:pokeruby/src/cable_club.c:197 sub_8082D9C"""
    status = con.exchange_status_timed()
    if status == EXCHANGE_COMPLETE:
        n = con.player_count()
        return 1 if min_players <= n <= max_players else 4
    if status == EXCHANGE_TIMED_OUT:
        return 0
    if status == EXCHANGE_IN_PROGRESS:
        return 3
    return 0


class LinkUp:
    """The Cable Club's link-up task, from the attendant's "Please wait." to the trainer cards
    (pret:pokeruby/src/cable_club.c:148 sub_8082CD4 and the tasks it starts). Run it with
    con.add_task(LinkUp(con, seat, card).run()); .result is gSpecialVar_Result once it ends, .stage
    where it is, .cards the trainer cards received."""

    def __init__(self, con, seat, card=b"", message_frames=MESSAGE_FRAMES):
        self.con = con
        self.link_type, self.min, self.max = seat
        self.card = bytes(card)
        self.message_frames = message_frames
        self.result = None
        self.stage = "opening"
        self.cards = []
        self.timeout = 0                  # data[4]
        con.link_type = self.link_type

    def _ended(self, result, why):
        self.result = result
        self.stage = why
        self.con.log.append(("link-up", why, result))

    def _link_error(self):
        """pret:pokeruby/src/cable_club.c:218 sub_8082DF4"""
        return self.con.link_error_occurred

    def _cancelled(self):
        """pret:pokeruby/src/cable_club.c:228 sub_8082E28 (B before the link is up)"""
        return self.con.new_keys & B_BUTTON and not self.con.link_status & 0x40

    def _si_high(self):
        """pret:pokeruby/src/cable_club.c:252 sub_8082EB8 - GetSioMultiSI: someone has plugged in ahead
        of the leader."""
        return self.con.gl.si == 1

    def _message(self):
        """ShowFieldAutoScrollMessage: GetFieldMessageBoxMode() is HIDDEN again after a while."""
        left = [self.message_frames]

        def hidden():
            left[0] -= 1
            return left[0] < 0
        return hidden

    def run(self):
        con = self.con
        # pret:pokeruby/src/cable_club.c:272 sub_8082F20
        con.open_link_timed()
        con.reset_link_players()
        for _ in range(10):
            yield
        # pret:pokeruby/src/cable_club.c:289 sub_8082F68 - wait for someone to plug in
        self.stage = "waiting for players"
        while True:
            if self._cancelled():
                return self._ended(RESULT_CANCELLED, "cancelled")
            if con.link_status & 0x40:
                con.suppress_link_error_message = True
            if con.new_keys & B_BUTTON:
                return self._ended(RESULT_CANCELLED, "cancelled")
            if con.player_count() >= 2:
                break
            yield
        con.suppress_link_error_message = True
        if con.is_master():
            yield from self._leader()
        else:
            yield from self._child()

    def _leader(self):
        con = self.con
        while True:
            # pret:pokeruby/src/cable_club.c:314 sub_8082FEC - "Please press A when everyone's here."
            self.stage = "leader's message"
            box = self._message()
            while True:
                if self._cancelled():
                    return self._ended(RESULT_CANCELLED, "cancelled")
                if self._si_high() or self._link_error():
                    return self._ended(RESULT_LINK_ERROR, "link error")
                if box():
                    break
                yield
            # pret:pokeruby/src/cable_club.c:328 sub_808303C - wait for A with enough players
            self.stage = "waiting for A"
            while True:
                yield
                if self._cancelled():
                    return self._ended(RESULT_CANCELLED, "cancelled")
                if self._si_high() or self._link_error():
                    return self._ended(RESULT_LINK_ERROR, "link error")
                n = con.player_count()
                if con.new_keys & A_BUTTON and n >= self.min:
                    con.save_link_player_count(n)            # sub_80081C8
                    break
            # pret:pokeruby/src/cable_club.c:365 sub_80830E4 - "N players. OK?" A to confirm
            self.stage = "confirming"
            box = self._message()
            again = False
            while True:
                yield
                if self._cancelled():
                    return self._ended(RESULT_CANCELLED, "cancelled")
                if self._si_high() or self._link_error():
                    return self._ended(RESULT_LINK_ERROR, "link error")
                if not box():
                    continue
                if con.saved_link_player_count != con.player_count() or con.held_keys & B_BUTTON:
                    again = True                             # (pret:pokeruby/src/link.c:1086 sub_800820C)
                    break
                if con.held_keys & A_BUTTON:
                    con.advance_as_master()                  # sub_8007F4C
                    break
            if not again:
                break
        # pret:pokeruby/src/cable_club.c:393 sub_8083188 - the link players exchanged
        self.stage = "exchanging link players"
        while True:
            yield
            if self._link_error():
                return self._ended(RESULT_LINK_ERROR, "link error")
            self.timeout += 1                                # pret:pokeruby/src/cable_club.c:546 sub_8083444
            if self.timeout > 600:
                return self._ended(RESULT_LINK_ERROR, "timed out")
            if con.player_count() != con.saved_link_player_count:
                return self._ended(RESULT_LINK_ERROR, "the player count changed")
            self.result = player_count_ok(con, self.min, self.max)
            if self.result:
                break
        # pret:pokeruby/src/cable_club.c:448 sub_8083288
        yield
        if self._link_error():
            return self._ended(RESULT_LINK_ERROR, "link error")
        if self.result == RESULT_IN_PROGRESS:
            yield from self._close()
            return
        self._prepare_card()
        con.request_block(2)                                 # sub_8007E9C
        yield from self._cards()

    def _child(self):
        con = self.con
        # pret:pokeruby/src/cable_club.c:414 sub_80831F8
        self.stage = "waiting for the leader"
        while True:
            yield
            if self._cancelled():
                return self._ended(RESULT_CANCELLED, "cancelled")
            if self._link_error():
                return self._ended(RESULT_LINK_ERROR, "link error")
            self.result = player_count_ok(con, self.min, self.max)
            if self.result:
                break
        if self.result == RESULT_IN_PROGRESS:
            yield from self._close()
            return
        self._prepare_card()
        yield from self._cards()

    def _prepare_card(self):
        con = self.con
        con.save_link_player_count(con.player_count())       # sub_80081C8
        card = self.card[:len(con.block_send_buffer)]
        con.block_send_buffer[:len(card)] = card             # TrainerCard_GenerateCardForPlayer

    def _cards(self):
        """pret:pokeruby/src/cable_club.c:470 sub_8083314"""
        con = self.con
        self.stage = "trainer cards"
        while True:
            yield
            if self._link_error():
                return self._ended(RESULT_LINK_ERROR, "link error")
            want = (1 << con.saved_link_player_count) - 1    # pret:pokeruby/src/link.c:1064 sub_8008198
            if con.block_received_status() == want:
                break
        self.cards = [con.block(i) for i in range(con.player_count())]
        con.suppress_link_error_message = False
        con.reset_block_received_flags()
        if self.result == RESULT_OK:
            return self._ended(RESULT_OK, "linked")
        con.set_close_link_callback()
        yield from self._close(already=True)

    def _close(self, already=False):
        """pret:pokeruby/src/cable_club.c:518 sub_80833C4"""
        if not already:
            self.con.set_close_link_callback()
        self.stage = "closing"
        while self.con.received_remote_link_players:
            yield
        self._ended(self.result, "closed")


class LinkRoom:
    """A link room (the Trade Center, the Record Corner): entering it (pret:pokeruby/src/overworld.c:1378
    c2_80567AC, pret:pokeruby/src/field_fadetransition.c:140 sub_8080A5C) and callback1 there,
    pret:pokeruby/src/overworld.c:2132 sub_8055354, which sends this console's key with every
    command and reads everyone's.

    The players' walking is reduced to "busy for STEP_FRAMES after a step"; what the room is for
    (sitting down at a seat) is left to the routine's model, through .keys_seen."""

    def __init__(self, con, warp_frames=WARP_FRAMES):
        self.con = con
        self.warp_frames = warp_frames
        self.entered = False
        self.mode = [0x80] * 4            # gUnknown_03000580 (0x80: free to act)
        self.busy = [0] * 4               # frames left of a link player's step
        self.controls_locked = True       # ArePlayerFieldControlsLocked
        self.keys_seen = []               # (frame, player, key) - the keys read back from the link
        self.frames = 0

    def enter(self):
        """Warp in: callback1 and the key function set, then the field callback's task."""
        con = self.con
        con.callback1 = self.callback1
        con.room_mode = "normal"          # sub_80543DC(sub_8055390)
        con.add_task(self._fade_in())

    def _fade_in(self):
        """pret:pokeruby/src/field_fadetransition.c:140 sub_8080A5C"""
        con = self.con
        for _ in range(self.warp_frames):
            yield
        con.set_ready_callback()                           # sub_80084A4
        yield
        while not con.is_link_task_finished():
            yield
        for _ in range(16):                                # sub_8080E70: the fade from black
            yield
        con.set_keys_callback()                            # sub_8007B14
        self.controls_locked = False
        self.entered = True
        con.log.append(("room", "entered"))

    def local_key(self):
        """The key function, gUnknown_03000584."""
        con, mode = self.con, self.con.room_mode
        q_recv, q_send = con.gl.recv_queue["count"], con.gl.send_queue["count"]
        if mode == "normal":                               # pret:pokeruby/src/overworld.c:2140 sub_8055390
            if self.controls_locked:
                return 17
            if q_recv > 4:
                return 27
            if q_send <= 4:
                return self._pad_key()
            return 28
        if mode == "idle":                                 # pret:pokeruby/src/overworld.c:2151 sub_80553E0
            return 17
        if mode == "recv_backed_up":                       # pret:pokeruby/src/overworld.c:2171 sub_8055408
            if q_recv > 2:
                return 17
            self.controls_locked = False
            con.room_mode = "idle"
            return 26
        if mode == "send_backed_up":                       # pret:pokeruby/src/overworld.c:2187 sub_8055438
            if q_send > 2:
                return 17
            self.controls_locked = False
            con.room_mode = "idle"
            return 26
        return 17

    def _pad_key(self):
        """pret:pokeruby/src/overworld.c:2076 sub_80552B0"""
        held, new = self.con.held_keys, self.con.new_keys
        if held & DPAD_UP:
            return 19
        if held & DPAD_DOWN:
            return 18
        if held & DPAD_LEFT:
            return 20
        if held & DPAD_RIGHT:
            return 21
        if new & START_BUTTON:
            return 24
        if new & A_BUTTON:
            return 25
        return 17

    def callback1(self):
        """pret:pokeruby/src/overworld.c:2132 sub_8055354"""
        con = self.con
        self.frames += 1
        me = con.multiplayer_id()
        for i in range(4):                                 # pret:pokeruby/src/overworld.c:2052 sub_8055218
            key = con.keys_in[i]
            if key:
                self.keys_seen.append((self.frames, i, key))
            self._player_key(i, key, i == me)
            if self.busy[i]:
                self.busy[i] -= 1
        con.room_key = self._clamp(self.local_key())       # sub_8055280
        con.keys_in = [17] * 4                             # sub_8055340

    @staticmethod
    def _clamp(key):
        """pret:pokeruby/src/overworld.c:2068 sub_8055280"""
        return key if 17 <= key < 30 else 17

    def _player_key(self, i, key, local):
        """pret:pokeruby/src/overworld.c:1943 sub_8054FF8, for the keys that matter to the link: the
        backed-up queues (27, 28) and the states (22, 23, 26, 29); a step (18-21) keeps the player busy."""
        con = self.con
        idle = not self.busy[i]                            # pret:pokeruby/src/overworld.c:2297 sub_8055618
        if self.mode[i] == 0x80:
            if key in (27, 28) and idle:
                self.mode[i] = 0x81
                if local:
                    con.room_mode = "recv_backed_up" if key == 27 else "send_backed_up"
                    self.controls_locked = True            # sub_80557E8
            elif key in (18, 19, 20, 21) and idle:
                self.busy[i] = STEP_FRAMES
        if key == 23:
            self.mode[i] = 0x83
        elif key == 22:
            self.mode[i] = 0x82
        elif key == 26:
            self.mode[i] = 0x80
            if local:
                con.room_mode = "normal"
        elif key == 29 and self.mode[i] == 0x82:
            self.mode[i] = 0x81
