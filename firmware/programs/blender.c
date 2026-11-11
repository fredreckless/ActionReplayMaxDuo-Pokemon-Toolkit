/* blender.c - the DUO as the player's partner at the Berry Blender, Ruby, Sapphire and Emerald (8
 * November 2026; docs/BLENDER.md). Grown from tower.c: the same link engine and log, no battle. The
 * DUO can be either player (11 November): player 1, the game leading, or player 0, the leader, which
 * asks for the trainer cards and the berries, sends the time and best RPM, and gathers the answers
 * to "blend another berry?" into its verdict. From pret's pokeemerald berry_blender.c,
 * cable_club.c and link.c, and pokeruby's berry_blender.c (the same protocol):
 *   - the link-up (LINKTYPE_BERRY_BLENDER_SETUP 0x4411, TryBerryBlenderLinkup): link players (the
 *     game's version and link type), our trainer card (the leader's 0xCCCC 2); the link stays open
 *     while the player chooses a berry;
 *   - each blend (CB2_StartBlenderLink): a "ready" barrier, the leader's 0xCCCC 4 and a 40-byte block
 *     each (struct BlenderBerry: item, name, five flavours, smoothness). We wait for the game's and
 *     send the first of our berries that isn't the same as the player's (the same berry twice makes
 *     a black Pokeblock). The berries go in, a "ready" barrier, then the play: every frame each GBA
 *     sends 0x4444 (word 1 the keys held, word 2 a hit: BEST 0x4523, GOOD 0x5432, MISS 0x2345), and
 *     each GBA runs the arrow itself from what arrives (no arrow on the cable): we run it too,
 *     exactly as the game does, and press A as our arrow passes our spot (the player-1 spot of a
 *     two-player blend), the hit scored by our own copy of the arrow, as the game scores its own;
 *   - the end: the game stops sending 0x4444; the leader's block (40 bytes: the time, the best RPM);
 *     each player's answer to "blend another berry?" (0x2FFF with PLAY_AGAIN 0x7779 or, for no,
 *     0x8888); the leader's verdict (0x2FFF with 0x2222: again, or 0x1111: stop); "ready" barriers
 *     round the link save; then the next blend, or the link closed.
 * Every block goes into the log, as tower.c's, and every hit (ours and the player's) as an event. */
#include "link_core.h"

#define LT_BLENDER_SETUP 0x4411
#define SEND_KEYS   0x4444
#define HIT_BEST    0x4523
#define HIT_GOOD    0x5432
#define HIT_MISS    0x2345
#define SEND_PACKET 0x2FFF
#define PLAY_AGAIN  0x7779
#define SAY_NO      0x8888
#define LEADER_GO   0x2222
#define LEADER_STOP 0x1111

/* the arrow (berry_blender.c), two players: we are player 1, arrow 2 */
#define ARROW_START    0xC000     /* sArrowStartPos[sArrowStartPosIds[0]] */
#define MIN_SPEED      0x80
#define HIT_RANGE      (is_master ? 224 : 96)   /* sArrowHitRangeStart[playerIdToArrowId[us]]: arrow 1 or 2 */
#define LT_SETUP_ASK   0x4411     /* (as master: the link type we ask link players for) */
#define NO_BERRIES     0x9999
#define NO_SPACE       0xAAAA
#define MAX_PROGRESS   1000

static u32 udiv(u32 a, u32 b)             /* (small numbers only; the barrier keeps it a loop, not a library call) */
{
    u32 q = 0;
    while (a >= b) { a -= b; q++; __asm__ volatile("" : "+r"(a)); }
    return q;
}

/* ------------------------------------------------------------------ what the PC loads, and the log */
#define BLOB_AT     0x02010030          /* build_v4.py BUFFER */
#define BLOB_MAX    248
static u32 put_at, blob_ready;
#define blob_words  ((u32 *)BLOB_AT)
#define BLOB        ((u8 *)BLOB_AT)
#define BLENDS      BLOB[0]             /* how many blends the DUO stays for (1-9) */
#define OUR_GENDER  BLOB[1]             /* our trainer: 0 boy, 1 girl */
#define SKILL       BLOB[2]             /* 0 expert: always BEST; 1 good; 2 casual */
#define NBERRIES    BLOB[3]             /* our berries, in order of choice (1-4) */
#define OUR_NAME    (BLOB + 4)          /* 8 bytes, game charset */
#define OUR_TID     (BLOB + 12)         /* 4 bytes */
#define LABEL       ((const char *)BLOB + 20)   /* 28: a line for the screen */
#define BERRIES     (BLOB + 48)         /* 4 x 16: struct BlenderBerry (15 bytes), padded */
#define CARD        (BLOB + 112)        /* 100: our trainer card (struct TrainerCard) */

#define LOG         ((u8 *)(BLOB_AT + 0x400))
#define LOG_MAX     0x1F800
#define RX_MAX      0x400
static u32 log_len, log_full, log_seq, log_lost;
static u8 scratch[64];
enum { K_GAME, K_OURS, K_EVENT };
enum { E_SESSION = 1, E_CLOSE, E_READY, E_BERRY, E_START, E_HIT, E_GAME_HIT, E_END, E_ANSWER, E_VERDICT,
       E_TRUNCATED };

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
enum { ST_WAITING, ST_HANDSHAKE, ST_CONNECTED, ST_LINKUP, ST_CHOOSING, ST_BERRIES, ST_COUNTDOWN, ST_BLENDING,
       ST_RESULTS, ST_AGAIN, ST_DONE };
static u32 state, is_master, transfers, bad_checksums, game_lp_type, game_lp_lang, stop_requested;
static u32 role_known, si_low_run, sessions, hs_run, max_gap;
static u8 game_player[60];

static u32 close_pending, close_at, barriers, blends, berry_wanted, game_item, our_item, verdict, answered;
static u8 small[40];                      /* our berry block */

/* the blend: our copy of the game's arrow */
static u32 arrow, timer, pass, in_window, pressed, plan, ended, press, frames;
static s32 speed, progress, shown_progress;
static u32 hits[2][3];                    /* this blend's hits: [player][best, good, miss] */
static u32 max_speed, time_rpm, max_rpm;
static u32 lead_timer, card_asked, barriers_to_go, berries_asked_at, game_resp;

/* ------------------------------------------------------------------ the link layer */
static u32 send_idx, recv_idx, checksum, checksum_ready, nonzero;
static u16 frame[CMD_LEN][2], current[CMD_LEN];
#define QN 4
static u16 qcmd[QN][4];
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
    u32 version = game_player[16];                           /* the game's own version */
    lp[0] = version; lp[1] = game_player[17];
    memcpy(lp + 4, OUR_TID, 4);
    memcpy(lp + 8, OUR_NAME, 8);
    memcpy(lp + 0x14, game_player + 16 + 0x14, 4);           /* link type */
    memcpy(lp + 0x1A, game_player + 16 + 0x1A, 2);           /* language */
    if (version >= 3) {                                      /* Emerald: the progress flags, the gender */
        lp[0x10] = 0x11;
        lp[0x13] = OUR_GENDER;
    } else {
        lp[0x10] = OUR_GENDER;                               /* Ruby/Sapphire keep the gender here */
    }
    lp[0x18] = is_master ? 0 : 1;
}

static void queue4(u16 w0, u16 w1, u16 w2, u16 w3)
{
    if (qcount == QN) return;
    u16 *q = qcmd[(qhead + qcount) % QN];
    q[0] = w0; q[1] = w1; q[2] = w2; q[3] = w3;
    qcount++;
}
#define queue(a, b, c) queue4(a, b, c, 0)

static void send_block(const u8 *src, u32 len)
{
    tx_src = src; tx_len = len; tx_off = 0; tx_header = 0; tx_on = 1;
}

static void lead(void)                    /* as player 0, once a cycle: the leader's requests */
{
    if (tx_on) return;
    if (state == ST_LINKUP && game_player[16] && !card_asked && ++lead_timer > 40) {   /* cable_club.c: the cards */
        queue(0xCCCC, 2, 0); card_asked = 1; lead_timer = 0;
        barriers_to_go = 1;                                  /* (the first blend's barrier comes next) */
    }
    if (berries_asked_at && ++berries_asked_at > 16) {       /* CB2_StartBlenderLink 9: after the barrier */
        queue(0xCCCC, 4, 0); berries_asked_at = 0;
    }
}

static void next_command(void)
{
    for (u32 i = 0; i < CMD_LEN; i++) current[i] = 0;
    if (qcount) {
        u16 *q = qcmd[qhead];
        current[0] = q[0]; current[1] = q[1]; current[2] = q[2]; current[3] = q[3];
        qhead = (qhead + 1) % QN; qcount--;
        return;
    }
    if (is_master) lead();
    if (qcount) { next_command(); return; }
    if (state == ST_BLENDING) {                  /* the play: every frame, our keys and a hit */
        current[0] = SEND_KEYS;
        current[1] = press ? 1 : 0;              /* (A held as we press) */
        current[2] = press;
        press = 0;
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
        if (!CARD[0x38]) CARD[0x38] = game_player[16];       /* (the card's game: the game's own) */
        send_block(CARD, 100);
    }
    else if (n == 4) { berry_wanted = 1; state = ST_BERRIES; }   /* (ours once the game's is here) */
    else send_block(0, n == 3 ? 220 : n == 2 ? 100 : 200);
}

/* ------------------------------------------------------------------ the blend */
static void start_blend(void)
{
    arrow = ARROW_START; speed = MIN_SPEED; timer = 0; progress = shown_progress = 0;
    pass = in_window = pressed = ended = press = frames = 0;
    zero(hits, sizeof hits);
    max_speed = MIN_SPEED; max_rpm = 0; game_resp = 0;
    log_event(E_START, blends + 1);
}

static void hit(u32 who, u32 code)       /* UpdateSpeedFromHit, then the progress bar (two players) */
{
    u32 k;
    if (code == HIT_BEST) { speed += speed < 1500 ? 384 : 128; progress += udiv(speed, 55); k = 0; }
    else if (code == HIT_GOOD) { if (speed < 1500) speed += 256; progress += udiv(speed, 70); k = 1; }
    else if (code == HIT_MISS) { speed -= 256; if (speed < MIN_SPEED) speed = MIN_SPEED; k = 2; }
    else return;
    if (progress >= MAX_PROGRESS && k == 0) progress = MAX_PROGRESS;
    hits[who][k]++;
    if ((u32)speed > max_speed) max_speed = speed;
    log_event(who ? E_HIT : E_GAME_HIT, k | (arrow >> 8) << 8);
}

static u32 our_plan(u32 n)               /* what we aim for on our n-th pass: 0 BEST, 1 GOOD, 2 MISS */
{
    if (SKILL == 1) return (n & 3) == 3;                     /* good: one GOOD in four */
    if (SKILL >= 2) { u32 m = n - 3 * udiv(n, 3); return m; }   /* casual: BEST, GOOD, MISS */
    return 0;                                                /* expert */
}

static void blend_frame(u32 game_hit, u32 our_hit)   /* one frame of CB2_PlayBlender, as the game runs it */
{
    if (ended) return;                                       /* (CB2_EndBlenderGame: no more hits, the clock stopped) */
    frames++;
    arrow = (arrow + speed) & 0xFFFF;                        /* UpdateBlenderCenter */
    u32 pos = (arrow >> 8) + 24, prox = 0;                   /* GetArrowProximity, for our arrow */
    if (pos >= HIT_RANGE && pos < HIT_RANGE + 48)
        prox = pos >= HIT_RANGE + 20 && pos < HIT_RANGE + 28 ? 2 : 1;
    if (!ended) {                                            /* HandlePlayerInput: our press */
        if (prox && !in_window) { in_window = 1; pressed = 0; plan = our_plan(pass); }
        if (in_window && !pressed) {
            u32 code = 0;
            if (plan == 0 && (prox == 2 || (prox == 1 && pos >= HIT_RANGE + 28))) code = prox == 2 ? HIT_BEST : HIT_GOOD;
            if (plan == 1 && prox == 1) code = HIT_GOOD;
            if (plan == 2 && !prox) code = HIT_MISS;         /* (a touch late: just past the spot) */
            if (code) { press = code; pressed = 1; }
        }
        if (!prox && in_window) { in_window = 0; pass++; }
    }
    if (++timer > 5) { if (speed > MIN_SPEED) speed--; timer = 0; }
    if (is_master) { hit(1, our_hit); hit(0, game_hit); }    /* UpdateOpponentScores: player 0 first */
    else { hit(0, game_hit); hit(1, our_hit); }
    u32 rpm = (u32)speed * 360000 >> 16;                     /* UpdateRPM: ArrowSpeedToRPM, in hundredths */
    if (rpm > max_rpm) max_rpm = rpm;
    if (shown_progress < progress) shown_progress += 2;      /* TryUpdateProgressBar */
    if (!ended && shown_progress >= MAX_PROGRESS) { ended = 1; log_event(E_END, frames); }
}

static void berry_block(const u8 *b)      /* the game's berry: ours, not the same */
{
    game_item = b[0] | b[1] << 8;
    u32 n = NBERRIES ? NBERRIES : 1, k = 0;
    while (k + 1 < n && (BERRIES[16 * k] | BERRIES[16 * k + 1] << 8) == game_item) k++;
    zero(small, 40);
    memcpy(small, BERRIES + 16 * k, 15);
    our_item = small[0] | small[1] << 8;
    send_block(small, 40);
    berry_wanted = 0;
    state = ST_COUNTDOWN;
    log_event(E_BERRY, game_item | our_item << 8);
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
        if (state < ST_LINKUP) state = ST_LINKUP;
        return;
    }
    if (size == 40 && berry_wanted && kept >= 15) { berry_block(b); return; }
    if (size == 40 && state == ST_RESULTS && kept >= 6 && !is_master) {    /* the leader's time and best RPM */
        time_rpm = (b[0] | b[1] << 8) | (u32)(b[4] | b[5] << 8) << 16;
        u32 again = blends + 1 < (BLENDS ? BLENDS : 1);
        answered = again ? PLAY_AGAIN : SAY_NO;
        queue(SEND_PACKET, answered, 0);                     /* "blend another berry?" */
        log_event(E_ANSWER, answered);
        state = ST_AGAIN;
    }
}

static void process_command(void)
{
    u32 game = is_master ? 1 : 0, ours = 1 - game;
    u16 c = frame[0][game];
    if (c == 0x2222 || frame[0][ours] == 0x2222)
        player_pending = 1;
    if (state == ST_COUNTDOWN && c == SEND_KEYS) {
        state = ST_BLENDING; start_blend();
        /* as master, the game's first 0x4444 reaches us a frame later in its play than as a child
         * (who starts the transfers decides): its first frame has gone by already */
        if (is_master) arrow = (arrow + speed) & 0xFFFF;
    }
    if (state == ST_BLENDING) {
        if (c == SEND_KEYS) { blend_frame(frame[2][game], frame[0][ours] == SEND_KEYS ? frame[2][ours] : 0); return; }
        state = ST_RESULTS;                                  /* the game's play is over */
        if (is_master) {                                     /* the leader's block: the time and best RPM */
            zero(small, 40);
            small[0] = frames; small[1] = frames >> 8; small[2] = frames >> 16;
            small[4] = max_rpm; small[5] = max_rpm >> 8;
            time_rpm = (frames & 0xFFFF) | (max_rpm & 0xFFFF) << 16;
            send_block(small, 40);
            answered = blends + 1 < (BLENDS ? BLENDS : 1) ? PLAY_AGAIN : SAY_NO;
            log_event(E_ANSWER, answered);
            state = ST_AGAIN;
        }
    }
    if (frame[0][ours] == 0xCCCC && is_master)               /* our own request: our block too */
        answer_request(frame[1][ours]);
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
    case SEND_PACKET:                                        /* the leader's verdict (its own answer: ignored) */
        if (is_master && state == ST_AGAIN && !game_resp) {  /* as leader: the game's answer, then our verdict */
            u16 r = frame[1][game];
            if (r != PLAY_AGAIN && r != SAY_NO && r != NO_BERRIES && r != NO_SPACE) break;
            game_resp = r;
            u32 go = r == PLAY_AGAIN && answered == PLAY_AGAIN;
            if (go) queue(SEND_PACKET, LEADER_GO, 0);
            else if (answered != PLAY_AGAIN) queue4(SEND_PACKET, LEADER_STOP, answered, 0);
            else queue4(SEND_PACKET, LEADER_STOP, r, 1);
            verdict = go ? 2 : 1;
            blends++;
            log_event(E_VERDICT, verdict | game_resp << 8);
            state = go ? ST_CHOOSING : ST_AGAIN;
            if (go) barriers_to_go = 5;                      /* (four round the link save, then the next blend's) */
            break;
        }
        if (!is_master && (frame[1][game] == LEADER_GO || frame[1][game] == LEADER_STOP)) {
            verdict = frame[1][game] == LEADER_GO ? 2 : 1;
            blends++;
            log_event(E_VERDICT, verdict | frame[2][game] << 8);
            state = verdict == 2 ? ST_CHOOSING : ST_AGAIN;
        }
        break;
    case 0x2FFE:
        queue(0x2FFE, 0, 0);
        barriers++;
        log_event(E_READY, barriers);
        if (state == ST_LINKUP) state = ST_CHOOSING;
        if (is_master && barriers_to_go && --barriers_to_go == 0) berries_asked_at = 1;
        break;
    case 0x5FFF:
        queue(0x5FFF, 0, 0);
        log_event(E_CLOSE, state);
        close_pending = 1;
        break;
    }
}

static void new_session(void)
{
    rx_on = tx_on = player_pending = 0;
    qcount = 0;
    lead_timer = card_asked = barriers_to_go = berries_asked_at = 0;
}

/* ------------------------------------------------------------------ the DUO's screen */
static const char *const SAY[] = {
    "Blender: waiting for game", "Blender: handshaking", "Blender: linked", "Blender: linking up",
    "The player chooses a berry", "Berries in", "Countdown", "Blending",
    "The results", "Another berry?", "Done: the link is closed",
};
static u32 shown = 0xFF, label_shown;

static void screen(api_t *api, int linked)
{
    if (shown == state || (linked && state != ST_DONE)) return;
    if (!label_shown) {
        label_shown = 1;
        api->log("Playing: Berry Blender partner");
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
    case 3: v = blends | (game_item & 0xFF) << 8 | (our_item & 0xFF) << 16 | verdict << 24; break;
    case 4: v = 4 * idx + 3 < log_len ? ((u32 *)LOG)[idx] : 0; break;
    case 5: v = log_len | log_full << 31; break;
    case 6: v = game_player[16] | game_player[17] << 8 | game_player[18] << 16 | (u32)game_player[19] << 24; break;
    case 7: {
        u32 at = 16 + 4 + 4 * (idx < 3 ? idx : 0);
        v = game_player[at] | game_player[at + 1] << 8 | game_player[at + 2] << 16 | (u32)game_player[at + 3] << 24;
        break;
    }
    case 8: v = max_gap; break;
    case 9: v = game_player[16 + 0x10]; break;
    case 10: v = hits[1][0] | hits[1][1] << 8 | hits[1][2] << 16 | (log_lost & 0xFF) << 24; break;   /* our hits */
    case 11: v = hits[0][0] | hits[0][1] << 8 | hits[0][2] << 16; break;      /* the player's */
    case 12: v = (speed & 0xFFFF) | (u32)(progress & 0xFFFF) << 16; break;  /* the blend now */
    case 13: v = time_rpm; break;                            /* the leader's: time (low 16 bits), best RPM */
    case 14: v = frames | (max_speed & 0xFFFF) << 16; break;
    case 20: put_at = 0; blob_ready = 0; v = BLOB_MAX; break;
    case 21: v = api->crc32(blob_words, put_at * 4);
             blob_ready = put_at * 4 >= BLOB_MAX && NBERRIES >= 1 && NBERRIES <= 4;
             if (blob_ready) log_len = log_full = log_seq = 0;
             break;
    default: v = 0xFFFFFFFF; break;
    }
    api->reply(0x2A, v);
    return 0;
}

#define LINK_TYPE_ASK LT_SETUP_ASK
#include "link_tail.h"
