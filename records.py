"""Record Mixing records and their parts, as files (docs/RECORD_FORMATS.md).

    python records.py show FILE...                 what a .rm3 or part file holds, and its checks
    python records.py split FILE [--out DIR]       a .rm3, or a Ruby/Sapphire save backup's own record,
                                                   into part files (.sb3 .tv3 .pn3 .om3 .dt3 .dm3 .bt3)
    python records.py join PART... --out FILE.rm3  part files into a whole record
    python records.py predict SAVE RECORD.rm3      what the save's game would keep after mixing with it

Ruby/Sapphire's layout first (the user's choice, 6 November): it is the one every game mixes with.
Each file holds the game's own bytes; this module reads, checks, writes and converts them. The
game's words (Easy Chat, TV scripts, the old man's lines) are never stored here: they are read from
the user's own cartridge copy by the workshop. Sources: pokeruby src/record_mixing.c, tv.c,
dewford_trend.c, mauville_man.c, battle_tower.c, daycare.c, include/global.h, include/tv.h."""
import argparse, os, struct, sys

import secret_bases as SB

# ------------------------------------------------------------------- the record (PlayerRecords)
RS_SIZE = 0x1230
PARTS = [  # (name, offset, size, count, extension)
    ("bases", 0x0000, 160, 20, ".sb3"),
    ("tv", 0x0C80, 36, 25, ".tv3"),
    ("news", 0x1004, 64, 1, ".pn3"),
    ("old_man", 0x1044, 64, 1, ".om3"),
    ("trends", 0x1084, 8, 5, ".dt3"),
    ("mail", 0x10AC, 120, 1, ".dm3"),
    ("tower", 0x1124, 164, 1, ".bt3"),
]
GIFT_AT = 0x11C8
EXT_PART = {p[4]: p[0] for p in PARTS}
PART = {p[0]: p for p in PARTS}

# In a Ruby/Sapphire save (SaveBlock 1 = sections 1-4, SaveBlock 2 = section 0)
SB1_AT = {"tv": 0x2738, "news": 0x2ABC, "old_man": 0x2D94, "trends": 0x2DD4, "daycare": 0x2F9C}
SB2_TOWER_AT = 0xA8

# ------------------------------------------------------------------- names (game facts, not text)
TV_KINDS = {1: "Fan Club letter", 2: "Recent happenings", 3: "Fan Club opinions", 4: "(unused show 4)",
            5: "Name Rater", 6: "Bravo Trainer: Pokémon profile", 7: "Bravo Trainer: Battle Tower profile",
            21: "Pokémon Today: caught", 22: "Smart Shopper", 23: "Pokémon Today: failed", 24: "Fishing advice",
            25: "World of Masters", 41: "Mass outbreak"}
OLD_MEN = ["Bard", "Hipster", "Trader", "Storyteller", "Giddy"]
NEWS_KINDS = {1: "Slateport sale", 2: "Game Corner", 3: "Lilycove festival", 4: "Blend Master"}   # tv.h POKENEWS_*
LEVEL_MODES = ["level 50", "level 100"]


def channel(kind):
    """tv.c GetTVChannelByShowType: 2 interviews (1-20), 3 records (21-40), 4 outbreaks (41-60)."""
    return 0 if not kind else 2 if kind <= 20 else 3 if kind <= 40 else 4 if kind <= 60 else 0


def words(ws):
    """Easy Chat words as group:index (the words themselves come from the user's ROM)."""
    return " ".join("-" if w == 0xFFFF else f"{w >> 9}:{w & 0x1FF}" for w in ws)


def text(raw, language=2):
    return SB.decode_name(bytes(raw), language)


# ------------------------------------------------------------------- the whole record
def split(rec):
    """{part: [bytes, ...]} from a Ruby/Sapphire record, plus 'gift' (an item number)."""
    if len(rec) != RS_SIZE:
        raise ValueError(f"a Ruby/Sapphire record is {RS_SIZE} bytes, not {len(rec)}"
                         + (" (5,188 is Emerald's own layout: not yet)" if len(rec) == 0x1444 else ""))
    out = {name: [bytes(rec[at + size * i:at + size * (i + 1)]) for i in range(count)]
           for name, at, size, count, _ in PARTS}
    out["gift"] = struct.unpack_from("<H", rec, GIFT_AT)[0]
    return out


def join(parts):
    """A Ruby/Sapphire record from {part: [bytes, ...]} (missing parts and slots left empty) and
    'gift'. The filler stays 0, as the game's does."""
    rec = bytearray(RS_SIZE)
    for name, at, size, count, _ in PARTS:
        items = parts.get(name) or []
        if len(items) > count:
            raise ValueError(f"at most {count} {name} in a record, not {len(items)}")
        for i, b in enumerate(items):
            if len(b) != size:
                raise ValueError(f"a {name} part is {size} bytes, not {len(b)}")
            rec[at + size * i:at + size * (i + 1)] = b
    struct.pack_into("<H", rec, GIFT_AT, parts.get("gift", 0))
    return bytes(rec)


# ------------------------------------------------------------------- reading a save's own record
def save_blocks(data):
    """(SaveBlock 1, SaveBlock 2) of the newest valid copy of a 128 KB Gen 3 save."""
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
        if all(k in secs for k in range(5)):
            idx = secs[0][1]
            if best is None or idx > best[0]:
                best = (idx, b"".join(secs[k][0][:3968] for k in range(1, 5)), secs[0][0][:3884])
    if not best:
        raise ValueError("no valid Pokémon save in this file")
    return best[1], best[2]


def _box_species_item(mon):
    pid, otid = struct.unpack_from("<II", mon, 0)
    plain = struct.pack("<12I", *[w ^ pid ^ otid for w in struct.unpack_from("<12I", mon, 0x20)])
    g = SB._ORDERS[pid % 24].index("G")
    return struct.unpack_from("<HH", plain, 12 * g)


def record_from_save(data, game="Ruby", language=2):
    """The record a Ruby or Sapphire save would send when it mixes now
    (record_mixing.c RecordMixing_PrepareExchangePacket): its bases with slot 0's team from the
    party, its TV shows with its own interviews taken off (sub_80C045C), its news, old man, trends,
    day-care letters (InitDaycareMailRecordMixing), its own Battle Tower record; no gift."""
    if game not in ("Ruby", "Sapphire"):
        raise ValueError(f"{game}: only Ruby and Sapphire saves so far")
    sb1, sb2 = save_blocks(data)
    bases = [b"\0" * 160] * 20
    for i, b in SB.bases_from_save(data, game, language):
        bases[i] = b
    tv = bytearray(sb1[SB1_AT["tv"]:SB1_AT["tv"] + 36 * 25])
    for i in range(5):                                 # sub_80C045C
        if channel(tv[36 * i]) == 2:
            tv[36 * i + 1] = 0
    d = SB1_AT["daycare"]
    mail = bytearray(120)
    mail[0:112] = sb1[d + 160:d + 160 + 112]           # misc.mail[2]
    count = 0
    for i in range(2):
        species, item = _box_species_item(sb1[d + 80 * i:d + 80 * (i + 1)])
        if species:
            count += 1
            mail[116 + 2 * i] = 0 if item == 0 else 1
        else:
            mail[116 + 2 * i] = 1
    struct.pack_into("<I", mail, 112, count)
    return join({"bases": bases, "tv": [bytes(tv[36 * i:36 * (i + 1)]) for i in range(25)],
                 "news": [sb1[SB1_AT["news"]:SB1_AT["news"] + 64]],
                 "old_man": [sb1[SB1_AT["old_man"]:SB1_AT["old_man"] + 64]],
                 "trends": [sb1[SB1_AT["trends"] + 8 * i:SB1_AT["trends"] + 8 * (i + 1)] for i in range(5)],
                 "mail": [bytes(mail)], "tower": [sb2[SB2_TOWER_AT:SB2_TOWER_AT + 164]], "gift": 0})


# ------------------------------------------------------------------- parts: reading and checking
def tower_checksum(rec):
    """battle_tower.c: the sum of the record's 32-bit words before the checksum."""
    return sum(struct.unpack_from(f"<{(len(rec) - 4) // 4}I", rec, 0)) & 0xFFFFFFFF


def with_tower_checksum(rec):
    rec = bytearray(rec)
    struct.pack_into("<I", rec, len(rec) - 4, tower_checksum(rec))
    return bytes(rec)


def parse_tower(rec):
    mode, cls, streak = struct.unpack_from("<BBH", rec, 0)
    party = []
    for k in range(3):
        o = 0x1C + 44 * k
        sp, item = struct.unpack_from("<HH", rec, o)
        if not sp:
            continue
        ivs = struct.unpack_from("<I", rec, o + 0x18)[0]
        party.append(dict(species=sp, item=item, moves=list(struct.unpack_from("<4H", rec, o + 4)), level=rec[o + 12],
                          pp_bonuses=rec[o + 13], evs=list(rec[o + 14:o + 20]), ot_id=struct.unpack_from("<I", rec, o + 20)[0],
                          ivs=[ivs >> (5 * i) & 31 for i in range(6)], ability=ivs >> 31 & 1,
                          personality=struct.unpack_from("<I", rec, o + 0x1C)[0], nickname=rec[o + 0x20:o + 0x2B],
                          friendship=rec[o + 0x2B]))
    return dict(mode=mode, trainer_class=cls, streak=streak, name=rec[4:12], tid=struct.unpack_from("<H", rec, 12)[0],
                sid=struct.unpack_from("<H", rec, 14)[0], greeting=list(struct.unpack_from("<6H", rec, 0x10)),
                party=party, checksum=struct.unpack_from("<I", rec, 0xA0)[0])


def parse_trend(t):
    a, rand, w1, w2 = struct.unpack("<HHHH", t)
    return dict(trendiness=a & 0x7F, max_trendiness=a >> 7 & 0x7F, rising=a >> 14 & 1, rand=rand, words=[w1, w2])


def parse_old_man(o):
    kind = o[0]
    f = dict(kind=kind, character=OLD_MEN[kind] if kind < 5 else f"unknown ({kind})")
    if kind == 0:
        f.update(song=list(struct.unpack_from("<6H", o, 2)), new_song=list(struct.unpack_from("<6H", o, 0x0E)),
                 player=o[0x1A:0x22], player_id=bytes(o[0x25:0x29]), changed=o[0x29])
    elif kind == 1:
        f.update(spoken=o[1])
    elif kind == 2:
        f.update(decorations=list(o[1:5]), traders=[o[5 + 11 * i:16 + 11 * i] for i in range(4)], traded=o[49])
    elif kind == 3:
        f.update(recorded=o[1], stats=list(o[4:8]), names=[o[8 + 7 * i:15 + 7 * i] for i in range(4)],
                 values=[struct.unpack_from("<I", o, 36 + 4 * i)[0] for i in range(4)])
    elif kind == 4:
        f.update(tale=o[1], question=o[2], words=list(struct.unpack_from("<10H", o, 4)), questions=list(o[0x18:0x24]))
    return f


def parse_mail(m):
    letters = []
    for i in range(2):
        o = 56 * i
        letters.append(dict(words=list(struct.unpack_from("<9H", m, o)), writer=m[o + 0x12:o + 0x1A],
                            writer_id=struct.unpack_from("<I", m, o + 0x1A)[0], species=struct.unpack_from("<H", m, o + 0x1E)[0],
                            mail_item=struct.unpack_from("<H", m, o + 0x20)[0], trainer=m[o + 0x24:o + 0x2C],
                            pokemon=m[o + 0x2C:o + 0x37]))
    count = struct.unpack_from("<I", m, 112)[0]
    return dict(letters=letters, count=count, no_item=[not m[116], not m[118]])


def check_part(kind, b):
    """(problems, warnings) for one part's bytes."""
    problems, warnings = [], []
    size = PART[kind][2]
    if len(b) != size:
        return [f"a {kind} part is {size} bytes, not {len(b)}"], []
    t = SB.tables()
    if kind == "tv":
        k = b[0]
        if k and k not in TV_KINDS:
            problems.append(f"show kind {k} isn't one Ruby or Sapphire has")
        if k and b[1] not in (0, 1):
            problems.append(f"'on the air' is {b[1]}, not 0 or 1")
    elif kind == "news":
        for i in range(16):
            kk, state, days = struct.unpack_from("<BBH", b, 4 * i)
            if kk and kk not in NEWS_KINDS:
                problems.append(f"news {i}: kind {kk} unknown")
    elif kind == "old_man":
        if b[0] > 4:
            problems.append(f"old man {b[0]} isn't one of the five")
    elif kind == "trends":
        f = parse_trend(b)
        if f["trendiness"] > f["max_trendiness"]:
            warnings.append("trendiness above its maximum (the game keeps it at or below)")
        if any(w == 0xFFFF for w in f["words"]) and any(w != 0xFFFF for w in f["words"]):
            problems.append("a trend needs both its words")
    elif kind == "tower":
        f = parse_tower(b)
        if any(b) and f["checksum"] != tower_checksum(b):
            problems.append(f"checksum {f['checksum']:#010x}, should be {tower_checksum(b):#010x} "
                            "(the game drops the trainer: ValidateBattleTowerRecordChecksums)")
        if f["mode"] > 1:
            problems.append(f"level mode {f['mode']} (0 = level 50, 1 = level 100)")
        for i, m in enumerate(f["party"]):
            if not 0 < m["species"] < len(t.species):
                problems.append(f"Pokémon {i + 1}: species {m['species']} unknown")
            if sum(m["evs"]) > 510:
                warnings.append(f"Pokémon {i + 1}: EVs total {sum(m['evs'])}, over 510")
            if m["level"] != (50 if f["mode"] == 0 else 100):
                warnings.append(f"Pokémon {i + 1}: level {m['level']} in a {LEVEL_MODES[f['mode'] & 1]} record")
        if f["party"] and len({m["species"] for m in f["party"]}) < len(f["party"]):
            warnings.append("the same species twice (the Tower doesn't allow it)")
    elif kind == "mail":
        f = parse_mail(b)
        if f["count"] > 2:
            problems.append(f"{f['count']} Pokémon in the day care (at most 2)")
    elif kind == "bases":
        if any(b):
            _, problems, warnings = SB.check_sb3(b)
    return problems, warnings


def describe(kind, b, language=2):
    """A line or two in plain words about one part."""
    if not any(b):
        return "(empty)"
    t = SB.tables()
    if kind == "bases":
        return SB.describe(SB.parse_sb3(b))
    if kind == "tv":
        tid = b[0x22] | b[0x23] << 8
        return f"{TV_KINDS.get(b[0], f'kind {b[0]}')}, {'on the air' if b[1] else 'off the air'}, made by trainer {tid:05d}"
    if kind == "news":
        items = [struct.unpack_from("<BBH", b, 4 * i) for i in range(16)]
        on = [f"{NEWS_KINDS.get(k, k)} ({d} days)" for k, s, d in items if k]
        return ", ".join(on) or "(no news)"
    if kind == "old_man":
        f = parse_old_man(b)
        if b[0] == 0:
            return f"the Bard, with a song by {text(f['player'], language) or '(nobody yet)'}: {words(f['song'])}"
        if b[0] == 2:
            return "the Trader, with " + ", ".join(SB.decoration_name(d) for d in f["decorations"] if d)
        if b[0] == 3:
            return "the Storyteller, with tales of " + ", ".join(text(n, language) for n in f["names"] if n[0] != 0xFF)
        return f"the {f['character']}"
    if kind == "trends":
        f = parse_trend(b)
        return f"'{words(f['words'])}', trendiness {f['trendiness']} of {f['max_trendiness']}"
    if kind == "mail":
        f = parse_mail(b)
        ls = [f"a letter from {text(l['writer'], language)} on {t.items[l['mail_item']][0] if l['mail_item'] < len(t.items) else l['mail_item']}"
              for l in f["letters"] if l["mail_item"]]
        return (", ".join(ls) or "no letters") + f"; {f['count']} Pokémon in the day care"
    if kind == "tower":
        f = parse_tower(b)
        team = ", ".join(SB.species_name(m["species"]) for m in f["party"])
        return (f"{text(f['name'], language)} ({f['tid']:05d}), {LEVEL_MODES[f['mode'] & 1]}, win streak {f['streak']}: {team}")
    return ""


def kind_of_file(path, data):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".rm3":
        return "record"
    if ext in EXT_PART:
        return EXT_PART[ext]
    raise ValueError(f"{os.path.basename(path)}: not a record file (.rm3 or {' '.join(EXT_PART)})")


# ------------------------------------------------------------------- what the game will keep
# The tool's own reading of pokeruby's merges for two players (tests/mix_game_model.py has an
# independent copy; the tests check they agree). "game" is the receiving Ruby or Sapphire.
SB2_TOWER_RECORDS_AT = 0xA8 + 0xA4
SB2_SEEN_AT = 0x18 + 0x44
GAME_CLEAR_FLAG = 0x804
SPECIES_FIELDS = {1: (2,), 3: (2,), 4: (6,), 5: (2, 0x1C), 6: (2,), 7: (0x0A, 0x14), 21: (0x10,), 23: (0x0C, 0x0E),
                  24: (4,), 25: (8, 4)}
ALWAYS_SHOWN = (2, 22, 41)                 # kinds that don't depend on the Pokédex


def _random(state):
    """The games' random number: (new state, value)."""
    state = (state * 1103515245 + 24691) & 0xFFFFFFFF
    return state, state >> 16


def game_state(save, game="Ruby", language=2):
    """What the game holds that decides the merge: its record as it would send it, its five Battle
    Tower trainers, its trainer ID, which Pokémon it has seen, and whether it has beaten the game."""
    sb1, sb2 = save_blocks(save)
    seen_bits = sb2[SB2_SEEN_AT:SB2_SEEN_AT + 52]
    clear = bool(sb1[0x1220 + GAME_CLEAR_FLAG // 8] >> (GAME_CLEAR_FLAG % 8) & 1)
    import duo_events
    def seen(species):
        dex = duo_events.pk3_species(species)[0] if 0 < species <= 411 else 0
        return dex > 0 and bool(seen_bits[(dex - 1) // 8] >> ((dex - 1) % 8) & 1)
    return dict(record=record_from_save(save, game, language), tid=struct.unpack_from("<I", sb2, 0x0A)[0],
                tower=[bytes(sb2[SB2_TOWER_RECORDS_AT + 164 * i:SB2_TOWER_RECORDS_AT + 164 * (i + 1)]) for i in range(5)],
                seen=seen, game_clear=clear)


def predict(state, ours, our_tid, game_is_player0=False):
    """What a Ruby or Sapphire keeps after mixing with one partner who sends `ours` (a record):
    returns {tv, news, old_man, trends, daycare_mail, tower, tower_slots}. `state` as game_state()
    gives it. tower_slots: where the partner's trainer may go (more than one when the game picks
    one of its lowest win streaks at random)."""
    mine = split(state["record"])
    theirs = split(ours)
    order = (mine, theirs) if game_is_player0 else (theirs, mine)
    ids = (state["tid"] & 0xFFFF, our_tid & 0xFFFF) if game_is_player0 else (our_tid & 0xFFFF, state["tid"] & 0xFFFF)
    me = 0 if game_is_player0 else 1
    out = {}

    # TV: each side's shows that are off the air move across, if the receiver didn't make them
    shows = [[bytearray(b) for b in order[p]["tv"]] for p in (0, 1)]
    def channel_of(kind):
        return channel(kind) if kind <= 60 else 0
    def give(show, to_id):
        lo, hi = to_id & 0xFF, to_id >> 8
        made_by, passed_by, passed_by2 = (show[0x22], show[0x23]), (show[0x20], show[0x21]), (show[0x1E], show[0x1F])
        ch = channel_of(show[0])
        if ch == 3:
            if passed_by == (lo, hi) or made_by == (lo, hi):
                return None
            moved = bytearray(show)
            moved[0x20:0x22], moved[0x1E:0x20] = bytes(passed_by2), bytes([lo, hi])
        elif ch in (2, 4):
            if made_by == (lo, hi):
                return None
            moved = bytearray(show)
            moved[0x22:0x24], moved[0x20:0x22] = bytes(passed_by), bytes([lo, hi])
        else:
            return None
        moved[1] = 1
        if ch == 4:
            moved[0x16:0x18] = b"\x01\x00"
        return moved
    while True:
        finished = 0
        for p in (0, 1):
            k = next((k for k in range(24) if not shows[p][k][1] and 1 <= shows[p][k][0] <= 60), None)
            if k is None:
                finished += 1
                continue
            q = 1 - p
            free = next((f for f in range(5, 24) if not shows[q][f][0]), None)
            moved = give(shows[p][k], ids[q]) if free is not None else None
            if moved is not None:
                shows[q][free] = moved
            shows[p][k] = bytearray(36)
        if finished == 2:
            break
    tv = shows[me]
    def compact(lo, hi):
        kept = [b for b in tv[lo:hi] if b[0]]
        tv[lo:hi] = kept + [bytearray(36) for _ in range(hi - lo - len(kept))]
    compact(0, 5); compact(5, 24)
    free = sum(1 for b in tv[5:24] if not b[0])
    if free < 5:
        tv[5:24] = tv[5 + 5 - free:24] + [bytearray(36) for _ in range(5 - free)]
    for b in tv[:24]:
        if b[0] in (0,) + ALWAYS_SHOWN:
            continue
        if b[0] in SPECIES_FIELDS:
            if not all(state["seen"](struct.unpack_from("<H", b, at)[0]) for at in SPECIES_FIELDS[b[0]]):
                b[1] = 0
        else:
            b[1] = 0
        if not state["game_clear"] and b[0] in (7, 41):
            b[1] = 0
    if not state["game_clear"]:
        for b in tv[:24]:
            if b[0] == 41:
                b[1] = 0
    out["tv"] = [bytes(b) for b in tv]

    # News: news of a kind the game hasn't got comes in as "upcoming"; Ruby keeps kinds 1-3
    news = [[list(struct.unpack_from("<BBH", order[p]["news"][0], 4 * i)) for i in range(16)] for p in (0, 1)]
    for i in range(16):
        for p in (0, 1):
            item = news[p][i]
            dst = news[1 - p]
            if item[0] and any(not d[0] for d in dst) and all(d[0] != item[0] for d in dst):
                dst[next(x for x in range(16) if not dst[x][0])] = [item[0], 1, item[2]]
    kept = [n for n in news[me] if 0 < n[0] <= 3]
    kept += [[0, 0, 0]] * (16 - len(kept))
    if not state["game_clear"]:
        kept = [[k, 0, d] for k, s_, d in kept]
    out["news"] = [tuple(n) for n in kept]

    # The old man: the partner's, talking afresh
    o = bytearray(theirs["old_man"][0])
    if o[0] in (0, 1, 2, 3):
        o[{0: 0x29, 1: 1, 2: 49, 3: 1}[o[0]]] = 0
    out["old_man"] = bytes(o)

    # Trends: everyone's, the trendier copy of a phrase, sorted, the top five
    pool = {}
    order_seen = []
    for p in (0, 1):
        for t in order[p]["trends"]:
            w = struct.unpack("<HHHH", t)
            key = w[2:]
            if key not in pool:
                pool[key] = w
                order_seen.append(key)
            elif pool[key][0] & 0x7F < w[0] & 0x7F:
                pool[key] = w
    items = [pool[k] for k in order_seen]
    rank = lambda w: (w[0] & 0x7F, w[0] >> 7 & 0x7F, w[1], w[2], w[3])
    for h in range(len(items)):
        for i in range(h + 1, len(items)):
            if rank(items[i]) >= rank(items[h]):
                items[i], items[h] = items[h], items[i]
    out["trends"] = [struct.pack("<HHHH", *w) for w in items[:5]] + [bytes(8)] * (5 - min(5, len(items)))

    # Day-care letters: swapped between the two sides' Pokémon that hold nothing
    mail = [bytearray(order[p]["mail"][0]) for p in (0, 1)]
    rng = ids[0] & 0xFFFF
    picks = []
    for p in (0, 1):
        m = mail[p]
        n = struct.unpack_from("<I", m, 112)[0]
        free = [j < min(n, 2) and not m[116 + 2 * j] for j in (0, 1)]
        if free[0] != free[1]:
            picks.append((p, 0 if free[0] else 1))
        elif free[0]:
            has = [struct.unpack_from("<H", m, 56 * j + 0x20)[0] != 0 for j in (0, 1)]
            if has[0] != has[1]:
                picks.append((p, 0 if has[0] else 1))
            else:
                rng, r = _random(rng)
                picks.append((p, r % 2))
    if len(picks) == 2:
        (a, ja), (b, jb) = picks
        la, lb = bytes(mail[a][56 * ja:56 * ja + 56]), bytes(mail[b][56 * jb:56 * jb + 56])
        mail[a][56 * ja:56 * ja + 56], mail[b][56 * jb:56 * jb + 56] = lb, la
    out["daycare_mail"] = bytes(mail[me][:112])

    # The Battle Tower: the partner's trainer into one of the five
    new = theirs["tower"][0]
    tower = [bytes(r) for r in state["tower"]]
    same = [i for i, r in enumerate(tower) if r[12:16] == new[12:16] and r[8] == new[8]]
    empty = [i for i, r in enumerate(tower) if struct.unpack_from("<H", r, 2)[0] == 0]
    if same:
        slots = same[:1]
    elif empty:
        slots = empty[:1]
    else:
        streaks = [struct.unpack_from("<H", r, 2)[0] for r in tower]
        slots = [i for i, v in enumerate(streaks) if v == min(streaks)]
    out["tower_slots"] = slots
    out["tower"] = [new if i == slots[0] else r for i, r in enumerate(tower)] if len(slots) == 1 else tower
    return out


# ------------------------------------------------------------------- command line
def _show(paths):
    bad = 0
    for p in paths:
        data = open(p, "rb").read()
        kind = kind_of_file(p, data)
        print(os.path.basename(p))
        items = []
        if kind == "record":
            parts = split(data)
            for name, _, size, count, _ in PARTS:
                for i, b in enumerate(parts[name]):
                    if any(b):
                        items.append((name, i, b))
            print(f"  gift item: {SB.item_name(parts['gift']) if parts['gift'] else 'none'}")
        elif len(data) % PART[kind][2] == 0 and kind in ("tv", "trends") and len(data) > PART[kind][2]:
            raise ValueError(f"{p}: one {kind} per file")
        else:
            items.append((kind, 0, data))
        for name, i, b in items:
            problems, warnings = check_part(name, b)
            print(f"  {name} {i}: {describe(name, b)}")
            for x in problems:
                print(f"    PROBLEM: {x}")
            for x in warnings:
                print(f"    note: {x}")
            bad += bool(problems)
    return 1 if bad else 0


def _split(path, out):
    data = open(path, "rb").read()
    base = os.path.splitext(os.path.basename(path))[0]
    if path.lower().endswith(".rm3"):
        rec = data
    else:
        game, language = SB.game_from_path(os.path.abspath(path))
        rec = record_from_save(data, game or "Ruby", language or 2)
    os.makedirs(out, exist_ok=True)
    parts = split(rec)
    written = []
    if not path.lower().endswith(".rm3"):
        name = os.path.join(out, base + ".rm3")
        open(name, "wb").write(rec)
        written.append(name)
    for name, _, size, count, ext in PARTS:
        for i, b in enumerate(parts[name]):
            if not any(b) or (name == "tv" and not b[0]):
                continue
            fn = os.path.join(out, f"{base} - {name} {i}{ext}")
            open(fn, "wb").write(b)
            written.append(fn)
    for w in written:
        print(w)
    return 0


def _join(paths, out, gift):
    parts = {}
    for p in paths:
        data = open(p, "rb").read()
        kind = kind_of_file(p, data)
        if kind == "record":
            raise ValueError("join takes part files, not a .rm3")
        parts.setdefault(kind, []).append(data)
    if gift:
        parts["gift"] = SB._lookup(gift, [i[0] for i in SB.tables().items], "item")
    if "tower" in parts:
        parts["tower"] = [with_tower_checksum(b) for b in parts["tower"]]
    rec = join(parts)
    open(out, "wb").write(rec)
    print(out)
    return 0


def _predict(save_path, ours_path, our_tid, first):
    game, language = SB.game_from_path(os.path.abspath(save_path))
    state = game_state(open(save_path, "rb").read(), game or "Ruby", language or 2)
    ours = open(ours_path, "rb").read()
    before, after = split(state["record"]), predict(state, ours, our_tid, first)
    print(f"What the game keeps after mixing with {os.path.basename(ours_path)} (Ruby's own rules):")
    new = [b for b in after["tv"][5:24] if b[0] and b not in before["tv"]]
    print(f"  TV: {len(new)} new show(s)" + "".join(f"\n    {describe('tv', b, language or 2)}" for b in new))
    kinds = [NEWS_KINDS.get(k, k) for k, st, d in after["news"] if k]
    print(f"  News: {', '.join(map(str, kinds)) or 'none'}" + ("" if state["game_clear"] else " (not active until the game is beaten)"))
    print(f"  Old man: {describe('old_man', after['old_man'], language or 2)}")
    print("  Trends, top first:")
    for t in after["trends"]:
        if any(t):
            print(f"    {describe('trends', t)}")
    changed = after["daycare_mail"] != before["mail"][0][:112]
    print(f"  Day-care letters: {'swapped' if changed else 'unchanged'}")
    slots = after["tower_slots"]
    print(f"  Battle Tower: the partner's trainer goes to slot {slots[0] + 1}" if len(slots) == 1 else
          f"  Battle Tower: the partner's trainer replaces one of slots {', '.join(str(x + 1) for x in slots)} (the game picks)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="records.py", description="Record Mixing records and their parts, as files.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show"); s.add_argument("files", nargs="+")
    s = sub.add_parser("split"); s.add_argument("file"); s.add_argument("--out", default=".")
    s = sub.add_parser("join"); s.add_argument("files", nargs="+"); s.add_argument("--out", required=True)
    s.add_argument("--gift", help="a gift item for the others (only player 0's counts)")
    s = sub.add_parser("predict", help="what a Ruby or Sapphire save would keep after mixing with a record")
    s.add_argument("save"); s.add_argument("record", help="the partner's record (.rm3)")
    s.add_argument("--partner-id", type=int, default=0, help="the partner's trainer ID (default 0)")
    s.add_argument("--game-first", action="store_true", help="the game is player 0 (the cable's master end)")
    a = ap.parse_args(argv)
    import runlog
    runlog.start("records", argv)
    try:
        if a.cmd == "show":
            return _show(a.files)
        if a.cmd == "split":
            return _split(a.file, a.out)
        if a.cmd == "predict":
            return _predict(a.save, a.record, a.partner_id, a.game_first)
        return _join(a.files, a.out, a.gift)
    except (ValueError, OSError) as e:
        print(f"records.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
