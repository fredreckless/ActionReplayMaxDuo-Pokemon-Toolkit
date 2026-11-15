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


_BATTLE_CB2 = {}                # the battle's own callback, seen on the first press outside the party menu
PHYSICAL = set(range(9))       # Gen 3: a move's kind follows its type (Normal to Steel physical)


def _battler(v, b):
    """gBattleMons[b]: species, the four stats, moves, types, PP, HP."""
    mons = MOVES[0]
    m = v.read("partner", mons + 0x58 * b, 0x58)
    return dict(species=struct.unpack_from("<H", m, 0)[0], stats=struct.unpack_from("<5H", m, 2),
                moves=struct.unpack_from("<4H", m, 0x0C), types=(m[0x21], m[0x22]), pp=m[0x24:0x28],
                hp=struct.unpack_from("<H", m, 0x28)[0])


def _score(move, att_types, att_stats, foe_types, foe_stats):
    """What a good player weighs: power x accuracy, x1.5 for the attacker's own type, x how well the
    type does against the foe's (both types), x attack over defence for the move's kind. Moves that
    need a turn to charge, or recharge after, count for half."""
    if TOOLKIT not in sys.path:
        sys.path.insert(0, TOOLKIT)
    import duo_battle as B
    eff, power, typ, acc = B.MOVES[move][0], B.MOVES[move][1], B.MOVES[move][2], B.MOVES[move][3] or 100
    if not power:
        return 0.0
    if power == 1:                               # (fixed or variable damage: count it as a middling hit)
        power = 60
    mult = 1.0
    for d in set(foe_types):
        m = B.CHART.get((typ, d))
        if m:
            mult *= m[0] / 10
    stab = 1.5 if typ in att_types else 1.0
    atk, df = (att_stats[0], foe_stats[1]) if typ in PHYSICAL else (att_stats[3], foe_stats[4])
    half = 0.5 if B.EFFECT.get(eff) in B.AWKWARD else 1.0
    return power * acc / 100 * stab * mult * atk / max(1, df) * half


def _foes(v, b):
    return [f for f in range(4) if f % 2 != b % 2 and _battler(v, f)["hp"]]


def _move_with_pp(v):
    """In the game's own move menu: move the cursor to the best move against the foes on the field
    (_score), as a good player would choose; never one with no PP left (A would only say so, for
    ever: 14 November, Aggron's Iron Defense ran out). With nothing left, the game picks Struggle."""
    mons, cursor, funcs, choose = MOVES
    f = struct.unpack("<4I", v.read("partner", funcs, 16))
    for b in range(4):
        if f[b] & ~1 != choose & ~1:
            continue
        c = v.read("partner", cursor + b, 1)[0] & 3
        me = _battler(v, b)
        foes = [_battler(v, x) for x in _foes(v, b)] or [_battler(v, b ^ 1)]
        usable = [i for i in range(4) if me["moves"][i] and me["pp"][i]]
        if not usable:
            return
        try:
            t = max(usable, key=lambda i: (max(_score(me["moves"][i], me["types"], me["stats"], fo["types"],
                                                      fo["stats"]) for fo in foes), -i))
        except Exception:                         # (never let the choosing stop a rehearsal)
            t = c if c in usable else usable[0]
        if (t ^ c) & 1:
            v.press("partner", "RIGHT" if t & 1 else "LEFT", frames=4, then=12)
        if (t ^ c) & 2:
            v.press("partner", "DOWN" if t & 2 else "UP", frames=4, then=12)
        return


def _party_order(v, alive):
    """The party's Pokemon that can fight, best first against the foe now on the field: each one's
    best move's _score (from its own species' types and base stats, and its moves)."""
    if TOOLKIT not in sys.path:
        sys.path.insert(0, TOOLKIT)
    import duo_battle as B
    import duo_events as E
    try:
        foe = next((_battler(v, f) for f in (1, 3) if _battler(v, f)["hp"]), _battler(v, 1))
        party = v.read("partner", PARTY, 600)
        def best(i):
            f, problems = E.parse_pk3(bytes(party[100 * i:100 * i + 100]))
            if problems:
                return 0
            sp = B.SPECIES[f["species"]]
            stats = (sp[1], sp[2], sp[3], sp[4], sp[5])
            return max((_score(m, (sp[6], sp[7]), stats, foe["types"], foe["stats"]) for m in f["moves"] if m),
                       default=0)
        return sorted(alive, key=lambda i: -best(i))
    except Exception:
        return alive


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
            alive = _party_order(v, alive)
            target = alive[(_party_visits - 1) % len(alive)] if alive else None
            for k in range(18):                   # (DOWN within a column, RIGHT across: a multi battle's
                if target is None or v.read("partner", PARTY_MENU + 9, 1)[0] == target:    # screen has two)
                    break
                v.press("partner", "RIGHT" if k % 3 == 2 else "DOWN", frames=4, then=20)
        else:
            for _ in range(1 + (_party_visits - 1) % 5):
                v.press("partner", "DOWN", frames=4, then=20)
        v.press("partner", "A", frames=6, then=50)       # the Pokemon: its menu (SHIFT first)
        v.press("partner", "A", frames=6, then=60)       # SHIFT
        # (a press too early can land on SUMMARY instead: back out of it, and the next visit
        # chooses again; 15 November, the battle video)
        for _ in range(6):
            cb2 = struct.unpack("<I", v.read("partner", GMAIN + 4, 4))[0] & ~1
            if cb2 in (CB2_PARTY_MENU, _BATTLE_CB2.get("cb2")) or not _BATTLE_CB2:
                break
            v.press("partner", "B", frames=6, then=60)
    else:
        _BATTLE_CB2.setdefault("cb2", struct.unpack("<I", v.read("partner", GMAIN + 4, 4))[0] & ~1)
        _move_with_pp(v)
        v.press("partner", "A", frames=6, then=40)


def record(v, **what):
    """With VDUO_RECORD set (vduo.py saves both screens there), note something against the frame
    being recorded, in terminal.jsonl: the tool's command and each line it prints (the video's
    terminal), or a mark (mark=...) at a moment in the rehearsal that a caption can follow."""
    rec = os.environ.get("VDUO_RECORD")
    if not rec:
        return
    import json
    os.makedirs(rec, exist_ok=True)
    with open(os.path.join(rec, "terminal.jsonl"), "a") as f:
        f.write(json.dumps(dict(n=getattr(v, "_rec_n", 0), **what)) + "\n")


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
        self.v = v
        record(v, cmd=self.shown(args))
        threading.Thread(target=self._read, daemon=True).start()

    @staticmethod
    def shown(args):
        """The command as someone with the real DUO would type it: no --virtual, --wait or --seconds
        (the rehearsal's own time limit), and files by their names alone."""
        out, skip = [], False
        for x in args:
            if skip:
                skip = False
            elif x == "--seconds":
                skip = True
            else:
                out.append(os.path.basename(x) if os.sep in x else x)
        return "python duo_events.py " + " ".join(out)

    def _read(self):
        for line in self.p.stdout:
            self.lines.append(line.rstrip())
            record(self.v, line=line.rstrip())
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
        """A phase past waiting. ("WAITING" in the blender; and the tool's "no change for 30 s" notice
        isn't a phase: on a slow run, such as a recorded one, it comes before the link does.)"""
        return any("waiting" not in l.lower() and "no change for" not in l for l in self.phases())

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
