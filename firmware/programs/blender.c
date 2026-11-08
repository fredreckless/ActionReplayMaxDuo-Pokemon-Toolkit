/* blender.c - the DUO as the player's partner at the Berry Blender, Ruby, Sapphire and Emerald (8
 * November 2026; docs/BLENDER.md). Grown from tower.c: the same link engine and log, no battle. The
 * DUO must be player 1 (the game, player 0, is the leader). From pret's pokeemerald berry_blender.c,
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
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef int s32;

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
#define HIT_RANGE      96         /* sArrowHitRangeStart[2] */
#define MAX_PROGRESS   1000

static void *memcpy(void *d, const void *s, unsigned n) { u8 *p = d; const u8 *q = s; while (n--) *p++ = *q++; return d; }
static void zero(void *d, unsigned n) { u8 *p = d; while (n--) *p++ = 0; }
static u32 udiv(u32 a, u32 b)             /* (small numbers only; the barrier keeps it a loop, not a library call) */
{
    u32 q = 0;
    while (a >= b) { a -= b; q++; __asm__ volatile("" : "+r"(a)); }
    return q;
}

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
static u32 max_speed, time_rpm;

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
    max_speed = MIN_SPEED;
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
    hit(0, game_hit);                                        /* UpdateOpponentScores: player 0, then us */
    hit(1, our_hit);
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
    if (size == 40 && state == ST_RESULTS && kept >= 6) {    /* the leader's time and best RPM */
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
    if (state == ST_COUNTDOWN && c == SEND_KEYS) { state = ST_BLENDING; start_blend(); }
    if (state == ST_BLENDING) {
        if (c == SEND_KEYS) { blend_frame(frame[2][game], frame[0][ours] == SEND_KEYS ? frame[2][ours] : 0); return; }
        state = ST_RESULTS;                                  /* the game's play is over */
    }
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
        if (frame[1][game] == LEADER_GO || frame[1][game] == LEADER_STOP) {
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
