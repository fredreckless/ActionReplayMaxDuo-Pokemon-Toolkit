"""compose.py - the videos' frames, 1080x1080 at 30 a second, written straight into ffmpeg.

Why 1080x1080: the GBA's screen is 3:2. With the game across the full width W it is 2W/3 tall; two
half-width panes below at the same 3:2 are W/3 tall; so the screens alone make a square, plus the
instruction band. With integer scaling and a band of 120:

    +----+------------------------------------+----+
    |    |   the game's GBA, 4x (960x640)     |    |   0-640
    +----+------------------------------------+----+
    |  instruction band (step, words)                 |   640-760
    +-----------------------+------------------------+
    |  the laptop's terminal | the DUO's GBA, 2x      |   760-1080
    |  600x320               | 480x320                |
    +-----------------------+------------------------+

Setup scenes (setups.py) and title cards take the whole square.

A recording is what vduo.py and ruby.Tool leave in VDUO_RECORD: NNNNNN_partner.png and
NNNNNN_duo.png every VDUO_RECORD_STEP frames (2: so 30 a second is real time), and terminal.jsonl
(the tool's command and lines, and marks, each against a recorded frame).
"""
import hashlib, json, os, subprocess
from PIL import Image, ImageDraw

from scene import font, draw_band, INK, GOLD

S, FPS = 1080, 30
TOP, BAND = 640, 120
BOT = TOP + BAND
GAME_X = (S - 960) // 2
TERM_W = S - 480
PROMPT = "C:\\ActionReplay>"
BG = (14, 17, 30)
DIM = (130, 140, 168)


class Recording:
    def __init__(self, path):
        self.path = path
        self.n = 0
        while os.path.exists(self.frame(self.n, "partner")):
            self.n += 1
        if not self.n:
            raise SystemExit(f"no recorded frames in {path}")
        self.events = []
        tj = os.path.join(path, "terminal.jsonl")
        if os.path.exists(tj):
            with open(tj) as f:
                self.events = [json.loads(l) for l in f if l.strip()]
        self.events.sort(key=lambda e: e["n"])
        self.cmd = next((e["cmd"] for e in self.events if "cmd" in e), None)
        self._hash = {}

    def frame(self, i, who):
        return os.path.join(self.path, f"{i:06d}_{who}.png")

    def image(self, i, who):
        return Image.open(self.frame(max(0, min(i, self.n - 1)), who)).convert("RGB")

    def digest(self, i):
        if i not in self._hash:
            h = hashlib.md5()
            for who in ("partner", "duo"):
                with open(self.frame(i, who), "rb") as f:
                    h.update(f.read())
            self._hash[i] = h.digest()
        return self._hash[i]

    def find(self, text, after=0, kind="line"):
        for e in self.events:
            if e["n"] >= after and text in e.get(kind, ""):
                return e["n"]
        return None

    def lines_until(self, i):
        return [e["line"] for e in self.events if "line" in e and e["n"] <= i]


def blank(img):
    return img is None or img.getextrema() in (((0, 0),) * 3, ((255, 255),) * 3)


class Video:
    def __init__(self, out, title, game_name, crf=20, preset="veryfast"):
        self.out, self.title, self.game_name = out, title, game_name
        self.caption, self.step = "", None
        self.term = []                       # (kind, text)
        self.typing = None
        self.game = self.duo = None
        self.badge = ""
        self.frames = 0
        self.f_term = font("VT323-Regular.ttf", 22)
        self.f_small = font("Jersey10.ttf", 30)
        self.f_tag = font("Silkscreen-Regular.ttf", 16)
        self._cache = {}
        self._fade, self._from, self._shown = 0, None, None
        self.p = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{S}x{S}",
             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], stdin=subprocess.PIPE)

    # -- panels ------------------------------------------------------------------------------------------
    def _cached(self, key, make):
        if key not in self._cache:
            for k in [k for k in self._cache if k[0] == key[0]]:
                del self._cache[k]
            self._cache[key] = make()
        return self._cache[key]

    def _margins(self):
        def make():
            img = Image.new("RGB", (S, TOP), BG)
            for x, text in ((0, "THE GAME'S GBA"), (S - GAME_X, self.game_name.upper())):
                strip = Image.new("RGB", (TOP, GAME_X), BG)
                d = ImageDraw.Draw(strip)
                d.text((TOP // 2, GAME_X // 2), text, font=self.f_tag, fill=DIM, anchor="mm")
                img.paste(strip.rotate(90 if x == 0 else -90, expand=True), (x, 0))
            return img
        return self._cached(("margins", self.game_name), make)

    def _band(self):
        def make():
            img = Image.new("RGB", (S, BAND), BG)
            draw_band(img, self.caption, self.step, 0, BAND)
            return img
        return self._cached(("band", self.caption, self.step), make)

    def _terminal(self):
        def make():
            w, h = TERM_W, S - BOT
            img = Image.new("RGB", (w, h), (10, 12, 16))
            d = ImageDraw.Draw(img)
            d.rectangle([0, 0, w, 26], fill=(38, 42, 54))
            d.text((10, 13), "THE LAPTOP: COMMAND PROMPT", font=self.f_tag, fill=(205, 210, 222), anchor="lm")
            cols = int((w - 20) / d.textlength("M", font=self.f_term))
            rows = []
            for kind, t in self.term:
                pad = " " * min(8, len(t) - len(t.lstrip()) + 2)
                while len(t) > cols:
                    cut = t.rfind(" ", len(pad) + 4, cols)
                    cut = cols if cut < 0 else cut
                    rows.append((kind, t[:cut]))
                    t = pad + t[cut:].lstrip()
                rows.append((kind, t))
            if self.typing is not None:
                text, k = self.typing
                rows.append(("cmd", PROMPT + " " + text[:k] + "_"))
            lh = 20
            fit = (h - 34) // lh
            for i, (kind, t) in enumerate(rows[-fit:]):
                col = {"cmd": (130, 230, 150), "phase": (255, 214, 120), "warn": (255, 140, 120)}.get(
                    kind, (214, 220, 230))
                d.text((10, 32 + i * lh), t, font=self.f_term, fill=col)
            return img
        return self._cached(("term", len(self.term), self.typing), make)

    def _duo_panel(self):
        def make():
            img = Image.new("RGB", (480, S - BOT), (36, 42, 34))
            if blank(self.duo):
                d = ImageDraw.Draw(img)
                d.text((240, 160), "the DUO's GBA: off", font=self.f_small, fill=(98, 110, 92), anchor="mm")
            else:
                img.paste(self.duo.resize((480, 320), Image.NEAREST), (0, 0))
            return img
        return self._cached(("duo", id(self.duo)), make)

    def panel_frame(self):
        frame = Image.new("RGB", (S, S), BG)
        frame.paste(self._margins(), (0, 0))
        if blank(self.game):
            d = ImageDraw.Draw(frame)
            d.rectangle([GAME_X, 0, GAME_X + 959, TOP - 1], fill=(30, 34, 28))
            d.text((S // 2, TOP // 2), "the game's GBA: off", font=font("Jersey10.ttf", 48), fill=(90, 100, 86),
                   anchor="mm")
        else:
            frame.paste(self.game.resize((960, 640), Image.NEAREST), (GAME_X, 0))
        if self.badge:
            d = ImageDraw.Draw(frame)
            d.rectangle([GAME_X + 960 - 150, 14, GAME_X + 960 - 14, 62], fill=(0, 0, 0))
            d.text((GAME_X + 960 - 82, 39), self.badge, font=font("Jersey10.ttf", 40), fill=GOLD, anchor="mm")
        frame.paste(self._band(), (0, TOP))
        frame.paste(self._terminal(), (0, BOT))
        frame.paste(self._duo_panel(), (TERM_W, BOT))
        d = ImageDraw.Draw(frame)
        d.line([(TERM_W, BOT), (TERM_W, S)], fill=(70, 78, 110), width=2)
        return frame

    def emit(self, n=1, full=None):
        frame = full if full is not None else self.panel_frame()
        if self._fade and self._from is not None:
            frame = Image.blend(self._from, frame, 1 - self._fade / 12)
            self._fade -= 1
        raw = frame.tobytes()
        for _ in range(n):
            self.p.stdin.write(raw)
        self.frames += n
        self._shown = frame

    def crossfade(self):
        """The next half second blends in from whatever was last shown."""
        self._from, self._fade = self._shown, 12

    # -- what a story says ----------------------------------------------------------------------------
    def say(self, caption, step=None):
        self.caption, self.step = caption, step

    def seconds(self, s):
        return max(1, int(round(s * FPS)))

    def title_card(self, title, sub, secs=4.0):
        img = Image.new("RGB", (S, S), BG)
        d = ImageDraw.Draw(img)
        d.text((S // 2, S // 2 - 70), title, font=font("Jersey10.ttf", 96), fill=INK, anchor="mm")
        y = S // 2 + 30
        for line in sub.split("\n"):
            d.text((S // 2, y), line, font=font("Jersey10.ttf", 42), fill=DIM, anchor="mm")
            y += 48
        n = self.seconds(secs)
        for i in range(n):
            f = min(1.0, i / 12, (n - i) / 12)
            self.emit(full=Image.blend(Image.new("RGB", img.size, BG), img, f) if f < 1 else img)

    def scene(self, sc, speed=1.0):
        """An animated setup scene, full screen, from start to end; blends in and out."""
        self.crossfade()
        for i in range(int(sc.duration * FPS / speed)):
            self.emit(full=sc.render(i * speed / FPS))
        self.crossfade()

    def type_command(self, cmd):
        for k in range(1, len(cmd) + 1, 1):
            self.typing = (cmd, k)
            if k % 2 == 0 or k == len(cmd):
                self.emit()
        self.emit(self.seconds(0.4))
        self.typing = None
        self.term.append(("cmd", PROMPT + " " + cmd))

    def print_lines(self, lines):
        for l in lines:
            kind = "phase" if l.startswith("  [") else "warn" if "WARN" in l or "FAIL" in l else "out"
            self.term.append((kind, l))

    def play(self, rec, start=0, end=None, speed=1.0, cues=(), idle=1.5, shown_from=None):
        """Recorded frames start..end at speed (fast-forward shows its badge), the terminal following
        the tool's lines; cues (frame, words, step) change the band. Stretches where nothing changes
        on either screen are cut down to idle seconds."""
        end = rec.n if end is None else min(end, rec.n)
        shown = shown_from if shown_from is not None else len(rec.lines_until(start - 1)) if start else 0
        cues = sorted((c for c in cues if c[0] is not None), key=lambda c: c[0])
        still, last, pos = 0, None, float(start)
        self.badge = f">> {speed:g}x" if speed > 1 else ""
        while pos < end:
            i = int(pos)
            while cues and cues[0][0] <= i:
                _, cap, step = cues.pop(0)
                self.say(cap, step)
            lines = rec.lines_until(i)
            new = len(lines) > shown
            if new:
                self.print_lines(lines[shown:])
                shown = len(lines)
            dg = rec.digest(i)
            still = still + 1 if dg == last else 0
            last = dg
            if still < idle * FPS * max(1.0, speed) or new:
                self.game, self.duo = rec.image(i, "partner"), rec.image(i, "duo")
                self.emit()
            pos += speed
        lines = rec.lines_until(end)
        if len(lines) > shown:
            self.print_lines(lines[shown:])
        self.badge = ""

    def hold(self, secs):
        self.emit(self.seconds(secs))

    def close(self):
        self.p.stdin.close()
        self.p.wait()
        return self.frames / FPS
