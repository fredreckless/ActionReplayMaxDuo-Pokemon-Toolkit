/* contest.c - the DUO as a contestant in Emerald's link Contest, E mode (8 November 2026;
 * docs/CONTEST.md). Grown from blender.c: the same link engine and log. The game always works out
 * the contest (the leader, whose figures every other GBA copies). The DUO can be player 1, or (11
 * November) player 0: then it asks for the trainer cards, sends the random seed and the two other
 * contestants (player 0's jobs), and a leader ID below the game's, so that the game still leads. From pret's pokeemerald contest_link.c, contest_link_util.c, contest.c, contest_util.c and
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
#include "link_core.h"

#define LT_CONTEST_EMODE 0x6602
#define MON_SIZE    64            /* struct ContestPokemon */
#define BLK_MAX     256           /* BLOCK_BUFFER_SIZE */

/* ------------------------------------------------------------------ what the PC loads, and the log */
#define BLOB_AT     0x02010030          /* build_v4.py BUFFER */
#define BLOB_MAX    376
static u32 put_at, blob_ready;
#define blob_words  ((u32 *)BLOB_AT)
#define BLOB        ((u8 *)BLOB_AT)
#define NMOVES      BLOB[0]             /* the length of our plan (1-8): the move slots, round by round */
#define OUR_GENDER  BLOB[1]             /* our trainer: 0 boy, 1 girl */
#define OUR_NAME    (BLOB + 4)          /* 8 bytes, game charset */
#define OUR_TID     (BLOB + 12)         /* 4 bytes */
#define ORDER       (BLOB + 232)        /* 8: the plan, a move slot for each round (then round again) */
#define LABEL       ((const char *)BLOB + 20)   /* 28: a line for the screen */
#define MON         (BLOB + 48)         /* 64: our struct ContestPokemon, as the game sends it */
#define CARD        (BLOB + 112)        /* 100: our trainer card (struct TrainerCard) */
#define RIVALS      (BLOB + 248)        /* 128: as player 0, the two other contestants (struct ContestPokemon x 2) */

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
static u32 lead_timer, card_asked, setup_barriers, lead_send, lead_at;
static u8 seed[4];
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
    lp[0x18] = is_master ? 0 : 1;
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

static void lead(void)                    /* as player 0, once a cycle: player 0's jobs */
{
    if (tx_on) return;
    if (state == ST_LINKUP && game_player[16] && !card_asked && ++lead_timer > 40) {   /* cable_club.c: the cards */
        queue(0xCCCC, 2, 0); card_asked = 1;
    }
    if (lead_send && ++lead_at > 12) {                       /* a while after the barrier: the block itself */
        if (lead_send == 1) {                                /* Task_LinkContest_CommunicateRngEm: the seed */
            u32 r = transfers * 0x9E3779B1u ^ lines_total;
            seed[0] = r; seed[1] = r >> 8; seed[2] = r >> 16; seed[3] = r >> 24;
            send_block(seed, 4);
        } else {                                             /* ...CommunicateAIMonsEm: the other two contestants */
            send_block(RIVALS, 2 * MON_SIZE);
        }
        log_event(E_MON, lead_send == 1 ? 4 : 2 * MON_SIZE);
        lead_send = 0;
    }
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
    if (is_master) { lead(); if (qcount) { next_command(); return; } }
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
    if (state == ST_SETUP && !is_master && ((size == 4 && !seed_seen) || size == 2 * MON_SIZE)) {   /* player 0's own */
        seed_seen = 1; skipped++;
        log_event(E_SKIP, size);
        return;
    }
    if (state == ST_SETUP && size == 2 && setup_blocks == 1 && is_master) {   /* leader IDs: ours below the game's */
        setup_blocks++;
        ours[0] = ours[1] = 0;
        send_block(ours, 2);
        log_event(E_MIRROR, 0);
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
    if (frame[0][ours_id] == 0xCCCC && is_master)            /* our own request: our block too */
        answer_request(frame[1][ours_id]);
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
        if (is_master && state == ST_SETUP) {                /* the set-up's steps after the contestants */
            setup_barriers++;
            if (setup_barriers == 1 || setup_barriers == 4) { lead_send = setup_barriers == 1 ? 1 : 2; lead_at = 0; }
        }
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
    lead_timer = card_asked = setup_barriers = lead_send = 0;
    rx_on = tx_on = player_pending = 0;
    qcount = 0;
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
             blob_ready = put_at * 4 >= BLOB_MAX && NMOVES >= 1 && NMOVES <= 8;
             if (blob_ready) log_len = log_full = log_seq = 0;
             break;
    default: v = 0xFFFFFFFF; break;
    }
    api->reply(0x2A, v);
    return 0;
}

#define LINK_TYPE_ASK LT_CONTEST_EMODE
#include "link_tail.h"
