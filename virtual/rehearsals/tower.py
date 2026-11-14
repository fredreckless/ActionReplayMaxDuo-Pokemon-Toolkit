"""tower.py - rehearsal 7: the Battle Tower's link multi battle (Emerald), the Virtual DUO as partner.

    python3 tower.py --rom EMERALD.gba --sav EMERALD.sav --duo-flash duo_flash.bin \\
        --state at_tower_link_question.state --pk3 A.pk3 B.pk3 [--retire-after 1] --out OUT

The state is the partner at the Battle Tower lobby's link multi battle counter with "Would you like
to take the LINK MULTI BATTLE ROOM challenge?" (CHALLENGE/INFO/EXIT) on screen (savegen makes it).
The game's side: CHALLENGE, LV. 50, its first two Pokemon (the cursor goes to CONFIRM by itself
after the second), YES to saving; then A throughout the battles (ruby.battle_press: past a
fainted Pokemon too). The DUO retires after --retire-after battles, which ends the challenge.
With --duo-player 0 the DUO is on the master end (player 0: the leader, giving the verdicts).
Passes when the tool ends cleanly ("done", everything kept) having seen at least one battle through.
(Each battle links twice: first for the party menu's summaries, then for the battle itself; the
tower program learnt the first here, 13 November.)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ruby import Runner, Tool, battle_press, common_args, set_game, tap_until_linked


def main():
    ap = common_args(__doc__.splitlines()[0])
    ap.add_argument("--pk3", nargs=2, required=True, help="the DUO's two Pokemon")
    ap.add_argument("--level", default="medium")
    ap.add_argument("--retire-after", type=int, default=1)
    ap.add_argument("--minutes", type=float, default=25)
    ap.add_argument("--duo-player", type=int, default=1, choices=(0, 1))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    set_game(a.rom)
    with Runner(duo_fw=a.duo_flash, partner=a.rom, partner_save=a.sav, duo_player=a.duo_player,
                wait_for_hello=True, log_link=os.path.join(a.out, "link.log")) as v:
        v.state_load("partner", a.state)
        tool = Tool(v, ["tower", "--pk3", *a.pk3, "--level", a.level, "--retire-after", str(a.retire_after),
                        "--seconds", str(int(a.minutes * 60))], log=os.path.join(a.out, "tool.log"), cwd=a.out)
        assert tool.wait_for("Ready", 120), "the tool never got ready"
        for k, wait in (("A", 100), ("A", 100), ("A", 160),        # CHALLENGE; LV. 50; "select two"
                        ("A", 70),                                  # (the party screen opens)
                        ("A", 70), ("A", 70),                       # the first Pokemon: ENTER
                        ("DOWN", 40), ("A", 70), ("A", 100)):       # the second: ENTER (then CONFIRM)
            v.press("partner", k, frames=6, then=wait)
        v.screenshot("partner", os.path.join(a.out, "chosen.png"))
        v.press("partner", "A", frames=6, then=90)                  # CONFIRM
        print("linked after", tap_until_linked(v, tool, taps=60), "taps", flush=True)
        end = time.monotonic() + a.minutes * 60
        presses = 0
        while tool.p.poll() is None:
            if time.monotonic() > end:
                v.screenshot("partner", os.path.join(a.out, "timed_out.png"))
                raise SystemExit("the challenge didn't end in time")
            battle_press(v)
            presses += 1
            if presses % 100 == 0:
                v.screenshot("partner", os.path.join(a.out, "latest.png"))
        for _ in range(20):
            v.press("partner", "A", frames=6, then=60)
        code = tool.finish(v)
        v.screenshot("partner", os.path.join(a.out, "after.png"))
    print("\n".join(l for l in tool.lines if l.startswith("  [") or "battle" in l.lower() and "Kept" not in l
                    or "Transfers" in l)[-3000:])
    import re
    played = [l for l in tool.lines if re.search(r"The challenge: [1-9]\d* battles?,", l)]
    ok = code == 0 and bool(played) and tool.saw("done") and not tool.saw("checksum mismatches: 1") \
        and tool.saw("safe to switch the DUO's GBA off")
    print("PASS" if ok else f"FAIL (tool exit {code})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
