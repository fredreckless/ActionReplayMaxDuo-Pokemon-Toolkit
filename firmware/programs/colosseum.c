/* colosseum.c - the DUO's GBA sits in a Pokemon Ruby/Sapphire Cable Club Colosseum as the other
 * player, battles the game once with the PC's team (.pk3 files), and records everything the game
 * sends for the PC: the first step of the battle partner (docs/BATTLE.md, "The probe"). It plays
 * as simply as it can - the first move that has PP, the next Pokemon when one faints - because its
 * job is to listen. Nothing is written to either cartridge; the game saves nothing for a link battle
 * but its link record, as with any partner.
 *
 * The link engine (transfers, roles, master pacing, the PC) and the room walk are mix.c's. On top:
 *   - the Cable Club (0x2233, cable_club.c sub_808347C): link players, each player's trainer card
 *     (0xCCCC 2), and the same link carries on into the Colosseum (the fade-in's 0x2FFE answered);
 *     room keys (0xCAFE) a frame, walking to a spot - player 0: (3,5), player 1: (10,5), or the
 *     other one if the player is standing on ours - then key 22 ("seated");
 *   - both seated: the game closes that link (sub_808382C: 0x2211, 0x5FFF) and the battle opens a
 *     new one (0x2211, HandleLinkBattleSetup): link players, then each side sends a header
 *     (struct LinkPartnerHeader: its version signature, which Pokemon are fit, its Enigma Berry) and
 *     its party, two Pokemon at a time, each block once the game's block of the same turn is here
 *     (CB2_HandleStartBattle waits for both of each before going on);
 *   - who runs the battle (battle_main.c case 1): equal signatures make player 0 the master, a
 *     higher one wins. As player 1 we send the game's own; as player 0 we send 0x0001, lower than
 *     any game's, so the game runs the battle either way and we only ever play a follower;
 *   - the battle: every controller command the game's engine emits comes to every player as a
 *     block (struct LinkBattleCommunicationHeader: state 0, the battler, ... the size, then the
 *     command). Our battlers are the odd ones. For each command we answer "done" (state 2, our
 *     multiplayer ID: LinkOpponentBufferExecCompleted); for ours, first the answer the game's own
 *     controller would send (state 1): an action (fight), a move, a Pokemon after a faint. Every
 *     block we send is 16 bytes. GETMONDATA needs nothing from us: the game's own copy of our party
 *     answers it (LinkOpponentHandleGetAttributes);
 *   - the end (CONTROLLER_ENDLINKBATTLE): the game closes the link (0x5FFF), goes back to the
 *     Colosseum and opens it again as 0x2233 (sub_8083664): we walk back to the door and leave
 *     (23), or follow the player out;
 *   - a double battle (0x2244) is the same room and the same link; our battlers are 1 and 3.
 * Every block the game sends (and ours, and the link's events) goes into a log in the firmware's
 * save-transfer buffer, which the PC reads during and after the battle. */
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

#define LT_SINGLE 0x2233   /* the attendant's link, kept open into the Colosseum; the room again after */
#define LT_DOUBLE 0x2244
#define LT_BATTLE 0x2211   /* the battle's own link */

/* controller commands (pokeruby battle_controllers.h) and the replies we send */
#define C_SWITCHINANIM    5
#define C_FAINTANIMATION 10
#define C_CHOOSEACTION   18
#define C_CHOOSEMOVE     20
#define C_CHOOSEPOKEMON  22
#define C_ENDLINKBATTLE  55
#define R_TWORETURNVALUES 33
#define R_CHOSENMON       34

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

/* ------------------------------------------------------------------ what the PC loads, and the log
 * Both live in the firmware's save-transfer buffer (0x20000 bytes), which nothing uses while a
 * program runs. */
#define BLOB_AT     0x02010030          /* build_v4.py BUFFER */
#define BLOB_MAX    748
static u32 put_at, blob_ready;
#define blob_words  ((u32 *)BLOB_AT)
#define BLOB        ((u8 *)BLOB_AT)
#define TEAM_COUNT  BLOB[0]             /* 1 to 6 */
#define OUR_GENDER  BLOB[1]             /* our trainer: 0 boy, 1 girl */
#define OUR_NAME    (BLOB + 4)          /* 8 bytes, game charset */
#define OUR_TID     (BLOB + 12)         /* 4 bytes */
#define LABEL       ((const char *)BLOB + 20)   /* 28: a line for the screen */
#define PARTY       (BLOB + 48)         /* 6 x 100: the game's party form */
#define CARD        (BLOB + 648)        /* 100: our trainer card (struct TrainerCard) */

#define LOG         ((u8 *)(BLOB_AT + 0x400))
#define LOG_MAX     0x1F800             /* to the end of the buffer */
#define RX_MAX      0x400               /* (a block longer than this is kept cut short) */
static u32 log_len, log_full, log_seq, log_lost;
static u8 scratch[64];                    /* where a block goes once the log is full */
enum { K_GAME, K_OURS, K_EVENT };
enum { E_SESSION = 1, E_CLOSE, E_READY, E_SEATED, E_CHOICE, E_END, E_TRUNCATED, E_DROPPED };

static u8 *log_room(u32 len)              /* where an entry's bytes go (after its 4-byte head), or 0 */
{
    if (log_full || log_len + 8 + len > LOG_MAX) { log_full = 1; return 0; }
    return LOG + log_len + 4;
}

static void log_commit(u32 len, u32 kind)  /* the entry whose bytes are in place */
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
    if (rx_on && rx_dst != scratch) { log_lost++; return; }   /* (a block is arriving into the log) */
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
enum { ST_WAITING, ST_HANDSHAKE, ST_CONNECTED, ST_ROOM, ST_WALKING, ST_SEATED, ST_STARTING, ST_TEAMS,
       ST_BATTLE, ST_OVER, ST_BACK, ST_WALKING_OUT, ST_EXITING, ST_DONE };
static u32 state, is_master, transfers, bad_checksums, game_lp_type, game_lp_lang, stop_requested;
static u32 role_known, si_low_run, sessions, hs_run, max_gap;
static u8 game_player[60];

/* the sitting's own story */
static u32 room_keys_seen, walk_frame, game_ready, battled, doubles;
static u32 game_exiting, sent_exit, close_pending, close_at, asked_at, round_timer, start_timer;
static u32 barriers;
static u32 start_in, start_out;           /* the battle's opening blocks: the game's, ours (header, 3 x party) */
static u32 commands, ours_answered, outcome, choices;
static u32 fainted, on_field[2], last_pick;

/* ------------------------------------------------------------------ the link layer */
static u32 send_idx, recv_idx, checksum, checksum_ready, nonzero;
static u16 frame[CMD_LEN][2], current[CMD_LEN];
#define QN 4
static u16 qcmd[QN][3];                   /* small commands waiting to go: up to 3 words */
static u32 qhead, qcount;
static u16 loaded;

static u32 rx_size, rx_have, rx_keep;   /* the game's block, straight into the log (rx_on, rx_dst) */
static u32 player_pending;

static const u8 *tx_src;                  /* our outgoing block */
static u32 tx_len, tx_off, tx_on, tx_header;
static u8 our_player[60];
static u8 our_header[32];
#define TQ 16
static u8 tq[TQ][16];                     /* battle blocks waiting to go: 16 bytes each */
static u32 tq_head, tq_count, tq_dropped;

static void build_our_player(void)
{
    static const char magic[] = "GameFreak inc.";
    zero(our_player, 60);
    memcpy(our_player, magic, 14);
    memcpy(our_player + 44, magic, 14);
    u8 *lp = our_player + 16;
    lp[0] = game_player[16]; lp[1] = game_player[17];       /* the game's version; lp_field_2 stays 0 */
    memcpy(lp + 4, OUR_TID, 4);
    memcpy(lp + 8, OUR_NAME, 8);
    memcpy(lp + 0x14, game_player + 16 + 0x14, 4);           /* link type */
    memcpy(lp + 0x1A, game_player + 16 + 0x1A, 2);           /* language */
    lp[0x10] = OUR_GENDER;                                   /* Ruby/Sapphire keep the gender here */
    lp[0x18] = is_master ? 0 : 1;                            /* id: our spot (VAR_0x8005) */
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

static void battle_block(const u8 *cmd, u32 state_, const u8 *data, u32 n)
{
    /* a block for the game's linkRecv: struct LinkBattleCommunicationHeader, then the data; the
     * size rounded as PrepareBufferDataTransferLink rounds it (4 or 5 bytes: 8) */
    if (tq_count == TQ) { tq_dropped++; log_event(E_DROPPED, cmd[1]); return; }
    u8 *b = tq[(tq_head + tq_count) % TQ];
    zero(b, 16);
    b[0] = state_; b[1] = cmd[1]; b[2] = cmd[2]; b[3] = cmd[3];
    b[4] = 8; b[6] = cmd[6]; b[7] = cmd[7];
    memcpy(b + 8, data, n);
    tq_count++;
    log_bytes(b, 16, K_OURS);
}

#define RW_DIST rw_dist_space
static u8 rw_dist_space[14 * 9];
#include "room_walk.h"

/* The Colosseum (layout SingleBattleColosseum, 14 x 9) as room_walk.h sees it: open floor from
 * (1,3) to (12,7) but the attendant at (9,3); the spots at (3,5) and (10,5); the door (6,8)-(7,8). */
static const u16 colo_room[9] = { 0x0, 0x0, 0x0, 0x1DFE, 0x1FFE, 0x1FFE, 0x1FFE, 0x1FFE, 0xC0 };   /* bit x: open floor */
static const u8 colo_spots[4] = { 3, 5, 10, 5 };
static u32 sat, sat_at;

static u16 room_key(void)                 /* our key for this frame in the Colosseum */
{
    /* after the room has settled, a shortest way to our spot around the player (a step at a time,
     * each once the last has finished; waiting while the way is blocked); on it, "seated" (22) */
    u32 me = is_master ? 0 : 1, other = 1 - me;
    u32 f = walk_frame++;
    if (f == 0) { rw_start(colo_room, 0, 14, 9, 8, 6, 7, 6, 7, colo_spots, 2); sat = 0; }
    if (sat) {
        if (f == sat_at + 10) { state = ST_SEATED; log_event(E_SEATED, rw[me].x); return 22; }
        return 17;
    }
    if (f < 40 || !rw_free(me)) return 17;
    u32 spot_x = is_master ? 3 : 10;
    if (rw[other].x == spot_x && rw[other].y == 5) spot_x = 13 - spot_x;   /* the player took ours */
    if (rw_at(me, spot_x, 5)) { sat = 1; sat_at = f; return 17; }
    u16 k;
    if (!rw_take(spot_x, 5, &k)) return 17;
    rw_blocked_now = !k;
    if (!k) return 17;
    rw_await = 1;
    return k;
}

static u16 exit_key(void)                 /* back in the room after the battle: leave it */
{
    /* as the Trade Center after a trade (overworld.c sub_805465C: everyone standing, facing down):
     * a shortest way to a door tile around the player (waiting while every way is blocked), DOWN
     * there facing down (the exit prompt), then 23. If the player leaves first, we follow at once. */
    u32 me = is_master ? 0 : 1;
    u32 f = walk_frame++;
    if (f == 0) { rw_settle(); asked_at = 0; }
    if (sent_exit) return 17;
    if (game_exiting) { sent_exit = 1; state = ST_EXITING; return 23; }
    if (f < 60) return 17;
    if (asked_at) {
        if (f >= asked_at + 30) { sent_exit = 1; state = ST_EXITING; return 23; }
        return 17;
    }
    if (!rw_free(me)) return 17;
    state = ST_WALKING_OUT;
    if (rw_on_door(me)) {
        rw_blocked_now = 0; rw_await = 1;
        if (rw[me].facing != RW_KEY_DOWN) return RW_KEY_DOWN;   /* turn to the way out (a wall: no step) */
        asked_at = f;
        return RW_KEY_DOWN;                                     /* "Will the link be terminated?" */
    }
    u16 k;
    if (!rw_take(-1, -1, &k)) return 17;
    rw_blocked_now = !k;
    if (!k) return 17;
    rw_await = 1;
    return k;
}

static u32 in_room(void) { return game_lp_type == LT_SINGLE || game_lp_type == LT_DOUBLE; }

static void next_command(void)
{
    for (u32 i = 0; i < CMD_LEN; i++) current[i] = 0;
    if (qcount) {
        u16 *q = qcmd[qhead];
        current[0] = q[0]; current[1] = q[1]; current[2] = q[2];
        qhead = (qhead + 1) % QN; qcount--;
        return;
    }
    if (!tx_on && tq_count && game_lp_type == LT_BATTLE) {      /* the next battle block */
        send_block(tq[tq_head], 16);
        tq_head = (tq_head + 1) % TQ; tq_count--;
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
        return;
    }
    if (in_room() && room_keys_seen) {                           /* the room: a key every frame */
        current[0] = 0xCAFE;
        if (battled) current[1] = exit_key();
        else {
            current[1] = room_key();
            if (state < ST_WALKING) state = ST_WALKING;
        }
    }
}

static void answer_request(u32 n)         /* 0xCCCC n: our block of that size */
{
    if (n == 2) send_block(CARD, 100);
    else send_block(0, n == 4 ? 40 : n == 3 ? 220 : n == 2 ? 100 : 200);     /* (zeros: a request we don't expect) */
}

/* ------------------------------------------------------------------ the battle */
static void opening_block(void)          /* our next opening block, once the game's of that turn is here */
{
    if (tx_on || start_out >= 4 || start_in <= start_out || game_lp_type != LT_BATTLE) return;
    if (start_out == 0) send_block(our_header, sizeof our_header - 1);   /* (31 bytes, as Ruby's) */
    else send_block(PARTY + 200 * (start_out - 1), 200);
    if (start_out == 0) log_bytes(our_header, 31, K_OURS);
    start_out++;
    if (start_out == 4) state = ST_BATTLE;
}

static void game_header(const u8 *b)     /* the game's LinkPartnerHeader: our answer to it */
{
    zero(our_header, sizeof our_header);
    if (is_master) { our_header[0] = 1; our_header[1] = 0; }     /* 0x0001: the game runs the battle */
    else { our_header[0] = b[0]; our_header[1] = b[1]; }         /* its own: player 0 (the game) runs it */
    u32 fit = 0;
    for (u32 i = 0; i < TEAM_COUNT && i < 6; i++) fit |= 1u << (2 * i);   /* every Pokemon fit to battle */
    our_header[2] = fit; our_header[3] = fit >> 8;
}

static u32 pick_next(void)               /* a Pokemon to send in after a faint: the next one fit */
{
    for (u32 k = 1; k <= 6; k++) {
        u32 i = last_pick + k;
        if (i >= 6) i -= 6;
        if (i >= TEAM_COUNT || fainted >> i & 1 || i == on_field[0] || i == on_field[1]) continue;
        return i;
    }
    return 6;                                                  /* (PARTY_SIZE: none) */
}

static void battle_command(const u8 *b, u32 len)   /* one of the game's battle blocks */
{
    if (len < 9) return;
    if (b[0] != 0) return;                          /* (its own answers and "done"s: logged only) */
    commands++;
    u32 battler = b[1], cmd = b[8], ours = battler & 1, side = battler >> 1;
    const u8 *d = b + 8;
    u8 r[5] = { 0, 0, 0, 0, 0 };
    if (ours) {
        switch (cmd) {
        case C_CHOOSEACTION:                        /* fight (B_ACTION_USE_MOVE) */
            r[0] = R_TWORETURNVALUES;
            battle_block(b, 1, r, 4);
            ours_answered++;
            break;
        case C_CHOOSEMOVE: {                        /* the first move with PP; the foe opposite */
            u32 slot = 0;
            for (u32 i = 0; i < 4; i++)
                if (len >= 8 + 16 && (d[4 + 2 * i] | d[5 + 2 * i]) && d[12 + i]) { slot = i; break; }
            r[0] = R_TWORETURNVALUES; r[1] = 10; r[2] = slot; r[3] = battler ^ 1;
            battle_block(b, 1, r, 4);
            log_event(E_CHOICE, slot);
            ours_answered++; choices++;
            break;
        }
        case C_CHOOSEPOKEMON: {
            u32 i = pick_next();
            r[0] = R_CHOSENMON; r[1] = i;
            battle_block(b, 1, r, 5);
            log_event(E_CHOICE, 0x100 | i);
            if (i < 6) { last_pick = i; }
            ours_answered++; choices++;
            break;
        }
        case C_SWITCHINANIM:
            if (len >= 10) on_field[side] = d[1];
            break;
        case C_FAINTANIMATION:
            fainted |= 1u << on_field[side];
            break;
        }
    }
    if (cmd == C_ENDLINKBATTLE && len >= 10 && !(state == ST_OVER)) {
        outcome = d[1];
        state = ST_OVER;
        log_event(E_END, outcome);
    }
    u8 done[4] = { is_master ? 0 : 1, 0, 0, 0 };     /* B_COMM_CONTROLLER_IS_DONE, our multiplayer ID */
    battle_block(b, 2, done, 4);
}

static void game_block(u32 size)          /* a whole block from the game has arrived */
{
    u32 kept = rx_keep;
    if (rx_dst != scratch) log_commit(kept, K_GAME);
    if (kept < size) log_event(E_TRUNCATED, size);
    const u8 *b = rx_dst;
    if (size == 60 && player_pending) {
        memcpy(game_player, b, 60);
        game_lp_type = game_player[16 + 0x14] | game_player[16 + 0x15] << 8;
        game_lp_lang = game_player[16 + 0x1A];
        build_our_player();
        send_block(our_player, 60);
        player_pending = 0;
        log_event(E_SESSION, game_lp_type);
        if (in_room() && !battled && state < ST_ROOM) {
            state = ST_ROOM;
            doubles = game_lp_type == LT_DOUBLE;
            on_field[1] = doubles ? 1 : 6;                     /* (battler 3's Pokemon, in a double) */
        }
        else if (game_lp_type == LT_BATTLE) { state = ST_STARTING; start_in = start_out = 0; }
        else if (in_room() && battled) {
            state = ST_BACK; room_keys_seen = walk_frame = game_exiting = sent_exit = 0;
        }
        return;
    }
    if (game_lp_type != LT_BATTLE) return;
    if (start_in < 4) {                                    /* the opening: header, 3 x party */
        if (start_in == 0) { game_header(b); state = ST_TEAMS; }
        start_in++;
        return;
    }
    battle_command(b, kept);
}

static void process_command(void)
{
    u32 game = is_master ? 1 : 0;
    u16 c = frame[0][game];
    if (in_room() && room_keys_seen)
        rw_apply(frame[0][0], frame[1][0], frame[0][1], frame[1][1], is_master ? 0 : 1);   /* where everyone is */
    if (c == 0x2222 || frame[0][is_master ? 0 : 1] == 0x2222)
        player_pending = 1;
    if (frame[0][is_master ? 0 : 1] == 0xCCCC)                  /* our own request, as master */
        answer_request(frame[1][is_master ? 0 : 1]);
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
            if (rx_have < rx_keep) rx_dst[rx_have] = frame[j][game];
            rx_have++;
            if (rx_have < rx_size) { if (rx_have < rx_keep) rx_dst[rx_have] = frame[j][game] >> 8; rx_have++; }
        }
        if (rx_have >= rx_size) { rx_on = 0; game_block(rx_size); }
        break;
    case 0xCCCC:
        answer_request(frame[1][game]);
        break;
    case 0x2FFE:
        /* "ready" (link.c sub_80084A4): the fade-in after a warp into a Cable Club room waits for
         * every player's (lab session 31) */
        queue(0x2FFE, 0, 0);
        barriers++;
        log_event(E_READY, barriers);
        break;
    case 0xCAFE:
        room_keys_seen = 1;
        if (in_room() && !battled) {
            if (frame[1][game] == 22) game_ready = 1;          /* the player has sat down */
            if (frame[1][game] == 29) game_ready = 0;          /* ... and stood up again (B) */
        }
        if (in_room() && battled && frame[1][game] == 23) game_exiting = 1;
        break;
    case 0x5FFF:
        queue(0x5FFF, 0, 0);
        log_event(E_CLOSE, state);
        if (state == ST_BACK || state == ST_WALKING_OUT || state == ST_EXITING) close_pending = 1;
        else if (state == ST_OVER) battled = 1;               /* the room comes next */
        break;
    }
}

static void each_cycle(void)              /* once a command cycle (a frame): the sitting's decisions */
{
    opening_block();
    if (!is_master || !in_room() || battled || tx_on || qcount)
        return;
    /* as master in the Cable Club, we ask for the trainer cards (cable_club.c sub_8083288) */
    if (state == ST_ROOM && !room_keys_seen && !round_timer) {
        if (++start_timer > 40) { queue(0xCCCC, 2, 0); round_timer = 1; start_timer = 0; }
    }
}

static void new_session(void)             /* the link is up again: forget the last one's blocks */
{
    rx_on = tx_on = player_pending = 0;
    qcount = 0;
    start_timer = round_timer = 0;
    room_keys_seen = walk_frame = 0;
}

static u32 master_session_type(void)      /* as master, which link this is */
{
    return state == ST_SEATED ? LT_BATTLE : doubles ? LT_DOUBLE : LT_SINGLE;
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
            if (is_master) queue(0x2222, master_session_type(), 0);
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
        if (checksum_ready && (w[0] != checksum || w[1] != checksum) && !hs_run)   /* (not a new link starting) */
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
        if (send_idx == 0) { each_cycle(); next_command(); }
        loaded = current[send_idx++];
    }
    if (recv_idx == CMD_LEN)
        send_idx = recv_idx = 0;
    SIOMLT_SEND = loaded;
}

/* ------------------------------------------------------------------ the DUO's screen */
/* A log line costs the GBA over a frame, and a link session can't spare one: each line waits for a
 * moment with no link session - before the first, between sessions, or once done. */
static const char *const SAY[] = {
    "Colosseum: waiting for game", "Colosseum: handshaking", "Colosseum: linked", "Cable Club: link players",
    "Walking to our spot", "On our spot", "Battle: opening the link", "Battle: swapping teams",
    "Battling (listening)", "Battle over", "Back in the room", "Walking out to the door", "Leaving the room",
    "Done: the link is closed",
};
static u32 shown = 0xFF, label_shown;

static void screen(api_t *api, int linked)
{
    if (shown == state || (linked && state != ST_DONE)) return;
    if (!label_shown) {
        label_shown = 1;
        api->log("Playing: Colosseum");
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
    case 3: v = (commands & 0xFFFF) | (ours_answered & 0xFF) << 16 | outcome << 24; break;
    case 4: v = 4 * idx + 3 < log_len ? ((u32 *)LOG)[idx] : 0; break;   /* the log, a word at a time */
    case 5: v = log_len | log_full << 31; break;
    case 6: v = game_player[16] | game_player[17] << 8 | game_player[18] << 16 | (u32)game_player[19] << 24; break;
    case 7: {                                                    /* the game's link player: ID, name */
        u32 at = 16 + 4 + 4 * (idx < 3 ? idx : 0);
        v = game_player[at] | game_player[at + 1] << 8 | game_player[at + 2] << 16 | (u32)game_player[at + 3] << 24;
        break;
    }
    case 8: v = max_gap; break;
    case 9: v = game_player[16 + 0x10]; break;                  /* the game's player's gender */
    case 10: v = rw_blocked_now; break;                        /* the way to the spot or door is blocked */
    case 11: v = fainted | choices << 8 | (tq_dropped & 0xFF) << 16 | (log_lost & 0xFF) << 24; break;
    case 20: put_at = 0; blob_ready = 0; v = BLOB_MAX; break;
    case 21: v = api->crc32(blob_words, put_at * 4);
             blob_ready = put_at * 4 >= BLOB_MAX && TEAM_COUNT >= 1 && TEAM_COUNT <= 6;
             if (blob_ready) { log_len = log_full = log_seq = 0; on_field[0] = 0; on_field[1] = 6; }
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
            if (blob_ready) on_transfer();                       /* (only once the PC has loaded us) */
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
        if (rw_need && send_idx == 0 && recv_idx == 0 && !in_flight)
            rw_plan_run(is_master ? 0 : 1);       /* (between two frames' cycles; it gives way to transfers) */
        /* the end: done once our own 0x5FFF has gone out and the game has had time to close */
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
