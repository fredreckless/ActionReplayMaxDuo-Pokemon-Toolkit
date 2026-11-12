/* fuzz_core.c - hammer the core's API with random traffic under AddressSanitizer and UBSan.
 *
 *   cc -std=c99 -g -O1 -fsanitize=address,undefined -I../core fuzz_core.c ../core/duocore.c -o fuzz_core
 *   ./fuzz_core [ROUNDS]
 *
 * It checks memory safety and a few invariants that must hold whatever the traffic:
 * the overlay always reads zeros with F0 0F at 0x9C; asleep or unmapped, the save window reads
 * FF; a save never changes except through an SRAM write; reads agree with duo_render. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "duocore.h"

static uint32_t s = 12345;
static uint32_t rnd(void) { s ^= s << 13; s ^= s >> 17; s ^= s << 5; return s; }

#define CHECK(c, ...) do { if (!(c)) { printf("FAILED: " __VA_ARGS__); printf("\n"); return 1; } } while (0)

int main(int argc, char **argv) {
    int rounds = argc > 1 ? atoi(argv[1]) : 300;
    static uint8_t fw[0x30000], game[0x200000], save[0x20000], snap[0x20000], buf[0x200];
    for (size_t i = 0; i < sizeof fw; i++) fw[i] = (uint8_t)rnd();
    for (size_t i = 0; i < sizeof game; i++) game[i] = (uint8_t)rnd();
    static const uint32_t game_sizes[] = {0x1000, 0x80000, 0x180000, 0x200000, 1};
    static const uint16_t maps[] = {0x0120, 0x0101, 0x0007, 0x0001, 0x0120, 0x1234};
    static const int widths[] = {1, 2, 4};
    long ops = 0;
    for (int round = 0; round < rounds; round++) {
        int type = round % 6;
        size_t glen = game_sizes[rnd() % 5];
        size_t slen = rnd() % 3 == 0 ? 0 : (rnd() % 0x20000);
        for (size_t i = 0; i < slen; i++) save[i] = (uint8_t)rnd();
        duo_t *d = duo_new(fw, sizeof fw, game, glen, type, save, slen);
        CHECK(d, "duo_new");
        size_t ssize = duo_save_size(d);
        duo_save_copy(d, snap);
        duo_result r;
        for (int k = 0; k < 4000; k++, ops++) {
            uint32_t a, v = rnd();
            int w = widths[rnd() % 3];
            switch (rnd() % 10) {
            case 0: duo_write(d, DUO_MAPREG, 2, maps[rnd() % 6], &r); break;
            case 1: case 2: {
                static const uint32_t offs[] = {0x5555, 0x2AAA, 0};
                static const uint8_t vals[] = {0xAA, 0x55, 0x90, 0xF0, 0xB0, 0x80, 0xA0};
                duo_write(d, DUO_SAVE_BASE + (rnd() % 4 ? offs[rnd() % 3] : rnd() % 0x10000), 1,
                          vals[rnd() % 7], &r);
                break;
            }
            case 3: a = DUO_ROM_BASE + rnd() % DUO_ROM_SIZE; duo_read(d, a, w, &r); break;
            case 4: a = DUO_SAVE_BASE + rnd() % 0x10000; duo_read(d, a, w, &r); break;
            case 5: duo_write(d, (rnd() & 1) ? 0x0800AAAAu : DUO_ROM_BASE, 2, (rnd() & 1) ? 0x9090 : 0xF0F0, &r); break;
            case 6: duo_set_waitcnt(d, (uint16_t)v, &r); break;
            case 7: { uint8_t p[8]; for (int i = 0; i < 8; i++) p[i] = (uint8_t)rnd();
                      switch (rnd() % 4) {
                      case 0: duo_usb_from_pc(d, p, rnd() % 9, &r); break;
                      case 1: duo_usb_take(d, p); break;
                      default: duo_write(d, 0x09FE01E0u + (rnd() % 4 == 0), (rnd() & 1) ? 1 : 2, rnd(), &r);
                               duo_read(d, 0x09FE01C0u, 2, &r);
                      }
                      CHECK(duo_usb_turn(d) == 0 || duo_usb_turn(d) == 1, "turn"); break; }
            case 8: duo_write(d, DUO_ROM_BASE + rnd() % DUO_ROM_SIZE, w, v, &r);
                    CHECK(r.status == DUO_FAIL || (r.flags & DUO_F_ROM_CHANGED) || r.msg[0] == 0, "write result"); break;
            case 9: {
                a = DUO_ROM_BASE + rnd() % (DUO_ROM_SIZE - sizeof buf);
                duo_render(d, a, buf, sizeof buf);
                break;
            }
            }
            CHECK(strlen(r.msg) < DUO_MSG, "message length");
            if (r.flags & DUO_F_ROM_CHANGED) CHECK(r.rom_lo < r.rom_hi && r.rom_hi <= DUO_ROM_SIZE, "range");
            /* invariants */
            duo_render(d, DUO_ROM_BASE + 0x20, buf, 0x80);
            for (int i = 0; i < 0x7C; i++) CHECK(buf[i] == 0, "overlay not zero at %#x", 0x20 + i);
            CHECK(buf[0x7C] == 0xF0 && buf[0x7D] == 0x0F && buf[0x7E] == 0 && buf[0x7F] == 0, "mapping register");
            if (!duo_mapped(d) || !duo_awake(d)) {
                duo_render(d, DUO_SAVE_BASE + (rnd() % 0xFF00), buf, 0x100);
                for (int i = 0; i < 0x100; i++) CHECK(buf[i] == 0xFF, "asleep or unmapped save not FF");
            }
            if (type != DUO_SAVE_SRAM) {
                static uint8_t now[0x20000];
                if (k % 500 == 0) { duo_save_copy(d, now); CHECK(!memcmp(now, snap, ssize), "save changed"); }
            }
            a = DUO_ROM_BASE + rnd() % (DUO_ROM_SIZE - 4);
            if (duo_mapped(d) && !duo_awake(d)) continue;  /* a read would wake it: leave that to case 3 */
            uint32_t got = duo_read(d, a, 4, &r);
            duo_render(d, a, buf, 4);
            CHECK(got == (uint32_t)(buf[0] | buf[1] << 8 | buf[2] << 16 | (uint32_t)buf[3] << 24), "read != render at %#x", a);
        }
        duo_free(d);
    }
    printf("fuzz_core: %d rounds, %ld operations, clean (%s)\n", rounds, ops, duo_version());
    return 0;
}
