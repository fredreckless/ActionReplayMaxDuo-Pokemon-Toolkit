/* mbsend.c - the DUO's GBA sends a multiboot program over the link cable to a GBA with no cartridge
 * in (19 November 2026; docs/MULTIBOOT.md, path A). This is how Emerald's Berry Fix screen sends its
 * program to a Ruby or Sapphire player's GBA (pret:pokeemerald/src/berry_fix_program.c:246 MultiBootStartMaster(&sBerryFix->mb,),
 * and FireRed/LeafGreen's the same.
 *
 * Nothing in the protocol is ours. The handshake below is pret's port of Nintendo's own library,
 * pokeemerald src/multiboot.c, function for function (each cited), driven as berry_fix_program.c
 * drives it: once a frame, the program started once one GBA has answered steadily for 180 frames,
 * palette colour 4, speed 1. The transfer itself is the DUO's own GBA BIOS (SWI 25h, MultiBoot),
 * as it is the game's. The receiving GBA runs its own BIOS. So on hardware every word on the cable
 * is made by the same code as when Emerald sends. Our part is only where the program comes from:
 * the PC loads it from the user's own file (never from this toolkit) into the firmware's
 * save-transfer buffer, which nothing uses while a program runs.
 *
 * The DUO's GBA must be the master (the cable's purple plug, SI low): MultiBoot checks for that
 * itself and reports an error otherwise (MultiBootSend). Nothing is written to any cartridge here;
 * what the received program does on the other GBA is its own business. */
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef signed char s8;

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
#define REG_SIOMULTI(i) REG16(0x04000120 + 2 * (i))
#define REG_SIOCNT      REG16(0x04000128)
#define REG_SIODATA8    REG16(0x0400012A)
#define REG_RCNT        REG16(0x04000134)
#define REG_IE          REG16(0x04000200)
#define REG_IF          REG16(0x04000202)
#define VCOUNT          REG16(0x04000006)

/* pokeemerald include/gba/io_reg.h */
#define SIO_MULTI_MODE  0x2000
#define SIO_115200_BPS  0x0003
#define SIO_MULTI_SI    0x0004
#define SIO_MULTI_SD    0x0008
#define SIO_MULTI_BUSY  0x0080
#define SIO_START       0x0080
#define SIO_ERROR       0x0040
#define SIO_ID          0x0030

/* pret:pokeemerald/include/gba/multiboot.h:4 #define MULTIBOOT_NCHILD        3       // Maximum number of slaves */
#define MULTIBOOT_NCHILD        3
#define MULTIBOOT_HEADER_SIZE   0xc0
#define MULTIBOOT_SEND_SIZE_MIN 0x100
#define MULTIBOOT_SEND_SIZE_MAX 0x40000
#define MULTIBOOT_ERROR_NO_PROBE_TARGET   0x50
#define MULTIBOOT_ERROR_NO_DLREADY        0x60
#define MULTIBOOT_ERROR_BOOT_FAILURE      0x70
#define MULTIBOOT_ERROR_HANDSHAKE_FAILURE 0x71
#define MULTIBOOT_CONNECTION_CHECK_WAIT 15
#define MULTIBOOT_SERVER_TYPE_NORMAL 0
#define MULTIBOOT_SERVER_TYPE_QUICK  1
#define MULTIBOOT_HANDSHAKE_TIMEOUT 400

/* pret:pokeemerald/include/multiboot.h:4 #define MULTIBOOT_MASTER_INFO            0x62 */
#define MULTIBOOT_MASTER_INFO            0x62
#define MULTIBOOT_CLIENT_INFO            0x72
#define MULTIBOOT_MASTER_START_PROBE     0x61
#define MULTIBOOT_MASTER_REQUEST_DLREADY 0x63
#define MULTIBOOT_CLIENT_DLREADY         0x73
#define MULTIBOOT_MASTER_START_DL        0x64

/* pret:pokeemerald/include/gba/multiboot.h:9 struct MultiBootParam - the BIOS reads this block (SWI 25h) */
struct MultiBootParam
{
    u32 system_work[5]; // 00
    u8 handshake_data;  // 14
    u16 handshake_timeout; // 16
    u8 probe_count; // 18
    u8 client_data[MULTIBOOT_NCHILD]; // 19
    u8 palette_data; // 1c
    u8 response_bit; // 1d
    u8 client_bit; // 1e
    u8 reserved1; // 1f
    const u8 *boot_srcp; // 20
    const u8 *boot_endp; // 24
    const u8 *masterp;
    u8 *reserved2[MULTIBOOT_NCHILD];
    u32 system_work2[4];
    u8 sendflag;
    u8 probe_target_bit;
    u8 check_wait;
    u8 server_type;
};

/* ------------------------------------------------------------------ the BIOS call */
/* pret:pokefirered/src/libagbsyscall.s:52 movs r1, 0x1 - MultiBoot: r1 = 1 (MultiPlay, 115 kbit/s), SWI 25h */
__attribute__((noinline)) static int MultiBoot(struct MultiBootParam *mp)
{
    register struct MultiBootParam *r0 asm("r0") = mp;
    register u32 r1 asm("r1") = 1;
    asm volatile("svc 0x25" : "+r"(r0), "+r"(r1) : : "r2", "r3", "r12", "lr", "memory", "cc");
    return (int)(u32)r0;
}

/* ------------------------------------------------------------------ pokeemerald src/multiboot.c */
static u16 MultiBoot_required_data[MULTIBOOT_NCHILD];

static int MultiBootSend(struct MultiBootParam *mp, u16 data);
static int MultiBootHandShake(struct MultiBootParam *mp);
static void MultiBootWaitCycles(u32 cycles);
static void MultiBootWaitSendDone(void);
static int MultiBootCheckComplete(struct MultiBootParam *mp);
static void MultiBootStartProbe(struct MultiBootParam *mp);

/* pret:pokeemerald/src/multiboot.c:12 void MultiBootInit(struct MultiBootParam *mp) */
static void MultiBootInit(struct MultiBootParam *mp)
{
    mp->client_bit = 0;
    mp->probe_count = 0;
    mp->response_bit = 0;

    mp->check_wait = MULTIBOOT_CONNECTION_CHECK_WAIT;
    mp->sendflag = 0;

    mp->handshake_timeout = 0;

    REG_RCNT = 0;
    REG_SIOCNT = SIO_MULTI_MODE | SIO_115200_BPS;
    REG_SIODATA8 = 0;
}

/* pret:pokeemerald/src/multiboot.c:28 int MultiBootMain(struct MultiBootParam *mp) */
static int MultiBootMain(struct MultiBootParam *mp)
{
    int i;
    int j;
    int k;

    if (MultiBootCheckComplete(mp))
    {
        return 0;
    }

    if (mp->check_wait > MULTIBOOT_CONNECTION_CHECK_WAIT)
    {
        mp->check_wait--;
        return 0;
    }

output_burst:
    if (mp->sendflag)
    {
        mp->sendflag = 0;

        i = REG_SIOCNT & (SIO_MULTI_BUSY | SIO_ERROR | SIO_ID | SIO_MULTI_SD | SIO_MULTI_SI);
        if (i != SIO_MULTI_SD)
        {
            MultiBootInit(mp);
            return i ^ SIO_MULTI_SD;
        }
    }

    if (mp->probe_count >= 0xe0)
    {
        i = MultiBootHandShake(mp);
        if (i)
        {
            return i;
        }

        if (mp->server_type == MULTIBOOT_SERVER_TYPE_QUICK
         && mp->probe_count > 0xe1
         && MultiBootCheckComplete(mp) == 0)
        {
            MultiBootWaitSendDone();
            goto output_burst;
        }

        if (MultiBootCheckComplete(mp) == 0)
        {
            if (mp->handshake_timeout == 0)
            {
                MultiBootInit(mp);
                return MULTIBOOT_ERROR_HANDSHAKE_FAILURE;
            }
            mp->handshake_timeout--;
        }

        return 0;
    }

    switch (mp->probe_count)
    {
    case 0:
        k = 0x0e;
        for (i = MULTIBOOT_NCHILD; i != 0; i--)
        {
            if (REG_SIOMULTI(i) != 0xffff)
            {
                break;
            }
            k >>= 1;
        }

        k &= 0x0e;
        mp->response_bit = k;

        for (i = MULTIBOOT_NCHILD; i != 0; i--)
        {
            j = REG_SIOMULTI(i);
            if (mp->client_bit & (1 << i))
            {
                if (j != ((MULTIBOOT_CLIENT_INFO << 8) | (1 << i)))
                {
                    k = 0;
                    break;
                }
            }
        }

        mp->client_bit &= k;

        if (k == 0)
        {
            mp->check_wait = MULTIBOOT_CONNECTION_CHECK_WAIT;
        }

        if (mp->check_wait)
        {
            mp->check_wait--;
        }
        else
        {
            if (mp->response_bit != mp->client_bit)
            {
                MultiBootStartProbe(mp);
                goto case_1;
            }
        }

    output_master_info:
        return MultiBootSend(mp, (MULTIBOOT_MASTER_INFO << 8) | mp->client_bit);

    case_1:
    case 1:
        mp->probe_target_bit = 0;
        for (i = MULTIBOOT_NCHILD; i != 0; i--)
        {
            j = REG_SIOMULTI(i);
            if ((j >> 8) == MULTIBOOT_CLIENT_INFO)
            {
                MultiBoot_required_data[i - 1] = j;
                j &= 0xff;
                if (j == (1 << i))
                {
                    mp->probe_target_bit |= j;
                }
            }
        }

        if (mp->response_bit != mp->probe_target_bit)
        {
            goto output_master_info;
        }

        mp->probe_count = 2;
        return MultiBootSend(mp, (MULTIBOOT_MASTER_START_PROBE << 8) | mp->probe_target_bit);

    case 2:
        for (i = MULTIBOOT_NCHILD; i != 0; i--)
        {
            if (mp->probe_target_bit & (1 << i))
            {
                j = REG_SIOMULTI(i);
                if (j != MultiBoot_required_data[i - 1])
                {
                    mp->probe_target_bit ^= 1 << i;
                }
            }
        }
        goto output_header;

    case 0xd0:
        k = 1;
        for (i = MULTIBOOT_NCHILD; i != 0; i--)
        {
            j = REG_SIOMULTI(i);
            mp->client_data[i - 1] = j;
            if (mp->probe_target_bit & (1 << i))
            {
                if ((j >> 8) != MULTIBOOT_CLIENT_INFO
                 && (j >> 8) != MULTIBOOT_CLIENT_DLREADY)
                {
                    MultiBootInit(mp);
                    return MULTIBOOT_ERROR_NO_DLREADY;
                }
                if (j == MultiBoot_required_data[i - 1])
                {
                    k = 0;
                }
            }
        }

        if (k == 0)
        {
            return MultiBootSend(mp, (MULTIBOOT_MASTER_REQUEST_DLREADY << 8) | mp->palette_data);
        }

        mp->probe_count = 0xd1;

        k = 0x11;
        for (i = MULTIBOOT_NCHILD; i != 0; i--)
        {
            k += mp->client_data[i - 1];
        }
        mp->handshake_data = k;
        return MultiBootSend(mp, (MULTIBOOT_MASTER_START_DL << 8) | (k & 0xff));

    case 0xd1:
        for (i = MULTIBOOT_NCHILD; i != 0; i--)
        {
            j = REG_SIOMULTI(i);
            if (mp->probe_target_bit & (1 << i))
            {
                if ((j >> 8) != MULTIBOOT_CLIENT_DLREADY)
                {
                    MultiBootInit(mp);
                    return MULTIBOOT_ERROR_NO_DLREADY;
                }
            }
        }

        i = MultiBoot(mp);

        if (i == 0)
        {
            mp->probe_count = 0xe0;
            mp->handshake_timeout = MULTIBOOT_HANDSHAKE_TIMEOUT;
            return 0;
        }
        MultiBootInit(mp);
        mp->check_wait = MULTIBOOT_CONNECTION_CHECK_WAIT * 2;
        return MULTIBOOT_ERROR_BOOT_FAILURE;

    default:
        for (i = MULTIBOOT_NCHILD; i != 0; i--)
        {
            if (mp->probe_target_bit & (1 << i))
            {
                j = REG_SIOMULTI(i);
                if ((j >> 8) != (MULTIBOOT_MASTER_START_PROBE + 1 - (mp->probe_count >> 1))
                 || ((j & 0xff) != (1 << i)))
                {
                    mp->probe_target_bit ^= 1 << i;
                }
            }
        }

        if (mp->probe_count == 0xc4)
        {
            mp->client_bit = mp->probe_target_bit & 0x0e;
            mp->probe_count = 0;
            goto output_master_info;
        }

    output_header:
        if (mp->probe_target_bit == 0)
        {
            MultiBootInit(mp);
            return MULTIBOOT_ERROR_NO_PROBE_TARGET;
        }

        mp->probe_count += 2;
        if (mp->probe_count == 0xc4)
        {
            goto output_master_info;
        }
        i = MultiBootSend(mp,
            (mp->masterp[mp->probe_count - 4 + 1] << 8)
            | mp->masterp[mp->probe_count - 4]);

        if (i)
        {
            return i;
        }
        if (mp->server_type == MULTIBOOT_SERVER_TYPE_QUICK)
        {
            MultiBootWaitSendDone();
            goto output_burst;
        }
        return 0;
    }
}

/* pret:pokeemerald/src/multiboot.c:290 static int MultiBootSend(struct MultiBootParam *mp, u16 data) */
static int MultiBootSend(struct MultiBootParam *mp, u16 data)
{
    int i;

    i = REG_SIOCNT & (SIO_MULTI_BUSY | SIO_MULTI_SD | SIO_MULTI_SI);
    if (i != SIO_MULTI_SD)
    {
        MultiBootInit(mp);
        return i ^ SIO_MULTI_SD;
    }

    REG_SIODATA8 = data;
    REG_SIOCNT = SIO_MULTI_MODE | SIO_START | SIO_115200_BPS;

    mp->sendflag = 1;
    return 0;
}

/* pret:pokeemerald/src/multiboot.c:308 void MultiBootStartProbe(struct MultiBootParam *mp) */
static void MultiBootStartProbe(struct MultiBootParam *mp)
{
    if (mp->probe_count != 0)
    {
        MultiBootInit(mp);
        return;
    }
    mp->check_wait = 0;
    mp->client_bit = 0;
    mp->probe_count = 1;
}

/* pret:pokeemerald/src/multiboot.c:320 void MultiBootStartMaster(struct MultiBootParam *mp, const u8 *srcp, int length, u8 palette_color, s8 palette_speed) */
static void MultiBootStartMaster(struct MultiBootParam *mp, const u8 *srcp, int length, u8 palette_color, s8 palette_speed)
{
    int i = 0;

    if (mp->probe_count != 0
     || mp->client_bit == 0
     || mp->check_wait != 0)
    {
        MultiBootInit(mp);
        return;
    }

    mp->boot_srcp = srcp;
    length = (length + 15) & ~15;
    if (length < MULTIBOOT_SEND_SIZE_MIN || length > MULTIBOOT_SEND_SIZE_MAX)
    {
        MultiBootInit(mp);
        return;
    }

    mp->boot_endp = srcp + length;

    switch (palette_speed)
    {
    case -4:
    case -3:
    case -2:
    case -1:
        i = (palette_color << 3) | (3 - palette_speed);
        break;
    case 0:
        i = 0x38 | palette_color;
        break;
    case 1:
    case 2:
    case 3:
    case 4:
        i = (palette_color << 3) | (palette_speed - 1);
        break;
    }

    mp->palette_data = ((i & 0x3f) << 1) | 0x81;
    mp->probe_count = 0xd0;
}

/* pret:pokeemerald/src/multiboot.c:365 int MultiBootCheckComplete(struct MultiBootParam *mp) */
static int MultiBootCheckComplete(struct MultiBootParam *mp)
{
    if (mp->probe_count == 0xe9)
    {
        return 1;
    }

    return 0;
}

/* pret:pokeemerald/src/multiboot.c:375 static int MultiBootHandShake(struct MultiBootParam *mp) */
static int MultiBootHandShake(struct MultiBootParam *mp)
{
    int i, j;

#define send_data (mp->system_work[0])
#define must_data (mp->system_work[1])

    switch (mp->probe_count)
    {
    case_0xe0:
    case 0xe0:
        mp->probe_count = 0xe1;
        must_data = 0x0000;
        send_data = 0x100000;
        return MultiBootSend(mp, 0x0000);

    default:
        for (i = MULTIBOOT_NCHILD; i != 0; i--)
        {
            j = REG_SIOMULTI(i);
            if ((mp->client_bit & (1 << i))
                && j != must_data)
            {
                goto case_0xe0;
            }
        }
        mp->probe_count++;
        must_data = send_data & 0xffff;
        if (send_data == 0x0000)
        {
            must_data = mp->masterp[0xac] | (mp->masterp[0xad] << 8);
            send_data = must_data << 5;
        }
        send_data >>= 5;
    output_common:
        return MultiBootSend(mp, send_data);

    case 0xe7:
    case 0xe8:
        for (i = MULTIBOOT_NCHILD; i != 0; i--)
        {
            j = REG_SIOMULTI(i);
            if ((mp->client_bit & (1 << i)) && j != must_data)
            {
                MultiBootInit(mp);
                return MULTIBOOT_ERROR_HANDSHAKE_FAILURE;
            }
        }

        mp->probe_count++;
        if (mp->probe_count == 0xe9)
        {
            return 0;
        }

        send_data = mp->masterp[0xae] | (mp->masterp[0xaf] << 8);
        must_data = send_data;
        goto output_common;
    }

#undef send_data
#undef must_data
}

/* pret:pokeemerald/src/multiboot.c:440 static void MultiBootWaitCycles(u32 cycles) */
__attribute__((naked)) static void MultiBootWaitCycles(u32 cycles)
{
    asm volatile("\
    mov  r2, pc\n\
    lsrs r2, 24\n\
    movs r1, 12\n\
    cmp  r2, 2\n\
    beq  1f\n\
    movs r1, 13\n\
    cmp  r2, 8\n\
    beq  1f\n\
    movs r1, 4\n\
1:\n\
    subs r0, r1\n\
    bgt  1b\n\
    bx   lr\n");
}

/* pret:pokeemerald/src/multiboot.c:458 static void MultiBootWaitSendDone(void) */
static void MultiBootWaitSendDone(void)
{
    int i;

    for (i = 0; i < 31069; i++)
    {
        if ((REG_SIOCNT & SIO_START) == 0)
        {
            break;
        }
    }

    MultiBootWaitCycles(600);
}

/* ------------------------------------------------------------------ what the PC loads */
#define BLOB_AT     0x02010030          /* build_v4.py BUFFER (0x20000 bytes) */
#define BLOB        ((u8 *)BLOB_AT)
#define IMAGE_LEN   (*(u32 *)BLOB)      /* the whole file: the 0xC0-byte header, then the program */
#define LABEL       ((const char *)BLOB + 8)    /* 28: a line for the screen */
#define IMAGE       (BLOB + 48)         /* (4-byte aligned) */
#define IMAGE_MAX   (0x20000 - 48)
static u32 put_at, blob_ready;
#define blob_words  ((u32 *)BLOB_AT)

/* ------------------------------------------------------------------ the sending, as the Berry Fix screen does it */
enum { ST_LOADING, ST_WAITING, ST_PROBING, ST_READY, ST_SENDING, ST_DONE, ST_FAILED };
static struct MultiBootParam mb;
static u32 state, frames, timer, errors, last_error, stop_requested, boot_calls;

/* pret:pokeemerald/src/berry_fix_program.c:239 MultiBootMain(&sBerryFix->mb); - MAINSTATE_MULTIBOOT and MAINSTATE_TRANSMIT */
static void frame(void)
{
    int r;
    if (state == ST_WAITING || state == ST_PROBING || state == ST_READY) {
        r = MultiBootMain(&mb);
        if (r) { errors++; last_error = r; }
        if (mb.probe_count != 0 || (!(mb.response_bit & 2) || !(mb.client_bit & 2))) {
            timer = 0;
            state = mb.probe_count ? ST_PROBING : ST_WAITING;
        } else if (++timer > 180) {
            MultiBootStartMaster(&mb, IMAGE + MULTIBOOT_HEADER_SIZE, (int)(IMAGE_LEN - MULTIBOOT_HEADER_SIZE), 4, 1);
            state = ST_SENDING;
        } else {
            state = ST_READY;
        }
    } else if (state == ST_SENDING) {
        u32 before = mb.probe_count;
        r = MultiBootMain(&mb);
        if (before == 0xd1) boot_calls++;
        if (r) { errors++; last_error = r; }
        if (MultiBootCheckComplete(&mb))
            state = ST_DONE;
        else if (!(mb.client_bit & 2))
            state = ST_FAILED;
    }
}

static u8 pkt[8];
static int pc_service(api_t *api)
{
    if (!api->avail())
        return 0;
    api->recv8(pkt);
    u32 arg = pkt[4] | pkt[5] << 8 | pkt[6] << 16 | (u32)pkt[7] << 24, v;
    if (pkt[3] == 0x2B) {
        api->reply(0x2B, state | frames << 8);
        stop_requested = 1;
        return 1;
    }
    if (pkt[3] == 0x2C) {
        if (put_at < 0x20000 / 4)
            blob_words[put_at++] = arg;
        api->reply(0x2C, put_at);
        return 0;
    }
    switch (arg & 0xFF) {
    case 0: v = state | (u32)mb.probe_count << 8 | (u32)mb.client_bit << 16 | (u32)mb.response_bit << 24; break;
    case 1: v = last_error | (errors & 0xFF) << 8 | (boot_calls & 0xFF) << 16; break;
    case 2: v = (REG_SIOCNT & SIO_MULTI_SI) ? 0 : 1; break;        /* 1: the DUO's GBA is on the master plug */
    case 3: v = mb.client_data[0] | mb.client_data[1] << 8 | mb.client_data[2] << 16 | (u32)mb.handshake_data << 24; break;
    case 20: put_at = 0; blob_ready = 0; state = ST_LOADING; v = IMAGE_MAX; break;
    case 21: {
        u32 len = IMAGE_LEN, body = len - MULTIBOOT_HEADER_SIZE;
        v = api->crc32(blob_words, put_at * 4);
        blob_ready = len > MULTIBOOT_HEADER_SIZE && len <= IMAGE_MAX && put_at * 4 >= 48 + len
                     && ((body + 15) & ~15) >= MULTIBOOT_SEND_SIZE_MIN && ((body + 15) & ~15) <= MULTIBOOT_SEND_SIZE_MAX;
        if (blob_ready) {
            for (u32 i = len; i < ((len + 15) & ~15u); i++) IMAGE[i] = 0;   /* (the BIOS sends whole 16-byte units) */
            mb.masterp = IMAGE;
            mb.server_type = MULTIBOOT_SERVER_TYPE_NORMAL;               /* sBerryFix->mb.server_type = 0 */
            MultiBootInit(&mb);
            timer = 0; state = ST_WAITING;
            api->log(LABEL);
        }
        break;
    }
    default: v = 0xFFFFFFFF; break;
    }
    api->reply(0x2A, v);
    return 0;
}

u32 start(api_t *api)
{
    u16 saved_ie = REG_IE, saved_rcnt = REG_RCNT, saved_siocnt = REG_SIOCNT;
    REG_IE = saved_ie & ~0x0080;                    /* (no serial interrupt: the library polls) */
    u32 last = VCOUNT & 0xFF;
    while (!stop_requested) {
        u32 v = VCOUNT & 0xFF;
        if (v == 160 && last != 160) {              /* once a frame, at the start of the VBlank */
            frames++;
            if (blob_ready) frame();
        }
        last = v;
        if (v < 150 || v >= 200)                    /* (the PC between frames, not at the frame's edge) */
            pc_service(api);
    }
    REG_SIOCNT = saved_siocnt & ~SIO_START;
    REG_RCNT = saved_rcnt;
    REG_IE = saved_ie;
    return state | frames << 8;
}
