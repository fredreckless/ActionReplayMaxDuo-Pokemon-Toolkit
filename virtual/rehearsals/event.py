"""event.py - rehearsal 4: a Mystery Event (.me3) from the Virtual DUO to English Ruby over the link cable.

    python3 event.py --rom RUBY.gba --sav RUBY.sav --duo-flash duo_flash.bin \\
        --state at_link_standby.state --me3 EVENT.me3 --out OUT

The state is the partner on the title menu's MYSTERY EVENTS screen, showing "Link standby...". The
game receives the event, runs it and saves by itself; afterwards its save (from memory: the original
file is never touched) is kept as OUT/after.sav and compared with the save given. Passes when the
tool reports the game has the event and saved, with no checksum mismatches, and the save changed.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ruby import Tool, common_args, runner


def main():
    ap = common_args(__doc__.splitlines()[0])
    ap.add_argument("--me3", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with runner(a, log_link=os.path.join(a.out, "link.log")) as v:
        v.state_load("partner", a.state)
        tool = Tool(v, ["event", "--event", a.me3, "--seconds", "300"], log=os.path.join(a.out, "tool.log"), cwd=a.out)
        assert tool.wait_for("Ready", 120), "the tool never got ready"
        for i in range(400):                            # the game does the rest; A clears its messages
            if tool.p.poll() is not None or tool.saw("safe to switch"):
                break
            v.run_frames("partner", 60)
            if i % 5 == 4:
                v.press("partner", "A", frames=6, then=20)
                v.screenshot("partner", os.path.join(a.out, "progress.png"))
        code = tool.finish(v)
        v.run_frames("partner", 300)
        v.screenshot("partner", os.path.join(a.out, "after.png"))
        after = os.path.join(a.out, "after.sav")
        v.save_sav("partner", after)
    print("\n".join(l for l in tool.lines if l.startswith("  [") or "Finished" in l or "Transfers" in l or "saved" in l))
    changed = open(after, "rb").read() != open(a.sav, "rb").read()
    print("the save changed:", changed)
    if open(a.me3, "rb").read() in open(after, "rb").read():
        print("the .me3 is in the save byte for byte (a saved event is the game's own stored form)")
    ok = code == 0 and changed and tool.saw("checksum mismatches: 0")
    print("PASS" if ok else f"FAIL (tool exit {code})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
