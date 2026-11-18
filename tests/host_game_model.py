"""
The game as wireless host, the DUO joining (docs/WIRELESS_HOST.md), for the simulator: what Emerald
(or FireRed/LeafGreen) asks of its adapter while leading a group, as far as stage H1 - a child
connects and gives its name. It rides on rfu_game_model's command layer and NI receiver, and follows
librfu 1026 and the link manager (cited).
"""
import rfu_game_model as RFU
from rfu_game_model import (LinkError, NIReceiver, NISender, LCOM_UNI, BUSY, RECV_LAST, RECV_SUCCESS, SENDING,
                            SEND_START, SEND_SUCCESS)

ACCEPTED_SERIALS = (0x0002, 0x7F7D, 0x7F7F)  # pret:pokeemerald/src/link_rfu_2.c:227 sAcceptedSerialNos
ACTIVITY_WONDER_CARD2 = 23                   # (Mystery Gift with a friend: "Send")


def parse_child_frames(ack):
    """pret:pokeemerald/src/librfu_rfu.c:1924 rfu_STC_PARENT_analyzeRecvPacket: the first data word
    shifted right 8 holds a 5-bit byte count per child slot; the frames follow, slot 0's first, each
    with a child's 2-byte header (pret:pokeemerald/src/librfu_rfu.c:85 llsf_struct)."""
    if len(ack) < 2:
        return []
    counts = [(ack[1] >> (8 + 5 * i)) & 0x1F for i in range(4)]
    raw = b"".join(w.to_bytes(4, "little") for w in ack[2:])
    out, at = [], 0
    for slot, count in enumerate(counts):
        end = at + count
        while end - at >= 2:
            h = raw[at] | raw[at + 1] << 8
            size = h & 0x1F
            out.append(dict(slot=slot, size=size, phase=h >> 5 & 3, n=h >> 7 & 3, ack=h >> 9 & 1,
                            state=h >> 10 & 0xF, recv_first=h >> 14 & 2, data=raw[at + 2:at + 2 + size]))
            at += 2 + size
        at = end
    return out


def parent_ack_frame(r, slot=0):
    """The parent's acknowledgement for an NI chunk: a 3-byte header, size 0, addressed to `slot`."""
    h = (r.state & 0xF) << 14 | 1 << 13 | r.phase << 9 | r.n[r.phase] << 11 | (1 << slot) << 18
    return h.to_bytes(3, "little")


def host_and_wait_child(game, compat=RFU.EN_EMERALD, activity=ACTIVITY_WONDER_CARD2, polls=300):
    """The leader's link manager (pret:pokeemerald/src/AgbRfu_LinkManager.c:432
    rfu_LMAN_manager_entity): reset, config, game data, start searching for children
    (pret:pokeemerald/src/librfu_rfu.c:505 rfu_REQ_startSearchChild), then poll
    (pret:pokeemerald/src/librfu_rfu.c:557 rfu_REQ_pollSearchChild) until a child is listed - with
    librfu 1026 it is connected at once (pret:pokeemerald/src/librfu_rfu.c:592 rfu_STC_readChildList)."""
    yield ("until_ready",)
    if (yield from game.check_id()) != 0x8001:
        raise LinkError("adapter not found")
    yield from game.command(0x10)
    yield from game.command(0x17, [0x003C0420])
    yield from game.command(0x16, [0x0002 | compat << 16, 0, 0, activity, 0, 0xFFFFFFFF])
    yield from game.command(0x13)
    yield from game.command(0x19)
    for _ in range(polls):
        ack = yield from game.command(0x1A)
        if (ack[0] >> 8) & 0xFF >= 1:
            child = dict(id=ack[1] & 0xFFFF, slot=ack[1] >> 16 & 0xFF)
            yield from game.command(0x1B)
            return child
        yield ("delay", 16 * RFU.MS)
    raise LinkError("no child joined")


def receive_child_name(game, slot=0, max_frames=240):
    """pret:pokeemerald/src/AgbRfu_LinkManager.c:1001 rfu_LMAN_PARENT_checkRecvChildName: the new
    child's serial number, game name and user name arrive over NI, data type 1; a serial outside the
    accepted list is disconnected. Each frame: read the child's frames (0x26), acknowledge, hand over."""
    r = NIReceiver(26)
    for _ in range(max_frames):
        ack = yield from game.command(0x26)
        frames = [f for f in parse_child_frames(ack) if f["slot"] == slot]
        r.end_seen = not frames
        for f in frames:
            if f["recv_first"] == 0 and f["state"] != LCOM_UNI and not f["ack"]:
                r.receive(f["state"], f["phase"], f["n"], f["data"])
        if r.state == RECV_LAST and not r.end_seen:
            r.state = RECV_SUCCESS
        if r.state == RECV_SUCCESS:
            name = bytes(r.buf)
            serial = name[0] | name[1] << 8
            if r.type != 1:
                raise LinkError(f"the child's first NI data was type {r.type}, not its name")
            if serial not in ACCEPTED_SERIALS:
                raise LinkError(f"the child's serial {serial:#06x} is not accepted: disconnected")
            return dict(serial=serial, gname=name[2:15], uname=name[17:26])
        if r.state & BUSY:
            sub = parent_ack_frame(r, slot)
            pad = sub + bytes(-len(sub) % 4)
            words = [len(sub)] + [int.from_bytes(pad[i:i + 4], "little") for i in range(0, len(pad), 4)]
            ready = yield from game.change(0x25, words)
        else:
            ready = yield from game.change(0x27)
        if ready != 0x99660028:
            raise LinkError(f"expected 'data ready', got {ready:#010x}")
    raise LinkError(f"the child's name never arrived (receiver state {r.state:#06x})")


RFU_STATUS_JOIN_GROUP_OK, RFU_STATUS_JOIN_GROUP_NO = 5, 6   # pret:pokeemerald/include/link_rfu.h:40 RFU_STATUS_JOIN_GROUP_OK


class ParentNISender(NISender):
    """librfu's NI sender on the parent: the same states as the child's, with the parent's 3-byte
    sub-frame header naming the slots it is for (pret:pokeemerald/src/librfu_rfu.c:85 llsf_struct)."""

    def __init__(self, data, slot=0, sub_frame=8, data_type=0):
        super().__init__(data, sub_frame=sub_frame, data_type=data_type)
        self.slot = slot
        self.payload = sub_frame - 3
        self.ctrl = bytes([data_type]) + self.payload.to_bytes(2, "little") + self.dataSize.to_bytes(4, "little")
        self.src = self.ctrl

    def construct(self):
        buf = self._buf()
        if self.state == SENDING:
            for _ in range(4):
                if self.now[self.phase] < len(buf):
                    break
                self.phase = (self.phase + 1) & 3
        if self.state == SENDING:
            size = min(self.payload, len(buf) - self.now[self.phase])
        else:
            size = self.payload if self.remain >= self.payload else max(0, self.remain)
        h = (self.state & 0xF) << 14 | self.phase << 9 | self.n[self.phase] << 11 | (1 << self.slot) << 18 | size
        out = h.to_bytes(3, "little") + buf[self.now[self.phase]:self.now[self.phase] + size]
        if self.state == SENDING:
            self.phase = (self.phase + 1) & 3
        self.frames_sent += 1
        return out


def send_join_status(game, status=RFU_STATUS_JOIN_GROUP_OK, slot=0, max_frames=240):
    """The leader's answer to a child that asked to join: one status byte over NI, sub-frames of 8
    (pret:pokeemerald/src/link_rfu_2.c:1691, SendRfuStatusToPartner's rfu_NI_setSendData), each chunk
    acknowledged by the child."""
    s = ParentNISender(bytes([status]), slot=slot)
    for _ in range(max_frames):
        ack = yield from game.command(0x26)
        for f in parse_child_frames(ack):
            if f["slot"] == slot and f["recv_first"] == 0 and f["state"] != LCOM_UNI and f["ack"]:
                s.on_ack(f["state"], f["phase"], f["n"])
        if s.state == SEND_SUCCESS:
            return s
        sub = s.construct()
        pad = sub + bytes(-len(sub) % 4)
        words = [len(sub)] + [int.from_bytes(pad[i:i + 4], "little") for i in range(0, len(pad), 4)]
        ready = yield from game.change(0x25, words)
        s.after_send()
        if s.state == SEND_SUCCESS:
            return s
        if ready != 0x99660028:
            raise LinkError(f"expected 'data ready', got {ready:#010x}")
    raise LinkError(f"join answer not delivered (sender state {s.state:#06x})")


def lead_and_accept(game, compat=RFU.EN_EMERALD, answer=RFU_STATUS_JOIN_GROUP_OK):
    """Stages H1 and H2's first half: host, see the DUO join, read its name, answer it."""
    child = yield from host_and_wait_child(game, compat=compat)
    name = yield from receive_child_name(game, child["slot"])
    yield from send_join_status(game, answer, child["slot"])
    return child, name


# -- stage H2b: link_rfu_2 with the game as parent, the DUO as its child ---------------------------
from rfu_game_model import (CMD_PLAYER_IDS, CMD_PLAYER_IDS_NEW, CMD_BLOCK_INIT, CMD_BLOCK, CMD_BLOCK_REQ,
                            CMD_READY_CLOSE, CMD_READY_EXIT, CMD_DISCONNECT, COMM_SLOT_LENGTH, MAX_RFU_PLAYERS,
                            BLOCK_REQUEST_SIZES, RECV_READY, RECV_RECEIVING, RECV_FINISHED, MAGIC, link_player_block)

RFU_CHILD_MAX = 4
# pret:pokeemerald/src/link_rfu_2.c:171 sSlotToLinkPlayerTableId (indexed by a slot bit mask)
SLOT_TO_LINK_PLAYER_TABLE_ID = [0, 0, 1, 1, 2, 2, 2, 2, 3]


class ParentLink:
    """The game's link_rfu_2 as parent once its slots are finalized (one child, in slot 0), with the
    initial link-player exchange. Rows of `recv_cmds` (gRecvCmds) are link players; the UNI table
    it sends every frame (gRfu.recvCmds) is last frame's gRecvCmds."""

    def __init__(self, parent_slots=1, player_block=None):
        self.parent_slots, self.disconnect_slots = parent_slots, 0
        self.send_cmd = [0] * 8                                        # gSendCmd
        self.recv_cmds = [[0] * 7 for _ in range(MAX_RFU_PLAYERS)]     # gRecvCmds
        self.uni_table = bytes(70)                                     # gRfu.recvCmds
        self.child_recv_buffer = [bytes(COMM_SLOT_LENGTH)] * RFU_CHILD_MAX
        self.child_recv_ids = [0xFF] * RFU_CHILD_MAX                   # ParentResetChildRecvMetadata
        self.child_recv_errors = [0] * RFU_CHILD_MAX
        self.link_player_idx = [0] * RFU_CHILD_MAX
        self.set_link_player_ids_from_slots(parent_slots)
        self.player_count, self.multiplayer_id = 0, 0
        self.recv_block = [dict(next=0, count=0, owner=0, flags=0, receiving=RECV_READY) for _ in range(MAX_RFU_PLAYERS)]
        self.block_received = [False] * MAX_RFU_PLAYERS
        self.num_blocks_received = [0] * MAX_RFU_PLAYERS
        self.block_recv_buffer = [bytearray(256) for _ in range(MAX_RFU_PLAYERS)]
        self.block_send_buffer = bytearray(256)
        self.send_block = dict(next=0, count=0, payload=b"", sending=False, owner=0)
        self.callback, self.block_send_attempts, self.block_request_type = None, 0, 0
        self.local_block = player_block or link_player_block(trainer_id=0x0003D4C1)
        self.link_players = [None] * MAX_RFU_PLAYERS
        self.received_remote_link_players, self.exchange_state, self.exchange_active = False, 0, True
        self.errors, self.child_cmds, self.frames = [], [], 0
        self.ready_exit_standby, self.ready_close_link, self.all_ready_num = [False] * 5, [False] * 5, 0
        self.close_task, self.disconnect = False, False

    def set_link_player_ids_from_slots(self, base_slots):
        """pret:pokeemerald/src/link_rfu_2.c:384 SetLinkPlayerIdsFromSlots (addSlots -1: initialize)."""
        base_id = 1
        for i in range(RFU_CHILD_MAX):
            if base_slots >> i & 1:
                self.link_player_idx[i] = base_id
                base_id += 1

    # -- RfuMain1_Parent -------------------------------------------------------------------------
    def main1(self):
        """pret:pokeemerald/src/link_rfu_2.c:717 ReadAllPlayerRecvCmds, then the UNI send to the children
        (pret:pokeemerald/src/link_rfu_2.c:778 RfuMain1_Parent): the parent's 3-byte header (UNI state,
        the slots it is for, the size), the 70-byte table. Returns 0x25's words: total bytes first."""
        self.uni_table = b"".join((c & 0xFFFF).to_bytes(2, "little") for row in self.recv_cmds for c in row)
        self.recv_cmds = [[0] * 7 for _ in range(MAX_RFU_PLAYERS)]
        h = LCOM_UNI << 14 | self.parent_slots << 18 | len(self.uni_table)
        sub = h.to_bytes(3, "little") + self.uni_table
        pad = sub + bytes(-len(sub) % 4)
        return [len(sub)] + [int.from_bytes(pad[i:i + 4], "little") for i in range(0, len(pad), 4)]

    def receive(self, ack):
        """rfu_REQ_recvData: each child's UNI frame lands in its receive buffer
        (pret:pokeemerald/src/librfu_rfu.c:2007 rfu_STC_UNI_receive)."""
        for f in parse_child_frames(ack):
            if f["recv_first"] == 0 and f["state"] == LCOM_UNI and self.parent_slots >> f["slot"] & 1:
                if f["size"] > COMM_SLOT_LENGTH:
                    self.errors.append(f"child UNI frame of {f['size']} bytes: too big for its buffer")
                else:
                    self.child_recv_buffer[f["slot"]] = f["data"] + bytes(COMM_SLOT_LENGTH - f["size"])

    # -- RfuMain2_Parent -------------------------------------------------------------------------
    def main2(self):
        """pret:pokeemerald/src/link_rfu_2.c:824 RfuMain2_Parent: each child's new command, its sequence
        number checked (byte 0, top three bits, one more than last time), becomes its link player's row;
        the parent's own command goes in row 0 (pret:pokeemerald/src/link_rfu_2.c:733 MoveSendCmdToRecv);
        then the commands are handled and the link callback runs."""
        self.frames += 1
        for i in range(RFU_CHILD_MAX):
            if not self.parent_slots >> i & 1:
                continue
            buf = bytearray(self.child_recv_buffer[i])
            if buf[1]:
                if self.child_recv_ids[i] != 0xFF and buf[0] >> 5 != (self.child_recv_ids[i] + 1) & 7:
                    self.child_recv_errors[i] += 1
                    if self.child_recv_errors[i] > 4:
                        self.errors.append(f"slot {i}: sequence numbers out of step five times (F_RFU_ERROR_8|1)")
                else:
                    self.child_recv_ids[i] = buf[0] >> 5
                    self.child_recv_errors[i] = 0
                    buf[0] &= 0x1F
                    row = self.link_player_idx[i]
                    self.recv_cmds[row] = [buf[2 * j] | buf[2 * j + 1] << 8 for j in range(7)]
                    self.child_cmds.append(self.recv_cmds[row][0])
            self.child_recv_buffer[i] = bytes(COMM_SLOT_LENGTH)        # (cleared as read)
        self.recv_cmds[0] = list(self.send_cmd[:7])
        self.send_cmd = [0] * 8
        self.handle_receive()
        if self.callback:                                              # CallRfuFunc
            self.callback()

    def handle_receive(self):
        """pret:pokeemerald/src/link_rfu_2.c:1075 RfuHandleReceiveCommand, the parent's cases."""
        for i in range(MAX_RFU_PLAYERS):
            c = self.recv_cmds[i]
            kind = c[0] & 0xFF00
            rb = self.recv_block[i]
            if kind == CMD_BLOCK_INIT:
                if rb["receiving"] == RECV_READY:
                    rb.update(next=0, count=c[1], owner=c[2], flags=0, receiving=RECV_RECEIVING)
                    self.block_received[i] = False
            elif kind == CMD_BLOCK:
                if rb["receiving"] == RECV_RECEIVING:
                    n = c[0] & 0xFF
                    rb["next"] = n
                    rb["flags"] |= 1 << n
                    for j in range(6):
                        if n * 12 + 2 * j + 1 < 256:
                            self.block_recv_buffer[i][n * 12 + 2 * j:n * 12 + 2 * j + 2] = c[j + 1].to_bytes(2, "little")
                    if rb["flags"] == (1 << rb["count"]) - 1:
                        rb["receiving"] = RECV_FINISHED
                        if i:                                          # Rfu_SetBlockReceivedFlag (parent)
                            self.num_blocks_received[i] = 1
                        else:
                            self.block_received[i] = True
            elif kind == CMD_BLOCK_REQ:
                size = BLOCK_REQUEST_SIZES[c[1]] if c[1] < len(BLOCK_REQUEST_SIZES) else 0
                self.init_block_send(self.block_send_buffer, size)
            elif kind == CMD_READY_CLOSE:
                self.ready_close_link[i] = True
            elif kind == CMD_READY_EXIT:
                if self.all_ready_num == c[1]:
                    self.ready_exit_standby[i] = True
            elif kind == CMD_DISCONNECT and i:
                self.errors.append(f"disconnect command from player {i}")
            if self.num_blocks_received[i]:                            # four frames' grace for a child's block
                if self.num_blocks_received[i] == 4:
                    self.block_received[i] = True
                    self.num_blocks_received[i] = 0
                else:
                    self.num_blocks_received[i] += 1

    # -- blocks ----------------------------------------------------------------------------------
    def prepare(self, cmd):
        """pret:pokeemerald/src/link_rfu_2.c:1233 RfuPrepareSendBuffer."""
        self.send_cmd[0] = cmd
        if cmd == CMD_BLOCK_INIT:
            self.send_cmd[1] = self.send_block["count"]
            self.send_cmd[2] = self.send_block["owner"] + 0x80
        elif cmd == CMD_BLOCK_REQ:
            if self.all_ready_to_receive():
                self.send_cmd[1] = self.block_request_type
        elif cmd in (CMD_READY_EXIT, CMD_READY_CLOSE):
            self.send_cmd[1] = self.all_ready_num
        elif cmd in (CMD_PLAYER_IDS, CMD_PLAYER_IDS_NEW):
            slots = self.parent_slots ^ self.disconnect_slots
            self.player_count = bin(slots).count("1") + 1
            self.send_cmd[1] = self.player_count
            self.send_cmd[2] = self.link_player_idx[0] | self.link_player_idx[1] << 8
            self.send_cmd[3] = self.link_player_idx[2] | self.link_player_idx[3] << 8

    def init_block_send(self, src, size):
        """pret:pokeemerald/src/link_rfu_2.c:1289 Rfu_InitBlockSend."""
        if self.callback is not None or self.send_cmd[0] or self.send_block["sending"]:
            return False
        sb = self.send_block
        sb.update(owner=self.multiplayer_id, sending=True, count=size // 12 + (size % 12 != 0), next=0)
        if src is not self.block_send_buffer:
            self.block_send_buffer[:len(src)] = src
        sb["payload"] = bytes(self.block_send_buffer)
        self.prepare(CMD_BLOCK_INIT)
        self.callback = self.handle_block_send
        self.block_send_attempts = 0
        return True

    def handle_block_send(self):
        """The parent sends its block's announcement three more times, then the chunks
        (HandleBlockSend's MODE_PARENT branch)."""
        if self.send_cmd[0] == 0:
            self.prepare(CMD_BLOCK_INIT)
            self.block_send_attempts += 1
            if self.block_send_attempts > 2:
                self.callback = self.send_next_block

    def send_next_block(self):
        sb, p = self.send_block, self.send_block["payload"]
        n = sb["next"]
        self.send_cmd = [CMD_BLOCK | n] + [p[n * 12 + 2 * i] | p[n * 12 + 2 * i + 1] << 8 for i in range(6)] + [0]
        sb["next"] += 1
        if sb["count"] <= sb["next"]:
            sb["sending"] = False
            self.callback = self.send_last_block

    def send_last_block(self):
        self.callback = None                                           # (the parent checks nothing)

    def all_ready_to_receive(self):                                    # AreAllPlayersReadyToReceive
        return all(rb["receiving"] == RECV_READY for rb in self.recv_block)

    def block_status(self):                                            # Rfu_GetBlockReceivedStatus
        return sum(1 << i for i in range(MAX_RFU_PLAYERS)
                   if self.recv_block[i]["receiving"] == RECV_FINISHED and self.block_received[i])

    def reset_block_received(self, i):
        self.block_received[i] = False
        self.recv_block[i]["receiving"] = RECV_READY

    # -- standby and closing, as the leader --------------------------------------------------------
    def set_standby(self):
        """pret:pokeemerald/src/link_rfu_2.c:1554 Rfu_SetLinkStandbyCallback."""
        if self.callback is None:
            self.callback = self.link_standby

    def link_standby(self):
        """pret:pokeemerald/src/link_rfu_2.c:1520 Rfu_LinkStandby, the leader's branch: wait for every
        member's READY_EXIT_STANDBY, then send its own (twice, LinkLeaderReadyToExitStandby)."""
        if all(self.ready_exit_standby[i] for i in range(1, self.player_count)) and self.send_cmd[0] == 0:
            self.prepare(CMD_READY_EXIT)
            self.callback = self.leader_ready_to_exit

    def leader_ready_to_exit(self):
        if self.send_cmd[0] == 0:
            self.prepare(CMD_READY_EXIT)
            self.callback = self.send_ready_exit_until_all_ready

    def send_ready_exit_until_all_ready(self):
        """pret:pokeemerald/src/link_rfu_2.c:1481 SendReadyExitStandbyUntilAllReady (the leader never resends)."""
        if all(self.ready_exit_standby[i] for i in range(self.player_count)):
            self.ready_exit_standby = [False] * 5
            self.all_ready_num += 1
            self.callback = None

    def tasks(self):
        """pret:pokeemerald/src/link_rfu_2.c:1465 Task_TryReadyCloseLink."""
        if self.close_task and self.callback is None:
            self.close_task = False
            self.callback = self.send_ready_close

    def send_ready_close(self):                                    # SendReadyCloseLink
        if self.send_cmd[0] == 0 and not self.exchange_active:
            self.prepare(CMD_READY_CLOSE)
            self.callback = self.wait_all_ready_close

    def wait_all_ready_close(self):
        """pret:pokeemerald/src/link_rfu_2.c:1428 WaitAllReadyToCloseLink: every player ready, then (next
        frame, as the parent) DisconnectRfu - rfu_REQ_disconnect, and the adapter is powered down."""
        if sum(self.ready_close_link) == self.player_count:
            self.callback = self.try_disconnect

    def try_disconnect(self):
        self.disconnect = True
        self.callback = None

    # -- Task_PlayerExchange (parent path) -------------------------------------------------------
    def player_exchange(self):
        """pret:pokeemerald/src/link_rfu_2.c:1754 Task_PlayerExchange: the leader names the players
        (SEND_PLAYER_IDS), asks everyone for their link player (BLOCK_REQ, size NONE: 200 bytes),
        sends its own the same way, and reads them all when every block is in
        (pret:pokeemerald/src/link.c:1768 LinkPlayerFromBlock)."""
        s = self.exchange_state
        if s == 0:
            if self.all_ready_to_receive():
                self.block_received = [False] * MAX_RFU_PLAYERS
                self.block_send_buffer[:len(self.local_block)] = self.local_block
                self.exchange_state = 1
        elif s == 1:
            self.prepare(CMD_PLAYER_IDS_NEW if self.received_remote_link_players else CMD_PLAYER_IDS)
            self.exchange_state = 101
        elif s == 101:
            if self.send_cmd[0] == 0:
                self.exchange_state = 2
        elif s == 2:
            if self.player_count:
                self.exchange_state = 3
        elif s == 3:
            if self.all_ready_to_receive():
                self.block_request_type = 0                            # BLOCK_REQ_SIZE_NONE
                self.prepare(CMD_BLOCK_REQ)
                self.exchange_state = 4
        elif s == 4:
            if all(self.recv_block[i]["receiving"] == RECV_FINISHED and self.block_received[i]
                   for i in range(self.player_count)):
                self.exchange_state = 5
        elif s == 5:
            for i in range(self.player_count):
                block = bytes(self.block_recv_buffer[i][:60])
                self.link_players[i] = block[16:44]
                if block[:16].split(b"\0")[0] != MAGIC or block[44:60].split(b"\0")[0] != MAGIC:
                    self.errors.append(f"link player {i}: bad magic -> CB2_LinkError")
                self.reset_block_received(i)
            self.exchange_state = 6
        elif s == 6:
            self.received_remote_link_players = True
            self.exchange_active = False


def null_frames(game, frames):
    """Between the "OK" and the slots being finalized (Task_SendMysteryGift waits 120 frames,
    pret:pokeemerald/src/union_room.c:1880): each frame the parent reads (0x26) and sends without
    handing the clock over; with nothing to send, librfu's null frame - one byte, 0xFF - goes out
    on the first frames, then one frame in 16 (pret:pokeemerald/src/librfu_rfu.c:1645 rfu_REQ_sendData)."""
    ember, null = 16, 0
    for _ in range(frames):
        yield from game.command(0x26)
        if ember:
            ember -= 1
        else:
            null += 1
        if ember or not null & 0xF:
            yield from game.command(0x24, [1, 0xFF])
        yield ("delay", 16 * RFU.MS)


def lead_link(game, parent, max_frames=600, extra_frames=30):
    """Each frame once finalized: RfuMain1_Parent (send the table, hand the clock over until the
    adapter says the children's data are in), RfuMain2_Parent (read them, handle them), then the
    tasks. Ends a little after the link players are in."""
    done_at = None
    for frame in range(max_frames):
        words = parent.main1()
        ready = yield from game.change(0x25, words)
        if ready != 0x99660028:
            raise LinkError(f"expected 'data ready', got {ready:#010x}")
        ack = yield from game.command(0x26)
        parent.receive(ack)
        parent.main2()
        if parent.exchange_active:
            parent.player_exchange()
        if parent.errors:
            raise LinkError("; ".join(parent.errors))
        if parent.received_remote_link_players and done_at is None:
            done_at = frame
        if done_at is not None and frame - done_at >= extra_frames:
            return parent
    raise LinkError(f"link players not exchanged (exchange state {parent.exchange_state}, "
                    f"child commands seen {len(parent.child_cmds)})")


def lead_and_link(game, compat=RFU.EN_EMERALD, wait_frames=121):
    """Stages H1 to H2b: host, accept the DUO, wait as Task_SendMysteryGift does, finalize the slots
    (pret:pokeemerald/src/link_rfu_2.c:498 InitParentSendData), exchange link players."""
    child, name = yield from lead_and_accept(game, compat=compat)
    yield from null_frames(game, wait_frames)
    parent = ParentLink(parent_slots=1 << child["slot"])
    yield from lead_link(game, parent)
    return child, name, parent


# -- stage H3: Mystery Gift with a friend, "Send" - the game's server, the DUO as client -------------
from rfu_game_model import MGLink, crc16

# pret:pokeemerald/include/mystery_gift_client.h:18 (client script instructions)
(CLI_NONE, CLI_RETURN, CLI_RECV, CLI_SEND_LOADED, CLI_COPY_RECV, CLI_YES_NO, CLI_COPY_RECV_IF_N, CLI_COPY_RECV_IF,
 CLI_LOAD_GAME_DATA, CLI_SAVE_NEWS, CLI_SAVE_CARD, CLI_PRINT_MSG, CLI_COPY_MSG, CLI_ASK_TOSS, CLI_LOAD_TOSS_RESPONSE,
 CLI_RUN_MEVENT_SCRIPT, CLI_SAVE_STAMP, CLI_SAVE_RAM_SCRIPT, CLI_RECV_EREADER_TRAINER, CLI_SEND_STAT,
 CLI_SEND_READY_END) = range(21)
CLI_MSG_CARD_RECEIVED, CLI_MSG_NEWS_RECEIVED, CLI_MSG_HAD_CARD, CLI_MSG_HAD_NEWS = 2, 3, 5, 7
CLI_MSG_COMM_CANCELED, CLI_MSG_CANT_ACCEPT, CLI_MSG_COMM_ERROR, CLI_MSG_BUFFER_FAILURE = 9, 10, 11, 14
# pret:pokeemerald/include/mystery_gift_link.h:9 MG_LINKID_*
(MG_CLIENT_SCRIPT, MG_GAME_DATA, MG_GAME_STAT, MG_RESPONSE, MG_READY_END, MG_DYNAMIC_MSG, MG_CARD, MG_NEWS,
 MG_STAMP, MG_RAM_SCRIPT) = range(16, 26)
SVR_MSG_CARD_SENT, SVR_MSG_NEWS_SENT, SVR_MSG_HAS_CARD, SVR_MSG_HAS_NEWS = 2, 3, 5, 7
SVR_MSG_CLIENT_CANCELED, SVR_MSG_CANT_SEND_GIFT_1 = 9, 10
HAS_NO_CARD, HAS_SAME_CARD, HAS_DIFF_CARD = 0, 1, 2                # pret:pokeemerald/include/constants/mystery_gift.h:28
SEND_TYPE_DISALLOWED, SEND_TYPE_ALLOWED = 0, 1


def client_script(*cmds):
    """struct MysteryGiftClientCmd: u32 instruction, u32 parameter."""
    return b"".join(i.to_bytes(4, "little") + p.to_bytes(4, "little") for i, p in cmds)


# pret:pokeemerald/src/mystery_gift_scripts.c:18 onwards (the client scripts the "Send" server uses)
CS_SEND_GAME_DATA = client_script((CLI_LOAD_GAME_DATA, 0), (CLI_SEND_LOADED, 0), (CLI_RECV, MG_CLIENT_SCRIPT), (CLI_COPY_RECV, 0))
CS_CANT_ACCEPT = client_script((CLI_SEND_READY_END, 0), (CLI_RETURN, CLI_MSG_CANT_ACCEPT))
CS_SAVE_CARD = client_script((CLI_RECV, MG_CARD), (CLI_SAVE_CARD, 0), (CLI_RECV, MG_RAM_SCRIPT), (CLI_SAVE_RAM_SCRIPT, 0),
                             (CLI_SEND_READY_END, 0), (CLI_RETURN, CLI_MSG_CARD_RECEIVED))
CS_SAVE_NEWS = client_script((CLI_RECV, MG_NEWS), (CLI_SAVE_NEWS, 0), (CLI_SEND_LOADED, 0), (CLI_RECV, MG_CLIENT_SCRIPT),
                             (CLI_COPY_RECV, 0))
CS_HAD_NEWS = client_script((CLI_SEND_READY_END, 0), (CLI_RETURN, CLI_MSG_HAD_NEWS))
CS_NEWS_RECEIVED = client_script((CLI_SEND_READY_END, 0), (CLI_RETURN, CLI_MSG_NEWS_RECEIVED))
CS_ASK_TOSS = client_script((CLI_ASK_TOSS, 0), (CLI_LOAD_TOSS_RESPONSE, 0), (CLI_SEND_LOADED, 0),
                            (CLI_RECV, MG_CLIENT_SCRIPT), (CLI_COPY_RECV, 0))
CS_HAD_CARD = client_script((CLI_SEND_READY_END, 0), (CLI_RETURN, CLI_MSG_HAD_CARD))
CS_DYNAMIC_ERROR = client_script((CLI_RECV, MG_DYNAMIC_MSG), (CLI_COPY_MSG, 0), (CLI_SEND_READY_END, 0),
                                 (CLI_RETURN, CLI_MSG_BUFFER_FAILURE))

GAME_DATA_VALID_VAR, GIFT_TYPE_1, GIFT_TYPE_2 = 0x101, 1 << 2, 1 << 9   # pret:pokeemerald/src/mystery_gift.c:342


def validate_link_game_data(d, is_news):
    """pret:pokeemerald/src/mystery_gift.c:390 MysteryGift_ValidateLinkGameData (struct
    MysteryGiftLinkGameData: u32 at 0, u16 at 4, u32 at 8, u16 at 0xC, u32 at 0x10, flagId at 0x14)."""
    u16 = lambda o: d[o] | d[o + 1] << 8
    u32 = lambda o: int.from_bytes(d[o:o + 4], "little")
    if u32(0) != GAME_DATA_VALID_VAR or not u16(4) & 1 or not u32(8) & 1:
        return False
    if not is_news and (not u16(0xC) & GIFT_TYPE_1 or not u32(0x10) & (GIFT_TYPE_2 | 0x180)):
        return False
    return True


class MGServer:
    """pret:pokeemerald/src/mystery_gift_server.c with gMysteryGiftServerScript_SendWonderCard and
    _SendWonderNews (pret:pokeemerald/src/mystery_gift_scripts.c:193): the game sharing its saved card
    (and RAM script) or news with the player linked as 1. Each script step is one call of run(), as
    MysteryGiftServer_CallFunc is called once a frame."""

    def __init__(self, parent, card=None, ram_script=b"", news=None):
        self.link = MGLink(parent, 0, 1)                           # MysteryGiftServer_Init(svr, script, 0, 1)
        self.is_news = news is not None
        card = bytearray(card or bytes(0x14C))
        if card[8] >> 6 == SEND_TYPE_ALLOWED:                      # DisableWonderCardSending
            card[8] = card[8] & 0x3F | SEND_TYPE_DISALLOWED << 6
        self.card, self.news = bytes(card), news
        # SVR_COPY_SAVED_RAM_SCRIPT sets the pointer but not the size, so SVR_LOAD_RAM_SCRIPT sends
        # with size 0, which the link layer makes MG_LINK_BUFFER_SIZE: 1024 bytes from the save.
        self.ram_script = bytes(ram_script) + bytes(max(0, 0x400 - len(ram_script)))
        self.func, self.param, self.result, self.history = "run", 0, None, []
        self.recv_buf = b""
        self.script = self._main()

    def _main(self):
        if self.is_news:
            yield ("load", MG_CLIENT_SCRIPT, CS_SEND_GAME_DATA)
            yield ("send",)
            yield ("recv", MG_GAME_DATA)
            if not validate_link_game_data(self.recv_buf, True):
                yield from self._end(CS_CANT_ACCEPT, SVR_MSG_CANT_SEND_GIFT_1)
                return
            yield ("load", MG_CLIENT_SCRIPT, CS_SAVE_NEWS)
            yield ("send",)
            yield ("load", MG_NEWS, self.news)
            yield ("send",)
            yield ("recv", MG_RESPONSE)
            if int.from_bytes(self.recv_buf[:4], "little") == 1:  # SVR_READ_RESPONSE: not saved
                yield from self._end(CS_HAD_NEWS, SVR_MSG_HAS_NEWS)
                return
            yield from self._end(CS_NEWS_RECEIVED, SVR_MSG_NEWS_SENT)
            return
        yield ("load", MG_CLIENT_SCRIPT, CS_SEND_GAME_DATA)
        yield ("send",)
        yield ("recv", MG_GAME_DATA)
        game_data = self.recv_buf
        if not validate_link_game_data(game_data, False):
            yield from self._end(CS_CANT_ACCEPT, SVR_MSG_CANT_SEND_GIFT_1)
            return
        their_flag = game_data[0x14] | game_data[0x15] << 8         # MysteryGift_CompareCardFlags
        ours = self.card[0] | self.card[1] << 8
        has = HAS_NO_CARD if their_flag == 0 else HAS_SAME_CARD if their_flag == ours else HAS_DIFF_CARD
        self.history.append(("has", has))
        if has == HAS_SAME_CARD:
            yield from self._end(CS_HAD_CARD, SVR_MSG_HAS_CARD)
            return
        if has == HAS_DIFF_CARD:
            yield ("load", MG_CLIENT_SCRIPT, CS_ASK_TOSS)
            yield ("send",)
            yield ("recv", MG_RESPONSE)
            if int.from_bytes(self.recv_buf[:4], "little") != 0:   # kept the old card
                yield ("load", MG_CLIENT_SCRIPT, CS_DYNAMIC_ERROR)
                yield ("send",)
                yield ("load", MG_DYNAMIC_MSG, b"Canceled reading\nthe Card.\0")
                yield ("send",)
                yield ("recv", MG_READY_END)
                yield ("return", SVR_MSG_CLIENT_CANCELED)
                return
        yield ("load", MG_CLIENT_SCRIPT, CS_SAVE_CARD)              # sServerScript_SendCard
        yield ("send",)
        yield ("load", MG_CARD, self.card)
        yield ("send",)
        yield ("load", MG_RAM_SCRIPT, self.ram_script)
        yield ("send",)
        yield ("recv", MG_READY_END)
        yield ("return", SVR_MSG_CARD_SENT)

    def _end(self, script, msg):
        yield ("load", MG_CLIENT_SCRIPT, script)
        yield ("send",)
        yield ("recv", MG_READY_END)
        yield ("return", msg)

    def run(self):
        """MysterGiftServer_Run: True once it has returned (SVR_RET_END)."""
        if self.func == "recv":
            if self.link.recv():
                self.recv_buf = bytes(self.link.recv_buf[:self.link.recv_size])
                self.func = "run"
        elif self.func == "send":
            if self.link.send():
                self.func = "run"
        elif self.func == "run":
            op = next(self.script)
            self.history.append(op[:2])
            if op[0] == "load":
                self.link.init_send(op[1], op[2], len(op[2]))
            elif op[0] == "send":
                self.func = "send"
            elif op[0] == "recv":
                self.link.init_recv(op[1])
                self.func = "recv"
            elif op[0] == "return":
                self.result, self.func = op[1], "done"
        return self.func == "done"


def lead_and_share(game, card=None, ram_script=b"", news=None, compat=RFU.EN_EMERALD, wait_frames=121, max_frames=4000):
    """Stage H3, all of "Send" as the game does it (pret:pokeemerald/src/mystery_gift_menu.c:1522
    MG_STATE_SEND onwards): host, accept, link players, the server - while the leader's standby
    (Task_SendMysteryGift state 16) runs - then Rfu_SetCloseLinkCallback and, once the DUO is ready
    to close too, the disconnect (0x30). Returns the parent and the server."""
    child, name = yield from lead_and_accept(game, compat=compat)
    yield from null_frames(game, wait_frames)
    parent = ParentLink(parent_slots=1 << child["slot"])
    server, standby = None, False
    for frame in range(max_frames):
        words = parent.main1()
        ready = yield from game.change(0x25, words)
        if ready != 0x99660028:
            raise LinkError(f"expected 'data ready', got {ready:#010x}")
        ack = yield from game.command(0x26)
        parent.receive(ack)
        parent.main2()
        if parent.exchange_active:
            parent.player_exchange()
        if parent.received_remote_link_players:
            if not standby:
                parent.set_standby()                               # Task_SendMysteryGift 16
                standby = True
                server = MGServer(parent, card, ram_script, news)  # MG_STATE_SERVER_LINK_START
            elif server.result is None and server.run():
                parent.close_task = True                           # MG_STATE_SERVER_LINK_END
        parent.tasks()
        if parent.errors:
            raise LinkError("; ".join(parent.errors))
        if parent.disconnect:
            yield from game.command(0x30, [parent.parent_slots])  # DisconnectRfu: rfu_REQ_disconnect
            parent.received_remote_link_players = False
            return parent, server
    raise LinkError(f"gift not shared (exchange state {parent.exchange_state}, server "
                    f"{server and server.func}, history {server and server.history[-4:]})")
