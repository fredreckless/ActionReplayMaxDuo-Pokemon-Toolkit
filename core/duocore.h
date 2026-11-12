/*
 * duocore.h - one behavioural model of the Action Replay MAX DUO's three chips.
 *
 * The core answers the GBA's cartridge-bus reads and writes (address, width, value) and
 * decides everything the DUO's hardware decides: the Actel's mapping register, header overlay
 * and control area; the SST flash, its mirror and ID mode, and open bus above it; the game
 * cartridge seen through the pass-through slot, including its save chip's sleep and wake; and
 * the USB link's strict alternation. It knows nothing of any emulator: a host (tests/hwsim.py
 * through ctypes, later an mGBA cartridge device) owns the CPU and the rest of the GBA.
 *
 * Every behaviour here was measured on real hardware (docs/FINDINGS.md) or is what the
 * toolkit's simulator already modelled; the first version matches tests/hwsim.py exactly.
 */
#ifndef DUOCORE_H
#define DUOCORE_H

#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
#define DUO_API __declspec(dllexport)
#else
#define DUO_API __attribute__((visibility("default")))
#endif

#define DUO_ROM_BASE   0x08000000u
#define DUO_ROM_SIZE   0x02000000u      /* the cartridge ROM space, 32 MB */
#define DUO_SAVE_BASE  0x0E000000u
#define DUO_SAVE_SIZE  0x00010000u      /* the save chip's 64 KB window */
#define DUO_CTRL_LO    0x09FE0000u      /* the Actel's control area */
#define DUO_CTRL_HI    0x09FFFFFFu
#define DUO_MAPREG     0x0800009Cu
#define DUO_MAP_DUO    0x0120u

enum duo_save_type {
    DUO_SAVE_SANYO = 0,     /* 128 KB Flash, ID 62/13, banked */
    DUO_SAVE_MACRONIX = 1,  /* 128 KB Flash, ID C2/09, banked */
    DUO_SAVE_FLASH512 = 2,  /* 64 KB Flash, ID BF/D4 */
    DUO_SAVE_SRAM = 3,      /* 32 KB SRAM */
    DUO_SAVE_EEPROM = 4,    /* nothing answers at 0x0E000000 */
    DUO_SAVE_NONE = 5
};

/* What one bus access did, beyond the value read. */
enum duo_status {
    DUO_OK = 0,
    DUO_FAIL = 1            /* the access could not happen on hardware: the host stops the CPU */
};
enum duo_flags {
    DUO_F_VIOLATION = 1,    /* a write that could change the game's save (msg says what) */
    DUO_F_BAD = 2,          /* something a test must fail on, though the CPU carries on */
    DUO_F_ROM_CHANGED = 4,  /* the ROM space now reads differently in [rom_lo, rom_hi) */
    DUO_F_SAVE_CHANGED = 8, /* the save window now reads differently */
    DUO_F_WOKE = 16,        /* this read woke the game's save chip */
    DUO_F_USB_SENT = 32     /* the GBA finished a packet for the PC: duo_usb_take() it */
};

#define DUO_MSG 200

typedef struct duo_result {
    int32_t status;         /* enum duo_status */
    int32_t flags;          /* enum duo_flags */
    uint32_t rom_lo, rom_hi;/* offsets into the ROM space, valid with DUO_F_ROM_CHANGED */
    uint32_t cycles;        /* extra bus cycles the DUO costs (0: not modelled yet) */
    char msg[DUO_MSG];      /* the failure, violation or bad-access message, if any */
} duo_result;

typedef struct duo duo_t;

/* fw: the DUO flash image (padded with FF to 512 KB); game: the cartridge's ROM chip contents
 * (open bus above); save: the save chip's contents (FF-padded to the chip's size). */
DUO_API duo_t *duo_new(const uint8_t *fw, size_t fw_len, const uint8_t *game, size_t game_len,
                       int save_type, const uint8_t *save, size_t save_len);
DUO_API void duo_free(duo_t *d);

/* ---- the cartridge bus ---- */
/* A read the GBA makes, with its side effects (a game ROM read wakes the save chip). */
DUO_API uint32_t duo_read(duo_t *d, uint32_t addr, int width, duo_result *r);
/* A write the GBA makes. */
DUO_API void duo_write(duo_t *d, uint32_t addr, int width, uint32_t value, duo_result *r);
/* What reads of [addr, addr+len) would return now, without side effects (for hosts that keep
 * the cartridge in memory and refresh it when the core reports a change). */
DUO_API void duo_render(const duo_t *d, uint32_t addr, uint8_t *out, size_t len);
/* The span of the ROM space that can differ between the DUO and the game (above it both read
 * as open bus). */
DUO_API uint32_t duo_rom_span(const duo_t *d);
/* The GBA's WAITCNT, as the cartridge sees it: 2-cycle first-access timing is too fast for
 * some game ROM chips (Ruby's corrupted, LeafGreen's didn't). */
DUO_API void duo_set_waitcnt(duo_t *d, uint16_t waitcnt, duo_result *r);
/* Does the core need to hear about ROM reads? (Only while the save chip sleeps behind a mapped
 * game: hosts may skip notifying it otherwise.) */
DUO_API int duo_wants_rom_reads(const duo_t *d);

/* ---- the USB link: the Actel's link registers and the Cypress chip's observed behaviour ----
 * The GBA side is ordinary bus traffic: LINK_IN (0x09FE01C0) reads a byte from the USB chip with
 * its strobe in bit 8, LINK_OUT (0x09FE01E0) takes a byte from the GBA with the GBA's strobe in
 * bit 8, both only while the DUO is mapped. These calls are the PC's side. */
/* Whose packet the link expects next: 0 = the PC's, 1 = the GBA's (or one is being handed over). */
DUO_API int duo_usb_turn(const duo_t *d);
/* A PC packet is waiting that the GBA hasn't started reading. */
DUO_API int duo_usb_pending(const duo_t *d);
/* The PC writes a packet: DUO_OK if the chip takes it; DUO_FAIL (never seen by the GBA, the
 * PC's write times out) for a second PC packet in a row. */
DUO_API int duo_usb_from_pc(duo_t *d, const uint8_t *pkt, size_t len, duo_result *r);
/* The GBA's last complete packet, for the PC: 1 and 8 bytes in out, or 0 if none is waiting. */
DUO_API int duo_usb_take(duo_t *d, uint8_t *out);
/* The two link registers as they stand (for tests and debugging). */
DUO_API uint16_t duo_link_in(const duo_t *d);
DUO_API uint16_t duo_link_out(const duo_t *d);

/* ---- save states: the whole DUO, for a host saving its emulator's state alongside ---- */
DUO_API size_t duo_state_size(const duo_t *d);
DUO_API void duo_state_save(const duo_t *d, uint8_t *out);
DUO_API int duo_state_load(duo_t *d, const uint8_t *in, size_t len);   /* DUO_FAIL: another DUO's state */

/* ---- state, for hosts and tests ---- */
DUO_API int duo_mapped(const duo_t *d);          /* 0 = the DUO program, else the map value */
DUO_API int duo_awake(const duo_t *d);
DUO_API int duo_bank(const duo_t *d);
DUO_API int duo_id_mode(const duo_t *d);
DUO_API int duo_flash_id_mode(const duo_t *d);
DUO_API uint16_t duo_waitcnt(const duo_t *d);
DUO_API uint32_t duo_save_writes(const duo_t *d);
DUO_API uint32_t duo_ignored(const duo_t *d);
DUO_API size_t duo_save_size(const duo_t *d);
DUO_API void duo_save_copy(const duo_t *d, uint8_t *out);   /* the save chip's contents */
DUO_API int duo_cmd_len(const duo_t *d);                     /* a Flash command in progress */
DUO_API const char *duo_version(void);

#endif
