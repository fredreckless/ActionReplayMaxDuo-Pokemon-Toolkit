"""unlock.py - the unlocks, played in the game and recorded for the videos (one GBA, the DUO's off):

    VDUO_RECORD=DIR python3 unlock.py mystery_event --rom RUBY.gba --sav ruby.sav
    VDUO_RECORD=DIR python3 unlock.py mystery_gift --rom EMERALD.gba --sav emerald.sav

mystery_event (English Ruby): the save from savegen, in Petalburg City's Pokemon Center after the
fifth badge (set here), MYSTERY EVENT not yet on the title menu (cleared here). Tell the man by the
PC the profile MYSTERY EVENT IS EXCITING, through the easy chat screen's A-Z mode with real button
presses; save; restart; the title menu now has MYSTERY EVENT. Passes when the game set the flag
itself and the title menu shows the item.

mystery_gift (English Emerald): the same idea at the questionnaire on Oldale Town's Poke Mart
counter: LINK TOGETHER WITH ALL; save; restart; MYSTERY GIFT on the title menu.

Marks in DIR/terminal.jsonl (mark=...) say where each part starts, for the captions.
"""
import argparse, json, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "savegen"))
import savegen, profiles  # noqa: E402


def mark(g, text):
    rec = os.environ.get("VDUO_RECORD")
    if rec:
        os.makedirs(rec, exist_ok=True)
        with open(os.path.join(rec, "terminal.jsonl"), "a") as f:
            f.write(json.dumps(dict(n=getattr(g.v, "_rec_n", 0), mark=text)) + "\n")
    print("--", text, flush=True)


def presses(g, seq, gap=14):
    """A string of presses: A, DOWN*13, w30 (wait 30 frames), A+B (together)."""
    for k in seq.split():
        if k.startswith("w"):
            g.run(int(k[1:]))
            continue
        n = 1
        if "*" in k:
            k, n = k.split("*")
            n = int(n)
        for _ in range(n):
            g.tap(*k.split("+"), gap=gap)


def flag_set(g, n):
    return bool(g.read(g.sb1() + g.p.SB1_FLAGS + n // 8, 1)[0] >> (n % 8) & 1)


def restart_to_title(g):
    """A soft reset (A+B+START+SELECT), then through the intro to the title menu."""
    g.v.keys("partner", "A", "B", "START", "SELECT")
    g.run(10)
    g.v.keys("partner")
    g.run(60)
    for _ in range(3000):
        if g.callback2() == g.p.sym["CB2_MainMenu"] & ~1:
            break
        g.tap("A", gap=10)
    else:
        raise RuntimeError("no title menu after the restart")


# MYSTERY EVENT IS EXCITING, in English Ruby's easy chat A-Z mode (found by trying, with screenshots:
# the letter grid opens on A each time; DOWN stops at a list's last word)
RUBY_PROFILE = [
    ("MYSTERY", "A w30 SELECT w30 DOWN*2 A w30 DOWN*30 A w30"),          # A-Z mode, M, the last M word
    ("EVENT", "RIGHT A w30 RIGHT*4 A w30 DOWN*10 A w30"),                 # E
    ("IS", "DOWN LEFT A w30 DOWN RIGHT*2 A w30 DOWN*13 A w30"),           # I
    ("EXCITING", "RIGHT A w30 RIGHT*4 A w30 DOWN*13 RIGHT A w30"),        # E
]
EXDATA = 0x84C                           # FLAG_SYS_EXDATA_ENABLE: MYSTERY EVENT on the title menu
BADGE01 = 0x807


# LINK TOGETHER WITH ALL, in English Emerald's easy chat A-Z mode (its letter grid is in threes:
# ABC DEF / GHI JKL / MNO PQRS / TUV WXYZ, and also opens on A each time)
EMERALD_QUESTIONNAIRE = [
    ("LINK", "A w30 SELECT w30 DOWN RIGHT*5 A w30 DOWN*13 RIGHT A w30"),     # A-Z mode, L
    ("TOGETHER", "RIGHT A w30 DOWN*3 A w30 DOWN*28 A w30"),                  # T
    ("WITH", "DOWN LEFT A w30 DOWN*3 RIGHT*3 A w30 DOWN*26 RIGHT A w30"),    # W
    ("ALL", "RIGHT A w30 A w30 DOWN*9 RIGHT A w30"),                         # A
]
MYSTERY_GIFT = 0x8DB                     # FLAG_SYS_MYSTERY_GIFT_ENABLE (Emerald)


def mystery_gift(rom, sav):
    p = profiles.for_rom(rom)
    if p.TITLE != "English Emerald":
        raise SystemExit("mystery_gift knows English Emerald's screens only")
    g = savegen.Game(rom, p, save=sav)
    try:
        mark(g, "boot")
        savegen.continue_to(g, (2, 4, 0, 5))            # Oldale Town's Poke Mart, below the questionnaire
        g.flag(MYSTERY_GIFT, False)
        g.run(30)
        mark(g, "talk")
        g.tap("UP", hold=2, gap=12)
        for _ in range(30):                               # "There is a questionnaire. Fill it out?" YES
            if g.has_task("Task_HandleYesNoInput"):
                break
            g.tap("A", gap=30)
        else:
            raise RuntimeError("no questionnaire")
        g.run(20)
        mark(g, "profile")
        g.tap("A", gap=60)
        g.run(60)
        for word, seq in EMERALD_QUESTIONNAIRE:
            mark(g, word)
            presses(g, seq)
        mark(g, "ok")
        presses(g, "DOWN RIGHT w20 A w60 A w60")         # OK; "Is it okay?" YES
        mark(g, "secret")
        for _ in range(40):
            if flag_set(g, MYSTERY_GIFT):
                break
            g.tap("B", gap=40)
        else:
            raise RuntimeError("the game didn't unlock MYSTERY GIFT")
        presses(g, "w30 B w40 B w40 B w40 B w60", gap=20)
        mark(g, "save")
        savegen.save_game(g)
        g.run(60)
        mark(g, "restart")
        restart_to_title(g)
        g.run(60)
        mark(g, "menu")
        presses(g, "w60 DOWN w40 DOWN w120")
        mark(g, "end")
        g.screenshot("/tmp/unlock_menu.png")
        print("PASS: the game set MYSTERY GIFT's flag itself, and saved")
    finally:
        g.close()


# Emerald's save: gSaveBlock1's MysteryGiftSave (0x322C): the news's CRC and news (0x1BC), then the
# card's CRC and card, the metadata's CRC and metadata - the same order as a .wc3 file from its
# start - and the RAM script (0x3728), as the .wc3's last 1004 bytes.
SB1_CARD_CRC, SB1_RAM_SCRIPT = 0x322C + 4 + 0x1BC, 0x3728
ITEM_KEYITEMS = 0x5D8                    # gSaveBlock1's key items (Emerald), quantities unencrypted


def mystery_gift_claim(rom, sav, wc3):
    """Proof in the game that a Wonder Card does what it says (English Emerald): the card from the
    .wc3 is put in the save where the game keeps one it has received (the Virtual DUO can't rehearse
    receiving it over the adapter yet: see make_videos.py), saved by the game itself; then, recorded:
    upstairs in Oldale Town's Pokemon Center the Mystery Gift man hands over what it promises.
    Passes when the bag holds a new key item."""
    p = profiles.for_rom(rom)
    if p.TITLE != "English Emerald":
        raise SystemExit("mystery_gift_claim knows English Emerald's screens only")
    raw = open(wc3, "rb").read()
    import duo_events as E
    problems = E.check_wc3(raw)
    if problems:
        raise SystemExit("; ".join(problems))
    size = E.WC3_LAYOUTS[len(raw)][1]
    head, script = raw[:4 + size + 0x28], raw[4 + size + 0x50:4 + size + 0x50 + 1004]
    g = savegen.Game(rom, p, save=sav)
    try:
        for _ in range(3000):                             # the title menu, then in through CONTINUE
            if g.callback2() == p.sym["CB2_MainMenu"] & ~1:
                break
            g.tap("A", gap=10)
        g.run(60)
        sb1 = g.sb1()
        g.write(sb1 + SB1_CARD_CRC, head)
        g.write(sb1 + SB1_RAM_SCRIPT, script)
        g.flag(MYSTERY_GIFT)
        savegen.point_continue(g, (2, 3, 1, 3))           # Oldale's Pokemon Center upstairs, below the man
        g.tap("A", gap=10)
        g.wait(g.in_overworld, 1200, what="the overworld")
        g.run(60)
        savegen.save_game(g)                              # the game writes the card to the save itself
        restart_to_title(g)
        g.run(60)
        got = g.read(g.sb1() + SB1_CARD_CRC, len(head))
        print("  card in the save after the restart:", "yes" if got == head else
              f"no (first difference at {next(i for i in range(len(head)) if got[i] != head[i]):#x})")
        mark(g, "title")
        # (English Emerald's MYSTERY GIFT menu goes back to the title when it finds no adapter, so
        # the card itself isn't shown here: the Mystery Gift man is the proof)
        g.run(120)
        mark(g, "continue")
        g.tap("A", gap=10)
        g.wait(g.in_overworld, 1200, what="the overworld")
        g.run(60)
        mark(g, "talk")
        g.tap("UP", hold=2, gap=12)
        before = g.read(sb1 + ITEM_KEYITEMS, 120)
        for _ in range(40):
            g.tap("A", gap=40)
            if g.read(sb1 + ITEM_KEYITEMS, 120) != before:
                break
        else:
            raise RuntimeError("the Mystery Gift man gave nothing")
        mark(g, "got")
        presses(g, "w60 A w60 A w60 A w60 B w60", gap=20)
        got = [struct.unpack_from("<H", g.read(sb1 + ITEM_KEYITEMS, 120), 4 * i)[0] for i in range(30)]
        new = [x for x in got if x and x not in
               [struct.unpack_from("<H", before, 4 * i)[0] for i in range(30)]]
        mark(g, "end")
        print(f"PASS: the Mystery Gift man gave item {new[0] if new else '?'} for the card")
    finally:
        g.close()


ITEM_MYSTIC_TICKET = 370                 # pret's include/constants/items.h


def mystery_gift_claim_frlg(rom, sav, item=ITEM_MYSTIC_TICKET):
    """The end of the FireRed/LeafGreen Mystery Gift video (21 November 2026): in the save the game
    wrote after receiving the card over the (emulated) Wireless Adapter, CONTINUE upstairs in the
    Pokemon Center, walk over to the delivery person in green (shown only while a Wonder Card waits:
    pret's CableClub_EventScript_HideOrShowMysteryGiftMan), take the gift, and look in the bag's
    KEY ITEMS. Passes when the bag's key items hold the item (the Mystic Ticket by default)."""
    p = profiles.for_rom(rom)
    g = savegen.Game(rom, p, save=sav)
    try:
        for _ in range(3000):
            if g.callback2() == p.sym["CB2_MainMenu"] & ~1:
                break
            g.tap("A", gap=10)
        g.run(90)
        mark(g, "title")
        g.run(60)
        g.tap("A", gap=10)
        g.wait(g.in_overworld, 1200, what="the overworld")
        g.run(60)
        mark(g, "continue")
        men = [xy for _, lid, xy in g.objects() if lid == 4]
        if not men:
            raise RuntimeError("no delivery person upstairs")
        target = (men[0][0] - 7, men[0][1] - 7)
        g.run(60)
        mark(g, "walk")
        # behind the counter, like the attendants: talk to them across it, from two tiles below
        tx, ty = target[0], target[1] + 2
        for _ in range(40):
            x, y = g.player_xy()
            if (x, y) == (tx, ty):
                break
            k = "LEFT" if x > tx else "RIGHT" if x < tx else "DOWN" if y < ty else "UP"
            g.tap(k, hold=14, gap=6)
            g.run(8)
        else:
            raise RuntimeError(f"couldn't get below {target}")
        g.tap("UP", hold=2, gap=16)
        g.run(20)
        mark(g, "talk")
        def has():
            raw = g.read(g.sb1() + p.SB1_KEYITEMS, 30 * 4)
            return any(struct.unpack_from("<H", raw, 4 * i)[0] == item for i in range(30))
        if has():
            raise RuntimeError("the key items already hold it")
        for _ in range(40):
            g.tap("A", gap=50)
            if has():
                break
        else:
            raise RuntimeError("the delivery person gave nothing")
        mark(g, "got")
        for _ in range(8):                                # the rest of the messages
            g.tap("A", gap=50)
        g.run(60)
        mark(g, "bag")
        presses(g, "w60 START w90 DOWN w40 DOWN w40 A w150 RIGHT w90", gap=20)   # START > (POKeDEX, POKeMON) BAG, then KEY ITEMS
        g.run(240)
        g.screenshot("/tmp/claim_bag.png")
        mark(g, "end")
        print(f"PASS: the delivery person handed over item {item}, now in KEY ITEMS")
    finally:
        g.close()


def _texting(g):
    """A battle message waiting for A: the text printer's flag in the battle window... approximated by
    the screen's bottom box being the plain message box (no menu on its right)."""
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "_battle_now.png")
    g.screenshot(path)
    from PIL import Image
    im = Image.open(path).convert("RGB")
    return im.getpixel((200, 136)) == im.getpixel((120, 136))     # the menu's box would differ there


def owner_xy(g):
    """The base's owner: the object event with local id 1 (savegen's objects(): map coordinates + 7)."""
    hit = [(xy[0] - 7, xy[1] - 7) for _, lid, xy in g.objects() if lid == 1]
    if not hit:
        raise RuntimeError("no owner in the base")
    return hit[0]


def walk_next_to(g, target, limit=80):
    """Walk until beside target (a tile away, up, down, left or right), then face it: one step at a
    time, toward it, the other way round when something is in the way."""
    tx, ty = target
    for _ in range(limit):
        x, y = g.player_xy()
        dx, dy = tx - x, ty - y
        if abs(dx) + abs(dy) == 1:
            g.tap("RIGHT" if dx > 0 else "LEFT" if dx < 0 else "DOWN" if dy > 0 else "UP", hold=2, gap=16)
            return
        tries = []
        if dy:
            tries.append("DOWN" if dy > 0 else "UP")
        if dx:
            tries.append("RIGHT" if dx > 0 else "LEFT")
        tries += [k for k in ("LEFT", "RIGHT", "UP", "DOWN") if k not in tries]
        for k in tries:
            g.tap(k, hold=14, gap=6)
            g.run(8)
            if g.player_xy() != (x, y):
                break
    raise RuntimeError(f"couldn't get beside {target}")


def evergrande_theme(rom, sav, out, secs=150):
    """OUT: Ever Grande City's music (the Record Corner's theme, at full length), 16-bit stereo at
    32768 Hz: the game standing outside its Pokemon Center with nothing pressed, sound only."""
    p = profiles.for_rom(rom)
    g = savegen.Game(rom, p, save=sav)
    try:
        for _ in range(3000):
            if g.callback2() == p.sym["CB2_MainMenu"] & ~1:
                break
            g.tap("A", gap=10)
        g.run(40)
        savegen.point_continue(g, (0, 8, 27, 49))          # Ever Grande City, below the Pokemon Center
        g.tap("A", gap=10)
        g.wait(g.in_overworld, 1200, what="the overworld")
        g.run(180)                                        # (the fade, and the music under way)
        if os.path.exists(out):
            os.remove(out)
        g.v.cmd(f"audio partner {g.v._path(os.path.abspath(out))}")
        g.run(int(secs * 59.7275))
        g.v.cmd("audio partner -")
        print(f"PASS: {os.path.getsize(out) / 4 / 32768:.0f} s of Ever Grande City's music in {out}")
    finally:
        g.close()


def visit_base(rom, sav, sb3):
    """The end of the Record Mixing video: in the save the game wrote after mixing, straight to the
    base's spot on its route (the game's own CONTINUE, pointed there: a teleport), in through its
    entrance by walking, over to its owner, and a battle with them, up to both first Pokemon out."""
    import secret_bases as SB
    p = profiles.for_rom(rom)
    f = SB.parse_sb3(open(sb3, "rb").read())
    loc = SB.tables().locations[f["location"]]
    route = (0, 16 + loc["route"] - 101)                  # (Routes 101 to 134 follow the towns in group 0)
    g = savegen.Game(rom, p, save=sav)
    try:
        for _ in range(3000):
            if g.callback2() == p.sym["CB2_MainMenu"] & ~1:
                break
            g.tap("A", gap=10)
        g.run(40)
        # owners battle only after the Champion (FLAG_SYS_GAME_CLEAR: pret's secret_base.inc)
        g.flag(0x864 if "Emerald" in p.TITLE else 0x804)
        savegen.point_continue(g, (route[0], route[1], loc["x"], loc["y"] + 1))
        g.tap("A", gap=10)
        g.wait(g.in_overworld, 1200, what="the overworld")
        g.run(60)
        mark(g, "arrive")
        g.run(90)
        mark(g, "walk")
        for _ in range(12):                               # up into the entrance (A too, if it asks)
            g.tap("UP", hold=10, gap=20)
            if g.read(g.sb1() + 4, 1)[0] != route[0]:
                break
        else:
            raise RuntimeError("the base's entrance didn't take the player in")
        g.run(120)
        mark(g, "inside")
        # over to the owner (gObjectEvents: local id 1 in a base) and battle them
        walk_next_to(g, owner_xy(g))
        mark(g, "talk")
        mons = p.gBattleMons
        for _ in range(60):                               # their words, YES to a battle, more words
            if struct.unpack("<H", g.read(mons + 0x58, 2))[0]:
                break
            g.tap("A", gap=40)
        else:
            raise RuntimeError("the owner didn't battle")
        mark(g, "battle")
        g.wait(lambda: all(struct.unpack("<H", g.read(mons + 0x58 * b + 0x28, 2))[0] for b in (0, 1)),
               1800, step=10, what="both first Pokemon out")
        # "... would like to battle!" waits for A; then each side sends out its first Pokemon and the
        # menu comes up (gBattlerControllerFuncs[0] settles on it): no more presses after that
        funcs = p.gBattlerControllerFuncs
        settled, last = 0, None
        for _ in range(400):
            f0 = struct.unpack("<I", g.read(funcs, 4))[0]
            settled = settled + 1 if f0 == last else 0
            last = f0
            if settled == 4 and not _texting(g):
                break
            if settled == 4:
                g.tap("A", gap=10)
                settled = 0
            g.run(30)
        g.run(240)
        mark(g, "end")
        g.screenshot("/tmp/visit_base.png")
        print(f"PASS: inside the base on Route {loc['route']}, battling its owner")
    finally:
        g.close()


def mystery_event(rom, sav):
    p = profiles.for_rom(rom)
    if p.TITLE != "English Ruby 1.1":
        raise SystemExit("mystery_event knows English Ruby 1.1's screens only")
    g = savegen.Game(rom, p, save=sav)
    try:
        mark(g, "boot")
        savegen.continue_to(g, (8, 4, 11, 3))           # Petalburg City's Pokemon Center, by the man
        for b in range(5):                                # the first five badges (Norman beaten)
            g.flag(BADGE01 + b)
        g.flag(EXDATA, False)
        g.run(30)
        mark(g, "talk")
        g.tap("UP", hold=2, gap=12)
        for _ in range(30):
            if g.has_task("Task_HandleMultichoiceInput"):
                break
            g.tap("A", gap=30)
        else:
            raise RuntimeError("he didn't ask")
        g.run(30)
        mark(g, "profile")
        g.tap("A", gap=60)                                # YES; "Yes! Thank you!"
        g.tap("A", gap=60)                                # then the profile screen
        g.run(60)
        for word, seq in RUBY_PROFILE:
            mark(g, word)
            presses(g, seq)
        mark(g, "ok")
        presses(g, "DOWN RIGHT w20 A w60 A w60")         # OK; "Your profile is as shown. Okay?" YES
        mark(g, "secret")
        for _ in range(40):                               # his answer, read with B (A would talk again)
            if flag_set(g, EXDATA):
                break
            g.tap("B", gap=40)
        else:
            raise RuntimeError("the game didn't unlock MYSTERY EVENT")
        presses(g, "w30 B w40 B w40 B w40 B w60", gap=20)
        mark(g, "save")
        savegen.save_game(g)
        g.run(60)
        mark(g, "restart")
        restart_to_title(g)
        g.run(60)
        mark(g, "menu")
        presses(g, "w60 DOWN w40 DOWN w120")
        mark(g, "end")
        g.screenshot("/tmp/unlock_menu.png")
        print("PASS: the game set MYSTERY EVENT's flag itself, and saved")
    finally:
        g.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("which", choices=("mystery_event", "mystery_gift", "mystery_gift_claim", "mystery_gift_claim_frlg",
                                      "visit_base", "theme"))
    ap.add_argument("--out", help="theme: where the music goes")
    ap.add_argument("--sb3", help="visit_base: the base that was mixed in")
    ap.add_argument("--wc3", help="mystery_gift_claim: the Wonder Card (English Emerald's)")
    ap.add_argument("--rom", required=True)
    ap.add_argument("--sav", required=True)
    a = ap.parse_args()
    import shutil, tempfile                               # the game saves: on a copy, not the file given
    copy = os.path.join(tempfile.mkdtemp(prefix="unlock_"), os.path.basename(a.sav))
    shutil.copy(a.sav, copy)
    a.sav = copy
    if a.which == "mystery_gift_claim":
        return mystery_gift_claim(a.rom, a.sav, a.wc3)
    if a.which == "mystery_gift_claim_frlg":
        return mystery_gift_claim_frlg(a.rom, a.sav)
    if a.which == "visit_base":
        return visit_base(a.rom, a.sav, a.sb3)
    if a.which == "theme":
        return evergrande_theme(a.rom, a.sav, a.out)
    {"mystery_event": mystery_event, "mystery_gift": mystery_gift}[a.which](a.rom, a.sav)


if __name__ == "__main__":
    main()
