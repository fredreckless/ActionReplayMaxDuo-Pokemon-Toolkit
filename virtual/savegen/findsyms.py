"""findsyms.py - find a game's addresses in another language's ROM, from pret's symbols for the
English ROM. (pret has symbols for the English games only; the other languages' code is nearly
the same, but moved about, and their RAM is laid out a little differently.)

    python3 virtual/savegen/findsyms.py ENGLISH.gba ENGLISH.sym OTHER.gba NAME [NAME ...]
    python3 virtual/savegen/findsyms.py table emerald|leafgreen ENGLISH.gba ENGLISH.sym OTHER.gba ...
        (the second prints profiles.py's DERIVED entries for those ROMs)

Code: each function's bytes in the English ROM, with the words that hold addresses and the BL
instructions masked out (they differ when anything moves), searched for in the other ROM; the
match nearest the English address wins, and it must be the only exact one in a window.
RAM: a few English functions that load the variable's address from their literal pool are found
in the other ROM as above, and the word at the same place in each is read; they must agree.
Run it here, once; the results go into profiles.py as facts about each ROM.
"""
import bisect, struct, sys

ROM = 0x08000000


class Syms:
    def __init__(self, path):
        self.addr, self.size, rows = {}, {}, []
        for line in open(path):
            p = line.split()
            if len(p) < 4:
                continue
            a, n = int(p[0], 16), p[3]
            sz = int(p[2], 16)
            self.addr[n], self.size[n] = a, sz
            if ROM <= a < ROM + 0x2000000 and sz:
                rows.append((a, sz, n))
        rows.sort()
        self.funcs = rows
        self.starts = [r[0] for r in rows]


def masked(rom, start, size):
    """The function's bytes and a mask (1 = must match)."""
    b = rom[start - ROM:start - ROM + size]
    m = bytearray([1]) * len(b)
    i = 0
    while i + 1 < len(b):                              # BL: 0xF000-0xF7FF then 0xF800-0xFFFF
        h1, h2 = struct.unpack_from("<H", b, i)[0], struct.unpack_from("<H", b, i + 2)[0] if i + 3 < len(b) else 0
        if 0xF000 <= h1 < 0xF800 and h2 >= 0xF800:
            m[i:i + 4] = b"\0\0\0\0"
            i += 4
            continue
        i += 2
    off = (4 - (start % 4)) % 4
    for j in range(off, len(b) - 3, 4):                # literal-pool words that look like addresses
        w = struct.unpack_from("<I", b, j)[0]
        if 0x02000000 <= w < 0x04000000 or ROM <= w < 0x0A000000:
            m[j:j + 4] = b"\0\0\0\0"
    return b, m


def find_function(eng, other, start, size, window=0x400000):
    b, m = masked(eng, start, size)
    if size < 12:
        return None
    # anchor: the longest fully-matched run
    best, run_s, best_s = 0, 0, 0
    for i in range(len(m) + 1):
        if i == len(m) or not m[i]:
            if i - run_s > best:
                best, best_s = i - run_s, run_s
            run_s = i + 1
    if best < 8:
        return None
    anchor = bytes(b[best_s:best_s + best])
    hits = []
    pos = other.find(anchor)
    while pos != -1:
        cand = pos - best_s
        if cand >= 0 and cand % 2 == 0 and all(not m[k] or other[cand + k] == b[k] for k in range(len(b))):
            hits.append(cand + ROM)
        pos = other.find(anchor, pos + 1)
    if not hits:
        return None
    hits.sort(key=lambda h: abs(h - start))
    if len(hits) > 1 and abs(hits[1] - start) - abs(hits[0] - start) < 0x100:
        return None                                    # two equally good: ambiguous
    if abs(hits[0] - start) > window:
        return None
    return hits[0]


def users_of(eng, syms, value, limit=12):
    """English functions whose literal pools hold `value` (and where in them)."""
    word = struct.pack("<I", value)
    out = []
    pos = eng.find(word)
    while pos != -1 and len(out) < 4000:
        if pos % 4 == 0:
            a = pos + ROM
            i = bisect.bisect_right(syms.starts, a) - 1
            if i >= 0:
                fs, fz, fn = syms.funcs[i]
                if fs <= a < fs + fz and fz <= 0x1000:
                    out.append((fz, fs, a - fs, fn))
        pos = eng.find(word, pos + 1)
    out.sort()
    return out[:limit]


def find_ram(eng, other, syms, value):
    votes = {}
    for fz, fs, off, fn in users_of(eng, syms, value):
        hit = find_function(eng, other, fs, fz)
        if hit is None:
            continue
        w = struct.unpack_from("<I", other, hit - ROM + off)[0]
        votes[w] = votes.get(w, 0) + 1
    if not votes:
        return None, 0, 0
    w, n = max(votes.items(), key=lambda kv: kv[1])
    return w, n, sum(votes.values())


def by_neighbours(eng, other, syms, start, size, reach=0x1800):
    i = bisect.bisect_left(syms.starts, start)
    shifts = []
    for direction in (-1, 1):
        j = i + direction if direction > 0 else i - 1
        while 0 <= j < len(syms.funcs) and abs(syms.funcs[j][0] - start) < reach:
            fs, fz, _ = syms.funcs[j]
            if fz >= 0x30 and fs != start:
                hit = find_function(eng, other, fs, fz)
                if hit is not None:
                    shifts.append(hit - fs)
                    break
            j += direction
    if len(shifts) != 2 or shifts[0] != shifts[1]:
        return None
    cand = start + shifts[0]
    b, m = masked(eng, start, size)
    o = other[cand - ROM:cand - ROM + size]
    return cand if all(not m[k] or o[k] == b[k] for k in range(len(b))) else None


def find(eng, esym, other, name):
    a = esym.addr[name]
    if a >= ROM:
        hit = find_function(eng, other, a, esym.size[name])
        if hit is not None:
            return hit, None
        # small functions are often byte-for-byte the same as others (a CB2 that just runs the
        # tasks, the sprites and the palette fade): try where code stores a pointer to it, then the
        # shift of its neighbours in the same file (code in one file moves together)
        w, n, total = find_ram(eng, other, esym, a | 1)
        if w is not None:
            return w & ~1, (n, total)
        return by_neighbours(eng, other, esym, a, esym.size[name]), None
    w, n, total = find_ram(eng, other, esym, a)
    return w, (n, total)


# What profiles.py needs, by its own names, and pret's name for each.
NEEDS = {
    "emerald": (dict(gMain="gMain", gTasks="gTasks", gObjectEvents="gObjectEvents",
                     gPlayerPartyCount="gPlayerPartyCount", gPlayerParty="gPlayerParty",
                     sb1_ptr="gSaveBlock1Ptr", sb2_ptr="gSaveBlock2Ptr", sStartMenuCursorPos="sStartMenuCursorPos",
                     sNumStartMenuActions="sNumStartMenuActions", sCurrentStartMenuActions="sCurrentStartMenuActions"),
                dict(CB2_Overworld="CB2_Overworld", CB2_MainMenu="CB2_MainMenu", CB2_NamingScreen="CB2_NamingScreen",
                     Task_StartMenu="Task_ShowStartMenu", Task_HandleYesNoInput="Task_HandleYesNoInput",
                     Task_HandleMultichoiceInput="Task_HandleMultichoiceInput", Task_MysteryGift="Task_MysteryGift",
                     CB2_PartyMenu="CB2_UpdatePartyMenu")),
}
NEEDS["leafgreen"] = (dict(NEEDS["emerald"][0], sNumStartMenuActions="sNumStartMenuItems",
                           sCurrentStartMenuActions="sStartMenuOrder"),
                      dict(NEEDS["emerald"][1], Task_StartMenu="Task_StartMenuHandleInput",
                           Task_HandleYesNoInput="Task_YesNoMenu_HandleInput",
                           Task_HandleMultichoiceInput="Task_MultichoiceMenu_HandleInput"))


def table(game, eng, symp, others):
    E, S = open(eng, "rb").read(), Syms(symp)
    ram, code = NEEDS[game]
    h = lambda v: "None" if v is None else f"0x{v:08X}"
    for path in others:
        O = open(path, "rb").read()
        d = {k: find(E, S, O, n)[0] for k, n in ram.items()}
        c = {k: find(E, S, O, n)[0] for k, n in code.items()}
        print(f'    "{O[0xAC:0xB0].decode()}": dict(' + ", ".join(f"{k}={h(v)}" for k, v in d.items()) + ",")
        print("                 sym=dict(" + ", ".join(f"{k}={h(v)}" for k, v in c.items()) + ")),")


def main():
    if sys.argv[1] == "table":
        return table(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:])
    eng, symp, oth = sys.argv[1:4]
    E, O, S = open(eng, "rb").read(), open(oth, "rb").read(), Syms(symp)
    for name in sys.argv[4:]:
        v, votes = find(E, S, O, name)
        en = S.addr[name]
        print(f"{name:32s} en {en:08X}  ->  {('%08X' % v) if v is not None else 'NOT FOUND'}"
              + (f"  ({votes[0]} of {votes[1]} agree)" if votes else ""))


if __name__ == "__main__":
    main()
