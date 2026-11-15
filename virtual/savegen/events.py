"""events.py - real event Pokemon for the DUO's side of the rehearsals and videos: picked at random
from a folder of .pk3 files (Project Pokemon's EventsGallery, say), raised to level 50, and written
as offer.pk3 (for trades) and team1.pk3 / team2.pk3 (for battles, contests and the Tower).

    python3 virtual/savegen/events.py FOLDER OUT [--seed N] [--level 50] [--kanto-offer]

Raising a level is something a player can really do, so only events met at or below the level are
picked (a level 70 event can't come down to 50), and each one must still pass the toolkit's own
legality check afterwards. The species are all different. --kanto-offer: the Pokemon to trade is
one of the first 151 and not Mew (FireRed and LeafGreen take only those before the National
Pokedex). Nothing from the folder is kept beyond the three files written.
"""
import argparse, os, random, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))


def at_level(data, level=50):
    """The Pokemon at this level (its experience set to the level's minimum for its growth rate), as
    PKHeX's decrypted 80-byte .pk3, with its checksum. Everything else stays as the event gave it."""
    import duo_events as E
    f, problems = E.parse_pk3(data)
    if problems:
        raise ValueError("; ".join(problems))
    growth = E.PK3_BASE_STATS[(f["species"] - 1) * 7 + 6]
    blocks = bytearray(f["blocks"])
    struct.pack_into("<I", blocks, 4, E.pk3_exp_for_level(growth, level))
    head = bytearray(data[:0x20])
    struct.pack_into("<H", head, 0x1C, sum(struct.unpack("<24H", bytes(blocks))) & 0xFFFF)
    return bytes(head) + bytes(blocks)


def level_of(data):
    import duo_events as E
    f, _ = E.parse_pk3(data)
    return E.pk3_party_fields(f)[4]


def candidates(folder, level=50, log=print):
    import duo_battle as B
    import duo_events as E
    out = []
    for root, _, files in os.walk(folder):
        for name in sorted(files):
            if not name.lower().endswith(".pk3"):
                continue
            path = os.path.join(root, name)
            try:
                data = open(path, "rb").read()
                f, problems = E.parse_pk3(data)
                if problems or f["egg"] or level_of(data) > level:
                    continue
                raised = at_level(data, level)
                if B.check_legal(raised)[0]:
                    continue
                out.append((path, f["species"], f["dex"], raised))
            except Exception:
                continue
    return out


def pick(folder, n=3, seed=None, level=50, kanto_offer=False):
    """n event Pokemon of different species, the first suitable for a trade."""
    pool = candidates(folder, level)
    rng = random.Random(seed)
    rng.shuffle(pool)
    chosen, seen = [], set()
    if kanto_offer:
        first = next((c for c in pool if 0 < c[2] <= 150), None)
        if first:
            chosen.append(first)
            seen.add(first[1])
    for c in pool:
        if len(chosen) == n:
            break
        if c[1] not in seen:
            chosen.append(c)
            seen.add(c[1])
    if len(chosen) < n:
        raise SystemExit(f"only {len(chosen)} suitable event Pokemon in {folder} (need {n}, at or below level {level})")
    return chosen


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder")
    ap.add_argument("out")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--level", type=int, default=50)
    ap.add_argument("--kanto-offer", action="store_true")
    a = ap.parse_args()
    import duo_events as E
    os.makedirs(a.out, exist_ok=True)
    chosen = pick(a.folder, 3, a.seed, a.level, a.kanto_offer)
    for fname, (path, sp, dex, raised) in zip(("offer.pk3", "team1.pk3", "team2.pk3"), chosen):
        with open(os.path.join(a.out, fname), "wb") as f:
            f.write(raised)
        print(f"  {fname}: {E.parse_pk3(raised)[0]['name']} (Lv {a.level}), from {os.path.basename(path)}")
    print("PASS")


if __name__ == "__main__":
    main()
