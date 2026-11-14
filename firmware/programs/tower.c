/* tower.c - the DUO as the player's partner in Emerald's Battle Tower link multi battle (8 November
 * 2026; docs/MULTI.md). Grown from colosseum.c: the same link engine, blocks, battle answers and PC
 * choices, without the room walk (the Tower's link-up is at the counter). The DUO can be either
 * player (11 November); the game always runs the battle:
 *   - player 1 (the game's GBA on the master end): player 0's copy of the Tower trainers' list and
 *     party is the one the battle uses, the game's; we answer the game's blocks as below;
 *   - player 0 (the DUO's GBA on the master end): we ask for the trainer cards, send the game's own
 *     trainers' list and Tower party straight back (player 1 keeps player 0's), send the header
 *     signature 0x0001 (below Emerald's 0x0300: FindLinkBattleMaster makes the game, on the highest
 *     version, the battle's master), and give the verdict on carrying on from both choices. Our
 *     Pokemon are then party slots 0-2 and battler 0, the game's 3-5 and battler 2.
 *   - the lobby (LINKTYPE_BATTLE_TOWER_50 0x2266 / _OPEN 0x2277): link players (the game's version:
 *     Emerald), our trainer card (our two Pokemon's species at 0x54: the same species as the
 *     player's fails the link-up), the link save's three "ready" barriers, the win streaks (4 bytes
 *     each) and the Tower trainers' list (40 bytes; ours is the game's back), then closed;
 *   - each battle (LINKTYPE_BATTLE_TOWER 0x2288, CB2_HandleStartMultiPartnerBattle): link players,
 *     then seven blocks each way, ours once the game's of that turn is here: the header (the game's
 *     own signature: player 0, the game, runs the battle), our party (two Pokemon, then a third,
 *     empty), three blocks of the Tower trainers' party (ours ignored: zeros) and the recorded
 *     battle's seed. Four battlers: the player 0, us 2, the Tower's trainers 1 and 3 (the game's
 *     AI). We answer battler 2's choices (the PC's, as in the Colosseum); our Pokemon are party slots
 *     3 and 4 (MULTI_PARTY_SIZE);
 *   - after a win that isn't the seventh (Task_LinkRetireStatusWithBattleTowerPartner): the link
 *     again; we, the follower, send our choice first (2 bytes: carry on, or retire after the battle
 *     the PC set), the game its verdict (2 bytes), a "ready" barrier, closed. A loss, the seventh win
 *     or a verdict to stop ends the challenge.
 * Every block goes into the log, as colosseum.c's. */
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

#define LT_TOWER_50   0x2266   /* the lobby's link-up, level 50 */
#define LT_TOWER_OPEN 0x2277   /* ... open level */
#define LT_TOWER      0x2288   /* each battle, and the link after it */
#define PARTY_BASE    (is_master ? 0 : 3)   /* our Pokemon's party slots (link id 0: 0-2; id 2: 3-5) */
#define OUR_BATTLER   (is_master ? 0 : 2)   /* our battler: the link player's id (0 or 2) */

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
#define BLOB_MAX    844
static u32 put_at, blob_ready;
#define blob_words  ((u32 *)BLOB_AT)
#define BLOB        ((u8 *)BLOB_AT)
#define TEAM_COUNT  BLOB[0]             /* 1 or 2 */
#define OUR_GENDER  BLOB[1]             /* our trainer: 0 boy, 1 girl */
#define ASK_PC      BLOB[2]             /* 1: the PC makes our choices (8 November); 0: we play simply */
#define FALLBACK_S  BLOB[3]             /* seconds without a word from the PC before we choose ourselves */
#define OUR_NAME    (BLOB + 4)          /* 8 bytes, game charset */
#define OUR_TID     (BLOB + 12)         /* 4 bytes */
#define LABEL       ((const char *)BLOB + 20)   /* 28: a line for the screen */
#define RETIRE_AFTER BLOB[47]           /* retire after this battle (0: carry on) */
#define PARTY       (BLOB + 48)         /* 6 x 100: the game's party form */
#define CARD        (BLOB + 648)        /* 100: our trainer card (struct TrainerCard) */
#define PARTNER_MENU (BLOB + 748)       /* 96: our two Pokemon for the game's party menu (MultiPartnerMenuPokemon x 3) */

#define LOG         ((u8 *)(BLOB_AT + 0x400))
#define LOG_MAX     0x1F800             /* to the end of the buffer */
#define RX_MAX      0x400               /* (a block longer than this is kept cut short) */
static u32 log_len, log_full, log_seq, log_lost;
static u8 scratch[64];                    /* where a block goes once the log is full */
enum { K_GAME, K_OURS, K_EVENT };
enum { E_SESSION = 1, E_CLOSE, E_READY, E_SEATED, E_CHOICE, E_END, E_TRUNCATED, E_DROPPED, E_ASKED, E_FALLBACK,
       E_VERDICT };

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
enum { ST_WAITING, ST_HANDSHAKE, ST_CONNECTED, ST_LOBBY, ST_TRAINERS, ST_BETWEEN, ST_STARTING, ST_TEAMS,
       ST_BATTLE, ST_OVER, ST_RETIRE, ST_DONE };
static u32 state, is_master, transfers, bad_checksums, game_lp_type, game_lp_lang, stop_requested;
static u32 role_known, si_low_run, sessions, hs_run, max_gap;
static u8 game_player[60];

/* the challenge's own story */
static u32 close_pending, close_at, battles, won, verdict, lobby_blocks, retire_next, choice_sent;
static u8 small[40];                      /* our short blocks: the win streak, the trainers, our choice */
static u32 barriers;
static u32 card_asked, lead_timer;        /* as player 0: the trainer cards' request */
static u8 mirror[200];                    /* as player 0: the game's Tower party block, to send back */
static u32 start_in, start_out;           /* the battle's opening blocks: the game's, ours (seven each) */
static u32 partner_stage;                 /* each battle links twice (13 November, the emulator): 1 the first link,
                                             for the party menu's summaries; 2 ours sent, the battle's link next */
static u32 commands, ours_answered, outcome, choices;
static u32 fainted, on_field[2], last_pick;
/* a choice waiting for the PC, one per battler of ours (side 0: battler 1, side 1: battler 3) */
static u8 pend_on[2], pend_kind[2], pend_seq[2], pend_moves[2], pend_hdr[2][8], pend_fb[2][4];
static u32 pend_since[2], pc_alive_at, ask_seq;

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
    /* the game's own version (the Tower's link multi battle is Emerald with Emerald); lp_field_2 0 */
    u32 version = game_player[16];
    lp[0] = version; lp[1] = game_player[17];
    memcpy(lp + 4, OUR_TID, 4);
    memcpy(lp + 8, OUR_NAME, 8);
    memcpy(lp + 0x14, game_player + 16 + 0x14, 4);           /* link type */
    memcpy(lp + 0x1A, game_player + 16 + 0x1A, 2);           /* language */
    if (version >= 3) {                                      /* Emerald: the progress flags */
        lp[0x10] = 0x11;                                     /* (as trade.c: National Dex, game cleared; */
        lp[0x13] = OUR_GENDER;                               /* the gender here) */
    } else {
        lp[0x10] = OUR_GENDER;                               /* Ruby/Sapphire keep the gender here */
    }
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

static void next_command(void)
{
    for (u32 i = 0; i < CMD_LEN; i++) current[i] = 0;
    if (is_master && !tx_on && !qcount && state == ST_LOBBY && game_player[16] && !card_asked && ++lead_timer > 40) {
        queue(0xCCCC, 2, 0); card_asked = 1;                     /* (as player 0: cable_club.c, the cards) */
    }
    if (qcount) {
        u16 *q = qcmd[qhead];
        current[0] = q[0]; current[1] = q[1]; current[2] = q[2];
        qhead = (qhead + 1) % QN; qcount--;
        return;
    }
    if (!tx_on && tq_count && state >= ST_STARTING && state <= ST_OVER) {   /* the next battle block */
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
}

static void answer_request(u32 n)         /* 0xCCCC n: our block of that size */
{
    if (n == 2) {
        if (!CARD[0x38]) CARD[0x38] = game_player[16];       /* (the card's game: the game's own) */
        send_block(CARD, 100);
    }
    else send_block(0, n == 4 ? 40 : n == 3 ? 220 : n == 2 ? 100 : 200);     /* (zeros: a request we don't expect) */
}

/* ------------------------------------------------------------------ the battle */
static void opening_block(void)          /* our next opening block, once the game's of that turn is here */
{
    if (tx_on || start_out >= 7 || start_in <= start_out || state < ST_STARTING) return;
    const u8 *zeros = PARTY + 400;                              /* (slots 4-5: always empty) */
    if (start_out == 0) send_block(our_header, sizeof our_header - 1);   /* the header (31 bytes) */
    else if (start_out == 1) send_block(PARTY, 200);             /* our two Pokemon */
    else if (start_out == 2) send_block(PARTY + 200, 100);       /* a third (none) */
    else if (start_out < 6) send_block(is_master ? mirror : zeros, 200);   /* the Tower trainers' (player 0's
                                                                   are used: the game's own, back) */
    else send_block(zeros, 4);                                   /* the recorded battle's seed */
    if (start_out == 0) log_bytes(our_header, 31, K_OURS);
    start_out++;
    if (start_out == 7) state = ST_BATTLE;
}

static void game_header(const u8 *b)     /* the game's LinkPartnerHeader: our answer to it */
{
    zero(our_header, sizeof our_header);
    if (is_master) { our_header[0] = 1; our_header[1] = 0; }     /* 0x0001: the game, on 0x0300, runs it */
    else { our_header[0] = b[0]; our_header[1] = b[1]; }         /* its own: player 0 (the game) runs it */
    u32 fit = 0;
    for (u32 i = 0; i < TEAM_COUNT && i < 2; i++) fit |= 1u << (2 * i);   /* every Pokemon fit to battle */
    our_header[2] = fit; our_header[3] = fit >> 8;
}

static u32 pick_next(void)               /* a Pokemon to send in after a faint: the next one fit */
{
    for (u32 i = PARTY_BASE; i < PARTY_BASE + TEAM_COUNT; i++)
        if (!(fainted >> i & 1) && i != on_field[0]) return i;
    return 6;                                                  /* (PARTY_SIZE: none) */
}

static void answer_choice(const u8 *hdr, u32 kind, const u8 *r)   /* our answer to a choice, then "done" */
{
    battle_block(hdr, 1, r, kind == 2 ? 5 : 4);
    if (kind) {
        log_event(E_CHOICE, kind == 2 ? 0x100 | r[1] : r[2]);
        if (kind == 2 && r[1] < 6) last_pick = r[1];
        choices++;
    }
    ours_answered++;
    u8 done[4] = { is_master ? 0 : 1 };              /* (then "done", as below) */
    battle_block(hdr, 2, done, 4);
}

static void battle_command(const u8 *b, u32 len)   /* one of the game's battle blocks */
{
    if (len < 9) return;
    if (b[0] != 0) return;                          /* (its own answers and "done"s: logged only) */
    commands++;
    u32 battler = b[1], cmd = b[8], ours = battler == OUR_BATTLER, side = 0;
    const u8 *d = b + 8;
    u8 r[4] = { 0, 0, 0, 0 };
    if (ours && (cmd == C_CHOOSEACTION || cmd == C_CHOOSEMOVE || cmd == C_CHOOSEPOKEMON)) {
        /* our own simple choice: fight; the first move with PP at the foe opposite; the next fit
         * Pokemon. Kept as the fallback when the PC chooses (and doesn't answer in time). */
        u32 kind = cmd == C_CHOOSEACTION ? 0 : cmd == C_CHOOSEMOVE ? 1 : 2, moves = 0;
        r[0] = R_TWORETURNVALUES;
        if (kind == 1) {
            for (u32 i = 0; i < 4; i++)
                if (len >= 8 + 16 && (d[4 + 2 * i] | d[5 + 2 * i]) && d[12 + i]) moves |= 1u << i;
            u32 slot = 0;
            while (slot < 3 && moves && !(moves >> slot & 1)) slot++;
            r[1] = 10; r[2] = slot; r[3] = battler ^ 1;
        }
        if (kind == 2) { r[0] = R_CHOSENMON; r[1] = pick_next(); }
        if (!ASK_PC) { answer_choice(b, kind, r); return; }
        pend_on[side] = 1; pend_kind[side] = kind; pend_seq[side] = ++ask_seq & 31; pend_moves[side] = moves;
        memcpy(pend_hdr[side], b, 8); memcpy(pend_fb[side], r, 4);
        pend_since[side] = now();
        log_event(E_ASKED, battler | kind << 8);
        return;                                     /* (answered, and "done", once the PC has chosen) */
    }
    if (ours) {
        switch (cmd) {
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
        battles++;
        won += outcome == 1;                                    /* (B_OUTCOME_WON: our side too) */
        retire_next = outcome == 1 && battles < 7;
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
        if (game_lp_type == LT_TOWER_50 || game_lp_type == LT_TOWER_OPEN) {
            state = ST_LOBBY; lobby_blocks = 0; card_asked = lead_timer = 0;
        }
        else if (game_lp_type == LT_TOWER && retire_next) {      /* after a win: our choice first (each_cycle) */
            state = ST_RETIRE; choice_sent = 0;
        }
        else if (game_lp_type == LT_TOWER) {
            state = ST_STARTING; start_in = start_out = 0; on_field[0] = PARTY_BASE;
            partner_stage = partner_stage == 2 ? 0 : 1;          /* (the first of the battle's two links, or the second) */
        }
        return;
    }
    if (state == ST_LOBBY || state == ST_TRAINERS) {             /* the win streak, then the trainers */
        if (size == 4 && lobby_blocks == 0) { zero(small, 4); send_block(small, 4); lobby_blocks = 1; state = ST_TRAINERS; }
        else if (size == 40 && lobby_blocks == 1) { memcpy(small, b, 40); send_block(small, 40); lobby_blocks = 2; }
        return;
    }
    if (state == ST_RETIRE && is_master) {                       /* the game's choice: our verdict */
        u32 theirs = b[0] | b[1] << 8, ours = RETIRE_AFTER && battles >= RETIRE_AFTER;
        verdict = ours && theirs ? 1 : theirs ? 2 : ours ? 3 : 0;     /* BOTH_ / MEMBER_ / LEADER_RETIRE, CONTINUE */
        zero(small, 2);
        small[0] = verdict;
        send_block(small, 2);
        choice_sent = 1;
        log_event(E_VERDICT, verdict);
        return;
    }
    if (state == ST_RETIRE) {                                    /* the game's verdict */
        verdict = b[0] | b[1] << 8;
        log_event(E_VERDICT, verdict);
        return;
    }
    if (partner_stage == 1 && state == ST_STARTING) {          /* CB2_PreInitMultiBattle: each side's two Pokemon, */
        if (size == 96) { send_block(PARTNER_MENU, 96); partner_stage = 2; }   /* for the party menu; then the link */
        return;                                                /* closes and the battle's own opens */
    }
    if (state < ST_STARTING || state > ST_OVER) return;
    if (start_in < 7) {                                    /* the opening: seven blocks */
        if (start_in == 0) { game_header(b); state = ST_TEAMS; }
        if (start_in >= 3 && start_in < 6) {                     /* the Tower's trainers: kept to send back */
            zero(mirror, sizeof mirror);
            memcpy(mirror, b, kept < sizeof mirror ? kept : sizeof mirror);
        }
        start_in++;
        return;
    }
    battle_command(b, kept);
}

static void process_command(void)
{
    u32 game = is_master ? 1 : 0;
    u16 c = frame[0][game];
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
    case 0x5FFF:
        queue(0x5FFF, 0, 0);
        log_event(E_CLOSE, state);
        if (state == ST_LOBBY || state == ST_TRAINERS) {         /* the lobby: on to the battles, or a failed link-up */
            if (lobby_blocks == 2) state = ST_BETWEEN; else close_pending = 1;
        }
        else if (state == ST_OVER) { if (retire_next) state = ST_BETWEEN; else close_pending = 1; }
        else if (state == ST_RETIRE) { if (verdict || small[0]) close_pending = 1; else { retire_next = 0; state = ST_BETWEEN; } }
        break;
    }
}

static void each_cycle(void)              /* once a command cycle (a frame) */
{
    opening_block();
    if (state == ST_RETIRE && !is_master && !choice_sent && !tx_on && !player_pending) {   /* (once our link player has gone) */
        zero(small, 2);
        small[0] = RETIRE_AFTER && battles >= RETIRE_AFTER;   /* BATTLE_TOWER_LINK_RETIRE : _CONTINUE */
        send_block(small, 2);
        choice_sent = 1;
    }
}

static void new_session(void)             /* the link is up again: forget the last one's blocks */
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
            if (is_master) queue(0x2222, battles || lobby_blocks == 2 ? LT_TOWER : LT_TOWER_50, 0);   /* as player 0:
                                                       link players, please (the type: our best guess; the game
                                                       answers whatever it says, link.c) */
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
    "Tower: waiting for game", "Tower: handshaking", "Tower: linked", "Lobby: linking up",
    "Lobby: the trainers", "Between battles", "Battle: opening the link", "Battle: swapping teams",
    "Battling", "Battle over", "Carry on?", "Done: the link is closed",
};
static u32 shown = 0xFF, label_shown;

static void screen(api_t *api, int linked)
{
    if (shown == state || (linked && state != ST_DONE)) return;
    if (!label_shown) {
        label_shown = 1;
        api->log("Playing: Battle Tower partner");
        if (LABEL[0]) api->log(LABEL);
    }
    shown = state;
    if (state < sizeof SAY / sizeof SAY[0]) api->log(SAY[state]);
}

/* ------------------------------------------------------------------ the PC's choices (8 November)
 * Poll 12 says what's waiting (and tells us the PC is there); poll 13 answers one: the side (bit 0),
 * the value (bits 1-8: an action, a move slot or a party slot), the target battler (bits 9-10) and the
 * choice's number (bits 11-15). We check it against the rules (a move with PP, a Pokemon that can
 * battle and isn't out) and send it; without a word from the PC for FALLBACK_S seconds, we choose
 * ourselves. */
static u32 pc_answer(u32 a)
{
    u32 side = a & 1, value = a >> 1 & 0xFF, target = a >> 9 & 3, seq = a >> 11 & 31;
    if (!pend_on[side] || pend_seq[side] != seq) return 0;
    u32 kind = pend_kind[side], ok = 1;
    u8 r[4] = { R_TWORETURNVALUES, value, 0, 0 };
    if (kind == 0 && value != 0 && !(value == 2 && pick_next() < 6)) ok = 0;    /* fight, or switch if one can */
    if (kind == 1) {
        if (value > 3 || !(pend_moves[side] >> value & 1) || !(target & 1)) ok = 0;   /* (at the Tower's trainers) */
        r[1] = 10; r[2] = value; r[3] = target;
    }
    if (kind == 2) {
        if (value < PARTY_BASE || value >= PARTY_BASE + TEAM_COUNT || fainted >> value & 1 || value == on_field[0]) ok = 0;
        r[0] = R_CHOSENMON;
    }
    pend_on[side] = 0;
    if (!ok) log_event(E_FALLBACK, pend_hdr[side][1]);           /* against the rules: our own choice instead */
    answer_choice(pend_hdr[side], kind, ok ? r : pend_fb[side]);
    return ok ? 1 : 2;
}

static void choose_late(void)                /* the PC has gone quiet: our own choice */
{
    u32 t = now(), wait = (FALLBACK_S ? FALLBACK_S : 15) * 60 * LINES_PER_FRAME;
    for (u32 side = 0; side < 2; side++) {
        if (!pend_on[side]) continue;
        u32 since = pc_alive_at - pend_since[side] < 0x80000000u ? pc_alive_at : pend_since[side];
        if (t - since < wait) continue;
        pend_on[side] = 0;
        log_event(E_FALLBACK, pend_hdr[side][1]);
        answer_choice(pend_hdr[side], pend_kind[side], pend_fb[side]);
    }
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
    case 10: v = battles | won << 8 | verdict << 16 | lobby_blocks << 24; break;   /* the challenge so far */
    case 11: v = fainted | choices << 8 | (tq_dropped & 0xFF) << 16 | (log_lost & 0xFF) << 24; break;
    case 12: pc_alive_at = now();                               /* what's waiting for the PC */
             v = 0;
             for (u32 k = 0; k < 2; k++)
                 if (pend_on[k]) v |= (1u | pend_kind[k] << 1 | pend_seq[k] << 3) << (8 * k);
             v |= (on_field[0] & 7) << 16 | (on_field[1] & 7) << 19 | fainted << 22;
             break;
    case 13: pc_alive_at = now(); v = pc_answer(idx); break;
    case 20: put_at = 0; blob_ready = 0; v = BLOB_MAX; break;
    case 21: v = api->crc32(blob_words, put_at * 4);
             blob_ready = put_at * 4 >= BLOB_MAX && TEAM_COUNT >= 1 && TEAM_COUNT <= 2;
             if (blob_ready) { log_len = log_full = log_seq = 0; on_field[0] = PARTY_BASE; on_field[1] = 6; pend_on[0] = pend_on[1] = 0;
                               last_pick = PARTY_BASE; }
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
        if ((pend_on[0] | pend_on[1]) && !(REG_IF & IF_SERIAL))
            choose_late();
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
