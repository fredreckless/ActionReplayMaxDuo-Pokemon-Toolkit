"""phrases.py - the secret phrases that unlock MYSTERY GIFT and MYSTERY EVENT, in every language.

    python3 virtual/savegen/phrases.py find ENGLISH_DIR SYMS_DIR ROM [ROM ...]
        reads each ROM's own phrase (the words the game compares with what you enter) and the
        addresses the play step needs, and prints PHRASES entries for this file (run here, once:
        it needs pret's symbols for the English games, like findsyms.py)
    python3 virtual/savegen/phrases.py play ROM SAV [--record DIR]
        plays the unlock in the game with real button presses: walks up to the questionnaire (or,
        in Ruby and Sapphire, the man by the PC in Petalburg City's Pokemon Center), enters the
        phrase word by word in the easy chat screen's A-Z mode, saves, restarts, and checks that
        the game set the flag itself and that the title menu has the new item. Works on a copy of
        SAV. Prints PASS or FAIL.
    python3 virtual/savegen/phrases.py table
        the phrases as a Markdown table (for docs/UNLOCKING.md)

Which unlock each game has (from pret's scripts, and checked here in every ROM):
    FireRed, LeafGreen, Emerald: MYSTERY GIFT, from the questionnaire on a Poke Mart's counter
        (FireRed and LeafGreen also hold Mystery Event's phrase from Japanese Ruby, but no script
        uses it). Japanese Emerald also takes MYSTERY EVENT there.
    Ruby, Sapphire: MYSTERY EVENT, from the man by the PC in Petalburg City's Pokemon Center
        (after beating Norman). Ruby and Sapphire compare the words' text, not their numbers.

How a word is found in the A-Z lists without knowing the language: the game builds each letter's
list when the easy chat screen opens (Emerald, FireRed, LeafGreen: sWordData's unlocked words by
letter; Ruby and Sapphire: gEasyChatStruct's at 0x02001B78), so the letter and the place in its
list are read from there, and the presses follow from them. Every word is checked in the phrase
being entered before going on.
"""
import argparse, json, os, shutil, struct, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
ROM = 0x08000000
EMPTY = 0xFFFF

# Word ids in every language (pret's EC_WORD_*): the words differ by language, so these are only
# for telling the two phrases apart.
LINK, MYSTERY, EVENT = 0x209, 0x143A, 0x1817

FAMILY = {"BPE": "emerald", "BPR": "leafgreen", "BPG": "leafgreen", "AXV": "ruby", "AXP": "ruby"}
SYMS = {"emerald": "pokeemerald.sym", "leafgreen": "pokeleafgreen_rev1.sym", "ruby": "pokeruby_rev1.sym"}
ENGLISH = {"emerald": "English Emerald", "leafgreen": "English LeafGreen 1.1", "ruby": "English Ruby 1.1"}
LANGS = {1: "Japanese", 2: "English", 3: "French", 4: "Italian", 5: "German", 7: "Spanish"}


def header(path):
    with open(path, "rb") as f:
        f.seek(0xAC)
        code = f.read(4).decode("ascii", "replace")
        f.seek(0xBC)
        return code, f.read(1)[0]


def key_of(code, version):
    return code + (str(version) if version else "")


def lang_of(code):
    return {"J": 1, "E": 2, "P": 2, "F": 3, "I": 4, "D": 5, "S": 7}[code[3]]


# ---------------------------------------------------------------- reading the ROMs

def word_text(rom, groups, wid, lang):
    """Emerald, FireRed and LeafGreen: a word's text from gEasyChatGroups (12-byte word records)."""
    import secret_bases as SB
    g, i = wid >> 9, wid & 0x1FF
    data, n = struct.unpack_from("<IH", rom, groups - ROM + 8 * g)
    if i >= n or not ROM <= data < ROM + len(rom):
        raise ValueError(hex(wid))
    tp = struct.unpack_from("<I", rom, data - ROM + 12 * i)[0]
    raw = rom[tp - ROM:tp - ROM + 32]
    return SB.decode_name(raw[:raw.index(0xFF) + 1], lang)


def callers(rom, target):
    out = []
    for i in range(0, len(rom) - 4, 2):
        h1, h2 = struct.unpack_from("<HH", rom, i)
        if 0xF000 <= h1 < 0xF800 and h2 >= 0xF800:
            off = ((h1 & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
            if off & 0x400000:
                off -= 0x800000
            if ROM + i + 4 + off == target:
                out.append(ROM + i)
    return out


def find_gen3(eng, esym, rom, family, lang):
    """Emerald/FireRed/LeafGreen: the phrases IsPhraseDifferentThanPlayerInput is given, the word
    table, and sEasyChatScreen and the word lists' pointer."""
    import findsyms as F
    gs, gz = esym.addr["EasyChat_GetNumWordsInGroup"], esym.size["EasyChat_GetNumWordsInGroup"]
    b = eng[gs - ROM:gs - ROM + gz]
    off = next(j for j in range(0, gz, 4) if ROM <= struct.unpack_from("<I", b, j)[0] < 0x0A000000)
    groups = struct.unpack_from("<I", rom, F.find_function(eng, rom, gs, gz) - ROM + off)[0]
    cmp_ = F.find_function(eng, rom, esym.addr["IsPhraseDifferentThanPlayerInput"],
                           esym.size["IsPhraseDifferentThanPlayerInput"])

    def phrase_at(w):
        ids = struct.unpack_from("<4H", rom, w - ROM)
        texts = [word_text(rom, groups, x, lang) if x != EMPTY else "" for x in ids]
        if ids[0] == EMPTY:
            raise ValueError
        return list(ids), texts
    found = {}
    near = []
    for c in callers(rom, cmp_):
        for j in range(c - 0x30, c + 0x90, 2):
            if (j - ROM) % 4:
                continue
            w = struct.unpack_from("<I", rom, j - ROM)[0]
            if ROM <= w < ROM + len(rom) and w % 2 == 0:
                try:
                    ids, texts = phrase_at(w)
                except Exception:
                    continue
                near.append(w)
                kind = "gift" if LINK in ids else "event" if MYSTERY in ids and EVENT in ids else None
                if kind and kind not in found:
                    found[kind] = (w, ids, texts)
    # (Spanish Emerald: the call's literal pool is out of reach of the scan; the phrases sit together)
    for w0 in near:
        for k in range(-4, 5):
            w = w0 + 8 * k
            try:
                ids, texts = phrase_at(w)
            except Exception:
                continue
            kind = "gift" if LINK in ids else "event" if MYSTERY in ids and EVENT in ids else None
            if kind and kind not in found:
                found[kind] = (w, ids, texts)
    ram = {"groups": groups} if lang == 1 else {}
    for name, sym in (("screen", "sEasyChatScreen"),
                      ("words", "sWordData" if family == "emerald" else "sEasyChatSelectionData")):
        w, votes = F.find(eng, esym, rom, sym)
        if w is None or not 0x02000000 <= w < 0x02040000:
            raise RuntimeError(f"{sym} not found")
        ram[name] = w
    return found, ram


def find_ruby(eng, esym, rom, lang):
    """Ruby/Sapphire: gMysteryEventPhrase. The function that compares it reaches into
    gEasyChatStruct, laid out differently in each language, so it isn't found by its bytes; the
    phrase is found instead as English Ruby's four words in any order (the translations reorder
    them), which comes up exactly once in each European ROM. Its words' text comes from the game
    while the easy chat screen is open (play)."""
    import itertools
    english = (MYSTERY, EVENT, 0x100B, 0x200F)          # MYSTERY EVENT IS EXCITING
    hits = []
    for perm in itertools.permutations(english):
        b = struct.pack("<4H", *perm)
        i = rom.find(b)
        while i >= 0:
            hits.append((ROM + i, list(perm)))
            i = rom.find(b, i + 1)
    if len(hits) != 1:
        raise RuntimeError(f"gMysteryEventPhrase: {len(hits)} candidates")
    w, ids = hits[0]
    return {"event": (w, ids, None)}, {}


def find(english_dir, syms_dir, roms):
    import findsyms as F, profiles
    eng = {}
    for name in os.listdir(english_dir):
        p = os.path.join(english_dir, name)
        try:
            t = profiles.for_rom(p).TITLE
        except BaseException:
            continue
        for fam, title in ENGLISH.items():
            if t == title:
                eng[fam] = (open(p, "rb").read(), F.Syms(os.path.join(syms_dir, SYMS[fam])))
    out = {}
    for path in roms:
        code, ver = header(path)
        fam = FAMILY.get(code[:3])
        if fam is None or fam not in eng:
            print(f"# {os.path.basename(path)}: not a game this knows ({code})", file=sys.stderr)
            continue
        e, s = eng[fam]
        rom = open(path, "rb").read()
        lang = lang_of(code)
        try:
            found, ram = find_ruby(e, s, rom, lang) if fam == "ruby" else find_gen3(e, s, rom, fam, lang)
        except Exception as ex:
            print(f"# {os.path.basename(path)}: {ex}", file=sys.stderr)
            continue
        entry = {k: dict(ids=v[1], texts=v[2]) for k, v in found.items()}
        entry.update(ram)
        out[key_of(code, ver)] = entry
        print(f"# {key_of(code, ver)} {os.path.basename(path)}: "
              + "; ".join(f"{k} {' / '.join(t or '?' for t in (v[2] or ['?']))}" for k, v in found.items()),
              file=sys.stderr)
    return out


# ---------------------------------------------------------------- playing it in the game

FLAGS = {   # (the flag the game sets, the Pokedex flag the questionnaire wants first)
    ("emerald", "gift"): (0x8DB, 0x861), ("emerald", "event"): (0x8AC, 0x861),
    ("leafgreen", "gift"): (0x839, 0x829), ("ruby", "event"): (0x84C, None),
}
WHERE = {   # (map group, number, x, y) to stand at, facing up to it
    "emerald": (2, 4, 0, 5),          # Oldale Town's Poke Mart, below the questionnaire
    "leafgreen": (6, 3, 1, 5),        # Pewter City's Poke Mart, below the questionnaire (Viridian's has the parcel scene)
    "ruby": (8, 4, 11, 3),            # Petalburg City's Pokemon Center, below the man by the PC
}
BADGE01_RUBY = 0x807
PHRASE_OFF = {"emerald": 0x3C, "leafgreen": 0x18}
RUBY_EC = 0x02001000                  # gEasyChatStruct (gSharedMem + 0x1000)


def keyboard_cell(letter):
    """sAlphabetGroupIdMap: A-F, G-L, M-S, T-Z; 0 ('Others') at the end of the first row."""
    if letter == 0:
        return 0, 6
    for row, (first, n) in enumerate(((1, 6), (7, 6), (13, 7), (20, 7))):
        if first <= letter < first + n:
            return row, letter - first
    raise ValueError(letter)


class Entry:
    """The easy chat screen, read from RAM."""

    def __init__(self, g, fam, info):
        self.g, self.fam, self.info = g, fam, info
        self.stride = 270
        if fam == "ruby":
            # English Ruby's lists hold up to 255 words a letter, the other languages' 270 (pret
            # has it for German); what follows them is the table of the words' text, so the
            # length is the one that puts ROM pointers there
            self.stride = next(n for n in (270, 255) if self._looks_like_text_table(self.ruby_text_table(n)))

    def ruby_text_table(self, stride=None):
        return (RUBY_EC + 0xB78 + 54 * (stride or self.stride) + 0x62 + 3) & ~3

    def _looks_like_text_table(self, a):
        ptrs = struct.unpack("<8I", self.g.read(a + 0x400, 32))     # (group 1's words, in order)
        return all(ROM <= q < 0x0A000000 for q in ptrs) and all(0 < b - a2 < 16 for a2, b in zip(ptrs, ptrs[1:]))

    def screen(self):
        return self.g.u32(self.info["screen"])

    def b(self, off):
        v = self.g.read(self.screen() + off, 1)[0]
        return v - 256 if v > 127 else v

    def phrase(self):
        if self.fam == "ruby":
            return list(struct.unpack("<4H", self.g.read(RUBY_EC + 0x0C, 8)))
        return list(struct.unpack("<4H", self.g.read(self.screen() + PHRASE_OFF[self.fam], 8)))

    def lists(self):
        """Each letter's words, as the screen built them (letter 0 is 'Others')."""
        if self.fam == "ruby":
            base, counts = RUBY_EC + 0xB78, None
        else:
            w = self.g.u32(self.info["words"])
            base, counts = w + 0x64, struct.unpack("<27H", self.g.read(w + 0x2E, 54))
        out = []
        for L in range(27):
            raw = struct.unpack(f"<{self.stride}H", self.g.read(base + 2 * self.stride * L, 2 * self.stride))
            n = counts[L] if counts else next((i for i, x in enumerate(raw) if x == EMPTY), self.stride)
            out.append(list(raw[:n]))
        return out

    def where(self, wid):
        for L, words in enumerate(self.lists()):
            if wid in words:
                return L, words.index(wid)
        raise RuntimeError(f"word {wid:#x} isn't in any letter's list")


def press_until(g, key, done, limit=60, gap=12):
    for _ in range(limit):
        if done():
            return
        g.tap(key, gap=gap)
    if not done():
        raise RuntimeError(f"pressed {key} {limit} times and never got there")


def enter_word_gen3(g, e, k, wid, log):
    """Emerald, FireRed, LeafGreen: every step checked against the screen's own cursors."""
    col, row = k % 2, k // 2
    for _ in range(8):                                    # the phrase's box
        c, r = e.b(5), e.b(6)
        if (c, r) == (col, row):
            break
        g.tap("DOWN" if r < row else "UP" if r > row else "RIGHT" if c < col else "LEFT", gap=12)
    g.tap("A", gap=30)                                    # the keyboard (let it open: FireRed
    g.run(60)                                             # misses a SELECT while it slides in)
    if not e.b(9):
        g.tap("SELECT", gap=20)                           # A-Z mode (the screen redraws first:
        g.wait(lambda: e.b(9) == 1, 240, step=10, what="A-Z mode")    # FireRed takes a while)
        g.run(30)
    L, i = e.where(wid)
    kr, kc = keyboard_cell(L)
    press_until(g, "DOWN" if e.b(0xB) < kr else "UP", lambda: e.b(0xB) == kr, limit=8)
    press_until(g, "RIGHT" if e.b(0xA) < kc else "LEFT", lambda: e.b(0xA) == kc, limit=8)
    g.tap("A", gap=30)                                    # that letter's words
    wr, wc = i // 2, i % 2
    press_until(g, "DOWN", lambda: e.b(0xE) + e.b(0x11) >= wr, limit=200, gap=6)
    press_until(g, "UP", lambda: e.b(0xE) + e.b(0x11) <= wr, limit=10, gap=8)
    press_until(g, "RIGHT" if wc else "LEFT", lambda: e.b(0x10) == wc, limit=3)
    g.run(20)                                             # (let the list finish scrolling)
    if e.b(0xE) + e.b(0x11) != wr or e.b(0x10) != wc:
        raise RuntimeError(f"the word cursor is at {e.b(0xE) + e.b(0x11)},{e.b(0x10)}, not {wr},{wc}")
    g.tap("A", gap=40)
    g.wait(lambda: e.phrase()[k] == wid, 120, step=10, what=f"word {k + 1} in its box")
    log(f"  word {k + 1}: letter {L}, place {i} in its list")


def group_list(g, groups, gid):
    """A group's words in the order its list shows them (Japanese games, group mode): the group's
    records in turn, each naming the word it shows (alphabeticalOrder), if that word is enabled."""
    data, n = struct.unpack("<IH", g.read(groups + 8 * gid, 6))
    recs = g.read(data, 12 * n)
    out = []
    for i in range(n):
        order = struct.unpack_from("<i", recs, 12 * i + 4)[0]
        if 0 <= order < n and struct.unpack_from("<i", recs, 12 * order + 8)[0]:
            out.append(gid << 9 | order)
    return out


def enter_word_japanese(g, e, k, wid, log):
    """Japanese Emerald, FireRed, LeafGreen: by group (the screen's own mode at first), since their
    kana keyboard isn't the European A-Z one: the group's place among the unlocked groups and the
    word's place in the group's list (both in three columns in Japanese: the names are short),
    every step checked against the cursors."""
    col, row = k % 2, k // 2
    for _ in range(8):
        c, r = e.b(5), e.b(6)
        if (c, r) == (col, row):
            break
        g.tap("DOWN" if r < row else "UP" if r > row else "RIGHT" if c < col else "LEFT", gap=12)
    g.tap("A", gap=30)
    g.run(60)
    if e.b(9):
        g.tap("SELECT", gap=20)
        g.wait(lambda: e.b(9) == 0, 240, step=10, what="group mode")
        g.run(30)
    w = g.u32(e.info["words"])
    n = struct.unpack("<H", g.read(w, 2))[0]
    ids = list(struct.unpack(f"<{n}H", g.read(w + 2, 2 * n)))
    gi = ids.index(wid >> 9)
    gr, gc = gi // 3, gi % 3
    press_until(g, "DOWN", lambda: e.b(0xB) + e.b(0xC) >= gr, limit=20, gap=10)
    press_until(g, "UP", lambda: e.b(0xB) + e.b(0xC) <= gr, limit=10, gap=10)
    press_until(g, "RIGHT" if e.b(0xA) < gc else "LEFT", lambda: e.b(0xA) == gc, limit=4)
    g.run(20)
    g.tap("A", gap=30)
    words = group_list(g, e.info["groups"], wid >> 9)
    i = words.index(wid)
    wr, wc = i // 3, i % 3
    press_until(g, "DOWN", lambda: e.b(0xE) + e.b(0x11) >= wr, limit=200, gap=6)
    press_until(g, "UP", lambda: e.b(0xE) + e.b(0x11) <= wr, limit=10, gap=8)
    press_until(g, "RIGHT" if e.b(0x10) < wc else "LEFT", lambda: e.b(0x10) == wc, limit=4)
    g.run(20)
    g.tap("A", gap=40)
    g.wait(lambda: e.phrase()[k] == wid, 120, step=10, what=f"word {k + 1} in its box")
    log(f"  word {k + 1}: group {wid >> 9} (place {gi}), place {i} in its list")


def enter_word_ruby(g, e, k, wid, log):
    """Ruby and Sapphire: the presses English Ruby's screen takes (the keyboard opens on A each
    time; DOWN moves a row of two words), with the letter and place read from the lists."""
    g.tap(("A", "RIGHT", "DOWN", "RIGHT")[k], gap=20) if k else None
    if k == 2:
        g.tap("LEFT", gap=20)
    if k:
        g.tap("A", gap=30)
    else:
        presses(g, "A w30 SELECT w30")
    L, i = e.where(wid)
    kr, kc = keyboard_cell(L)
    presses(g, f"DOWN*{kr} RIGHT*{kc} A w30" if kr or kc else "A w30")
    presses(g, (f"DOWN*{i // 2} " if i >= 2 else "") + ("RIGHT " if i % 2 else "") + "A w40")
    log(f"  word {k + 1}: letter {L}, place {i} in its list")


def presses(g, seq, gap=14):
    for kk in seq.split():
        if kk.startswith("w"):
            g.run(int(kk[1:]))
            continue
        n = 1
        if "*" in kk:
            kk, n = kk.split("*")
            n = int(n)
        for _ in range(n):
            g.tap(*kk.split("+"), gap=gap)


def flag_set(g, n):
    return bool(g.read(g.sb1() + g.p.SB1_FLAGS + n // 8, 1)[0] >> (n % 8) & 1)


def restart_to_title(g):
    g.v.keys("partner", "A", "B", "START", "SELECT")
    g.run(10)
    g.v.keys("partner")
    g.run(60)
    for _ in range(3000):
        if g.callback2() == g.p.sym["CB2_MainMenu"] & ~1:
            return
        g.tap("A", gap=10)
    raise RuntimeError("no title menu after the restart")


def ruby_word_text(g, e, wid):
    """A word's text while Ruby's easy chat screen is open: gEasyChatStruct's ecWordStrings, after
    the letters' lists, decoded."""
    import secret_bases as SB
    p = g.u32(e.ruby_text_table() + 4 * (0x100 * (wid >> 9) + (wid & 0x1FF)))
    raw = g.read(p, 32)
    return SB.decode_name(raw[:raw.index(0xFF) + 1], g.p.LANGUAGE)


def _mark(g, text):
    """A mark in a recording (the video follows them: video/unlock.py's mark, the same format)."""
    rec = os.environ.get("VDUO_RECORD")
    if rec:
        os.makedirs(rec, exist_ok=True)
        with open(os.path.join(rec, "terminal.jsonl"), "a") as f:
            f.write(json.dumps(dict(n=getattr(g.v, "_rec_n", 0), mark=text)) + "\n")


def play(rom, sav, kind=None, log=print, record=None):
    import savegen, profiles
    code, ver = header(rom)
    key, fam = key_of(code, ver), FAMILY.get(code[:3])
    info = PHRASES.get(key)
    if fam is None or info is None:
        raise SystemExit(f"no phrase known for {key}")
    kind = kind or ("gift" if "gift" in info and fam != "ruby" else "event")
    if kind not in info or (fam, kind) not in FLAGS:
        raise SystemExit(f"{key} has no {kind} unlock")
    words = info[kind]["ids"]
    flag, dex = FLAGS[(fam, kind)]
    p = profiles.for_rom(rom)
    copy = os.path.join(tempfile.mkdtemp(prefix="phrase_"), os.path.basename(sav))
    shutil.copy(sav, copy)
    if record:
        os.environ["VDUO_RECORD"] = record
    g = savegen.Game(rom, p, save=copy, log=log)
    try:
        # on the title menu, before CONTINUE: the flags (FireRed and LeafGreen only show the
        # questionnaire if the Pokedex flag is set when the Mart loads), and where to stand
        for _ in range(3000):
            if g.callback2() == p.sym["CB2_MainMenu"] & ~1:
                break
            g.tap("A", gap=10)
        g.run(60)
        _mark(g, "boot")
        g.flag(flag, False)
        if dex:
            g.flag(dex)
        if fam == "ruby":
            for b in range(5):
                g.flag(BADGE01_RUBY + b)
        savegen.point_continue(g, WHERE[fam])
        g.tap("A", gap=10)
        g.wait(g.in_overworld, 1200, what="the overworld")
        g.wait(lambda: g.player_xy() == WHERE[fam][2:], 600, what="the player")
        g.run(90)
        _mark(g, "talk")
        g.tap("UP", hold=2, gap=12)
        want = "Task_HandleMultichoiceInput" if fam == "ruby" else "Task_HandleYesNoInput"
        press_until(g, "A", lambda: g.has_task(want), limit=30, gap=30)
        g.run(20)
        g.tap("A", gap=60)                              # YES
        if fam == "ruby":
            g.tap("A", gap=60)                          # "Yes! Thank you!", then the profile
        g.run(60)
        _mark(g, "profile")
        e = Entry(g, fam, info)
        texts = []
        for k, wid in enumerate(words):
            if wid == EMPTY:
                if e.phrase()[k] != EMPTY:
                    raise RuntimeError(f"box {k + 1} should stay empty, and isn't")
                log(f"  word {k + 1}: left empty, as the phrase has it")
                texts.append("")
                continue
            _mark(g, f"word{k + 1}")
            enter = enter_word_ruby if fam == "ruby" else enter_word_japanese if p.LANGUAGE == 1 else enter_word_gen3
            enter(g, e, k, wid, log)
            got = e.phrase()[k]
            if got != wid:
                raise RuntimeError(f"box {k + 1} has word {got:#x}, not {wid:#x}")
            texts.append(ruby_word_text(g, e, wid) if fam == "ruby" else info[kind]["texts"][k])
        g.screenshot(os.path.join(record or tempfile.gettempdir(), f"{key}_{kind}_phrase.png"))
        log("  entered: " + " / ".join(t or "(empty)" for t in texts))
        # OK, then YES to "Is it okay?"
        _mark(g, "ok")
        g.tap("DOWN", gap=12)                           # the buttons: DEL. ALL, CANCEL, OK
        if fam == "ruby":
            g.tap("RIGHT", gap=20)
        else:
            press_until(g, "RIGHT", lambda: e.b(6) == 2 and e.b(5) == 2, limit=4)
        presses(g, "A w60 A w60")
        _mark(g, "secret")
        for _ in range(40):
            if flag_set(g, flag):
                break
            g.tap("B", gap=40)
        else:
            raise RuntimeError("the game didn't set the flag")
        presses(g, "w30 B w40 B w40 B w40 B w60", gap=20)
        _mark(g, "save")
        savegen.save_game(g)
        g.run(60)
        _mark(g, "restart")
        restart_to_title(g)
        g.run(120)
        _mark(g, "menu")
        g.run(150)
        _mark(g, "end")
        shot = os.path.join(record or tempfile.gettempdir(), f"{key}_{kind}_title.png")
        g.screenshot(shot)
        log(f"  the title menu after a restart: {shot}")
        return texts
    finally:
        g.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find")
    f.add_argument("english")
    f.add_argument("syms")
    f.add_argument("roms", nargs="+")
    pl = sub.add_parser("play")
    pl.add_argument("rom")
    pl.add_argument("sav")
    pl.add_argument("--kind", choices=("gift", "event"))
    pl.add_argument("--record")
    sub.add_parser("table")
    a = ap.parse_args()
    if a.cmd == "find":
        print(json.dumps(find(a.english, a.syms, a.roms), indent=1, ensure_ascii=False))
    elif a.cmd == "play":
        try:
            texts = play(a.rom, a.sav, a.kind, record=a.record)
            print("PASS: " + " / ".join(t or "(empty)" for t in texts))
        except (RuntimeError, SystemExit) as ex:
            print(f"FAIL: {ex}")
            sys.exit(1)
    else:
        print(markdown())


# Found by `find` in each ROM (14 November): the words in the game's own order (0xffff: a box left
# empty), their text as the game shows it, and (Emerald, FireRed, LeafGreen) where the easy chat
# screen's pointers are. Ruby and Sapphire's texts are the game's own, read while playing it (ruby_word_text).
PHRASES = {
    "BPEJ": {"gift": dict(ids=[0xa33, 0x140c, 0x143a, 0x209], texts=["ともだち", "いっぱい", "ふしぎ", "つうしん"]), "event": dict(ids=[0x143a, 0x1817, 0x2023, 0x200f], texts=["ふしぎ", "できごと", "わくわく", "ドキドキ"]), "screen": 0x2039de4, "words": 0x2039dec, "groups": 0x8578d14},
    "BPES": {"gift": dict(ids=[0x209, 0xe0e, 0xa39, 0xffff], texts=["CONEXIÓN", "CON", "TODOS", ""]), "screen": 0x203a118, "words": 0x203a120},
    "BPEE": {"gift": dict(ids=[0x209, 0x140b, 0x1030, 0x102a], texts=["LINK", "TOGETHER", "WITH", "ALL"]), "screen": 0x203a118, "words": 0x203a120},
    "BPED": {"gift": dict(ids=[0x209, 0x1030, 0x102a, 0x140b], texts=["LINK", "MIT", "ALLE", "ZUSAMMEN"]), "screen": 0x203a118, "words": 0x203a120},
    "BPEF": {"gift": dict(ids=[0x209, 0x1030, 0xe0c, 0x20b], texts=["CONNEXION", "AVEC", "LES", "DRESSEUR"]), "screen": 0x203a118, "words": 0x203a120},
    "BPEI": {"gift": dict(ids=[0xa14, 0xe37, 0x209, 0xc00], texts=["INSIEME", "IN", "LINK", "!"]), "screen": 0x203a118, "words": 0x203a120},
    "BPRJ": {"gift": dict(ids=[0xa33, 0x140c, 0x143a, 0x209], texts=["ともだち", "いっぱい", "ふしぎ", "つうしん"]), "event": dict(ids=[0x143a, 0x1817, 0x2023, 0x200f], texts=["ふしぎ", "できごと", "わくわく", "ドキドキ"]), "screen": 0x203ac60, "words": 0x2039934, "groups": 0x83b3a44},
    "BPRS": {"gift": dict(ids=[0x209, 0xe0e, 0xa39, 0xffff], texts=["CONEXIÓN", "CON", "TODOS", ""]), "event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENTO", "MISTERIOSO", "ES", "DEMASIADO"]), "screen": 0x203ace8, "words": 0x20399bc},
    "BPRD": {"gift": dict(ids=[0x209, 0x1030, 0x102a, 0x140b], texts=["LINK", "MIT", "ALLE", "ZUSAMMEN"]), "event": dict(ids=[0x143a, 0x1817, 0x100b, 0x200f], texts=["GEHEIM", "GESCHEHEN", "IST", "JIPP! JIPP!"]), "screen": 0x203ace8, "words": 0x20399bc},
    "BPRE": {"gift": dict(ids=[0x209, 0x140b, 0x1030, 0x102a], texts=["LINK", "TOGETHER", "WITH", "ALL"]), "event": dict(ids=[0x143a, 0x1817, 0x100b, 0x200f], texts=["MYSTERY", "EVENT", "IS", "EXCITING"]), "screen": 0x203ace8, "words": 0x20399bc},
    "BPRF": {"gift": dict(ids=[0x209, 0x1030, 0xe0c, 0x20b], texts=["CONNEXION", "AVEC", "LES", "DRESSEUR"]), "event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENEMENT", "MYSTERE", "EST", "PASSIONNANT"]), "screen": 0x203ace8, "words": 0x20399bc},
    "BPRI": {"gift": dict(ids=[0xa14, 0xe37, 0x209, 0xc00], texts=["INSIEME", "IN", "LINK", "!"]), "event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENTO", "SEGRETO", "È", "FANTASTICO"]), "screen": 0x203ace8, "words": 0x20399bc},
    "BPGJ": {"gift": dict(ids=[0xa33, 0x140c, 0x143a, 0x209], texts=["ともだち", "いっぱい", "ふしぎ", "つうしん"]), "event": dict(ids=[0x143a, 0x1817, 0x2023, 0x200f], texts=["ふしぎ", "できごと", "わくわく", "ドキドキ"]), "screen": 0x203ac60, "words": 0x2039934, "groups": 0x83b38b4},
    "BPGD": {"gift": dict(ids=[0x209, 0x1030, 0x102a, 0x140b], texts=["LINK", "MIT", "ALLE", "ZUSAMMEN"]), "event": dict(ids=[0x143a, 0x1817, 0x100b, 0x200f], texts=["GEHEIM", "GESCHEHEN", "IST", "JIPP! JIPP!"]), "screen": 0x203ace8, "words": 0x20399bc},
    "BPGS": {"gift": dict(ids=[0x209, 0xe0e, 0xa39, 0xffff], texts=["CONEXIÓN", "CON", "TODOS", ""]), "event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENTO", "MISTERIOSO", "ES", "DEMASIADO"]), "screen": 0x203ace8, "words": 0x20399bc},
    "BPGE1": {"gift": dict(ids=[0x209, 0x140b, 0x1030, 0x102a], texts=["LINK", "TOGETHER", "WITH", "ALL"]), "event": dict(ids=[0x143a, 0x1817, 0x100b, 0x200f], texts=["MYSTERY", "EVENT", "IS", "EXCITING"]), "screen": 0x203ace8, "words": 0x20399bc},
    "BPGF": {"gift": dict(ids=[0x209, 0x1030, 0xe0c, 0x20b], texts=["CONNEXION", "AVEC", "LES", "DRESSEUR"]), "event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENEMENT", "MYSTERE", "EST", "PASSIONNANT"]), "screen": 0x203ace8, "words": 0x20399bc},
    "BPGI": {"gift": dict(ids=[0xa14, 0xe37, 0x209, 0xc00], texts=["INSIEME", "IN", "LINK", "!"]), "event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENTO", "SEGRETO", "È", "FANTASTICO"]), "screen": 0x203ace8, "words": 0x20399bc},
    "AXVE1": {"event": dict(ids=[0x143a, 0x1817, 0x100b, 0x200f], texts=["MYSTERY", "EVENT", "IS", "EXCITING"])},
    "AXVS1": {"event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENTO", "MISTERIOSO", "ES", "DEMASIADO"])},
    "AXVD": {"event": dict(ids=[0x143a, 0x1817, 0x100b, 0x200f], texts=["GEHEIM", "GESCHEHEN", "IST", "JIPP! JIPP!"])},
    "AXVF1": {"event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENEMENT", "MYSTERE", "EST", "PASSIONNANT"])},
    "AXVI1": {"event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENTO", "SEGRETO", "È", "FANTASTICO"])},
    "AXPS1": {"event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENTO", "MISTERIOSO", "ES", "DEMASIADO"])},
    "AXPD1": {"event": dict(ids=[0x143a, 0x1817, 0x100b, 0x200f], texts=["GEHEIM", "GESCHEHEN", "IST", "JIPP! JIPP!"])},
    "AXPE1": {"event": dict(ids=[0x143a, 0x1817, 0x100b, 0x200f], texts=["MYSTERY", "EVENT", "IS", "EXCITING"])},
    "AXPF1": {"event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENEMENT", "MYSTERE", "EST", "PASSIONNANT"])},
    "AXPI": {"event": dict(ids=[0x1817, 0x143a, 0x100b, 0x200f], texts=["EVENTO", "SEGRETO", "È", "FANTASTICO"])},
}


def markdown():
    rows = ["| Game | Language | Unlocks | Phrase |", "|---|---|---|---|"]
    names = {"BPE": "Emerald", "BPR": "FireRed", "BPG": "LeafGreen", "AXV": "Ruby", "AXP": "Sapphire"}
    for key, v in PHRASES.items():
        fam = FAMILY[key[:3]]
        for kind in ("gift", "event"):
            if kind in v and (fam, kind) in FLAGS:
                words = " ".join(f"**{t}**" if t else "(empty)" for t in (v[kind]["texts"] or ["?"]))
                rows.append(f"| {names[key[:3]]} | {LANGS[lang_of(key)]} | "
                            f"{'MYSTERY GIFT' if kind == 'gift' else 'MYSTERY EVENT'} | {words} |")
    return "\n".join(rows)


if __name__ == "__main__":
    main()
