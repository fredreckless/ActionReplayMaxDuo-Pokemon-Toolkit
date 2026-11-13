"""colosseum.py - rehearsal 2: a Colosseum battle (single or double) between the Virtual DUO and a game (English Ruby; Emerald and LeafGreen from the Cable Club menu).

    python3 colosseum.py --rom RUBY.gba --sav RUBY.sav --duo-flash duo_flash.bin \\
        --state at_colosseum_question.state --pk3 A.pk3 [B.pk3 ...] [--level simple]

The state is the partner standing at the Colosseum attendant (the left counter of a Pokemon Center's
2nd floor) with "Would you like to battle?" on screen. The game's side presses A throughout: FIGHT,
then its first move (and after a faint, the next Pokemon: ruby.battle_press). Passes when the tool reports the battle played to the end and exits cleanly.
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ruby import Tool, Walker, battle_press, choose_room, common_args, runner, tap_until_linked

# SingleBattleColosseum (pokeruby data/maps): player 0's spot is (3,5), the door (6,8) and (7,8);
# in RAM the coordinates carry the 7-tile border.
SPOT0, DOOR = (10, 12), (13, 15)


def main():
    ap = common_args(__doc__.splitlines()[0])
    ap.add_argument("--pk3", nargs="+", required=True, help="the DUO's team")
    ap.add_argument("--level", default="simple")
    ap.add_argument("--mode", choices=("single", "double"), default="single")
    ap.add_argument("--minutes", type=float, default=15)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with runner(a, log_link=os.path.join(a.out, "link.log")) as v:
        v.state_load("partner", a.state)
        tool = Tool(v, ["colosseum", "--level", a.level, "--pk3", *a.pk3, "--seconds", str(int(a.minutes * 60))],
                    log=os.path.join(a.out, "tool.log"), cwd=a.out)
        assert tool.wait_for("Ready", 120), "the tool never got ready"
        if choose_room(v, a.profile, "COLOSSEUM"):      # Emerald, FireRed/LeafGreen: the menu, then the
            if a.mode == "double":                       # mode, then the save prompts (tapped through below)
                v.press("partner", "DOWN", frames=6, then=20)
        else:                                            # Ruby: "Would you like to battle?"
            for wait in (90, 90, 90, 240):              # YES; save? YES; overwrite? YES; saving
                v.press("partner", "A", frames=6, then=wait)
            v.run_frames("partner", 300)                # "Which Battle Mode would you like to play?"
            if a.mode == "double":
                v.press("partner", "DOWN", frames=6, then=20)
        v.screenshot("partner", os.path.join(a.out, "mode.png"))
        print("linked after", tap_until_linked(v, tool), "taps", flush=True)
        v.run_frames("partner", 300)
        w = Walker(v, me=0)
        w.to(DOOR[0], DOOR[1] - 1); w.to(SPOT0[0], DOOR[1] - 1); w.to(*SPOT0)
        v.screenshot("partner", os.path.join(a.out, "on_spot.png"))
        end = time.monotonic() + a.minutes * 60
        presses = 0
        while not tool.saw("the battle is over"):
            if time.monotonic() > end:
                v.screenshot("partner", os.path.join(a.out, "timed_out.png"))
                raise SystemExit("the battle didn't end in time")
            battle_press(v)
            presses += 1
            if presses % 100 == 0:                       # what the game's screen shows, now and then
                v.screenshot("partner", os.path.join(a.out, "latest.png"))
        print(tool.phases()[-1], flush=True)
        for _ in range(30):                              # through the result messages, back to the room
            v.press("partner", "A", frames=6, then=60)
            if tool.saw("done"):
                break
        code = tool.finish(v)
        v.screenshot("partner", os.path.join(a.out, "after.png"))
    print("\n".join(tool.lines[-4:]))
    ok = code == 0 and tool.saw("played to the end") and tool.saw("checksum mismatches: 0")
    print("PASS" if ok else f"FAIL (tool exit {code})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
