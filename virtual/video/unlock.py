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
    ap.add_argument("which", choices=("mystery_event", "mystery_gift"))
    ap.add_argument("--rom", required=True)
    ap.add_argument("--sav", required=True)
    a = ap.parse_args()
    import shutil, tempfile                               # the game saves: on a copy, not the file given
    copy = os.path.join(tempfile.mkdtemp(prefix="unlock_"), os.path.basename(a.sav))
    shutil.copy(a.sav, copy)
    a.sav = copy
    {"mystery_event": mystery_event, "mystery_gift": mystery_gift}[a.which](a.rom, a.sav)


if __name__ == "__main__":
    main()
