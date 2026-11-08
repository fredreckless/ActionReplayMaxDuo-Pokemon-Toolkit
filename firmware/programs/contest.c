/* contest.c - the DUO as a contestant in Emerald's link Contest, E mode (8 November 2026;
 * docs/CONTEST.md). Grown from blender.c: the same link engine and log. The DUO must be player 1:
 * the game, player 0, is the leader that works out the contest; every other GBA copies the leader's
 * figures. From pret's pokeemerald contest_link.c, contest_link_util.c, contest.c, contest_util.c and
 * cable_club.c:
 *   - the link-up (LINKTYPE_CONTEST_EMODE 0x6602, 2-4 players, all Emerald): link players (we say
 *     Emerald), our trainer card (the leader's 0xCCCC 2);
 *   - the set-up (Task_LinkContest_StartCommunicationEm), each step after a "ready" barrier: each
 *     player's struct ContestPokemon (64 bytes: ours, from the PC); the leader's random seed (4
 *     bytes, the leader's only); each player's leader ID (2 bytes, 0x6E: equal, so player 0 leads);
 *     each player's category (2 bytes); the leader's AI contestants (64 bytes each, the leader's
 *     only); each player's round-1 points (8 bytes) and turn order (4 bytes);
 *   - the contest (contest.c) and the results (contest_util.c): each player's contestant number (1
 *     byte), each player's move each round (2 bytes: one of ours, in turn), and many blocks where
 *     every player sends its own copy and the leader's is the one used (the appeals' state, the
 *     final standings). For those we send the game's own block back: it is the leader's, so ours is
 *     never read, and it has the size the game expects;
 *   - the link closed (0x5FFF) after the results.
 * Every block goes into the log, as blender.c's. */
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
#define SIOMULTI(i) REG16(0x04000120 + 2 * (i))
#define SIOCNT      REG16(0x04000128)
#define SIOMLT_SEND REG16(0x0400012A)
#define RCNT        REG16(0x04000134)
#define REG_IE      REG16(0x04000200)
#define REG_IF      REG16(0x04000202)
#define VCOUNT      REG16(0x04000006)

#define MULTI_MODE  0x2000
#define BAUD_115200 0x0003
#define CNT_SI      0x0004
#define CNT_ID_SHIFT 4
#define SI_LOW_NEEDED 16
#define CNT_START   0x0080
#define CNT_IRQ     0x4000
#define IF_SERIAL   0x0080
#define LINES_PER_FRAME 228
#define GAP_AFTER_DONE 13
#define LINK_UP_WAIT   (2 * LINES_PER_FRAME)

#define MASTER_HS 0x8FFF
#define SLAVE_HS  0xB9A0
#define CMD_LEN   8

#define LT_CONTEST_EMODE 0x6602
#define MON_SIZE    64            /* struct ContestPokemon */
#define BLK_MAX     256           /* BLOCK_BUFFER_SIZE */

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
#define BLOB_AT     0x02010030          /* build_v4.py BUFFER */
#define BLOB_MAX    248
static u32 put_at, blob_ready;
#define blob_words  ((u32 *)BLOB_AT)
#define BLOB        ((u8 *)BLOB_AT)
#define NMOVES      BLOB[0]             /* our moves, in the order we use them (1-4) */
#define OUR_GENDER  BLOB[1]             /* our trainer: 0 boy, 1 girl */
#define OUR_NAME    (BLOB + 4)          /* 8 bytes, game charset */
#define OUR_TID     (BLOB + 12)         /* 4 bytes */
#define ORDER       (BLOB + 16)         /* 4: the order of our moves (indexes into the Pokemon's) */
#define LABEL       ((const char *)BLOB + 20)   /* 28: a line for the screen */
#define MON         (BLOB + 48)         /* 64: our struct ContestPokemon, as the game sends it */
#define CARD        (BLOB + 112)        /* 100: our trainer card (struct TrainerCard) */

#define LOG         ((u8 *)(BLOB_AT + 0x400))
#define LOG_MAX     0x1F800
#define RX_MAX      0x400
static u32 log_len, log_full, log_seq, log_lost;
static u8 scratch[64];
enum { K_GAME, K_OURS, K_EVENT };
enum { E_SESSION = 1, E_CLOSE, E_READY, E_MON, E_SKIP, E_MIRROR, E_MOVE, E_INDEX, E_STANDINGS, E_TRUNCATED };

static u8 *log_room(u32 len)
{
    if (log_full || log_len + 8 + len > LOG_MAX) { log_full = 1; return 0; }
    return LOG + log_len + 4;
}

static void log_commit(u32 len, u32 kind)
{
    if (log_full || log_len + 8 + len > LOG_MAX) { log_full = 1; return; }
    u8 *h = LOG + log_len;
    h[0] = len; h[1] = len >> 8; h[2] = kind; h[3] = log_seq++;
    log_len += 4 + ((len + 3) & ~3u);
}

static u32 rx_on;
static u8 *rx_dst;
static void log_bytes(const u8 *src, u32 len, u32 kind)
{
    if (rx_on && rx_dst != scratch) { log_lost++; return; }
    u8 *d = log_room(len);
    if (!d) return;
    memcpy(d, src, len);
    log_commit(len, kind);
}

static void log_event(u32 code, u32 arg)
{
    u8 e[4] = { code, code >> 8, arg, arg >> 8 };
    log_bytes(e, 4, K_EVENT);
}

/* ------------------------------------------------------------------ progress, for the PC */
enum { ST_WAITING, ST_HANDSHAKE, ST_CONNECTED, ST_LINKUP, ST_SETUP, ST_CONTEST, ST_RESULTS, ST_DONE };
static u32 state, is_master, transfers, bad_checksums, game_lp_type, game_lp_lang, stop_requested;
static u32 role_known, si_low_run, sessions, hs_run, max_gap;
static u8 game_player[60];

static u32 close_pending, close_at, barriers, setup_blocks, seed_seen, rounds, mirrored, skipped, category;
static u8 blk[BLK_MAX];                   /* the game's block as it arrives (and ours, sent back) */
static u8 ours[4];                        /* our contestant number, our move */
static u8 standings[4], have_standings;

/* ------------------------------------------------------------------ the link layer */
static u32 send_idx, recv_idx, checksum, checksum_ready, nonzero;
static u16 frame[CMD_LEN][2], current[CMD_LEN];
#define QN 4
static u16 qcmd[QN][3];
static u32 qhead, qcount;
static u16 loaded;

static u32 rx_size, rx_have, rx_keep;
static u32 player_pending;

static const u8 *tx_src;
static u32 tx_len, tx_off, tx_on, tx_header;
static u8 our_player[60];


static void build_our_player(void)
{
    static const char magic[] = "GameFreak inc.";
    zero(our_player, 60);
    memcpy(our_player, magic, 14);
    memcpy(our_player + 44, magic, 14);
    u8 *lp = our_player + 16;
    lp[0] = 3; lp[1] = game_player[17];                      /* Emerald: E mode is Emerald only */
    memcpy(lp + 4, OUR_TID, 4);
    memcpy(lp + 8, OUR_NAME, 8);
    memcpy(lp + 0x14, game_player + 16 + 0x14, 4);           /* link type */
    memcpy(lp + 0x1A, game_player + 16 + 0x1A, 2);           /* language */
    lp[0x10] = 0x11;                                         /* the progress flags (National Dex, champion) */
    lp[0x13] = OUR_GENDER;
    lp[0x18] = 1;
}

static void queue(u16 w0, u16 w1, u16 w2)
{
    if (qcount == QN) return;
    u16 *q = qcmd[(qhead + qcount) % QN];
    q[0] = w0; q[1] = w1; q[2] = w2;
    qcount++;
}

static void send_block(const u8 *src, u32 len)
{
    tx_src = src; tx_len = len; tx_off = 0; tx_header = 0; tx_on = 1;
}

static void next_command(void)
{
    for (u32 i = 0; i < CMD_LEN; i++) current[i] = 0;
    if (qcount) {
        u16 *q = qcmd[qhead];
        current[0] = q[0]; current[1] = q[1]; current[2] = q[2];
        qhead = (qhead + 1) % QN; qcount--;
        return;
    }
    if (tx_on) {
        if (!tx_header) {
            current[0] = 0xBBBB; current[1] = tx_len; current[2] = (is_master ? 0 : 1) + 128;
            tx_header = 1;
            return;
        }
        current[0] = 0x8888;
        for (u32 j = 0; j < 7; j++) {
            u32 at = tx_off + 2 * j;
            u32 lo = tx_src && at < tx_len ? tx_src[at] : 0, hi = tx_src && at + 1 < tx_len ? tx_src[at + 1] : 0;
            current[1 + j] = lo | hi << 8;
        }
        tx_off += 14;
        if (tx_off >= tx_len) tx_on = 0;
    }
}

static void answer_request(u32 n)         /* 0xCCCC n: our block of that size */
{
    if (n == 2) {
        if (!CARD[0x38]) CARD[0x38] = 3;                     /* (the card's game: Emerald) */
        send_block(CARD, 100);
    }
    else send_block(0, n == 4 ? 40 : n == 3 ? 220 : n == 2 ? 100 : 200);
}

/* ------------------------------------------------------------------ the contest */
static u32 our_move(void)                 /* this round's move: the next in the PC's order */
{
    u32 n = NMOVES ? NMOVES : 1, i = rounds++;
    while (i >= n) i -= n;
    u32 k = ORDER[i] & 3, m = MON[30 + 2 * k] | MON[31 + 2 * k] << 8;
    for (k = 0; !m && k < 4; k++) m = MON[30 + 2 * k] | MON[31 + 2 * k] << 8;   /* (an empty slot: the first move) */
    return m;
}

static void game_block(u32 size)          /* a whole block from the game has arrived */
{
    u32 kept = rx_keep;
    if (rx_dst != scratch) log_commit(kept, K_GAME);
    if (kept < size) log_event(E_TRUNCATED, size);
    if (size == 60 && player_pending) {
        memcpy(game_player, blk, 60);
        game_lp_type = game_player[16 + 0x14] | game_player[16 + 0x15] << 8;
        game_lp_lang = game_player[16 + 0x1A];
        build_our_player();
        send_block(our_player, 60);
        player_pending = 0;
        log_event(E_SESSION, game_lp_type);
        if (state < ST_LINKUP) state = ST_LINKUP;
        return;
    }
    if (state == ST_LINKUP && size == 100) return;           /* the game's trainer card */
    if (state < ST_CONTEST && size == MON_SIZE && !setup_blocks) {   /* the contestants: ours */
        state = ST_SETUP; setup_blocks = 1;
        send_block(MON, MON_SIZE);
        log_event(E_MON, size);
        return;
    }
    if (state == ST_SETUP && ((size == 4 && !seed_seen) || size == 2 * MON_SIZE)) {   /* the leader's own */
        seed_seen = 1; skipped++;
        log_event(E_SKIP, size);
        return;
    }
    if (state == ST_SETUP && size == 2 && setup_blocks == 2) category = blk[0];
    if (state >= ST_SETUP) setup_blocks++;
    if (size == 1) {                                         /* our contestant number */
        state = state == ST_SETUP ? ST_CONTEST : ST_RESULTS;
        ours[0] = is_master ? 0 : 1;
        send_block(ours, 1);
        log_event(E_INDEX, ours[0]);
        return;
    }
    if (state >= ST_CONTEST && size == 2) {                  /* the round's move: ours */
        u32 m = our_move();
        ours[0] = m; ours[1] = m >> 8;
        send_block(ours, 2);
        log_event(E_MOVE, m);
        return;
    }
    if (state >= ST_CONTEST && size == 4) {                  /* (the last 4-byte block: the final standings) */
        memcpy(standings, blk, 4); have_standings = 1;
    }
    if (size <= BLK_MAX) {                                   /* every player's copy, the leader's used: the game's back */
        send_block(blk, size);
        mirrored++;
        log_event(E_MIRROR, size);
    }
}

static void process_command(void)
{
    u32 game = is_master ? 1 : 0, ours_id = 1 - game;
    u16 c = frame[0][game];
    if (c == 0x2222 || frame[0][ours_id] == 0x2222)
        player_pending = 1;
    switch (c) {
    case 0xBBBB:
        rx_size = frame[1][game];
        rx_keep = rx_size < RX_MAX ? rx_size : RX_MAX;
        rx_dst = log_room(rx_keep);
        if (!rx_dst) { rx_dst = scratch; if (rx_keep > sizeof scratch) rx_keep = sizeof scratch; }
        rx_have = 0; rx_on = 1;
        break;
    case 0x8888:
        if (!rx_on) break;
        for (u32 j = 1; j < CMD_LEN && rx_have < rx_size; j++) {
            u8 lo = frame[j][game], hi = frame[j][game] >> 8;
            if (rx_have < rx_keep) rx_dst[rx_have] = lo;
            if (rx_have < BLK_MAX) blk[rx_have] = lo;
            rx_have++;
            if (rx_have < rx_size) {
                if (rx_have < rx_keep) rx_dst[rx_have] = hi;
                if (rx_have < BLK_MAX) blk[rx_have] = hi;
                rx_have++;
            }
        }
        if (rx_have >= rx_size) { rx_on = 0; game_block(rx_size); }
        break;
    case 0xCCCC:
        answer_request(frame[1][game]);
        break;
    case 0x2FFE:
        queue(0x2FFE, 0, 0);
        barriers++;
        log_event(E_READY, barriers);
        break;
    case 0x5FFF:
        queue(0x5FFF, 0, 0);
        log_event(E_CLOSE, state);
        if (have_standings) log_event(E_STANDINGS, standings[0] | standings[1] << 8);
        close_pending = 1;
        break;
    }
}

static void new_session(void)
{
    rx_on = tx_on = player_pending = 0;
    qcount = 0;
}

static void on_transfer(void)
{
    u16 w[2] = { SIOMULTI(0), SIOMULTI(1) };
    transfers++;
    is_master = (SIOCNT >> CNT_ID_SHIFT & 3) == 0;
    role_known = 1;
    if (state == ST_HANDSHAKE || state == ST_WAITING || hs_run == 0xFFFF) {
        static u32 prev, seen_two;
        u32 n = 0;
        for (u32 i = 0; i < 2; i++) {
            if ((w[i] & ~3) == SLAVE_HS || w[i] == MASTER_HS) n++;
            else break;
        }
        if (n > 1 && n == prev && w[0] == MASTER_HS) {
            sessions++; hs_run = 0;
            send_idx = recv_idx = 0; checksum_ready = 0; nonzero = 0;
            new_session();
            if (state < ST_CONNECTED) state = ST_CONNECTED;
            loaded = 0;
            SIOMLT_SEND = loaded;
            return;
        }
        prev = n;
        seen_two = n == 2 ? seen_two + 1 : 0;
        loaded = is_master && seen_two >= 20 ? MASTER_HS : SLAVE_HS;
        SIOMLT_SEND = loaded;
        return;
    }
    u16 gw = w[is_master ? 1 : 0];
    hs_run = ((gw & ~3) == SLAVE_HS || gw == MASTER_HS) ? hs_run + 1 : 0;
    if (hs_run >= 3) {                                           /* the game opened a new link */
        hs_run = 0xFFFF;
        rx_on = tx_on = qcount = player_pending = 0;
        loaded = SLAVE_HS;
        SIOMLT_SEND = loaded;
        return;
    }
    if (send_idx == 0) {
        if (checksum_ready && (w[0] != checksum || w[1] != checksum) && !hs_run)
            bad_checksums++;
        checksum = 0; checksum_ready = 1;
    } else {
        frame[recv_idx][0] = w[0]; frame[recv_idx][1] = w[1];
        checksum = (checksum + w[0] + w[1]) & 0xFFFF;
        nonzero |= w[0] | w[1];
        recv_idx++;
        if (recv_idx == CMD_LEN) {
            if (nonzero) process_command();
            nonzero = 0;
        }
    }
    if (send_idx == CMD_LEN) {
        loaded = checksum;
    } else {
        if (send_idx == 0) next_command();
        loaded = current[send_idx++];
    }
    if (recv_idx == CMD_LEN)
        send_idx = recv_idx = 0;
    SIOMLT_SEND = loaded;
}

/* ------------------------------------------------------------------ the DUO's screen */
static const char *const SAY[] = {
    "Contest: waiting for game", "Contest: handshaking", "Contest: linked", "Contest: linking up",
    "Contest: setting up", "The contest", "The results", "Done: the link is closed",
};
static u32 shown = 0xFF, label_shown;

static void screen(api_t *api, int linked)
{
    if (shown == state || (linked && state != ST_DONE)) return;
    if (!label_shown) {
        label_shown = 1;
        api->log("Playing: Contest entrant");
        if (LABEL[0]) api->log(LABEL);
    }
    shown = state;
    if (state < sizeof SAY / sizeof SAY[0]) api->log(SAY[state]);
}

/* ------------------------------------------------------------------ the PC */
static u8 pkt[8];
static int pc_service(api_t *api)
{
    if (!api->avail())
        return 0;
    api->recv8(pkt);
    u32 arg = pkt[4] | pkt[5] << 8 | pkt[6] << 16 | (u32)pkt[7] << 24, v, idx = arg >> 8;
    if (pkt[3] == 0x2B) {
        api->reply(0x2B, state | transfers << 8);
        stop_requested = 1;
        return 1;
    }
    if (pkt[3] == 0x2C) {
        if (put_at < BLOB_MAX / 4)
            blob_words[put_at++] = arg;
        api->reply(0x2C, put_at);
        return 0;
    }
    switch (arg & 0xFF) {
    case 0: v = state | is_master << 5 | (sessions & 3) << 6 | (transfers & 0xFFFFFF) << 8; break;
    case 1: v = bad_checksums | barriers << 16; break;
    case 2: v = game_lp_type | game_lp_lang << 16; break;
    case 3: v = rounds | category << 8 | (mirrored & 0xFF) << 16 | (skipped & 0xFF) << 24; break;
    case 4: v = 4 * idx + 3 < log_len ? ((u32 *)LOG)[idx] : 0; break;
    case 5: v = log_len | log_full << 31; break;
    case 6: v = game_player[16] | game_player[17] << 8 | game_player[18] << 16 | (u32)game_player[19] << 24; break;
    case 7: {
        u32 at = 16 + 4 + 4 * (idx < 3 ? idx : 0);
        v = game_player[at] | game_player[at + 1] << 8 | game_player[at + 2] << 16 | (u32)game_player[at + 3] << 24;
        break;
    }
    case 8: v = max_gap; break;
    case 9: v = have_standings ? standings[0] | standings[1] << 8 | standings[2] << 16 | (u32)standings[3] << 24 : 0xFFFFFFFF; break;
    case 10: v = log_lost; break;
    case 20: put_at = 0; blob_ready = 0; v = BLOB_MAX; break;
    case 21: v = api->crc32(blob_words, put_at * 4);
             blob_ready = put_at * 4 >= BLOB_MAX && NMOVES >= 1 && NMOVES <= 4;
             if (blob_ready) log_len = log_full = log_seq = 0;
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
    u16 saved_ie = REG_IE, saved_rcnt = RCNT, saved_siocnt = SIOCNT;
    REG_IE = saved_ie & ~IF_SERIAL;
    RCNT = 0;
    SIOCNT = MULTI_MODE | BAUD_115200 | CNT_IRQ;
    REG_IF = IF_SERIAL;
    loaded = SLAVE_HS;
    SIOMLT_SEND = loaded;
    last_vcount = VCOUNT & 0xFF;
    u32 last_done = now(), next_cycle = last_done, in_flight = 0, started_at = 0;
    u32 last_iter = now();
    while (!stop_requested) {
        u32 t = now();
        if (state >= ST_CONNECTED && t - last_iter > max_gap)
            max_gap = t - last_iter;
        last_iter = t;
        if (!role_known) {
            si_low_run = SIOCNT & CNT_SI ? 0 : si_low_run < SI_LOW_NEEDED ? si_low_run + 1 : si_low_run;
            is_master = si_low_run >= SI_LOW_NEEDED;
        }
        int linked = state >= ST_CONNECTED && hs_run != 0xFFFF;
        if (REG_IF & IF_SERIAL) {
            REG_IF = IF_SERIAL;
            in_flight = 0;
            int was = linked;
            if (blob_ready) on_transfer();
            last_done = now();
            if (!was && state >= ST_CONNECTED && hs_run != 0xFFFF)
                next_cycle = last_done + LINK_UP_WAIT;
        } else if (in_flight && now() - started_at > 2 * LINES_PER_FRAME) {
            in_flight = 0;
        } else if (blob_ready && is_master && !in_flight && !(SIOCNT & CNT_START) && now() - last_done >= GAP_AFTER_DONE) {
            int cycle_start = !linked || send_idx == 0;
            if (!cycle_start || (int)(now() - next_cycle) >= 0) {
                if (cycle_start)
                    next_cycle = now() + LINES_PER_FRAME;
                in_flight = 1; started_at = now();
                SIOCNT = MULTI_MODE | BAUD_115200 | CNT_IRQ | CNT_START;
            }
        }
        if (!(REG_IF & IF_SERIAL))
            pc_service(api);
        if (close_pending && !qcount && !tx_on && state != ST_DONE) {
            if (!close_at) close_at = now() | 1;
            else if (now() - close_at > 10 * LINES_PER_FRAME) state = ST_DONE;
        }
        if (blob_ready && !in_flight && !(REG_IF & IF_SERIAL))
            screen(api, state >= ST_CONNECTED && hs_run != 0xFFFF);
    }
    SIOCNT = saved_siocnt & ~(CNT_START | CNT_IRQ);
    RCNT = saved_rcnt;
    REG_IF = IF_SERIAL;
    REG_IE = saved_ie;
    return state | transfers << 8;
}
