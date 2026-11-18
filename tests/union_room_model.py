"""
The game's side of the Union Room, for the simulator (docs/UNION_ROOM.md): what Emerald (or
FireRed/LeafGreen) does from walking into the room to reading a partner's trainer card, as the
partner's child. It rides on rfu_game_model (librfu's commands and link_rfu_2's child, ChildLink),
and follows pokeemerald's union_room.c.
"""
import rfu_game_model as RFU
from rfu_game_model import LinkError

IN_UNION_ROOM = 0x40                    # pret:pokeemerald/include/constants/union_room.h:56 IN_UNION_ROOM
ACTIVITY_CARD = 8                       # pret:pokeemerald/include/constants/union_room.h:28 ACTIVITY_CARD
ACTIVITY_ACCEPT = 17                    # pret:pokeemerald/include/constants/union_room.h:39 ACTIVITY_ACCEPT
ACTIVITY_DECLINE = 18                   # pret:pokeemerald/include/constants/union_room.h:40 ACTIVITY_DECLINE
ACTIVITY_TRADE = 4                      # pret:pokeemerald/include/constants/union_room.h:24 ACTIVITY_TRADE
ACTIVITY_CHAT = 5                       # pret:pokeemerald/include/constants/union_room.h:25 ACTIVITY_CHAT
RFU_SERIAL_GAME = 0x0002                # pret:pokeemerald/include/link_rfu.h:23 RFU_SERIAL_GAME
CMD_PACKET = 0x2F00                     # pret:pokeemerald/include/link_rfu.h:10 RFUCMD_SEND_PACKET
LANGUAGE_JAPANESE = 1
# pret:pokeemerald/src/data/union_room.h:1029 sAcceptedActivityIds_Resume (activities 0, 1, 3, 4, 8, 17, 18, 15, 16)
ACCEPTED_RESUME = {IN_UNION_ROOM | a for a in (0, 1, 3, 4, 8, 17, 18, 15, 16)}


def trainer_card(name=b"\xC1\xC2\xC3\xFF\xFF\xFF\xFF\xFF", trainer_id=0xD4C1, version=3):
    """The game's own struct TrainerCard as CreateTrainerCardInBuffer fills it (the fields the
    tests look at), 100 bytes: pret:pokeemerald/src/union_room.c:1631 CreateTrainerCardInBuffer."""
    c = bytearray(100)
    c[0x0E:0x10] = trainer_id.to_bytes(2, "little")
    c[0x30:0x38] = name[:8]
    c[0x38] = version
    return bytes(c)


def find_union_room_player(game, compat=RFU.EN_EMERALD, polls=150):
    """Entering the Union Room (pret:pokeemerald/src/union_room.c:2509 UR_STATE_INIT_LINK): the
    game broadcasts itself as IN_UNION_ROOM and looks for players. A parent shows in its list when
    its serial is accepted and its activity is one the room shows
    (pret:pokeemerald/src/union_room.c:3465 Task_SearchForChildOrParent), Japanese ones dropped by
    a non-Japanese game (the language check at pret:pokeemerald/src/union_room.c:3465 Task_SearchForChildOrParent)."""
    yield ("until_ready",)
    if (yield from game.check_id()) != 0x8001:
        raise LinkError("adapter not found")
    yield from game.command(0x10)
    yield from game.command(0x17, [0x003C0420])
    # (serial, RfuGameData: compatibility, trainer ID, partnerInfo, trade fields, activity at byte 10)
    yield from game.command(0x16, [RFU_SERIAL_GAME | compat << 16, 0, 0, IN_UNION_ROOM, 0, 0xFFFFFFFF])
    yield from game.command(0x1C)
    my_language = compat & 0xF
    for _ in range(polls):
        ack = yield from game.command(0x1D)
        for h in RFU.parse_candidates(ack):
            g = h["gname"]
            if not h["checksum_ok"] or h["serial"] != RFU_SERIAL_GAME:
                continue
            if (IN_UNION_ROOM | g["activity"]) not in ACCEPTED_RESUME or g["started"]:
                continue
            if (g["language"] == LANGUAGE_JAPANESE) != (my_language == LANGUAGE_JAPANESE):
                continue
            yield from game.command(0x1E)
            return h
        yield ("delay", 16 * RFU.MS)
    raise LinkError("nobody in the Union Room")


READY_FINISH_TRADE = 0xABCD            # pret:pokeemerald/include/link.h:72 LINKCMD_READY_FINISH_TRADE
CONFIRM_FINISH_TRADE = 0xDCBA          # pret:pokeemerald/include/link.h:78 LINKCMD_CONFIRM_FINISH_TRADE
MAIL_SIZE = 6 * 36 + 4                 # sizeof(struct Mail) * PARTY_SIZE + 4


class URoomChild:
    """union_room.c's states for the player who walked up to a partner and pressed A, from
    UR_STATE_TRY_COMMUNICATING to reading the card - or, from the trading board, to a trade (the
    partner is player 0, the game player 1)."""

    def __init__(self, child, card, activity=ACTIVITY_CARD, offer=None, anim_frames=120):
        """offer: for a trade, the game's own Pokemon (100 bytes, party form) and its species and
        level, sent with the request (pret:pokeemerald/src/union_room.c:2766 UR_STATE_SEND_TRADE_REQUST)."""
        self.c, self.card, self.activity, self.offer = child, card, activity, offer
        self.state, self.cards, self.answer, self.result = "communicating", {}, None, None
        self.received_mon, self.timer, self.anim_frames = None, 0, anim_frames
        self.say = b"\xC2\xDD\x00\xBE\xCF\xC9\xAB"          # "Hi DUO!" (what the player types)

    def frame(self):
        c = self.c
        if self.state == "communicating":                # pret:pokeemerald/src/union_room.c:2659 UR_STATE_TRY_COMMUNICATING
            if c.received_remote_link_players:
                c.block_send_buffer[:len(self.card)] = self.card
                self.state = "cards"
        elif self.state == "cards":                      # pret:pokeemerald/src/union_room.c:1517 Task_ExchangeCards
            want = (1 << c.player_count) - 1
            if c.block_status() == want:
                for i in range(c.player_count):
                    self.cards[i] = bytes(c.block_recv_buffer[i][:100])
                    c.reset_block_received(i)
                self.state = "choose"
        elif self.state == "choose":                     # pret:pokeemerald/src/union_room.c:2707 UR_STATE_HANDLE_DO_SOMETHING_PROMPT_INPUT
            if c.send_cmd[0] == 0 and c.callback is None:   # Rfu_SendPacket
                extra = [self.offer["species"], self.offer["level"]] if self.offer else [0, 0]
                c.send_cmd[:7] = [CMD_PACKET, IN_UNION_ROOM | self.activity, *extra, 0, 0, 0]
                self.state = "waiting"
        elif self.state == "waiting":                    # pret:pokeemerald/src/union_room.c:2773 UR_STATE_WAIT_FOR_RESPONSE_TO_REQUEST
            r = c.recv_cmds[0][1] if (c.recv_cmds[0][0] & 0xFF00) == CMD_PACKET else 0
            if r == IN_UNION_ROOM | ACTIVITY_ACCEPT:     # pret:pokeemerald/src/union_room.c:4289 PollPartnerYesNoResponse
                self.answer = "accept"
                if self.activity == ACTIVITY_CARD:
                    c.set_standby()                      # pret:pokeemerald/src/union_room.c:2808 UR_STATE_PRINT_CARD_INFO
                    self.state = "reading card"
                elif self.activity == ACTIVITY_TRADE:
                    c.set_standby()                      # pret:pokeemerald/src/union_room.c:3010 UR_STATE_START_ACTIVITY_LINK
                    self.state = "starting trade"
                elif self.activity == ACTIVITY_CHAT:
                    c.set_standby()
                    self.state = "starting chat"
                else:
                    self.state, self.result = "done", "accepted"
            elif r == IN_UNION_ROOM | ACTIVITY_DECLINE:
                self.answer = "decline"
                c.close_task = True                      # UR_STATE_REQUEST_DECLINED: SetCloseLinkCallback
                self.state, self.result = "done", "declined"
        elif self.state == "starting trade":             # then pret:pokeemerald/src/union_room.c:1477 Task_StartUnionRoomTrade
            if c.callback is None and c.all_ready_num:
                if c.init_block_send(self.offer["mon"], 100):
                    self.state = "trading mons"
        elif self.state == "trading mons":
            if c.block_status() == 3:
                self.received_mon = bytes(c.block_recv_buffer[0][:100])
                for i in range(2):
                    c.reset_block_received(i)
                self.state = "mail"
        elif self.state == "mail":
            if c.init_block_send(bytes(MAIL_SIZE), MAIL_SIZE):
                self.state = "trading mail"
        elif self.state == "trading mail":
            if c.block_status() == 3:
                for i in range(2):
                    c.reset_block_received(i)
                self.state, self.timer = "animation", 0  # pret:pokeemerald/src/trade.c:2827 CB2_LinkTrade
        elif self.state == "animation":                  # pret:pokeemerald/src/trade.c:4627 CB2_UpdateLinkTrade
            st = c.block_status()
            if st & 1 and c.block_recv_buffer[0][0] | c.block_recv_buffer[0][1] << 8 == CONFIRM_FINISH_TRADE:
                self.result = "the go-ahead came before the animation ended (TradeMons skipped)"
                self.state = "done"
                return True
            self.timer += 1
            if self.timer >= self.anim_frames:           # DoTradeAnim done: TradeMons, then "ready"
                block = READY_FINISH_TRADE.to_bytes(2, "little") + bytes(18)
                if c.init_block_send(block, 20):
                    self.traded = True
                    self.state = "waiting for go-ahead"
        elif self.state == "waiting for go-ahead":       # pret:pokeemerald/src/trade.c:4650 CB2_WaitTradeComplete
            st = c.block_status()
            if st & 2:
                c.reset_block_received(1)                # (our own "ready", echoed)
            if st & 1:
                ok = c.block_recv_buffer[0][0] | c.block_recv_buffer[0][1] << 8 == CONFIRM_FINISH_TRADE
                c.reset_block_received(0)
                if ok:
                    self.state, self.timer = "saving", 0  # pret:pokeemerald/src/trade.c:4676 CB2_SaveAndEndTrade
                    self.standbys = 0
        elif self.state == "saving":                     # standbys before, after and around the save, then close
            # (CB2_SaveAndEndTrade states 1, 41 and 5: a standby each, with the save and pauses between)
            if c.callback is None:
                self.timer += 1
                if self.timer > 60:
                    if self.standbys < 3:
                        c.set_standby()
                        self.standbys += 1
                        self.timer = 0
                    else:
                        c.close_task = True
                        self.state, self.result = "done", "traded"
        elif self.state == "starting chat":              # then EnterUnionRoomChat (pret:pokeemerald/src/union_room.c:1715)
            if c.callback is None and c.all_ready_num:
                self.chat_log, self.chat_sent, self.chat_state = [], 0, "join"
                self.state = "chat"
        elif self.state == "chat":
            return self.chat_frame()
        elif self.state == "reading card":
            if c.callback is None and c.all_ready_num:   # the standby is over
                c.close_task = True                      # (the player chooses EXIT)
                self.state, self.result = "done", "read the card"
        return self.state == "done"


    # -- the chat (pret:pokeemerald/src/union_room_chat.c), as player 1 -----------------------------
    CHAT_NAME = b"\xC1\xC2\xC3\xFF\xFF\xFF\xFF\xFF"

    def chat_buffer(self, kind, text=b""):
        """PrepareSendBuffer_*: the kind, our name, then the text or (JOIN, LEAVE) our player number."""
        b = bytearray(40)
        b[0], b[1:9] = kind, self.CHAT_NAME
        if kind == CHAT_MESSAGE_CHAT:
            b[9:9 + len(text) + 1] = text + b"\xFF"
        else:
            b[9] = self.c.multiplayer_id
        return bytes(b)

    def chat_frame(self):
        """Chat_Join, Chat_SendMessage, then leaving (Chat_HandleInput's "quit": LEAVE, then wait to be
        dropped - Chat_Drop), with Task_ReceiveChatMessage reading every block as it comes."""
        c = self.c
        st = c.block_status()
        for i in range(c.player_count):                  # Task_ReceiveChatMessage
            if st >> i & 1:
                msg = bytes(c.block_recv_buffer[i][:40])
                c.reset_block_received(i)
                self.chat_log.append((i, msg))
                if i == 0 and msg[0] == CHAT_MESSAGE_DROP:
                    self.chat_state = "dropped"          # CHAT_EXIT_DROPPED (we are not the leader)
        free = c.callback is None and c.send_cmd[0] == 0 and not c.exchange_active
        from_duo = [m for i, m in self.chat_log if i == 0]
        if self.chat_state == "join":
            if free and c.init_block_send(self.chat_buffer(CHAT_MESSAGE_JOIN), 40):
                self.chat_state = "wait hello"
        elif self.chat_state == "wait hello":
            if any(m[0] == CHAT_MESSAGE_CHAT for m in from_duo):
                self.chat_state = "say"
        elif self.chat_state == "say":
            if free and c.init_block_send(self.chat_buffer(CHAT_MESSAGE_CHAT, self.say), 40):
                self.chat_state = "wait reply"
        elif self.chat_state == "wait reply":
            if sum(m[0] == CHAT_MESSAGE_CHAT for m in from_duo) >= 2:
                self.chat_state = "leave"
        elif self.chat_state == "leave":
            if free and c.init_block_send(self.chat_buffer(CHAT_MESSAGE_LEAVE), 40):
                self.chat_state = "wait drop"
        elif self.chat_state == "dropped":                # Chat_Drop: SetCloseLinkCallback
            if free:
                c.close_task = True
                self.state, self.result = "done", "chatted"
        return self.state == "done"


CHAT_MESSAGE_CHAT, CHAT_MESSAGE_JOIN, CHAT_MESSAGE_LEAVE, CHAT_MESSAGE_DROP = 1, 2, 3, 4   # pret:pokeemerald/src/union_room_chat.c:43 CHAT_MESSAGE_CHAT


def union_room_session(game, child, ur, max_frames=3000, drop_every=0):
    """After joining: every frame the adapter says 'data ready', the game reads the host's packet,
    runs link_rfu_2 and the Union Room's states, and answers. Ends once the link is closed.
    drop_every=N: every Nth packet is lost on the way, as in rfu_game_model.receive_gift."""
    child.dropped = 0
    for frame in range(max_frames):
        ack = yield from game.command(0x26)
        if drop_every and frame % drop_every == drop_every - 1:
            child.dropped += 1
            ready = yield from game.change(0x27)
            if ready != 0x99660028:
                raise LinkError(f"expected 'data ready', got {ready:#010x}")
            continue
        child.msc(ack)
        child.main()
        ur.frame()
        child.tasks()
        if child.disconnect_mode:
            cmd, words = child.packet()
            yield from game.command(0x24, words if cmd == 0x25 else [])
            yield from game.command(0x30, [1])
            child.received_remote_link_players = False
            return ur
        if child.errors:
            raise LinkError("; ".join(child.errors))
        cmd, words = child.packet()
        ready = yield from game.change(cmd, words)
        if ready != 0x99660028:
            raise LinkError(f"expected 'data ready', got {ready:#010x}")
    raise LinkError(f"Union Room not finished (state {ur.state}, exchange {child.exchange_state})")


def talk_to_partner(game, compat=RFU.EN_EMERALD, activity=ACTIVITY_CARD, card=None, offer=None, drop_every=0):
    """The whole of milestone 1: find the DUO in the room, walk up, press A, connect, exchange
    link players and cards, ask for `activity` and see the answer."""
    found = yield from find_union_room_player(game, compat=compat)
    yield from RFU.connect_to(game, found["id"])                 # TryConnectToUnionRoomParent
    yield from RFU.send_child_name(game, RFU.child_name_bytes())
    yield from RFU.wait_join_status(game)
    child = RFU.ChildLink()
    ur = URoomChild(child, card or trainer_card(), activity, offer=offer)
    yield from union_room_session(game, child, ur, max_frames=6000, drop_every=drop_every)
    return found, child, ur
