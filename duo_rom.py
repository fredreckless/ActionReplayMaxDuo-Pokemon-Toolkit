"""Copy what the Secret Base Workshop needs from the Pokemon cartridge in the Action Replay MAX DUO
to a ROM file on this PC (read-only).

    python duo_rom.py                  the parts the workshop draws with (about two minutes)
    python duo_rom.py --whole          the cartridge's whole ROM, any game (16 MB: well over an hour)
    python duo_rom.py --out FOLDER     somewhere else than a 'roms' folder beside the tools

Made for the Secret Base Workshop (secret_base_workshop.html), which reads the game's own room
tiles, decorations and dolls from your ROM in your browser, so the toolkit itself never carries any
of the game's art. Reading through the DUO is slow (about 3 KB a second), so by default only those
parts are read: the 24 room layouts and their tiles, the decoration table, and the doll and cushion
pictures - found by the addresses pret's symbol files give for each game (addresses only, nothing
of the game's data), checked on the cartridge before they're trusted, and followed from there. The
file saved is a full-size ROM with only those parts filled in, which the workshop opens as it is.

Known so far: English Ruby (all three revisions), English Sapphire (the first) and English
Emerald. Other versions (Japanese, European) can be copied whole with --whole until their addresses
are known. FireRed and LeafGreen have no Secret Bases: only --whole copies them.

Like maxduo_saves.py it only reads: the cartridge is mapped in, each piece is read and checked
against the GBA's own CRC of the same bytes, and the DUO is put back as it was. The DUO's own chip
covers 0x20-0x9F of the cartridge header (part of the start-up logo), so those bytes read as zeros
here; nothing the workshop uses is there. Needs the Reckless firmware (v3.1 or later) and the GBA
in USB SERVER MODE. Keep the ROM to yourself: it's your cartridge's, and not for sharing."""
import argparse, os, struct, sys, time, zlib

import maxduo_saves as M
from maxduo_saves import DuoError, Lab, MaxDuo, UsbTransport, MAP_REG

CHUNK = 0x10000
DUO_MAP = 0x0120                         # the DUO's own mapping, put back after every read
GAME_ROM_SIZE = 0x1000000                # every Gen 3 Pokemon cartridge is 16 MB
POKEMON_CODES = ("AXV", "AXP", "BPE", "BPR", "BPG")
SECRET_BASE_CODES = {"AXV": "Ruby", "AXP": "Sapphire", "BPE": "Emerald"}
# The 24 Secret Base rooms in the games' layout order (all the 1s: red, brown, blue, yellow cave,
# tree, shrub; then the 2s...): their sizes, as the workshop checks them
ROOM_SIZES = [(11, 9)] * 6 + [(7, 16), (14, 9), (15, 7), (14, 9), (7, 16), (15, 7),
                              (15, 8), (15, 11), (10, 17), (12, 11), (17, 8), (13, 11),
                              (9, 15), (14, 12), (9, 17), (13, 14), (14, 14), (14, 11)]
SPRITE_DECORATIONS = range(76, 121)      # the dolls and cushions (objects, not map tiles)
# The routes with Secret Bases, and every route's size in tiles (pret's layouts.json): gMapLayouts
# entries 16-49 are Routes 101-134 in all three games. The workshop draws the route round a base's
# entrance from them (11 November).
ROUTE_TILES = {101: (20, 20), 102: (50, 20), 103: (80, 22), 104: (40, 80), 105: (40, 80), 106: (80, 20), 107: (60, 20),
               108: (60, 20), 109: (40, 63), 110: (40, 100), 111: (40, 140), 112: (40, 60), 113: (100, 20), 114: (40, 80),
               115: (40, 80), 116: (100, 20), 117: (60, 20), 118: (80, 20), 119: (40, 140), 120: (40, 100), 121: (80, 20),
               122: (40, 40), 123: (140, 20), 124: (80, 80), 125: (80, 40), 126: (80, 80), 127: (80, 80), 128: (120, 40),
               129: (80, 40), 130: (80, 40), 131: (60, 40), 132: (80, 40), 133: (80, 40), 134: (80, 40)}

# Where each game keeps what the workshop reads (pret/pokeruby and pret/pokeemerald, the symbols
# branch: gMapLayouts, gDecorations, gObjectEventGraphicsInfoPointers and sObjectEventSpritePalettes
# with their sizes, and SecretBase_<Kind><n>_Layout in layout order). Code + revision.
WORKSHOP_PARTS = {
    "AXVE0": dict(layouts=0x8304f18, decorations=0x83eb6c4, gfx=(0x836dc58, 0x368), pals=(0x837377c, 0xe0),
                 text=[(0x81b0a91, 0, "string"), (0x81b0aed, 0, "string"), (0x81b0b2c, 0, "string"), (0x81f0208, 754, "block"), (0x81fde1d, 77, "block"), (0x83c5564, 15356, "block"), (0x83ce048, 76, "ptrs"), (0x83d1434, 16, "ptrs"), (0x83d1444, 16, "ptrs"), (0x83d1454, 16, "ptrs"), (0x83d1470, 32, "ptrs"), (0x83d1490, 24, "ptrs"), (0x83d14a8, 20, "ptrs"), (0x83d14bc, 4, "ptrs"), (0x83d14c0, 48, "ptrs"), (0x83d14f0, 52, "ptrs"), (0x83d1524, 36, "ptrs"), (0x83d1548, 60, "ptrs"), (0x83d1584, 76, "ptrs"), (0x83d15d0, 28, "ptrs"), (0x83d15ec, 8, "ptrs"), (0x83d15f4, 12, "ptrs"), (0x83e53e0, 576, "stories"), (0x83e73c4, 704, "places"), (0x816b9ce, 0, "string")],
                 easy_chat=(0x83dbf2c, 0x83de0e0),
                 rooms=(0x82e7788, 0x82e7870, 0x82e7958, 0x82e7a40, 0x82e7b28, 0x82e7c10, 0x82e7d10, 0x82e7e2c, 0x82e7f20, 0x82e803c, 0x82e813c, 0x82e8230, 0x82e8340, 0x82e84ac, 0x82e8620, 0x82e8748, 0x82e8878, 0x82e89b8, 0x82e8ae8, 0x82e8c58, 0x82e8dac, 0x82e8f38, 0x82e90e0, 0x82e9234)),
    "AXVE1": dict(layouts=0x8304f30, decorations=0x83eb6e0, gfx=(0x836dc70, 0x368), pals=(0x8373794, 0xe0),
                 text=[(0x81b0aa7, 0, "string"), (0x81b0b03, 0, "string"), (0x81b0b42, 0, "string"), (0x81f0220, 754, "block"), (0x81fde35, 77, "block"), (0x83c5580, 15356, "block"), (0x83ce064, 76, "ptrs"), (0x83d1450, 16, "ptrs"), (0x83d1460, 16, "ptrs"), (0x83d1470, 16, "ptrs"), (0x83d148c, 32, "ptrs"), (0x83d14ac, 24, "ptrs"), (0x83d14c4, 20, "ptrs"), (0x83d14d8, 4, "ptrs"), (0x83d14dc, 48, "ptrs"), (0x83d150c, 52, "ptrs"), (0x83d1540, 36, "ptrs"), (0x83d1564, 60, "ptrs"), (0x83d15a0, 76, "ptrs"), (0x83d15ec, 28, "ptrs"), (0x83d1608, 8, "ptrs"), (0x83d1610, 12, "ptrs"), (0x83e53fc, 576, "stories"), (0x83e73e0, 704, "places"), (0x816b9ee, 0, "string")],
                 easy_chat=(0x83dbf48, 0x83de0fc),
                 rooms=(0x82e77a0, 0x82e7888, 0x82e7970, 0x82e7a58, 0x82e7b40, 0x82e7c28, 0x82e7d28, 0x82e7e44, 0x82e7f38, 0x82e8054, 0x82e8154, 0x82e8248, 0x82e8358, 0x82e84c4, 0x82e8638, 0x82e8760, 0x82e8890, 0x82e89d0, 0x82e8b00, 0x82e8c70, 0x82e8dc4, 0x82e8f50, 0x82e90f8, 0x82e924c)),
    "AXVE2": dict(layouts=0x8304f30, decorations=0x83eb6e0, gfx=(0x836dc70, 0x368), pals=(0x8373794, 0xe0),
                 text=[(0x81b0aa7, 0, "string"), (0x81b0b03, 0, "string"), (0x81b0b42, 0, "string"), (0x81f0220, 754, "block"), (0x81fde35, 77, "block"), (0x83c5580, 15356, "block"), (0x83ce064, 76, "ptrs"), (0x83d1450, 16, "ptrs"), (0x83d1460, 16, "ptrs"), (0x83d1470, 16, "ptrs"), (0x83d148c, 32, "ptrs"), (0x83d14ac, 24, "ptrs"), (0x83d14c4, 20, "ptrs"), (0x83d14d8, 4, "ptrs"), (0x83d14dc, 48, "ptrs"), (0x83d150c, 52, "ptrs"), (0x83d1540, 36, "ptrs"), (0x83d1564, 60, "ptrs"), (0x83d15a0, 76, "ptrs"), (0x83d15ec, 28, "ptrs"), (0x83d1608, 8, "ptrs"), (0x83d1610, 12, "ptrs"), (0x83e53fc, 576, "stories"), (0x83e73e0, 704, "places"), (0x816b9ee, 0, "string")],
                 easy_chat=(0x83dbf48, 0x83de0fc),
                 rooms=(0x82e77a0, 0x82e7888, 0x82e7970, 0x82e7a58, 0x82e7b40, 0x82e7c28, 0x82e7d28, 0x82e7e44, 0x82e7f38, 0x82e8054, 0x82e8154, 0x82e8248, 0x82e8358, 0x82e84c4, 0x82e8638, 0x82e8760, 0x82e8890, 0x82e89d0, 0x82e8b00, 0x82e8c70, 0x82e8dc4, 0x82e8f50, 0x82e90f8, 0x82e924c)),
    "AXPE0": dict(layouts=0x8304ea8, decorations=0x83eb71c, gfx=(0x836dbe8, 0x368), pals=(0x837370c, 0xe0),
                 text=[(0x81b0a21, 0, "string"), (0x81b0a7d, 0, "string"), (0x81b0abc, 0, "string"), (0x81f0198, 754, "block"), (0x81fddad, 77, "block"), (0x83c55bc, 15356, "block"), (0x83ce0a0, 76, "ptrs"), (0x83d148c, 16, "ptrs"), (0x83d149c, 16, "ptrs"), (0x83d14ac, 16, "ptrs"), (0x83d14c8, 32, "ptrs"), (0x83d14e8, 24, "ptrs"), (0x83d1500, 20, "ptrs"), (0x83d1514, 4, "ptrs"), (0x83d1518, 48, "ptrs"), (0x83d1548, 52, "ptrs"), (0x83d157c, 36, "ptrs"), (0x83d15a0, 60, "ptrs"), (0x83d15dc, 76, "ptrs"), (0x83d1628, 28, "ptrs"), (0x83d1644, 8, "ptrs"), (0x83d164c, 12, "ptrs"), (0x83e5438, 576, "stories"), (0x83e741c, 704, "places"), (0x816b95e, 0, "string")],
                 easy_chat=(0x83dbf84, 0x83de138),
                 rooms=(0x82e7718, 0x82e7800, 0x82e78e8, 0x82e79d0, 0x82e7ab8, 0x82e7ba0, 0x82e7ca0, 0x82e7dbc, 0x82e7eb0, 0x82e7fcc, 0x82e80cc, 0x82e81c0, 0x82e82d0, 0x82e843c, 0x82e85b0, 0x82e86d8, 0x82e8808, 0x82e8948, 0x82e8a78, 0x82e8be8, 0x82e8d3c, 0x82e8ec8, 0x82e9070, 0x82e91c4)),
    "BPEE0": dict(layouts=0x8481dd4, decorations=0x85a5c08, gfx=(0x8505620, 0x3bc), pals=(0x850bbc8, 0x120),
                 rooms=(0x8440880, 0x8440968, 0x8440a50, 0x8440b38, 0x8440c20, 0x8440d08, 0x8440e08, 0x8440f24, 0x8441018, 0x8441134, 0x8441234, 0x8441328, 0x8441438, 0x84415a4, 0x8441718, 0x8441840, 0x8441970, 0x8441ab0, 0x8441be0, 0x8441d50, 0x8441ea4, 0x8442030, 0x84421d8, 0x844232c)),
}


def wake(mapping):
    return [("w16", MAP_REG, mapping), ("delay", 0, 0x400), ("r16", 0x08000000, 2)]


def read_header(lab, mapping):
    """(header info, ROM size) of the cartridge, as maxduo_saves.py reads them."""
    for attempt in range(3):
        res = lab.run(wake(mapping) + [("r8", 0x08000000, 32), ("r8", 0x080000A0, 32)] + M.rom_size_ops()
                      + [("w16", MAP_REG, DUO_MAP)], messages=["ROM copy: reading header"])
        d = [x for _, x in res]
        info = M.describe_header(d[2])
        if info["header_ok"]:
            size = M.rom_size_from(d[3:-1])
            if info["code"][:3] in POKEMON_CODES:   # (lab session 31: LeafGreen measured as 32 MB)
                size = min(size, GAME_ROM_SIZE)
            return info, size, d[1] + bytes(0x80) + d[2]
        print(f"  The header's checksum doesn't match ({d[2].hex(' ')}); reading it again...")
    raise DuoError("the cartridge's header never read cleanly: check it's seated in the DUO")


def read_chunk(lab, mapping, addr):
    ops = wake(mapping) + [("r8", addr, CHUNK), ("crct", addr, CHUNK), ("w16", MAP_REG, DUO_MAP)]
    for attempt in range(3):
        res = lab.run(ops)
        data, gba_crc = res[-2][1], M._w(res[-1][1])
        if zlib.crc32(data) == gba_crc:
            return data
        print(f"\n  The GBA's own checksum of {addr:#010x} disagreed; reading it again...")
    raise DuoError(f"the ROM at {addr:#010x} read differently three times: check the cartridge's contacts")


class Pieces:
    """Reads pieces of the cartridge ROM in batches, each checked against the GBA's own CRC, into a
    full-size image (the rest left zero)."""
    BATCH, SPANS = 0x6000, 32                            # bytes and pieces in one go

    def __init__(self, lab, mapping, size):
        self.lab, self.mapping, self.image, self.got = lab, mapping, bytearray(size), 0
        self.have = bytearray(size // 4)                 # which words have been read
        self.t0 = time.time()

    def read(self, wanted):
        """wanted: (address, length) pairs; returns their bytes, in order."""
        spans = []
        for addr, n in wanted:
            a0, a1 = addr & ~3, (addr + n + 3) & ~3          # (the GBA's CRC works in whole words)
            if not (0x08000000 <= a0 and a1 <= 0x08000000 + len(self.image)):
                raise DuoError(f"a piece at {addr:#010x} lies outside the cartridge: its tables aren't as expected")
            w = (a0 - 0x08000000) // 4                       # only the words not read yet
            for k in range(w, (a1 - 0x08000000) // 4):
                if not self.have[k]:
                    if spans and spans[-1][0] + spans[-1][1] == 0x08000000 + 4 * k:
                        spans[-1] = (spans[-1][0], spans[-1][1] + 4)
                    else:
                        spans.append((0x08000000 + 4 * k, 4))
        batch, total = [], 0
        for span in spans + [None]:
            if span is None or (batch and (total + span[1] > self.BATCH or len(batch) >= self.SPANS)):
                self._batch(batch)
                batch, total = [], 0
            if span is not None:
                batch.append(span)
                total += span[1]
        return [bytes(self.image[a - 0x08000000:a - 0x08000000 + n]) for a, n in wanted]

    def _batch(self, spans):
        if not spans:
            return
        ops = wake(self.mapping)
        for a, n in spans:
            ops += [("r8", a, n), ("crct", a, n)]
        ops.append(("w16", MAP_REG, DUO_MAP))
        for attempt in range(3):
            res = self.lab.run(ops)[1:]                     # (after the wake-up read)
            pairs = [(res[2 * i][1], M._w(res[2 * i + 1][1])) for i in range(len(spans))]
            if all(zlib.crc32(d) == c for d, c in pairs):
                break
            print("\n  The GBA's own checksum disagreed; reading those pieces again...")
        else:
            raise DuoError("pieces of the ROM read differently three times: check the cartridge's contacts")
        for (a, n), (d, _) in zip(spans, pairs):
            self.image[a - 0x08000000:a - 0x08000000 + n] = d
            self.have[(a - 0x08000000) // 4:(a - 0x08000000 + n) // 4] = b"\1" * (n // 4)
            self.got += n
        rate = self.got / max(time.time() - self.t0, 0.01)
        sys.stdout.write(f"\r    {self.got >> 10:,} KB read  ({rate / 1024:.1f} KB/s)   ")
        sys.stdout.flush()

    def lz77(self, addr):
        """Reads a compressed block (the GBA BIOS's LZ77) a piece at a time until it's all there."""
        have = self.read([(addr, 0x800)])[0]
        while True:
            need = lz77_length(have)
            if need is not None:
                if need > len(have):
                    self.read([(addr, need)])
                return
            have = self.read([(addr, len(have) + 0x1000)])[0]


def lz77_length(data):
    """How many bytes the LZ77 block at the start of `data` takes, or None if it runs past the end."""
    if len(data) < 4 or data[0] != 0x10:
        raise DuoError("the room tiles aren't compressed the way the game keeps them: its tables aren't as expected")
    size, src, dst = int.from_bytes(data[1:4], "little"), 4, 0
    while dst < size:
        if src >= len(data):
            return None
        flags = data[src]; src += 1
        for b in range(8):
            if dst >= size:
                break
            if flags & (0x80 >> b):
                if src + 2 > len(data):
                    return None
                dst += (data[src] >> 4) + 3; src += 2
            else:
                if src >= len(data):
                    return None
                dst += 1; src += 1
    return src


def workshop_parts(lab, mapping, info, header):
    """The workshop's pieces of a known Ruby/Sapphire/Emerald, as a full-size image."""
    where = WORKSHOP_PARTS[f"{info['code']}{info['revision']}"]
    p = Pieces(lab, mapping, GAME_ROM_SIZE)
    p.image[0:len(header)] = header
    u32 = lambda b, o: struct.unpack_from("<I", b, o)[0]
    u16 = lambda b, o: struct.unpack_from("<H", b, o)[0]
    ok = lambda a: 0x08000000 <= a < 0x08000000 + GAME_ROM_SIZE

    # the rooms: the 24 layouts (checked by their sizes), and the layout table that lists them
    layouts = p.read([(a, 24) for a in where["rooms"]])
    for k, lay in enumerate(layouts):
        if (u32(lay, 0), u32(lay, 4)) != ROOM_SIZES[k] or not all(ok(u32(lay, f)) for f in (8, 12, 16, 20)):
            raise DuoError("the Secret Base rooms aren't where pret's notes put them for this game: is it a "
                           "different revision? python duo_rom.py --whole copies the whole ROM instead")
    for n in range(0x400, 0x1400, 0x400):
        table = p.read([(where["layouts"], n)])[0]
        if struct.pack("<24I", *where["rooms"]) in table:
            break
    else:
        raise DuoError("the layout table doesn't list the Secret Base rooms as expected")
    # the routes with Secret Bases (gMapLayouts entries 16-49), checked by their sizes; any that
    # aren't as expected are left out (the workshop then shows only its sketch for them)
    import secret_bases
    base_routes = sorted({l["route"] for l in secret_bases.tables().locations.values()})
    ptrs = [u32(table, 4 * (16 + r - 101)) for r in base_routes]
    routes = [lay for r, lay in zip(base_routes, p.read([(a, 24) for a in ptrs if ok(a)]) if all(ok(a) for a in ptrs) else [])
              if (u32(lay, 0), u32(lay, 4)) == ROUTE_TILES[r] and all(ok(u32(lay, f)) for f in (8, 12, 16, 20))]
    layouts = layouts + routes
    # each room's (and route's) map and border, and its two tilesets: tiles (often compressed), palettes, metatiles
    p.read([(u32(l, 8), 8) for l in layouts] + [(u32(l, 12), 2 * u32(l, 0) * u32(l, 4)) for l in layouts])
    sets = sorted({u32(l, f) for l in layouts for f in (16, 20)})
    for ts in p.read([(a, 24) for a in sets]):
        if ts[0]:
            p.lz77(u32(ts, 4))
        else:
            p.read([(u32(ts, 4), 512 * 32)])
        p.read([(u32(ts, 8), 16 * 32), (u32(ts, 12), 512 * 16)])
    # the decorations (121 records of 32 bytes) and each one's tiles
    dec = p.read([(where["decorations"], 121 * 32)])[0]
    if any(dec[32 * k] != k for k in range(121)):
        raise DuoError("the decoration table isn't where pret's notes put it for this game")
    tiles = p.read([(u32(dec, 32 * k + 0x1C), 18) for k in range(121)])
    # the object pictures: every entry of the table (the workshop finds it that way), and the
    # dolls' and cushions' first frames; then the object palettes
    gfx_at, gfx_size = where["gfx"]
    table = p.read([(gfx_at, gfx_size)])[0]
    infos = p.read([(u32(table, 4 * i), 0x24) for i in range(gfx_size // 4)])
    wanted = sorted({u16(tiles[d], 0) for d in SPRITE_DECORATIONS})
    frames = p.read([(u32(infos[g], 0x1C), 8) for g in wanted if g < len(infos)])
    p.read([(u32(f, 0), (u16(infos[g], 8) * u16(infos[g], 10)) // 2) for g, f in zip(wanted, frames)])
    pal_at, pal_size = where["pals"]
    pals = p.read([(pal_at, pal_size)])[0]
    p.read([(u32(pals, 8 * i), 32) for i in range(pal_size // 8) if ok(u32(pals, 8 * i))])
    # the Easy Chat words (Ruby and Sapphire: every group's words, then the table of 22 pointers
    # to them), for the Record Workshop's old man, trends and the rest
    # the games' own lines for the Record Workshop (TV shows, the old man, Dewford, the Battle Tower):
    # pret's tables, then every string they point to (up to 1 KB each; the page reads up to the end mark)
    if "text" in where:
        strings = []
        tables = p.read([(a, size) for a, size, kind in where["text"] if kind != "string"])
        k = 0
        for a, size, kind in where["text"]:
            if kind == "string":
                strings.append(a)
                continue
            t = tables[k]
            k += 1
            if kind == "ptrs":
                strings += [u32(t, 4 * i) for i in range(size // 4)]
            elif kind == "places":
                strings += [u32(t, 8 * i + 4) for i in range(size // 8)]
            elif kind == "stories":
                strings += [u32(t, 16 * i + o) for i in range(size // 16) for o in (4, 8, 12)]
        strings = sorted({x for x in strings if ok(x)})
        p.read([(x, min(0x400, 0x08000000 + GAME_ROM_SIZE - x)) for x in strings])
    if "easy_chat" in where:
        words_at, table_at = where["easy_chat"]
        block = p.read([(words_at, table_at + 22 * 4 - words_at)])[0]
        ptrs = struct.unpack_from("<22I", block, table_at - words_at)
        if ptrs[0] != words_at or any(not words_at <= a < table_at for a in ptrs) or list(ptrs) != sorted(ptrs):
            raise DuoError("the Easy Chat words aren't where pret's notes put them for this game")
    print()
    return bytes(p.image)


def dump(duo, args):
    lab = Lab(duo)
    mapping = getattr(args, "map", None) or 0x0101
    info, size, header = read_header(lab, mapping)
    whole = getattr(args, "whole", False)
    base = M.safe_filename(f"{info['title']} ({info['code']}) rev {info['revision']}")
    out = getattr(args, "out", None) or os.path.join(os.path.dirname(os.path.abspath(__file__)), "roms")
    print(f"  Game: {info['title']} ({info['code']}, revision {info['revision']}), {size >> 20} MB")
    if not whole:
        game = SECRET_BASE_CODES.get(info["code"][:3])
        if not game:
            raise DuoError("this game has no Secret Bases, so the workshop can't use it (it needs Ruby, Sapphire or "
                           "Emerald). To copy its whole ROM anyway: python duo_rom.py --whole")
        if f"{info['code']}{info['revision']}" not in WORKSHOP_PARTS:
            raise DuoError(f"this {game} ({info['code']}, revision {info['revision']}) isn't one whose addresses "
                           "are known yet (English Ruby, Sapphire and Emerald are). python duo_rom.py --whole copies "
                           f"the whole ROM instead, at about 3 KB a second ({size >> 20} MB: well over an hour)")
        os.makedirs(out, exist_ok=True)
        t0 = time.time()
        print("  Reading only what the workshop draws with (the rooms, the decorations, the dolls)...")
        data = workshop_parts(lab, mapping, info, header)
        path = os.path.join(out, base + " - workshop parts.gba")
        with open(path, "wb") as f:
            f.write(data)
        if lab.v3:
            lab.run([], messages=["Workshop parts copied", f"{info['title']}"])
        print(f"Saved: {path}\n  (the workshop's parts of the ROM, in {time.time() - t0:.0f} s; the rest left empty)")
        print("  Open secret_base_workshop.html and choose 'Use my ROM's graphics' to load it.")
        return path, data, info
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, base + ".gba")
    t0, parts = time.time(), []
    for k, addr in enumerate(range(0x08000000, 0x08000000 + size, CHUNK)):
        parts.append(read_chunk(lab, mapping, addr))
        done = (k + 1) * CHUNK
        rate = done / max(time.time() - t0, 0.01)
        filled = 30 * done // size
        sys.stdout.write(f"\r    [{'#' * filled}{'.' * (30 - filled)}] {done >> 10:,} of {size >> 10:,} KB"
                         f"  (about {max(0, (size - done) / rate):.0f} s left)   ")
        sys.stdout.flush()
    print()
    data = b"".join(parts)
    with open(path, "wb") as f:
        f.write(data)
    if lab.v3:
        lab.run([], messages=["ROM copied to PC", f"{size >> 20} MB, CRC {zlib.crc32(data):08X}"])
    print(f"Saved: {path}\n  ({len(data):,} bytes in {time.time() - t0:.0f} s; header bytes 0x20-0x9F read as zeros "
          "through the DUO)")
    return path, data, info


def main(argv=None):
    ap = argparse.ArgumentParser(prog="duo_rom.py", description="Copy what the Secret Base Workshop needs from the "
                                 "cartridge in the DUO to a ROM file (read-only).")
    ap.add_argument("--whole", action="store_true", help="copy the whole ROM, any game (slow: well over an hour)")
    ap.add_argument("--out", metavar="FOLDER", help="where to save it (default: a 'roms' folder beside this tool)")
    ap.add_argument("--map", type=lambda v: int(v, 0), default=None, help="cartridge mapping (default 0x101, as for saves)")
    ap.add_argument("--wait", type=int, default=120, help="seconds to wait for the GBA to be switched on (default 120)")
    args = ap.parse_args(argv)
    import runlog
    runlog.start("duo_rom", argv)
    t = UsbTransport()
    try:
        duo = MaxDuo(t)
        version = duo.connect(wait_s=args.wait)
        print(f"Connected to Action Replay MAX DUO (Datel protocol {version >> 8}.{version & 0xFF:02d})")
        if not duo.is_v3():
            raise DuoError("copying a ROM needs the Reckless firmware (v3.1 or later)")
        print("Copying from the cartridge (reads only)...")
        dump(duo, args)
    except DuoError as err:
        sys.exit(f"\nStopped: {err}")
    except KeyboardInterrupt:
        sys.exit("\nStopped (Ctrl+C): nothing was saved.")
    except Exception as err:
        if type(err).__name__ in ("USBTimeoutError", "USBError"):
            sys.exit(f"\nThe Action Replay stopped answering ({err}).\n"
                     "Check the console batteries and that USB SERVER MODE is still showing.")
        raise
    finally:
        t.close()


if __name__ == "__main__":
    main()
