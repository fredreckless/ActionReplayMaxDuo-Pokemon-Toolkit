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
#define DMACNT_H(k) REG16(0x040000BA + 12 * (k))   /* DMA0-3 control: bit 15 enable, bits 12-13 timing */

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
#define SCOPE       BLOB[3]             /* 1: the scope - the DUO's own multi-player hardware as master, the lines watched */
#define LINK_TYPE   ((u16)(BLOB[4] | BLOB[5] << 8))   /* 0: the handshake only */
#define OUR_TID     (BLOB + 8)          /* 4 bytes */
#define OUR_NAME    (BLOB + 12)         /* 8 bytes: "DUO", then 2 and 3 added */
#define LABEL       ((const char *)BLOB + 32)   /* 28 */

#define LOG         ((u8 *)(BLOB_AT + 0x400))
#define LOG_MAX     0x1F800
static u32 log_len, log_full, log_seq;
enum { K_GAME, K_OURS, K_EVENT, K_SCOPE };
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
/* 12 November (hardware, rows 12a/12b): every figure above mixed in the 30 s before the game's GBA was
 * on (no pull-up then: SD read low, words of 0 with no stop bit), and the handshake never finished.
 * So the same figures again from the game's first real word on, the first 32 of its words logged, its
 * handshakes counted, and the line's idle level between transfers (it should be high: pulled up) */
static u32 game_on, words2, stop2, timeouts2, edge_min2 = 0xFFFF, edge_max2, hs_reads, hs_run_best, hs_run, logged2;
static u32 sd_low_after, sd_checks;
/* 14 November (hardware, row 12a again): the game sent its handshake 0xB9A0 every time and the DUO read
 * 0xB8A0 every time - one bit (bit 8) wrong, its neighbours right - and about one stop bit in eight
 * missing. That's one sample taken late, at the same point of every transfer: the transfers start on
 * the same line each frame, and a line is 1232 cycles (about 8.5 bits), so a stall once a line (an
 * HBlank DMA left running: the only thing that stops the CPU with interrupts off) lands on bit 8 and
 * near the stop bit. So: every running DMA is paused for the transfer (about 1 ms) and put back after;
 * how late each sample is taken is measured, and which bit is the worst; which channels were running
 * is reported; and why the program stopped. */
static u32 dma_seen, late_max, late_bit, late_bad, done_why;
/* 14 November (hardware, 12a with the DMA fix): the handshake finished in the DUO's reading, but the game
 * went on sending its handshake 0xB9A0 for ever: link.c's child finishes only on reading the master's
 * 0x8FFF in slot 0 (with the player count as before), and the DUO sent it once. So after its 0x8FFF and
 * the first checksum slot the DUO looks at the game's word: still the handshake, and it goes back (one
 * plain handshake transfer for the count, then 0x8FFF again), counting the tries. */
static u32 confirm, hs_tries, hs_taken_after;
/* 15 November (hardware, 12a with the confirm fix): the game never took the DUO's 0x8FFF in 374 tries -
 * it misreads the DUO's words. So the DUO now tries its sending timing in turn, three tries each: the
 * lead from SC going low to its start bit, and its bit time (sending only: the DUO's reading of the
 * game's words keeps its own). The setting that worked is kept and reported. And "taken" is now
 * decided over three transfers, the game's handshake allowing two bits misread, as a misread 0xB9A0
 * passed for "taken" before (on 15 November, try 494 with a missing stop bit in two words of three). */
/* 15 November, late (hardware): the leads of 146 and 220 silenced the game - it stopped answering at all
 * with them, and the DUO waited on it for good. So the game times its slot from SC going low, and the
 * DUO's start bit belongs close to it: the leads are all short now, the first 0 (SC and the start bit
 * in one write, as a GBA master does), and a setting the game goes quiet with is left after a while. */
static const short SWEEP[][2] = {        /* the lead (cycles; 0: with SC), the bit time's change (1/256 cycle a bit) */
    { 0, 0 }, { 16, 0 }, { 32, 0 }, { 64, 0 }, { 0, 256 }, { 0, -256 }, { 16, 256 }, { 16, -256 },
    { 0, 512 }, { 0, -512 }, { 8, 0 }, { 48, 0 },
};
#define N_SWEEP (sizeof SWEEP / sizeof SWEEP[0])
/* 16 November, night (hardware): with the hybrid, slot 0 comes from the link hardware, and the game
 * has never read a word the DUO sent by hand - in DoHandshake a slot that isn't a handshake and isn't
 * 0xFFFF makes the count 0, a missing one stops it at the slots before. So the hybrid steps through
 * these instead (3 tries each): the gap before slots 2 and 3 (quarter bits), the bit time, and whether
 * slot 3 is sent at all - sent alone, slot 2 shows apart "the game read it" (it links as three) from
 * "it read garbage" (it never links) and "it missed it" (it links as two). */
static const short HYB[][3] = {          /* gap (quarter bits), the bit time's change (1/256 cycle), slots by hand */
    { 4, 0, 2 }, { 4, 0, 1 }, { 2, 0, 2 }, { 2, 0, 1 }, { 1, 0, 2 }, { 6, 0, 2 },
    { 6, 0, 1 }, { 4, 256, 2 }, { 4, -256, 2 }, { 8, 0, 2 }, { 8, 0, 1 }, { 12, 0, 2 },
};                                       /* (the longest gaps last: past the game's wait it links as two, and stays) */
static u8 hyb_out[16];                   /* each one's outcome: 1 garbage (never linked), 2 linked as two (missed),
                                            3 linked as three (slot 2 read), 4 linked as four */
#define N_HYB (sizeof HYB / sizeof HYB[0])
static u32 hyb_gap = 4, hyb_slots = 2;
static u32 silent_run;
static u32 scope_n, scope_taken, scope_words, scope_hs;   /* (the scope, below) */
static u32 sweep_at, sweep_tries, taken_setting = 0xFF, hs_like_count, tx_fp, lead = 64;
static void sweep_apply(void);
static void tx_offsets(void);
static void sweep_next(u32 why)
{
    sweep_tries = 0; silent_run = 0;
    if (++sweep_at == (SCOPE == 2 ? N_HYB : N_SWEEP)) sweep_at = 0;
    sweep_apply();
    log_event(E_TIMING, why | sweep_at);
}
static void sweep_apply(void)
{
    if (SCOPE == 2) {
        u32 k = sweep_at < N_HYB ? sweep_at : 0;
        hyb_gap = GAP_Q ? GAP_Q : HYB[k][0];
        hyb_slots = HYB[k][2];
        tx_fp = (145 << 8) + 163 + (signed char)BIT_ADJ + HYB[k][1];
        tx_offsets();
        return;
    }
    lead = SWEEP[sweep_at][0];
    tx_fp = (145 << 8) + 163 + (signed char)BIT_ADJ + SWEEP[sweep_at][1];
    tx_offsets();
}
static inline u32 hs_like(u16 w)          /* the game's handshake, two bits misread at most */
{
    u32 d = (w & ~3u) ^ 0xB9A0;
    d &= 0xFFFF;
    u32 n = 0;
    while (d) { d &= d - 1; n++; }
    return n <= 2;
}

static inline u16 tnow(void) { return TM0CNT_L; }
#define SIOMULTI(i) REG16(0x04000120 + 2 * (i))
#define SIOMLT_SEND REG16(0x0400012A)
static inline void until(u16 t) { while ((s16)(tnow() - t) < 0) ; }
static inline u16 at_bit(u16 t0, u32 k256) { return t0 + (u16)((bit_fp * k256) >> 16); }   /* k256: bits x 256 */
static inline u16 at_tx(u16 t0, u32 k256) { return t0 + (u16)((tx_fp * k256) >> 16); }     /* (our sending)  */
static inline void set_pins(u16 v) { rc = v; RCNT = v; }

/* 16 November (hardware, the hybrid): the game counted four players, then its checksums parted from
 * the DUO's by a bit or two - so it misreads some of the hand-sent bits. The edges' times and pin
 * values are worked out before the word now, and the loop between them is only the wait and the
 * write; and the DUO notes how late each write came after its time (the most, and at which bit). */
static u32 tx_late_max, tx_late_bit, tx_late_bad, hw_used, hw_differ;
static u16 tx_edge[19], tx_val[3][19];      /* the edges' offsets (bit time), each slot's pin values: made ahead */
static void tx_offsets(void)
{
    for (u32 i = 0; i < 19; i++) tx_edge[i] = at_tx(0, i << 8);
}
static void prepare_word(u32 k, u32 w, u16 base)   /* slot k's word: the pin values for its 19 edges */
{
    u16 hi = base | OUT(P_SD) | P_SD, lo = (base | OUT(P_SD)) & ~P_SD;
    tx_val[k][0] = lo;                                       /* the start bit: low */
    for (u32 i = 0; i < 16; i++) tx_val[k][i + 1] = w >> i & 1 ? hi : lo;
    tx_val[k][17] = hi;                                      /* the stop bit: high */
    tx_val[k][18] = base & ~OUT(P_SD);                       /* SD back to an input (the game's turn) */
}
static u16 tx_late[3][19];
static u32 tx_sent;                       /* the slots sent this transfer (their lateness tallied after) */
static void tx_tally(void)
{
    for (u32 k = 0; k < 3; k++) {
        if (!(tx_sent >> k & 1)) continue;
        for (u32 i = 0; i < 19; i++) {
            if (tx_late[k][i] > tx_late_max) { tx_late_max = tx_late[k][i]; tx_late_bit = i; }
            if (tx_late[k][i] > 48) tx_late_bad++;
        }
    }
    tx_sent = 0;
}
/* 16 November, evening: why slots 2 and 3 failed on hardware. Slot 3's start was worked out only
 * after slot 2's sending returned, with one bit to spare - and on the real GBA the DUO's code is
 * slower than the simulator had it (its samples 62 cycles late against 39), so slot 3's start bit was
 * already overdue: written at once and the next edge straight after, a start bit of a few cycles, and
 * the game read the word wrong. (The simulator at the real speed shows it: the game never links.)
 * Now slots 2 and 3 go as one schedule of edges made before the transfer, from one start - and a start
 * that is overdue moves the whole schedule later, so no edge is ever squeezed. */
static u16 st_at[2 * 19], st_val[2 * 19];
static void prepare_stream(void)          /* slots 2 and 3 back to back, their gap between */
{
    u32 gap = hyb_gap;
    u16 second = at_tx(0, (18 << 8) + (gap << 6));
    for (u32 i = 0; i < 19; i++) {
        st_at[i] = tx_edge[i];           st_val[i] = tx_val[1][i];
        st_at[19 + i] = second + tx_edge[i];
        st_val[19 + i] = hyb_slots >= 2 ? tx_val[2][i] : tx_val[1][18];   /* (slot 3 off: SD left free) */
    }
}
static void put_stream(u16 t0)
{
    u16 now = TM0CNT_L;
    if ((s16)(now + 64 - t0) > 0) t0 = now + 64;             /* overdue: the whole schedule later, never squeezed
                                                                (64: time to reach the first edge, so it goes out as late as the rest) */
    u16 *late = tx_late[1];                                  /* (tx_late[1] and [2] in a row: 38 entries) */
    for (u32 i = 0; i < 2 * 19; i++) {
        u16 t = t0 + st_at[i];
        while ((s16)(TM0CNT_L - t) < 0) ;
        RCNT = st_val[i];
        late[i] = TM0CNT_L - t;
    }
    rc = st_val[2 * 19 - 1];
    tx_sent |= 6;
}

static void put_word(u16 t0, u32 k)       /* slot k's word on SD, made ahead: start, 16 bits, stop; SD released */
{
    u16 *late = tx_late[k];
    const u16 *val = tx_val[k];
    for (u32 i = 0; i < 19; i++) {
        u16 t = t0 + tx_edge[i];
        while ((s16)(TM0CNT_L - t) < 0) ;
        RCNT = val[i];
        late[i] = TM0CNT_L - t;
    }
    rc = val[18];
    tx_sent |= 1u << k;
}

static u32 word_read;
static u16 late_at[17];                   /* how late each sample of the last word came (the sums after it) */
static inline u32 sample_at(u16 te, u32 k256, u32 i)   /* SD at that point of a word; the time taken noted */
{
    u16 at = at_bit(te, k256);
    until(at);
    u32 v = RCNT & P_SD;
    late_at[i] = tnow() - at;
    return v;
}

static void lateness(void)                 /* after a word, nothing waiting: the sums over its samples */
{
    if (!game_on) return;
    for (u32 i = 0; i < 17; i++) {
        if (late_at[i] > late_max) { late_max = late_at[i]; late_bit = i; }
        if (late_at[i] > 48) late_bad++;                     /* a third of a bit: the reading is in doubt */
    }
}

static u32 get_word(u16 from, u16 *end)   /* the game's word off SD: 0xFFFF if it never starts */
{
    u16 limit = at_bit(from, 12 << 8);
    while (RCNT & P_SD)
        if ((s16)(tnow() - limit) >= 0) { timeouts++; timeouts2 += game_on; return 0xFFFF; }
    u16 te = tnow(), d = te - from;
    if (d < edge_min) edge_min = d;
    if (d > edge_max) edge_max = d;
    if (game_on) { if (d < edge_min2) edge_min2 = d; if (d > edge_max2) edge_max2 = d; }
    u32 w = 0;
    for (u32 i = 0; i < 16; i++)
        if (sample_at(te, (i << 8) + 384, i)) w |= 1u << i; /* the middle of bit i (after a start bit) */
    u32 stop_ok = sample_at(te, 17 * 256 + 128, 16);
    if (!stop_ok) { stop_errors++; stop2 += game_on; }
    *end = at_bit(te, 18 << 8);
    word_read = 1;
    words_ok++;
    words2 += game_on;
    return w;
}

static u16 words[4];
static void transfer(const u16 *mine)     /* one multi-player transfer, the DUO the master */
{
    u16 saved_ime = REG_IME;
    REG_IME = 0;
    u16 dma[4];
    for (u32 k = 0; k < 4; k++) {                            /* a running DMA stalls the CPU mid-bit: pause it */
        dma[k] = DMACNT_H(k);
        if (dma[k] & 0x8000) {
            dma_seen |= (1u << k) | (u32)(dma[k] >> 12 & 3) << (8 + 2 * k);
            DMACNT_H(k) = dma[k] & ~0x8000;
        }
    }
    prepare_word(0, mine[0], GP | OUT(P_SC | P_SO) | P_SO);   /* (SC low, SO high, as they'll be) */
    prepare_word(1, mine[2], GP | OUT(P_SC | P_SO));         /* (SC low, SO low) */
    prepare_word(2, mine[3], GP | OUT(P_SC | P_SO));
    if (PLAYERS >= 3) prepare_stream();
    if (SCOPE == 2) {
        /* the hybrid (16 November): the scope showed the DUO's own link hardware sending slot 0 just as
         * lab4p does by hand - yet the game takes the hardware's 0x8FFF at once and never lab4p's. So
         * here the hardware sends slot 0, the DUO reads the game's word off RCNT (which shows the pins in
         * this mode too), then takes the pins in general-purpose mode, SC still low, for slots 2 and 3 */
        for (u32 i = 0; i < 20000 && (SIOCNT & 0x80); i++) ;           /* (the last one's timeout over) */
        RCNT = 0; rc = 0;
        SIOCNT = 0x2003;
        SIOMLT_SEND = mine[0];
        u16 t0 = tnow();
        SIOCNT = 0x2083;                                     /* the hardware's transfer: SC low, slot 0 */
        while (!(RCNT & P_SO) && (u16)(tnow() - t0) < 400) ;
        while ((RCNT & P_SO) && (u16)(tnow() - t0) < 4000) ;              /* SO low: its word is done */
    } else {
        if (lead)
            set_pins(GP | OUT(P_SC | P_SO) | P_SO);          /* SC low: busy; SO high */
        else
            set_pins(GP | OUT(P_SC | P_SO | P_SD) | P_SO);   /* SC low and the start bit at once */
        u16 t = tnow() + lead;
        put_word(t, 0);
        set_pins(rc & ~P_SO);                                /* SO low: the game's turn */
    }
    words[0] = mine[0];
    u16 end = tnow();
    if (SCOPE == 2 && PLAYERS >= 3) {
        /* 16 November, evening: slots 2 and 3 came too long after the game's word (over 500 cycles at
         * the GBA's real speed, the DUO reading the game's bits and then getting ready), past the time a
         * GBA's link hardware waits for the next unit (the scope: about 570 cycles) - so the game took
         * them for missing and counted two players. The link hardware reads the game's word itself; the
         * DUO needs only its start bit: slot 2 is due 18 bits and the gap after it, and there's the whole
         * of the game's word to get ready in. The schedule's first edge takes the pins. */
        u16 limit = at_bit(end, 12 << 8);
        u32 seen = 1;
        while (RCNT & P_SD)
            if ((s16)(tnow() - limit) >= 0) { seen = 0; break; }
        u16 te = tnow();
        words[2] = words[3] = 0xFFFF;
        if (seen) {
            u16 d = te - end;
            if (d < edge_min) edge_min = d;
            if (d > edge_max) edge_max = d;
            if (game_on) { if (d < edge_min2) edge_min2 = d; if (d > edge_max2) edge_max2 = d; }
            u32 gap = hyb_gap;
            /* the game's word, as the link hardware read it: just after its stop bit, before the pins are
             * taken (16 November, evening: read after, it was stale - the handshake every time, so the DUO
             * thought the game never linked and went back, over and over: "Please wait") */
            until(at_bit(te, (18 << 8) + 32));
            u16 hw1 = SIOMULTI(1);
            u16 give_up = at_bit(te, (18 << 8) + 192);
            while (hw1 == 0xFFFF && (s16)(tnow() - give_up) < 0) hw1 = SIOMULTI(1);
            put_stream(at_bit(te, (18 << 8) + (gap << 6)));  /* slots 2 and 3; the first edge takes the pins */
            words[2] = mine[2];
            words[3] = hyb_slots >= 2 ? mine[3] : 0xFFFF;
            hw_used++;
            if (hw1 == 0xFFFF) hw_differ++;                  /* (not there in time: counted, shown as no answer) */
            words[1] = hw1;
            if (hw1 != 0xFFFF) { words_ok++; words2 += game_on; }
        } else {
            timeouts++; timeouts2 += game_on;
            words[1] = 0xFFFF;
            set_pins(GP | OUT(P_SC | P_SO));
        }
    } else
        words[1] = get_word(end, &end);
    if (!(SCOPE == 2 && PLAYERS >= 3)) words[2] = words[3] = 0xFFFF;
    if (SCOPE == 2 && PLAYERS >= 3) { }
    else if (SCOPE == 2) {                                   /* the control: the hardware ends its own transfer */
        for (u32 i = 0; i < 20000 && (SIOCNT & 0x80); i++) ;
        u16 hw1 = SIOMULTI(1);
        if (hw1 != words[1]) { hw_differ++; if (hw_differ <= 16) log_event(E_STOPBIT, words[1] ^ hw1); }
        hw_used++;
        words[1] = hw1;
    }
    if (SCOPE == 2 && PLAYERS >= 3) { }                     /* (slots 2 and 3 went above) */
    else if (PLAYERS >= 3 && words[1] != 0xFFFF) {
        u32 gap = GAP_Q ? GAP_Q : 4;
        u16 t2 = at_bit(end, gap << 6);
        put_stream(t2);                                      /* slots 2 and 3: one schedule, never squeezed */
        words[2] = mine[2];
        words[3] = mine[3];
    } else {
        until(at_bit(end, 3 << 8));                          /* (the timeout after the last unit) */
    }
    set_pins(GP | OUT(P_SC | P_SO) | P_SC | P_SO);          /* SC high, SO high: done */
    if (game_on) { sd_checks++; if (!(RCNT & P_SD)) sd_low_after++; }   /* SD idle: pulled up by the game, high */
    if (word_read) { word_read = 0; lateness(); }
    tx_tally();
    for (u32 k = 0; k < 4; k++)                              /* the paused DMAs back as they were */
        if (dma[k] & 0x8000 && dma[k] >> 12 & 3)             /* (never restart an immediate one: it would run again) */
            DMACNT_H(k) = dma[k];
    REG_IME = saved_ime;
}

/* ------------------------------------------------------------------ the link above the bits */
enum { ST_WAITING, ST_HANDSHAKE, ST_LINKED, ST_PLAYERS, ST_CLOSING, ST_DONE };
static u32 state, transfers, sessions, stop_requested, hs_seen, players_seen, close_pending, close_at;
static u32 sum_two, sum_four, ck_game_two, ck_game_four, ck_neither, cycles, link_sent, sum_three, ck_game_three;
static u16 game_first[8];
static u32 send_idx, recv_idx;
static u16 frame[CMD_LEN][4];
static u16 cur[4][CMD_LEN];               /* each of our slots' command this cycle */
static u8 lp[3][60];                      /* our link players */
static u32 tx_off[4], tx_on[4], tx_hdr[4];
/* 16 November, evening (hardware: the control's link was clean - 1916 checksums of 1916 - yet the game
 * gave a link error after the link players, and never sent a room key). In the Trade Center the
 * leader then asks for the trainer cards (0xCCCC 2), every player answering it, the leader too, and
 * only then do both go into the room, where each sends its keys every frame (0xCAFE). The trade
 * program does all this as leader; lab4p never asked, so the game waited, then gave up. Now lab4p does
 * the same, its blocks blank: enough to stand in the room. */
static u32 tx_len[4], tx_blank[4];        /* a slot's block: its length; 1: blank (zeros), else its link player */
static u32 game_version, lp_type, req_timer, req_sent, room_keys, ready_pending, blocks_got;
static void queue_block(u32 slot, u32 len, u32 blank)
{
    tx_len[slot] = len; tx_blank[slot] = blank; tx_on[slot] = 1; tx_off[slot] = 0; tx_hdr[slot] = 0;
}
static void answer_request(u32 n)         /* 0xCCCC n: each of our slots sends a blank block of that size */
{
    u32 len = n == 2 ? 100 : n == 3 ? 220 : n == 4 ? 40 : 200;
    queue_block(0, len, 1);
    if (PLAYERS >= 3) { queue_block(2, len, 1); queue_block(3, len, 1); }
}
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
    u32 len = tx_len[slot] ? tx_len[slot] : 60;
    if (!tx_hdr[slot]) { c[0] = 0xBBBB; c[1] = len; c[2] = slot + 128; tx_hdr[slot] = 1; return; }
    c[0] = 0x8888;
    for (u32 j = 0; j < 7; j++) {
        u32 at = tx_off[slot] + 2 * j;
        if (!tx_blank[slot])
            c[1 + j] = (at < len ? lp[k][at] : 0) | (at + 1 < len ? lp[k][at + 1] : 0) << 8;
    }
    tx_off[slot] += 14;
    if (tx_off[slot] >= len) tx_on[slot] = 0;
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
        return;
    }
    if (game_closing || tx_on[0]) return;
    if (ready_pending) { cur[0][0] = 0x2FFE; ready_pending = 0; return; }   /* "ready": we are */
    if (room_keys) { cur[0][0] = 0xCAFE; cur[0][1] = 17; return; }        /* in the room: standing still */
    if (lp_type == 0x1133 && !players_pending && !req_sent && ++req_timer > 40) {
        cur[0][0] = 0xCCCC; cur[0][1] = 2;                   /* the trainer cards, please (as the leader asks) */
        req_sent = 1;
        answer_request(2);                                   /* (our own request: we answer it too) */
        log_event(E_SESSION, 0xCC02);
    }
}

static void game_command(void)
{
    u16 c = frame[0][1];
    if (c && c != 0x8888 && c != 0xCAFE) log_event(E_COMMAND, c);   /* (room keys: every frame, not logged) */
    if (c == 0x2222 || frame[0][0] == 0x2222) {               /* everyone sends a link player: ours once the game's is here */
        players_pending = 1;
        if (state < ST_PLAYERS) state = ST_PLAYERS;
    }
    if (c == 0xCCCC) answer_request(frame[1][1]);
    if (c == 0xCAFE && !room_keys) { room_keys = 1; log_event(E_SESSION, 0xCAFE); }
    if (c == 0x2FFE) ready_pending = 1;
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
            blocks_got++;
            if (players_pending && rx_size == 60) {               /* the game's version and language in ours */
                lp_type = game_block[16 + 0x14] | game_block[16 + 0x15] << 8;
                game_version = game_block[16];
                build_players();
                for (u32 k = 0; k < 4; k++) { tx_on[k] = k != 1; tx_off[k] = 0; tx_hdr[k] = 0; tx_len[k] = 60; tx_blank[k] = 0; }
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
    if (!game_on && words[1] != 0 && words[1] != 0xFFFF) game_on = 1;   /* (the game's GBA is on: its first real word) */
    if (game_on && logged2 < 32) { logged2++; log_event(E_WORD, words[1]); }
    if ((words[1] & ~3) == SLAVE_HS) { hs_reads++; if (++hs_run > hs_run_best) hs_run_best = hs_run; } else hs_run = 0;
    if (state < ST_LINKED && hs_seen && taken_setting == 0xFF) {   /* the game quiet with this setting: the next */
        if (words[1] != 0xFFFF) silent_run = 0;
        else if (++silent_run >= 150) sweep_next(0x100);
    }
    if (state < ST_LINKED) {
        static u32 prev, seen_all;
        u32 n = 0;
        for (u32 i = 0; i < 4; i++) {
            if ((words[i] & ~3) == SLAVE_HS || words[i] == MASTER_HS) n++;
            else break;
        }
        if (n > 1 && state < ST_HANDSHAKE) state = ST_HANDSHAKE;
        if (n > 1 && n == prev && words[0] == MASTER_HS) {    /* the handshake done, as DoHandshake sees it */
            players_seen = n; hs_seen++; hs_tries++; confirm = 1;
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
    if (confirm == 1) {
        /* the first transfer after the handshake: the game's word is still its handshake even when it
         * took ours - link.c's DoHandshake loads SIOMLT_SEND with 0xB9A0 *before* it decides, so the
         * transfer after it says yes carries it once more (15 November: taking that for a miss sent
         * the DUO back about a thousand times, until timing let one through). So this transfer is
         * the checksum slot as usual, and the next one says. */
        confirm = 3; hs_like_count = 0;
    } else if (confirm >= 3) {                               /* the next three: did the game take it? */
        hs_like_count += hs_like(words[1]);
        if (hs_tries <= 12) log_event(E_WORD, words[1]);
        if (++confirm == 6) {
            if (hs_like_count >= 2) {                        /* no: still its handshake. Back to the handshake */
                confirm = 2; state = ST_HANDSHAKE; send_idx = CMD_LEN; recv_idx = 0;
                log_event(E_HANDSHAKE, 0x100 | (hs_tries & 0xFF));
                if (taken_setting == 0xFF && ++sweep_tries >= 3) {   /* the next sending timing */
                    if (SCOPE == 2 && sweep_at < N_HYB && !hyb_out[sweep_at]) hyb_out[sweep_at] = 1;
                    sweep_next(0);
                }
                return;
            }
            confirm = 0;
            if (!hs_taken_after) { hs_taken_after = hs_tries; taken_setting = sweep_at; }
        }
    }
    if (send_idx == 0) {                                     /* the checksum slot just went */
        if (cycles > 1) {
            u16 g = words[1];
            /* which slots the game summed: only where the sums differ (slots 2 and 3 often send zeros, and
             * then two, three and four slots sum alike) */
            u16 s2 = sum_two, s3 = sum_three, s4 = sum_four;
            u8 o = 0;
            if (g == s4 && s4 != s3 && s4 != s2) { ck_game_four++; o = 4; }
            else if (g == s3 && s3 != s4 && s3 != s2) { ck_game_three++; o = 3; }   /* (slot 2 alone, read) */
            else if (g == s2 && s2 != s3 && s2 != s4) { ck_game_two++; o = 2; }
            else if (g != s2 && g != s3 && g != s4) ck_neither++;
            if (SCOPE == 2 && taken_setting < N_HYB && o && !hyb_out[taken_setting]) hyb_out[taken_setting] = o;
            if (g != (u16)sum_four && ck_game_two + ck_neither <= 8) log_event(E_CHECKSUM, g ^ (u16)sum_four);
        }
        sum_two = sum_four = sum_three = 0;
    } else {
        for (u32 i = 0; i < 4; i++) frame[recv_idx][i] = words[i];
        sum_two += words[0] + words[1];
        sum_three += words[0] + words[1] + words[2];
        sum_four += words[0] + words[1] + words[2] + words[3];  /* (as a four-player game sums: 0xFFFF data too) */
        if (++recv_idx == CMD_LEN) { game_command(); recv_idx = 0; }
    }
}

static void our_words(u16 *mine)          /* what our slots send in the next transfer */
{
    if (state < ST_LINKED) {
        static u32 sent;
        u32 ready = words[1] != 0xFFFF && (words[1] & ~3) == SLAVE_HS;
        /* the game's handshake about 20 times (not 20 in a row: on hardware, 12 November, the reads were
         * patchy and a run of 20 never came), then ours as master */
        sent = ready ? sent + 1 : sent > 2 && sent < 20 ? sent - 2 : sent >= 20 ? sent : 0;
        static u32 retry_plain;
        if (confirm == 2) { confirm = 0; retry_plain = 1; }      /* the game missed it: back, one plain transfer first */
        mine[0] = sent >= 20 && !retry_plain ? MASTER_HS : SLAVE_HS;
        retry_plain = 0;
        mine[2] = SLAVE_HS | 2; mine[3] = SLAVE_HS | 3;
        return;
    }
    if (send_idx == 0) { next_cycle(); cycles++; }
    if (send_idx == CMD_LEN) {                               /* the checksum: our sum over the slots we count */
        u16 ck = PLAYERS >= 3 ? (SCOPE == 2 && hyb_slots < 2 ? sum_three : sum_four) : sum_two;
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
    if (pkt[3] == 0x2B) { api->reply(0x2B, state | transfers << 8); stop_requested = 1; if (!done_why) done_why = 3; return 1; }
    if (pkt[3] == 0x2C) {
        if (put_at < BLOB_MAX / 4) blob_words[put_at++] = arg;
        api->reply(0x2C, put_at);
        return 0;
    }
    switch (arg & 0xFF) {
    case 0: v = state | (sessions & 3) << 6 | (transfers & 0xFFFFFF) << 8; break;
    case 1: v = words_ok | timeouts << 16; break;
    case 2: v = stop_errors | players_seen << 16 | (hs_seen & 0x7F) << 24 | not_master << 31; break;
    case 3: v = edge_min | edge_max << 16; break;
    case 4: v = 4 * idx + 3 < log_len ? ((u32 *)LOG)[idx] : 0; break;
    case 5: v = log_len | log_full << 31; break;
    case 6: v = game_first[0] | game_first[1] << 16; break;
    case 7: v = (ck_game_two & 0xFFFF) | ck_game_four << 16; break;
    case 8: v = ck_neither | cycles << 16; break;
    case 9: v = game_version | lp_type << 8; break;          /* (kept: the trainer card's block comes after) */
    case 10: v = (words2 & 0xFFFF) | stop2 << 16; break;                 /* from the game's first real word */
    case 11: v = (timeouts2 & 0xFFFF) | (hs_reads & 0xFFFF) << 16; break;
    case 12: v = (edge_min2 & 0xFFFF) | edge_max2 << 16; break;
    case 13: v = hs_run_best; break;
    case 14: v = sd_low_after; break;                        /* SD read low just after we let go of it... */
    case 15: v = sd_checks; break;                           /* ...out of so many (the PC works out the share) */
    case 16: v = dma_seen; break;                            /* DMA channels found running: bits 0-3, timings 8-15 */
    case 17: v = (late_max & 0xFFFF) | late_bit << 16; break;   /* the latest sample (cycles) and its bit (16: stop) */
    case 18: v = late_bad; break;                            /* samples a third of a bit late or more */
    case 19: v = done_why; break;                            /* 1 not master, 2 the game closed, 3 asked to stop */
    case 22: v = hs_tries | hs_taken_after << 16; break;     /* 0x8FFF sent so many times; taken on try N (0: never) */
    case 27: v = hw_used | hw_differ << 16; break;
    case 29: v = room_keys | req_sent << 1 | (blocks_got & 0xFF) << 8 | (lp_type & 0xFFFF) << 16; break;
    case 28: v = tx_late_max | tx_late_bit << 16 | (tx_late_bad > 255 ? 255 : tx_late_bad) << 24; break;
    case 25: v = scope_n | scope_words << 16; break;
    case 26: v = scope_hs | scope_taken << 16; break;
    case 30: v = ck_game_three; break;
    case 32: v = 0; for (u32 k = 0; k < 8; k++) v |= (u32)(hyb_out[k] & 15) << (4 * k); break;
    case 33: v = 0; for (u32 k = 8; k < 16; k++) v |= (u32)(hyb_out[k] & 15) << (4 * (k - 8)); break;
    case 31: { u32 k = idx < N_HYB ? idx : 0; v = (u16)HYB[k][0] | (u32)(HYB[k][1] & 0xFFF) << 16 | (u32)HYB[k][2] << 28; } break;
    case 23: v = taken_setting | sweep_at << 8 | (SCOPE == 2 ? N_HYB : N_SWEEP) << 16; break;   /* the sending timing that worked (0xFF: none) */
    case 24: v = (u16)SWEEP[idx][0] | (u32)(u16)SWEEP[idx][1] << 16; break;
    case 20: put_at = 0; blob_ready = 0; v = BLOB_MAX; break;
    case 21: v = api->crc32(blob_words, put_at * 4);
             blob_ready = put_at * 4 >= BLOB_MAX && (PLAYERS == 1 || PLAYERS == 3);
             if (blob_ready) { log_len = log_full = log_seq = 0; bit_fp = (145 << 8) + 163 + (signed char)BIT_ADJ; sweep_apply(); }
             break;
    default: v = 0xFFFFFFFF; break;
    }
    api->reply(0x2A, v);
    return 0;
}

/* ------------------------------------------------------------------ the scope (16 November)
 * Every sending timing the DUO tried by hand, the game missed. So this one asks the real thing: the
 * DUO's own multi-player hardware is the master (as the trade program, which works on hardware), and
 * while it runs a transfer the DUO watches the lines as fast as it can - SIOCNT's SI and SD bits and
 * its busy bit, and RCNT's four (if they show the pins in this mode) - noting each change against
 * timer 0. That is how a GBA master's word looks on SD, start bit to stop bit, and when the game's
 * answer follows it: the pattern to copy. The words the hardware read are kept too, and whether the
 * game took the hardware's 0x8FFF: the control for the cable and the game. */
static void scope_transfer(void)
{
    u16 saved_ime = REG_IME;
    REG_IME = 0;
    RCNT = 0;                                                /* the link port to the serial hardware */
    SIOCNT = 0x2003;                                         /* multi-player, 115,200 baud, no interrupt */
    SIOMLT_SEND = MASTER_HS;
    u8 buf[4 + 64 * 3];
    u32 n = 0, last = 0x100, done_at = 0;
    u16 t0 = tnow();
    SIOCNT = 0x2083;                                         /* start */
    for (;;) {
        u16 sc = SIOCNT, r = RCNT, t = tnow() - t0;
        u32 v = (sc >> 2 & 3) | (sc >> 5 & 4) | (sc >> 3 & 8) | (r & 0xF) << 4;   /* SI SD busy error | RCNT */
        if (v != last && n < 64) { buf[4 + 3 * n] = t; buf[5 + 3 * n] = t >> 8; buf[6 + 3 * n] = v; n++; }
        last = v;
        if (!(sc & 0x80)) { if (!done_at) done_at = t ? t : 1; else if ((u16)(t - done_at) > 600) break; }
        if (t > 30000) break;
    }
    u16 w1 = SIOMULTI(1);
    if (w1 != 0xFFFF) scope_words++;
    if ((w1 & ~3) == SLAVE_HS) scope_hs++;
    else if (w1 != 0xFFFF && scope_hs && !scope_taken) scope_taken = scope_n + 1;
    if (scope_n < 40 || (w1 & ~3) != SLAVE_HS) {             /* the first forty, and any that isn't a handshake */
        if (log_len < LOG_MAX - 0x400) {
            buf[0] = scope_n; buf[1] = scope_n >> 8; buf[2] = w1; buf[3] = w1 >> 8;
            log_bytes(buf, 4 + 3 * n, K_SCOPE);
        }
    }
    scope_n++;
    REG_IF = 0x80;
    REG_IME = saved_ime;
}

/* ------------------------------------------------------------------ entry */
__attribute__((section(".text.start")))
u32 start(api_t *api)
{
    u16 saved_ie = REG_IE, saved_rcnt = RCNT, saved_siocnt = SIOCNT, saved_tm = TM0CNT_H;
    TM0CNT_H = 0; TM0CNT_L = 0; TM0CNT_H = 0x80;              /* timer 0: the CPU clock, free-running */
    bit_fp = (145 << 8) + 163;
    sweep_apply();
    last_vcount = VCOUNT & 0xFF;
    u32 next = now(), in_cycle = 0, idle_set = 0;
    while (!stop_requested) {
        pc_service(api);
        if (!blob_ready) continue;
        if (!idle_set) {                                     /* SC and SO high, SD an input: idle, as a master */
            idle_set = 1;
            set_pins(GP | OUT(P_SC | P_SO) | P_SC | P_SO);
            /* (the master's SI is held low; 15 November: one high reading in a thousand stopped a run at
             * once, and the next run was fine - so most readings, not any) */
            u32 high = 0;
            for (u32 i = 0; i < 1000; i++) high += !!(RCNT & P_SI);
            not_master = high > 500;
            if (not_master) { api->log("4P lab: the DUO isn't master"); state = ST_DONE; done_why = 1; }
        }
        if (shown != state && (state < ST_HANDSHAKE || state == ST_DONE)) {   /* (a line costs a frame: never while linked) */
            shown = state;
            api->log(SAY[state < 6 ? state : 5]);
            if (state == ST_WAITING && LABEL[0]) api->log(LABEL);
        }
        if (state == ST_DONE) continue;
        u32 t = now();
        if (SCOPE == 1) {                                    /* (one transfer a frame, as link.c's master) */
            if ((int)(t - next) < 0) continue;
            next = t + LINES_PER_FRAME;
            scope_transfer();
            if (state == ST_WAITING) state = ST_HANDSHAKE;
            continue;
        }
        /* the pace of link.c's master (pret:pokeruby/src/link.c:1615 LinkVSync): one transfer a frame until
         * linked, then a command of nine transfers a frame, eight lines apart. Scheduled from the last
         * time, not from when the DUO noticed (17 November, the simulator with link.c ported: from
         * when it noticed, each frame ran a little long, the game - which queues a command every
         * frame in the Trade Center room - got ahead, and its queue filled: a link error) */
        if ((int)(t - next) < 0) continue;
        if ((int)(t - next) > 2 * LINES_PER_FRAME) next = t;      /* (far behind: start again from now) */
        if (state < ST_LINKED) next += LINES_PER_FRAME;
        else if (++in_cycle < 9) next += 8;
        else { in_cycle = 0; next += LINES_PER_FRAME - 8 * 8; }
        u16 mine[4] = { 0, 0, 0, 0 };
        our_words(mine);
        transfer(mine);
        on_words();
        if (game_closing && !close_pending) { close_pending = 1; close_at = now(); }
        if (close_pending && now() - close_at > 30 * LINES_PER_FRAME) { state = ST_DONE; done_why = 2; }
    }
    RCNT = saved_rcnt;
    SIOCNT = saved_siocnt;
    REG_IF = 0x80;
    REG_IE = saved_ie;
    TM0CNT_H = saved_tm;
    return state | transfers << 8;
}
