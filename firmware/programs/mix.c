/* mix.c - the DUO's GBA sits in a Pokemon Ruby/Sapphire Cable Club Record Corner as the other
 * player and mixes records with the game: up to twenty Secret Bases from the PC (.sb3 files) go in,
 * and the game's own twenty come back to the PC. docs/RECORD_MIXING.md. The game files the bases
 * by its own rules and saves itself; nothing is written to either cartridge by this program.
 *
 * The link engine (transfers, roles, master pacing, the PC) is trade.c's, unchanged. On top:
 *   - the Cable Club (0x3311, cable_club.c sub_808350C): link players, each player's trainer card
 *     (0xCCCC 2), and the same link carries on into the Record Corner: once the game sends room
 *     keys (0xCAFE), we send one a frame too, walking to a seat on our side of the table - player
 *     0: up, up, left, left, up to (6,6); player 1: up, up, right x4, up to (13,6) - then key 22
 *     ("seated");
 *   - once both players are seated, each game runs Task_RecordMixing_Main: its room keys stop
 *     (ClearLinkCallback_2), and after 80 frames the records go across in 24 rounds: the master
 *     asks with 0xCCCC 1 and every player sends 200 bytes. Our record is the PC's twenty bases
 *     (rounds 0-15 exactly), then - so that nothing else in the game changes - its own TV shows,
 *     news, Mauville old man, Dewford trends and day-care mail handed straight back, which takes
 *     waiting for the game's block of each later round before sending ours; an empty Battle Tower
 *     record (a friend who hasn't been there); and the PC's gift item (only player 0's counts);
 *   - the game's bases (its rounds 0-15) are kept, in place of ours once each has gone, for the PC;
 *   - the game merges, saves (by itself, no link barrier) and closes the link (0x5FFF); then
 *     reopens it as 0x3322 (cable_club.c sub_8083664) and the room comes back: we stand up (26),
 *     walk back to the door and leave (23), or follow the player out;
 *   - 0x5FFF answered, as always.
 * The PC loads: base count, our gender, gift item, trainer name and ID, 20 x 160-byte bases. */
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

#define LT_MIX   0x3311   /* the attendant's link, kept open into the Record Corner */
#define LT_AFTER 0x3322   /* the room again after mixing (cable_club.c sub_8083664, VAR_0x8004 = 4) */

#define CHUNK       200   /* record_mixing.c BUFFER_CHUNK_SIZE */
#define ROUNDS      24    /* Ruby sends 24 chunks of its 0x1230-byte record */
#define BASE_ROUNDS 16    /* 20 x 160 bytes of Secret Bases: exactly rounds 0-15 */
#define BT_START    0x1124 /* struct PlayerRecords: the Battle Tower record, 0xA4 bytes */
#define GIFT_AT     0x11C8 /* u16 giftItem, then filler to 0x1230 */
#define START_WAIT  150   /* as master: frames after both are seated before the first round
                           * (each game waits 20 + 60 frames, then copies its first chunk) */
#define ROUND_GAP   8     /* as master: frames between a round's end and the next request */

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

/* ------------------------------------------------------------------ what the PC loads */
#define BLOB_MAX (16 + 3200 + 28)
static u32 blob_words[BLOB_MAX / 4], put_at, blob_ready;
#define BLOB ((u8 *)blob_words)
#define BASE_COUNT  BLOB[0]
#define OUR_GENDER  BLOB[1]             /* the first base's owner: 0 boy, 1 girl */
#define GIFT_LO     BLOB[2]
#define GIFT_HI     BLOB[3]
#define OUR_NAME    (BLOB + 4)          /* 8 bytes, game charset */
#define OUR_TID     (BLOB + 12)         /* 4 bytes */
#define BASES       (BLOB + 16)         /* 20 x 160: ours to send; then the game's, as they arrive */
#define LABEL       ((const char *)BLOB + 3216)  /* 28: a line for the screen, e.g. "Bringing 12 bases" */

/* ------------------------------------------------------------------ progress, for the PC */
enum { ST_WAITING, ST_HANDSHAKE, ST_CONNECTED, ST_ROOM, ST_WALKING, ST_SEATED, ST_MIXING, ST_MIXED,
       ST_REOPENING, ST_BACK, ST_WALKING_OUT, ST_EXITING, ST_DONE };
static u32 state, is_master, transfers, bad_checksums, game_lp_type, game_lp_lang, stop_requested;
static u32 role_known, si_low_run, sessions, hs_run, max_gap;
static u8 game_player[60];

/* the sitting's own story */
static u32 room_keys_seen, walk_frame, game_ready, game_quiet, cafe_stopped;
static u32 rounds_asked, game_blocks, our_blocks, mirror_wait, copy_pending, round_timer, start_timer;
static u32 game_exiting, sent_exit, close_pending, close_at;
static u8 chunk[CHUNK];                   /* a later round's chunk: the game's, handed back */

/* ------------------------------------------------------------------ the link layer */
static u32 send_idx, recv_idx, checksum, checksum_ready, nonzero;
static u16 frame[CMD_LEN][2], current[CMD_LEN];
#define QN 4
static u16 qcmd[QN][3];                   /* small commands waiting to go: up to 3 words */
static u32 qhead, qcount;
static u16 loaded;

static u32 rx_size, rx_have, rx_on;       /* the game's block */
static u8 rx_buf[224];
static u32 player_pending;

static const u8 *tx_src;                  /* our outgoing block */
static u32 tx_len, tx_off, tx_on, tx_header, tx_kind;
static u8 our_player[60], blank[100];

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
}

static void queue(u16 w0, u16 w1, u16 w2)
{
    if (qcount == QN) return;
    u16 *q = qcmd[(qhead + qcount) % QN];
    q[0] = w0; q[1] = w1; q[2] = w2;
    qcount++;
}

static void send_block(const u8 *src, u32 len, u32 kind)
{
    tx_src = src; tx_len = len; tx_off = 0; tx_header = 0; tx_on = 1; tx_kind = kind;
}

static u16 room_key(void)                 /* our key for this frame in the Record Corner */
{
    /* after the room has settled: a step, then nothing until it's over (20 frames); then
     * "seated" (22), once the game has seen us step onto the seat */
    static const u8 walk0[5] = { 19, 19, 20, 20, 19 };
    static const u8 walk1[7] = { 19, 19, 21, 21, 21, 21, 19 };
    u32 steps = is_master ? 5 : 7;
    u32 f = walk_frame++;
    if (f < 40) return 17;
    f -= 40;
    if (f < steps * 20) {
        if (f % 20) return 17;
        return is_master ? walk0[f / 20] : walk1[f / 20];
    }
    if (f == steps * 20 + 10) { state = ST_SEATED; return 22; }
    return 17;
}

static u16 exit_key(void)                 /* back in the room after mixing: leave it */
{
    /* we are still "seated" (0x82): stand up (26) once the game's player is free to move, walk
     * back to the door (player 1 from (13,6): down, left x4, down, down; player 0 from (6,6):
     * down, right x2, down, down), press down on it (the exit prompt), then 23. If the player
     * leaves first, we follow at once. */
    static const u8 out0[5] = { 18, 21, 21, 18, 18 };
    static const u8 out1[7] = { 18, 20, 20, 20, 20, 18, 18 };
    u32 steps = is_master ? 5 : 7;
    u32 f = walk_frame++;
    if (sent_exit) return 17;
    if (game_exiting) { sent_exit = 1; state = ST_EXITING; return 23; }
    if (f < 90) return 17;
    if (f == 90) return 26;
    f -= 110;
    if ((int)f < 0) return 17;
    if (f < steps * 20) {
        if (f % 20) return 17;
        state = ST_WALKING_OUT;
        return is_master ? out0[f / 20] : out1[f / 20];
    }
    if (f == steps * 20 + 10) return 18;
    if (f == steps * 20 + 40) { sent_exit = 1; state = ST_EXITING; return 23; }
    return 17;
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
            u32 lo = at < tx_len ? tx_src[at] : 0, hi = at + 1 < tx_len ? tx_src[at + 1] : 0;
            current[1 + j] = lo | hi << 8;
        }
        tx_off += 14;
        if (tx_off >= tx_len) { tx_on = 0; if (tx_kind == 1) our_blocks++; }
        return;
    }
    if (game_lp_type == LT_MIX && room_keys_seen && !cafe_stopped) {     /* the room: a key every frame */
        current[0] = 0xCAFE;
        current[1] = room_key();
        if (state < ST_WALKING) state = ST_WALKING;
    } else if (game_lp_type == LT_AFTER && room_keys_seen) {
        current[0] = 0xCAFE;
        current[1] = exit_key();
    }
}

static u8 card[100];
static void build_card(void)              /* the trainer card the game shows for us */
{
    /* struct TrainerCard (pokeruby trainer_card.h): the first base's owner's gender, ID and name;
     * no stars, no play time, no money, no Pokedex */
    zero(card, sizeof card);
    card[0x00] = OUR_GENDER;
    card[0x0E] = OUR_TID[0]; card[0x0F] = OUR_TID[1];
    memcpy(card + 0x30, OUR_NAME, 8);
    card[0x38] = game_player[16];
}

static void flush_copy(void)              /* a base round's game block, once ours has gone */
{
    /* (both blocks of a round start in the same frame, so ours has always gone by the time the
     * game's arrives; the wait is a safety margin, not something the tests can tell apart) */
    if (copy_pending && !tx_on) {
        memcpy(BASES + CHUNK * (game_blocks - 1), rx_buf, CHUNK);
        copy_pending = 0;
    }
}

static void send_mirror(u32 r)            /* round r >= 16: the game's own chunk, handed back */
{
    memcpy(chunk, rx_buf, CHUNK);
    u32 at = CHUNK * r;
    for (u32 i = 0; i < CHUNK; i++, at++) {
        if (at >= BT_START && at < GIFT_AT) chunk[i] = 0;     /* no Battle Tower record */
        else if (at == GIFT_AT) chunk[i] = GIFT_LO;
        else if (at == GIFT_AT + 1) chunk[i] = GIFT_HI;
        else if (at > GIFT_AT + 1) chunk[i] = 0;              /* the filler */
    }
    send_block(chunk, CHUNK, 1);
}

static void answer_request(u32 n)         /* 0xCCCC n: our block of that size */
{
    if (n == 1 && game_lp_type == LT_MIX && rounds_asked < ROUNDS) {
        flush_copy();
        u32 r = rounds_asked++;
        if (state < ST_MIXING) state = ST_MIXING;
        cafe_stopped = 1;
        if (r < BASE_ROUNDS) send_block(BASES + CHUNK * r, CHUNK, 1);
        else if (game_blocks > r) send_mirror(r);             /* (the game's was quicker) */
        else mirror_wait = 1;
    } else if (n == 2) {
        build_card();
        send_block(card, 100, 4);
    } else {
        send_block(blank, n == 4 ? 40 : n == 2 ? 100 : n == 3 ? 220 : 200, 4);
    }
}

static void game_block(u32 size)          /* a whole block from the game has arrived */
{
    if (size == 60 && player_pending) {
        memcpy(game_player, rx_buf, 60);
        game_lp_type = game_player[16 + 0x14] | game_player[16 + 0x15] << 8;
        game_lp_lang = game_player[16 + 0x1A];
        build_our_player();
        send_block(our_player, 60, 0);
        player_pending = 0;
        if (game_lp_type == LT_MIX && state < ST_ROOM) state = ST_ROOM;
        if (game_lp_type == LT_AFTER) { state = ST_BACK; room_keys_seen = walk_frame = game_exiting = sent_exit = 0; }
        return;
    }
    if (size == CHUNK && game_lp_type == LT_MIX && game_blocks < ROUNDS) {
        u32 r = game_blocks++;
        if (r < BASE_ROUNDS) {
            copy_pending = 1;                                  /* into BASES once ours has gone */
            flush_copy();
        } else if (mirror_wait && r + 1 == rounds_asked) {
            mirror_wait = 0;
            send_mirror(r);
        }
    }
}

static void process_command(void)
{
    u32 game = is_master ? 1 : 0;
    u16 c = frame[0][game];
    if (c == 0x2222 || frame[0][is_master ? 0 : 1] == 0x2222)
        player_pending = 1;
    if (frame[0][is_master ? 0 : 1] == 0xCCCC)                  /* our own request, as master */
        answer_request(frame[1][is_master ? 0 : 1]);
    if (c != 0xCAFE) game_quiet++;
    switch (c) {
    case 0xBBBB:
        rx_size = frame[1][game] <= sizeof rx_buf ? frame[1][game] : sizeof rx_buf;
        rx_have = 0; rx_on = 1;
        break;
    case 0x8888:
        if (!rx_on) break;
        for (u32 j = 1; j < CMD_LEN && rx_have < rx_size; j++) {
            rx_buf[rx_have++] = frame[j][game];
            if (rx_have < rx_size) rx_buf[rx_have++] = frame[j][game] >> 8;
        }
        if (rx_have >= rx_size) { rx_on = 0; game_block(rx_size); }
        break;
    case 0xCCCC:
        answer_request(frame[1][game]);
        break;
    case 0xCAFE:
        room_keys_seen = 1;
        game_quiet = 0;
        if (game_lp_type == LT_MIX) {
            if (frame[1][game] == 22) game_ready = 1;          /* the player has sat down */
            if (frame[1][game] == 29) game_ready = 0;          /* ... and stood up again (B) */
        }
        if (game_lp_type == LT_AFTER && frame[1][game] == 23) game_exiting = 1;
        break;
    case 0x5FFF:
        queue(0x5FFF, 0, 0);
        if (state == ST_BACK || state == ST_WALKING_OUT || state == ST_EXITING) close_pending = 1;
        else if (state == ST_MIXED) state = ST_REOPENING;      /* saved; the room comes next */
        break;
    }
}

static void each_cycle(void)              /* once a command cycle (a frame): the sitting's decisions */
{
    flush_copy();
    if (game_lp_type == LT_MIX && rounds_asked == ROUNDS && game_blocks == ROUNDS && our_blocks == ROUNDS
            && !tx_on && state == ST_MIXING)
        state = ST_MIXED;
    /* both seated: once the game's room keys have stopped (it has started mixing), so do ours */
    if (game_lp_type == LT_MIX && state == ST_SEATED && game_ready && room_keys_seen && game_quiet >= 3)
        cafe_stopped = 1;
    if (!is_master || game_lp_type != LT_MIX || tx_on || qcount)
        return;
    /* as master in the Cable Club, we ask for the trainer cards (cable_club.c sub_8083288) */
    if (state == ST_ROOM && !room_keys_seen && rounds_asked == 0 && !round_timer) {
        if (++start_timer > 40) { queue(0xCCCC, 2, 0); round_timer = 1; start_timer = 0; }
        return;
    }
    /* as master once both are seated: the 24 rounds, each when the last has fully gone */
    if ((state == ST_SEATED && game_ready) || state == ST_MIXING) {
        if (rounds_asked == 0) {
            if (++start_timer > START_WAIT) { queue(0xCCCC, 1, 0); round_timer = 0; }
        } else if (rounds_asked < ROUNDS && game_blocks == rounds_asked && our_blocks == rounds_asked
                   && !copy_pending && !mirror_wait) {
            if (++round_timer > ROUND_GAP) { queue(0xCCCC, 1, 0); round_timer = 0; }
        }
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
    return state >= ST_MIXED ? LT_AFTER : LT_MIX;
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
            else game_quiet++;                                   /* nobody said anything this frame */
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
    "Mixing: waiting for game", "Mixing: handshaking", "Mixing: linked", "Cable Club: link players",
    "Walking to the table", "Seated at the table", "Mixing records", "Mixed: the game saves",
    "Mixed and saved", "Back in the room", "Walking out to the door", "Leaving the room",
    "Done: the link is closed",
};
static u32 shown = 0xFF, label_shown;

static void screen(api_t *api, int linked)
{
    if (shown == state || (linked && state != ST_DONE)) return;
    if (!label_shown) {
        label_shown = 1;
        api->log("Playing: Record Corner");
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
        if (put_at < sizeof blob_words / 4)
            blob_words[put_at++] = arg;
        api->reply(0x2C, put_at);
        return 0;
    }
    switch (arg & 0xFF) {
    case 0: v = state | is_master << 5 | (sessions & 3) << 6 | (transfers & 0xFFFFFF) << 8; break;
    case 1: v = bad_checksums; break;
    case 2: v = game_lp_type | game_lp_lang << 16; break;
    case 3: v = rounds_asked | game_blocks << 8 | our_blocks << 16 | game_ready << 24; break;
    case 4: {                                                    /* the bases area, a word at a time */
        u32 at = 4 * idx;
        v = at + 3 < 3200 ? BASES[at] | BASES[at + 1] << 8 | BASES[at + 2] << 16 | (u32)BASES[at + 3] << 24 : 0;
        break;
    }
    case 6: v = game_player[16] | game_player[17] << 8 | game_player[18] << 16 | (u32)game_player[19] << 24; break;
    case 7: {                                                    /* the game's link player: ID, name */
        u32 at = 16 + 4 + 4 * (idx < 3 ? idx : 0);
        v = game_player[at] | game_player[at + 1] << 8 | game_player[at + 2] << 16 | (u32)game_player[at + 3] << 24;
        break;
    }
    case 8: v = max_gap; break;
    case 9: v = game_player[16 + 0x10]; break;                  /* the game's player's gender */
    case 20: put_at = 0; blob_ready = 0; v = sizeof blob_words; break;
    case 21: v = api->crc32(blob_words, put_at * 4);
             blob_ready = put_at * 4 >= 16 + 3200 && BASE_COUNT <= 20;
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
