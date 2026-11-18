/*
 * A Game Boy Advance Wireless Adapter, played by the DUO's GBA (firmware v4.2 program).
 *
 * The Pokemon game on the other GBA talks to "its adapter" exactly as librfu does with
 * the real one (see docs/WIRELESS.md and the Emerald decompilation, librfu_intr.c):
 *
 *   ID exchange   librfu's Sio32ID: NINTENDO, then the adapter ID 0x8001. The game is the
 *                 clock master. Done again after every reset of the adapter.
 *   Commands      0x9966LLCC + LL data words from the game (each answered with 0x80000000),
 *                 then our acknowledgement 0x9966LL(CC+0x80) + LL words of response.
 *                 The game clocks every word at 2 MHz; between words both sides signal
 *                 "ready" on their SO lines (the SIOCNT bit 3 / bit 2 handshake).
 *   Clock swap    after 0x25, 0x27, 0x35 or 0x37 the game becomes the clock slave and waits
 *                 for the adapter to send it a command (0x27 "nothing happened" after the
 *                 configured number of frames, 0x28 "data ready", 0x29 "disconnected").
 *
 * This first version is an adapter with no other adapters in range: searches find nothing.
 * Everything the game asks is recorded in a trace the PC reads.
 *
 * PC conversation (one packet answered per packet received):
 *   0x2A POLL arg   -> 0x2A value   (arg & 0xFF selects, arg >> 8 is an index)
 *        0 status  1 last word  2 trace count  3 trace entry (head)  4 trace entry (data)
 *        5 counters
 *   0x2B STOP       -> 0x2B status, then this program returns to the firmware.
 *
 * Nothing here touches either cartridge.
 */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

typedef struct {
    void (*send8)(const void *);
    void (*recv8)(void *);
    u32 (*avail)(void);
    void (*idle)(void);
    void (*log)(const char *);
    void (*log1)(const char *, u32);
    void (*reply)(u32 cmd, u32 value);
    u32 (*crc32)(const void *, u32);
} api_t;

#define REG16(a) (*(volatile u16 *)(a))
#define REG32(a) (*(volatile u32 *)(a))
#define SIODATA32 REG32(0x04000120)
#define SIOCNT    REG16(0x04000128)
#define RCNT      REG16(0x04000134)
#define VCOUNT    REG16(0x04000006)

#define CNT_INTERNAL 0x0001
#define CNT_2MHZ     0x0002
#define CNT_SI       0x0004
#define CNT_SO_HIGH  0x0008
#define CNT_START    0x0080
#define CNT_32BIT    0x1000

#define IDLE_WORD 0x80000000u
#define RFU_ID    0x8001u
#define LINES_PER_FRAME 228
#define HANDSHAKE_LINES 160          /* ~10 ms: the game answers within microseconds */
#define WATCHDOG_LINES  315          /* ~20 ms */

/* ------------------------------------------------------------------ helpers */
void *memset(void *d, int c, unsigned n) { u8 *p = d; while (n--) *p++ = (u8)c; return d; }
void *memcpy(void *d, const void *s, unsigned n) { u8 *p = d; const u8 *q = s; while (n--) *p++ = *q++; return d; }

static u32 lines_total, last_vcount;

static u32 now(void)                  /* scanlines since start (63.6 us each) */
{
    u32 v = VCOUNT & 0xFF;
    u32 d = v >= last_vcount ? v - last_vcount : v + LINES_PER_FRAME - last_vcount;
    last_vcount = v;
    lines_total += d;
    return lines_total;
}

static int si(void) { return (SIOCNT & CNT_SI) != 0; }

static int wait_si(int level, u32 lines)
{
    u32 t0 = now();
    while (si() != level)
        if (now() - t0 > lines)
            return 0;
    return 1;
}

/* ------------------------------------------------------------------ trace */
#define TRACE_N 32
#define EV_ID_EXCHANGE   0x01    /* pseudo-commands, so the trace reads as a story */
#define EV_WAIT_TIMEOUT  0x02
#define EV_LOST          0x03
#define EV_SWAP_FAILED   0x04
#define EV_STRAY         0x05    /* the game wanted more of an answer than we sent */
#define EV_FLICK_TIMEOUT 0x06    /* the game never noticed we were ready */
#define EV_CONNECTED     0x07    /* the game has connected to our distributor */
#define EV_CHILD_NAME    0x08    /* the host side has received the game's name (NI) */
#define EV_JOIN_SENT     0x09    /* the host has told the game it may join (NI, acknowledged) */

static u32 trace_head[TRACE_N], trace_data[TRACE_N], trace_count;
static u32 n_commands, n_id, n_lost, last_word;

static void trace(u32 cmd, u32 len, u32 data)
{
    if (trace_count) {
        u32 i = (trace_count - 1) % TRACE_N;
        if ((trace_head[i] & 0xFFFF) == ((len << 8) | cmd) && trace_data[i] == data
                && (trace_head[i] >> 16) != 0xFFFF) {
            trace_head[i] += 0x10000;
            return;
        }
    }
    u32 i = trace_count % TRACE_N;
    trace_head[i] = 0x10000 | (len << 8) | cmd;
    trace_data[i] = data;
    trace_count++;
}

/* ------------------------------------------------------------------ the adapter itself */
enum { ST_IDLE = 0, ST_HOST_CLOSED = 1, ST_HOST_OPEN = 2, ST_SEARCHING = 3, ST_CONNECTING = 4,
       ST_CONNECTED = 5, ST_ASLEEP = 0xFF };

static u32 adapter_state, system_config, game_config[6];
static u32 req[32], req_len, req_cmd;
static u32 ack[32], ack_len;
static int swap_after;                 /* the game hands us the clock after this command */

/* ------------------------------------------------------------------ a distributor in range
 * What a searching game sees (0x1D): one host, broadcasting what Emerald's Mystery Gift looks
 * for (link_rfu_2.c / union_room.c in the decomp): serial number 0x7F7F (BPEJ; 0x7D in English), RFU_SERIAL_WONDER_
 * DISTRIBUTOR, and as its "game name" a struct RfuGameData with compatibility.hasCard set.
 * Layout as librfu's rfu_REQ_configGameData builds it: serial (2), gname (13), checksum (1),
 * uname (8); checksum = ~(sum of gname[0..7] + uname[0..7]).
 * Lab session 16: every answer word with a top bit of 1 needs a 'ready' flick, and about one
 * flick in ten loses its word. So the values we choose keep every word of this answer below
 * 0x80000000: the name is "DUO" plus a space (0x00), so its end mark (0xFF) falls in the low
 * byte of a word, the padding after it is 0x00 (the game copies all 8 bytes but reads only up
 * to the end mark), and the trainer ID puts the checksum byte below 0x80. Only the 0x9966
 * header still needs a flick. */
#define HOST_ID      0x7DA5
#define CHILD_ID     0x2C41
#define HOST_TRAINER 0x5678           /* with the name below, the checksum byte is 0x2C */
/* The distributor serial each game wants (Stage 1): Japanese Emerald (BPEJ) wants 0x7F7F - found
 * by --sweep-serial, lab session 19; it doesn't contain 0x7F7D at all. The English decomps (Emerald,
 * FireRed/LeafGreen) say 0x7F7D, used for every other game until a sweep says otherwise. Chosen
 * when the game sends its broadcast data (0x16), which names its language and version; the PC
 * can override it (pc_serial, --serial). */
#define SERIAL_JP_EMERALD 0x7F7F
#define SERIAL_DECOMP     0x7F7D
static u32 dist_serial = SERIAL_JP_EMERALD, pc_serial, host_lang = 1;
__attribute__((unused)) static u32 host_cfg[6], host_on = 1, n_hosts = 1, connect_polls, child_connected;
/* --sweep-serial: the Japanese Emerald doesn't contain 0x7F7D (session 18), so offer every serial
 * number in turn, three per answer, each host's ID being its serial. Each block of serials is shown
 * twice, each time in less than the 240 frames Emerald then spends looking for the host it
 * accepted - so it finds it again and connects (0x1F) to that ID. */
static u32 sweep_n, found_serial;
#if defined(LAB) || defined(UNION_ROOM)
#define sweep 0                          /* the lab and Union Room builds leave the sweep out, to make room */
#define next_sweep_serial() 0
#else
static u32 sweep;
/* 512 serials a block, each block offered twice (a cycle is ~171 answers, ~2.8 s); then the next */
__attribute__((noinline)) static u32 next_sweep_serial(void)
{
    u32 n = sweep_n++, id = ((n >> 10) << 9 | (n & 511)) & 0x7FFF;
    return id < 3 ? 3 : id;                                    /* 0 and 2 are other serials */
}
#endif

#define GIFT_MAX (4 + 0x14C + 1000)
static u32 gift_words[(GIFT_MAX + 3) / 4];               /* (defined with the Mystery Gift server) */
#if defined(LAB) || defined(UNION_ROOM)
#define GIFT_IS_NEWS 0                   /* the lab build sends Wonder Cards only, to make room */
#else
#define GIFT_IS_NEWS (gift_words[0] >> 16 & 1)
#endif

#ifdef UNION_ROOM
static u32 ur_offer;                     /* the trading board: species | type << 10 | level << 16 (0: none) */
static u32 corner;                       /* the Direct Corner (docs/DIRECT_CORNER.md): the group's activity, 0 for the Union Room */
#endif
static void build_host(void)
{
#ifndef GAME_HOSTS
    u8 b[24];
#ifdef UNION_ROOM
    /* A player in the Union Room (docs/UNION_ROOM.md): pret:pokeemerald/src/link_rfu_2.c:2066
     * SetHostRfuGameData - no Wonder Card or News, activity IN_UNION_ROOM (0x40), not started */
    u32 compat = host_lang | 1 << 7 | 1 << 8 | 1 << 9 | 3 << 10;
#else
    u32 compat = host_lang               /* language: the game's own (Japanese until it says) */
               | (GIFT_IS_NEWS ? 1 << 4 : 1 << 5)   /* hasNews or hasCard: what we offer */
               | 1 << 7 | 1 << 8 | 1 << 9 /* canLinkNationally, hasNationalDex, gameClear */
               | 3 << 10;                /* version: Emerald */
#endif
    static const u8 uname[8] = { 0xBE, 0xCF, 0xC9, 0x00, 0xFF, 0, 0, 0 };   /* "DUO " */
    u8 sum = 0;
    memset(b, 0, sizeof b);
    b[0] = dist_serial & 0xFF;
    b[1] = dist_serial >> 8;
    b[2] = compat; b[3] = compat >> 8;   /* RfuGameData.compatibility */
    b[4] = HOST_TRAINER & 0xFF; b[5] = HOST_TRAINER >> 8;   /* .playerTrainerId */
#ifdef UNION_ROOM
    b[10] = ur_offer; b[11] = ur_offer >> 8;   /* .tradeSpecies (10 bits), .tradeType (6): the board */
    b[12] = corner ? corner : 0x40;      /* .activity = IN_UNION_ROOM | ACTIVITY_NONE (or a group's), not started */
    b[13] = ur_offer >> 16 << 1;         /* .playerGender 0, .tradeLevel */
#else
    b[12] = 21 + GIFT_IS_NEWS;           /* .activity = ACTIVITY_WONDER_CARD (or _NEWS), not started */
#endif
    memcpy(b + 16, uname, 8);
    for (int i = 0; i < 8; i++)
        sum += b[2 + i] + uname[i];
    b[15] = ~sum;
    for (int i = 0; i < 6; i++)
        host_cfg[i] = b[4 * i] | b[4 * i + 1] << 8 | b[4 * i + 2] << 16 | (u32)b[4 * i + 3] << 24;
#endif
}

/* ------------------------------------------------------------------ the host's link layer (librfu NI)
 * Once connected, the "host" (our distributor) and the game talk in librfu link-layer frames
 * (see docs/DISTRIBUTOR.md). The host speaks once a frame: we tell the waiting game "data
 * ready" (0x28), it reads the host's frames (0x26) and answers with its own (0x24/0x25).
 * First the game sends its name over NI, librfu's reliable channel: a 7-byte control block
 * (data type, payload size, data size), then the data in four interleaved windows, each chunk
 * numbered and acknowledged by the host. This is the receiving half, as librfu's
 * rfu_STC_NI_receive_Receiver does it; the host's frames carry the acknowledgements. */
#define LCOM_NI_START 1
#define LCOM_NI       2
#define LCOM_NI_END   3
#define LCOM_UNI      4
#define NI_BUSY       0x8000
#define NI_RECV       0x0040
#define NI_RECV_START (NI_BUSY | NI_RECV | LCOM_NI_START)
#define NI_RECEIVING  (NI_BUSY | NI_RECV | LCOM_NI)
#define NI_RECV_LAST  (NI_BUSY | NI_RECV | LCOM_NI_END)
#define NI_RECV_OK    (NI_RECV | 6)

static struct {
    u32 state, ack, phase, n[4], remain, payload, size, type, off[4];
    u8 ctrl[8];                      /* dataType, payloadSize (2), dataSize (4) */
} ni;
static u8 child_name[32];            /* the game's serialNo, gname, uname: 26 bytes */
static u32 ni_end_seen, child_frames, host_frames;

static void ni_reset(void) { memset(&ni, 0, sizeof ni); }

static void ni_copy(u32 phase, const u8 *src, u32 len)
{
    u8 *base = ni.state == NI_RECEIVING ? child_name : ni.ctrl;
    u32 lim = ni.state == NI_RECEIVING ? sizeof child_name : sizeof ni.ctrl;
    for (u32 i = 0; i < len; i++, ni.off[phase]++)
        if (ni.off[phase] < lim)
            base[ni.off[phase]] = src[i];
}

static void ni_receive(u32 state, u32 phase, u32 n, u32 len, const u8 *data)
{
    int check = 0;
    if (state == LCOM_NI_END) {
        ni_end_seen = 1;
        if (ni.state == NI_RECEIVING) {
            ni.phase = 0;
            ni.n[0] = 0;
            ni.state = NI_RECV_LAST;
        }
    } else if (state == LCOM_NI) {
        if (ni.state == NI_RECV_START && !ni.remain) {       /* control block complete: data next */
            ni.type = ni.ctrl[0];
            ni.payload = ni.ctrl[1] | ni.ctrl[2] << 8;
            ni.size = ni.ctrl[3] | ni.ctrl[4] << 8 | ni.ctrl[5] << 16 | (u32)ni.ctrl[6] << 24;
            for (int w = 0; w < 4; w++) {
                ni.n[w] = 0;
                ni.off[w] = ni.payload * w;
            }
            ni.remain = ni.size;
            ni.state = NI_RECEIVING;
        }
        if (ni.state == NI_RECEIVING)
            check = 1;
    } else if (state == LCOM_NI_START) {
        if (ni.state != NI_RECV_START) {                     /* a new transfer */
            if (ni.state != 0 && ni.state != NI_RECV_OK)
                ;                                            /* (librfu only starts from idle) */
            ni_reset();
            ni.remain = 7;
            ni.ack = 1;
            ni.state = NI_RECV_START;
        }
        check = 1;
    }
    if (check && n == ((ni.n[phase] + 1) & 3)) {
        ni_copy(phase, data, len);
        if (ni.state == NI_RECEIVING)
            ni.off[phase] += 3 * ni.payload;
        ni.remain -= len;
        ni.n[phase] = n;
    }
    ni.phase = phase;
}

/* The sending half (librfu's rfu_STC_setSendData_org / NI_constructLLSF / NI_receive_Sender,
 * host side: 3-byte sub-frame headers addressed to slot 0). First use: link_rfu_2's
 * "you may join" status byte, RFU_STATUS_JOIN_GROUP_OK, sent with a sub-frame size of 8. */
#define NI_SEND       0x0020
#define NI_SEND_START (NI_BUSY | NI_SEND | LCOM_NI_START)
#define NI_SENDING    (NI_BUSY | NI_SEND | LCOM_NI)
#define NI_SEND_LAST  (NI_BUSY | NI_SEND | LCOM_NI_END)
#define NI_SEND_NULL  (NI_BUSY | NI_SEND)
#define NI_SEND_OK    (NI_SEND | 6)

static struct {
    u32 state, phase, n[4], acked[4], payload, size, now[4];
    int remain;
    const u8 *src;
    u8 ctrl[8];
} nis;
static const u8 join_group_ok = 5;                /* RFU_STATUS_JOIN_GROUP_OK */

static void nis_start(const u8 *src, u32 size, u32 type, u32 sub_frame)
{
    memset(&nis, 0, sizeof nis);
#ifdef GAME_HOSTS
    nis.payload = sub_frame - 2;                  /* a child's 2-byte header (librfu llsf_struct[MODE_CHILD]) */
#else
    nis.payload = sub_frame - 3;
#endif
    nis.size = size;
    nis.src = src;
    nis.ctrl[0] = type;
    nis.ctrl[1] = nis.payload; nis.ctrl[2] = nis.payload >> 8;
    nis.ctrl[3] = size; nis.ctrl[4] = size >> 8; nis.ctrl[5] = size >> 16; nis.ctrl[6] = size >> 24;
    nis.remain = 7;
    for (int i = 0; i < 4; i++) nis.n[i] = 1;
    nis.state = NI_SEND_START;
}

static u32 nis_frame(u8 *out)
{
    const u8 *buf = nis.state == NI_SEND_START ? nis.ctrl : nis.src;
    u32 len = nis.state == NI_SEND_START ? 7 : nis.size, size, h;
    if (nis.state == NI_SENDING)
        for (int i = 0; i < 4 && nis.now[nis.phase] >= len; i++)
            nis.phase = (nis.phase + 1) & 3;
    if (nis.state == NI_SENDING)
        size = len - nis.now[nis.phase] < nis.payload ? len - nis.now[nis.phase] : nis.payload;
    else
        size = nis.remain >= (int)nis.payload ? nis.payload : nis.remain > 0 ? (u32)nis.remain : 0;
#ifdef GAME_HOSTS
    h = (nis.state & 0xF) << 10 | nis.phase << 5 | nis.n[nis.phase] << 7 | size;
    out[0] = h; out[1] = h >> 8;
    for (u32 i = 0; i < size; i++)
        out[2 + i] = buf[nis.now[nis.phase] + i];
    if (nis.state == NI_SENDING)
        nis.phase = (nis.phase + 1) & 3;
    return 2 + size;
#else
    h = (nis.state & 0xF) << 14 | nis.phase << 9 | nis.n[nis.phase] << 11 | size | 1u << 18;
    out[0] = h; out[1] = h >> 8; out[2] = h >> 16;
    for (u32 i = 0; i < size; i++)
        out[3 + i] = buf[nis.now[nis.phase] + i];
    if (nis.state == NI_SENDING)
        nis.phase = (nis.phase + 1) & 3;
    return 3 + size;
#endif
}

static void nis_ack(u32 st, u32 phase, u32 n)
{
    if (((st == LCOM_NI && nis.state == NI_SENDING) || (st == LCOM_NI_START && nis.state == NI_SEND_START)
            || (st == LCOM_NI_END && nis.state == NI_SEND_LAST)) && nis.n[phase] == n)
        nis.acked[phase] = 1;
    if (!nis.acked[phase])
        return;
    nis.n[phase] = (nis.n[phase] + 1) & 3;
    nis.acked[phase] = 0;
    if (nis.state == NI_SEND_START || nis.state == NI_SENDING) {
        nis.now[phase] += nis.state == NI_SEND_START ? nis.payload : nis.payload << 2;
        nis.remain -= nis.payload;
        if (nis.remain <= 0) {
            nis.phase = 0;
            if (nis.state == NI_SEND_START) {
                for (int i = 0; i < 4; i++) {
                    nis.n[i] = 1;
                    nis.now[i] = nis.payload * i;
                }
                nis.remain = nis.size;
                nis.state = NI_SENDING;
            } else {
                nis.n[0] = 0;
                nis.remain = 0;
                nis.state = NI_SEND_LAST;
            }
        }
    } else if (nis.state == NI_SEND_LAST) {
        nis.state = NI_SEND_NULL;
    }
}

/* ------------------------------------------------------------------ stage D2: link_rfu_2's parent
 * Once the game has been told it may join, librfu's UNI channel takes over: every frame the
 * host sends one unreliable sub-frame holding link_rfu_2's command table, gRfu.recvCmds: seven
 * u16s for each of five players (70 bytes) - our own command in row 0 and, echoed back, the
 * game's last command in row 1 (the game, player 1, checks its own echoes). The game answers
 * each new table with one 14-byte sub-frame: its command, a sequence number in bits 5-7.
 * On top of that, link_rfu_2's blocks (0x8800 init, then 0x8900|n chunks of 12 bytes) carry
 * first the link-player exchange, then Mystery Gift's own conversation (mystery_gift_link.c):
 * a 6-byte header (ident, CRC-16, size), then the data in blocks of up to 252 bytes. */
#define CMD_READY_CLOSE 0x5F00
#define CMD_READY_EXIT  0x6600
#define CMD_PLAYER_IDS  0x7700
#define CMD_PLAYER_IDS_NEW 0x7800
#define CMD_BLOCK_INIT  0x8800
#define CMD_BLOCK       0x8900
#define CMD_BLOCK_REQ   0xA100
#define UNI_BYTES       70

#define EV_LINK_PLAYERS  0x0A    /* the game's link-player block has arrived (data: trainer ID) */
#define EV_MG_STEP       0x0B    /* the Mystery Gift server moved on (data: step << 16 | ident) */
#define EV_MG_ERROR      0x0C    /* something the game sent was not what the server expected */
#define EV_CLOSE         0x0D    /* the game is ready to close the link: we agree */

static u8 child_uni[16];
static u32 child_uni_new, link_state, link_timer, n_child_cmds, n_uni, n_resent, uni_acked;
static u16 rx_cmd[7], tx_cmd[7];

#if !defined(UNION_ROOM) || defined(GAME_HOSTS)
static u16 crc16(const u8 *p, u32 n, u16 crc)    /* util.c CalcCRC16WithTable, before its final ~ */
{
    while (n--) {
        crc ^= *p++;
        for (int b = 0; b < 8; b++)
            crc = crc & 1 ? (crc >> 1) ^ 0x8408 : crc >> 1;
    }
    return crc;
}
#endif

/* What the PC loads (0x2C PUT), from the user's own files:
 *   a Wonder Card: its size, the card, then the 1000-byte RAM script (struct RamScriptData);
 *   or Wonder News: its size with bit 16 set, then the news (struct WonderNews).
 * Nothing is sent without one except "nothing to send" (the game then says so - a safe dry run). */
#define GIFT_MAX (4 + 0x14C + 1000)
static u32 gift_words[(GIFT_MAX + 3) / 4], put_at, gift_ready;
#define GIFT ((const u8 *)gift_words)
#define CARD_SIZE (gift_words[0] & 0xFFFF)                /* (the news size, for news) */

/* Our outgoing block: one link_rfu_2 block. Bytes come from a source that is zero past its
 * end (the RAM script is sent as 1024 bytes, MG_LINK_BUFFER_SIZE, as Emerald's server does). */
static struct {
    const u8 *src;
    u32 len, size, count, next, inits, gap, active;
} bs;
#define BS_INITS 8              /* real parents send 4: the game ignores repeats */
#define BS_GAP   8              /* frames between blocks, so the game can take each one in */

static void bs_start(const u8 *src, u32 len, u32 size)
{
    bs.src = src; bs.len = len; bs.size = size;
    bs.count = (size + 11) / 12;
    bs.next = 0; bs.inits = 0; bs.gap = 0; bs.active = 1;
}

static int bs_step(void)                 /* fills tx_cmd; returns 1 while the block is going */
{
    if (!bs.active)
        return 0;
    if (bs.inits < BS_INITS) {
        tx_cmd[0] = CMD_BLOCK_INIT; tx_cmd[1] = bs.count; tx_cmd[2] = 0x80;   /* owner 0 + 0x80 */
        bs.inits++;
        return 1;
    }
    if (bs.next < bs.count) {
        tx_cmd[0] = CMD_BLOCK | bs.next;
        for (u32 j = 0; j < 6; j++) {
            u32 at = bs.next * 12 + 2 * j, lo = at < bs.len ? bs.src[at] : 0, hi = at + 1 < bs.len ? bs.src[at + 1] : 0;
            tx_cmd[1 + j] = lo | hi << 8;
        }
        bs.next++;
        return 1;
    }
    if (++bs.gap < BS_GAP)
        return 1;
    bs.active = 0;
    return 0;
}

/* The game's incoming blocks (row 1). */
static struct {
    u32 state, count, flags, done;       /* state: 0 ready, 1 receiving */
#ifdef GAME_HOSTS
    u8 head[252];                        /* a whole Mystery Gift link block (stage H3) */
#elif defined(UNION_ROOM)
    u8 head[108];                        /* the first 108 bytes (9 chunks): a whole struct Pokemon */
#else
    u8 head[64];                         /* the first 64 bytes of the block */
#endif
} rb;
static u8 child_player[64];              /* the game's LinkPlayerBlock (magic, LinkPlayer, magic) */
static u8 game_data[64];                 /* the start of the game's MysteryGiftLinkGameData */

static void rb_chunk(u32 n)
{
    if (rb.state != 1 || n >= 24)
        return;
    for (u32 j = 0; j < 6; j++) {
        u32 at = n * 12 + 2 * j;
        if (at + 1 < sizeof rb.head) {
            rb.head[at] = rx_cmd[1 + j];
            rb.head[at + 1] = rx_cmd[1 + j] >> 8;
        }
    }
    rb.flags |= 1u << n;
    if (rb.flags == (1u << rb.count) - 1) {
        rb.state = 0;                    /* ready for the next one at once */
        rb.done++;
    }
}

#ifdef UNION_ROOM
/* The Union Room partner (docs/UNION_ROOM.md), after the link players: cards, then the game's
 * requests. mg_step: 0 ask for cards, 1 waiting for the game's, 2 waiting for a request (and
 * answering it), on and on. Steps and answers go to the trace as EV_MG_STEP (step << 16 | value). */
__attribute__((unused)) static u32 mg_step, mg_sub, mg_errors, mg_got, mg_resp, ur_packet, ur_reply, ur_answer;
#define ACT_CARD   (0x40 | 8)            /* IN_UNION_ROOM | ACTIVITY_CARD ("Greetings") */
#define ACT_ACCEPT (0x40 | 17)
#define ACT_DECLINE (0x40 | 18)
#define CMD_PACKET 0x2F00                /* pret:pokeemerald/include/link_rfu.h:10 RFUCMD_SEND_PACKET */
#define EV_UR_STEP 0x0E                  /* the Union Room partner moved on (step << 16 | detail) */

/* Our struct TrainerCard (pret:pokeemerald/include/trainer_card.h): 100 bytes, the block size
 * Task_ExchangeCards asks for (BLOCK_REQ_SIZE_100). */
static u8 our_card[100];
static void build_card(void)
{
    memset(our_card, 0, sizeof our_card);
    our_card[0x01] = 1;                                    /* stars */
    our_card[0x02] = 1;                                    /* hasPokedex */
    our_card[0x0C] = 151;                                  /* caughtMonsCount */
    our_card[0x0E] = HOST_TRAINER & 0xFF; our_card[0x0F] = HOST_TRAINER >> 8;
    our_card[0x10] = 42;                                   /* playTimeHours */
    our_card[0x24] = 0x10; our_card[0x25] = 0x27;          /* money: 10000 */
    memset(our_card + 0x28, 0xFF, 8);                      /* easyChatProfile: no words */
    our_card[0x30] = 0xBE; our_card[0x31] = 0xCF; our_card[0x32] = 0xC9;   /* "DUO" */
    memset(our_card + 0x33, 0xFF, 5);
    our_card[0x38] = 3;                                    /* version: Emerald */
}

/* The trade (pret:pokeemerald/src/union_room.c:1477 Task_StartUnionRoomTrade, then
 * pret:pokeemerald/src/trade.c:4650 CB2_WaitTradeComplete): our Pokemon for the game's, the mail,
 * and once the game says its animation is done (0xABCD), the leader's go-ahead (0xDCBA). Our
 * Pokemon is the one the PC loaded (100 bytes, the party form) into the gift buffer. */
#define UR_TRADE_MON  10
#define UR_TRADE_MAIL 11
#define UR_TRADE_SCENE 12
#define UR_TRADE_DONE 13
#define ACT_TRADE (0x40 | 4)            /* pret:pokeemerald/include/constants/union_room.h:24 ACTIVITY_TRADE */
static u8 game_mon[100];

/* Chat (pret:pokeemerald/src/union_room_chat.c): every message is a 40-byte block - its kind
 * (CHAT_MESSAGE_CHAT 1, JOIN 2, LEAVE 3, DROP 4), the sender's name (8 bytes), then the text (or,
 * for JOIN, LEAVE and DROP, the sender's player number). We are the leader, player 0: we join,
 * say hello, repeat back whatever the player says, and when the player leaves, end the chat
 * (DROP), as a leader left alone does (Task_ReceiveChatMessage, then Chat_Exit). */
#define ACT_CHAT (0x40 | 5)             /* pret:pokeemerald/include/constants/union_room.h:25 ACTIVITY_CHAT */
#define UR_CHAT 14
#define UR_CHAT_DONE 15
/* The Direct Corner, step 1 (docs/DIRECT_CORNER.md): we lead a group (a Trade Center: activity 4);
 * the game joins, the link players are exchanged, then - after the standby before
 * pret:pokeemerald/src/union_room.c:1643 Task_StartActivity - the cards, as
 * pret:pokeemerald/src/union_room.c:1611 CB2_TransitionToCableClub does on the way to the room. */
#define UR_CORNER_WAIT 16
#define UR_CORNER_ROOM 17
static u32 standbys, corner_wait;
static u8 chat_out[40], chat_last[40];
static u32 chat_due, chat_count;
static const u8 chat_hello[] = { 0xC2, 0xBF, 0xC6, 0xC6, 0xC9, 0xAB, 0x00, 0xC3, 0xB4, 0xC7, 0x00, 0xCE, 0xC2, 0xBF, 0x00,
                                 0xBE, 0xCF, 0xC9, 0xAD, 0xFF };           /* "HELLO! I'M THE DUO." */

static void chat_block(u32 kind, const u8 *text, u32 n)
{
    memset(chat_out, 0, sizeof chat_out);
    chat_out[0] = kind;
    chat_out[1] = 0xBE; chat_out[2] = 0xCF; chat_out[3] = 0xC9; chat_out[4] = 0xFF;   /* "DUO" */
    for (u32 i = 0; i < n && 9 + i < sizeof chat_out; i++)
        chat_out[9 + i] = text[i];
    bs_start(chat_out, sizeof chat_out, sizeof chat_out);
}
static const u8 confirm_block[2] = { 0xBA, 0xDC };        /* LINKCMD_CONFIRM_FINISH_TRADE */
#define MAIL_SIZE (6 * 36 + 4)                            /* sizeof(struct Mail) * PARTY_SIZE + 4 */

static void mg_frame(void)
{
    if (bs.active)
        return;
    switch (mg_step) {
    case 0:                                  /* pret:pokeemerald/src/union_room.c:1517 Task_ExchangeCards */
        tx_cmd[0] = CMD_BLOCK_REQ; tx_cmd[1] = 2;          /* BLOCK_REQ_SIZE_100 */
        build_card();
        bs_start(our_card, sizeof our_card, sizeof our_card);
        mg_step = 1;
        trace(EV_UR_STEP, 0, 1 << 16);
        break;
    case 1:
        if (rb.done != mg_got) {
            mg_got = rb.done;
            memcpy(game_data, rb.head, sizeof game_data);
            mg_step = corner ? UR_CORNER_ROOM : 2;
            trace(EV_UR_STEP, 0, 2 << 16 | game_data[0x0E] | game_data[0x0F] << 8);
        }
        break;
    case UR_TRADE_MON:                       /* the game's Pokemon in; ours out */
        if (rb.done != mg_got) {
            mg_got = rb.done;
            memcpy(game_mon, rb.head, sizeof game_mon);
            bs_start((const u8 *)gift_words, 100, 100);
            mg_step = UR_TRADE_MAIL;
            trace(EV_UR_STEP, 0, UR_TRADE_MAIL << 16 | game_mon[0] | game_mon[1] << 8);
        }
        break;
    case UR_TRADE_MAIL:                      /* the game's mail in; ours (none) out */
        if (rb.done != mg_got) {
            mg_got = rb.done;
            bs_start(our_card, 0, MAIL_SIZE);              /* (no bytes from the source: all zero) */
            mg_step = UR_TRADE_SCENE;
            trace(EV_UR_STEP, 0, UR_TRADE_SCENE << 16);
        }
        break;
    case UR_TRADE_SCENE:                     /* the game: "my animation is done"; we: go ahead */
        if (rb.done != mg_got) {
            mg_got = rb.done;
            if (rb.head[0] == 0xCD && rb.head[1] == 0xAB) {
                bs_start(confirm_block, 2, 20);
                mg_step = UR_TRADE_DONE;
                trace(EV_UR_STEP, 0, UR_TRADE_DONE << 16);
            }
        }
        break;
    case UR_TRADE_DONE:
    case UR_CHAT_DONE:
        break;
    case UR_CORNER_WAIT:                     /* the standby first, so the game's card is in its buffer */
        if (standbys && ++corner_wait > 10) {
            mg_step = 0;
            trace(EV_UR_STEP, 0, UR_CORNER_WAIT << 16 | corner);
        }
        break;
    case UR_CORNER_ROOM:                     /* in the room: the link goes on (the room itself is step 2) */
        break;
    case UR_CHAT:
        if (chat_due) {                                    /* after our JOIN: hello */
            chat_due = 0;
            chat_block(1, chat_hello, sizeof chat_hello);
            break;
        }
        if (rb.done != mg_got) {
            mg_got = rb.done;
            switch (rb.head[0]) {
            case 2:                                        /* the player joined: so do we (player 0) */
                chat_block(2, 0, 0);
                chat_due = 1;
                break;
            case 1:                                        /* a message: kept for the PC, said back */
                memcpy(chat_last, rb.head, sizeof chat_last);
                chat_count++;
                chat_block(1, rb.head + 9, 31);
                break;
            case 3:                                        /* the player left: the chat is over */
                chat_block(4, 0, 0);
                mg_step = UR_CHAT_DONE;
                break;
            }
            trace(EV_UR_STEP, 0, UR_CHAT << 16 | rb.head[0] << 8 | (chat_count & 0xFF));
        }
        break;
    default:                                 /* pret:pokeemerald/src/union_room.c:4289 PollPartnerYesNoResponse */
        if (ur_packet) {
            mg_resp = ur_packet;
            ur_answer = ur_packet == ACT_CARD || ur_packet == ACT_CHAT || (ur_packet == ACT_TRADE && ur_offer && put_at >= 25)
                      ? ACT_ACCEPT : ACT_DECLINE;
            ur_packet = 0;
            ur_reply = 3;                                  /* (the game reads it on any frame) */
            mg_step = mg_step < 9 ? mg_step + 1 : 9;
            trace(EV_UR_STEP, 0, mg_step << 16 | mg_resp << 8 | ur_answer);
            if (mg_resp == ACT_TRADE && ur_answer == ACT_ACCEPT) {
                mg_got = rb.done;
                mg_step = UR_TRADE_MON;
            }
            if (mg_resp == ACT_CHAT) {
                mg_got = rb.done;
                mg_step = UR_CHAT;
            }
        }
        if (ur_reply) {
            ur_reply--;
            tx_cmd[0] = CMD_PACKET; tx_cmd[1] = ur_answer;
        }
        break;
    }
}
#else
/* The Mystery Gift server: Emerald's gMysteryGiftServerScript_SendWonderCard, reduced to what a
 * distributor needs. Client scripts are struct MysteryGiftClientCmd {u32 instr, parameter}. */
enum { CLI_RETURN = 1, CLI_RECV = 2, CLI_SEND_LOADED = 3, CLI_COPY_RECV = 4, CLI_LOAD_GAME_DATA = 8,
       CLI_SAVE_NEWS = 9, CLI_SAVE_CARD = 10, CLI_SAVE_RAM_SCRIPT = 17, CLI_SEND_READY_END = 20 };
enum { ID_CLIENT_SCRIPT = 16, ID_GAME_DATA = 17, ID_RESPONSE = 19, ID_READY_END = 20, ID_CARD = 22,
       ID_NEWS = 23, ID_RAM_SCRIPT = 25 };
enum { MSG_NOTHING_SENT = 0, MSG_CARD_RECEIVED = 2, MSG_NEWS_RECEIVED = 3, MSG_HAD_NEWS = 7 };
static const u32 script_send_game_data[] = { CLI_LOAD_GAME_DATA, 0, CLI_SEND_LOADED, 0,
                                             CLI_RECV, ID_CLIENT_SCRIPT, CLI_COPY_RECV, 0 };
static const u32 script_save_card[] = { CLI_RECV, ID_CARD, CLI_SAVE_CARD, 0, CLI_RECV, ID_RAM_SCRIPT,
                                        CLI_SAVE_RAM_SCRIPT, 0, CLI_SEND_READY_END, 0, CLI_RETURN, MSG_CARD_RECEIVED };
static const u32 script_nothing_sent[] = { CLI_SEND_READY_END, 0, CLI_RETURN, MSG_NOTHING_SENT };
#ifndef LAB
/* Wonder News (the decomp's server script for news): the game saves the news unless it already
 * has the same one, and answers with a word - FALSE if it saved it, TRUE if it already had it. */
static const u32 script_save_news[] = { CLI_RECV, ID_NEWS, CLI_SAVE_NEWS, 0, CLI_SEND_LOADED, 0,
                                        CLI_RECV, ID_CLIENT_SCRIPT, CLI_COPY_RECV, 0 };
static const u32 script_news_received[] = { CLI_SEND_READY_END, 0, CLI_RETURN, MSG_NEWS_RECEIVED };
static const u32 script_had_news[] = { CLI_SEND_READY_END, 0, CLI_RETURN, MSG_HAD_NEWS };
#endif

enum { MG_SEND, MG_RECV, MG_END };
static u32 mg_step, mg_sub, mg_off, mg_ident, mg_size, mg_errors, mg_got, mg_resp;
static u8 mg_head[8];

/* step table: what the server does, in order */
static void mg_item(u32 step, u32 *op, u32 *ident, const u8 **src, u32 *len, u32 *size)
{
    *src = 0; *len = *size = 0;
#ifndef LAB
    if (gift_ready && GIFT_IS_NEWS && step >= 2) {
        const u32 *script = mg_resp ? script_had_news : script_news_received;
        switch (step) {
        case 2: *op = MG_SEND; *ident = ID_CLIENT_SCRIPT; *src = (const u8 *)script_save_news;
                *len = *size = sizeof script_save_news; return;
        case 3: *op = MG_SEND; *ident = ID_NEWS; *src = GIFT + 4; *len = *size = CARD_SIZE; return;
        case 4: *op = MG_RECV; *ident = ID_RESPONSE; return;
        case 5: *op = MG_SEND; *ident = ID_CLIENT_SCRIPT; *src = (const u8 *)script;
                *len = *size = sizeof script_news_received; return;
        case 6: *op = MG_RECV; *ident = ID_READY_END; return;
        default: *op = MG_END; *ident = 0; return;
        }
    }
#endif
    switch (step) {
    case 0: *op = MG_SEND; *ident = ID_CLIENT_SCRIPT; *src = (const u8 *)script_send_game_data;
            *len = *size = sizeof script_send_game_data; break;
    case 1: *op = MG_RECV; *ident = ID_GAME_DATA; break;
    case 2: *op = MG_SEND; *ident = ID_CLIENT_SCRIPT;
            if (gift_ready) { *src = (const u8 *)script_save_card; *len = *size = sizeof script_save_card; }
            else { *src = (const u8 *)script_nothing_sent; *len = *size = sizeof script_nothing_sent; }
            break;
    case 3: *op = gift_ready ? MG_SEND : MG_RECV; *ident = gift_ready ? ID_CARD : ID_READY_END;
            *src = GIFT + 4; *len = *size = CARD_SIZE; break;
    case 4: *op = gift_ready ? MG_SEND : MG_END; *ident = ID_RAM_SCRIPT;
            *src = GIFT + 4 + CARD_SIZE; *len = 1000; *size = 0x400; break;
    case 5: *op = gift_ready ? MG_RECV : MG_END; *ident = ID_READY_END; break;
    default: *op = MG_END; *ident = 0; break;
    }
}

static void mg_next(void)
{
    mg_step++;
    mg_sub = 0;
    u32 op, ident, len, size; const u8 *src;
    mg_item(mg_step, &op, &ident, &src, &len, &size);
    trace(EV_MG_STEP, 0, mg_step << 16 | (op == MG_END ? 0xFFFF : ident));
}

/* One frame of the server; may start a block (bs) or consume the game's (rb). */
static void mg_frame(void)
{
    u32 op, ident, len, size; const u8 *src;
    mg_item(mg_step, &op, &ident, &src, &len, &size);
    if (op == MG_END || bs.active)
        return;
    if (op == MG_SEND) {
        if (mg_sub == 0) {                                       /* header: ident, CRC, size */
            u16 crc = crc16(src, len, 0x1121);
            u8 zero = 0;
            for (u32 i = len; i < size; i++) crc = crc16(&zero, 1, crc);
            crc = ~crc;
            mg_head[0] = ident; mg_head[1] = 0; mg_head[2] = crc; mg_head[3] = crc >> 8;
            mg_head[4] = size; mg_head[5] = size >> 8;
            bs_start(mg_head, 6, 6);
            mg_off = 0;
            mg_sub = 1;
        } else if (mg_off < size) {                              /* data, 252 bytes a block */
            u32 n = size - mg_off < 252 ? size - mg_off : 252;
            bs_start(src + mg_off, mg_off < len ? (len - mg_off < n ? len - mg_off : n) : 0, n);
            mg_off += n;
        } else {
            mg_next();
        }
        return;
    }
    /* MG_RECV: header, then blocks until size bytes */
    if (rb.done == mg_got)
        return;
    mg_got = rb.done;
    if (mg_sub == 0) {
        mg_ident = rb.head[0] | rb.head[1] << 8;
        mg_size = rb.head[4] | rb.head[5] << 8;
        if (mg_ident != ident || mg_size > 0x400) {
            mg_errors++;
            trace(EV_MG_ERROR, 0, mg_ident << 16 | mg_size);
        }
        mg_off = 0;
        mg_sub = 1;
        if (mg_size == 0)
            mg_next();
        return;
    }
    {
        u32 n = mg_size - mg_off < 252 ? mg_size - mg_off : 252;
        if (ident == ID_GAME_DATA && mg_off == 0)
            memcpy(game_data, rb.head, sizeof game_data);
        if (ident == ID_RESPONSE && mg_off == 0)
            mg_resp = rb.head[0];                                /* TRUE: it already had this news */
        mg_off += n;
        if (mg_off >= mg_size)
            mg_next();
    }
}

#endif

static void rb_init(void)
{
    if (rb.state == 0) {
        rb.state = 1;
        rb.count = rx_cmd[1] < 24 ? rx_cmd[1] : 24;
        rb.flags = 0;
        memset(rb.head, 0, sizeof rb.head);
    }
}

static u32 standby_reply, standby_num, close_reply;

static void handle_child_cmd(void)
{
    switch (rx_cmd[0] & 0xFF00) {
    case CMD_BLOCK_INIT: rb_init(); break;
    case CMD_BLOCK:      rb_chunk(rx_cmd[0] & 0xFF); break;
    case CMD_READY_EXIT: standby_reply = 1; standby_num = rx_cmd[1]; break;
    case CMD_READY_CLOSE: close_reply = 1; break;
#ifdef UNION_ROOM
    case CMD_PACKET:     ur_packet = rx_cmd[1]; break;   /* the game's request (Rfu_SendPacket) */
#endif
    }
}

/* Our link-player block: "GameFreak inc." magic, a struct LinkPlayer, the magic again. */
static u8 player_block[60];
static void build_player_block(void)
{
    static const char magic[] = "GameFreak inc.";
    memset(player_block, 0, sizeof player_block);
    memcpy(player_block, magic, 14);
    memcpy(player_block + 44, magic, 14);
    u8 *lp = player_block + 16;
    lp[0] = 3; lp[1] = 0x40;                       /* version: Emerald + 0x4000 */
    lp[3] = 0x80;                                  /* lp_field_2 = 0x8000 */
    lp[4] = HOST_TRAINER & 0xFF; lp[5] = HOST_TRAINER >> 8;   /* trainerId, as broadcast */
    lp[8] = 0xBE; lp[9] = 0xCF; lp[10] = 0xC9;     /* name "DUO" */
    memset(lp + 11, 0xFF, 5);
    lp[26] = host_lang;                            /* language: the game's own */
}

enum { LS_OFF, LS_IDS, LS_REQ, LS_EXCHANGE, LS_SERVE, LS_DONE };

static void link_frame(void)
{
    memset(rx_cmd, 0, sizeof rx_cmd);
    memset(tx_cmd, 0, sizeof tx_cmd);
    if (child_uni_new) {
        child_uni_new = 0;
        if (child_uni[1]) {                                      /* a command (its high byte) */
            child_uni[0] &= 0x1F;                                /* drop the sequence number */
            for (u32 j = 0; j < 7; j++)
                rx_cmd[j] = child_uni[2 * j] | child_uni[2 * j + 1] << 8;
            n_child_cmds++;
            handle_child_cmd();
        }
    }
    link_timer++;
    if (link_state == LS_EXCHANGE && rb.done) {                  /* the game's link player arrived */
        memcpy(child_player, rb.head, sizeof child_player);
        trace(EV_LINK_PLAYERS, 0, child_player[20] | child_player[21] << 8 | child_player[22] << 16
              | (u32)child_player[23] << 24);
        link_state = LS_SERVE;
        mg_got = rb.done;
        link_timer = 0;
    }
    if (standby_reply) {                                         /* Rfu_LinkStandby, as the leader */
        standby_reply = 0;
#ifdef UNION_ROOM
        standbys++;
#endif
        tx_cmd[0] = CMD_READY_EXIT; tx_cmd[1] = standby_num;
        return;
    }
    if (close_reply) {
        close_reply = 0;
        tx_cmd[0] = CMD_READY_CLOSE;
        trace(EV_CLOSE, 0, mg_step);
        return;
    }
    if (bs_step())
        return;
    switch (link_state) {
    case LS_IDS:                                                 /* two players; slot 0 is player 1 */
        tx_cmd[0] = CMD_PLAYER_IDS; tx_cmd[1] = 2; tx_cmd[2] = 0x0001;
        link_state = LS_REQ;
        break;
    case LS_REQ:                                                 /* everyone sends their link player */
        tx_cmd[0] = CMD_BLOCK_REQ; tx_cmd[1] = 0;                /* BLOCK_REQ_SIZE_NONE: 200 bytes */
        build_player_block();
        bs_start(player_block, sizeof player_block, 200);
        link_state = LS_EXCHANGE;
        link_timer = 0;
        break;
    case LS_EXCHANGE:
        if (link_timer > 240 && rb.state == 0)                   /* nothing in 4 s: ask again */
            link_state = LS_IDS;
        break;
    case LS_SERVE:
        if (link_timer > 10)
            mg_frame();
        break;
    }
}

/* A data command from the connected game: librfu's child packet, header word first
 * (bytes << 8 for slot 0), then 2-byte-headed sub-frames. */
#ifdef GAME_HOSTS
__attribute__((unused))
#endif
static void host_receive(void)
{
    u32 bytes = (req[0] >> 8) & 0x1F, at = 0;
    const u8 *d = (const u8 *)&req[1];
    child_frames++;
    ni_end_seen = bytes == 0;
    while (bytes - at >= 2 && at < 4 * 31) {
        u32 h = d[at] | d[at + 1] << 8, len = h & 0x1F;
        u32 recv_first = (h >> 14) & 2, st = (h >> 10) & 0xF, ack = (h >> 9) & 1;
        if (!recv_first && st != LCOM_UNI && !ack)
            ni_receive(st, (h >> 5) & 3, (h >> 7) & 3, len, d + at + 2);
        else if (!recv_first && st != LCOM_UNI && (nis.state & NI_BUSY))
            nis_ack(st, (h >> 5) & 3, (h >> 7) & 3);                 /* the game acknowledging us */
        else if (!recv_first && st == LCOM_UNI && len <= 16) {
            memcpy(child_uni, d + at + 2, len);                      /* librfu's rfu_STC_UNI_receive */
            if (len < 16) memset(child_uni + len, 0, 16 - len);
            child_uni_new = 1;
            uni_acked = 1;                                           /* (it only answers new packets) */
            n_uni++;
        }
        at += 2 + len;
    }
    if (ni.state == NI_RECV_LAST && !ni_end_seen) {         /* librfu's rfu_CB_recvData */
        ni.state = NI_RECV_OK;
        nis_start(&join_group_ok, 1, 0, 8);                          /* link_rfu_2: "you may join" */
        trace(EV_CHILD_NAME, 0, child_name[0] | child_name[1] << 8 | child_name[17] << 16 | child_name[18] << 24);
    }
}

/* The host's frame for the game to read (0x26): the NI acknowledgement while receiving
 * (3-byte header: size 0, phase, n, ack, slot state, addressed slots), else librfu's
 * one-byte "null" frame. Returns the answer length. */
static u32 hf[32], hf_len, hf_uni;               /* the host's packet for the next 0x26 (0: none) */

#ifdef GAME_HOSTS
__attribute__((unused))
#endif
static u32 host_frame(void)
{
    u8 *out = (u8 *)&hf[1];
    u32 bytes = 0;
    hf_uni = 0;
    host_frames++;
    if (ni.state & NI_BUSY) {
        u32 f = (ni.state & 0xF) << 14 | ni.ack << 13 | ni.phase << 9 | ni.n[ni.phase] << 11 | 1u << 18;
        out[0] = f; out[1] = f >> 8; out[2] = f >> 16;
        bytes = 3;
    }
    if (nis.state & NI_BUSY) {
        u32 was_null = nis.state == NI_SEND_NULL;
        bytes += nis_frame(out + bytes);
        if (was_null) {                                              /* librfu's rfu_CB_sendData */
            nis.state = NI_SEND_OK;
            trace(EV_JOIN_SENT, 0, join_group_ok);
            link_state = LS_IDS;                                     /* stage D2 starts next frame */
            link_timer = 0;
        }
    } else if (link_state != LS_OFF) {
        link_frame();                                                /* UNI: gRfu.recvCmds */
        u32 h = LCOM_UNI << 14 | UNI_BYTES | 1u << 18;
        out[bytes] = h; out[bytes + 1] = h >> 8; out[bytes + 2] = h >> 16;
        memset(out + bytes + 3, 0, UNI_BYTES);
        memcpy(out + bytes + 3, tx_cmd, 14);                         /* row 0: us */
        memcpy(out + bytes + 3 + 14, rx_cmd, 14);                    /* row 1: the game's, echoed */
        bytes += 3 + UNI_BYTES;
        hf_uni = 1;
    }
    if (!bytes) {
        out[0] = 0xFF;                                               /* librfu's one-byte null frame */
        bytes = 1;
    }
    u32 total = bytes;
    while (bytes & 3)
        out[bytes++] = 0;
    hf[0] = total;                                                   /* bytes from the host */
    return 1 + bytes / 4;
}

#ifdef GAME_HOSTS
/* ------------------------------------------------------------------ the game hosts, the DUO joins
 * (docs/WIRELESS_HOST.md, stage H1). The game polls for children (0x1A); after a few polls the DUO's
 * child is listed (ID, slot 0) and connected at once (librfu 1026: rfu_STC_readChildList). The child
 * must then send its name over NI, data type 1, in 14-byte sub-frames
 * (AgbRfu_LinkManager.c rfu_LMAN_PARENT_checkRecvChildName). The game's frames to us carry the
 * parent's 3-byte headers; ours to it the child's 2-byte ones. */
#define EV_NAME_SENT 0x0F                /* the game has acknowledged our name */
#define EV_JOIN_ANSWER 0x7E              /* the game's answer: RFU_STATUS_JOIN_GROUP_OK (5) or _NO */
static u32 join_polls, join_named, join_answered;
static const u8 our_name[26] = {
    0x02, 0x00,                          /* serialNo: RFU_SERIAL_GAME */
    0x02 | 1 << 7, 0x0F,                 /* gname.compatibility: English, canLinkNationally, version */
    HOST_TRAINER & 0xFF, HOST_TRAINER >> 8,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,            /* the rest of the game name (9), 2 bytes padding */
    0xBE, 0xCF, 0xC9, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00   /* uname: "DUO" */
};

/* Stage H2b (docs/WIRELESS_HOST.md): link_rfu_2 with the game as parent. Every frame it sends its
 * command table - seven u16s per link player, its own in row 0, ours (as it last got them) in our
 * row - and we answer each with one 14-byte UNI frame: our command, a sequence number in byte 0's
 * top three bits (pret:pokeemerald/src/link_rfu_2.c:908 ChildBuildSendCmd), which the game checks
 * counts up by one (pret:pokeemerald/src/link_rfu_2.c:824 RfuMain2_Parent). What we do with it is
 * the child's side of pret:pokeemerald/src/link_rfu_2.c:1754 Task_PlayerExchange: take our player
 * number from SEND_PLAYER_IDS, answer BLOCK_REQ with our link player, read the game's. */
static u8 parent_uni[UNI_BYTES];
static u32 parent_uni_new, child_seq, my_id, n_players, join_linked, n_tables;
static struct { u32 state, count, next, echo, wait, len; const u8 *src; } cs;   /* our block: 1 announcing, 2 chunks, 3 checking, 4 done */
static const u8 block_req_size[5] = { 200, 200, 100, 220, 40 };   /* link_rfu_2.c sBlockRequests */
#define EV_BLOCK_SENT 0x7D              /* the game has every chunk of our link player */
#define CS_INITS 3                      /* announce a block at least this often (repeats are harmless) */

static void cs_begin(const u8 *src, u32 len, u32 size)
{
    cs.src = src; cs.len = len;
    cs.count = (size + 11) / 12;
    cs.state = cs.count ? 1 : 0;
    cs.next = cs.echo = cs.wait = 0;
}

static void cs_chunk(u32 n)
{
    tx_cmd[0] = CMD_BLOCK | n;
    for (u32 j = 0; j < 6; j++) {
        u32 at = n * 12 + 2 * j;
        tx_cmd[1 + j] = (at < cs.len ? cs.src[at] : 0) | (at + 1 < cs.len ? cs.src[at + 1] : 0) << 8;
    }
}

/* Stage H3 (docs/WIRELESS_HOST.md): Mystery Gift with a friend, "Send". The game runs its Mystery
 * Gift server (pret:pokeemerald/src/mystery_gift_server.c) and we are its client
 * (pret:pokeemerald/src/mystery_gift_client.c): we run the client scripts it sends, give it our
 * game data, keep the card (or news) and RAM script it sends for the PC. Both directions use
 * pret:pokeemerald/src/mystery_gift_link.c's framing: a 6-byte header block (ident, CRC-16,
 * size; size 0 means 1024), then the data in blocks of up to 252 bytes. */
enum { CLI_NONE, CLI_RETURN, CLI_RECV, CLI_SEND_LOADED, CLI_COPY_RECV, CLI_LOAD_GAME_DATA = 8, CLI_SAVE_NEWS,
       CLI_SAVE_CARD, CLI_COPY_MSG = 12, CLI_ASK_TOSS, CLI_LOAD_TOSS_RESPONSE, CLI_SAVE_RAM_SCRIPT = 17,
       CLI_SEND_READY_END = 20 };                                   /* pret:pokeemerald/include/mystery_gift_client.h:18 */
enum { MG_CLIENT_SCRIPT = 16, MG_GAME_DATA, MG_RESPONSE = 19, MG_READY_END, MG_DYNAMIC_MSG, MG_CARD, MG_NEWS,
       MG_RAM_SCRIPT = 25 };                                        /* pret:pokeemerald/include/mystery_gift_link.h:9 */
#define EV_MG_GOT  0x7C                 /* the game's server sent us something (data: ident << 16 | size) */
#define EV_MG_DONE 0x7B                 /* our client script returned (data: its message, CLI_MSG_*) */
#define CLI_DONE 3
#define MS_GAP 10                       /* tables between our blocks, so the game has read the last one */
static u8 cli_script[128], recv_script[128], game_data_out[100], response[4], ms_head[6];
static u32 cli_pc, cli_mode, cli_result, cli_errors, cli_got;       /* mode: 0 run, 1 receiving, 2 sending, 3 done */
static u32 mr_state, mr_want, mr_size, mr_at, mr_crc, mr_cap, mr_run;
static u8 *mr_dst;
static const u8 *ms_src;
static u32 ms_state, ms_len, ms_size, ms_at, standby_due, standby_timer, standby_ok, close_due;
#define GIFT_W ((u8 *)gift_words)

static void mg_trace_error(u32 what)
{
    cli_errors++;
    trace(EV_MG_ERROR, 0, what);
}

static void mr_block(void)              /* a whole block from the game (row 0), after the link players */
{
    if (mr_state == 0) {                                            /* MysteryGiftLink_Recv: the header */
        u32 ident = rb.head[0] | rb.head[1] << 8;
        mr_crc = rb.head[2] | rb.head[3] << 8;
        mr_size = rb.head[4] | rb.head[5] << 8;
        if (cli_mode != 1 || ident != mr_want || mr_size > 0x400) {
            mg_trace_error(0x10000 | ident);
            return;
        }
        mr_dst = ident == MG_CLIENT_SCRIPT ? recv_script : ident == MG_RAM_SCRIPT ? GIFT_W + 4 + 0x14C
               : ident == MG_CARD || ident == MG_NEWS ? GIFT_W + 4 : 0;
        mr_cap = ident == MG_CLIENT_SCRIPT ? sizeof recv_script : ident == MG_RAM_SCRIPT ? 1000
               : ident == MG_CARD ? 0x14C : ident == MG_NEWS ? 0x1BC : 0;
        if (mr_dst == recv_script)
            memset(recv_script, 0, sizeof recv_script);
        mr_state = 1; mr_at = 0; mr_run = 0x1121;
        return;
    }
    u32 n = mr_size - mr_at < 252 ? mr_size - mr_at : 252;
    mr_run = crc16(rb.head, n, mr_run);
    for (u32 i = 0; i < n; i++)
        if (mr_at + i < mr_cap)
            mr_dst[mr_at + i] = rb.head[i];
    mr_at += n;
    if (mr_at < mr_size)
        return;
    mr_state = 0;
    if ((u16)~mr_run != mr_crc) {                                   /* the game would call LinkRfu_FatalError */
        mg_trace_error(0x20000 | mr_want);
        cli_mode = CLI_DONE; cli_result = 0xFF;
        return;
    }
    cli_got = mr_size;
    trace(EV_MG_GOT, 0, mr_want << 16 | mr_size);
    cli_mode = 0;
}

static void ms_load(u32 ident, const u8 *src, u32 len, u32 size)   /* MysteryGiftLink_InitSend */
{
    static const u8 zero = 0;
    u16 crc = crc16(src, len, 0x1121);
    for (u32 i = len; i < size; i++)
        crc = crc16(&zero, 1, crc);
    crc = ~crc;
    ms_head[0] = ident; ms_head[1] = ident >> 8; ms_head[2] = crc; ms_head[3] = crc >> 8;
    ms_head[4] = size; ms_head[5] = size >> 8;
    ms_src = src; ms_len = len; ms_size = size;
}

static void ms_step(void)               /* MysteryGiftLink_Send: the next of our blocks, when it's time */
{
    if (!ms_state)
        return;
    if (ms_state == 1) {
        cs_begin(ms_head, 6, 6);
        ms_state = 2; ms_at = 0;
    } else if (ms_state == 2) {
        u32 n = ms_size - ms_at < 252 ? ms_size - ms_at : 252;
        cs_begin(ms_src + ms_at, ms_len > ms_at ? ms_len - ms_at : 0, n);
        ms_at += n;
        if (ms_at >= ms_size) ms_state = 3;
    }
}

static void build_game_data(void)       /* struct MysteryGiftLinkGameData (pret:pokeemerald/src/mystery_gift.c:346) */
{
    memset(game_data_out, 0, sizeof game_data_out);
    game_data_out[0x00] = 0x01; game_data_out[0x01] = 0x01;        /* validationVar: GAME_DATA_VALID_VAR */
    game_data_out[0x04] = 1;                                        /* validationFlag1 */
    game_data_out[0x08] = 1;                                        /* validationFlag2 */
    game_data_out[0x0C] = 4 | 1;                                    /* validationGiftType1 (the news form passes for cards too) */
    game_data_out[0x10] = 1; game_data_out[0x11] = 0x02;            /* validationGiftType2: 0x201 */
    /* flagId (0x14) = 0: no Wonder Card, so the game sends its card straight away */
    game_data_out[0x43] = 0xBE; game_data_out[0x44] = 0xCF; game_data_out[0x45] = 0xC9;   /* playerName "DUO" */
    memset(game_data_out + 0x46, 0xFF, 5);
    game_data_out[0x4B] = HOST_TRAINER & 0xFF; game_data_out[0x4C] = HOST_TRAINER >> 8;
    memcpy(game_data_out + 0x5C, "BPEE", 4);                        /* romHeaderGameCode */
}

static void cli_run(void)               /* MysteryGiftClient's script, a few steps per table */
{
    for (u32 guard = 0; guard < 8 && cli_mode == 0; guard++) {
        if (cli_pc >= sizeof cli_script / 8) {
            cli_mode = CLI_DONE; cli_result = 0xFE;
            break;
        }
        const u8 *c = cli_script + 8 * cli_pc++;
        u32 instr = c[0] | c[1] << 8, param = c[4] | c[5] << 8;
        switch (instr) {
        case CLI_NONE: case CLI_COPY_MSG: case CLI_ASK_TOSS: break;
        case CLI_RETURN:
            cli_mode = CLI_DONE; cli_result = param;
            trace(EV_MG_DONE, 0, param);
            break;
        case CLI_RECV:  mr_want = param; mr_state = 0; cli_mode = 1; break;
        case CLI_SEND_LOADED: ms_state = 1; cli_mode = 2; break;
        case CLI_COPY_RECV: memcpy(cli_script, recv_script, sizeof cli_script); cli_pc = 0; break;
        case CLI_LOAD_GAME_DATA: build_game_data(); ms_load(MG_GAME_DATA, game_data_out, 100, 100); break;
        case CLI_SAVE_CARD: gift_words[0] = cli_got; break;
        case CLI_SAVE_RAM_SCRIPT: gift_ready = 1; break;
        case CLI_SAVE_NEWS:                                         /* saved, so "not the same": 0 */
            gift_words[0] = cli_got | 1 << 16; gift_ready = 1;
            response[0] = 0; ms_load(MG_RESPONSE, response, 4, 4);
            break;
        case CLI_LOAD_TOSS_RESPONSE: response[0] = 0; ms_load(MG_RESPONSE, response, 4, 4); break;
        case CLI_SEND_READY_END: ms_load(MG_READY_END, game_data_out, sizeof game_data_out, 0x400);
                                 ms_state = 1; cli_mode = 2; break;
        default: mg_trace_error(0x30000 | instr); cli_mode = CLI_DONE; cli_result = 0xFD; break;
        }
    }
}

static void cli_start(void)             /* MysteryGiftClient_Create: gMysteryGiftClientScript_Init */
{
    memset(cli_script, 0, sizeof cli_script);
    cli_script[0] = CLI_RECV; cli_script[4] = MG_CLIENT_SCRIPT;
    cli_script[8] = CLI_COPY_RECV;
    cli_pc = cli_mode = cli_result = cli_errors = 0;
    mr_state = ms_state = 0;
    gift_words[0] = 0; gift_ready = 0;
}

static void join_link(void)             /* one table from the game: pret RfuHandleReceiveCommand, as child */
{
    u32 done_before = rb.done;
    memset(tx_cmd, 0, sizeof tx_cmd);
    n_tables++;
    for (u32 j = 0; j < 7; j++)                                      /* row 0: the game's command */
        rx_cmd[j] = parent_uni[2 * j] | parent_uni[2 * j + 1] << 8;
    switch (rx_cmd[0] & 0xFF00) {
    case CMD_PLAYER_IDS: case CMD_PLAYER_IDS_NEW:
        n_players = rx_cmd[1];
        my_id = rx_cmd[2] & 0xFF;                                    /* linkPlayerIdx[childSlot 0] */
        break;
    case CMD_BLOCK_INIT: rb_init(); break;
    case CMD_BLOCK:      rb_chunk(rx_cmd[0] & 0xFF); break;
    case CMD_BLOCK_REQ:
        if (!cs.state && my_id) {
            build_player_block();
            cs_begin(player_block, sizeof player_block, rx_cmd[1] < 5 ? block_req_size[rx_cmd[1]] : 0);
        }
        break;
    case CMD_READY_EXIT: if (rx_cmd[1] == 0) standby_ok = 1; break;  /* the leader's, after ours */
    case CMD_READY_CLOSE: close_due = 2; break;                      /* Rfu_SetCloseLinkCallback: agree */
    }
    if (rb.done != done_before) {
        if (!join_linked) {                                          /* the game's link player */
            join_linked = 1;
            memcpy(child_player, rb.head, sizeof child_player);
            trace(EV_LINK_PLAYERS, 0, child_player[20] | child_player[21] << 8 | child_player[22] << 16
                  | (u32)child_player[23] << 24);
            cli_start();
            standby_due = 1;                                         /* Rfu_SetLinkStandbyCallback (child) */
        } else {
            mr_block();
        }
    }
    if (my_id && my_id < 5) {                                        /* our row: what the game got from us */
        u32 e = parent_uni[14 * my_id] | parent_uni[14 * my_id + 1] << 8;
        if ((e & 0xFF00) == CMD_BLOCK_INIT && cs.state == 1 && cs.wait >= CS_INITS)
            cs.state = 2;
        if ((e & 0xFF00) == CMD_BLOCK && (e & 0x1F) < 24)
            cs.echo |= 1u << (e & 0x1F);
    }
    if (cs.state == 3 && cs.echo == (1u << cs.count) - 1) {
        cs.state = 4; cs.wait = 0;
        if (cs.src == player_block)
            trace(EV_BLOCK_SENT, 0, cs.count);
    }
    if (ms_state == 3 && cs.state == 4) {                            /* our last block is in */
        ms_state = 0;
        cli_mode = 0;
    }
    if (join_linked && cli_mode == 0)
        cli_run();
    if (cs.state == 0 || (cs.state == 4 && ++cs.wait > MS_GAP)) {   /* free to say something else */
        if (close_due) {
            close_due--;
            tx_cmd[0] = CMD_READY_CLOSE;
            trace(EV_CLOSE, 0, cli_result);
        } else if (standby_due && !standby_ok && (standby_timer++ == 0 || standby_timer > 60)) {
            tx_cmd[0] = CMD_READY_EXIT;                              /* allReadyNum 0 (SendReadyExitStandbyUntilAllReady) */
            standby_timer = 1;
        } else {
            ms_step();
        }
    }
    if (!tx_cmd[0]) {
        switch (cs.state) {
        case 1:
            tx_cmd[0] = CMD_BLOCK_INIT; tx_cmd[1] = cs.count; tx_cmd[2] = my_id + 0x80;
            cs.wait++;
            break;
        case 2:
            cs_chunk(cs.next++);
            if (cs.next >= cs.count) { cs.state = 3; cs.wait = 0; }
            break;
        case 3:
            if (++cs.wait > 2) {                                     /* a chunk the game missed: again */
                for (u32 k = 0; k < cs.count; k++) {
                    u32 n = cs.next + k;
                    if (n >= cs.count) n -= cs.count;
                    if (!(cs.echo >> n & 1)) { cs_chunk(n); cs.next = n + 1; break; }
                }
            }
            break;
        }
    }
    if (tx_cmd[0]) {
        tx_cmd[0] |= child_seq << 5;
        child_seq = (child_seq + 1) & 7;
    }
}

static void join_receive(void)          /* the game's 0x24/0x25: total bytes, then parent sub-frames */
{
    u32 bytes = req[0] & 0x7F, at = 0;
    const u8 *d = (const u8 *)&req[1];
    child_frames++;
    ni_end_seen = 0;                     /* (set again by an end frame in this packet) */
    while (bytes - at >= 3 && at < 4 * 31) {
        u32 h = d[at] | d[at + 1] << 8 | d[at + 2] << 16, len = h & 0x7F;
        u32 st = h >> 14 & 0xF, ph = h >> 9 & 3, n = h >> 11 & 3;
        if (!(h >> 22 & 3) && (h >> 18 & 1) && st == LCOM_UNI && len <= UNI_BYTES) {
            memcpy(parent_uni, d + at + 3, len);                     /* stage H2b: the game's table */
            memset(parent_uni + len, 0, UNI_BYTES - len);
            parent_uni_new = 1;
        } else if (!(h >> 22 & 3) && (h >> 18 & 1) && st != LCOM_UNI) {
            if (h >> 13 & 1) {
                if (nis.state & NI_BUSY)
                    nis_ack(st, ph, n);                              /* the game acknowledging our name */
            } else {
                ni_receive(st, ph, n, len, d + at + 3);              /* its answer to us */
            }
        }
        at += 3 + len;
    }
    if (ni.state == NI_RECV_LAST && !ni_end_seen && !join_answered) {     /* librfu's rfu_CB_recvData */
        ni.state = NI_RECV_OK;
        join_answered = 1;
        trace(EV_JOIN_ANSWER, 0, child_name[0]);
    }
}

static u32 join_frame(void)             /* our frame for the game's next 0x26: bytes << 8, then ours */
{
    u8 *out = (u8 *)&hf[1];
    u32 bytes = 0;
    if (ni.state & NI_BUSY) {                                        /* acknowledging its answer */
        u32 f = (ni.state & 0xF) << 10 | 1u << 9 | ni.phase << 5 | ni.n[ni.phase] << 7;
        out[0] = f; out[1] = f >> 8;
        bytes = 2;
    }
    if (nis.state & NI_BUSY) {
        u32 was_null = nis.state == NI_SEND_NULL;
        bytes += nis_frame(out + bytes);
        if (was_null) {
            nis.state = NI_SEND_OK;
            join_named = 1;
            trace(EV_NAME_SENT, 0, 0);
        }
    }
    if (parent_uni_new) {                                            /* UNI: one frame per table */
        parent_uni_new = 0;
        join_link();
        u32 h = LCOM_UNI << 10 | 14;
        out[bytes] = h; out[bytes + 1] = h >> 8;
        for (u32 j = 0; j < 7; j++) {
            out[bytes + 2 + 2 * j] = tx_cmd[j];
            out[bytes + 3 + 2 * j] = tx_cmd[j] >> 8;
        }
        bytes += 16;
    }
    u32 total = bytes;
    while (bytes & 3)
        out[bytes++] = 0;
    hf[0] = total << 8;                                              /* slot 0's byte count */
    return 1 + bytes / 4;
}
#endif

/* What the game sends us once connected: the first few data commands, word for word. This is
 * librfu's own framing of the child's first messages (its game name over the NI channel) - the
 * ground truth the host side will be built against. */
#define CAP_CMDS 3
#define CAP_WORDS 6
#ifdef LAB
static u32 cap_cmd[CAP_CMDS], cap_data[CAP_CMDS][CAP_WORDS], cap_count;

static void capture(void)
{
    if (cap_count >= CAP_CMDS)
        return;
    u32 n = req_len < CAP_WORDS ? req_len : CAP_WORDS;
    cap_cmd[cap_count] = req_cmd | req_len << 8 | child_connected << 16;
    for (u32 i = 0; i < n; i++)
        cap_data[cap_count][i] = req[i];
    cap_count++;
}
#else
#define capture() ((void)0)
#endif

static void respond(void)
{
    u32 cmd = req_cmd;
    ack_len = 0;
    swap_after = 0;
    switch (cmd) {
    case 0x10: adapter_state = ST_IDLE; child_connected = 0; break;   /* Hello / reset */
    case 0x11: ack[0] = child_connected ? 0xFF : 0; ack_len = 1; break; /* signal levels */
    case 0x12: ack[0] = 0x00830117; ack_len = 1; break;                /* version */
    case 0x13: ack[0] = (adapter_state == ST_ASLEEP ? 0 : adapter_state) << 24
                       | (child_connected ? 1 << 16 | CHILD_ID : 0); ack_len = 1; break;
    case 0x14: ack[0] = 0xFF; ack_len = 1; break;                      /* slot status */
    case 0x15: memset(ack, 0, 7 * 4); ack[6] = 257; ack_len = 7; break;
    case 0x16: {                                                       /* broadcast data */
        u32 compat = req[0] >> 16, lang = compat & 0xF;               /* RfuGameCompatibilityData */
        memcpy(game_config, req, sizeof game_config);
        if (lang) host_lang = lang;
#ifdef UNION_ROOM
        dist_serial = 0x0002;                                          /* RFU_SERIAL_GAME */
#else
        dist_serial = pc_serial ? pc_serial
                    : lang == 1 && (compat >> 10 & 0xF) == 3 ? SERIAL_JP_EMERALD : SERIAL_DECOMP;
#endif
        build_host();
        break;
    }
    case 0x17: system_config = req[0]; break;                          /* setup */
    case 0x19: adapter_state = ST_HOST_OPEN; break;
#ifdef GAME_HOSTS
    case 0x1A: case 0x1B:                                              /* our child joins */
        if (++join_polls > 3) {
            ack[0] = CHILD_ID;                                         /* its ID, slot 0 */
            ack_len = 1;
            if (!child_connected) {
                child_connected = 1;
                ni_reset();
                nis_start(our_name, sizeof our_name, 1, 14);           /* data type 1: our name */
                memset(&cs, 0, sizeof cs); memset(&rb, 0, sizeof rb);
                my_id = n_players = child_seq = join_linked = parent_uni_new = 0;
                standby_due = standby_timer = standby_ok = close_due = 0;
                cli_mode = CLI_DONE;
                hf_len = 0;
                trace(EV_CONNECTED, 0, CHILD_ID);
            }
        }
        break;
#else
    case 0x1A: break;                                                  /* nobody joined */
#endif
#ifndef GAME_HOSTS
    case 0x1B: adapter_state = ST_HOST_CLOSED; break;
#endif
#ifndef GAME_HOSTS                                                     /* (the DUO only joins) */
    case 0x1C: adapter_state = ST_SEARCHING; break;
    case 0x1D: case 0x1E:                                              /* who is in range */
        if (host_on && (adapter_state == ST_SEARCHING || cmd == 0x1E)) {
            /* n_hosts = 4 is the PC's --check-search: librfu restarts its search (0x1E, 0x1C) as
             * soon as one answer holds four entries whose checksums are good - proof on real
             * hardware that our answer's data words arrive intact. */
            for (u32 k = 0; k < n_hosts; k++) {
                u32 id = HOST_ID + k;
                memcpy(ack + 7 * k + 1, host_cfg, sizeof host_cfg);
                if (sweep) {
                    id = next_sweep_serial();
                    ack[7 * k + 1] = (host_cfg[0] & 0xFFFF0000) | id;  /* (not in the checksum) */
                }
                ack[7 * k] = id;                                       /* id, next free slot 0 */
            }
            ack_len = 7 * n_hosts;
        }
        if (cmd == 0x1E) adapter_state = ST_IDLE;
        break;
    case 0x1F:
        adapter_state = ST_CONNECTING;
        connect_polls = host_on && (sweep || (req[0] & 0xFFFF) - HOST_ID < n_hosts) ? 1 : 0;
        if (sweep) found_serial = req[0] & 0xFFFF;
        break;
    case 0x20: case 0x21:                                              /* connected yet? */
        if (connect_polls && (cmd == 0x21 || ++connect_polls > 2)) {
            ack[0] = CHILD_ID;                                         /* slot 0, status 0: done */
            child_connected = 1;
            adapter_state = ST_CONNECTED;
            ni_reset();
            memset(&nis, 0, sizeof nis);
            link_state = LS_OFF; hf_len = 0; child_uni_new = 0; uni_acked = 0;
            memset(&bs, 0, sizeof bs); memset(&rb, 0, sizeof rb);
            mg_step = mg_sub = mg_got = 0;
#ifdef UNION_ROOM
            if (corner) mg_step = UR_CORNER_WAIT;
            standbys = corner_wait = 0;
#endif
            if (cmd == 0x21) trace(EV_CONNECTED, 0, CHILD_ID);
        } else {
            ack[0] = connect_polls ? 0x01000000 : 0x04000000;          /* trying / failed */
            if (cmd == 0x21) adapter_state = ST_IDLE;
        }
        ack_len = 1;
        break;
#endif
#ifdef GAME_HOSTS
    case 0x24: if (child_connected) join_receive(); break;
    case 0x25: if (child_connected) join_receive(); swap_after = 1; break;
#else
    case 0x24: capture(); if (child_connected) host_receive(); break;
    case 0x25: capture(); if (child_connected) host_receive(); swap_after = 1; break;
#endif
    case 0x26: memcpy(ack, hf, hf_len * 4); ack_len = hf_len; break;  /* the host's packet (again, if retried) */
    case 0x27: swap_after = 1; break;
    case 0x30: child_connected = 0; adapter_state = ST_IDLE; break;
    case 0x32: case 0x34: break;
    case 0x33: ack[0] = 0x01000000; ack_len = 1; break;
    case 0x35: case 0x37: swap_after = 1; break;
    case 0x3D: adapter_state = ST_ASLEEP; break;
    default:   ack[0] = 2; ack_len = 1; cmd = 0xEE - 0x80; break;      /* unknown command */
    }
    ack[31] = 0x99660000 | (ack_len << 8) | ((cmd + 0x80) & 0xFF);
}

/* ------------------------------------------------------------------ ID exchange (Sio32ID) */
static const u16 nintendo[4] = { 0x494E, 0x544E, 0x4E45, 0x4F44 };
static u32 id_count, id_send, id_recv, id_last;

static void id_reset(void) { id_count = id_send = id_recv = id_last = 0; }

static u32 id_step(u32 d)              /* librfu Sio32ID, adapter side; returns our next word */
{
    u32 theirs = d & 0xFFFF, echoed = d >> 16;
    if (id_last == 0) {
        if (echoed == id_recv) {
            if (id_count < 4) {
                if (id_recv == (~id_send & 0xFFFF) && theirs == (~id_recv & 0xFFFF))
                    id_count++;
            } else {
                id_last = theirs;
            }
        } else {
            id_count = 0;
        }
    }
    id_send = id_count < 4 ? nintendo[id_count] : RFU_ID;
    id_recv = ~theirs & 0xFFFF;
    return (id_send << 16) | id_recv;
}

/* ------------------------------------------------------------------ the link port */
enum { PH_COMMAND, PH_REQUEST, PH_ACK_HEADER, PH_ACK_DATA, PH_ID };
static u32 phase, ack_next, req_next;

static void arm(u32 word)                /* clock slave, ready: next word loaded, SO low */
{
    SIODATA32 = word;
    SIOCNT = CNT_32BIT | CNT_START;
}

#ifdef PROBE
/* ------------------------------------------------------------------ 2 MHz probe (adapter_probe)
 * Real hardware (lab session 11): the game's words reach us at 2 MHz, but it rejects our
 * 0x80000000. Each attempt of a command tries one way of loading that answer:
 *   E_LAG1      every bit arrives one clock late: load W << 1 and hold SO at W's top bit
 *   E_FIRSTBIT  only the first bit is late: load W and hold SO at its top bit
 *   E_PLAIN     as designed (fails on real hardware so far)
 * The game only goes on to the ready handshake if it got exactly 0x80000000, so a handshake
 * after the first word means that encoding works. Words after a handshake must be loaded with
 * SO low ("ready"); for top-bit-1 words we flick SO low just long enough for the game to see
 * it, and back high before its first clock edge - the counters say whether that worked. */
enum { E_LAG1, E_FIRSTBIT, E_PLAIN, N_ENC };
static u32 enc, tries[N_ENC], accepts[N_ENC], acks_ok[N_ENC], hs_count, hs_after_header;

static void arm_idle(void)
{
    if (enc == E_PLAIN) { arm(IDLE_WORD); return; }
    SIODATA32 = enc == E_LAG1 ? IDLE_WORD << 1 : IDLE_WORD;
    SIOCNT = CNT_32BIT | CNT_START | CNT_SO_HIGH;
}

static void arm_word(u32 w)
{
    u32 b = enc == E_PLAIN ? 0 : w >> 31, t0;
    SIODATA32 = enc == E_LAG1 ? w << 1 : w;
    if (!b) {
        SIOCNT = CNT_32BIT | CNT_START;
        return;
    }
    t0 = now();
    while (SIOCNT & CNT_START) {
        SIOCNT = CNT_32BIT | CNT_START;                       /* low: ready */
        SIOCNT = CNT_32BIT | CNT_START | CNT_SO_HIGH;         /* high before the first clock edge */
        for (volatile int i = 0; i < 2; i++) ;
        if (now() - t0 > HANDSHAKE_LINES)
            break;
    }
}

/* End of a command: the game's last handshake wants us low; once it has gone idle (low too),
 * load the next idle answer the probe's way (SO high). */
static void idle_after_command(void)
{
    arm(IDLE_WORD);
    if (enc != E_PLAIN && wait_si(0, HANDSHAKE_LINES))
        arm_idle();
}
#else
/* Real hardware (lab session 12): at 2 MHz the game reads the FIRST bit of each of our words
 * correctly only if SO is already resting at that bit's level (SIOCNT bit 3) - the other 31
 * bits are fine. So every word is loaded with SO at its top bit.
 *   - The first word of a command has no handshake: just rest SO at 1 (0x80000000).
 *   - After a handshake SO must go low to say "ready", but a top-bit-1 word needs SO high when
 *     the game's clock starts. So we FLICK it: low for a moment, then high again. The game starts
 *     its clock a microsecond or two after it notices the low (librfu_intr.c: handshake_wait(0),
 *     STWI_stop_timer_in_RAM, two SIOCNT writes), so the flick must be long enough to be noticed
 *     down the cable, and short enough to be over before that first clock edge.
 *   - Lab session 15 (29,562 flicks up to 12 us wide, none noticed; the game noticed at once when
 *     we sat disarmed and low): while armed, our SO shows the loaded word's first bit, whatever
 *     SIOCNT bit 3 says (as GBATEK describes an active transfer). So the flick now DISARMS for a
 *     moment - SO really goes low - and re-arms before the game's first clock edge. If the game
 *     clocks while we are still disarmed the word is lost: we see its SO go low with no word, and
 *     narrow the flick.
 *   - Lab sessions 12-14: a two-instruction flick (~0.25 us) is noticed only rarely. The width
 *     is now tuned while running: if the game never clocks, flicks get wider; if it clocks but
 *     then rejects the word (first bit wrong), they get narrower. Per-width counts go to the PC.
 *   - After each flick we keep our hands off SIOCNT for longer than a whole word (16 us):
 *     touching SIOCNT mid-word loses it (session 13).
 * The end of a command needs a plain low (unarmed) until the game has gone idle. */
static u32 n_stray, n_flick_timeouts;

#define W_MAX 13                         /* (the simulator's tuning test climbs to 12) */
volatile u32 flick_w = 1;                /* spin-loop iterations the flick stays low (tuned) */
static int last_flick = -1;              /* width of the flick that started the last word, or -1 */
static int flick_good = -1;              /* the last width the game accepted, or -1 */
#ifdef LAB
/* The lab build (adapter_lab, --lab on the PC) also keeps per-width flick counts, a link-port
 * scope (SI sampled after the first flicks), a capture of the game's first data commands and the
 * timing calibration. The everyday build leaves them out to make room. */
#define LAB_ONLY(x) x
static u16 w_pulses[W_MAX + 1], w_clocked[W_MAX + 1], w_accepted[W_MAX + 1], w_rejected[W_MAX + 1];
static u32 spin_per_8_lines, polls_per_8_lines;
#define SCOPE_N 3
static u32 scope_si[SCOPE_N][2], scope_meta[SCOPE_N], scope_count;
#else
#define LAB_ONLY(x)
#endif

static void spin(u32 n)                  /* two instructions a step: fine, even steps */
{
    if (n)
        __asm__ volatile("1: subs %0, %0, #1\n\tbne 1b" : "+l"(n) : : "cc");
}

#ifdef LAB
static u32 count_8_lines(int polls)       /* units of work done in 8 scanlines (0 if VCOUNT is stuck) */
{
    u32 n = 0, guard = 0, v = VCOUNT & 0xFF;
    while ((VCOUNT & 0xFF) == v)
        if (++guard > 200000) return 0;
    v = (VCOUNT & 0xFF) + 8;
    if (v >= LINES_PER_FRAME) v -= LINES_PER_FRAME;
    while ((VCOUNT & 0xFF) != v) {
        if (polls) {
            for (int i = 0; i < 16; i++)
                if (!(SIOCNT & 0x8000)) n++;             /* the same shape as the quiet-spell poll */
        } else {
            spin(16);
            n += 16;
        }
        if (n > 4000000) return 0;
    }
    return n;
}

static void calibrate(void)              /* how fast spin() and the polling loop run */
{
    spin_per_8_lines = count_8_lines(0);
    polls_per_8_lines = count_8_lines(1);
}
#endif

static void arm_idle(void)
{
    SIODATA32 = IDLE_WORD;
    SIOCNT = CNT_32BIT | CNT_START | CNT_SO_HIGH;
}

static void judge_flick(int accepted);

#define FLICK_QUIET 40          /* polls of SIOCNT (see calibrate): well over one 16 us word */
#define PULSES_PER_WIDTH 4
#define FLICK_LINES 790        /* ~50 ms of flicking: inside librfu's 80 ms handshake timeout */

static void arm_word(u32 w)
{
    u32 t0, tries = 0;
    LAB_ONLY(u32 cap = scope_count < SCOPE_N ? scope_count : SCOPE_N;)
    SIODATA32 = w;
    last_flick = -1;
    if (!(w >> 31)) {
        /* Lab session 17: arming straight from "resting high" leaves SO high, so the game never
         * saw us ready and never clocked the word. Go low unarmed first, then arm at once -
         * two stores, as narrow as a width-0 flick - so SO is low both before and after. */
        SIOCNT = CNT_32BIT;
        SIOCNT = CNT_32BIT | CNT_START;
        return;
    }
    SIOCNT = CNT_32BIT | CNT_START | CNT_SO_HIGH;             /* armed: SO shows the word's first bit */
    if (flick_good >= 0)
        flick_w = flick_good;                                 /* start from the last width that worked */
    t0 = now();
    for (;;) {
        u32 fw = flick_w, si_bits[2] = { 0, 0 }, done_at = 0xFF;
        SIOCNT = CNT_32BIT;                                   /* disarmed for a moment: SO really low */
        spin(fw);
        SIOCNT = CNT_32BIT | CNT_START | CNT_SO_HIGH;         /* armed again before the first clock edge */
        LAB_ONLY(w_pulses[fw]++;)
        for (u32 i = 0; i < FLICK_QUIET; i++) {
            u32 c = SIOCNT;
            if (i < 64 && (c & CNT_SI))
                si_bits[i >> 5] |= 1u << (i & 31);
            if (!(c & CNT_START)) { done_at = i; break; }
        }
        /* The game went low (it saw us and clocked) but our word never completed: it clocked while
         * we were still disarmed, and the word is lost. The pulse is too wide. */
        int lost = done_at == 0xFF && (si_bits[0] != 0xFFFFFFFF || (si_bits[1] & 0xFF) != 0xFF);
#ifdef LAB
        if (cap < SCOPE_N && (done_at != 0xFF || tries == 0 || lost)) {
            scope_si[cap][0] = si_bits[0];
            scope_si[cap][1] = si_bits[1];
            scope_meta[cap] = fw | (done_at << 8) | (w & 0xFFFF0000);
            scope_count = ++cap;
        }
#endif
        if (done_at != 0xFF) {
            LAB_ONLY(w_clocked[fw]++;)
            last_flick = fw;                                  /* judged at the next handshake */
            return;
        }
        if (lost) {
            LAB_ONLY(w_clocked[fw]++;)
            last_flick = fw;
            judge_flick(0);                                   /* narrower; the game will retry */
            return;
        }
        if (++tries % PULSES_PER_WIDTH == 0 && flick_w < W_MAX)
            flick_w++;                                        /* not noticed: wider */
        if (now() - t0 > FLICK_LINES) {
            n_flick_timeouts++;
            trace(EV_FLICK_TIMEOUT, 0, w);
            return;
        }
    }
}

/* Called by the next handshake: did the game accept the word that flick started? */
static void judge_flick(int accepted)
{
    if (last_flick < 0)
        return;
    if (accepted) {
        LAB_ONLY(w_accepted[last_flick]++;)
        flick_good = last_flick;
    } else {
        LAB_ONLY(w_rejected[last_flick]++;)
        flick_good = -1;
        if (flick_w > 0 && flick_w >= (u32)last_flick)
            flick_w = last_flick ? last_flick - 1 : 0;       /* clocked but refused: narrower */
    }
    last_flick = -1;
}

static void idle_after_command(void)
{
    SIOCNT = CNT_32BIT;                                       /* low, unarmed: the game's last check */
    /* It has seen us once it goes idle (low), and may start its next command microseconds later
     * (link_rfu_2 sends straight after receiving), so watch for that in a tight loop - no clock
     * reads - and re-arm at once. 200000 polls is well over the 10 ms handshake allowance. */
    for (u32 n = 0; n < 200000 && si(); n++)
        ;
    arm_idle();                                               /* rest high for the next command */
}
#endif

static void back_to_idle(void)
{
    phase = PH_COMMAND;
    SIOCNT = CNT_32BIT;
    arm_idle();
}

/* After every word of a command: SO high, wait for the game's SO high, then load the next
 * word, arm, and drop SO in one write - the game starts the next word when it sees us low. */
static int handshake_then_arm(u32 word)
{
    SIOCNT = CNT_32BIT | CNT_SO_HIGH;
    if (!wait_si(1, HANDSHAKE_LINES)) {
#ifndef PROBE
        judge_flick(0);
#endif
        n_lost++;
        trace(EV_LOST, 0, req_cmd | phase << 8 | ack_next << 16);   /* which word was refused */
#ifdef PROBE
        enc = enc + 1 < N_ENC ? enc + 1 : 0;                   /* the game will try again */
#endif
        back_to_idle();
        return 0;
    }
#ifdef PROBE
    if (hs_count == 0) accepts[enc]++;
    if (hs_after_header) acks_ok[enc]++;
    hs_count++;
    hs_after_header = 0;
#else
    judge_flick(1);
#endif
    if (phase == PH_COMMAND) {                                 /* the command is complete */
        idle_after_command();
        return 1;
    }
    arm_word(word);
    return 1;
}

/* Clock master for one word (the game is waiting as clock slave). */
static int master_word(u32 word, u32 *got)
{
    if (!wait_si(0, HANDSHAKE_LINES))            /* the game is armed and ready */
        return 0;
    SIODATA32 = word;
    SIOCNT = CNT_32BIT | CNT_2MHZ | CNT_INTERNAL;
    SIOCNT = CNT_32BIT | CNT_2MHZ | CNT_INTERNAL | CNT_START;
    while (SIOCNT & CNT_START)
        ;
    *got = SIODATA32;
    return 1;
}

/* The game has handed us the clock. Wait (serving the PC) until there is something to tell
 * it, then send that command, take its acknowledgement and hand the clock back. */
static int pc_service(api_t *api);
static int stop_requested;

static void clock_master_turn(api_t *api)
{
    u32 frames = child_connected ? 1 : system_config & 0xFF, t0 = now(), got = 0, cmd;
    SIOCNT = CNT_32BIT | CNT_2MHZ | CNT_INTERNAL;           /* SO low */
    for (;;) {
        if (pc_service(api) || stop_requested)
            return;
        if (frames && now() - t0 >= frames * LINES_PER_FRAME)
            break;
    }
    cmd = child_connected ? 0x99660028 : 0x99660027;           /* data ready / nothing happened */
    if (child_connected) {                                     /* this frame's packet from the host */
        /* Once the link is up, the game answers every packet it gets with a UNI sub-frame. No
         * answer means the packet went astray (a failed transfer): send the same one again rather
         * than move on, because link_rfu_2 never resends the parent's blocks. Repeats are harmless. */
#ifdef GAME_HOSTS
        hf_len = join_frame();
#else
        if (hf_uni && !uni_acked && n_resent < 0xFFFF)
            n_resent++;
        else
            hf_len = host_frame();
#endif
        uni_acked = 0;
    }
    if (!master_word(cmd, &got)) goto failed;
    /* inverted handshake: we stay low, the game goes high, we go high, the game re-arms (low) */
    if (!wait_si(1, HANDSHAKE_LINES)) goto failed;
    SIOCNT = CNT_32BIT | CNT_2MHZ | CNT_INTERNAL | CNT_SO_HIGH;
    for (volatile int i = 0; i < 40; i++) ;                    /* the game wants >= 40 us */
    if (!master_word(IDLE_WORD, &got)) goto failed;
    if ((got & 0x7FFFFFFF) != ((cmd + 0x80) & 0x7FFFFFFF)) goto failed;  /* its first bit is late too */
    /* final handshake, then the game is clock master again */
    if (!wait_si(1, HANDSHAKE_LINES)) goto failed;
    SIOCNT = CNT_32BIT | CNT_2MHZ | CNT_INTERNAL | CNT_SO_HIGH;
    wait_si(0, HANDSHAKE_LINES);
    if (!child_connected)
        trace(EV_WAIT_TIMEOUT, 0, frames);
    back_to_idle();
    return;
failed:
    last_word = got;
    trace(EV_SWAP_FAILED, 0, got);
    back_to_idle();
}

static u32 last_word_at;

#if !defined(LAB) && !defined(PROBE)
/* ------------------------------------------------------------------ the DUO's screen */
/* A log line costs the GBA over a frame (the firmware redraws, then waits for the next frame), and
 * the wireless link must never wait: a missed word can make the game think there's no adapter, or
 * drop the gift. So lines go out only before the game has sent a single word (while the tool says
 * to keep it switched off), and once the PC has stopped us (the link is over by then). */
static u32 game_seen, say_loaded;
static void screen_before_game(api_t *api)
{
    if (game_seen || !say_loaded) return;
    say_loaded = 0;
    api->log(GIFT_IS_NEWS ? "Wonder News loaded" : "Wonder Card loaded");
    api->log("Waiting for the game");
}
#endif

static void link_word(api_t *api, u32 in)
{
#if !defined(LAB) && !defined(PROBE)
    game_seen = 1;
#endif
    last_word = in;
    last_word_at = now();
    switch (phase) {
    case PH_ID:
    case PH_COMMAND:
        if ((in >> 16) == 0x9966 && phase == PH_ID) {
            /* Our answer to this word was part of the ID exchange, not 0x80000000, so the
             * game ignores it and sends the command again ~130 ms later. Be ready for it. */
            phase = PH_COMMAND;
            arm_idle();
            return;
        }
        if (in == ack[31] && (in & 0x80)) {
            /* Our own last acknowledgement coming back: after sleep the game clocks once more
             * without loading a new word, so its buffer still holds our answer (0x996600BD,
             * 0x99660096). It isn't a command - ignore it and wait for the real one. (A genuinely
             * unknown command, even one with bit 7 set, is still refused politely.) */
            arm_idle();
            return;
        }
        if ((in >> 16) == 0x9966) {
#ifdef PROBE
            tries[enc]++;
            hs_count = 0;
            hs_after_header = 0;
#endif
            req_cmd = in & 0xFF;
            req_len = (in >> 8) & 0xFF;
            req_next = 0;
            phase = PH_REQUEST;
            if (req_len == 0)
                goto request_done;
            handshake_then_arm(IDLE_WORD);
            return;
        }
        if (phase == PH_COMMAND && in == IDLE_WORD) {          /* nothing for us */
#ifndef PROBE
            n_stray++;
            trace(EV_STRAY, 0, req_cmd);
#endif
            arm_idle();
            return;
        }
        if (phase != PH_ID) {                                  /* the game is resetting us */
            id_reset();
            phase = PH_ID;
        }
        {
            u32 before = id_last;
            u32 w = id_step(in);
            if (!before && id_last) {
                /* The last pair carried both IDs (game B0BB8001 / us 8001B0BB): the game is
                 * done too, and its next word is a command - which wants 0x80000000 from us. */
                n_id++;
                trace(EV_ID_EXCHANGE, 0, id_last);
                phase = PH_COMMAND;
#ifdef PROBE
                enc = E_LAG1;
#endif
                arm_idle();
                return;
            }
            arm(w);                                            /* no handshake in the ID exchange */
        }
        return;
    case PH_REQUEST:
        if (req_next < 32) req[req_next] = in;
        req_next++;
        if (req_next < req_len) {
            handshake_then_arm(IDLE_WORD);
            return;
        }
    request_done:
        n_commands++;
        if (link_state == LS_OFF || req_cmd < 0x24 || req_cmd > 0x27)  /* (once the link is up, the */
            trace(req_cmd, req_len, req_len ? req[0] : 0);             /*  per-frame traffic is not) */
        respond();
        phase = PH_ACK_HEADER;
        handshake_then_arm(ack[31]);
        return;
    case PH_ACK_HEADER:
    case PH_ACK_DATA:
#ifdef PROBE
        hs_after_header = phase == PH_ACK_HEADER;
#endif
        if (phase == PH_ACK_HEADER)
            ack_next = 0;
        if (ack_next < ack_len) {
            phase = PH_ACK_DATA;
            handshake_then_arm(ack[ack_next++]);
            return;
        }
        if (swap_after) {
            /* last handshake, then the game becomes clock slave */
            SIOCNT = CNT_32BIT | CNT_SO_HIGH;
            if (!wait_si(1, HANDSHAKE_LINES)) { back_to_idle(); return; }
            SIOCNT = CNT_32BIT;                                /* low: done */
            if (!wait_si(0, HANDSHAKE_LINES)) { back_to_idle(); return; }
            clock_master_turn(api);
            return;
        }
        phase = PH_COMMAND;
        handshake_then_arm(IDLE_WORD);
        return;
    }
}

/* ------------------------------------------------------------------ the PC */
static u8 pkt[8];
static u32 status_word(void)
{
    return (adapter_state & 0xFF) | (phase << 8) | (n_commands << 16);
}

static int pc_service(api_t *api)
{
    if (!api->avail())
        return 0;
    api->recv8(pkt);
    u32 arg = pkt[4] | pkt[5] << 8 | pkt[6] << 16 | (u32)pkt[7] << 24;
    if (pkt[3] == 0x2B) {
        api->reply(0x2B, status_word());
        stop_requested = 1;
        return 1;
    }
    if (pkt[3] == 0x2C) {                                      /* PUT: the next word of the gift */
        if (put_at < sizeof gift_words / 4)
            gift_words[put_at++] = arg;
        api->reply(0x2C, put_at);
        return 0;
    }
    u32 v, idx = arg >> 8, i = idx % TRACE_N;
    switch (arg & 0xFF) {
    case 0: v = status_word(); break;
    case 1: v = last_word; break;
    case 2: v = trace_count; break;
    case 3: v = trace_head[i]; break;
    case 4: v = trace_data[i]; break;
    case 5: v = n_id | (n_lost << 16); break;
#ifndef PROBE
    case 8: v = n_stray | (n_flick_timeouts << 16); break;
    case 17: v = (i & 7) < 8 ? child_name[4 * (i & 7)] | child_name[4 * (i & 7) + 1] << 8
                 | child_name[4 * (i & 7) + 2] << 16 | (u32)child_name[4 * (i & 7) + 3] << 24 : 0; break;
    case 18: v = (ni.state & 0xFFFF) | (child_frames & 0xFF) << 16 | (host_frames & 0xFF) << 24; break;
    case 19: v = nis.state; break;
#ifdef LAB
    case 15: v = cap_count; break;
    case 16: v = (idx >> 5) < CAP_CMDS ? ((idx & 31) == 31 ? cap_cmd[idx >> 5]
                                        : (idx & 31) < CAP_WORDS ? cap_data[idx >> 5][idx & 31] : 0) : 0; break;
    case 9: v = i <= W_MAX ? (w_pulses[i] & 0xFFFF) | (w_clocked[i] << 16) : 0; break;
    case 10: v = i <= W_MAX ? (w_accepted[i] & 0xFFFF) | (w_rejected[i] << 16) : 0; break;
    case 11: v = flick_w | (scope_count << 8); break;
    case 12: v = spin_per_8_lines; break;
    case 13: v = polls_per_8_lines; break;
    case 14: v = (i >> 2) < SCOPE_N ? ((i & 3) == 0 ? scope_si[i >> 2][0] : (i & 3) == 1 ? scope_si[i >> 2][1]
                                        : scope_meta[i >> 2]) : 0; break;
#endif
#endif
#ifdef PROBE
    case 6: v = i < N_ENC ? (tries[i] | accepts[i] << 16) : 0; break;
    case 7: v = i < N_ENC ? acks_ok[i] : 0; break;
#endif
#ifndef PROBE
    case 20: put_at = 0; gift_ready = 0; v = sizeof gift_words; break;   /* start loading a gift */
    case 21:                                                   /* loaded: check it, then use it */
        v = api->crc32(gift_words, put_at * 4);
        gift_ready = GIFT_IS_NEWS ? put_at * 4 >= 4 + CARD_SIZE && CARD_SIZE >= 16 && CARD_SIZE <= 0x1BC
                                  : put_at * 4 >= 4 + CARD_SIZE + 1000 && CARD_SIZE >= 16 && CARD_SIZE <= 0x14C;
        build_host();                                          /* offer a card or news accordingly */
#if !defined(LAB) && !defined(PROBE)
        say_loaded = gift_ready;                               /* (shown after this reply, if still safe) */
#endif
        break;
    case 28: v = mg_resp | GIFT_IS_NEWS << 8 | gift_ready << 9; break;   /* news: did it already have it? */
    case 22: v = link_state | mg_step << 4 | mg_errors << 8 | (n_child_cmds & 0xFFFF) << 16; break;
    case 25: v = (n_uni & 0xFFFF) | n_resent << 16; break;
    case 27:                                                   /* --serial (0: choose by game) */
        if (idx) pc_serial = idx & 0x7FFF;
        v = dist_serial | (game_config[0] >> 16) << 16;
        break;
    case 26:                                                   /* --check-search, --sweep-serial */
#if !defined(LAB) && !defined(UNION_ROOM)
        if (idx & 0x10) { sweep = 1; n_hosts = 3; }
        else
#endif
        if (idx >= 1 && idx <= 4) n_hosts = idx;
        v = ((sweep_n >> 10) << 9 & 0x7FFF) | found_serial << 16;
        break;
    case 23: v = (i & 15) < 16 ? game_data[4 * (i & 15)] | game_data[4 * (i & 15) + 1] << 8
                 | game_data[4 * (i & 15) + 2] << 16 | (u32)game_data[4 * (i & 15) + 3] << 24 : 0; break;
    case 24: v = child_player[4 * (i & 15)] | child_player[4 * (i & 15) + 1] << 8
                 | child_player[4 * (i & 15) + 2] << 16 | (u32)child_player[4 * (i & 15) + 3] << 24; break;
#endif
#ifdef GAME_HOSTS
    case 31: v = idx < sizeof gift_words / 4 ? gift_words[idx] : 0; break;          /* what the game sent us */
    case 32: v = cli_result | cli_mode << 8 | gift_ready << 10 | join_linked << 11 | (cli_errors & 0xF) << 12
               | (n_tables & 0xFFFF) << 16; break;
#endif
#ifdef UNION_ROOM
    case 29: ur_offer = idx; build_host(); v = ur_offer; break;          /* the trading board's offer */
    case 34: corner = idx & 0x3F; build_host(); v = corner; break;      /* lead a Direct Corner group */
    case 33: v = idx < 10 ? chat_last[4 * idx] | chat_last[4 * idx + 1] << 8 | chat_last[4 * idx + 2] << 16
                 | (u32)chat_last[4 * idx + 3] << 24 : chat_count; break;   /* the player's last chat message */
    case 30: v = (i & 31) < 25 ? game_mon[4 * (i & 31)] | game_mon[4 * (i & 31) + 1] << 8
                 | game_mon[4 * (i & 31) + 2] << 16 | (u32)game_mon[4 * (i & 31) + 3] << 24 : 0; break;
#endif
    default: v = 0xFFFFFFFF; break;
    }
    api->reply(0x2A, v);
    return 0;
}

/* ------------------------------------------------------------------ entry */
__attribute__((section(".text.start")))
u32 start(api_t *api)
{
    u16 saved_rcnt = RCNT, saved_siocnt = SIOCNT;              /* handed back as we found them */
    RCNT = 0;
    SIOCNT = CNT_32BIT;
    adapter_state = ST_ASLEEP;
    phase = PH_ID;
    last_vcount = VCOUNT & 0xFF;
    build_host();
#ifdef LAB
    calibrate();
    last_vcount = VCOUNT & 0xFF;
#endif
#if !defined(LAB) && !defined(PROBE)
    api->log("Playing: Wireless Adapter");                     /* before the game is switched on */
#endif
    arm_idle();
    while (!stop_requested) {
        if (!(SIOCNT & CNT_START))
            link_word(api, SIODATA32);
        pc_service(api);
#if !defined(LAB) && !defined(PROBE)
        if (SIOCNT & CNT_START)                                /* (no word waiting to be handled) */
            screen_before_game(api);
#endif
        /* Every word of a command is handshaken, so a long silence mid-command means the
         * game gave up on it (and will reset us or start again): wait for a new command. */
        if (phase != PH_COMMAND && phase != PH_ID && now() - last_word_at > WATCHDOG_LINES) {
            n_lost++;
            trace(EV_LOST, 0, req_cmd | (phase | 0x80) << 8 | ack_next << 16);   /* never clocked */
            back_to_idle();
        }
    }
    SIOCNT = saved_siocnt & ~CNT_START;
    RCNT = saved_rcnt;
#if !defined(LAB) && !defined(PROBE) && !defined(UNION_ROOM)
    /* stopped by the PC, which waits until the game has hung up: the link is over */
    if (mg_step >= 6)
        api->log(GIFT_IS_NEWS ? "News sent: the game saves" : "Card sent: the game saves");
#endif
    return status_word();
}
