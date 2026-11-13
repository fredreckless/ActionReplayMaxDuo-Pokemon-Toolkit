"""savegen.py - make a Pokemon save for the rehearsals from a ROM alone, with the game's own code.

    python3 virtual/savegen/savegen.py --rom ruby.gba --out DIR

What it does, and why each step is the game's own work:

1. Boots the ROM with no save and plays the opening by button presses until the player stands in
   the overworld and the START menu opens (the game has made a new game in RAM: trainer ID,
   options, the lot).
2. Sets in RAM only what the Cable Club needs: the player's name, a party of six made-up Pokemon
   (the toolkit's own .pk3 code), berries and a Pokeblock Case, and the flags (the Pokemon and the
   Pokedex received, the cities visited, Mystery Events on). It also points the game's own
   "continue at a special warp" (gSaveBlock2.specialSaveWarp and warp1, which the game uses
   after a link save) at a Pokemon Center's upper floor.
3. Opens START, chooses SAVE, answers YES and lets the game write the save: so the save is in
   the game's own layout, with its own checksums, for whatever language the ROM is.
4. Boots again from that save and, for each rehearsal, walks up to the attendant and talks until
   the question is on screen, then keeps a save state there (states named as the rehearsals
   want them). The warp for each state is the game's own special warp again, set on the title
   menu before CONTINUE, so the save on disk is the same for every state.

Nothing of Nintendo's is kept in the repository: the ROM is passed in, and the save and states
are written to --out. The made-up Pokemon are the toolkit's (no event's data).
"""
import argparse, os, struct, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
VIRTUAL = os.path.dirname(HERE)
TOOLKIT = os.path.dirname(VIRTUAL)
sys.path.insert(0, os.path.join(VIRTUAL, "runner"))
sys.path.insert(0, TOOLKIT)
sys.path.insert(0, HERE)
from vduo import Runner  # noqa: E402
import profiles  # noqa: E402


def gen3_text(text, n):
    """English Gen 3 text, 0xFF-terminated and padded to n bytes."""
    out = bytearray()
    for c in text:
        out.append(0 if c == " " else 0xBB + ord(c) - 65 if c.isupper() else
                   0xD5 + ord(c) - 97 if c.islower() else 0xA1 + int(c))
    return bytes(out + b"\xff")[:n].ljust(n, b"\xff")


class Game:
    """One GBA running the ROM (the DUO's GBA stays switched off), with the profile's addresses."""

    def __init__(self, rom, prof, save=None, log=print):
        self.p, self.log = prof, log
        blank = os.path.join(os.environ.get("TMPDIR", "/tmp"), "savegen_blank_fw.bin")
        if not os.path.exists(blank):
            with open(blank, "wb") as f:
                f.write(bytes(0x80000))        # the DUO is never switched on: its flash doesn't matter
        self.v = Runner(duo_fw=blank, partner=rom, partner_save=save, duo_player=1, wait_for_hello=True)
        self.frames = 0

    def close(self):
        self.v.close()

    # ---- plumbing
    def run(self, n):
        self.v.run_frames("partner", n)
        self.frames += n

    def read(self, addr, n):
        return self.v.read("partner", addr, n)

    def write(self, addr, data):
        self.v.write("partner", addr, data)

    def u32(self, addr):
        return struct.unpack("<I", self.read(addr, 4))[0]

    def tap(self, *keys, hold=3, gap=8):
        self.v.keys("partner", *keys)
        self.run(hold)
        self.v.keys("partner")
        self.run(gap)

    def callback2(self):
        return self.u32(self.p.gMain + 4) & ~1

    def tasks(self):
        t = self.read(self.p.gTasks, 16 * 40)
        return {struct.unpack_from("<I", t, i * 40)[0] & ~1 for i in range(16) if t[i * 40 + 4]}

    def has_task(self, name):
        return self.p.sym[name] & ~1 in self.tasks()

    def screenshot(self, path):
        self.run(1)
        self.v.screenshot("partner", path)

    def wait(self, cond, frames, step=10, what="it"):
        for _ in range(0, frames, step):
            if cond():
                return
            self.run(step)
        if not cond():
            raise RuntimeError(f"timed out waiting for {what}")

    # ---- the game's RAM
    def sb1(self):
        """gSaveBlock1: fixed in Ruby; in Emerald and FireRed/LeafGreen it moves (gSaveBlock1Ptr)."""
        return self.u32(self.p.sb1_ptr) if hasattr(self.p, "sb1_ptr") else self.p.sb1

    def sb2(self):
        return self.u32(self.p.sb2_ptr) if hasattr(self.p, "sb2_ptr") else self.p.sb2

    def qty_key(self):
        """Emerald and FireRed/LeafGreen keep bag quantities XORed with the save's encryption key."""
        if not hasattr(self.p, "SB2_KEY"):
            return 0
        return self.u32(self.sb2() + self.p.SB2_KEY) & 0xFFFF

    def flag(self, n, on=True):
        a = self.sb1() + self.p.SB1_FLAGS + n // 8
        b = self.read(a, 1)[0]
        self.write(a, bytes([b | 1 << (n % 8) if on else b & ~(1 << (n % 8))]))

    def objects(self):
        t = self.read(self.p.gObjectEvents, 16 * 0x24)
        return [(i, t[i * 0x24 + 8], struct.unpack_from("<hh", t, i * 0x24 + 0x10))
                for i in range(16) if t[i * 0x24] & 1]

    def player_xy(self):
        for _, lid, xy in self.objects():
            if lid == 0xFF:
                return xy[0] - 7, xy[1] - 7         # the map's own coordinates (no border)
        return None

    def in_overworld(self):
        return self.callback2() == self.p.sym["CB2_Overworld"] & ~1


# ------------------------------------------------------------------ step 1: the opening

def play_opening(g):
    """Press through the intro, the title screen, NEW GAME and the professor's talk. Mashing A
    picks the first choice everywhere (a boy) and types a name in the naming screen, which step 2
    replaces; then wait until START opens a menu, which only happens once the player has control."""
    p = g.p
    naming = p.sym[p.NAMING_CB2] & ~1 if p.NAMING_CB2 else None     # (None: mash A through it)
    for i in range(4000):
        cb2 = g.callback2()
        if cb2 == p.sym["CB2_Overworld"] & ~1:
            break
        if cb2 == p.sym["CB2_MainMenu"] & ~1 and i % 2:
            g.tap("A")
        elif cb2 == naming:
            # a naming screen (FireRed/LeafGreen: the rival's too): START moves to OK, A finishes (an
            # empty name gets one of the game's own); then wait for the screen to go
            g.run(60)
            g.tap("START", gap=20)
            g.tap("A", gap=30)
            for _ in range(60):
                if g.callback2() != naming:
                    break
                g.run(10)
        else:
            g.tap("A", gap=6)
    else:
        raise RuntimeError("the opening didn't reach the overworld")
    g.log(f"  in the overworld after {g.frames} frames")
    # wait until START really opens the menu (the opening's scenes hold the controls for a while)
    for _ in range(200):
        g.write(p.sNumStartMenuActions, b"\0")
        g.tap("START", gap=20)
        if g.read(p.sNumStartMenuActions, 1)[0]:
            g.tap("B", gap=20)
            g.wait(lambda: not g.has_task("Task_StartMenu"), 300, what="the START menu to close")
            g.log(f"  the player has control after {g.frames} frames")
            return
        g.run(30)
    raise RuntimeError("START never opened the menu")


# ------------------------------------------------------------------ step 2: what the Cable Club needs

def make_mon(species, level, otid, ot_name, pid, nickname=None, game=2, lang=2):
    """A made-up Pokemon the player caught, as a 100-byte party Pokemon in the game's own form:
    the toolkit's .pk3 code works out the encryption, the checksum and the stats."""
    import duo_events as E
    return E.pk3_party_form(make_pk3(species, level, otid, ot_name, pid, nickname, game, lang))


def make_pk3(species, level, otid, ot_name, pid, nickname=None, game=2, lang=2):
    """The same Pokemon as a .pk3 (PKHeX's decrypted 80-byte form)."""
    import duo_battle as B
    import duo_events as E
    moves = B.default_moves(species, level)
    growth = E.PK3_BASE_STATS[(species - 1) * 7 + 6]
    exp = E.pk3_exp_for_level(growth, level)
    pp = [B.MOVES[m][4] for m in moves] + [0] * (4 - len(moves))
    ms = list(moves) + [0] * (4 - len(moves))
    g = struct.pack("<HHIBBH", species, 0, exp, 0, 70, 0)
    a = struct.pack("<4H4B", *ms, *pp)
    e = bytes(12)
    ivs = [20, 20, 20, 20, 20, 20]
    ivword = sum(v << (5 * i) for i, v in enumerate(ivs))
    origin = level | game << 7 | 4 << 11     # met at this level, in this game (2 Ruby, 3 Emerald,
    #                                           4 FireRed, 5 LeafGreen), in a Poke Ball (OT a boy)
    met = 0x10 if game in (2, 3) else 0x65    # Route 101; Route 1 in Kanto (FireRed/LeafGreen)
    m = struct.pack("<BBHII", 0, met, origin, ivword, 0)
    plain = g + a + e + m
    checksum = sum(struct.unpack("<24H", plain)) & 0xFFFF
    name = nickname or B.species_name(species)
    if lang == 1:                             # (Japanese names: 5 characters at most)
        name = name[:5]
    head = struct.pack("<II", pid, otid) + gen3_text(name, 10) + struct.pack("<H", lang)
    head += gen3_text(ot_name, 7) + b"\0" + struct.pack("<HH", checksum, 0)
    pk3 = head + plain
    problems = B.check_legal(pk3)[0]
    if problems:
        raise ValueError(f"{name}: {problems}")
    return pk3


def set_up(g, name, party, warp):
    p = g.p
    sb1, sb2 = g.sb1(), g.sb2()
    key = g.qty_key()
    name = name[:p.NAME_LENGTH]
    g.write(sb2 + 0, gen3_text(name, 8))
    otid = struct.unpack("<I", g.read(sb2 + 0x0A, 4))[0]
    # options: fast text (bits 0-2 of 0x14)
    o = struct.unpack("<H", g.read(sb2 + 0x14, 2))[0]
    g.write(sb2 + 0x14, struct.pack("<H", (o & ~7) | 2))
    # the party, live (the save copies it from here)
    mons = b""
    for i, sp in enumerate(party):
        mons += make_mon(B_species(sp), p.PARTY_LEVEL, otid, name, pid=0x1000_0000 + 0x0101_0101 * (i + 1) + i,
                         game=p.ORIGIN_GAME, lang=p.LANGUAGE)
    g.write(p.gPlayerParty, mons.ljust(600, b"\0"))
    g.write(p.gPlayerPartyCount, bytes([len(party)]))
    # the bag: a Pokeblock Case among the key items, ten of each of the first twenty berries
    if p.ITEM_POKEBLOCK_CASE:                      # (FireRed/LeafGreen have none)
        g.write(sb1 + p.SB1_KEYITEMS, struct.pack("<HH", p.ITEM_POKEBLOCK_CASE, 1 ^ key))
    berries = b"".join(struct.pack("<HH", p.ITEM_CHERI_BERRY + i, 10 ^ key) for i in range(20))
    g.write(sb1 + p.SB1_BERRIES, berries)
    for f in p.FLAGS:
        g.flag(f)
    # where CONTINUE puts the player: the game's own special warp (warp1, specialSaveWarp)
    point_continue(g, warp)
    g.log(f"  set up {name}: trainer {otid & 0xFFFF:05d}, {len(party)} Pokemon, berries, flags")


def B_species(name):
    import duo_battle as B
    return B.species_id(name)


def point_continue(g, warp):
    group, num, x, y = warp
    g.write(g.sb1() + 0x0C, struct.pack("<bbbxhh", group, num, -1, x, y))
    a = g.sb2() + 0x09                          # (Emerald and FireRed/LeafGreen: bit 0 of the flags)
    g.write(a, bytes([g.read(a, 1)[0] | 1]))


# ------------------------------------------------------------------ step 3: SAVE

def save_game(g):
    p = g.p
    for _ in range(20):
        g.write(p.sNumStartMenuActions, b"\0")
        g.tap("START", gap=20)
        if g.read(p.sNumStartMenuActions, 1)[0]:
            break
        g.run(30)
    n = g.read(p.sNumStartMenuActions, 1)[0]
    actions = list(g.read(p.sCurrentStartMenuActions, n))
    want = actions.index(p.MENU_ACTION_SAVE)
    for _ in range(12):
        cur = g.read(p.sStartMenuCursorPos, 1)[0]
        if cur == want:
            break
        g.tap("DOWN" if cur < want else "UP", gap=8)
    g.tap("A", gap=30)
    # "Would you like to save the game?" (YES is the first choice; with a save already there,
    # "overwrite?" too), the saving, then "<name> saved the game.": A until the START menu's task
    # has gone. (The save's questions are the menu's own callbacks, not a task to watch.)
    presses = 0
    while g.has_task("Task_StartMenu"):
        if presses == 40:
            raise RuntimeError("the START menu didn't close after SAVE")
        g.tap("A", gap=40)
        presses += 1
    g.run(60)
    g.log(f"  saved through START > SAVE ({presses} presses of A)")


def check_save(data, sb2_name):
    """A Gen 3 flash save: 14 sectors a slot, each with its id, checksum and signature."""
    best = None
    for slot in (0, 1):
        ids, counter = set(), None
        for s in range(14):
            sec = data[(slot * 14 + s) * 0x1000:(slot * 14 + s + 1) * 0x1000]
            sid, ck, sig, cnt = struct.unpack_from("<HHII", sec, 0xFF4)
            if sig != 0x08012025:
                break
            size = 3968 if sid != 13 else 2000           # (Ruby's last sector holds 0x7D0 bytes)
            words = struct.unpack_from(f"<{size // 4}I", sec, 0)
            t = sum(words) & 0xFFFFFFFF
            if ((t >> 16) + t) & 0xFFFF != ck:
                break
            ids.add(sid)
            counter = cnt
        if len(ids) == 14 and (best is None or counter > best[1]):
            best = (slot, counter)
    return best


# ------------------------------------------------------------------ step 4: the states

def continue_to(g, warp):
    """From a fresh boot with the save: title, then on the menu point the special warp, CONTINUE."""
    p = g.p
    for _ in range(3000):
        if g.callback2() == p.sym["CB2_MainMenu"] & ~1:
            break
        g.tap("A", gap=10)
    g.run(60)
    if warp:
        point_continue(g, warp)
    g.tap("A", gap=10)                             # CONTINUE is the first item
    g.wait(g.in_overworld, 1200, what="the overworld")
    g.wait(lambda: g.player_xy() == (warp[2], warp[3]) if warp else True, 600, what="the player")
    g.run(60)


def talk_until_question(g, face, task):
    g.tap(face, hold=2, gap=12)                     # a short tap only turns
    for _ in range(60):
        if any(g.has_task(t) for t in task):
            g.run(30)
            return
        g.tap("A", gap=20)
    raise RuntimeError("no question came")


def make_states(rom, sav, prof, out, log):
    made = []
    for st in prof.STATES:
        g = Game(rom, prof, save=sav, log=log)
        try:
            if st["kind"] == "talk":
                continue_to(g, st["warp"])
                talk_until_question(g, st["face"], st["task"])
            elif st["kind"] == "title_menu":
                title_menu_item(g, st)
            path = os.path.join(out, st["name"] + ".state")
            g.v.state_save("partner", path)
            g.screenshot(os.path.join(out, st["name"] + ".png"))
            made.append(path)
            log(f"  {st['name']}.state")
        finally:
            g.close()
    return made


def title_menu_item(g, st):
    """An item further down the title menu (MYSTERY EVENTS in Ruby, MYSTERY GIFT in Emerald), left
    waiting at its first screen: `downs` presses of DOWN from CONTINUE, then A, then until the
    item's own task is running (or its callback is), and a moment more."""
    p = g.p
    for _ in range(3000):
        if g.callback2() == p.sym["CB2_MainMenu"] & ~1:
            break
        g.tap("A", gap=10)
    g.run(60)
    for _ in range(st["downs"]):
        g.tap("DOWN", gap=10)
    if st.get("select_only"):                     # left highlighted, for the rehearsal to press A
        g.run(st.get("settle", 60))
        return
    g.tap("A", gap=30)
    want = p.sym[st["until"]] & ~1
    for _ in range(40):
        if st.get("press_first"):               # (Ruby's MYSTERY EVENTS: a press before "Link standby")
            g.tap("A", gap=20)
        if g.callback2() == want or want in g.tasks():
            g.run(st.get("settle", 60))
            return
        if not st.get("press_first"):
            g.tap("A", gap=20)
    raise RuntimeError(f"didn't reach {st['until']}")


def write_kit_pk3s(folder, log):
    """The DUO's own made-up Pokemon (trainer DUO, ID 12345): nothing from an event or a real game."""
    os.makedirs(folder, exist_ok=True)
    for fname, sp, lv, pid in (("offer.pk3", "SWELLOW", 30, 0x2468ACE1), ("team1.pk3", "METAGROSS", 50, 0x13579BDF),
                               ("team2.pk3", "ALTARIA", 50, 0x0F1E2D3C)):
        with open(os.path.join(folder, fname), "wb") as f:
            f.write(make_pk3(B_species(sp), lv, 54321 << 16 | 12345, "DUO", pid))     # (from Ruby)
    log(f"  made-up Pokemon for the DUO in {folder}: offer.pk3, team1.pk3, team2.pk3")


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rom", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="TESTER", help="the player's name (default TESTER)")
    ap.add_argument("--no-states", action="store_true")
    ap.add_argument("--pk3s", help="also write made-up Pokemon for the DUO's side here: offer.pk3 (to trade), "
                                   "team1.pk3 and team2.pk3 (its Colosseum team)")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    prof = profiles.for_rom(a.rom)
    log = lambda s: print(s, flush=True)
    log(f"{prof.TITLE}: a new save")
    t0 = time.monotonic()
    g = Game(a.rom, prof, log=log)
    try:
        play_opening(g)
        set_up(g, a.name, prof.PARTY, prof.HOME)
        save_game(g)
        sav = os.path.join(a.out, prof.SAVE_NAME)
        g.v.save_sav("partner", sav)
        g.screenshot(os.path.join(a.out, "saved.png"))
    finally:
        g.close()
    data = open(sav, "rb").read()
    ok = check_save(data, a.name)
    if not ok:
        raise SystemExit("FAIL: the game didn't write a complete save")
    log(f"  {sav}: slot {ok[0]}, save number {ok[1]} ({time.monotonic() - t0:.0f} s)")
    if not a.no_states:
        make_states(a.rom, sav, prof, a.out, log)
    if a.pk3s:
        write_kit_pk3s(a.pk3s, log)
    log("PASS")


if __name__ == "__main__":
    main()
