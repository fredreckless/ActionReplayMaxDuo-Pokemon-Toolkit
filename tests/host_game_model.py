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
