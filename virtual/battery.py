"""battery.py - every rehearsal for every ROM in a folder, for an overnight run (14 November 2026).

    python3 virtual/battery.py --roms DIR --gallery DIR --kit DIR --out DIR [--flash duo_flash.bin]

For each ROM under --roms (any depth): savegen makes a fresh save and its states, then every
rehearsal that game has runs from them, each in its own folder under OUT/<rom label>/. Event files
come from the Events Gallery (--gallery: its "Released/Gen 3" folder or the gallery's root), in the
ROM's own language: the Eon Ticket (.me3) for Ruby and Sapphire's Mystery Event, and for Mystery
Gift each Wonder Card for that game (E - ... for Emerald, FL - ... for FireRed and LeafGreen).
--kit holds willow.sb3, bard.om3 and trend.dt3 for Record Mixing.

Run it again on the same OUT and it skips what has already passed (OUT/done.jsonl), so a second
pass after `git pull` runs only what's new or failed: games savegen has learnt since, new
rehearsals, and failures again with any fixes. A ROM
savegen doesn't know is noted "not supported yet" and tried again next time.

Each ROM also gets the unlock: its own language's secret phrase for Mystery Gift or Mystery Event,
typed into the game (savegen/phrases.py).

After the ROMs, every Wonder Card and Mystery Event in the gallery goes through the real tool and DUO
program in the simulator, against each game and language it's for (tests/gallery_events.py): the
Virtual DUO can't rehearse Mystery Gift yet, so this is its check across every language.

OUT/summary.txt has a line per ROM and per pass; each rehearsal's output is OUT/<label>/<test>.out.
"""
import argparse, glob, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLKIT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "savegen"))
REH = os.path.join(HERE, "rehearsals")
LANG_DIR = {"English": "ENG", "French": "FRE", "German": "GER", "Italian": "ITA", "Spanish": "SPA",
            "Japanese": "JPN"}


def label_of(path):
    """'Pokemon - Version Rubis (France) (Rev 1).gba' -> 'ruby_france' (game from the folder or name)."""
    base = os.path.basename(path)
    region = re.findall(r"\(([^)]*)\)", base)
    region = (region[0] if region else "rom").lower().replace(", ", "_").replace(" ", "_")
    folder = os.path.basename(os.path.dirname(path)).lower()
    return f"{folder}_{region}"


def profile_of(rom):
    import profiles
    try:
        p = profiles.for_rom(rom)
    except (Exception, SystemExit) as err:          # (for_rom exits with a message for a ROM it doesn't know)
        return None, (str(err).splitlines() or ["unknown ROM"])[0][:120]
    words = p.TITLE.split()
    lang = words[0]
    game = next((w for w in words[1:] if w[0].isalpha()), "").lower()
    return (game, lang, p.TITLE), None


def gallery_files(gallery, lang, pattern):
    d = LANG_DIR.get(lang)
    roots = [os.path.join(gallery, "Released", "Gen 3"), gallery]
    for r in roots:
        hits = sorted(glob.glob(os.path.join(r, d, "Wondercards", pattern)))
        if hits:
            return hits
    return []


def tests_for(game, lang, S, P, kit, gallery):
    """(name, script, args) for each rehearsal this game has. S: savegen's states, P: its pk3s."""
    mix = ["--", "--base", f"{kit}/willow.sb3", "--old-man", f"{kit}/bard.om3", "--trend", f"{kit}/trend.dt3"]
    team = ["--pk3", f"{P}/team1.pk3", f"{P}/team2.pk3"]
    # the secret phrase that unlocks Mystery Gift or Mystery Event, typed into the game in its own
    # language (savegen/phrases.py; docs/UNLOCKING.md)
    out = [("unlock", "@phrase", [])]
    if game == "emerald" and lang == "Japanese":
        out.append(("unlock_event", "@phrase", ["--kind", "event"]))
    if game in ("ruby", "sapphire"):
        out += [("trade", "trade", ["--state", f"{S}/at_trade_question.state", "--pk3", f"{P}/offer.pk3", "--slot", "5"]),
                ("single", "colosseum", ["--state", f"{S}/at_colosseum_question.state", *team]),
                ("double", "colosseum", ["--state", f"{S}/at_colosseum_question.state", "--mode", "double", *team]),
                ("mix", "mix", ["--state", f"{S}/at_record_question.state", "@OUT", *mix]),
                ("blender1", "blender", ["--state", f"{S}/at_blender_question.state", "--duo-player", "1"]),
                ("blender0", "blender", ["--state", f"{S}/at_blender_question.state", "--duo-player", "0"])]
        # (the tool sends Mystery Events only for Japanese, English and German games so far: the others'
        # files go through gallery_events.py, which reports them as not supported yet)
        for me3 in (gallery_files(gallery, lang, "RS - *.me3") if lang in ("Japanese", "English", "German") else []):
            tag = re.sub(r"[^a-z0-9]+", "_", os.path.basename(me3).lower().replace(".me3", ""))[-24:].strip("_")
            out.append((f"event_{tag}", "event", ["--state", f"{S}/at_link_standby.state", "--me3", me3]))
    else:
        M = f"{S}/at_cable_club_menu.state"
        out += [("trade", "trade", ["--state", M, "--pk3", f"{P}/offer.pk3", "--slot", "6"]),
                ("single", "colosseum", ["--state", M, *team]),
                ("double", "colosseum", ["--state", M, "--mode", "double", *team])]
        if game == "emerald":
            out += [("mix", "mix", ["--state", M, "@OUT", *mix]),
                    ("blender1", "blender", ["--state", f"{S}/at_blender_question.state", "--duo-player", "1"]),
                    ("blender0", "blender", ["--state", f"{S}/at_blender_question.state", "--duo-player", "0"]),
                    ("contest1", "contest", ["--state", f"{S}/at_contest_question.state", "--pk3", f"{P}/team1.pk3", "--duo-player", "1"]),
                    ("contest0", "contest", ["--state", f"{S}/at_contest_question.state", "--pk3", f"{P}/team1.pk3", "--duo-player", "0"]),
                    ("tower1", "tower", ["--state", f"{S}/at_tower_link_question.state", *team, "--retire-after", "2", "--duo-player", "1"]),
                    ("tower0", "tower", ["--state", f"{S}/at_tower_link_question.state", *team, "--retire-after", "2", "--duo-player", "0"])]
        if os.path.exists(os.path.join(REH, "gift.py")):          # Mystery Gift, once its rehearsal exists
            pat = "E - *.wc3" if game == "emerald" else "FL - *.wc3"
            for wc3 in gallery_files(gallery, lang, pat):
                tag = re.sub(r"[^a-z0-9]+", "_", os.path.basename(wc3).lower().replace(".wc3", ""))[-28:].strip("_")
                out.append((f"gift_{tag}", "gift", ["--state", f"{S}/at_title_mystery_gift.state", "--wc3", wc3]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--roms", required=True)
    ap.add_argument("--gallery", required=True)
    ap.add_argument("--kit", default=os.path.expanduser("~/kit"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--flash", default=os.path.join(TOOLKIT, "firmware", "build", "duo_flash.bin"))
    ap.add_argument("--timeout", type=int, default=1800, help="seconds a rehearsal may take (default 1800)")
    a = ap.parse_args()
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    done_path = os.path.join(out, "done.jsonl")
    done = set()
    if os.path.exists(done_path):
        with open(done_path) as f:
            # (only what passed: a failure is tried again next pass, after `git pull` has brought any fix)
            done = {r["key"] for r in map(json.loads, filter(str.strip, f)) if r.get("ok")}
    summary = open(os.path.join(out, "summary.txt"), "a")

    def note(s):
        line = f"{time.strftime('%H:%M:%S')}  {s}"
        print(line, flush=True)
        summary.write(line + "\n")
        summary.flush()

    head = subprocess.run(["git", "log", "--oneline", "-1"], cwd=TOOLKIT, capture_output=True, text=True).stdout.strip()
    note(f"pass started; toolkit at {head}")
    roms = sorted(glob.glob(os.path.join(a.roms, "**", "*.gba"), recursive=True))
    total = {"pass": 0, "fail": 0, "skipped": 0, "unsupported": 0}
    for rom in roms:
        label = label_of(rom)
        prof, why = profile_of(rom)
        if not prof:
            note(f"{label}: not supported yet ({why})")
            total["unsupported"] += 1
            continue
        game, lang, title = prof
        D = os.path.join(out, label)
        S = os.path.join(D, "made")
        P = os.path.join(S, "pk3")
        tests = tests_for(game, lang, S, P, a.kit, a.gallery)
        todo = [t for t in tests if f"{label}/{t[0]}" not in done]
        if not todo:
            total["skipped"] += len(tests)
            continue
        os.makedirs(D, exist_ok=True)
        sav = glob.glob(os.path.join(S, "*.sav"))
        if not sav:
            r = subprocess.run([sys.executable, os.path.join(HERE, "savegen", "savegen.py"), "--rom", rom, "--out", S,
                                "--pk3s", P], capture_output=True, text=True, timeout=3600)
            with open(os.path.join(D, "savegen.out"), "w") as f:
                f.write(r.stdout + r.stderr)
            last = (r.stdout.strip().splitlines() or [""])[-1]
            sav = glob.glob(os.path.join(S, "*.sav"))
            if r.returncode or not last.startswith("PASS") or not sav:
                note(f"{label} ({title}): savegen FAILED ({last[:100]})")
                total["fail"] += 1
                continue
        passed, failed = [], []
        for name, script, args in todo:
            args = [x if x != "@OUT" else "--out" for x in args]
            if "--out" in args:                       # (mix: --out before its "--")
                i = args.index("--out")
                args = args[:i + 1] + [os.path.join(D, name)] + args[i + 1:]
            else:
                args = args + ["--out", os.path.join(D, name)]
            cmd = [sys.executable, os.path.join(REH, script + ".py"), "--rom", rom, "--sav", sav[0],
                   "--duo-flash", a.flash, *args]
            if script == "@phrase":
                cmd = [sys.executable, os.path.join(HERE, "savegen", "phrases.py"), "play", rom, sav[0],
                       *[x for x in args if x != "--out" and x != os.path.join(D, name)]]
            t0 = time.time()
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=a.timeout)
                text, rc = r.stdout + r.stderr, r.returncode
            except subprocess.TimeoutExpired as e:
                text, rc = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), -9
                text += f"\n(timed out after {a.timeout} s)"
            with open(os.path.join(D, name + ".out"), "w") as f:
                f.write(text)
            ok = rc == 0 and (text.strip().splitlines() or [""])[-1].startswith("PASS")
            (passed if ok else failed).append(name)
            for link in glob.glob(os.path.join(D, name, "**", "link.log"), recursive=True):
                os.remove(link)                           # (big, and only for debugging here)
            with open(done_path, "a") as f:
                f.write(json.dumps(dict(key=f"{label}/{name}", ok=ok, s=round(time.time() - t0))) + "\n")
        total["pass"] += len(passed)
        total["fail"] += len(failed)
        note(f"{label} ({title}): {len(passed)} passed, {len(failed)} failed"
             + (f" | FAIL {' '.join(failed)}" if failed else ""))
    # The Events Gallery's own files in the simulator (tests/gallery_events.py): Mystery Gift with every
    # Wonder Card, Mystery Event with every Eon Ticket, each against the games and language it's for
    ge = os.path.join(TOOLKIT, "tests", "gallery_events.py")
    listed = subprocess.run([sys.executable, ge, "list", a.gallery], capture_output=True, text=True, cwd=os.path.dirname(ge))
    rows = [l.split("\t", 1) for l in listed.stdout.splitlines() if "\t" in l]
    gp, gf, gn, gfail = 0, 0, 0, []
    G = os.path.join(out, "gallery")
    os.makedirs(G, exist_ok=True)
    for game, path in rows:
        key = f"gallery/{os.path.basename(path)}/{game}"
        if key in done:
            total["skipped"] += 1
            continue
        try:
            r = subprocess.run([sys.executable, ge, "one", path, game], capture_output=True, text=True,
                               timeout=900, cwd=os.path.dirname(ge))
            text, rc = r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            text, rc = "FAIL: timed out after 900 s", 1
        last = (text.strip().splitlines() or ["FAIL: no output"])[-1]
        with open(os.path.join(G, re.sub(r"[^A-Za-z0-9]+", "_", f"{os.path.basename(path)}_{game}") + ".out"), "w") as f:
            f.write(text)
        ok = rc == 0 and last.startswith("PASS")
        if ok:
            gp += 1
        elif last.startswith("NOT SUPPORTED"):
            gn += 1
        else:
            gf += 1
            gfail.append(f"{os.path.basename(path)} ({game})")
        with open(done_path, "a") as f:
            f.write(json.dumps(dict(key=key, ok=ok, line=last[:200])) + "\n")
    if rows:
        total["pass"] += gp
        total["fail"] += gf
        if gp or gf or gn:
            note(f"gallery events (simulator): {gp} passed, {gf} failed, {gn} not supported by the tool yet"
                 + (f" | FAIL {'; '.join(gfail)}" if gfail else ""))
    note(f"pass finished: {total['pass']} passed, {total['fail']} failed, {total['skipped']} done before, "
         f"{total['unsupported']} ROMs not supported yet")
    return 0 if not total["fail"] else 1


if __name__ == "__main__":
    sys.exit(main())
