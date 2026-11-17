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
        self.sd, self.si = 1, 0           # SIOCNT's SD and SI terminals (SI low: nobody before us)
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

    def _check_master_or_slave(self, sd=None, si=None):
        """pret:pokeruby/src/link.c:1521 CheckMasterOrSlave (SD high and SI low: the master end)."""
        sd = self.sd if sd is None else sd
        si = self.si if si is None else si
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


# ====================================================================== the console's link software
# link.c above the serial layer: OpenLink/CloseLink, LinkMain2 and its commands, blocks, link players,
# the link callbacks, the error status; and main.c's loop around it. pret's pokeruby names are kept
# (sub_XXXXXXXX where pokeruby has no better), so a reader can find each piece in the source.

MAX_LINK_PLAYERS = 4                      # pret:pokeruby/include/link.h:4 MAX_LINK_PLAYERS
BLOCK_BUFFER_SIZE = 0x100                 # pret:pokeruby/include/link.h:7 BLOCK_BUFFER_SIZE
BLOCK_REQUEST_SIZES = (200, 200, 100, 220, 40)   # pret:pokeruby/src/link.c:184 sBlockRequestLookupTable
MAGIC = b"GameFreak inc."                 # pret:pokeruby/src/link.c:195 sMagic
A_BUTTON, B_BUTTON, START_BUTTON = 0x01, 0x02, 0x08
DPAD_RIGHT, DPAD_LEFT, DPAD_UP, DPAD_DOWN = 0x10, 0x20, 0x40, 0x80
EXCHANGE_NOT_STARTED, EXCHANGE_COMPLETE, EXCHANGE_TIMED_OUT, EXCHANGE_IN_PROGRESS = 0, 1, 2, 3


def link_player_bytes(version, trainer_id, name, gender, link_type, language, lp_field_2=0, mp_id=0):
    """struct LinkPlayer (pret:pokeruby/include/link.h:63 LinkPlayer), 28 bytes."""
    name = bytes(name)[:11].ljust(11, b"\xff")
    return (version.to_bytes(2, "little") + lp_field_2.to_bytes(2, "little") + trainer_id.to_bytes(4, "little")
            + name + bytes([gender]) + link_type.to_bytes(4, "little") + mp_id.to_bytes(2, "little")
            + language.to_bytes(2, "little"))


def parse_link_player(b):
    return dict(version=int.from_bytes(b[0:2], "little"), lp_field_2=int.from_bytes(b[2:4], "little"),
                trainer_id=int.from_bytes(b[4:8], "little"), name=bytes(b[8:19]), gender=b[19],
                link_type=int.from_bytes(b[20:24], "little"), id=int.from_bytes(b[24:26], "little"),
                language=int.from_bytes(b[26:28], "little"))


class LinkErrorScreen(Exception):
    """CB2_LinkError: the game shows its link error and stops."""


class Console:
    """One game's link software, a frame at a time (frame()); its serial side is a GameLink, given each
    transfer by whoever moves the words (transfer()). The game's own logic - the Cable Club's tasks,
    a link room - runs as `callbacks`, a generator advanced by CallCallbacks; it reads and calls this
    object as the game's code calls link.c."""

    def __init__(self, local_player, game_version=2, block_send_buffer=None):
        """local_player: dict(trainer_id, name, gender, language, lp_field_2) - the save's, as
        InitLocalLinkPlayer reads it. game_version: gGameVersion (Ruby 2)."""
        self.gl = GameLink()
        self.local = dict(local_player)
        self.game_version = game_version
        self.link_open = False
        self.callback = None              # gLinkCallback: a method, or None
        self.link_type = 0                # gLinkType
        self.should_advance = 0           # gShouldAdvanceLinkState
        self.send_cmd = [0] * CMD_LENGTH  # gSendCmd
        self.recv_cmds = [[0] * 4 for _ in range(CMD_LENGTH)]   # gRecvCmds
        self.link_status = 0              # gLinkStatus
        self.link_players = [None] * 4    # gLinkPlayers (dicts)
        self.link_player_pending = [True] * 4   # gLinkPlayerPending
        self.link_player_blocks = [None] * 4    # the LinkPlayerBlocks as received (60 bytes)
        self.patch_link_player = None     # fn(bytearray block): a model's own LinkPlayer fields
        self.received_remote_link_players = False   # gReceivedRemoteLinkPlayers
        self.block_recv = [dict(pos=0, size=0, mp=0) for _ in range(4)]   # sBlockRecv
        self.block_recv_buffer = [bytearray(max(BLOCK_BUFFER_SIZE, 0x2000)) for _ in range(4)]
        self.block_received = [False] * 4  # gBlockReceived
        self.block_send = dict(active=False, pos=0, size=0, src=b"", mp=0)   # sBlockSend
        self.block_send_delay = 0         # sBlockSendDelayCounter
        self.block_send_buffer = bytearray(block_send_buffer or bytes(BLOCK_BUFFER_SIZE))   # gBlockSendBuffer
        self.block_request_type = 0       # gBlockRequestType
        self.closing = [0] * 4            # u8_array_3002B78 (0x5FFF seen)
        self.ready = [0] * 4              # u8_array_3002B70 (0x2FFE seen)
        self.keys_in = [0] * 4            # word_3002910 (0x4444 / 0xCAFE)
        self.room_key = 0                 # word_3004858 (overworld.c: this frame's key to send)
        self.transferring_data = False    # gLinkTransferringData
        self.link_error_occurred = False  # gLinkErrorOccurred
        self.suppress_link_error_message = False   # gSuppressLinkErrorMessage
        self.exchange_status = EXCHANGE_NOT_STARTED  # sPlayerDataExchangeStatus
        self.link_time_out_counter = 0    # gLinkTimeOutCounter
        self.saved_link_player_count = 0  # gSavedLinkPlayerCount
        self.error_screen = None          # CB2_LinkError's reason, once shown
        self.callback1 = None             # gMain.callback1 (a link room's, when in one)
        self.tasks = []                   # the running tasks (generators), stepped by RunTasks
        self.trigger_handshake_in = None  # Task_TriggerHandshake's count
        self.room_mode = None             # overworld.c's gUnknown_03000584 (the room's key function):
                                          # normal sub_8055390, idle sub_80553E0, script sub_80553E4,
                                          # recv_backed_up sub_8055408, send_backed_up sub_8055438
        self.room_flag = False            # gUnknown_03000588
        self.vsync_disabled = False       # gLinkVSyncDisabled
        self.held_keys = self.new_keys = 0   # gMain.heldKeys, gMain.newKeys
        self.log = []

    # ------------------------------------------------------------------ opening and closing
    def open_link(self):
        """pret:pokeruby/src/link.c:328 OpenLink (with InitLink, pret:pokeruby/src/link.c:306 InitLink)."""
        self.gl.state = START0                    # ResetSerial; EnableSerial clears gLink too
        self.vsync_disabled = False
        self.send_cmd = [0xEFFF] * CMD_LENGTH
        self.link_open = True
        self.gl._enable_serial()
        self.callback = self.cb_request_player_data_exchange
        self.link_error_occurred = False
        self.suppress_link_error_message = False
        self.reset_block_received_flags()
        self.received_remote_link_players = False
        for i in range(4):
            self.link_player_pending[i] = True
            self.closing[i] = self.ready[i] = 0
        self.trigger_handshake_in = 5             # pret:pokeruby/src/link.c:317 Task_TriggerHandshake

    def open_link_timed(self):
        """pret:pokeruby/src/link.c:696 OpenLinkTimed"""
        self.exchange_status = EXCHANGE_NOT_STARTED
        self.link_time_out_counter = 0
        self.open_link()

    def close_link(self):
        """pret:pokeruby/src/link.c:357 CloseLink"""
        self.received_remote_link_players = False
        self.link_open = False
        self.gl._disable_serial()
        self.gl.state = START0

    def reset_link_players(self):
        """pret:pokeruby/src/link.c:775 ResetLinkPlayers"""
        self.link_players = [None] * 4

    # ------------------------------------------------------------------ the main loop
    def transfer(self, recv, sio_id=None, sio_error=False):
        """A transfer done: SerialCB, with what this console's link hardware read."""
        self.gl.serial_cb(recv, self.gl.local_id if sio_id is None else sio_id, sio_error)

    def frame(self, held_keys=0):
        """The VBlank, then a turn of the main loop (one console on its own)."""
        self.vblank()
        self.main_loop(held_keys)

    def vblank(self):
        """pret:pokeruby/src/main.c:305 VBlankIntr's link part: LinkVSync (as master, it starts a command)."""
        if not self.vsync_disabled:
            self.gl.vsync()

    def main_loop(self, held_keys=0):
        """One turn of pret:pokeruby/src/main.c:84 AgbMain's loop: ReadKeys, then
        UpdateLinkAndCallCallbacks once, twice when overworld.c's link room says so."""
        self.new_keys = held_keys & ~self.held_keys       # ReadKeys: gMain.newKeys
        self.held_keys = held_keys
        if self.gl.send_queue["count"] > 1 and self.room_wants_send_catch_up():
            self.transferring_data = True
            self.update_link_and_call_callbacks(held_keys)
            self.transferring_data = False
        else:
            self.transferring_data = False
            self.update_link_and_call_callbacks(held_keys)
            if self.gl.recv_queue["count"] > 1 and self.room_wants_recv_catch_up():
                self.new_keys = 0
                self.transferring_data = True
                self.update_link_and_call_callbacks(held_keys)
                self.transferring_data = False

    def update_link_and_call_callbacks(self, held_keys=0):
        """pret:pokeruby/src/main.c:170 UpdateLinkAndCallCallbacks"""
        self.link_status, self.recv_cmds, _ = self.gl.main1(self.should_advance, self.send_cmd)
        self.should_advance = 0               # (LinkMain1: *shouldAdvanceLinkState = 0)
        self.link_main2(held_keys)
        if not (self.link_status & 0x100) or not self.keys_callback_active():
            self.call_callbacks()

    def call_callbacks(self):
        """pret:pokeruby/src/main.c:186 CallCallbacks - callback1 (in a link room, overworld.c's
        sub_8055354), then callback2, whose RunTasks steps the tasks: Task_TriggerHandshake and the
        game's own (the Cable Club's link-up, a routine's), each a generator stepped once a frame."""
        if self.error_screen:
            return
        if self.callback1:
            self.callback1()
        if self.trigger_handshake_in is not None:  # pret:pokeruby/src/link.c:317 Task_TriggerHandshake
            self.trigger_handshake_in -= 1
            if self.trigger_handshake_in == 0:
                self.should_advance = 1
                self.trigger_handshake_in = None
        for task in list(self.tasks):
            try:
                next(task)
            except StopIteration:
                self.tasks.remove(task)

    def add_task(self, gen):
        """CreateTask: `gen` is stepped from the next CallCallbacks on."""
        self.tasks.append(gen)
        return gen

    def link_main2(self, held_keys=0):
        """pret:pokeruby/src/link.c:438 LinkMain2"""
        if not self.link_open:
            return 0
        self.send_cmd = [0] * CMD_LENGTH
        if self.link_status & 0x40:
            self.process_recv_cmds()
            if self.callback:
                self.callback()
            self.check_error_status()
        return self.link_status

    def check_error_status(self):
        """pret:pokeruby/src/link.c:1261 CheckErrorStatus"""
        if self.link_open and self.link_status & LINK_STAT_ERRORS:
            why = self.gl.link_error()
            if not self.suppress_link_error_message:
                self.error_screen = why
            self.link_error_occurred = True
            self.log.append(("link error", why))
            self.close_link()

    # ------------------------------------------------------------------ commands
    def process_recv_cmds(self):
        """pret:pokeruby/src/link.c:475 ProcessRecvCmds"""
        r = self.recv_cmds
        for i in range(MAX_LINK_PLAYERS):
            self.keys_in[i] = 0
            c = r[0][i]
            if not c:
                continue
            if c == 0x2222:
                lp = link_player_bytes(self.game_version + 0x4000, self.local["trainer_id"], self.local["name"],
                                       self.local["gender"], self.link_type, self.local["language"],
                                       self.local.get("lp_field_2", 0), self.local.get("id", 0))
                block = bytearray(MAGIC.ljust(16, b"\0") + lp + MAGIC.ljust(16, b"\0"))
                if self.patch_link_player:                  # (a game's own fields: progress flags, ...)
                    self.patch_link_player(block)
                self.init_block_send(bytes(block))
            elif c in (0x4444, 0xCAFE):
                self.keys_in[i] = r[1][i]
            elif c == 0xBBBB:
                self.block_recv[i] = dict(pos=0, size=r[1][i], mp=r[2][i])
            elif c == 0x8888:
                b = self.block_recv[i]
                buf = self.block_recv_buffer[i]
                for j in range(CMD_LENGTH - 1):
                    at = b["pos"] + 2 * j
                    if at + 2 <= len(buf):
                        buf[at:at + 2] = r[j + 1][i].to_bytes(2, "little")
                b["pos"] += (CMD_LENGTH - 1) * 2
                if b["pos"] >= b["size"]:
                    if self.link_player_pending[i]:
                        block = bytes(buf[:60])
                        self.link_players[i] = parse_link_player(block[16:44])
                        self.link_player_blocks[i] = block
                        if block[:15] != MAGIC + b"\0" or block[44:59] != MAGIC + b"\0":
                            self.error_screen = self.error_screen or f"player {i}'s link player without GameFreak inc."
                            self.log.append(("link error", "magic", i))
                        else:
                            self.handle_receive_remote_link_player(i)
                    else:
                        self.block_received[i] = True        # pret:pokeruby/src/link.c:920 SetBlockReceivedFlag
            elif c == 0x5FFF:
                self.closing[i] = 1
            elif c == 0x2FFE:
                self.ready[i] = 1
            elif c == 0xCCCC:
                n = r[1][i]
                self.send_block(self.block_send_buffer[:BLOCK_REQUEST_SIZES[n]] if n < 5 else b"")

    def handle_receive_remote_link_player(self, mp):
        """pret:pokeruby/src/link.c:461 HandleReceiveRemoteLinkPlayer"""
        self.link_player_pending[mp] = False
        pending = sum(self.link_player_pending[i] for i in range(self.player_count()))
        if pending == 0 and not self.received_remote_link_players:
            self.received_remote_link_players = True

    def build_send_cmd(self, code):
        """pret:pokeruby/src/link.c:598 BuildSendCmd"""
        c = self.send_cmd
        if code == 0x2222:
            c[0], c[1] = 0x2222, self.link_type
        elif code in (0x2FFE, 0x5555, 0x5566, 0xAAAA, 0x5FFF):
            c[0] = code
        elif code == 0x4444:
            c[0], c[1] = 0x4444, self.held_keys
        elif code == 0xBBBB:
            c[0], c[1], c[2] = 0xBBBB, self.block_send["size"], self.block_send["mp"] + 128
        elif code == 0xCCCC:
            c[0], c[1] = 0xCCCC, self.block_request_type
        elif code == 0xCAFE:
            if not self.room_key or self.transferring_data:
                return
            c[0], c[1] = 0xCAFE, self.room_key

    # ------------------------------------------------------------------ blocks
    def init_block_send(self, data):
        """pret:pokeruby/src/link.c:790 InitBlockSend"""
        if self.block_send["active"]:
            return False
        data = bytes(data)
        if len(data) <= BLOCK_BUFFER_SIZE:                  # (it goes through gBlockSendBuffer)
            self.block_send_buffer[:len(data)] = data
        self.block_send = dict(active=True, pos=0, size=len(data), src=data, mp=self.multiplayer_id())
        self.build_send_cmd(0xBBBB)
        self.callback = self.cb_block_send_begin
        self.block_send_delay = 0
        return True

    def send_block(self, data):
        """pret:pokeruby/src/link.c:888 SendBlock"""
        return self.init_block_send(data)

    def cb_block_send_begin(self):
        """pret:pokeruby/src/link.c:821 LinkCB_BlockSendBegin"""
        self.block_send_delay += 1
        if self.block_send_delay > 2:
            self.callback = self.cb_block_send

    def cb_block_send(self):
        """pret:pokeruby/src/link.c:828 LinkCB_BlockSend"""
        b = self.block_send
        src = b["src"] + bytes(16)
        self.send_cmd[0] = 0x8888
        for i in range(CMD_LENGTH - 1):
            at = b["pos"] + 2 * i
            self.send_cmd[i + 1] = src[at] | src[at + 1] << 8
        b["pos"] += (CMD_LENGTH - 1) * 2
        if b["size"] <= b["pos"]:
            b["active"] = False
            self.callback = self.cb_block_send_end

    def cb_block_send_end(self):
        """pret:pokeruby/src/link.c:850 LinkCB_BlockSendEnd"""
        self.callback = None

    def request_block(self, n):
        """pret:pokeruby/src/link.c:893 sub_8007E9C - 0xCCCC n (everyone answers with a block)."""
        if self.callback:
            return False
        self.block_request_type = n
        self.build_send_cmd(0xCCCC)
        return True

    def block_received_status(self):
        """pret:pokeruby/src/link.c:912 GetBlockReceivedStatus"""
        return sum(1 << i for i in range(4) if self.block_received[i])

    def reset_block_received_flags(self):
        """pret:pokeruby/src/link.c:925 ResetBlockReceivedFlags"""
        self.block_received = [False] * 4

    def block(self, i):
        """gBlockRecvBuffer[i], as long as the last block from i said."""
        return bytes(self.block_recv_buffer[i][:self.block_recv[i]["size"]])

    def is_link_task_finished(self):
        """pret:pokeruby/src/link.c:907 IsLinkTaskFinished"""
        return self.callback is None

    # ------------------------------------------------------------------ callbacks
    def cb_request_player_data_exchange(self):
        """pret:pokeruby/src/link.c:1027 LinkCB_RequestPlayerDataExchange"""
        if self.link_status & 0x20:
            self.build_send_cmd(0x2222)
        self.callback = None

    def set_keys_callback(self):
        """pret:pokeruby/src/link.c:662 sub_8007B14 - the link room's: 0xCAFE every frame."""
        self.callback = self.cb_keys

    def cb_keys(self):
        """pret:pokeruby/src/link.c:675 sub_8007B44"""
        if self.received_remote_link_players:
            self.build_send_cmd(0xCAFE)

    def keys_callback_active(self):
        """pret:pokeruby/src/overworld.c:2483 sub_8055940"""
        return self.callback == self.cb_keys

    def set_close_link_callback(self):
        """pret:pokeruby/src/link.c:1148 SetCloseLinkCallback"""
        if not self.callback:
            self.callback = self.cb_close_send

    def cb_close_send(self):
        """pret:pokeruby/src/link.c:1157 sub_8008350"""
        if self.gl.recv_queue["count"] == 0:              # gLastRecvQueueCount
            self.build_send_cmd(0x5FFF)
            self.callback = self.cb_close_wait

    def cb_close_wait(self):
        """pret:pokeruby/src/link.c:1166 sub_800837C"""
        total = self.player_count()
        if sum(1 for i in range(total) if self.closing[i]) == total:
            self.close_link()
            self.callback = None

    def set_ready_callback(self):
        """pret:pokeruby/src/link.c:1228 sub_80084A4 - "ready" (0x2FFE), then wait for everyone's."""
        if not self.callback:
            self.callback = self.cb_ready_send

    def cb_ready_send(self):
        """pret:pokeruby/src/link.c:1235 sub_80084C8"""
        if self.gl.recv_queue["count"] == 0:
            self.build_send_cmd(0x2FFE)
            self.callback = self.cb_ready_wait

    def cb_ready_wait(self):
        """pret:pokeruby/src/link.c:1244 sub_80084F4"""
        total, count = self.player_count(), 0
        while count < total and self.ready[count]:
            count += 1
        if count == total:
            self.ready = [0] * 4
            self.callback = None

    # ------------------------------------------------------------------ what the game asks
    def player_count(self):
        """GetLinkPlayerCount (EXTRACT_PLAYER_COUNT(gLinkStatus))"""
        return self.link_status >> 2 & 7

    def multiplayer_id(self):
        """pret:pokeruby/src/link.c:878 GetMultiplayerId"""
        return self.gl.local_id

    def is_master(self):
        return bool(self.link_status & 0x20)

    def advance_as_master(self):
        """pret:pokeruby/src/link.c:938 sub_8007F4C - the leader confirms: send the master's handshake."""
        if self.link_status & 0x20 and self.player_count() > 1:
            self.should_advance = 1

    def save_link_player_count(self, n):
        """pret:pokeruby/src/link.c:1075 sub_80081C8"""
        self.saved_link_player_count = n

    def exchange_status_timed(self):
        """pret:pokeruby/src/link.c:706 GetLinkPlayerDataExchangeStatusTimed"""
        if self.received_remote_link_players:
            n = self.player_count()
            if n == 0:
                self.link_error_occurred = True
                self.close_link()
            same = sum(1 for i in range(n) if self.link_players[i] and self.link_players[0]
                       and self.link_players[i]["link_type"] == self.link_players[0]["link_type"])
            self.exchange_status = EXCHANGE_COMPLETE if same == n else EXCHANGE_IN_PROGRESS
        else:
            self.link_time_out_counter += 1
            if self.link_time_out_counter > 600:
                self.exchange_status = EXCHANGE_TIMED_OUT
        return self.exchange_status

    # ------------------------------------------------------------------ overworld.c's link room
    def room_wants_send_catch_up(self):
        """pret:pokeruby/src/overworld.c:2469 sub_8055910"""
        return self.room_mode is not None and self.keys_callback_active() and self.room_mode == "send_backed_up"

    def room_wants_recv_catch_up(self):
        """pret:pokeruby/src/overworld.c:2441 sub_80558AC (the palette fade's case left out)"""
        if self.room_mode is None or not self.keys_callback_active():
            return False
        if self.room_mode == "recv_backed_up":
            return True
        if self.room_mode != "script":
            return False
        was, self.room_flag = self.room_flag, False
        return was

# MASTER_ORDER - how a frame goes, in time: the VBlank interrupt (LinkVSync) starts a command; its
# first transfer (the checksum slot, about 2,600 cycles at 115,200 bps) is over before the main loop,
# just woken from WaitForVBlank, gets to LinkMain1; the other eight follow 12,608 cycles apart (the
# timer: pret:pokeruby/src/link.c:1531 InitTimer), while and after the main loop runs. So a frame's
# LinkMain1 dequeues the commands finished before this VBlank, and a CloseLink there stops the
# command just begun after one transfer.

class Cable:
    """A link cable joining Consoles (the first is plugged in as the master end), frame by frame in
    MASTER_ORDER. Words of absent players read 0xFFFF."""

    def __init__(self, *consoles):
        self.consoles = list(consoles)
        for i, c in enumerate(self.consoles):
            c.gl.si = 0 if i == 0 else 1
        self.transfers = 0

    def frame(self, keys=None):
        for c in self.consoles:
            c.vblank()
        master, looped = self.consoles[0], False
        for _ in range(64):
            if not (master.gl.start_transfer and master.gl.is_master):
                break
            master.gl.start_transfer = False
            self._transfer()
            if not looped:
                self._main_loops(keys)
                looped = True
        if not looped:
            self._main_loops(keys)

    def _main_loops(self, keys):
        for i, c in enumerate(self.consoles):
            c.main_loop((keys or {}).get(i, 0))

    def _transfer(self):
        if True:
            words = [c.gl.siomlt_send if c.gl.state >= HANDSHAKE else 0xFFFF for c in self.consoles]
            words = (words + [0xFFFF] * 4)[:4]
            self.transfers += 1
            for i, c in enumerate(self.consoles):
                if c.gl.state >= HANDSHAKE:
                    c.transfer(words, i)

    def run(self, frames, until=None, keys=None):
        for n in range(frames):
            self.frame(keys)
            if until and until():
                return n + 1
        return None
