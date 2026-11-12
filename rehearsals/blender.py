"""blender.py - rehearsal 5: the Berry Blender between the Virtual DUO and English Ruby.

    python3 blender.py --rom RUBY.gba --sav RUBY.sav --duo-flash duo_flash.bin \\
        --state at_blender_question.state [--duo-player 0|1] --out OUT

The state is the partner beside the link Berry Blender in a Contest Lobby (Lilycove's: the top one)
with "Is it okay to save the game before linking with your friends?" on screen. The game's side
presses A throughout: its first berry, and A at every turn of the blender, hit or miss. With
--duo-player 0 the DUO is on the master end and leads the blend. Passes when the tool reports the
blend and its Pokeblock, with no checksum mismatches.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ruby import Runner, Tool, common_args, tap_until_linked


def main():
    ap = common_args(__doc__.splitlines()[0])
    ap.add_argument("--duo-player", type=int, default=1, choices=(0, 1))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with Runner(duo_fw=a.duo_flash, partner=a.rom, partner_save=a.sav, duo_player=a.duo_player,
                wait_for_hello=True, log_link=os.path.join(a.out, "link.log")) as v:
        v.state_load("partner", a.state)
        tool = Tool(v, ["blender", "--blends", "1", "--seconds", "600"], log=os.path.join(a.out, "tool.log"), cwd=a.out)
        assert tool.wait_for("Ready", 120), "the tool never got ready"
        for wait in (90, 90, 240):                      # save? YES; overwrite? YES; saving
            v.press("partner", "A", frames=6, then=wait)
        print("linked after", tap_until_linked(v, tool), "taps", flush=True)
        n = 0
        while not (tool.saw("done") or tool.p.poll() is not None) and n < 3000:
            v.press("partner", "A", frames=4, then=8); n += 1    # A as often as the game will take it
            if n % 300 == 0:
                v.screenshot("partner", os.path.join(a.out, f"blend{n:04d}.png"))
        for _ in range(20):
            v.press("partner", "A", frames=6, then=60)
        code = tool.finish(v)
        v.screenshot("partner", os.path.join(a.out, "after.png"))
    print("\n".join(l for l in tool.lines if l.startswith("  [") or "Blend" in l or "speed" in l or "Transfers" in l
                    or "player 0" in l or "player 1" in l))
    ok = code == 0 and tool.saw("Pokeblock") and (tool.saw("checksum mismatches: 0") or not tool.saw("checksum"))
    print("PASS" if ok else f"FAIL (tool exit {code})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
