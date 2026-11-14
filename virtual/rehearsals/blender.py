"""blender.py - rehearsal 5: the Berry Blender between the Virtual DUO and English Ruby.

    python3 blender.py --rom RUBY.gba --sav RUBY.sav --duo-flash duo_flash.bin \\
        --state at_blender_question.state [--duo-player 0|1] --out OUT

The state is the partner beside the link Berry Blender in a Contest Lobby (Lilycove's: the top one)
with "Is it okay to save the game before linking with your friends?" on screen. The game's side
plays as a person would: A through the menus and its first berry, then during the blend A as its
own arrow passes the top, timed from the blender's state in RAM (the profile's BLENDER), so nearly
every press is a "best". With
--duo-player 0 the DUO is on the master end and leads the blend. Passes when the tool reports the
blend and its Pokeblock, with no checksum mismatches.
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ruby import Runner, Tool, common_args, set_game, tap_until_linked


class Player:
    """The game's side, as a person would play: A through the menus, and during the blend A as its
    own arrow passes the top (GetArrowProximity's best range), read from the blender's own state."""
    RANGE = (32, 224, 96, 160)                      # sArrowHitRangeStart, by arrow
    LEAD = int(os.environ.get("BLEND_LEAD", "1"))

    def __init__(self, v, profile, me):
        self.v, self.me, self.hits = v, me, 0
        self.blender = getattr(profile, "BLENDER", None)
        self.last, self.still, self.cool, self.menu = None, 0, 0, 0

    def step(self):
        v = self.v
        if self.blender:
            ptr = struct.unpack("<I", v.read("partner", self.blender[0], 4))[0]
            if 0x02000000 <= ptr < 0x02040000:
                pos, speed = struct.unpack("<Hh", v.read("partner", ptr + self.blender[1], 4))
                arrow = struct.unpack("<H", v.read("partner", ptr + self.blender[2] + 2 * self.me, 2))[0] & 3
                step = (pos - self.last) & 0xFFFF if self.last is not None else 0
                self.still = self.still + 1 if pos == self.last else 0
                self.last = pos
                if speed > 0 and self.still < 30:          # the blend: wait for our arrow
                    # the game sees A a frame or two after we press it, by when the arrow has moved on
                    at, start = (pos + self.LEAD * step) % 0x10000 // 256 + 24, self.RANGE[arrow]
                    if self.cool:
                        self.cool -= 1
                    elif start + 20 <= at < start + 28:
                        v.press("partner", "A", frames=1, then=0)
                        self.hits += 1
                        self.cool = 20
                        return
                    v.run_frames("partner", 1)
                    return
        self.menu += 1                                     # menus and messages: A now and then
        if self.menu % 12 == 0:
            v.press("partner", "A", frames=4, then=0)
        else:
            v.run_frames("partner", 1)


def main():
    ap = common_args(__doc__.splitlines()[0])
    ap.add_argument("--duo-player", type=int, default=1, choices=(0, 1))
    a = ap.parse_args()
    a.profile = set_game(a.rom)
    os.makedirs(a.out, exist_ok=True)
    with Runner(duo_fw=a.duo_flash, partner=a.rom, partner_save=a.sav, duo_player=a.duo_player,
                wait_for_hello=True, log_link=os.path.join(a.out, "link.log")) as v:
        v.state_load("partner", a.state)
        tool = Tool(v, ["blender", "--blends", "1", "--seconds", "600"], log=os.path.join(a.out, "tool.log"), cwd=a.out)
        assert tool.wait_for("Ready", 120), "the tool never got ready"
        for wait in (90, 90, 240):                      # save? YES; overwrite? YES; saving
            v.press("partner", "A", frames=6, then=wait)
        print("linked after", tap_until_linked(v, tool), "taps", flush=True)
        play = Player(v, a.profile, 1 - a.duo_player)
        n = 0
        while not (tool.saw("done") or tool.p.poll() is not None) and n < 60000:
            play.step(); n += 1
            if n % 3000 == 0:
                v.screenshot("partner", os.path.join(a.out, f"blend{n:05d}.png"))
        print(f"the game's player pressed {play.hits} times as its arrow passed", flush=True)
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
