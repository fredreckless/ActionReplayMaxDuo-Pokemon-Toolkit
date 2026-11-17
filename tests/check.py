"""Tiered testing: run what a change needs, not always everything.

    python tests/check.py quick              a fast spread of tests across every area (a few minutes)
    python tests/check.py changed [BASE]     the tests and planted bugs for the files changed since BASE
    python tests/check.py full [BASE]        every test, plus the planted bugs for what changed
    python tests/check.py full --all-bugs    every test and every planted bug that can run here
    python tests/check.py what [BASE]        just say what `changed` would run

BASE is a git revision (default origin/main); uncommitted and new files count as changed too.

When to use which (see docs/HANDOVER.md; revised 5 November to keep testing short):
- quick: after each small change while working;
- changed: before every push (the only test step a push waits for);
- full --all-bugs: before a GitHub release, at the end of a long session, or when hwsim.py,
  mutate4.py or the firmware builds change; in the background, without waiting on it;
- nothing: a change to documentation only (*.md, lab/, docs/)."""
import fnmatch, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import run_each

ALL = "ALL"

# Test groups, as prefixes of test names in test_v4.py.
MYSTERY_GIFT = ["wireless adapter", "distributor", "serial sweep", "find serial", "every game", "Wonder News",
                "search check", "finishing", "guided start-up", "2 MHz probe", "card checks",
                "v4.2 adapter test", "adapter program", "v4.2 programs", "Union Room"]
EREADER = ["e-Reader", "e-Card", "Mystery Event files", "Enigma Berry", "v4.2 programs", "guided start-up"]
TRADE = ["trade", "party form", "Pokemon files", "v4.2 programs"]
MIX = ["Record Mixing", "Secret Base", "v4.2 programs"]
COLOSSEUM = ["battle probe", "battle partner", "v4.2 programs"]
TOWER = ["Battle Tower", "v4.2 programs"]
BLENDER = ["Berry Blender", "v4.2 programs"]
CONTEST = ["Contest", "v4.2 programs"]
LAB4P = ["lab4p", "v4.2 programs"]
CABLE = TRADE + MIX + COLOSSEUM + TOWER + BLENDER + CONTEST + LAB4P     # every routine on pret_link's Console
EVENTS_TOOL = MYSTERY_GIFT + EREADER + TRADE + MIX + COLOSSEUM + TOWER + BLENDER + CONTEST + LAB4P + ["two tools", "v4.2 run", "connect"]

# Which tests a changed file needs, first match wins. ALL for anything shared; [] for documentation.
AREAS = [
    ("*.md", []), ("lab/*", []), ("docs/*", []), ("LICENSE*", []), (".gitignore", []),
    ("firmware/programs/ereader.c", EREADER),
    ("firmware/programs/adapter.c", MYSTERY_GIFT),
    ("firmware/programs/trade.c", TRADE),
    ("firmware/programs/mix.c", MIX),
    ("firmware/programs/colosseum.c", COLOSSEUM),
    ("firmware/programs/tower.c", TOWER),
    ("firmware/programs/blender.c", BLENDER),
    ("firmware/programs/contest.c", CONTEST),
    ("firmware/programs/lab4p.c", LAB4P),
    ("firmware/programs/room_walk.h", TRADE + MIX + COLOSSEUM),
    ("firmware/programs/*", MYSTERY_GIFT + EREADER + TRADE + MIX + COLOSSEUM + TOWER + BLENDER + CONTEST + LAB4P),
    ("firmware/embed_programs.py", MYSTERY_GIFT + EREADER + TRADE + MIX + COLOSSEUM + TOWER + BLENDER + CONTEST + LAB4P),
    ("firmware/thumbcheck.py", MYSTERY_GIFT + EREADER + ["build:"]),
    ("duo_events.py", EVENTS_TOOL),
    ("secret_bases.py", MIX),
    ("secret_base_workshop.html", ["Secret Base Workshop"]),
    ("duo_wireless.py", ["two tools"]),
    ("lab_runner.py", ["lab_runner"]),
    ("records.py", ["Record files"]),
    ("duo_battle.py", ["battle:", "battle partner", "Battle Tower"]), ("battle_data.py", ["battle:", "battle partner", "Battle Tower"]), ("contest_data.py", CONTEST), ("tools/make_battle_data.py", ["battle:"]),
    ("tests/rfu_game_model.py", MYSTERY_GIFT), ("tests/union_room_model.py", MYSTERY_GIFT),
    ("tests/link_game_model.py", EREADER),
    ("tests/mevent_model.py", EREADER),
    ("tests/trade_game_model.py", TRADE + MIX + COLOSSEUM + TOWER + BLENDER + CONTEST),
    ("tests/battle_game_model.py", COLOSSEUM + TOWER),
    ("tests/tower_game_model.py", TOWER),
    ("tests/blender_game_model.py", BLENDER),
    ("tests/contest_game_model.py", CONTEST),
    ("tests/gp_link_model.py", LAB4P),
    ("tests/pret_link.py", CABLE + EREADER), ("tests/pret_cable_club.py", CABLE),    # (17 November)
    ("tests/source_anchors.py", []), ("tools/pret.py", []),                         # (the anchors run on every tier)
    ("tests/mix_game_model.py", MIX),
    ("tests/ecard_fixtures.py", EREADER),
    ("tests/check.py", []), ("tests/run_each.py", []), ("tests/history/*", []),
    ("tests/mutate4.py", "BY_BUG"),   # the planted bugs whose lines changed (or one of each kind, for its machinery)
    ("tests/test_v4.py", "BY_TEST"),  # the tests whose own lines changed (all, if a shared helper did)
    ("*", ALL),                      # maxduo_saves.py, the firmware builds, hwsim, test_v4.py, fixtures...
]

# Which planted-bug kinds (tests/mutate4.py) a changed file needs.
BUG_KINDS = [
    ("firmware/programs/ereader.c", ["ereader"]),
    ("firmware/programs/adapter.c", ["prog"]),
    ("firmware/programs/trade.c", ["trade"]),
    ("firmware/programs/mix.c", ["mix"]),
    ("firmware/programs/colosseum.c", ["colosseum"]),
    ("firmware/programs/tower.c", ["tower"]),
    ("firmware/programs/blender.c", ["blender"]),
    ("firmware/programs/contest.c", ["contest"]),
    ("firmware/programs/lab4p.c", ["lab4p"]),
    ("firmware/programs/room_walk.h", ["trade", "mix", "colosseum"]),
    ("firmware/programs/*", ["prog", "ereader", "trade", "mix", "colosseum", "tower", "blender", "contest", "lab4p"]),
    ("firmware/build_v42.py", ["fw42"]),
    ("firmware/build_v4.py", ["fw", "fw42"]),
    ("firmware/build_*.py", ["fw", "fw42"]),
    ("duo_events.py", ["pc"]), ("maxduo_saves.py", ["pc"]), ("secret_bases.py", ["pc"]), ("records.py", []), ("secret_base_workshop.html", []),
    ("tests/rfu_game_model.py", ["prog"]), ("tests/union_room_model.py", ["prog"]),
    ("tests/link_game_model.py", ["ereader"]), ("tests/mevent_model.py", ["ereader", "pc"]),
    ("tests/ecard_fixtures.py", ["pc"]),
    ("tests/trade_game_model.py", ["trade", "mix", "colosseum", "blender", "contest"]),
    ("tests/mix_game_model.py", ["mix"]),
    ("tests/battle_game_model.py", ["colosseum", "tower"]),
    ("tests/tower_game_model.py", ["tower"]),
    ("tests/blender_game_model.py", ["blender"]),
    ("tests/contest_game_model.py", ["contest"]),
    ("tests/gp_link_model.py", ["lab4p"]),
    ("tests/pret_link.py", ["ereader", "trade", "mix", "colosseum", "tower", "blender", "contest", "lab4p"]),
    ("tests/pret_cable_club.py", ["trade", "mix", "colosseum", "tower", "blender", "contest", "lab4p"]),
    ("tests/hwsim.py", ALL), ("tests/fixtures.py", ALL),
    ("tests/mutate4.py", []),        # (see AREAS: the planted bugs whose lines changed)
]

# The quick tier: a fast spread across every area, by full test name prefix.
QUICK = [
    "build: every patch routine",                       # Thumb-1 only
    "info: v4 identifies itself",
    "stream: 9 data patterns round-trip exactly",
    "upload: a corrupted upload is detected",
    "types: SRAM",
    "verify: one bad byte",
    "refusals: DeleteFile",
    "cartridge report: the logo constants",
    "backups: per-game folder",
    "two tools:",
    "v4.2 programs:",
    "v4.2 run: a staged program with a bad magic",
    "card checks:",
    "Wonder News files:",
    "Mystery Event files:",
    "wireless adapter: Emerald's Mystery Gift search",
    "distributor: link players exchanged",
    "e-Reader: Ruby as master",
    "e-Card scans:",
    "trade, the game as master",
    "Record Mixing, the game as master",
    "Secret Base files",
    "battle: damage",
    "battle probe, the game as master",
    "Record files",
]


def changed_files(base):
    def git(*a):
        r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
        return r.stdout.splitlines() if r.returncode == 0 else []
    files = set(git("diff", "--name-only", base)) | set(git("diff", "--name-only", "--cached", base))
    files |= set(git("ls-files", "--others", "--exclude-standard"))
    return sorted(f for f in files if f)


def lookup(table, path):
    for pattern, value in table:
        if fnmatch.fnmatch(path, pattern):
            return value
    return None


def pick(prefixes, names):
    if prefixes == ALL:
        return list(names)
    return [n for n in names if any(n.startswith(p) for p in prefixes)]


def changed_tests(base):
    """The tests in test_v4.py whose own lines changed since BASE (17 November: an edit to one test
    used to run every test and every planted bug). ALL if a line outside every test changed."""
    r = subprocess.run(["git", "diff", "-U0", base, "--", "tests/test_v4.py"], cwd=ROOT, capture_output=True, text=True)
    lines = []
    for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", r.stdout, re.M):
        start, count = int(m.group(1)), int(m.group(2) or 1)
        lines += list(range(start, start + max(count, 1)))
    if not lines:
        return []
    starts = []                                   # (first line, name) of each test, decorator included
    for i, line in enumerate(open(os.path.join(HERE, "test_v4.py"), encoding="utf-8"), 1):
        m = re.match(r'@test\("(.*)"\)', line)
        if m:
            starts.append((i, m.group(1)))
    names = set()
    for n in lines:
        before = [name for first, name in starts if first <= n]
        if not before:
            return ALL                            # (the imports and helpers above the first test)
        names.add(before[-1])
    return sorted(names)


def changed_bugs(base):
    """Planted bugs whose own lines changed in mutate4.py; if anything else there changed (its
    machinery), one of each kind as well, to show it still plants and catches. No tests: mutate4.py
    changes none of them."""
    import mutate4
    r = subprocess.run(["git", "diff", "-U0", base, "--", "tests/mutate4.py"], cwd=ROOT, capture_output=True, text=True)
    added = [l[1:] for l in r.stdout.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    pairs, other = set(), False
    for line in added:
        hit = [(k, n) for k, table in mutate4.KINDS.items() for n in table if f'"{n}"' in line]
        pairs |= set(hit)
        other = other or (not hit and line.strip() != "")
    if other:
        pairs |= {(k, next(iter(table))) for k, table in mutate4.KINDS.items() if table}
    return sorted(pairs)


def bugs_for(names):
    """The planted bugs whose test is one of these: (kind, name) pairs."""
    import mutate4
    return [(k, n) for k, table in mutate4.KINDS.items() for n, entry in table.items()
            if any(entry[2] in t for t in names)]


def plan(base):
    names = run_each.all_names()
    files = changed_files(base)
    tests, kinds, pairs, why = set(), set(), set(), []
    for f in files:
        area = lookup(AREAS, f)
        k = lookup(BUG_KINDS, f) or []
        if area == "BY_BUG":
            mine = changed_bugs(base)
            pairs |= set(mine)
            why.append(f"  {f}: no tests; {len(mine)} planted bugs")
            continue
        if area == "BY_TEST":
            got = changed_tests(base)
            if got == ALL:
                area, k = ALL, ALL
            else:
                tests |= set(got)
                mine = bugs_for(got)
                pairs |= set(mine)
                why.append(f"  {f}: {len(got)} changed tests; {len(mine)} planted bugs on them")
                continue
        got = pick(area, names)
        tests |= set(got)
        kinds |= set(["fw", "fw42", "prog", "ereader", "trade", "pc"] if k == ALL else k)
        why.append(f"  {f}: " + ("all tests" if area == ALL else f"{len(got)} tests" if got else "no tests")
                   + (f"; planted bugs: {'all' if k == ALL else ', '.join(k)}" if k else ""))
    pairs = sorted(p for p in pairs if p[0] not in kinds)
    return files, [n for n in names if n in tests], sorted(kinds), pairs, why


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    tier = args[0] if args else "quick"
    base = args[1] if len(args) > 1 else "origin/main"
    jobs = next((int(a.split("=", 1)[1]) for a in flags if a.startswith("--jobs=")), None)
    names = run_each.all_names()
    t0 = time.time()
    # every tier: the simulator's citations of the games' source still hold (17 November)
    import source_anchors
    anchors_ok = tier == "what" or source_anchors.check()
    if tier == "quick":
        tests = pick(QUICK, names)
        missing = [q for q in QUICK if not pick([q], names)]
        assert not missing, f"QUICK names no longer match a test: {missing}"
        print(f"Quick tier: {len(tests)} of {len(names)} tests", flush=True)
        counts = run_each.run_tests(tests, jobs, quiet_pass=True)
        ok = not counts["FAIL"]
    elif tier in ("changed", "full", "what"):
        files, tests, kinds, pairs, why = plan(base)
        print(f"Changed since {base}: {len(files)} file(s)")
        print("\n".join(why) if why else "  (nothing)")
        if tier == "full":
            tests = names
        if "--all-bugs" in flags:
            kinds = None
        if kinds is None:
            pairs = []
        print(f"{'Full' if tier == 'full' else 'Changed'} tier: {len(tests)} tests; planted bugs: "
              + ("all" if kinds is None else ", ".join(kinds) or "none")
              + (f", and {len(pairs)} picked for the changed files" if pairs else ""), flush=True)
        if tier == "what":
            return 0
        ok = True
        if tests:
            counts = run_each.run_tests(tests, jobs, quiet_pass=True)
            ok = not counts["FAIL"]
        if kinds is None or kinds or pairs:
            import mutate4
            ok = mutate4.run_many(kinds, jobs, extra=pairs) and ok
    else:
        sys.exit(__doc__)
    ok = ok and anchors_ok
    print(f"{'ALL GOOD' if ok else 'FAILURES - see above'} ({time.time() - t0:.0f} s in all)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
