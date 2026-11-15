"""make_videos.py - every how-to video, from the ROMs alone: savegen makes a save and the states,
each rehearsal (and unlock) runs with its screens and the tool's output recorded, and the videos are
put together: animated pixel-art setup scenes full screen (setups.py: the five games and their
cables, the DUO and its USB lead, the link setup and the power-on order), then the recording in three panels (the
game's GBA on top, the instruction band, the laptop's terminal and the DUO's GBA below).
MP4s, 1080x1080 (see compose.py for why), 30 a second. Needs ffmpeg and Pillow.

    python3 virtual/video/make_videos.py --roms ROMS --kit KIT --out OUT
        [--only trade,blender] [--work DIR] [--reuse] [--crf 20]

KIT holds what the Mystery Event and Record Mixing rehearsals bring: eon.me3 (your own event file),
willow.sb3 (used only if the Secret Base Workshop can't run here), bard.om3, trend.dt3; and for
Mystery Gift's proof in the game, gift.wc3 (your own English Emerald Wonder Card). A video whose ROM or kit file is missing is skipped, with a note.
A range of games: FireRed trades, LeafGreen battles, Sapphire's double battle and Berry Blender,
Ruby's Record Mixing and Mystery Event, Emerald's contest, Tower and Mystery Gift, each from the
English ROM found under --roms.
"""
import argparse, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
VIRTUAL = os.path.dirname(HERE)
TOOLKIT = os.path.dirname(VIRTUAL)
sys.path.insert(0, HERE)

# name: (game, rehearsal, its arguments ({S} the states, {P} the pk3s, {K} the kit), the story)
RECIPES = {   # a range of games: each video uses the English ROM of the game named first
    "trade": ("firered", "trade", "--state {S}/at_cable_club_menu.state --pk3 {P}/offer.pk3 --slot 6", "trade"),
    "battle": ("leafgreen", "colosseum", "--state {S}/at_cable_club_menu.state --pk3 {P}/team1.pk3 {P}/team2.pk3",
               "battle"),
    "double_battle": ("sapphire", "colosseum", "--state {S}/at_colosseum_question.state --mode double "
                      "--pk3 {P}/team1.pk3 {P}/team2.pk3", "double_battle"),
    "record_mixing": ("ruby", "mix", "--state {S}/at_record_question.state -- --base {W}/willow.sb3 "
                      "--old-man {K}/bard.om3 --trend {K}/trend.dt3", "record_mixing"),
    "mystery_event": ("ruby", "event", "--state {S}/at_link_standby.state --me3 {K}/eon.me3", "mystery_event"),
    "berry_blender": ("sapphire", "blender", "--state {S}/at_blender_question.state", "blender"),
    "contest": ("emerald", "contest", "--state {S}/at_contest_question.state --pk3 {P}/team1.pk3", "contest"),
    "battle_tower": ("emerald", "tower", "--state {S}/at_tower_link_question.state --pk3 {P}/team1.pk3 "
                     "{P}/team2.pk3 --retire-after 1", "battle_tower"),
    "mystery_gift": ("emerald", None, "", "mystery_gift"),           # the unlock, then the steps
}
ENGLISH = {"AXVE": "ruby", "AXPE": "sapphire", "BPEE": "emerald", "BPRE": "firered", "BPGE": "leafgreen"}


def english_roms(folder):
    """The English ROM of each game under a folder (by the code in each ROM's header)."""
    found = {}
    for root, _, files in os.walk(folder or ""):
        for f in sorted(files):
            if f.lower().endswith(".gba"):
                with open(os.path.join(root, f), "rb") as fh:
                    fh.seek(0xAC)
                    code = fh.read(4).decode("ascii", "replace")
                if code in ENGLISH:
                    found.setdefault(ENGLISH[code], os.path.join(root, f))
    return found


UNLOCK = {"mystery_event": "mystery_event", "mystery_gift": "mystery_gift"}     # video: unlock.py's name


def run(cmd, log, env=None):
    with open(log, "w") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, cwd=TOOLKIT)
    with open(log) as f:
        last = (f.read().strip().splitlines() or [""])[-1]
    return r.returncode == 0 and last.startswith("PASS"), last


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--roms", help="a folder of ROMs: the English one of each game is used")
    ap.add_argument("--ruby", help="English Ruby (1.1), if not in --roms")
    ap.add_argument("--emerald", help="Emerald, if not in --roms")
    ap.add_argument("--kit", default=os.path.expanduser("~/kit"))
    ap.add_argument("--events", help="a folder of event .pk3 files: the DUO trades and battles with three of "
                                     "them, picked at random and raised to level 50")
    ap.add_argument("--flash", default=os.path.join(TOOLKIT, "firmware", "build", "duo_flash.bin"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--work", help="where saves and recordings go (default OUT/work)")
    ap.add_argument("--only", help="comma-separated: " + ", ".join(RECIPES))
    ap.add_argument("--reuse", action="store_true", help="keep saves and recordings already made")
    ap.add_argument("--crf", type=int, default=20)
    a = ap.parse_args()
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg isn't installed (sudo apt install ffmpeg)")
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("Pillow isn't installed (pip install pillow)")
    import stories
    out = os.path.abspath(a.out)
    work = os.path.abspath(a.work or os.path.join(out, "work"))
    os.makedirs(work, exist_ok=True)
    roms = english_roms(a.roms)
    roms.update({k: v for k, v in (("ruby", a.ruby), ("emerald", a.emerald)) if v})
    names = a.only.split(",") if a.only else list(RECIPES)
    made, saves, results = {}, {}, []
    t0 = time.time()
    for name in names:
        if name not in RECIPES:
            sys.exit(f"no video called {name}: " + ", ".join(RECIPES))
        game, rehearsal, args, story = RECIPES[name]
        rom = roms.get(game)
        if not rom or not os.path.exists(rom):
            results.append((name, f"skipped: no English {game} ROM (--roms)"))
            continue
        needs = [w.replace("{K}/", "") for w in args.split() if w.startswith("{K}/")]
        if "{W}" in args:
            needs.append("willow.sb3")                  # (the fallback, if the workshop can't run)
        missing = [n for n in needs if not os.path.exists(os.path.join(a.kit, n))]
        if missing:
            results.append((name, f"skipped: {', '.join(missing)} not in {a.kit}"))
            continue
        # the save and states, once a game
        S = os.path.join(work, f"saves_{game}")
        if game not in saves:
            if not (a.reuse and os.path.isdir(S)):
                shutil.rmtree(S, ignore_errors=True)
                print(f"savegen: {game} ...", flush=True)
                ok, last = run([sys.executable, os.path.join(VIRTUAL, "savegen", "savegen.py"), "--rom", rom,
                                "--out", S, "--pk3s", os.path.join(S, "pk3")], os.path.join(work, f"savegen_{game}.log"))
                if not ok:
                    results.append((name, f"savegen failed: {last}"))
                    continue
            saves[game] = next(os.path.join(S, f) for f in os.listdir(S) if f.endswith(".sav"))
            # the DUO's Pokemon: real event Pokemon, picked at random from --events and raised to
            # level 50 (savegen's own made-up ones if there's no folder)
            if a.events:
                ok, last = run([sys.executable, os.path.join(VIRTUAL, "savegen", "events.py"), a.events,
                                os.path.join(S, "pk3")] + (["--kanto-offer"] if game in ("firered", "leafgreen") else []),
                               os.path.join(work, f"events_{game}.log"))
                print(f"  event Pokemon for {game}: " + ("; ".join(
                    l.strip() for l in open(os.path.join(work, f"events_{game}.log")) if ".pk3: " in l)
                    if ok else f"none ({last})"), flush=True)
        # the unlock, recorded (the game alone)
        urec = None
        if name in UNLOCK:
            urec = os.path.join(work, f"rec_unlock_{name}")
            if not (a.reuse and os.path.exists(os.path.join(urec, "terminal.jsonl"))):
                shutil.rmtree(urec, ignore_errors=True)
                print(f"recording: {name} (the unlock) ...", flush=True)
                env = dict(os.environ, VDUO_RECORD=urec, VDUO_RECORD_STEP="2")
                ok, last = run([sys.executable, os.path.join(HERE, "unlock.py"), UNLOCK[name], "--rom", rom,
                                "--sav", saves[game]], os.path.join(work, f"unlock_{name}.log"), env)
                if not ok:
                    results.append((name, f"unlock failed: {last} (see {work}/unlock_{name}.log)"))
                    continue
        # Mystery Gift's proof: a Wonder Card (KIT/gift.wc3, English Emerald's) claimed in the game
        crec = None
        if name == "mystery_gift" and os.path.exists(os.path.join(a.kit, "gift.wc3")):
            crec = os.path.join(work, "rec_claim")
            if not (a.reuse and os.path.exists(os.path.join(crec, "terminal.jsonl"))):
                shutil.rmtree(crec, ignore_errors=True)
                print("recording: the Wonder Card claimed in the game ...", flush=True)
                env = dict(os.environ, VDUO_RECORD=crec, VDUO_RECORD_STEP="2")
                ok, last = run([sys.executable, os.path.join(HERE, "unlock.py"), "mystery_gift_claim", "--rom", rom,
                                "--sav", saves[game], "--wc3", os.path.join(a.kit, "gift.wc3")],
                               os.path.join(work, "claim.log"), env)
                if not ok:
                    print(f"  (the claim didn't play: {last})")
                    crec = None
        # Record Mixing's base: made in the Secret Base Workshop, in a real browser, recorded step
        # by step (workshop.py); the kit's willow.sb3 if that can't run here
        W = a.kit
        shop = None
        if "{W}" in args:
            shop = os.path.join(work, "workshop")
            if not (a.reuse and os.path.exists(os.path.join(shop, "steps.json"))):
                print("recording: the Secret Base Workshop ...", flush=True)
                ok, last = run([sys.executable, os.path.join(HERE, "workshop.py"), "--rom", rom, "--out", shop],
                               os.path.join(work, "workshop.log"))
                if not ok:
                    print(f"  (the workshop didn't run: {last}; using the kit's willow.sb3)")
                    shop = None
            if shop:
                W = shop
        # the rehearsal, recorded
        rec = os.path.join(work, f"rec_{name}")
        if rehearsal and not (a.reuse and os.path.exists(os.path.join(rec, "terminal.jsonl"))):
            shutil.rmtree(rec, ignore_errors=True)
            print(f"recording: {name} ...", flush=True)
            fmt = args.format(S=S, P=os.path.join(S, "pk3"), K=a.kit, W=W).split()
            cut = fmt.index("--") if "--" in fmt else len(fmt)
            cmd = [sys.executable, os.path.join(VIRTUAL, "rehearsals", rehearsal + ".py"), "--rom", rom,
                   "--sav", saves[game], "--duo-flash", a.flash, *fmt[:cut], "--out", os.path.join(work, f"run_{name}"),
                   *fmt[cut:]]
            env = dict(os.environ, VDUO_RECORD=rec, VDUO_RECORD_STEP="2")
            ok, last = run(cmd, os.path.join(work, f"run_{name}.log"), env)
            if not ok:
                results.append((name, f"rehearsal failed: {last} (see {work}/run_{name}.log)"))
                continue
        # Record Mixing's ending: to the base's spot on its route, and in (from the save the game wrote)
        vrec = None
        if name == "record_mixing":
            vrec = os.path.join(work, "rec_visit")
            after = os.path.join(work, f"run_{name}", "after.sav")
            if not (a.reuse and os.path.exists(os.path.join(vrec, "terminal.jsonl"))) and os.path.exists(after):
                shutil.rmtree(vrec, ignore_errors=True)
                print("recording: visiting the base ...", flush=True)
                env = dict(os.environ, VDUO_RECORD=vrec, VDUO_RECORD_STEP="2")
                ok, last = run([sys.executable, os.path.join(HERE, "unlock.py"), "visit_base", "--rom", rom, "--sav", after,
                                "--sb3", os.path.join(W, "willow.sb3")], os.path.join(work, "visit.log"), env)
                if not ok:
                    print(f"  (the visit didn't play: {last})")
            if not os.path.exists(os.path.join(vrec, "terminal.jsonl")):
                vrec = None
        # the video
        print(f"composing: {name} ...", flush=True)
        mp4 = os.path.join(out, f"{name}.mp4")
        secs = stories.make(story, mp4, rec, crf=a.crf, unlock_rec=urec, workshop=shop, claim_rec=crec,
                            visit_rec=vrec)
        results.append((name, f"{mp4} ({secs / 60:.1f} min)"))
        made[name] = mp4
    print()
    for name, what in results:
        print(f"  {name:16s} {what}")
    print(f"{len(made)} of {len(names)} videos made in {(time.time() - t0) / 60:.0f} minutes")
    return 0 if len(made) == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
