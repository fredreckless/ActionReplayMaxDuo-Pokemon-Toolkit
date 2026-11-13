"""contest.py - rehearsal 6: Emerald's link Contest (E MODE) between the Virtual DUO and English Emerald.

    python3 contest.py --rom EMERALD.gba --sav EMERALD.sav --duo-flash duo_flash.bin \\
        --state at_contest_question.state --pk3 MON.pk3 [--duo-player 0|1] --out OUT

The state is the partner at the link contest counter of Lilycove's Contest Lobby with "Would you
like to enter a CONTEST?" (ENTER/INFO/EXIT) on screen (savegen makes it). The game's side presses
A throughout: ENTER, YES to saving, E MODE, the first category (COOL), its first Pokemon, and its
first move each round. With --duo-player 0 the DUO is on the master end (player 0). Passes when
the tool reports the contest's results, with no checksum mismatches.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ruby import Runner, Tool, common_args, set_game, tap_until_linked


def main():
    ap = common_args(__doc__.splitlines()[0])
    ap.add_argument("--pk3", required=True, help="the DUO's contestant")
    ap.add_argument("--category", default="cool", help="the category (the game's side takes the first, COOL)")
    ap.add_argument("--duo-player", type=int, default=1, choices=(0, 1))
    ap.add_argument("--minutes", type=float, default=20)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    set_game(a.rom)
    with Runner(duo_fw=a.duo_flash, partner=a.rom, partner_save=a.sav, duo_player=a.duo_player,
                wait_for_hello=True, log_link=os.path.join(a.out, "link.log")) as v:
        v.state_load("partner", a.state)
        tool = Tool(v, ["contest", "--pk3", a.pk3, "--category", a.category, "--seconds", str(int(a.minutes * 60))],
                    log=os.path.join(a.out, "tool.log"), cwd=a.out)
        assert tool.wait_for("Ready", 120), "the tool never got ready"
        print("linked after", tap_until_linked(v, tool, taps=80), "taps", flush=True)
        n = 0
        while not (tool.saw("The results") or tool.saw("didn't") or tool.p.poll() is not None) and n < 6000:
            v.press("partner", "A", frames=6, then=24); n += 1   # every message, menu and move: the first
            if n % 300 == 0:
                v.screenshot("partner", os.path.join(a.out, f"contest{n:04d}.png"))
        for _ in range(60):                              # the results, (a painting,) back to the lobby
            if tool.p.poll() is not None:
                break
            v.press("partner", "A", frames=6, then=60)
        code = tool.finish(v)
        v.screenshot("partner", os.path.join(a.out, "after.png"))
    print("\n".join(l for l in tool.lines if l.startswith("  [") or "result" in l.lower() or "Transfers" in l
                    or "place" in l.lower() or "player 0" in l))
    ok = code == 0 and tool.saw("The results") and (tool.saw("checksum mismatches: 0") or not tool.saw("checksum"))
    print("PASS" if ok else f"FAIL (tool exit {code})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
