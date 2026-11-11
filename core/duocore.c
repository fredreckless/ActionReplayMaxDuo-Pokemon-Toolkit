/*
 * duocore.c - the MAX DUO's hardware, modelled once (see duocore.h).
 *
 * Sources for each behaviour: docs/FINDINGS.md and docs/HARDWARE.md in the toolkit, and the
 * toolkit's tests/hwsim.py, which this first version reproduces exactly.
 */
#include "duocore.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FLASH_SIZE   0x80000u    /* SST 39VF400A: 512 KB */
#define MIRROR_END   0x100000u   /* the flash appears twice below 1 MB, open bus above */
#define OVERLAY_LO   0x20u       /* the Actel overlays the header in every mode and width */
#define OVERLAY_HI   0xA0u
#define MAPREG_OFF   0x9Cu
#define TURN_PC      0
#define TURN_GBA     1

static const uint8_t MAPREG_READ[4] = {0xF0, 0x0F, 0x00, 0x00};
static const uint8_t FLASH_ID[4] = {0xBF, 0xBF, 0x82, 0x27};   /* SST BF / 2780, as halfwords */
static const uint8_t SAVE_IDS[3][2] = {{0x62, 0x13}, {0xC2, 0x09}, {0xBF, 0xD4}};

struct duo {
    uint8_t flash[FLASH_SIZE];
    uint8_t *game;
    size_t game_len;
    int save_type;
    uint8_t *save;
    size_t save_size;

    /* the Actel */
    uint16_t mapped;            /* 0: the DUO program; else the game map value */
    int flash_id;               /* the DUO's flash is in software-ID mode */
    uint16_t waitcnt;

    /* the game's save chip */
    int awake;
    int bank;
    int id_mode;
    int ncmd;                   /* a Flash command in progress: up to three (offset, value) */
    uint32_t cmd_off[3];
    uint8_t cmd_val[3];
    uint32_t save_writes;
    uint32_t ignored;

    /* the Cypress chip */
    int turn;
};

const char *duo_version(void) { return "duocore 0.1 (matches hwsim.py of 11 November 2026)"; }

/* ------------------------------------------------------------------ helpers */

static void clear(duo_result *r) {
    if (!r) return;
    r->status = DUO_OK;
    r->flags = 0;
    r->rom_lo = r->rom_hi = 0;
    r->cycles = 0;
    r->msg[0] = 0;
}

static void say(duo_result *r, const char *fmt, ...) {
    if (!r) return;
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(r->msg, DUO_MSG, fmt, ap);
    va_end(ap);
}

/* Python's "{:#x}": 0 is "0x0". */
static const char *hx(char *buf, uint32_t v) {
    snprintf(buf, 16, "0x%x", v);
    return buf;
}

static void rom_changed(duo_result *r, uint32_t lo, uint32_t hi) {
    if (!r) return;
    if (r->flags & DUO_F_ROM_CHANGED) {
        if (lo < r->rom_lo) r->rom_lo = lo;
        if (hi > r->rom_hi) r->rom_hi = hi;
    } else {
        r->rom_lo = lo;
        r->rom_hi = hi;
    }
    r->flags |= DUO_F_ROM_CHANGED;
}

static int is_game_map(uint32_t v) { return v == 0x0101 || v == 0x0007 || v == 0x0001; }

static int too_fast(uint16_t waitcnt) { return ((waitcnt >> 2) & 3) == 2; }   /* 2-cycle first access */

static int banked(int t) { return t == DUO_SAVE_SANYO || t == DUO_SAVE_MACRONIX; }

static int is_flash(int t) { return t == DUO_SAVE_SANYO || t == DUO_SAVE_MACRONIX || t == DUO_SAVE_FLASH512; }

static const char *type_name(int t) {
    static const char *n[] = {"sanyo", "macronix", "flash512", "sram", "eeprom", "none"};
    return (t >= 0 && t <= 5) ? n[t] : "?";
}

/* ------------------------------------------------------------------ life */

duo_t *duo_new(const uint8_t *fw, size_t fw_len, const uint8_t *game, size_t game_len,
               int save_type, const uint8_t *save, size_t save_len) {
    duo_t *d = calloc(1, sizeof *d);
    if (!d) return NULL;
    memset(d->flash, 0xFF, FLASH_SIZE);
    memcpy(d->flash, fw, fw_len < FLASH_SIZE ? fw_len : FLASH_SIZE);
    if (game_len > DUO_ROM_SIZE) game_len = DUO_ROM_SIZE;
    d->game = malloc(game_len ? game_len : 1);
    if (!d->game) { free(d); return NULL; }
    memcpy(d->game, game, game_len);
    d->game_len = game_len;
    d->save_type = save_type;
    switch (save_type) {
    case DUO_SAVE_SANYO: case DUO_SAVE_MACRONIX: d->save_size = 0x20000; break;
    case DUO_SAVE_FLASH512: d->save_size = 0x10000; break;
    case DUO_SAVE_SRAM: d->save_size = 0x8000; break;
    default: d->save_size = 0;
    }
    d->save = malloc(d->save_size ? d->save_size : 1);
    if (!d->save) { free(d->game); free(d); return NULL; }
    memset(d->save, 0xFF, d->save_size);
    memcpy(d->save, save, save_len < d->save_size ? save_len : d->save_size);
    d->waitcnt = 0x4314;
    d->turn = TURN_PC;
    return d;
}

void duo_free(duo_t *d) {
    if (!d) return;
    free(d->game);
    free(d->save);
    free(d);
}

/* ------------------------------------------------------------------ what the bus sees */

uint32_t duo_rom_span(const duo_t *d) {
    uint32_t span = d->game_len > MIRROR_END ? (uint32_t)d->game_len : MIRROR_END;
    return span < DUO_ROM_SIZE ? span : DUO_ROM_SIZE;
}

/* Open bus beyond the cartridge: the GBA reads back the address bits (a halfword each). */
static uint8_t open_bus(uint32_t off) {
    uint32_t h = ((DUO_ROM_BASE + (off & ~1u)) >> 1) & 0xFFFF;
    return (off & 1) ? (uint8_t)(h >> 8) : (uint8_t)h;
}

static uint8_t rom_byte(const duo_t *d, uint32_t off) {
    if (off >= OVERLAY_LO && off < OVERLAY_HI)              /* the Actel's window over the header */
        return off >= MAPREG_OFF ? MAPREG_READ[off - MAPREG_OFF] : 0;
    if (!d->mapped) {                                        /* the DUO's own flash */
        if (d->flash_id && off < 4) return FLASH_ID[off];
        return off < MIRROR_END ? d->flash[off & (FLASH_SIZE - 1)] : open_bus(off);
    }
    if (off >= d->game_len) return open_bus(off);            /* the game's ROM chip, FF-padded */
    uint8_t b = d->game[off];
    if (too_fast(d->waitcnt) && off >= 0x100 && off < 0x80000 && ((off - 0x100) & 0xFFF) == 0)
        b ^= 0x01;                                           /* 2-cycle first access: misread */
    return b;
}

static uint8_t save_byte(const duo_t *d, uint32_t off) {
    off &= DUO_SAVE_SIZE - 1;
    if (!d->mapped || !d->awake || d->save_type == DUO_SAVE_EEPROM || d->save_type == DUO_SAVE_NONE)
        return 0xFF;                                         /* asleep, or nothing there */
    if (d->id_mode && is_flash(d->save_type))
        return SAVE_IDS[d->save_type][off & 1];
    if (d->save_type == DUO_SAVE_SRAM)
        return d->save[off & 0x7FFF];
    return d->save[(uint32_t)d->bank * 0x10000 + off];
}

static uint8_t bus_byte(const duo_t *d, uint32_t addr) {
    if (addr >= DUO_ROM_BASE && addr < DUO_ROM_BASE + DUO_ROM_SIZE)
        return rom_byte(d, addr - DUO_ROM_BASE);
    if (addr >= DUO_SAVE_BASE && addr < DUO_SAVE_BASE + 0x02000000u)
        return save_byte(d, addr - DUO_SAVE_BASE);
    return 0xFF;
}

void duo_render(const duo_t *d, uint32_t addr, uint8_t *out, size_t len) {
    /* fast paths for the long spans hosts refresh */
    if (addr >= DUO_ROM_BASE && addr + len <= DUO_ROM_BASE + DUO_ROM_SIZE) {
        uint32_t off = addr - DUO_ROM_BASE;
        for (size_t i = 0; i < len; i++) out[i] = rom_byte(d, off + (uint32_t)i);
        return;
    }
    for (size_t i = 0; i < len; i++) out[i] = bus_byte(d, addr + (uint32_t)i);
}

int duo_wants_rom_reads(const duo_t *d) { return d->mapped && !d->awake; }

/* ------------------------------------------------------------------ reads */

uint32_t duo_read(duo_t *d, uint32_t addr, int width, duo_result *r) {
    char a[16];
    clear(r);
    uint32_t v = 0;
    if (addr >= DUO_ROM_BASE && addr < DUO_ROM_BASE + DUO_ROM_SIZE) {
        /* Any game ROM read, at any address and width, wakes the save chip (lab session 4). */
        if (d->mapped && !d->awake) {
            d->awake = 1;
            if (r) r->flags |= DUO_F_SAVE_CHANGED | DUO_F_WOKE;
        }
        if (addr >= DUO_CTRL_LO && addr <= DUO_CTRL_HI && d->mapped) {
            if (r) r->flags |= DUO_F_BAD;
            say(r, "read of DUO register area %s while the game was mapped", hx(a, addr));
        }
        for (int i = 0; i < width; i++) v |= (uint32_t)rom_byte(d, addr - DUO_ROM_BASE + i) << (8 * i);
        return v;
    }
    if (addr >= DUO_SAVE_BASE && addr < DUO_SAVE_BASE + 0x02000000u) {
        uint8_t b = save_byte(d, addr - DUO_SAVE_BASE);
        if (width != 1 && d->mapped) {
            /* The save area is an 8-bit bus: wider reads return the byte repeated (lab 5). */
            if (r) r->flags |= DUO_F_BAD;
            say(r, "%d-bit read of the save area at %s: the GBA's save bus is 8 bits wide, "
                   "so the real chip would return one byte repeated (found on real hardware, lab session 5)",
                8 * width, hx(a, addr));
        }
        for (int i = 0; i < width; i++) v |= (uint32_t)b << (8 * i);
        return v;
    }
    return 0;
}

/* ------------------------------------------------------------------ writes */

static void rom_write(duo_t *d, uint32_t addr, uint32_t value, duo_result *r) {
    char a[16], b[16];
    uint32_t v = value & 0xFFFF;
    if (addr == DUO_MAPREG) {
        if (is_game_map(v)) {
            d->mapped = (uint16_t)v;            /* the game swaps in; its save chip sleeps */
            d->awake = 0;
        } else if (v == DUO_MAP_DUO) {
            d->mapped = 0;
            d->awake = 0;
        } else {
            if (r) r->status = DUO_FAIL;
            say(r, "unexpected mapping value %s", hx(a, v));
            return;
        }
        d->flash_id = 0;                        /* a swap shows the flash's array again */
        rom_changed(r, 0, duo_rom_span(d));
        if (r) r->flags |= DUO_F_SAVE_CHANGED;
        return;
    }
    if (!d->mapped && (addr == 0x0800AAAAu || addr == 0x08005554u)) {
        if (v == 0x9090) {                      /* SST software-ID entry */
            d->flash_id = 1;
            rom_changed(r, 0, 4);
        }
        return;                                 /* unlock cycles are taken quietly */
    }
    if (!d->mapped && addr == DUO_ROM_BASE && v == 0xF0F0) {   /* ID exit */
        d->flash_id = 0;
        rom_changed(r, 0, 4);
        return;
    }
    if (r) r->status = DUO_FAIL;
    if (d->mapped)
        say(r, "unexpected write %s to %s (mapped=%u)", hx(a, v), hx(b, addr), d->mapped);
    else
        say(r, "unexpected write %s to %s (mapped=None)", hx(a, v), hx(b, addr));
}

static void save_write(duo_t *d, uint32_t off, uint32_t value, duo_result *r) {
    char a[16], b[16];
    uint8_t v = value & 0xFF;
    if (!d->mapped || !d->awake) return;        /* nothing connected (or asleep): ignored */
    d->save_writes++;
    int t = d->save_type;
    if (t == DUO_SAVE_SRAM) {
        if (r) r->flags |= DUO_F_VIOLATION | DUO_F_SAVE_CHANGED;
        say(r, "SRAM write %s at %s", hx(a, v), hx(b, off));
        d->save[off & 0x7FFF] = v;
        return;
    }
    if (t == DUO_SAVE_EEPROM || t == DUO_SAVE_NONE) {
        if (r) r->flags |= DUO_F_VIOLATION;
        say(r, "write to %s cart at %s", type_name(t), hx(a, off));
        return;
    }
    /* A Flash chip. */
    if (off == 0 && v == 0xF0 && d->ncmd == 0) {   /* reset */
        d->id_mode = 0;
        if (r) r->flags |= DUO_F_SAVE_CHANGED;
        return;
    }
    int n = d->ncmd + 1;                        /* the sequence so far, with this write */
    uint32_t so[4];
    uint8_t sv[4];
    for (int i = 0; i < d->ncmd; i++) { so[i] = d->cmd_off[i]; sv[i] = d->cmd_val[i]; }
    so[n - 1] = off;
    sv[n - 1] = v;
    static const uint32_t UO[2] = {0x5555, 0x2AAA};
    static const uint8_t UV[2] = {0xAA, 0x55};
    int unlock_prefix = 1;
    for (int i = 0; i < n && i < 2; i++)
        if (so[i] != UO[i] || sv[i] != UV[i]) unlock_prefix = 0;
    if (n <= 2 && unlock_prefix) {
        for (int i = 0; i < n; i++) { d->cmd_off[i] = so[i]; d->cmd_val[i] = sv[i]; }
        d->ncmd = n;
        return;
    }
    if (n == 3 && unlock_prefix && off == 0x5555) {
        d->ncmd = 0;
        if (v == 0x90) {
            d->id_mode = 1;
        } else if (v == 0xF0) {
            d->id_mode = 0;
        } else if (v == 0xB0 && banked(t)) {
            for (int i = 0; i < 3; i++) { d->cmd_off[i] = so[i]; d->cmd_val[i] = sv[i]; }
            d->ncmd = 3;
        } else {
            if (r) r->flags |= DUO_F_VIOLATION;
            say(r, "Flash command %s (could alter the save)", hx(a, v));
        }
        if (r) r->flags |= DUO_F_SAVE_CHANGED;
        return;
    }
    if (n == 4 && so[2] == 0x5555 && sv[2] == 0xB0 && off == 0) {   /* bank switch */
        d->bank = v & 1;
        d->ncmd = 0;
        if (r) r->flags |= DUO_F_SAVE_CHANGED;
        return;
    }
    /* Real Flash chips ignore an incomplete or out-of-order sequence and reset. */
    d->ignored++;
    if (off == 0x5555 && v == 0xAA) {
        d->cmd_off[0] = off;
        d->cmd_val[0] = v;
        d->ncmd = 1;
    } else {
        d->ncmd = 0;
    }
}

void duo_write(duo_t *d, uint32_t addr, int width, uint32_t value, duo_result *r) {
    (void)width;
    clear(r);
    if (addr >= DUO_ROM_BASE && addr < DUO_ROM_BASE + DUO_ROM_SIZE)
        rom_write(d, addr, value, r);
    else if (addr >= DUO_SAVE_BASE && addr < DUO_SAVE_BASE + DUO_SAVE_SIZE)
        save_write(d, addr - DUO_SAVE_BASE, value, r);
}

void duo_set_waitcnt(duo_t *d, uint16_t waitcnt, duo_result *r) {
    clear(r);
    uint16_t old = d->waitcnt;
    d->waitcnt = waitcnt;
    if (d->mapped && too_fast(old) != too_fast(waitcnt))
        rom_changed(r, 0, duo_rom_span(d));
}

/* ------------------------------------------------------------------ USB */

static void hexdump(char *out, size_t cap, const uint8_t *p, size_t n) {
    size_t k = 0;
    out[0] = 0;
    for (size_t i = 0; i < n && k + 3 < cap; i++) k += (size_t)snprintf(out + k, cap - k, "%02x", p[i]);
}

int duo_usb_turn(const duo_t *d) { return d->turn; }
void duo_usb_set_turn(duo_t *d, int turn) { d->turn = turn ? TURN_GBA : TURN_PC; }

int duo_usb_from_pc(duo_t *d, const uint8_t *pkt, size_t len, duo_result *r) {
    char h[80];
    clear(r);
    if (d->turn != TURN_PC) {
        hexdump(h, sizeof h, pkt, len);
        if (r) r->status = DUO_FAIL;
        say(r, "PC sent two packets in a row (%s) - the DUO never takes it", h);
        return DUO_FAIL;
    }
    d->turn = TURN_GBA;
    return DUO_OK;
}

int duo_usb_from_gba(duo_t *d, const uint8_t *pkt, size_t len, duo_result *r) {
    char h[80];
    clear(r);
    if (d->turn != TURN_GBA) {
        hexdump(h, sizeof h, pkt, len);
        if (r) r->status = DUO_FAIL;
        say(r, "GBA sent two packets in a row (%s) - it would hang here", h);
        return DUO_FAIL;
    }
    d->turn = TURN_PC;
    return DUO_OK;
}

/* ------------------------------------------------------------------ state */

int duo_mapped(const duo_t *d) { return d->mapped; }
int duo_awake(const duo_t *d) { return d->awake; }
int duo_bank(const duo_t *d) { return d->bank; }
int duo_id_mode(const duo_t *d) { return d->id_mode; }
int duo_flash_id_mode(const duo_t *d) { return d->flash_id; }
uint16_t duo_waitcnt(const duo_t *d) { return d->waitcnt; }
uint32_t duo_save_writes(const duo_t *d) { return d->save_writes; }
uint32_t duo_ignored(const duo_t *d) { return d->ignored; }
size_t duo_save_size(const duo_t *d) { return d->save_size; }
void duo_save_copy(const duo_t *d, uint8_t *out) { memcpy(out, d->save, d->save_size); }
int duo_cmd_len(const duo_t *d) { return d->ncmd; }
