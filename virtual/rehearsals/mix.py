"""mix.py - rehearsal 3: Record Mixing in the Record Corner between the Virtual DUO and English Ruby.

    python3 mix.py --rom RUBY.gba --sav RUBY.sav --duo-flash duo_flash.bin \\
        --state at_record_question.state --out OUT -- --base A.sb3 [--old-man X.om3 --trend Y.dt3 ...]

Everything after "--" goes to `duo_events.py mix` as it is. The state is the partner at the Record
Corner attendant (the right counter) with "Would you like to mix records?" on screen. Afterwards the
game's save, as the game itself wrote it, is kept as OUT/after.sav (in memory until then: the
original save file is never touched), and the toolkit's `bases` reads it back. Passes when the tool
finishes with the game saved and no checksum mismatches.
"""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ruby import TOOLKIT, Tool, Walker, common_args, objects, runner, tap_until_linked

# RecordCorner (pokeruby data/maps): seats at (6,4) and (6,6) on player 0's side, the doors (8..11,9).
SEAT0 = (13, 13)            # (6,6): from the door, up two rows, left, then up


def main():
    argv = sys.argv[1:]
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[:argv.index("--")] if "--" in argv else argv
    a = common_args(__doc__.splitlines()[0]).parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    with runner(a, log_link=os.path.join(a.out, "link.log")) as v:
        v.state_load("partner", a.state)
        tool = Tool(v, ["mix", *extra], log=os.path.join(a.out, "tool.log"), cwd=a.out)
        assert tool.wait_for("Ready", 120), "the tool never got ready"
        for wait in (90, 90, 90, 240):                  # YES; save? YES; overwrite? YES; saving
            v.press("partner", "A", frames=6, then=wait)
        print("linked after", tap_until_linked(v, tool), "taps", flush=True)
        v.run_frames("partner", 300)
        v.screenshot("partner", os.path.join(a.out, "room.png"))
        w = Walker(v, me=0)
        try:
            x, _ = w.pos()
            w.to(x, SEAT0[1] + 1); w.to(SEAT0[0], SEAT0[1] + 1); w.to(*SEAT0)
        except RuntimeError:
            print("objects:", objects(v)); v.screenshot("partner", os.path.join(a.out, "stuck.png")); raise
        v.screenshot("partner", os.path.join(a.out, "seated.png"))
        for _ in range(200):                            # the game mixes and saves by itself
            if tool.saw("leaving the room") or tool.saw("done") or tool.p.poll() is not None:
                break
            v.press("partner", "A", frames=6, then=54)  # (only clears the odd message)
        for _ in range(10):
            v.press("partner", "A", frames=6, then=60)
        code = tool.finish(v)
        v.screenshot("partner", os.path.join(a.out, "after.png"))
        after = os.path.join(a.out, "after.sav")
        v.save_sav("partner", after)
    print("\n".join(l for l in tool.lines if l.startswith("  [") or "Kept" in l or "Finished" in l or "Transfers" in l))
    bases = subprocess.run([sys.executable, os.path.join(TOOLKIT, "duo_events.py"), "bases", after, "--game", "Ruby"],
                           cwd=a.out, capture_output=True, text=True)
    print("the save afterwards, by `bases`:\n" + bases.stdout[-1500:] + bases.stderr[-500:])
    saved = open(after, "rb").read()
    landed = True
    for flag in ("--old-man", "--trend", "--news"):    # these travel byte for byte into the save
        if flag in extra:
            i = extra.index(flag) + 1
            while i < len(extra) and not extra[i].startswith("--"):
                there = open(extra[i], "rb").read() in saved
                landed &= there
                print(f"{os.path.basename(extra[i])}: {'in the save' if there else 'NOT in the save'}")
                i += 1
    ok = code == 0 and landed and tool.saw("Finished") and tool.saw("checksum mismatches: 0")
    print("PASS" if ok else f"FAIL (tool exit {code})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
