"""scene.py - animated setup scenes, full screen (1080x1080): sprites from parts.py on a 360x360 art
canvas scaled 3x, moving by keyframes (a pak sliding into a slot, a plug going into a port, a lead
drawing itself across, a power lamp and screen coming on), with labels pointing at the parts, the
terminal running on the laptop's own screen, and the instruction in a band along the bottom.
"""
import math, os
from PIL import Image, ImageDraw, ImageFont

import parts
from pixel import rgb, shade

CW = CH = 360
SCALE = 3
SIZE = CW * SCALE
FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


F_CAP = lambda: font("Jersey10.ttf", 50)
F_LABEL = lambda: font("Jersey10.ttf", 34)
F_TERM = lambda: font("VT323-Regular.ttf", 19)

INK, GOLD, PAPER = (250, 246, 232), (250, 204, 72), (18, 20, 34)


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


class Actor:
    def __init__(self, sprite, x, y, z=0, t_in=0.0, alpha=1.0):
        self.s, self.x, self.y, self.z, self.t_in = sprite, x, y, z, t_in
        self.moves = []                       # (t0, t1, (x0, y0), (x1, y1))
        self.on_at = None                     # the power lamp lights at this time
        self.screen = None                    # fn(t) -> an image for the sprite's screen, or None

    def move(self, t0, t1, frm, to):
        self.moves.append((t0, t1, frm, to))
        return self

    def pos(self, t):
        x, y = self.x, self.y
        for t0, t1, a, b in self.moves:
            if t >= t0:
                k = ease((t - t0) / max(1e-6, t1 - t0))
                x, y = lerp(a[0], b[0], k), lerp(a[1], b[1], k)
        return x, y

    def anchor(self, name, t):
        x, y = self.pos(t)
        a = self.s.anchors[name]
        return x + a[0], y + a[1]

    def visible(self, t):
        return t >= self.t_in


class Cable:
    """A lead between two points (each fixed or an actor's anchor), drawn on from the first end over
    t0..t1, with a plug sprite at each end and optionally a hub in the middle."""
    def __init__(self, a, b, t0, t1, colour, width=2, sag=40, plug_a=None, plug_b=None, hub=None, dangling=None):
        self.a, self.b, self.t0, self.t1 = a, b, t0, t1
        self.colour, self.width, self.sag = colour, width, sag
        self.plug_a, self.plug_b, self.hub, self.dangling = plug_a, plug_b, hub, dangling

    @staticmethod
    def point(p, t):
        if isinstance(p, tuple) and len(p) == 2 and isinstance(p[0], Actor):
            return p[0].anchor(p[1], t)
        return p

    def path(self, t, n=60):
        (x0, y0), (x1, y1) = self.point(self.a, t), self.point(self.b, t)
        # leave each plug upwards, then hang between them
        c0 = (x0, y0 - self.sag)
        c1 = (x1, y1 - self.sag)
        pts = []
        for i in range(n + 1):
            u = i / n
            a, b, c, d = (1 - u) ** 3, 3 * (1 - u) ** 2 * u, 3 * (1 - u) * u * u, u ** 3
            pts.append((a * x0 + b * c0[0] + c * c1[0] + d * x1, a * y0 + b * c0[1] + c * c1[1] + d * y1))
        return pts


class Label:
    def __init__(self, text, target, at, t0, t1=1e9):
        self.text, self.target, self.at, self.t0, self.t1 = text, target, at, t0, t1


class Scene:
    def __init__(self, duration):
        self.duration = duration
        self.actors, self.cables, self.labels, self.captions, self.badges = [], [], [], [], []
        self.terminal = None                 # (actor, fn(t) -> list of lines)

    def add(self, actor):
        self.actors.append(actor)
        return actor

    def caption(self, t, text, step=None):
        self.captions.append((t, text, step))

    def badge(self, t, actor, anchor, text):
        self.badges.append((t, actor, anchor, text))

    # -- drawing -------------------------------------------------------------------------------------
    def background(self):
        img = Image.new("RGBA", (CW, CH))
        d = ImageDraw.Draw(img)
        top, mid = rgb("#1c2340"), rgb("#141a30")
        for y in range(CH):
            k = y / CH
            d.line([(0, y), (CW, y)], fill=tuple(int(lerp(a, b, k)) for a, b in zip(top, mid)) + (255,))
        desk = rgb("#2a2f4f")
        d.rectangle([0, 214, CW, CH], fill=desk + (255,))
        d.line([(0, 214), (CW, 214)], fill=shade(desk, 1.25) + (255,))
        for x in range(0, CW, 4):                     # a faint pixel texture on the desk
            for y in range(218, CH, 6):
                if (x * 7 + y * 3) % 23 == 0:
                    d.point((x, y), fill=shade(desk, 1.1) + (255,))
        return img

    def render(self, t):
        art = self.background()
        d = ImageDraw.Draw(art)
        actors = sorted((a for a in self.actors if a.visible(t)), key=lambda a: a.z)
        # cables behind the parts they plug into (drawn first), plugs on top later
        for c in self.cables:
            if t < c.t0:
                continue
            pts = c.path(t)
            k = ease((t - c.t0) / max(1e-6, c.t1 - c.t0))
            shown = pts[:max(2, int(len(pts) * k))]
            d.line(shown, fill=shade(c.colour, 0.5) + (255,), width=c.width + 2, joint="curve")
            d.line(shown, fill=c.colour + (255,), width=c.width, joint="curve")
            d.line([(x, y - 1) for x, y in shown], fill=shade(c.colour, 1.3) + (255,), width=1)
            c._shown = shown
        for a in actors:
            x, y = a.pos(t)
            art.alpha_composite(a.s.img, (int(round(x)), int(round(y))))
            if a.on_at is not None and t >= a.on_at and "led" in a.s.anchors:
                lx, ly = a.anchor("led", t)
                d.rectangle([lx, ly, lx, ly + 1], fill=(90, 240, 110, 255))
            if a.screen and "screen" in a.s.anchors:
                img = a.screen(t)
                if img is not None:
                    sx, sy, sw, sh = a.s.anchors["screen"]
                    px, py = a.pos(t)
                    art.paste(img.convert("RGBA").resize((sw, sh), Image.BOX), (int(px + sx), int(py + sy)))
        for c in self.cables:                          # plugs and hubs on top
            if t < c.t0 or not getattr(c, "_shown", None):
                continue
            shown = c._shown
            for plug, p in ((c.plug_a, shown[0]), (c.plug_b, shown[-1] if len(shown) == len(c.path(t)) else None)):
                if plug and p:
                    tx, ty = plug.anchors["tip"]
                    art.alpha_composite(plug.img, (int(p[0] - tx), int(p[1] - ty)))
            if c.hub and len(shown) > 30:
                hx, hy = c.path(t)[30]
                art.alpha_composite(c.hub.img, (int(hx - c.hub.size[0] / 2), int(hy - c.hub.size[1] / 2)))
            if c.dangling and len(shown) == len(c.path(t)):
                plug, (dx, dy) = c.dangling
                ex, ey = shown[-1]
                bx, by = ex + dx, ey + dy
                d.line([(ex, ey - 8), (bx, by - plug.size[1])], fill=shade(c.colour, 0.5) + (255,), width=c.width + 2)
                d.line([(ex, ey - 8), (bx, by - plug.size[1])], fill=c.colour + (255,), width=c.width)
                art.alpha_composite(plug.img, (int(bx - plug.size[0] / 2), int(by - plug.size[1])))
                # (plugs at the cable's ends are drawn above)
        big = art.resize((SIZE, SIZE), Image.NEAREST).convert("RGB")
        g = ImageDraw.Draw(big)
        if self.terminal:
            actor, lines_fn = self.terminal
            if actor.visible(t):
                sx, sy, sw, sh = actor.s.anchors["screen"]
                px, py = actor.pos(t)
                X, Y = int((px + sx) * SCALE) + 8, int((py + sy) * SCALE) + 6
                f = F_TERM()
                cols = int((sw * SCALE - 16) / g.textlength("M", font=f))
                rows = []
                for col, line in lines_fn(t):
                    while len(line) > cols:
                        rows.append((col, line[:cols]))
                        line = "  " + line[cols:]
                    rows.append((col, line))
                lh = 19
                fit = (sh * SCALE - 10) // lh
                for i, (col, line) in enumerate(rows[-fit:]):
                    g.text((X, Y + i * lh), line, font=f, fill=col)
        fl = F_LABEL()
        for lb in self.labels:
            if not (lb.t0 <= t < lb.t1):
                continue
            k = ease((t - lb.t0) / 0.35)
            tx, ty = Cable.point(lb.target, t)
            X, Y = tx * SCALE, ty * SCALE
            LX, LY = lb.at[0] * SCALE, lb.at[1] * SCALE
            rows = lb.text.split("\n")
            tw = max(g.textlength(r, font=fl) for r in rows)
            hh = 20 + 17 * (len(rows) - 1)
            LX = min(max(LX, tw / 2 + 16), SIZE - tw / 2 - 16)
            col = tuple(int(lerp(c0, c1, k)) for c0, c1 in zip((40, 40, 60), GOLD))
            if abs(LY - Y) > hh + 4 or abs(LX - X) > tw / 2 + 4:
                g.line([(X, Y), (LX, LY + (hh if LY < Y else -hh))], fill=col, width=3)
                g.rectangle([X - 4, Y - 4, X + 4, Y + 4], fill=col)
            g.rectangle([LX - tw / 2 - 12, LY - hh, LX + tw / 2 + 12, LY + hh], fill=PAPER, outline=col, width=3)
            for j, r in enumerate(rows):
                g.text((LX, LY + 1 - 17 * (len(rows) - 1) + 34 * j), r, font=fl,
                       fill=tuple(int(lerp(40, c, k)) for c in INK), anchor="mm")
        fb = font("Jersey10.ttf", 44)
        for t0, actor, anchor, text in self.badges:
            if t >= t0 and actor.visible(t):
                ax, ay = actor.anchor(anchor, t)
                X, Y = ax * SCALE, ay * SCALE
                g.rectangle([X - 26, Y - 26, X + 26, Y + 26], fill=GOLD, outline=(30, 30, 40), width=4)
                g.text((X, Y + 1), text, font=fb, fill=(30, 30, 40), anchor="mm")
        cap = None
        for t0, text, step in self.captions:
            if t >= t0:
                cap = (text, step)
        if cap:
            draw_band(big, cap[0], cap[1], SIZE - 132)
        return big


def draw_band(img, text, step, y, h=120):
    """The instruction band: a step tag and the words, wrapped to two lines if need be."""
    g = ImageDraw.Draw(img)
    W = img.size[0]
    g.rectangle([0, y, W, y + h], fill=(28, 33, 56))
    g.line([(0, y), (W, y)], fill=(84, 94, 136), width=3)
    g.line([(0, y + h - 2), (W, y + h - 2)], fill=(84, 94, 136), width=3)
    x = 28
    if step:
        ft = font("Jersey10.ttf", 38)
        tw = g.textlength(step, font=ft)
        g.rectangle([x, y + h // 2 - 24, x + tw + 28, y + h // 2 + 24], fill=GOLD)
        g.text((x + 14 + tw / 2, y + h // 2 + 1), step, font=ft, fill=(30, 30, 40), anchor="mm")
        x += tw + 50
    room = W - x - 28
    for size in (52, 48, 44):
        f = font("Jersey10.ttf", size)
        if g.textlength(text, font=f) <= room:
            g.text((x, y + h // 2 + 2), text, font=f, fill=INK, anchor="lm")
            return
    f = font("Jersey10.ttf", 42)
    words, first = text.split(), ""
    while words and g.textlength((first + " " + words[0]).strip(), font=f) <= room:
        first = (first + " " + words.pop(0)).strip()
    g.text((x, y + h // 2 - 19), first, font=f, fill=INK, anchor="lm")
    g.text((x, y + h // 2 + 21), " ".join(words), font=f, fill=INK, anchor="lm")
