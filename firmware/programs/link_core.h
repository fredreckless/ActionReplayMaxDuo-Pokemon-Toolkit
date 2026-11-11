/* link_core.h - what the two-player link programs share (11 November 2026): the types, the DUO's
 * API, the serial registers and the link's constants, and the line clock. Included at the top of
 * blender.c and contest.c; link_tail.h, at their end, has the link layer and the entry. A fix here
 * reaches both. (Each program is still built on its own, so this saves no space in either.) */
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
