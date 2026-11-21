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
        # the game's sound (vduo.py: partner.pcm, and where each recorded frame's sound starts)
        self.pcm, self.pos = os.path.join(path, "partner.pcm"), []
        if os.path.exists(self.pcm) and os.path.exists(os.path.join(path, "partner_pos.txt")):
            with open(os.path.join(path, "partner_pos.txt")) as f:
                self.pos = [int(l) for l in f if l.strip()]

    def sound(self, i):
        """(start, length) of recorded frame i's sound in partner.pcm, or None."""
        if i + 1 < len(self.pos):
            return self.pos[i], max(1, self.pos[i + 1] - self.pos[i])
        return None

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
    def __init__(self, out, title, game_name, crf=20, preset="veryfast", theme=None):
        self.out, self.title, self.game_name = out, title, game_name
        self.theme = theme                   # music under everything (a .pcm, looped), or None
        self.sounds = []                     # (video frame, .pcm, start, length): the game's own sound
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
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", out + ".silent.mp4"], stdin=subprocess.PIPE)

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
                d.text((10, 32 + i * lh), t.replace("fi", "f\u200ci"), font=self.f_term, fill=col)   # (VT323's "fi" drops the i)
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

    OVERVIEW = [
        "Datel's Action Replay MAX DUO: it only ever backed up DS saves, and its drivers stopped working long ago",
        "New, open firmware (Reckless), built from Datel's own update file and installed by you",
        "Now it backs up any GBA game's save to the PC too, without ever writing to the cartridge",
        "Its GBA plays the other end of a link cable: trades, battles, Record Mixing, the Berry Blender, "
        "contests and the Battle Tower",
        "It plays the e-Reader for Mystery Events, and the Wireless Adapter and distributor for Mystery Gift",
        "As legit as it gets: the game receives everything through its own menus and its own code, just as "
        "from a real event or a real friend. Nothing is edited into the save",
        "Every Generation III Pokémon game; built against simulations of the DUO and the games, then proven "
        "on the real thing",
    ]

    def overview(self, secs=11.0):
        """The MAX DUO itself, big, and what this toolkit does with it: the opening of every video."""
        import parts
        from scene import Scene
        duo = parts.duo().img
        big = duo.resize((duo.width * 6, duo.height * 6), Image.NEAREST)
        bg = Scene(1).background().resize((S, S), Image.NEAREST).convert("RGB")
        ft, fb = font("Jersey10.ttf", 64), font("Jersey10.ttf", 31)
        n = self.seconds(secs)
        lines = []
        for item in self.OVERVIEW:                     # wrapped to the column right of the DUO
            words, cur = item.split(), ""
            d0 = ImageDraw.Draw(bg)
            rows = []
            for w in words:
                if d0.textlength((cur + " " + w).strip(), font=fb) > S - 440:
                    rows.append(cur)
                    cur = w
                else:
                    cur = (cur + " " + w).strip()
            rows.append(cur)
            lines.append(rows)
        for i in range(n):
            t = i / FPS
            frame = bg.copy()
            d = ImageDraw.Draw(frame)
            k = min(1.0, t / 0.6)
            x = int(-big.width + (40 + big.width) * (1 - (1 - k) ** 3))
            frame.paste(big, (x, 230), big)
            d.text((S // 2, 90), "Action Replay MAX DUO", font=ft, fill=GOLD, anchor="mm")
            d.text((S // 2, 150), "with the Reckless firmware and this toolkit", font=fb, fill=DIM, anchor="mm")
            y = 220
            for j, rows in enumerate(lines):
                if t < 0.8 + 1.1 * j:
                    break
                d.rectangle([392, y + 12, 402, y + 22], fill=GOLD)
                for r in rows:
                    d.text((416, y), r, font=fb, fill=INK)
                    y += 34
                y += 14
            draw_band(frame, "What it is, and what it does now", "MAX DUO", S - 132)
            f = min(1.0, i / 12, (n - i) / 12)
            self.emit(full=Image.blend(Image.new("RGB", frame.size, BG), frame, f) if f < 1 else frame)

    SETUP = [   # (what, then the words or commands, as the README has them)
        ("Get the toolkit from GitHub",
         ["github.com/fredreckless/ActionReplayMaxDuo-Pokemon-Toolkit", "Code > Download ZIP, and unzip it"]),
        ("Install Python 3.10 or newer, then the helpers",
         ["(tick \"Add Python to PATH\")", "pip install -r requirements.txt"]),
        ("Let Windows talk to the DUO, with Zadig",
         ["Options > List All Devices; USB ID 05FD DAAE", "WinUSB > Install Driver"]),
        ("Build the firmware from Datel's 1.06 update, and install it",
         ["python firmware/build_firmware.py us_update_v1_06.bin",
          "(DUO in USB SERVER MODE)  python maxduo_saves.py --update",
          "  firmware/build/duo_1.06_reckless_v4.2.bin   (type UPDATE)",
          "The USB screen then says RECKLESS V4 - READY"]),
    ]

    def setup(self, secs=13.0):
        """Setting the MAX DUO up, once: GitHub, Python, Zadig, the firmware (the README's steps)."""
        from scene import Scene
        bg = Scene(1).background().resize((S, S), Image.NEAREST).convert("RGB")
        ft, fh, fc = font("Jersey10.ttf", 60), font("Jersey10.ttf", 36), font("VT323-Regular.ttf", 30)
        n = self.seconds(secs)
        frames = []
        for j in range(len(self.SETUP) + 1):              # one frame per step shown so far
            fr = bg.copy()
            d = ImageDraw.Draw(fr)
            d.text((S // 2, 80), "Setting up the MAX DUO (once)", font=ft, fill=GOLD, anchor="mm")
            y = 150
            for k, (what, lines) in enumerate(self.SETUP[:j]):
                d.rounded_rectangle([40, y, 92, y + 48], 10, fill=GOLD)
                d.text((66, y + 24), str(k + 1), font=fh, fill=BG, anchor="mm")
                d.text((112, y + 4), what, font=fh, fill=INK)
                y += 50
                for line in lines:
                    d.rounded_rectangle([108, y, S - 40, y + 36], 6, fill=(8, 10, 18))
                    d.text((120, y + 2), line.replace("fi", "f\u200ci"), font=fc,      # (no "fi" ligature: VT323's drops the i)
                           fill=(150, 230, 160) if not line.startswith("(") else DIM)
                    y += 40
                y += 22
            draw_band(fr, "One time only: the toolkit, Python, the USB driver and the new firmware", "Setup", S - 132)
            frames.append(fr)
        step_at = [int(FPS * (0.6 + 2.2 * j)) for j in range(len(self.SETUP))]
        blank = Image.new("RGB", (S, S), BG)
        self._fade, self._from = 0, None
        for i in range(n):
            j = sum(1 for t in step_at if i >= t)
            fr = frames[j]
            f = min(1.0, (i + 1) / 10, (n - i) / 10)
            self.emit(full=fr if f >= 1 else Image.blend(blank, fr, f))

    def still(self, img, caption, step=None, secs=3.0, box=None):
        """A screenshot (the Secret Base Workshop, say) as a slide above the instruction band: fitted
        and centred; a tall one fills the width and scrolls slowly from top to bottom so its details
        can be read. Each slide fades up from the background and back down to it, never blended into
        whatever came before (15 November: the kit scene showed through the first slide)."""
        from scene import draw_band
        img = img.convert("RGB")
        if box:
            img = img.crop(box)
        H = S - 140
        n, k = self.seconds(secs), 8
        tall = img.height / img.width > (H - 30) / (S - 40) * 1.15
        if tall:
            w = S - 40
            img = img.resize((w, int(img.height * w / img.width)), Image.LANCZOS)
            n = max(n, self.seconds(min(14.0, 2.0 + img.height / 260)))   # time to read as it goes by
        else:
            kk = min((S - 40) / img.width, (H - 30) / img.height)
            img = img.resize((int(img.width * kk), int(img.height * kk)), Image.LANCZOS)
        blank = Image.new("RGB", (S, S), BG)

        def frame_at(i):
            fr = Image.new("RGB", (S, S), BG)
            if tall:
                travel = img.height - (H - 20)
                hold = FPS                                      # a second still at each end
                t = min(1.0, max(0.0, (i - hold) / max(1, n - 2 * hold)))
                t = t * t * (3 - 2 * t)
                y = int(travel * t)
                fr.paste(img.crop((0, y, img.width, y + H - 20)), (20, 10))
            else:
                fr.paste(img, ((S - img.width) // 2, (H - img.height) // 2 + 10))
            draw_band(fr, caption, step, S - 132)
            return fr

        self._fade, self._from = 0, None
        still = None if tall else frame_at(0)
        for i in range(n):
            fr = frame_at(i) if tall else still
            if i < k:
                fr = Image.blend(blank, fr, (i + 1) / k)
            elif i >= n - k:
                fr = Image.blend(fr, blank, (i - (n - k) + 1) / k)
            self.emit(full=fr)

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
                snd = rec.sound(i) if speed <= 1 else None      # (the game's sound, at its own speed)
                if snd:
                    self.sounds.append((self.frames, rec.pcm) + snd)
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
        silent = self.out + ".silent.mp4"
        if self.theme or self.sounds:
            wav = self.out + ".wav"
            self._soundtrack(wav)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", wav, "-c:v", "copy",
                            "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", self.out], check=True)
            os.remove(wav)
            os.remove(silent)
        else:
            os.replace(silent, self.out)
        return self.frames / FPS

    def _soundtrack(self, wav):
        """The music (the theme, looped, faded in and out) under everything, giving way to the game's
        own sound wherever the game plays at its own speed, with short crossfades between them."""
        import numpy as np
        import wave
        rate = 32768
        total = int(self.frames * rate / FPS) + rate
        music = np.zeros((total, 2), np.float32)
        if self.theme:
            loop = np.fromfile(self.theme, dtype="<i2").reshape(-1, 2).astype(np.float32)
            if len(loop) > rate:
                x = rate // 2                                # crossfade the loop's ends
                ramp = np.linspace(0, 1, x)[:, None]
                loop = np.concatenate([loop[x:-x], loop[-x:] * (1 - ramp) + loop[:x] * ramp])
                music = np.resize(loop, (total, 2)) if len(loop) else music
        game = np.zeros((total, 2), np.float32)
        mask = np.zeros(total, np.float32)
        maps = {}
        per = rate / FPS
        # runs of frames shown one after another from one recording: each run's sound joined up as it
        # was recorded and stretched once, smoothly, to the run's length (frame by frame, 1097 samples
        # squeezed into 1092 each time, it warbled: 15 November). A frame whose sound is much longer -
        # frames run unrecorded in between - keeps only its last frame's worth.
        runs, cur = [], []
        for snd in self.sounds:
            if cur and (snd[0] != cur[-1][0] + 1 or snd[1] != cur[-1][1] or snd[2] < cur[-1][2]):
                runs.append(cur)
                cur = []
            cur.append(snd)
        if cur:
            runs.append(cur)
        frame_len = 2 * 548.57
        for run in runs:
            pcm = run[0][1]
            if pcm not in maps:
                maps[pcm] = np.memmap(pcm, dtype="<i2", mode="r").reshape(-1, 2)
            m = maps[pcm]
            parts = []
            for _, _, start, n in run:
                if n > 1.6 * frame_len:
                    start, n = start + n - int(frame_len), int(frame_len)
                parts.append(m[start:start + n])
            src = np.concatenate(parts).astype(np.float32) if parts else np.zeros((0, 2), np.float32)
            a, b = int(run[0][0] * per), int((run[-1][0] + 1) * per)
            b = min(b, total)
            if len(src) < 2 or b - a < 2:
                continue
            x = np.linspace(0, len(src) - 1, b - a)
            seg = np.stack([np.interp(x, np.arange(len(src)), src[:, c]) for c in (0, 1)], axis=1)
            e = min(160, (b - a) // 2)                       # 5 ms fades at a run's ends: no clicks
            ramp = np.linspace(0, 1, e)[:, None]
            seg[:e] *= ramp
            seg[-e:] *= ramp[::-1]
            game[a:b] = seg
            mask[a:b] = 1
        k = int(0.15 * rate)                                 # smooth the switch over 0.15 s
        if k > 1:
            mask = np.convolve(mask, np.ones(k) / k, mode="same").astype(np.float32)
        mix = music * 0.5 * (1 - mask)[:, None] + game * 0.95
        fade = int(1.0 * rate)
        env = np.ones(total, np.float32)
        end = int(self.frames * rate / FPS)
        env[:fade] = np.linspace(0, 1, fade)
        env[max(0, end - fade):end] = np.linspace(1, 0, end - max(0, end - fade))
        env[end:] = 0
        mix = np.clip(mix * env[:, None], -32767, 32767).astype("<i2")
        with wave.open(wav, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(mix.tobytes())
