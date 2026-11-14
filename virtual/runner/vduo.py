"""vduo.py - drive the Virtual DUO runner (vduo) from Python tests.

    from vduo import Runner
    with Runner(duo_fw="fw_v42.bin", slot="ruby.gba", slot_save="ruby.sav", slot_type="sanyo",
                partner="ruby.gba", partner_save="ruby2.sav") as v:
        v.run_frames("partner", 600)                   # let the game boot
        v.press("partner", "A", frames=5)
        print(v.status())
        # duo_events.py --virtual 127.0.0.1:<v.usb_port> ... talks to the DUO meanwhile

Nothing is written to the ROM or save files given: saves live in memory in the runner, and
leave only through save_sav().
"""
import os, shutil, socket, subprocess, time

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = {"A": 0x001, "B": 0x002, "SELECT": 0x004, "START": 0x008, "RIGHT": 0x010, "LEFT": 0x020,
        "UP": 0x040, "DOWN": 0x080, "R": 0x100, "L": 0x200}


class VduoError(Exception):
    pass


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def binary():
    for p in (os.environ.get("VDUO"), os.path.join(HERE, "build", "vduo"), shutil.which("vduo")):
        if p and os.path.exists(p):
            return p
    raise VduoError("vduo isn't built: run runner/build.sh")


class Runner:
    def __init__(self, duo_fw, slot=None, slot_save=None, slot_type="none", partner=None, partner_save=None,
                 duo_player=0, wait_for_hello=False, usb_port=None, log_ctrl=None, log_link=None):
        self.usb_port = usb_port or free_port()
        cmd = [binary(), "--duo-fw", duo_fw, "--slot-type", slot_type, "--usb-port", str(self.usb_port),
               "--duo-player", str(duo_player)]
        for flag, val in (("--slot", slot), ("--slot-save", slot_save), ("--partner", partner),
                          ("--partner-save", partner_save), ("--log-ctrl", log_ctrl), ("--log-link", log_link)):
            if val:
                cmd += [flag, val]
        if wait_for_hello:
            cmd.append("--wait-for-hello")
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, bufsize=1)
        line = self.p.stdout.readline()
        if not line.startswith("ready"):
            raise VduoError(f"vduo didn't start: {line!r} {self.p.stderr.read()[-2000:]}")
        self.banner = line.strip()

    # ---- plumbing
    def cmd(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        extra = []
        while True:
            reply = self.p.stdout.readline()
            if not reply:
                raise VduoError(f"vduo stopped: {self.p.stderr.read()[-2000:]}")
            reply = reply.rstrip("\n")
            if reply.startswith("ok"):
                self.extra = extra
                return reply[3:]
            if reply.startswith("err"):
                raise VduoError(reply[4:])
            extra.append(reply)

    def close(self):
        if self.p.poll() is None:
            try:
                self.cmd("quit")
            except (VduoError, BrokenPipeError, OSError):
                pass
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- commands
    def _path(self, path):
        """The control channel splits on spaces: a path with spaces goes through a symbolic link
        without any (writing through one creates the file it points at)."""
        path = os.path.abspath(path)
        if " " not in path:
            return path
        import tempfile
        if not hasattr(self, "_links"):
            self._links = tempfile.mkdtemp(prefix="vduo_paths_")
        link = os.path.join(self._links, f"p{len(os.listdir(self._links))}{os.path.splitext(path)[1].replace(' ', '')}")
        os.symlink(path, link)
        return link

    def status(self):
        return dict(kv.split("=", 1) for kv in self.cmd("status").split())

    def run_frames(self, player, n):
        self.cmd(f"run_frames {player} {n}")

    def keys(self, player, *names):
        mask = 0
        for n in names:
            mask |= KEYS[n.upper()]
        self.cmd(f"keys {player} {mask:x}")

    def press(self, player, *names, frames=4, then=4):
        """Hold the buttons for some frames, then let go for some more."""
        self.keys(player, *names)
        self.run_frames(player, frames)
        self.keys(player)
        self.run_frames(player, then)

    def read(self, player, addr, n):
        return bytes.fromhex(self.cmd(f"read {player} {addr:#x} {n}"))

    def write(self, player, addr, data):
        self.cmd(f"write {player} {addr:#x} {bytes(data).hex()}")

    def state_save(self, player, path):
        self.cmd(f"state_save {player} {self._path(path)}")

    def state_load(self, player, path):
        self.cmd(f"state_load {player} {self._path(path)}")

    def screenshot(self, player, path):
        self.cmd(f"screenshot {player} {self._path(path)}")

    def save_sav(self, player, path):
        return int(self.cmd(f"save_sav {player} {self._path(path)}"))

    def save_flash(self, path):
        self.cmd(f"save_flash duo {self._path(path)}")

    def power_on(self):
        self.cmd("power_on")

    def reset(self, player):
        self.cmd(f"reset {player}")

    def events(self):
        self.cmd("events")
        return [e.split(" ", 2)[1:] for e in self.extra]

    def wait_until(self, player, predicate, frames=60, timeout=60.0, step=10):
        """Run a player in steps until predicate() holds (or fail after timeout seconds)."""
        end = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > end:
                raise VduoError("timed out waiting")
            self.run_frames(player, step)
