/* lab4p.c - the four-player cable experiment (8 November 2026; docs/MULTI.md, section 2). A lab
 * program: can the DUO's one GBA be three players on a two-player link cable?
 *
 * In the multi-player serial mode each GBA's hardware sends only its own slot: the master's word,
 * then each child's in turn, all on the one shared data line (SD), each unit starting once the one
 * before has finished (SI/SO chain). Players 2 and 3 are only time slots on that line. Here the
 * DUO, as the master, leaves the multi-player hardware alone and drives the link port itself in
 * general-purpose mode (RCNT), bit by bit at the games' 115,200 baud (about 146 CPU cycles a bit,
 * timed by timer 0): SC low for the transfer, its own word (a low start bit, 16 data bits from the
 * lowest, a high stop bit), SO low to hand the turn to the game, the game's word read off SD, then
 * - with three players of its own - two more words in slots 2 and 3, as children 2 and 3 would send
 * them, and SC high. Whether the game's hardware takes slots 2 and 3 from a GBA that isn't wired as
 * children 2 and 3 is what this finds out.
 *
 * What it does, by the PC's settings (BLOB):
 *   PLAYERS 1: the DUO as one player (slot 0 only): the control, proving the bit-by-bit link;
 *   PLAYERS 3: slots 0, 2 and 3: the link's handshake (link.c DoHandshake counts the handshake
 *              words in a row: four players if the game hears slots 2 and 3);
 *   LINK_TYPE (not 0): after the handshake, link players: 0x2222 from slot 0, then a 60-byte link
 *              player from each of the DUO's slots ("DUO", "DUO2", "DUO3"), and the game's. In the
 *              Trade Center (2 players only) a game that counts four refuses the link-up and closes
 *              it; one that counts two carries on as usual.
 * Everything goes into the log: the first words and timings, the handshake, every checksum (the
 * game's against the DUO's sums over two and four slots), the game's commands and blocks. */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef short s16;

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
#define SIOCNT      REG16(0x04000128)
#define RCNT        REG16(0x04000134)
#define REG_IE      REG16(0x04000200)
#define REG_IF      REG16(0x04000202)
#define REG_IME     REG16(0x04000208)
#define VCOUNT      REG16(0x04000006)
#define TM0CNT_L    REG16(0x04000100)
#define TM0CNT_H    REG16(0x04000102)

/* RCNT in general-purpose mode: bits 0-3 the levels of SC, SD, SI, SO; bits 4-7 their directions (1 out) */
#define GP          0x8000
#define P_SC        0x01
#define P_SD        0x02
#define P_SI        0x04
#define P_SO        0x08
#define OUT(p)      ((p) << 4)

#define LINES_PER_FRAME 228
#define MASTER_HS 0x8FFF
#define SLAVE_HS  0xB9A0
#define CMD_LEN   8

static void *memcpy(void *d, const void *s, unsigned n) { u8 *p = d; const u8 *q = s; while (n--) *p++ = *q++; return d; }
static void zero(void *d, unsigned n) { u8 *p = d; while (n--) *p++ = 0; }

static u32 lines_total, last_vcount;
static u32 now(void)
{
    u32 v = VCOUNT & 0xFF;
    u32 d = v >= last_vcount ? v - last_vcount : v + LINES_PER_FRAME - last_vcount;
    last_vcount = v;
    lines_total += d;
    return lines_total;
}

/* ------------------------------------------------------------------ what the PC loads, and the log */
#define BLOB_AT     0x02010030
#define BLOB_MAX    64
static u32 put_at, blob_ready;
#define blob_words  ((u32 *)BLOB_AT)
#define BLOB        ((u8 *)BLOB_AT)
#define PLAYERS     BLOB[0]             /* the DUO's players: 1 (slot 0) or 3 (slots 0, 2, 3) */
#define GAP_Q       BLOB[1]             /* the gap before slots 2 and 3, in quarter bits (default 4: one bit) */
#define BIT_ADJ     BLOB[2]             /* the bit time's correction, signed, in 1/256 cycle per bit */
#define LINK_TYPE   ((u16)(BLOB[4] | BLOB[5] << 8))   /* 0: the handshake only */
#define OUR_TID     (BLOB + 8)          /* 4 bytes */
#define OUR_NAME    (BLOB + 12)         /* 8 bytes: "DUO", then 2 and 3 added */
#define LABEL       ((const char *)BLOB + 32)   /* 28 */

#define LOG         ((u8 *)(BLOB_AT + 0x400))
#define LOG_MAX     0x1F800
static u32 log_len, log_full, log_seq;
enum { K_GAME, K_OURS, K_EVENT };
enum { E_WORD = 1, E_TIMING, E_HANDSHAKE, E_CHECKSUM, E_COMMAND, E_BLOCK, E_CLOSE, E_STOPBIT, E_SESSION };

static void log_bytes(const u8 *src, u32 len, u32 kind)
{
    if (log_full || log_len + 8 + len > LOG_MAX) { log_full = 1; return; }
    u8 *h = LOG + log_len;
    h[0] = len; h[1] = len >> 8; h[2] = kind; h[3] = log_seq++;
    memcpy(h + 4, src, len);
    log_len += 4 + ((len + 3) & ~3u);
}

static void log_event(u32 code, u32 arg)
{
    u8 e[4] = { code, code >> 8, arg, arg >> 8 };
    log_bytes(e, 4, K_EVENT);
}

/* ------------------------------------------------------------------ the bits */
static u32 bit_fp;                        /* the bit time in 1/256 cycles: 16777216 / 115200 = 145.64 */
static u16 rc;                            /* RCNT as we last set it */
static u32 timeouts, stop_errors, words_ok, edge_min = 0xFFFF, edge_max;

static inline u16 tnow(void) { return TM0CNT_L; }
static inline void until(u16 t) { while ((s16)(tnow() - t) < 0) ; }
static inline u16 at_bit(u16 t0, u32 k256) { return t0 + (u16)((bit_fp * k256) >> 16); }   /* k256: bits x 256 */
static inline void set_pins(u16 v) { rc = v; RCNT = v; }

static void put_word(u16 t0, u32 w)       /* our word on SD: start, 16 bits from the lowest, stop; SD released */
{
    until(t0);
    set_pins((rc | OUT(P_SD)) & ~P_SD);                      /* the start bit: low */
    for (u32 i = 0; i < 16; i++) {
        until(at_bit(t0, (i + 1) << 8));
        set_pins(w >> i & 1 ? rc | P_SD : rc & ~P_SD);
    }
    until(at_bit(t0, 17 << 8));
    set_pins(rc | P_SD);                                     /* the stop bit: high */
    until(at_bit(t0, 18 << 8));
    set_pins(rc & ~OUT(P_SD));                               /* SD back to an input (the game's turn) */
}

static u32 get_word(u16 from, u16 *end)   /* the game's word off SD: 0xFFFF if it never starts */
{
    u16 limit = at_bit(from, 12 << 8);
    while (RCNT & P_SD)
        if ((s16)(tnow() - limit) >= 0) { timeouts++; return 0xFFFF; }
    u16 te = tnow(), d = te - from;
    if (d < edge_min) edge_min = d;
    if (d > edge_max) edge_max = d;
    u32 w = 0;
    for (u32 i = 0; i < 16; i++) {
        until(at_bit(te, (i << 8) + 384));                   /* the middle of bit i (after a start bit) */
        if (RCNT & P_SD) w |= 1u << i;
    }
    until(at_bit(te, 17 * 256 + 128));
    if (!(RCNT & P_SD)) stop_errors++;
    *end = at_bit(te, 18 << 8);
    words_ok++;
    return w;
}

static u16 words[4];
static void transfer(const u16 *mine)     /* one multi-player transfer, the DUO the master */
{
    u16 saved_ime = REG_IME;
    REG_IME = 0;
    set_pins(GP | OUT(P_SC | P_SO) | P_SO);                  /* SC low: busy; SO high */
    u16 t = tnow() + 64;
    put_word(t, mine[0]);
    words[0] = mine[0];
    set_pins(rc & ~P_SO);                                    /* SO low: the game's turn */
    u16 end = tnow();
    words[1] = get_word(end, &end);
    words[2] = words[3] = 0xFFFF;
    if (PLAYERS >= 3 && words[1] != 0xFFFF) {
        u32 gap = GAP_Q ? GAP_Q : 4;
        u16 t2 = at_bit(end, gap << 6);
        put_word(t2, mine[2]);
        words[2] = mine[2];
        put_word(at_bit(t2, (18 << 8) + (gap << 6)), mine[3]);
        words[3] = mine[3];
    } else {
        until(at_bit(end, 3 << 8));                          /* (the timeout after the last unit) */
    }
    set_pins(GP | OUT(P_SC | P_SO) | P_SC | P_SO);          /* SC high, SO high: done */
    REG_IME = saved_ime;
}

/* ------------------------------------------------------------------ the link above the bits */
enum { ST_WAITING, ST_HANDSHAKE, ST_LINKED, ST_PLAYERS, ST_CLOSING, ST_DONE };
static u32 state, transfers, sessions, stop_requested, hs_seen, players_seen, close_pending, close_at;
static u32 sum_two, sum_four, ck_game_two, ck_game_four, ck_neither, cycles, link_sent;
static u16 game_first[8];
static u32 send_idx, recv_idx;
static u16 frame[CMD_LEN][4];
static u16 cur[4][CMD_LEN];               /* each of our slots' command this cycle */
static u8 lp[3][60];                      /* our link players */
static u32 tx_off[4], tx_on[4], tx_hdr[4];
static u8 game_block[64];
static u32 rx_size, rx_have, rx_on, game_closing, players_pending, not_master;

static void build_players(void)
{
    static const char magic[] = "GameFreak inc.";
    for (u32 k = 0; k < 3; k++) {
        u8 *b = lp[k];
        zero(b, 60);
        memcpy(b, magic, 14);
        memcpy(b + 44, magic, 14);
        u8 *p = b + 16;
        p[0] = game_block[16] ? game_block[16] : 2;          /* the game's version (Ruby if not yet seen) */
        memcpy(p + 4, OUR_TID, 4);
        p[4] += k;
        memcpy(p + 8, OUR_NAME, 8);
        if (k) {                                             /* "DUO2", "DUO3" */
            u32 n = 0;
            while (n < 6 && p[8 + n] != 0xFF) n++;
            p[8 + n] = 0xA1 + k + 1; if (n + 1 < 8) p[9 + n] = 0xFF;
        }
        p[0x14] = LINK_TYPE; p[0x15] = LINK_TYPE >> 8;
        p[0x1A] = game_block[16 + 0x1A] ? game_block[16 + 0x1A] : 2;
        p[0x18] = k ? k + 1 : 0;
    }
}

static void slot_command(u32 slot, u32 k)  /* slot's next command: its link player block, if it's sending */
{
    u16 *c = cur[slot];
    for (u32 i = 0; i < CMD_LEN; i++) c[i] = 0;
    if (game_closing) { c[0] = 0x5FFF; return; }
    if (!tx_on[slot]) return;
    if (!tx_hdr[slot]) { c[0] = 0xBBBB; c[1] = 60; c[2] = slot + 128; tx_hdr[slot] = 1; return; }
    c[0] = 0x8888;
    for (u32 j = 0; j < 7; j++) {
        u32 at = tx_off[slot] + 2 * j;
        c[1 + j] = (at < 60 ? lp[k][at] : 0) | (at + 1 < 60 ? lp[k][at + 1] : 0) << 8;
    }
    tx_off[slot] += 14;
    if (tx_off[slot] >= 60) tx_on[slot] = 0;
}

static void next_cycle(void)
{
    slot_command(0, 0);
    slot_command(2, 1);
    slot_command(3, 2);
    if (!game_closing && state == ST_LINKED && LINK_TYPE && !link_sent && cycles > 120) {   /* link players, please */
        cur[0][0] = 0x2222; cur[0][1] = LINK_TYPE;
        link_sent = 1;
        log_event(E_SESSION, LINK_TYPE);
    }
}

static void game_command(void)
{
    u16 c = frame[0][1];
    if (c && c != 0x8888) log_event(E_COMMAND, c);
    if (c == 0x2222 || frame[0][0] == 0x2222) {               /* everyone sends a link player: ours once the game's is here */
        players_pending = 1;
        if (state < ST_PLAYERS) state = ST_PLAYERS;
    }
    if (c == 0xBBBB) { rx_size = frame[1][1]; rx_have = 0; rx_on = 1; }
    else if (c == 0x8888 && rx_on) {
        for (u32 j = 1; j < CMD_LEN && rx_have < rx_size; j++, rx_have += 2) {
            if (rx_have < 64) game_block[rx_have] = frame[j][1];
            if (rx_have + 1 < 64) game_block[rx_have + 1] = frame[j][1] >> 8;
        }
        if (rx_have >= rx_size) {
            rx_on = 0;
            log_bytes(game_block, rx_size < 64 ? rx_size : 64, K_GAME);
            log_event(E_BLOCK, rx_size);
            if (players_pending && rx_size == 60) {               /* the game's version and language in ours */
                build_players();
                for (u32 k = 0; k < 4; k++) { tx_on[k] = k != 1; tx_off[k] = 0; tx_hdr[k] = 0; }
                players_pending = 0;
            }
        }
    }
    if (c == 0x5FFF && !game_closing) { game_closing = 1; state = ST_CLOSING; log_event(E_CLOSE, players_seen); }
}

static void on_words(void)                /* after each transfer: the link layer, as link.c's */
{
    transfers++;
    if (transfers <= 8) { game_first[transfers - 1] = words[1]; log_event(E_WORD, words[1]); }
    if (state < ST_LINKED) {
        static u32 prev, seen_all;
        u32 n = 0;
        for (u32 i = 0; i < 4; i++) {
            if ((words[i] & ~3) == SLAVE_HS || words[i] == MASTER_HS) n++;
            else break;
        }
        if (n > 1 && state < ST_HANDSHAKE) state = ST_HANDSHAKE;
        if (n > 1 && n == prev && words[0] == MASTER_HS) {    /* the handshake done, as DoHandshake sees it */
            players_seen = n; hs_seen++;
            state = ST_LINKED; sessions++;
            send_idx = CMD_LEN; recv_idx = 0; cycles = 0;     /* (the first transfer after: a checksum slot, 0) */
            sum_two = sum_four = 0;
            log_event(E_HANDSHAKE, n);
            return;
        }
        prev = n;
        seen_all = n == (PLAYERS >= 3 ? 4u : 2u) ? seen_all + 1 : 0;
        return;
    }
    if (send_idx == 0) {                                     /* the checksum slot just went */
        if (cycles > 1) {
            u16 g = words[1];
            if (g == (u16)sum_four && g == (u16)sum_two) { }
            else if (g == (u16)sum_four) ck_game_four++;
            else if (g == (u16)sum_two) ck_game_two++;
            else ck_neither++;
            if (g != (u16)sum_four && ck_game_two + ck_neither <= 8) log_event(E_CHECKSUM, g ^ (u16)sum_four);
        }
        sum_two = sum_four = 0;
    } else {
        for (u32 i = 0; i < 4; i++) frame[recv_idx][i] = words[i];
        sum_two += words[0] + words[1];
        sum_four += words[0] + words[1] + words[2] + words[3];  /* (as a four-player game sums: 0xFFFF data too) */
        if (++recv_idx == CMD_LEN) { game_command(); recv_idx = 0; }
    }
}

static void our_words(u16 *mine)          /* what our slots send in the next transfer */
{
    if (state < ST_LINKED) {
        static u32 sent;
        u32 ready = words[1] != 0xFFFF && (words[1] & ~3) == SLAVE_HS;
        sent = ready ? sent + 1 : 0;
        mine[0] = sent >= 20 ? MASTER_HS : SLAVE_HS;
        mine[2] = SLAVE_HS | 2; mine[3] = SLAVE_HS | 3;
        return;
    }
    if (send_idx == 0) { next_cycle(); cycles++; }
    if (send_idx == CMD_LEN) {                               /* the checksum: our sum over the slots we count */
        u16 ck = PLAYERS >= 3 ? sum_four : sum_two;
        mine[0] = mine[2] = mine[3] = ck;
        send_idx = 0;
        return;
    }
    mine[0] = cur[0][send_idx]; mine[2] = cur[2][send_idx]; mine[3] = cur[3][send_idx];
    send_idx++;
}

/* ------------------------------------------------------------------ the DUO's screen */
static const char *const SAY[] = { "4P lab: waiting for game", "4P lab: handshaking", "4P lab: linked",
                                   "4P lab: link players", "4P lab: the game closes", "4P lab: done" };
static u32 shown = 0xFF;

/* ------------------------------------------------------------------ the PC */
static u8 pkt[8];
static int pc_service(api_t *api)
{
    if (!api->avail())
        return 0;
    api->recv8(pkt);
    u32 arg = pkt[4] | pkt[5] << 8 | pkt[6] << 16 | (u32)pkt[7] << 24, v, idx = arg >> 8;
    if (pkt[3] == 0x2B) { api->reply(0x2B, state | transfers << 8); stop_requested = 1; return 1; }
    if (pkt[3] == 0x2C) {
        if (put_at < BLOB_MAX / 4) blob_words[put_at++] = arg;
        api->reply(0x2C, put_at);
        return 0;
    }
    switch (arg & 0xFF) {
    case 0: v = state | (sessions & 3) << 6 | (transfers & 0xFFFFFF) << 8; break;
    case 1: v = words_ok | timeouts << 16; break;
    case 2: v = stop_errors | players_seen << 16 | hs_seen << 24 | not_master << 31; break;
    case 3: v = edge_min | edge_max << 16; break;
    case 4: v = 4 * idx + 3 < log_len ? ((u32 *)LOG)[idx] : 0; break;
    case 5: v = log_len | log_full << 31; break;
    case 6: v = game_first[0] | game_first[1] << 16; break;
    case 7: v = (ck_game_two & 0xFFFF) | ck_game_four << 16; break;
    case 8: v = ck_neither | cycles << 16; break;
    case 9: v = game_block[16] | game_block[16 + 0x14] << 8 | game_block[16 + 0x15] << 16; break;
    case 20: put_at = 0; blob_ready = 0; v = BLOB_MAX; break;
    case 21: v = api->crc32(blob_words, put_at * 4);
             blob_ready = put_at * 4 >= BLOB_MAX && (PLAYERS == 1 || PLAYERS == 3);
             if (blob_ready) { log_len = log_full = log_seq = 0; bit_fp = (145 << 8) + 163 + (signed char)BIT_ADJ; }
             break;
    default: v = 0xFFFFFFFF; break;
    }
    api->reply(0x2A, v);
    return 0;
}

/* ------------------------------------------------------------------ entry */
__attribute__((section(".text.start")))
u32 start(api_t *api)
{
    u16 saved_ie = REG_IE, saved_rcnt = RCNT, saved_siocnt = SIOCNT, saved_tm = TM0CNT_H;
    TM0CNT_H = 0; TM0CNT_L = 0; TM0CNT_H = 0x80;              /* timer 0: the CPU clock, free-running */
    bit_fp = (145 << 8) + 163;
    last_vcount = VCOUNT & 0xFF;
    u32 next = now(), in_cycle = 0, idle_set = 0;
    while (!stop_requested) {
        pc_service(api);
        if (!blob_ready) continue;
        if (!idle_set) {                                     /* SC and SO high, SD an input: idle, as a master */
            idle_set = 1;
            set_pins(GP | OUT(P_SC | P_SO) | P_SC | P_SO);
            for (u32 i = 0; i < 1000; i++) not_master |= RCNT & P_SI;   /* (the master's SI is held low) */
            if (not_master) { api->log("4P lab: the DUO isn't master"); state = ST_DONE; }
        }
        if (shown != state && (state < ST_HANDSHAKE || state == ST_DONE)) {   /* (a line costs a frame: never while linked) */
            shown = state;
            api->log(SAY[state < 6 ? state : 5]);
            if (state == ST_WAITING && LABEL[0]) api->log(LABEL);
        }
        if (state == ST_DONE) continue;
        u32 t = now();
        /* the pace of link.c's master: one transfer a frame until linked, then a command of nine
         * transfers a frame, eight lines apart */
        if ((int)(t - next) < 0) continue;
        if (state < ST_LINKED) next = t + LINES_PER_FRAME;
        else if (++in_cycle < 9) next = t + 8;
        else { in_cycle = 0; next = t + LINES_PER_FRAME - 8 * 8; }
        u16 mine[4] = { 0, 0, 0, 0 };
        our_words(mine);
        transfer(mine);
        on_words();
        if (game_closing && !close_pending) { close_pending = 1; close_at = now(); }
        if (close_pending && now() - close_at > 30 * LINES_PER_FRAME) state = ST_DONE;
    }
    RCNT = saved_rcnt;
    SIOCNT = saved_siocnt;
    REG_IF = 0x80;
    REG_IE = saved_ie;
    TM0CNT_H = saved_tm;
    return state | transfers << 8;
}
