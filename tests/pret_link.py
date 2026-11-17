"""The games' own link layer, ported from the decompiled source: pret/pokeruby src/link.c (the same
in pokeemerald and pokefirered for everything here - DoHandshake, DoRecv, DoSend and SerialCB match
line for line). Every function cites the line it ports, as `pret:<repo>/<file>:<line> <name>`;
tests/source_anchors.py checks each citation against the pinned source (tools/pret.py fetches it).

Why (17 November): the simulator's game side was written from notes, twice over, and one copy got
DoHandshake's count wrong - a slot that is neither a handshake nor empty counts no players at all -
so it showed the DUO's hand-sent slots linking four players when the real game counted none. And
neither copy knew that SerialCB copies the link hardware's error flag into gLink.hardwareError on
every transfer once connected, which CheckErrorStatus turns into a link error. Port, don't recall.

This is the console's side: give it what its link hardware received each transfer (serial_cb),
and call vsync() and main1() once a frame as the game does. It never touches registers; what it
would write to REG_SIOMLT_SEND is in .siomlt_send, and .start_transfer is set when it (as master)
would start one.
"""

CMD_LENGTH = 8                            # pret:pokeruby/include/link.h:5 CMD_LENGTH
QUEUE_CAPACITY = 50                       # pret:pokeruby/include/link.h:6 QUEUE_CAPACITY
MASTER_HANDSHAKE = 0x8FFF                 # pret:pokeruby/include/link.h:29 MASTER_HANDSHAKE
SLAVE_HANDSHAKE = 0xB9A0                  # pret:pokeruby/include/link.h:30 SLAVE_HANDSHAKE
LINK_STAT_ERRORS = 0x0007F000             # pret:pokeruby/include/link.h:18 LINK_STAT_ERRORS

# gLink.state
START0, START1, HANDSHAKE, INIT_TIMER, CONN_ESTABLISHED = range(5)
LAG_NONE, LAG_MASTER, LAG_SLAVE = range(3)
QUEUE_FULL_NONE, QUEUE_FULL_SEND, QUEUE_FULL_RECV = range(3)


class GameLink:
    def __init__(self):
        self.state = START0
        self._clear()
        self.siomlt_send = 0
        self.start_transfer = False
        self.history = []                 # (what happened) for tests and reports

    def _clear(self):                     # CpuFill32(0, &gLink, sizeof(gLink)) and the statics
        self.local_id = self.player_count = 0
        self.is_master = 0                # 8: master (pret's own value)
        self.handshake_as_master = False
        self.link_field_F = 0
        self.received_nothing = False
        self.hardware_error = False
        self.bad_checksum = False
        self.queue_full = QUEUE_FULL_NONE
        self.lag = LAG_NONE
        self.serial_intr_counter = 0
        self.send_cmd_index = self.recv_cmd_index = 0
        self.checksum = 0
        self.send_queue = {"data": [[0] * QUEUE_CAPACITY for _ in range(CMD_LENGTH)], "count": 0, "pos": 0}
        self.recv_queue = {"data": [[[0] * QUEUE_CAPACITY for _ in range(CMD_LENGTH)] for _ in range(4)],
                           "count": 0, "pos": 0}
        self.s_num_vblanks_without_serial_intr = 0
        self.s_send_buffer_empty = False
        self.s_send_nonzero_check = 0
        self.s_recv_nonzero_check = 0
        self.s_checksum_available = False
        self.s_handshake_player_count = 0

    # ------------------------------------------------------------------ once a frame
    def main1(self, should_advance, send_cmd):
        """pret:pokeruby/src/link.c:1426 LinkMain1 - returns (status, recv_cmds, should_advance)."""
        recv = [[0] * 4 for _ in range(CMD_LENGTH)]
        if self.state == START0:
            self._disable_serial()
            self.state = START1
        elif self.state == START1:
            if should_advance == 1:
                self._enable_serial()
                self.state = HANDSHAKE
        elif self.state == HANDSHAKE:
            if should_advance == 1:
                if self.is_master == 8 and self.player_count > 1:
                    self.handshake_as_master = True
            elif should_advance == 2:
                self.state = START0
                self.siomlt_send = 0
            else:
                self._check_master_or_slave()
        elif self.state in (INIT_TIMER, CONN_ESTABLISHED):
            if self.state == INIT_TIMER:              # (falls through)
                self.state = CONN_ESTABLISHED
            self._enqueue_send_cmd(send_cmd)
            recv = self._dequeue_recv_cmds()
        return self.status(), recv, 0

    def status(self):
        """LinkMain1's return value (gLinkStatus)."""
        v = self.local_id | self.player_count << 2 | (0x20 if self.is_master == 8 else 0)
        v |= self.received_nothing << 8 | self.link_field_F << 9 | self.hardware_error << 12
        v |= self.bad_checksum << 13 | self.queue_full << 14
        if self.state == CONN_ESTABLISHED:
            v |= 0x40
        if self.lag == LAG_MASTER:
            v |= 0x10000
        if self.local_id > 3:
            v |= 0x20000
        if self.lag == LAG_SLAVE:
            v |= 0x40000
        return v

    def link_error(self):
        """pret:pokeruby/src/link.c:1261 CheckErrorStatus - the game's link error, or None."""
        s = self.status()
        if not s & LINK_STAT_ERRORS:
            return None
        why = [n for bit, n in ((1 << 12, "the link hardware's error flag"), (1 << 13, "a bad checksum"),
                                (3 << 14, "a full queue"), (1 << 16, "the master lagging"),
                                (1 << 17, "a player id over 3"), (1 << 18, "the slave lagging")) if s & bit]
        return ", ".join(why)

    def _check_master_or_slave(self, sd=1, si=0):
        """pret:pokeruby/src/link.c:1521 CheckMasterOrSlave (SD high and SI low: the master end)."""
        self.is_master = 8 if sd and not si and not self.local_id else 0

    def _disable_serial(self):
        """pret:pokeruby/src/link.c:1376 DisableSerial"""
        self._clear()

    def _enable_serial(self):
        """pret:pokeruby/src/link.c:1390 EnableSerial"""
        self.siomlt_send = 0
        self._clear()

    def _enqueue_send_cmd(self, send_cmd):
        """pret:pokeruby/src/link.c:1545 EnqueueSendCmd"""
        q = self.send_queue
        if q["count"] < QUEUE_CAPACITY:
            offset = q["pos"] + q["count"]
            if offset >= QUEUE_CAPACITY:
                offset -= QUEUE_CAPACITY
            for i in range(CMD_LENGTH):
                w = send_cmd[i] if i < len(send_cmd) else 0
                self.s_send_nonzero_check |= w
                q["data"][i][offset] = w
        else:
            self.queue_full = QUEUE_FULL_SEND
        if self.s_send_nonzero_check:
            q["count"] += 1
            self.s_send_nonzero_check = 0

    def _dequeue_recv_cmds(self):
        """pret:pokeruby/src/link.c:1581 DequeueRecvCmds"""
        q = self.recv_queue
        recv = [[0] * 4 for _ in range(CMD_LENGTH)]
        if q["count"] == 0:
            self.received_nothing = True
        else:
            for i in range(CMD_LENGTH):
                for j in range(self.player_count):
                    recv[i][j] = q["data"][j][i][q["pos"]]
            q["count"] -= 1
            q["pos"] += 1
            if q["pos"] >= QUEUE_CAPACITY:
                q["pos"] = 0
            self.received_nothing = False
        return recv

    def vsync(self):
        """pret:pokeruby/src/link.c:1615 LinkVSync"""
        if self.is_master:
            if self.state == HANDSHAKE:
                self.start_transfer = True
            elif self.state == CONN_ESTABLISHED:
                if self.serial_intr_counter > 8:
                    if self.lag == LAG_MASTER:
                        return
                    self.serial_intr_counter = 0
                elif self.hardware_error is not True:
                    self.lag = LAG_MASTER
                    return
                self.start_transfer = True
        elif self.state in (CONN_ESTABLISHED, HANDSHAKE):
            self.s_num_vblanks_without_serial_intr += 1
            if self.s_num_vblanks_without_serial_intr > 10:
                if self.state == CONN_ESTABLISHED:
                    self.lag = LAG_SLAVE
                if self.state == HANDSHAKE:
                    self.player_count = 0
                    self.link_field_F = 0

    # ------------------------------------------------------------------ each transfer
    def serial_cb(self, recv, sio_id=1, sio_error=False):
        """pret:pokeruby/src/link.c:1665 SerialCB - the serial interrupt, after a transfer: `recv` is
        SIOMULTI0-3 (0xFFFF for nobody), `sio_id` and `sio_error` SIOCNT's id and error bits."""
        self.local_id = sio_id
        if self.state == CONN_ESTABLISHED:
            self.hardware_error = bool(sio_error)
            self._do_recv(recv)
            self._do_send()
            self._send_recv_done()
        elif self.state == HANDSHAKE:
            if self._do_handshake(recv):
                if self.is_master:
                    self.state = INIT_TIMER
                    self.serial_intr_counter = 8
                else:
                    self.state = CONN_ESTABLISHED
                self.history.append(("linked", self.player_count))
        self.serial_intr_counter += 1
        self.s_num_vblanks_without_serial_intr = 0

    def _do_handshake(self, recv):
        """pret:pokeruby/src/link.c:1705 DoHandshake"""
        # (it loads REG_SIOMLT_SEND for the next transfer *before* deciding: the transfer after it
        # says yes still carries a handshake)
        self.siomlt_send = MASTER_HANDSHAKE if self.handshake_as_master else SLAVE_HANDSHAKE
        temp = list(recv[:4])
        self.handshake_as_master = False
        player_count, min_recv = 0, 0xFFFF
        for w in temp:
            if (w & ~3) == SLAVE_HANDSHAKE or w == MASTER_HANDSHAKE:
                player_count += 1
                if min_recv > w and w != 0:
                    min_recv = w
            else:
                if w != 0xFFFF:               # neither a handshake nor nobody: no players at all
                    player_count = 0
                break
        self.player_count = player_count
        if self.player_count > 1 and self.player_count == self.s_handshake_player_count \
                and temp[0] == MASTER_HANDSHAKE:
            return True
        self.link_field_F = (min_recv & 3) + 1 if self.player_count > 1 else 0
        self.s_handshake_player_count = self.player_count
        return False

    def _do_recv(self, recv):
        """pret:pokeruby/src/link.c:1760 DoRecv"""
        if self.send_cmd_index == 0:              # the checksum slot
            for i in range(self.player_count):
                if self.checksum != recv[i] and self.s_checksum_available:
                    self.bad_checksum = True
                    self.history.append(("bad checksum", i, self.checksum, recv[i]))
            self.checksum = 0
            self.s_checksum_available = True
        else:
            q = self.recv_queue
            index = q["pos"] + q["count"]
            if index >= QUEUE_CAPACITY:
                index -= QUEUE_CAPACITY
            if q["count"] < QUEUE_CAPACITY:
                for i in range(self.player_count):
                    self.checksum = (self.checksum + recv[i]) & 0xFFFF
                    self.s_recv_nonzero_check |= recv[i]
                    q["data"][i][self.recv_cmd_index][index] = recv[i]
            else:
                self.queue_full = QUEUE_FULL_RECV
            self.recv_cmd_index += 1
            if self.recv_cmd_index == CMD_LENGTH and self.s_recv_nonzero_check:
                q["count"] += 1
                self.s_recv_nonzero_check = 0

    def _do_send(self):
        """pret:pokeruby/src/link.c:1807 DoSend"""
        q = self.send_queue
        if self.send_cmd_index == CMD_LENGTH:
            self.siomlt_send = self.checksum
            if not self.s_send_buffer_empty:
                q["count"] -= 1
                q["pos"] += 1
                if q["pos"] >= QUEUE_CAPACITY:
                    q["pos"] = 0
            else:
                self.s_send_buffer_empty = False
        else:
            if not self.s_send_buffer_empty and q["count"] == 0:
                self.s_send_buffer_empty = True
            if self.s_send_buffer_empty:
                self.siomlt_send = 0
            else:
                self.siomlt_send = q["data"][self.send_cmd_index][q["pos"]]
            self.send_cmd_index += 1

    def _send_recv_done(self):
        """pret:pokeruby/src/link.c:1849 SendRecvDone"""
        if self.recv_cmd_index == CMD_LENGTH:
            self.send_cmd_index = 0
            self.recv_cmd_index = 0
        elif self.is_master:
            self.start_transfer = True            # (the timer, then Timer3Intr: the next transfer)
