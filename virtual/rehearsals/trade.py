"""trade.py - rehearsal 1: a Cable Club trade between the Virtual DUO and English Ruby.

    python3 trade.py --rom RUBY.gba --sav RUBY.sav --duo-flash duo_flash.bin \\
        --state at_trade_question.state --pk3 OFFER.pk3 --slot 2

The state is the partner standing at the Trade Center attendant (the middle counter) with "Would you
like to trade POKeMON?" on screen. The game offers the Pokemon in party slot --slot (1-6) for the
DUO's .pk3, then cancels and the DUO leaves. Passes when the tool exits cleanly having received one
Pokemon; the record the tool writes to its received/ folder is printed for comparison by hand.
"""
import glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ruby import TOOLKIT, Tool, Walker, choose_room, common_args, runner, tap_until_linked

# TradeCenter (pokeruby data/maps): player 0's seat is (4,5), the door (5,8); +7 in RAM.
SEAT0, DOOR = (11, 12), (12, 15)


def main():
    ap = common_args(__doc__.splitlines()[0])
    ap.add_argument("--pk3", required=True, help="what the DUO offers")
    ap.add_argument("--slot", type=int, default=1, help="the game's party slot to trade (1-6)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    received = os.path.join(TOOLKIT, "received")                # the tool keeps it in its own folder
    before = set(glob.glob(os.path.join(received, "*.pk3")))
    with runner(a, log_link=os.path.join(a.out, "link.log")) as v:
        v.state_load("partner", a.state)
        tool = Tool(v, ["trade", "--pk3", a.pk3, "--seconds", "600"], log=os.path.join(a.out, "tool.log"), cwd=a.out)
        assert tool.wait_for("Ready", 120), "the tool never got ready"
        if not choose_room(v, a.profile, "TRADE CENTER"):   # (Emerald, LeafGreen: from the Cable Club's menu)
            for wait in (90, 90, 90, 240):              # Ruby: YES; save? YES; overwrite? YES; saving
                v.press("partner", "A", frames=6, then=wait)
        print("linked after", tap_until_linked(v, tool), "taps", flush=True)
        v.run_frames("partner", 300)
        w = Walker(v, me=0)
        w.to(DOOR[0], DOOR[1] - 2); w.to(SEAT0[0], DOOR[1] - 2); w.to(*SEAT0)
        assert tool.wait_for("waiting for your choice", 60), "the trade screen didn't open"
        v.run_frames("partner", 120)
        v.screenshot("partner", os.path.join(a.out, "trade_screen.png"))
        # the party is two columns of three: slot 1 2 / 3 4 / 5 6
        keys = ["DOWN"] * ((a.slot - 1) // 2) + ["RIGHT"] * ((a.slot - 1) % 2) + ["A", "DOWN", "A"]   # then TRADE
        for k in keys:
            v.press("partner", k, frames=6, then=60)
        v.run_frames("partner", 240)
        v.press("partner", "A", frames=6, then=120)             # "Is this trade okay?" YES
        v.run_frames("partner", 3000)                           # the animation and the save
        v.screenshot("partner", os.path.join(a.out, "after_trade.png"))
        # CANCEL sits under the partner's side of the screen: RIGHT, RIGHT, DOWN (gTradeNextSelectedMonTable)
        for k, wait in (("RIGHT", 30), ("RIGHT", 30), ("DOWN", 30), ("A", 120), ("A", 300)):
            v.press("partner", k, frames=6, then=wait)
        v.run_frames("partner", 400)
        # once the DUO has left, the game ends the session itself and puts the player back in front
        # of the attendant ("I hope to see you again"): no need to walk out
        for _ in range(10):
            v.press("partner", "A", frames=6, then=60)
        v.screenshot("partner", os.path.join(a.out, "back_outside.png"))
        code = tool.finish(v)
    new = sorted(set(glob.glob(os.path.join(received, "*.pk3"))) - before)
    print("\n".join(tool.lines[-4:]))
    print("received:", [os.path.basename(n) for n in new])
    ok = code == 0 and len(new) == 1 and tool.saw("checksum mismatches: 0")
    print("PASS" if ok else f"FAIL (tool exit {code})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
