"""Secret Bases for Pokemon Ruby, Sapphire and Emerald: the .sb3 file (docs/SB3_FORMAT.md), the
base card that makes one by hand, and reading the bases out of a save backup.

An .sb3 is exactly what the game holds for one Secret Base: 160 bytes, struct SecretBase in
Emerald's layout (Ruby and Sapphire's differs only in byte 0x0D, the language). This module checks
one, writes one from a card, prints one back as a card, and reads the twenty bases out of a save
backup made by maxduo_saves.py (on the PC; it never touches a cartridge).

    python secret_bases.py show FILE.sb3          print a base as a card
    python secret_bases.py make CARD.txt          check a card and write its .sb3
    python secret_bases.py save SAVE.sav          write the save's bases as .sb3 files

(duo_events.py offers the same as `base show`, `base make` and `bases`, and sends .sb3 files to a
game with `mix`.) The data tables at the end come from pret/pokeemerald: names, learnsets,
decorations and the 24 rooms' tiles, packed."""
import base64, difflib, json, os, re, struct, sys, time, zlib

SB3_SIZE = 160
BASES_IN_SAVE = 20
LANGUAGES = {1: "Japanese", 2: "English", 3: "French", 4: "Italian", 5: "German", 7: "Spanish"}
LANG_SHORT = {0: "ANY", 1: "JPN", 2: "ENG", 3: "FRA", 4: "ITA", 5: "GER", 7: "SPA"}
CODE_LANGUAGE = {"J": 1, "E": 2, "P": 2, "F": 3, "I": 4, "D": 5, "S": 7}      # a cartridge code's last letter
GAME_CODES = {"AXV": "Ruby", "AXP": "Sapphire", "BPE": "Emerald", "BPR": "FireRed", "BPG": "LeafGreen"}
BASES_AT = {"Ruby": 0x1A08, "Sapphire": 0x1A08, "Emerald": 0x1A9C}           # in SaveBlock 1
PARTY_COUNT_AT, PARTY_AT = 0x234, 0x238                                     # (the same in all three)
MAX_ITEM = {"Ruby": 348, "Sapphire": 348, "Emerald": 376}
NATURES = ("Hardy Lonely Brave Adamant Naughty Bold Docile Relaxed Impish Lax Timid Hasty Serious Jolly "
           "Naive Modest Mild Quiet Bashful Rash Calm Gentle Sassy Careful Quirky").split()
DECOR_BAG = {"DESK": 10, "CHAIR": 10, "PLANT": 10, "ORNAMENT": 30, "MAT": 30, "POSTER": 10, "DOLL": 40, "CUSHION": 10}
SHAPES = {"1x1": (1, 1), "2x1": (2, 1), "3x1": (3, 1), "4x2": (4, 2), "2x2": (2, 2), "1x2": (1, 2), "1x3": (1, 3),
          "2x4": (2, 4), "3x3": (3, 3), "3x2": (3, 2)}
ROOM_KINDS = ("red cave", "brown cave", "blue cave", "yellow cave", "tree", "shrub")
MAX_EV = 85                                      # 510 / 6: the most a real Pokemon's average can be


# ---------------------------------------------------------------- the tables (see the end)
class _Tables:
    def __init__(self):
        raw = zlib.decompress(base64.b64decode(_TABLES))
        cut = raw.index(b"\0")
        j = json.loads(raw[:cut])
        self.species = j["species"]
        self.moves = j["moves"]
        self.items = [tuple(x) for x in j["items"]]
        self.gender = j["gender"]
        self.two_abilities = j["abil2"]
        self.decorations = [None] + [dict(zip(("name", "perm", "shape", "cat", "tiles"), r.split("|")))
                                     for r in j["decorations"]]
        self.rooms = [r.split("/") for r in j["rooms"]]
        self.learn = {}
        blob, at = raw[cut + 1:], 0
        for sp in range(1, 412):
            nl, no = blob[at], blob[at + 1]
            at += 2
            lv = {}
            for _ in range(nl):
                m, l = struct.unpack_from("<HB", blob, at)
                lv[m] = l
                at += 3
            other = set(struct.unpack_from(f"<{no}H", blob, at))
            at += 2 * no
            self.learn[sp] = (lv, other)
        self.locations = {}
        for row in _LOCATIONS.split():
            i, kind, room, route, x, y = row.split(":")
            self.locations[int(i)] = dict(kind=kind.replace("_", " "), room=int(room), route=int(route), x=int(x), y=int(y))


_T = None


def tables():
    global _T
    if _T is None:
        _T = _Tables()
    return _T


def _key(text):
    """A name as compared: no case, spaces, dots, hyphens or apostrophes; é as e; ♀/♂ as f/m."""
    t = text.lower().replace("é", "e").replace("♀", "f").replace("♂", "m")
    return re.sub(r"[\s.\-'’_]", "", t)


def _lookup(name, names, what):
    """The index of `name` in `names` (a list, None/'' for gaps), forgiving case and spacing."""
    want = _key(name)
    found = [i for i, n in enumerate(names) if n and _key(n) == want]
    if found:
        return found[0]
    if name.strip().isdigit() and 0 < int(name) < len(names) and names[int(name)]:
        return int(name)
    near = difflib.get_close_matches(name.upper(), [n for n in names if n], n=3, cutoff=0.6)
    hint = f" (did you mean {' or '.join(near)}?)" if near else ""
    raise ValueError(f"no {what} called '{name}'{hint}")


def species_name(sp):
    t = tables()
    return t.species[sp] if 0 < sp < len(t.species) and t.species[sp] and t.species[sp] != "?" else f"species {sp}"


def move_name(m):
    t = tables()
    return t.moves[m] if 0 < m < len(t.moves) else f"move {m}"


def item_name(i):
    t = tables()
    return t.items[i][0] if 0 < i < len(t.items) else f"item {i}"


def decoration_name(d):
    t = tables()
    return t.decorations[d]["name"] if 0 < d < len(t.decorations) else f"decoration {d}"


def location_text(bid):
    loc = tables().locations.get(bid)
    if not loc:
        return f"location {bid} (not a real one)"
    return f"{loc['kind'].capitalize()}, room {loc['room']}, Route {loc['route']} at {loc['x']},{loc['y']} (ID {bid})"


def location_short(bid):
    loc = tables().locations.get(bid)
    return f"{loc['kind'].capitalize()} {loc['room']}, Route {loc['route']}" if loc else f"location {bid}"


def room_of(bid):
    """The room's tiles (rows of letters, see the tables) for a location ID."""
    return tables().rooms[bid // 10]


# ---------------------------------------------------------------- Gen 3 text
_WEST = {0x00: " ", 0x01: "À", 0x02: "Á", 0x03: "Â", 0x04: "Ç", 0x05: "È", 0x06: "É", 0x07: "Ê", 0x08: "Ë",
         0x09: "Ì", 0x0B: "Î", 0x0C: "Ï", 0x0D: "Ò", 0x0E: "Ó", 0x0F: "Ô", 0x10: "Œ", 0x11: "Ù", 0x12: "Ú",
         0x13: "Û", 0x14: "Ñ", 0x15: "ß", 0x16: "à", 0x17: "á", 0x19: "ç", 0x1A: "è", 0x1B: "é", 0x1C: "ê",
         0x1D: "ë", 0x1E: "ì", 0x20: "î", 0x21: "ï", 0x22: "ò", 0x23: "ó", 0x24: "ô", 0x25: "œ", 0x26: "ù",
         0x27: "ú", 0x28: "û", 0x29: "ñ", 0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-", 0xB0: "…", 0xB1: "“",
         0xB2: "”", 0xB3: "‘", 0xB4: "’", 0xB5: "♂", 0xB6: "♀", 0xB8: ",", 0xBA: "/", 0xF0: ":",
         0xF1: "Ä", 0xF2: "Ö", 0xF3: "Ü", 0xF4: "ä", 0xF5: "ö", 0xF6: "ü"}
_WEST.update({0xA1 + i: str(i) for i in range(10)})
_WEST.update({0xBB + i: chr(65 + i) for i in range(26)})
_WEST.update({0xD5 + i: chr(97 + i) for i in range(26)})
_WEST_IN = {v: k for k, v in _WEST.items()}
_WEST_IN.update({"'": 0xB4, '"': 0xB2})
_KANA = ('?あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんぁぃぅぇぉゃゅょ'
         'がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽっアイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモ'
         'ヤユヨラリルレロワヲンァィゥェォャュョガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポッ')
_JP = {i: c for i, c in enumerate(_KANA) if i}
_JP.update({0x00: "　", 0xAB: "！", 0xAC: "？", 0xAD: "。", 0xAE: "ー"})
_JP.update({0xA1 + i: str(i) for i in range(10)})
_JP_IN = {v: k for k, v in _JP.items()}
_JP_IN.update({" ": 0x00, "!": 0xAB, "?": 0xAC, "-": 0xAE})


def decode_name(raw, language):
    table = _JP if language == 1 else _WEST
    return "".join(table.get(b, "?") for b in raw.split(b"\xff")[0])


def encode_name(text, language):
    """A trainer's name in the game's characters: 1 to 7 (Japanese: 5), padded with 0xFF."""
    limit = 5 if language == 1 else 7
    table = _JP_IN if language == 1 else _WEST_IN
    if not 1 <= len(text) <= limit:
        raise ValueError(f"a name has 1 to {limit} characters{' in Japanese' if language == 1 else ''}: '{text}'")
    out = bytearray()
    for ch in text:
        if ch not in table:
            raise ValueError(f"'{ch}' isn't in the {'Japanese' if language == 1 else 'European'} games' alphabet")
        out.append(table[ch])
    return bytes(out).ljust(7, b"\xff")


# ---------------------------------------------------------------- one base
def parse_sb3(data):
    """An .sb3's fields. Raises ValueError if it isn't 160 bytes."""
    if len(data) != SB3_SIZE:
        raise ValueError(f"not a Secret Base: {len(data)} bytes, not {SB3_SIZE}")
    flags = data[1]
    team = []
    for k in range(6):
        sp = struct.unpack_from("<H", data, 0x7C + 2 * k)[0]
        team.append(dict(species=sp, personality=struct.unpack_from("<I", data, 0x34 + 4 * k)[0],
                         moves=list(struct.unpack_from("<4H", data, 0x4C + 8 * k)),
                         item=struct.unpack_from("<H", data, 0x88 + 2 * k)[0], level=data[0x94 + k], ev=data[0x9A + k]))
    return dict(location=data[0], to_register=flags & 0xF, gender=flags >> 4 & 1, battled=flags >> 5 & 1,
                registry=flags >> 6, name_raw=bytes(data[2:9]), tid=struct.unpack_from("<H", data, 9)[0],
                sid=struct.unpack_from("<H", data, 11)[0], language=data[0x0D],
                received=struct.unpack_from("<H", data, 0x0E)[0], entered=data[0x10], unused=data[0x11],
                decorations=list(data[0x12:0x22]), positions=list(data[0x22:0x32]), padding=bytes(data[0x32:0x34]),
                team=team)


def owner_name(f):
    return decode_name(f["name_raw"], f["language"])


def names_match(a, b):
    """Two names as the game compares them: up to seven characters, ending where both end."""
    for i in range(7):
        if a[i] == 0xFF and b[i] == 0xFF:
            return True
        if a[i] != b[i]:
            return False
    return True


def owner_key(f):
    """Who a base belongs to, as the game decides it: gender, both IDs, the name."""
    return (f["gender"], f["tid"], f["sid"], f["name_raw"].split(b"\xff")[0])


def normalise(data, language=None):
    """The base as a file holds it: the receiving player's fields cleared (registered, new, to
    register, battled today, times entered), the language filled in if given and unknown."""
    b = bytearray(data)
    b[1] &= 0x10
    b[0x10] = b[0x11] = 0
    b[0x32:0x34] = b"\0\0"
    if language and not b[0x0D]:
        b[0x0D] = language
    return bytes(b)


def gender_of(species, personality):
    ratio = tables().gender[species]
    if ratio in (0, 254, 255):
        return {0: "male", 254: "female", 255: "genderless"}[ratio]
    return "female" if ratio > (personality & 0xFF) else "male"


def _cells(d, x, y):
    """The tiles a decoration covers when placed at (x, y): its bottom-left corner."""
    w, h = SHAPES[tables().decorations[d]["shape"]]
    return [(x + i, y - h + 1 + j) for j in range(h) for i in range(w)]


def check_decorations(f):
    """decoration.c CanPlaceDecoration, for a whole base: what a player couldn't have placed.
    Returns a list of problems (empty if the room would look as its owner arranged it)."""
    t = tables()
    room = [list(r) for r in room_of(f["location"])]
    width, height = len(room[0]), len(room)
    used = [(d, p) for d, p in zip(f["decorations"], f["positions"]) if d]
    problems, covered, dolls, counts = [], {}, set(), {}
    for d, pos in used:                                 # the furniture first: it changes the tiles
        dec = t.decorations[d]
        counts[dec["cat"]] = counts.get(dec["cat"], 0) + 1
        if dec["perm"] == "SPRITE":
            continue
        x, y = pos >> 4, pos & 0xF
        cells = _cells(d, x, y)
        what = f"{dec['name'].title()} at {x},{y}"
        if any(not (0 <= cx < width and 0 <= cy < height) for cx, cy in cells):
            problems.append(f"{what} reaches outside the room")
            continue
        w, h = SHAPES[dec["shape"]]
        clash = [c for c in cells if c in covered]
        if clash:
            problems.append(f"{what} overlaps {covered[clash[0]]}")
            continue
        for k, (cx, cy) in enumerate(cells):
            tile = room[cy][cx]
            row = k // w
            if dec["perm"] in ("SOLID_FLOOR", "PASS_FLOOR"):
                ok = tile == "." or (d == 33 and tile == "H")            # (the Solid Board bridges a hole)
            elif dec["perm"] == "BEHIND_FLOOR":
                ok = tile in (".", "N") if row == 0 else tile in (".", "T")
            else:                                                       # NA_WALL: posters
                ok = tile == "N"
            if not ok:
                place = {"N": "the back wall", "W": "a wall", "T": "the owner's spot", "P": "the PC",
                         "D": "the doorway", "H": "a hole", "#": "something solid"}.get(tile, "something")
                problems.append(f"{what}: {'a poster goes on the back wall, not' if dec['perm'] == 'NA_WALL' else 'it would stand on'} {place}"
                                if dec["perm"] != "NA_WALL" or tile != "." else f"{what}: a poster goes on the back wall")
                break
        for k, c in enumerate(cells):
            covered[c] = dec["name"].title()
        for k, (cx, cy) in enumerate(cells):
            if dec["tiles"] and k < len(dec["tiles"]):
                room[cy][cx] = dec["tiles"][k]
    for d, pos in used:                                 # then the dolls and cushions, on top
        dec = t.decorations[d]
        if dec["perm"] != "SPRITE":
            continue
        x, y = pos >> 4, pos & 0xF
        what = f"{dec['name'].title()} at {x},{y}"
        if not (0 <= x < width and 0 <= y < height):
            problems.append(f"{what} is outside the room")
            continue
        tile = room[y][x]
        big = dec["shape"] == "1x2"
        if (big and tile != "L") or (not big and tile not in ("s", "L")):
            problems.append(f"{what}: {'a big doll needs a large spot on a desk or mat' if big else 'dolls and cushions sit on a mat or a desk'}")
        if (x, y) in dolls:
            problems.append(f"{what} is on top of another doll or cushion")
        dolls.add((x, y))
    for cat, n in counts.items():
        if n > DECOR_BAG[cat]:
            problems.append(f"{n} {cat.lower()}s: a player can own at most {DECOR_BAG[cat]}")
    return problems


def check_sb3(data, game=None):
    """(fields, problems, warnings). Problems: the game would misbehave (the tool refuses the
    file). Warnings: the game would take it, but a real player couldn't have made it."""
    t = tables()
    f = parse_sb3(data)
    problems, warnings = [], []
    if f["location"] not in t.locations:
        problems.append(f"location {f['location']} isn't one of the 75 Secret Base spots")
    raw = f["name_raw"]
    end = raw.find(b"\xff")
    n = 7 if end < 0 else end
    lang = f["language"]
    if lang not in (0,) + tuple(LANGUAGES):
        problems.append(f"language byte {lang} isn't a game language")
    limit = 5 if lang == 1 else 7
    if not 1 <= n <= limit or any(b != 0xFF for b in raw[n:]):
        problems.append(f"the owner's name must be 1 to {limit} characters, then 0xFF")
    else:
        table = _JP if lang == 1 else _WEST
        if any(b not in table for b in raw[:n]):
            problems.append("the owner's name uses characters outside its language's alphabet")
    decs, pos = f["decorations"], f["positions"]
    k = next((i for i, d in enumerate(decs) if not d), 16)
    if any(decs[k:]) or any(pos[k:]):
        problems.append("decorations must fill the first slots, with the rest all 0")
    if any(d > 120 for d in decs):
        problems.append("a decoration ID above 120")
    team = f["team"]
    count = next((i for i, m in enumerate(team) if not m["species"]), 6)
    if count == 0:
        problems.append("the owner has no Pokemon (a base's owner always battles)")
    for i, m in enumerate(team):
        label = f"Pokemon {i + 1}"
        if i >= count:
            if m["species"] or m["level"] or m["item"] or m["ev"] or m["personality"] or any(m["moves"]):
                problems.append(f"{label}: everything after the team must be 0")
            continue
        sp = m["species"]
        if not (1 <= sp <= 411) or 252 <= sp <= 276:
            problems.append(f"{label}: species {sp} isn't a Pokemon (the games' internal numbers: 1-251, 277-411)")
            continue
        label = f"{label} ({species_name(sp).title()})"
        if not 1 <= m["level"] <= 100:
            problems.append(f"{label}: level {m['level']}")
        mv = [x for x in m["moves"] if x]
        if not mv:
            problems.append(f"{label}: no moves")
        if any(x > 354 for x in m["moves"]):
            problems.append(f"{label}: a move above 354")
        if len(set(mv)) != len(mv):
            problems.append(f"{label}: the same move twice")
        top = MAX_ITEM.get(game, 376)
        if m["item"] and (m["item"] > top or t.items[m["item"]][1] == "POCKET_KEY_ITEMS" or not t.items[m["item"]][0]
                          or t.items[m["item"]][0] == "????????"):
            problems.append(f"{label}: item {m['item']} can't be held{' in ' + game if game else ''}")
        if m["ev"] > MAX_EV:
            warnings.append(f"{label}: EV number {m['ev']}; a real Pokemon's average is at most {MAX_EV}")
        lv, other = t.learn.get(sp, ({}, set()))
        for x in mv:
            if x <= 354 and x not in other and not (x in lv and lv[x] <= m["level"]):
                why = f"until level {lv[x]}" if x in lv else "at all"
                warnings.append(f"{label}: can't learn {move_name(x).title()} {why}")
    if f["location"] in t.locations and not any("decoration" in p for p in problems):
        warnings += check_decorations(f)
    if f["to_register"] or f["battled"] or f["registry"] or f["entered"] or f["unused"] or any(f["padding"]):
        warnings.append("the receiving player's own fields were set (cleared before sending)")
    return f, problems, warnings


def describe(f, game=None):
    """A few lines about a base, for the screen."""
    lang = LANGUAGES.get(f["language"], "language unknown")
    lines = [f"{owner_name(f)} ({'girl' if f['gender'] else 'boy'}, ID {f['tid']:05d}, {lang}): {location_text(f['location'])}"]
    decs = [decoration_name(d).title() for d in f["decorations"] if d]
    lines.append(f"  {len(decs)} decoration{'s' if len(decs) != 1 else ''}" + (f": {', '.join(decs)}" if decs else ""))
    team = [m for m in f["team"] if m["species"]]
    lines.append("  Team: " + ", ".join(f"{species_name(m['species']).title()} Lv {m['level']}" for m in team))
    return lines


def file_name(f, extra=""):
    """In the EventsGallery's style: OWNER - Tree, Route 121 (ENG).sb3"""
    name = re.sub(r'[\\/:*?"<>|]', "_", owner_name(f))
    return f"{name} - {location_short(f['location'])}{extra} ({LANG_SHORT.get(f['language'], 'ANY')}).sb3"


# ---------------------------------------------------------------- personality values
def choose_personality(species, nature=None, gender=None, ability=None, seed=0):
    """A personality value giving the nature (0-24), gender ('male'/'female') and ability slot
    (0/1) asked for; any of them may be None. The same request always gives the same value."""
    t = tables()
    ratio = t.gender[species]
    if gender and ratio in (0, 254, 255) and gender != {0: "male", 254: "female", 255: "genderless"}[ratio]:
        raise ValueError(f"{species_name(species).title()} can't be {gender}")
    if ability == 1 and not t.two_abilities[species]:
        raise ValueError(f"{species_name(species).title()} has only one ability")
    x = (seed * 2654435761 + species * 40503 + 0x1234567) & 0xFFFFFFFF
    for _ in range(200000):
        x = (x * 1103515245 + 24691) & 0xFFFFFFFF                # the games' own generator
        pid = x
        if nature is not None and pid % 25 != nature:
            continue
        if gender and ratio not in (0, 254, 255) and gender_of(species, pid) != gender:
            continue
        if ability is not None and t.two_abilities[species] and (pid & 1) != ability:
            continue
        return pid
    raise ValueError("no personality value found")


# ---------------------------------------------------------------- the base card
CARD_HELP = """# Secret Base card (docs/SB3_FORMAT.md). Lines are `key = value`; '#' starts a comment.
#   owner, gender (boy/girl), language, id, secret id, received, location (a name or the ID)
#   decoration = NAME at X, Y          up to 16; X, Y is the bottom-left tile
#   pokemon = SPECIES Lv N @ ITEM : MOVE, MOVE, MOVE, MOVE  EV N  nature NATURE  male/female  ability 1/2
#             (or `personality 0x1234ABCD` instead of nature/gender/ability)"""


def parse_location(text):
    """A location from a card: its ID, or e.g. 'Tree, Route 121' (with ', room 1' or 'at 43,7' when
    one route has two of a kind)."""
    t = tables()
    s = text.strip()
    m = re.search(r"\(ID (\d+)\)", s) or re.fullmatch(r"(\d+)", s)
    if m:
        bid = int(m.group(1))
        if bid not in t.locations:
            raise ValueError(f"location {bid} isn't a Secret Base spot")
        return bid
    low = s.lower()
    kind = next((k for k in sorted(ROOM_KINDS, key=len, reverse=True) if k in low), None)
    route = re.search(r"route\s*(\d+)", low)
    if not kind or not route:
        raise ValueError(f"location '{text}': give the kind and route, e.g. 'Tree, Route 121', or the ID")
    hits = [i for i, l in t.locations.items() if l["kind"] == kind and l["route"] == int(route.group(1))]
    room = re.search(r"room\s*(\d)", low)
    at = re.search(r"at\s*(\d+)\s*,\s*(\d+)", low)
    if room:
        hits = [i for i in hits if t.locations[i]["room"] == int(room.group(1))]
    if at:
        hits = [i for i in hits if (t.locations[i]["x"], t.locations[i]["y"]) == (int(at.group(1)), int(at.group(2)))]
    if not hits:
        raise ValueError(f"no {kind} Secret Base on Route {route.group(1)} like that")
    if len(hits) > 1:
        raise ValueError(f"Route {route.group(1)} has {len(hits)} {kind} spots: " + "; ".join(location_text(i) for i in hits))
    return hits[0]


_POKEMON = re.compile(r"^\s*(?P<species>.+?)\s+Lv\.?\s*(?P<level>\d+)\s*(?:@\s*(?P<item>[^:]+?))?\s*"
                      r"(?::\s*(?P<moves>[^:]*?))?\s*(?P<rest>(?:\s+(?:EV\s*\d+|nature\s+\w+|male|female|"
                      r"ability\s*[12]|personality\s+(?:0x)?[0-9A-Fa-f]+))*)\s*$", re.I)


def parse_pokemon(text, seed=0):
    t = tables()
    m = _POKEMON.match(text)
    if not m:
        raise ValueError(f"can't read the Pokemon '{text.strip()}': write e.g. "
                         "'Swampert Lv 45 @ Leftovers : Surf, Earthquake, Protect, Rest  EV 85  nature Brave'")
    rest = m.group("rest") or ""
    tail_moves = m.group("moves") or ""
    # the moves end where the options begin
    opt = re.search(r"\s+(?:EV\s*\d+|nature\s+\w+|male|female|ability\s*[12]|personality\s)", tail_moves, re.I)
    if opt:
        rest = tail_moves[opt.start():] + " " + rest
        tail_moves = tail_moves[:opt.start()]
    sp = _lookup(m.group("species"), [n if n != "?" else "" for n in t.species], "Pokemon")
    level = int(m.group("level"))
    item = _lookup(m.group("item").strip(), [n for n, _ in t.items], "item") if m.group("item") else 0
    moves = [_lookup(x.strip(), t.moves, "move") for x in tail_moves.split(",") if x.strip()]
    if len(moves) > 4:
        raise ValueError(f"{species_name(sp).title()}: at most four moves")
    ev = re.search(r"EV\s*(\d+)", rest, re.I)
    nature = re.search(r"nature\s+(\w+)", rest, re.I)
    gender = re.search(r"\b(male|female)\b", rest, re.I)
    ability = re.search(r"ability\s*([12])", rest, re.I)
    pid = re.search(r"personality\s+((?:0x)?[0-9A-Fa-f]+)", rest, re.I)
    if pid:
        personality = int(pid.group(1), 16 if pid.group(1).lower().startswith("0x") or re.search("[a-f]", pid.group(1), re.I) else 10)
    else:
        nat = None
        if nature:
            names = [n.lower() for n in NATURES]
            if nature.group(1).lower() not in names:
                raise ValueError(f"no nature called '{nature.group(1)}' (they are {', '.join(NATURES)})")
            nat = names.index(nature.group(1).lower())
        personality = choose_personality(sp, nat, gender.group(1).lower() if gender else None,
                                         int(ability.group(1)) - 1 if ability else None, seed)
    return dict(species=sp, level=level, item=item, moves=(moves + [0, 0, 0, 0])[:4],
                ev=int(ev.group(1)) if ev else 0, personality=personality & 0xFFFFFFFF)


def card_to_sb3(text, seed_from=None):
    """A base card's text -> 160 bytes. Raises ValueError with the first thing that's wrong."""
    t = tables()
    owner = gender = language = tid = sid = location = None
    received, decorations, team = 0, [], []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.split("#")[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"line {n}: expected `key = value`")
        key, value = (x.strip() for x in line.split("=", 1))
        key = key.lower().replace("_", " ")
        try:
            if key == "owner":
                owner = value
            elif key == "gender":
                if value.lower() not in ("boy", "girl", "male", "female"):
                    raise ValueError("gender is boy or girl")
                gender = 1 if value.lower() in ("girl", "female") else 0
            elif key == "language":
                names = {v.lower(): k for k, v in LANGUAGES.items()} | {v.lower(): k for k, v in LANG_SHORT.items() if k}
                if value.lower() not in names:
                    raise ValueError(f"language is one of {', '.join(LANGUAGES.values())}")
                language = names[value.lower()]
            elif key in ("id", "trainer id"):
                tid = int(value)
            elif key in ("secret id", "sid"):
                sid = int(value)
            elif key == "received":
                received = int(value)
            elif key == "location":
                location = parse_location(value)
            elif key == "decoration":
                m = re.fullmatch(r"(.+?)\s+at\s+(\d+)\s*,\s*(\d+)", value, re.I)
                if not m:
                    raise ValueError("write e.g. `decoration = Small Desk at 2, 3`")
                d = _lookup(m.group(1), [x["name"] if x else "" for x in t.decorations], "decoration")
                x, y = int(m.group(2)), int(m.group(3))
                if not (0 <= x <= 15 and 0 <= y <= 15):
                    raise ValueError("a decoration's X and Y are 0 to 15")
                decorations.append((d, x << 4 | y))
            elif key == "pokemon":
                team.append(parse_pokemon(value, seed=(seed_from or 0) + 7919 * len(team) + (tid or 0)))
            else:
                raise ValueError(f"unknown key '{key}'")
        except ValueError as err:
            raise ValueError(f"line {n}: {err}") from None
    for what, v in (("owner", owner), ("gender", gender), ("id", tid), ("location", location)):
        if v is None:
            raise ValueError(f"the card has no `{what} = ...`")
    language = language or 2
    if not 0 <= tid <= 65535 or (sid is not None and not 0 <= sid <= 65535):
        raise ValueError("trainer IDs are 0 to 65535")
    if sid is None:
        sid = (tid * 48271 + sum(owner.encode("utf-8"))) % 65536          # the same card, the same ID
    if len(decorations) > 16:
        raise ValueError(f"{len(decorations)} decorations: a base holds 16")
    if not 1 <= len(team) <= 6:
        raise ValueError(f"{len(team)} Pokemon: a base's owner has 1 to 6")
    b = bytearray(SB3_SIZE)
    b[0] = location
    b[1] = gender << 4
    b[2:9] = encode_name(owner, language)
    struct.pack_into("<HH", b, 9, tid, sid)
    b[0x0D] = language
    struct.pack_into("<H", b, 0x0E, received)
    for k, (d, p) in enumerate(decorations):
        b[0x12 + k], b[0x22 + k] = d, p
    for k, m in enumerate(team):
        struct.pack_into("<I", b, 0x34 + 4 * k, m["personality"])
        struct.pack_into("<4H", b, 0x4C + 8 * k, *m["moves"])
        struct.pack_into("<H", b, 0x7C + 2 * k, m["species"])
        struct.pack_into("<H", b, 0x88 + 2 * k, m["item"])
        b[0x94 + k], b[0x9A + k] = m["level"], m["ev"]
    return bytes(b)


def sb3_to_card(data):
    """An .sb3 as a base card (the card makes the same 160 bytes again)."""
    f = parse_sb3(data)
    out = ["# Secret Base card", f"owner      = {owner_name(f)}", f"gender     = {'girl' if f['gender'] else 'boy'}",
           f"language   = {LANGUAGES.get(f['language'], 'English')}", f"id         = {f['tid']:05d}",
           f"secret id  = {f['sid']:05d}"]
    if f["received"]:
        out.append(f"received   = {f['received']}")
    out.append(f"location   = {location_text(f['location'])}")
    out.append("")
    for d, p in zip(f["decorations"], f["positions"]):
        if d:
            out.append(f"decoration = {decoration_name(d).title()} at {p >> 4}, {p & 0xF}")
    out.append("")
    for m in f["team"]:
        if not m["species"]:
            continue
        moves = ", ".join(move_name(x).title() for x in m["moves"] if x)
        item = f" @ {item_name(m['item']).title()}" if m["item"] else ""
        nature = NATURES[m["personality"] % 25]
        g = gender_of(m["species"], m["personality"])
        out.append(f"pokemon = {species_name(m['species']).title()} Lv {m['level']}{item} : {moves}  EV {m['ev']}"
                   f"  personality 0x{m['personality']:08X}   # {nature}, {g}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- reading a save backup
def game_from_path(path):
    """(game, language) from a cartridge code in a backup's path, e.g. 'AXVE POKEMON RUBY/...'."""
    m = None
    for m in re.finditer(r"(?<![A-Z0-9])(AXV|AXP|BPE|BPR|BPG)([JEPFIDS])(?![A-Z0-9])", path.upper()):
        pass
    if not m:
        return None, None
    return GAME_CODES[m.group(1)], CODE_LANGUAGE[m.group(2)]


def save_block1(data):
    """SaveBlock 1 of the newest valid copy in a 128 KB Gen 3 save, or None."""
    best = None
    for slot in range(2):
        secs = {}
        for k in range(14):
            o = slot * 0xE000 + k * 0x1000
            blk = data[o:o + 0x1000]
            if len(blk) < 0x1000:
                break
            sid, ck, sig, idx = struct.unpack_from("<HHII", blk, 0xFF4)
            if sig != 0x08012025 or sid > 13:
                continue
            n = {0: 3884, 13: 2000}.get(sid, 3968)
            c = sum(struct.unpack_from(f"<{n // 4}I", blk, 0)) & 0xFFFFFFFF
            if ((c >> 16) + c) & 0xFFFF == ck:
                secs[sid] = (blk, idx)
        if all(k in secs for k in range(1, 5)) and 0 in secs:
            idx = secs[0][1]
            if best is None or idx > best[0]:
                best = (idx, b"".join(secs[k][0][:3968] for k in range(1, 5)))
    return best[1] if best else None


_ORDERS = "GAEM GAME GEAM GEMA GMAE GMEA AGEM AGME AEGM AEMG AMGE AMEG EGAM EGMA EAGM EAMG EMGA EMAG MGAE MGEA MAGE MAEG MEGA MEAG".split()


def _party_mon(mon):
    """(species, item, moves, level, personality, EV average, egg) of a 100-byte party Pokemon."""
    pid, otid = struct.unpack_from("<II", mon, 0)
    plain = struct.pack("<12I", *[w ^ pid ^ otid for w in struct.unpack_from("<12I", mon, 0x20)])
    part = {c: plain[12 * i:12 * i + 12] for i, c in enumerate(_ORDERS[pid % 24])}
    species, item = struct.unpack_from("<HH", part["G"], 0)
    moves = list(struct.unpack_from("<4H", part["A"], 0))
    evs = part["E"][0:6]
    egg = bool(struct.unpack_from("<I", part["M"], 4)[0] >> 30 & 1)
    return species, item, moves, mon[0x54], pid, sum(evs) // 6, egg


def bases_from_save(data, game, language):
    """The save's Secret Bases as .sb3 bytes, by slot (empty slots left out). Slot 0, the player's
    own, gets its team from the party, as the game fills it in at the moment it mixes records."""
    if game not in BASES_AT:
        raise ValueError(f"{game} has no Secret Bases" if game else
                         "which game is this save from? (name its folder after the cartridge, as maxduo_saves.py does, "
                         "or say --game Ruby/Sapphire/Emerald)")
    sb1 = save_block1(data)
    if sb1 is None:
        raise ValueError("no valid Pokemon save in this file")
    out = []
    for i in range(BASES_IN_SAVE):
        rec = bytearray(sb1[BASES_AT[game] + SB3_SIZE * i:BASES_AT[game] + SB3_SIZE * (i + 1)])
        if not rec[0]:
            continue
        if i == 0:                                     # SetPlayerSecretBaseParty
            rec[0x34:0xA0] = bytes(0xA0 - 0x34)
            count, k = sb1[PARTY_COUNT_AT], 0
            for j in range(min(count, 6)):
                sp, item, moves, level, pid, ev, egg = _party_mon(sb1[PARTY_AT + 100 * j:PARTY_AT + 100 * (j + 1)])
                if not sp or egg or sp == 412:
                    continue
                struct.pack_into("<I", rec, 0x34 + 4 * k, pid)
                struct.pack_into("<4H", rec, 0x4C + 8 * k, *moves)
                struct.pack_into("<H", rec, 0x7C + 2 * k, sp)
                struct.pack_into("<H", rec, 0x88 + 2 * k, item)
                rec[0x94 + k], rec[0x9A + k] = level, ev
                k += 1
        lang = rec[0x0D] if game == "Emerald" and rec[0x0D] else language
        out.append((i, normalise(bytes(rec), lang)))
    return out


# ---------------------------------------------------------------- what the game will keep
def predict_mix(own, ours, player):
    """secret_base.c's filing (ReceiveSecretBasesData, two players), run on the PC: `own` the game's
    20 bases as it sent them, `ours` the 20 we sent, `player` its (gender, trainer ID bytes, name
    bytes). Returns the game's 20 bases afterwards. (tests/mix_game_model.py has its own copy.)"""
    mine = [bytearray(b) for b in own]
    theirs = [bytearray(b) for b in ours]
    gender, tid, name = player

    def bits(b):
        return b[1] & 0xF, b[1] >> 4 & 1, b[1] >> 6

    def same_name(x, y):
        for i in range(7):
            if x[i] == 0xFF and y[i] == 0xFF:
                return True
            if x[i] != y[i]:
                return False
        return True

    def blank(b):
        b[:] = bytes(SB3_SIZE)
        b[2:9] = b"\xff" * 7

    def recv(b):
        return struct.unpack_from("<H", b, 0x0E)[0]

    for b in theirs:                                    # the first of the player's own, sent back
        if b[0] and bits(b)[1] == gender and bytes(b[9:13]) == bytes(tid) and same_name(b[2:9], name):
            blank(b)
            break
    for i in range(1, BASES_IN_SAVE):
        b = mine[i]
        if not b[0]:
            continue
        if bits(b)[2] == 1:
            b[1] = (b[1] & 0xF0) | 1
        for j, o in enumerate(theirs):
            if o[0] and bits(o)[1] == bits(b)[1] and o[9:13] == b[9:13] and same_name(o[2:9], b[2:9]):
                if recv(b) > recv(o):
                    blank(o)
                else:
                    o[1] = (o[1] & 0xF0) | (b[1] & 0xF)
                    blank(b)
                break
    for b in theirs:
        b[1] &= ~0x20

    def file_one(b):
        if not b[0]:
            return
        at = next((i for i in range(BASES_IN_SAVE) if mine[i][0] == b[0]), None)
        if at == 0:
            return
        if at is not None:
            if mine[at][1] & 0xF == 1:
                return
            if mine[at][1] >> 6 != 2 or b[1] & 0xF == 1:
                mine[at][:] = b
                mine[at][1] = (mine[at][1] & 0x3F) | 0x80
            return
        at = next((i for i in range(1, BASES_IN_SAVE) if not mine[i][0]), None)
        if at is None:
            at = next((i for i in range(1, BASES_IN_SAVE) if mine[i][1] >> 6 == 0 and mine[i][1] & 0xF == 0), None)
        if at is not None:
            mine[at][:] = b
            mine[at][1] = (mine[at][1] & 0x3F) | 0x80

    file_one(theirs[0])
    for status in (1, 0):
        for b in theirs[1:]:
            if b[1] >> 6 == status:
                file_one(b)
    for b in mine[1:]:
        if b[1] & 0xF == 1:
            b[1] = (b[1] & 0x30) | 0x40
    for i in range(1, BASES_IN_SAVE - 1):
        for j in range(i + 1, BASES_IN_SAVE):
            a, c = mine[i][1] >> 6, mine[j][1] >> 6
            if (a == 0 and c == 1) or (a == 2 and c != 2):
                mine[i], mine[j] = mine[j], mine[i]
    for b in mine[1:]:
        if b[1] >> 6 == 2:
            b[1] &= 0x3F
    n = recv(mine[0])
    if n != 0xFFFF:
        struct.pack_into("<H", mine[0], 0x0E, n + 1)
    return [bytes(b) for b in mine]


# ---------------------------------------------------------------- the command line
def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="secret_bases.py", description="Secret Base files (.sb3): read, make, extract.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show", help="print .sb3 files as base cards")
    s.add_argument("files", nargs="+")
    m = sub.add_parser("make", help="check base cards and write their .sb3 files")
    m.add_argument("cards", nargs="+")
    m.add_argument("--out", help="folder for the .sb3 files (default: beside each card)")
    m.add_argument("--strict", action="store_true", help="refuse a card with warnings too")
    x = sub.add_parser("save", help="write a save backup's Secret Bases as .sb3 files")
    x.add_argument("save")
    x.add_argument("--game", choices=["Ruby", "Sapphire", "Emerald"])
    x.add_argument("--out", help="folder (default: a 'bases' folder beside this tool)")
    a = ap.parse_args(argv)
    return {"show": show_files, "make": make_cards, "save": save_bases}[a.cmd](a)


def _say(text):
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, "replace").decode(enc, "replace"))


def show_files(a):
    for p in a.files:
        data = open(p, "rb").read()
        f, problems, warnings = check_sb3(data)
        _say(f"# {os.path.basename(p)}")
        _say(sb3_to_card(data))
        for w in problems:
            _say(f"# *** {w}")
        for w in warnings:
            _say(f"# (warning) {w}")


def make_cards(a):
    made = []
    for p in a.cards:
        data = card_to_sb3(open(p, encoding="utf-8").read(), seed_from=sum(os.path.basename(p).encode()))
        f, problems, warnings = check_sb3(data)
        for line in describe(f):
            _say(line)
        for w in warnings:
            _say(f"  (warning) {w}")
        if problems or (getattr(a, "strict", False) and warnings):
            raise ValueError(f"{os.path.basename(p)}: " + "; ".join(problems or warnings))
        out = getattr(a, "out", None) or os.path.dirname(os.path.abspath(p))
        os.makedirs(out, exist_ok=True)
        dest = os.path.join(out, file_name(f))
        open(dest, "wb").write(data)
        _say(f"  Written: {dest}")
        made.append(dest)
    return made


def save_bases(a):
    data = open(a.save, "rb").read()
    game, lang = game_from_path(os.path.abspath(a.save))
    game = getattr(a, "game", None) or game
    lang = lang or 2
    out = getattr(a, "out", None) or os.path.join(os.path.dirname(os.path.abspath(__file__)), "bases")
    found = bases_from_save(data, game, lang)
    if not found:
        _say("  This save has no Secret Bases (the player may not have Secret Power yet).")
        return []
    os.makedirs(out, exist_ok=True)
    src = os.path.splitext(os.path.basename(a.save))[0]
    written = []
    for slot, rec in found:
        f = parse_sb3(rec)
        whose = "the player's own" if slot == 0 else f"slot {slot}"
        dest = os.path.join(out, file_name(f, extra=f", from {src}"))
        open(dest, "wb").write(rec)
        _say(f"  {whose}: {describe(f)[0]}")
        written.append(dest)
    _say(f"  {len(written)} base{'s' if len(written) != 1 else ''} written to {out}")
    return written


# 75 locations: ID:kind:room:route:x:y (pokeemerald include/constants/secret_bases.h and the routes' maps)
_LOCATIONS = """
1:red_cave:1:118:47:14 2:red_cave:1:125:53:10 3:red_cave:1:113:49:8
11:red_cave:2:118:67:6 12:red_cave:2:121:40:11 13:red_cave:2:111:35:1
21:red_cave:3:115:20:53 22:red_cave:3:121:18:13 23:red_cave:3:119:26:81
31:red_cave:4:127:59:67 32:red_cave:4:125:55:11 33:red_cave:4:111:27:27
41:brown_cave:1:114:9:47 42:brown_cave:1:115:32:39 43:brown_cave:1:115:23:8
51:brown_cave:2:114:30:51 52:brown_cave:2:115:26:15 53:brown_cave:2:115:32:46
61:brown_cave:3:114:11:62 62:brown_cave:3:115:21:18 63:brown_cave:3:115:25:24
71:brown_cave:4:114:19:70 72:brown_cave:4:115:32:6 73:brown_cave:4:114:32:57
81:blue_cave:1:116:71:4 82:blue_cave:1:123:47:3 83:blue_cave:1:123:57:5
91:blue_cave:2:116:79:11 92:blue_cave:2:123:49:3 93:blue_cave:2:120:18:12
101:blue_cave:3:120:28:62 102:blue_cave:3:116:56:6 103:blue_cave:3:119:16:81
111:blue_cave:4:120:30:62 112:blue_cave:4:116:55:15 113:blue_cave:4:119:16:28
121:yellow_cave:1:111:33:34 122:yellow_cave:1:118:29:5 123:yellow_cave:1:127:45:24
131:yellow_cave:2:111:24:36 132:yellow_cave:2:125:7:25 133:yellow_cave:2:115:8:30
141:yellow_cave:3:111:34:50 142:yellow_cave:3:127:59:72 143:yellow_cave:3:127:61:21
151:yellow_cave:4:127:67:63 152:yellow_cave:4:125:24:32 153:yellow_cave:4:111:35:31
161:tree:1:111:13:19 162:tree:1:121:43:7 163:tree:1:118:47:5 164:tree:1:111:14:19 171:tree:2:118:46:5 172:tree:2:121:42:7
173:tree:2:119:19:76 174:tree:2:115:7:20 181:tree:3:110:16:25 182:tree:3:114:11:27 183:tree:3:115:8:20 191:tree:4:110:17:25
192:tree:4:114:12:27 193:tree:4:119:18:76 201:shrub:1:119:5:2 202:shrub:1:119:4:89 203:shrub:1:120:38:54 204:shrub:1:120:5:76
211:shrub:2:119:5:15 212:shrub:2:119:7:101 213:shrub:2:120:31:23 221:shrub:3:119:34:24 222:shrub:3:120:26:10 223:shrub:3:119:4:15
231:shrub:4:119:31:73 232:shrub:4:120:29:85 233:shrub:4:119:6:2
"""

# pokeemerald, packed (zlib + base64): names of species, moves, items (with pockets), decorations
# (permission, shape, category, the behaviour of each tile), the 24 rooms' tiles, gender ratios,
# second abilities; then, per species, the moves it and its pre-evolutions can learn. Tile letters:
# '.' floor, N back wall, W wall, T owner's spot, P PC, D doorway, s/L holds a small/large decoration,
# H hole, '#' solid, o anything else.
_TABLES = """
eNrtvQl4XNd1JniuSSyFHcRaWKuwkAQBFAmQICmZVOmhqlBVQm2qBUVApihSVmjJZmBrsRVbkcaJOZ2l3W53205LY82MR/pmPP5iqTuyHTF2xlEUT6LF
1thytyetjNOWqKXbTuLIiiwlXuacc+9b672HAsX4+/r7TIrCe/Vu/efde889+7340MRt773pxptvum3iyusmosafibmJ5UpmWStplSJep9fW1dVaIldR
l7GUVsxquXjCuElkEvmcuklvaMU4XpeuraSL5UwCL6tasZxX18sZrVTOp0t0HdPKiWIhTZfZRFkr5ONMvoyfrhQT/M1EIs5fW9VWKzmNHuMnxXQmg5eF
dDyZWNcv8uVy3rzGq6JWLmtlTV6liRa9VSGhFfNVvFrRLxKrWq6EP7Xicn6VEVa1WKrC30vLixL2tpQqJqr6NXYihde5dDxf1HLvuGPx8KED+n2a35Mu
r60kEjlHs0WzWV5drqZzSRqNTGJFSxfX9ctl7vhaJVNIn+CWORyjTIJe9Zp0MplZL1RWVmiM+KYsbzYqyxp1PpnPyIt8PJ7md01m8vksAaYziUKmkiXw
glbUSvrPRKws5zmf0/SrbL5M342nk5lEmT6MV5LlYjrPM5av8sNColhKa9TPQmk9XomtSvLqChllVU5SMZ1NaAUim8SBz6TLqQSPekyjrlGLfCZd1ZL6
VSpdzOjXOINESlsuaswMcXWlZbRVbUPLMqFYKl/QL1YT6krLFphrMplSoZivlCVTFdI5+oiHI1ZGXsM7vCkncmUtls+b18UKP0CWilfi8t21NWT3ouxk
IstvmFtXfIbcJzmjlMlXC/It6HK5yEOmJXOJbLqc0K/LvGpWtOJKohxL7SH2jyOhvPwpx7mU4DeIJ6rJPPNJkgaS6GcrNMClFHZErcVMfr1Ulu+GqyxD
w57SKjn1USKX1Ogin2OGiuMsbPAqS60XmBlXi9ryMn2JOFL2cS2fwaW7TMskgwxSzPMgJE4kkslYpWxcV7ARvUBlOZ+TvUNwjV4vlS5n87mMpMPXOCfU
60w6tpouV7hLq/mVFbkIcG425FUxtZ7KF3PyKq6Ll1yJmams5ZKJjOQF7FVpVWLiF0oJjQdNizODECPKRYgfqYVWKmvF9Yq6yErxU4yEsmleE6XYOnIm
9eaa9dwJvePacmVjQ05blgcROaiULvKrVIr5knyEkqNI7JZcxwUV508zWkGusXhaCqhEYo0HYw3lXVGKzWtwkOXVSkZTn+HD9SRf5XEJrfNQ4xW9Mvca
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
"""


if __name__ == "__main__":
    try:
        _cli(sys.argv[1:])
    except ValueError as err:
        sys.exit(f"Stopped: {err}")
