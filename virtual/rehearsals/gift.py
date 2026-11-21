"""gift.py - a Wonder Card (.wc3) from the Virtual DUO to FireRed/LeafGreen or Emerald by Mystery Gift,
the DUO playing the Wireless Adapter and the distributor (21 November 2026: the first try of Mystery Gift
in the emulator).

    python3 gift.py --rom LEAFGREEN.gba --sav LG.sav --duo-flash duo_flash.bin \\
        --state at_title_mystery_gift.state --wc3 CARD.wc3 --out OUT

The state is the title menu with MYSTERY GIFT on it. The game is driven through its own menus; the
tool does the rest. Passes when the tool says the game has the card.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ruby import Tool, common_args, runner


def main():
    ap = common_args(__doc__.splitlines()[0])
    ap.add_argument("--wc3", required=True)
    ap.add_argument("--keys", default="", help="extra presses to try, for finding the way (debug)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with runner(a, log_link=os.path.join(a.out, "link.log")) as v:
        v.state_load("partner", a.state)
        tool = Tool(v, ["gift", "--card", a.wc3, "--seconds", "300"], log=os.path.join(a.out, "tool.log"), cwd=a.out)
        assert tool.wait_for("Ready", 120), "the tool never got ready"
        v.run_frames("partner", 60)
        v.screenshot("partner", os.path.join(a.out, "s0.png"))
        n = 0
        for i in range(300):
            if tool.p.poll() is not None:
                break
            v.run_frames("partner", 40)
            if i % 3 == 2:
                v.press("partner", "A", frames=6, then=20)
            if i % 6 == 5:
                n += 1
                v.screenshot("partner", os.path.join(a.out, f"p{n:03d}.png"))
        code = tool.finish(v)
        # the game saves the card by itself, then shows it; B leaves it, and the menu, to the title
        from PIL import Image
        def shown():                                    # what's on the game's screen: a corner pixel
            path = os.path.join(a.out, "now.png")
            v.screenshot("partner", path)
            return Image.open(path).convert("RGB").getpixel((120, 30))
        blue = shown()                                  # the Mystery Gift screen's checks
        v.run_frames("partner", 300)                    # "Data will be saved", then "Save completed"
        for _ in range(8):                              # A: the menu (WONDER CARDS...), A: the card itself
            v.press("partner", "A", frames=6, then=120)
            if shown() != blue:
                break
        else:
            raise RuntimeError("the Wonder Card never came up")
        v.run_frames("partner", 30)
        v.screenshot("partner", os.path.join(a.out, "card.png"))
        v.run_frames("partner", 360)                    # (held on screen for the video)
        v.press("partner", "B", frames=6, then=90)      # back to the menu
        v.screenshot("partner", os.path.join(a.out, "menu_after.png"))
        v.screenshot("partner", os.path.join(a.out, "after.png"))
        v.save_sav("partner", os.path.join(a.out, "after.sav"))
    print("\n".join(tool.lines[-40:]))
    ok = code == 0
    print("PASS" if ok else f"FAIL (tool exit {code})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
