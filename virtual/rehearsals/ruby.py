"""ruby.py - helpers for driving a Gen 3 game on the Virtual DUO's partner GBA (English Ruby 1.1
first, hence the name; runner() picks up any game savegen/profiles.py knows, by the ROM's header).

Nothing here is Nintendo's: the ROM, the save, the DUO's flash image and any save states are
passed in by path and stay where they are. The addresses below are facts about the game's RAM.
"""
import os, struct, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "runner"))
from vduo import Runner  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "savegen"))

OBJECTS = 0x030048A0          # gMapObjects (16 of 0x24 bytes) in English Ruby 1.1
GMAIN = 0x03001770            # gMain: callback1, callback2, ...
CB2_PARTY_MENU = 0x0806AEFC   # CB2_PartyMenuMain
PARTY_MENU, PARTY = None, 0x03004360  # gPartyMenu (Emerald, FireRed/LeafGreen), gPlayerParty
MOVES = (0x02024A80, 0x02024E64, 0x03004330, 0x0802C68C)   # gBattleMons, gMoveSelectionCursor,
#                                     gBattlerControllerFuncs, HandleInputChooseMove (English Ruby 1.1)


def _move_with_pp(v):
    """In the game's own move menu, with the cursor on a move that has no PP left (A would only say
    so, for ever): move the cursor to the first move that has some. (14 November: Aggron's first
    move, Iron Defense, ran out, and the DUO's Altaria couldn't finish the battle either.)"""
    mons, cursor, funcs, choose = MOVES
    f = struct.unpack("<4I", v.read("partner", funcs, 16))
    for b in range(4):
        if f[b] & ~1 != choose & ~1:
            continue
        c = v.read("partner", cursor + b, 1)[0] & 3
        m = v.read("partner", mons + 0x58 * b, 0x28)
        moves, pp = struct.unpack_from("<4H", m, 0x0C), m[0x24:0x28]
        if pp[c] or not moves[c]:
            return
        t = next((i for i in range(4) if moves[i] and pp[i]), None)
        if t is None:
            return                                # (nothing left: the game picks Struggle on A)
        if (t ^ c) & 1:
            v.press("partner", "RIGHT" if t & 1 else "LEFT", frames=4, then=12)
        if (t ^ c) & 2:
            v.press("partner", "DOWN" if t & 2 else "UP", frames=4, then=12)
        return
TOOLKIT = os.environ.get("TOOLKIT", os.path.dirname(os.path.dirname(HERE)))     # the repository: virtual/..


def objects(v):
    """(slot, local id, (x, y)) for every active object; coordinates include the map's 7-tile border."""
    t = v.read("partner", OBJECTS, 16 * 0x24)
    return [(i, t[i * 0x24 + 8], struct.unpack_from("<hh", t, i * 0x24 + 0x10))
            for i in range(16) if t[i * 0x24] & 1]


class Walker:
    """Moves the player one tile at a time, watching the game's own coordinates (closed loop)."""
    def __init__(self, v, me=0xFF):
        self.v, self.me = v, me           # me: 0xFF outdoors; in a link room, the link player number

    def pos(self):
        for _, lid, xy in objects(self.v):
            if lid == self.me:
                return xy
        raise RuntimeError("the player isn't among the objects")

    def to(self, x, y, face=None, limit=40):
        v = self.v
        for _ in range(limit):
            cx, cy = self.pos()
            if (cx, cy) == (x, y):
                break
            d = "LEFT" if cx > x else "RIGHT" if cx < x else "UP" if cy > y else "DOWN"
            v.keys("partner", d)
            for _ in range(30):
                v.run_frames("partner", 2)
                if self.pos() != (cx, cy):
                    break
            v.keys("partner")
            v.run_frames("partner", 20)
        else:
            raise RuntimeError(f"couldn't reach {(x, y)}; at {self.pos()}")
        if face:
            v.press("partner", face, frames=3, then=12)       # a short tap only turns


_party_visits = 0


def battle_press(v):
    """The game's side in a battle: A throughout (FIGHT, then the first move), except in the party
    menu after one of its Pokemon faints, where the cursor starts on the fainted one and A would only
    say so: there, move down to the next Pokemon, A, and A again for SHIFT. (A fainted one there just
    says so, and the next press moves on.)"""
    global _party_visits
    if struct.unpack("<I", v.read("partner", GMAIN + 4, 4))[0] & ~1 == CB2_PARTY_MENU:
        # one more DOWN on each visit: in a multi battle the partner's Pokemon are on the same screen
        # (the game refuses them and comes back with the cursor reset), so a single DOWN can land on
        # the same wrong one for ever (Italian Emerald's Tower, 14 November)
        _party_visits += 1
        if PARTY_MENU:
            # closed loop: the cursor (gPartyMenu.slotId) moved onto a Pokemon that can still fight,
            # a different one each visit (one still on the field, or the partner's, gets refused)
            party = v.read("partner", PARTY, 600)
            alive = [i for i in range(6) if struct.unpack_from("<HH", party, 100 * i + 86)[1]
                     and struct.unpack_from("<H", party, 100 * i + 86)[0]]
            target = alive[(_party_visits - 1) % len(alive)] if alive else None
            for k in range(18):                   # (DOWN within a column, RIGHT across: a multi battle's
                if target is None or v.read("partner", PARTY_MENU + 9, 1)[0] == target:    # screen has two)
                    break
                v.press("partner", "RIGHT" if k % 3 == 2 else "DOWN", frames=4, then=20)
        else:
            for _ in range(1 + (_party_visits - 1) % 5):
                v.press("partner", "DOWN", frames=4, then=20)
        v.press("partner", "A", frames=6, then=40)
        v.press("partner", "A", frames=6, then=60)
    else:
        _move_with_pp(v)
        v.press("partner", "A", frames=6, then=40)


class Tool:
    """duo_events.py --virtual, run beside the runner, its output gathered line by line. (-u: unbuffered,
    or Python holds the tool's lines back when its output is a pipe, and "Ready" never arrives.)"""
    def __init__(self, v, args, log=None, cwd=None):
        self.lines = []
        self.log = open(log, "w") if log else None
        self.p = subprocess.Popen([sys.executable, "-u", os.path.join(TOOLKIT, "duo_events.py"), "--virtual",
                                   f"127.0.0.1:{v.usb_port}", "--wait", "60", *args],
                                  cwd=cwd or os.getcwd(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            self.lines.append(line.rstrip())
            if self.log:
                self.log.write(line); self.log.flush()

    def saw(self, text):
        return any(text in l for l in self.lines)

    def wait_for(self, text, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.saw(text):
                return True
            time.sleep(0.2)
        return False

    def phases(self):
        return [l for l in self.lines if l.startswith("  [")]

    def linked(self):
        return any("waiting" not in l.lower() for l in self.phases())      # ("WAITING" in the blender)

    def finish(self, v, frames=7200):
        """Let the tool end on its own while the game keeps running."""
        for _ in range(frames // 60):
            if self.p.poll() is not None:
                break
            v.run_frames("partner", 60)
        if self.p.poll() is None:
            self.p.terminate()
        return self.p.wait(10)


def choose_room(v, profile, room):
    """Emerald and FireRed/LeafGreen: from the Cable Club's menu (the savegen state), the room by name.
    Returns False for Ruby, whose states stand at each room's own attendant."""
    menu = getattr(profile, "CABLE_CLUB_MENU", None)
    if not menu:
        return False
    for _ in range(menu.index(room)):
        v.press("partner", "DOWN", frames=6, then=20)
    v.press("partner", "A", frames=6, then=150)
    return True


def tap_until_linked(v, tool, taps=40):
    """The Cable Club's two prompts want a press, then a hold once the text has scrolled: tapping A
    until the DUO reports the link covers both, whatever the timing."""
    for i in range(taps):
        v.keys("partner", "A"); v.run_frames("partner", 12)
        v.keys("partner"); v.run_frames("partner", 18)
        if tool.linked():
            return i + 1
    raise RuntimeError("the link didn't come up")


def common_args(description):
    import argparse
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--rom", required=True, help="the game for the partner GBA (English Ruby 1.1, or any ROM "
                                                 "savegen/profiles.py knows)")
    ap.add_argument("--sav", required=True, help="its save (read only: it stays in memory)")
    ap.add_argument("--duo-flash", required=True, help="the DUO's flash image (formatted: see the README)")
    ap.add_argument("--state", required=True, help="a save state of the partner at the attendant's question")
    ap.add_argument("--out", default=".", help="where screenshots and logs go")
    return ap


def set_game(rom):
    """Point the helpers at this ROM's RAM and code (savegen/profiles.py); returns its profile."""
    global OBJECTS, GMAIN, CB2_PARTY_MENU, PARTY_MENU, PARTY, MOVES
    import profiles
    p = profiles.for_rom(rom)
    OBJECTS, GMAIN, CB2_PARTY_MENU = p.gObjectEvents, p.gMain, p.sym["CB2_PartyMenu"]
    PARTY_MENU, PARTY = getattr(p, "gPartyMenu", None), p.gPlayerParty
    MOVES = (p.gBattleMons, p.gMoveSelectionCursor, p.gBattlerControllerFuncs, p.sym["HandleInputChooseMove"])
    return p


def runner(a, **kw):
    a.profile = set_game(a.rom)
    return Runner(duo_fw=a.duo_flash, partner=a.rom, partner_save=a.sav, duo_player=1,
                  wait_for_hello=True, **kw)
