"""Makes battle_data.py: the Gen 3 numbers a battle needs, read from pret/pokeemerald's sources.

    python tools/make_battle_data.py                 fetch the sources from GitHub
    python tools/make_battle_data.py PATH            use a pokeemerald checkout at PATH

What it takes (facts about the games, no pictures or text): every species' base stats, types and
abilities (src/data/pokemon/species_info.h); every move's effect, power, type, accuracy, PP,
secondary-effect chance, target, priority and flags (src/data/battle_moves.h); the type chart
(gTypeEffectiveness in src/battle_main.c); every item's hold effect and its strength
(src/data/items.h); and the names of the constants, so the battle code can say EFFECT_SLEEP rather
than 1. The result is packed (JSON, zlib, base64) in battle_data.py, read by duo_battle.py."""
import base64, json, os, re, sys, urllib.request, zlib

RAW = "https://raw.githubusercontent.com/pret/pokeemerald/master/"
FILES = {
    "species": "include/constants/species.h", "moves": "include/constants/moves.h",
    "effects": "include/constants/battle_move_effects.h", "abilities": "include/constants/abilities.h",
    "hold": "include/constants/hold_effects.h", "items": "include/constants/items.h",
    "pokemon": "include/constants/pokemon.h", "battle_main_h": "include/battle_main.h",
    "battle_h": "include/battle.h", "species_info": "src/data/pokemon/species_info.h",
    "battle_moves": "src/data/battle_moves.h", "battle_main": "src/battle_main.c", "item_data": "src/data/items.h",
}


def source(root, name):
    rel = FILES[name]
    if root:
        return open(os.path.join(root, rel), encoding="utf-8").read()
    with urllib.request.urlopen(RAW + rel) as r:
        return r.read().decode("utf-8")


def defines(text, prefix):
    """{NAME: value} for '#define PREFIXNAME value' lines whose value is a number or a sum of known ones."""
    out = {}
    for name, value in re.findall(rf"#define\s+({prefix}\w+)\s+(.+?)\s*(?://.*)?$", text, re.M):
        expr = value.strip()
        expr = re.sub(r"\b([A-Z_][A-Z0-9_]*)\b", lambda m: str(out.get(m.group(1), m.group(0))), expr)
        try:
            out[name] = int(eval(expr, {"__builtins__": {}}))   # (only numbers, + - << | ( ) are left)
        except Exception:
            pass
    return out


def enum(text, prefix):
    """{NAME: value} for the members of C enums whose names start with prefix (counting up from 0,
    or from an explicit '= value')."""
    out = {}
    for body in re.findall(r"enum\s*\w*\s*\{(.*?)\};", text, re.S):
        k = 0
        for item in re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", body, flags=re.S)).split(","):
            item = item.strip()
            if not item:
                continue
            name, _, value = item.partition("=")
            name = name.strip()
            if value.strip():
                k = int(eval(re.sub(r"\b([A-Z_][A-Z0-9_]*)\b", lambda m: str(out[m.group(1)]), value), {"__builtins__": {}}))
            if name.startswith(prefix):
                out[name] = k
            k += 1
    return out


def entries(text, prefix):
    """{CONSTANT: {field: value text}} for designated initialisers '[PREFIX_X] = { .field = value, ... }'."""
    out = {}
    for m in re.finditer(rf"\[({prefix}\w+)\]\s*=\s*\{{\s*\n(.*?)\n\s*\}},", text, re.S):   # (not '= {0},')
        fields = {}
        for f, v in re.findall(r"\.(\w+)\s*=\s*(.*?),\s*\n", m.group(2) + ",\n"):
            fields[f] = v.strip().rstrip(",").strip()
        out[m.group(1)] = fields
    return out


def main(root=None):
    src = {k: source(root, k) for k in FILES}
    species = defines(src["species"], "SPECIES_")
    moves = defines(src["moves"], "MOVE_")
    effects = defines(src["effects"], "EFFECT_")
    abilities = defines(src["abilities"], "ABILITY_")
    hold = defines(src["hold"], "HOLD_EFFECT_")
    items = dict(enum(src["items"], "ITEM_"), **defines(src["items"], "ITEM_"))
    types = defines(src["pokemon"], "TYPE_")
    muls = defines(src["battle_main_h"], "TYPE_")
    targets = defines(src["battle_h"], "MOVE_TARGET_")
    flags = defines(src["pokemon"], "FLAG_")
    known = dict(species, **moves, **effects, **abilities, **hold, **items, **types, **muls, **targets, **flags)

    def num(text):
        text = text.strip()
        if text in known:
            return known[text]
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        if "|" in text:
            return sum({num(p) for p in text.split("|")})
        raise ValueError(f"can't read '{text}'")

    n_species = max(v for k, v in species.items() if k not in ("SPECIES_EGG", "NUM_SPECIES")) + 1
    sp_rows = [[0] * 10 for _ in range(n_species)]
    for name, f in entries(src["species_info"], "SPECIES_").items():
        if name not in species or "baseHP" not in f:
            continue
        t = [num(x) for x in re.findall(r"TYPE_\w+", f["types"])]
        a = [num(x) for x in re.findall(r"ABILITY_\w+", f["abilities"])]
        sp_rows[species[name]] = [num(f["baseHP"]), num(f["baseAttack"]), num(f["baseDefense"]), num(f["baseSpeed"]),
                                  num(f["baseSpAttack"]), num(f["baseSpDefense"]), t[0], t[1], a[0], a[1]]
    n_moves = defines(src["moves"], "MOVES_")["MOVES_COUNT"]
    mv_rows = [[0] * 9 for _ in range(n_moves)]
    for name, f in entries(src["battle_moves"], "MOVE_").items():
        if name in moves and moves[name] < n_moves:
            mv_rows[moves[name]] = [num(f["effect"]), num(f["power"]), num(f["type"]), num(f["accuracy"]), num(f["pp"]),
                                    num(f["secondaryEffectChance"]), num(f["target"]), num(f["priority"]), num(f.get("flags", "0"))]
    chart = src["battle_main"].split("gTypeEffectiveness")[1].split("};")[0]
    trip = [num(x) for x in re.findall(r"TYPE_\w+", chart)]
    held = {}
    for name, f in entries(src["item_data"], "ITEM_").items():
        if name in items and f.get("holdEffect", "HOLD_EFFECT_NONE") != "HOLD_EFFECT_NONE":
            held[items[name]] = [num(f["holdEffect"]), num(f.get("holdEffectParam", "0"))]
    names = lambda d, prefix: {str(v): k[len(prefix):] for k, v in d.items() if not k.startswith(("NUM_", prefix + "COUNT"))}
    data = dict(species=sp_rows, moves=mv_rows, type_chart=trip, held=held,
                effects=names(effects, "EFFECT_"), abilities=names(abilities, "ABILITY_"),
                hold_effects=names(hold, "HOLD_EFFECT_"),
                types={str(v): k[5:] for k, v in types.items() if v < 18 and not k.startswith("NUMBER")},
                targets={k[12:]: v for k, v in targets.items()}, flags={k[5:]: v for k, v in flags.items()})
    packed = base64.b64encode(zlib.compress(json.dumps(data, separators=(",", ":")).encode(), 9)).decode()
    lines = [packed[i:i + 100] for i in range(0, len(packed), 100)]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "battle_data.py")
    with open(out, "w", encoding="utf-8") as f:
        f.write('"""Gen 3 battle numbers from pret/pokeemerald (made by tools/make_battle_data.py; don\'t edit):\n'
                'base stats, types and abilities per species; effect, power, type, accuracy, PP, effect chance,\n'
                'target, priority and flags per move; the type chart; held items\' effects; the constants\' names."""\n'
                "import base64, json, zlib\n\n_PACKED = \"\"\"\n" + "\n".join(lines) + '\n"""\n\n'
                "DATA = json.loads(zlib.decompress(base64.b64decode(\"\".join(_PACKED.split()))))\n")
    print(f"battle_data.py: {n_species} species, {n_moves} moves, {len(trip) // 3} type-chart entries, "
          f"{len(held)} held items ({len(packed):,} characters)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
