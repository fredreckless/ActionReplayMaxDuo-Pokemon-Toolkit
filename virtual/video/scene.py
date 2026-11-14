"""scene.py - animated setup scenes, full screen (1080x1080): sprites from parts.py on a 360x360 art
canvas scaled 3x, moving by keyframes (a pak sliding into a slot, a GBA turned over, a lead drawing
itself across and plugging in, a power lamp and screen coming on), labels pointing at the parts, the
terminal running on the laptop's own screen, and the instruction in a band along the bottom.

Cables are smooth splines through waypoints: each leaves its plug straight out of the port, then
flows through the waypoints, with ferrite beads, a hub or a junction block riding along it and,
for a split cable, a branch from the junction.
"""
import math, os
from PIL import Image, ImageDraw, ImageFont

from pixel import rgb, shade

CW = CH = 360
SCALE = 3
SIZE = CW * SCALE
FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_fonts = {}


def font(name, size):
    if (name, size) not in _fonts:
        _fonts[name, size] = ImageFont.truetype(os.path.join(FONTS, name), size)
    return _fonts[name, size]


INK, GOLD, PAPER = (250, 246, 232), (250, 204, 72), (18, 20, 34)


def ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


class Actor:
    def __init__(self, sprite, x, y, z=0, t_in=0.0, t_out=1e9):
        self.s, self.x, self.y, self.z, self.t_in, self.t_out = sprite, x, y, z, t_in, t_out
        self.moves = []                       # (t0, t1, (x0, y0), (x1, y1))
        self.squash = None                    # (t0, t1, from, to): horizontal scale, for a flip
        self.on_at = None
        self.screen = None

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
        return self.t_in <= t < self.t_out


def catmull(points, step=0.7):
    """A smooth curve through the points (centripetal Catmull-Rom), sampled about every step pixels."""
    if len(points) < 2:
        return list(points)
    p = [points[0]] + list(points) + [points[-1]]
    out = []
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]

        def tj(ti, a, b):
            return ti + max(1e-3, math.hypot(b[0] - a[0], b[1] - a[1])) ** 0.5
        t0 = 0.0
        t1 = tj(t0, p0, p1)
        t2 = tj(t1, p1, p2)
        t3 = tj(t2, p2, p3)
        n = max(2, int(math.hypot(p2[0] - p1[0], p2[1] - p1[1]) / step))
        for k in range(n):
            t = t1 + (t2 - t1) * k / n

            def L(a, b, ta, tb):
                if tb - ta < 1e-9:
                    return a
                return ((tb - t) / (tb - ta) * a[0] + (t - ta) / (tb - ta) * b[0],
                        (tb - t) / (tb - ta) * a[1] + (t - ta) / (tb - ta) * b[1])
            a1, a2, a3 = L(p0, p1, t0, t1), L(p1, p2, t1, t2), L(p2, p3, t2, t3)
            b1, b2 = L(a1, a2, t0, t2), L(a2, a3, t1, t3)
            out.append(L(b1, b2, t1, t2))
    out.append(points[-1])
    return out


class Cable:
    """A lead from end a to end b through via points. An end is a fixed point, or (actor, anchor) with
    a plug sprite pushed into that port (the plug points down into it; the lead leaves upwards).
    beads: [(fraction along, sprite)] for ferrites, a hub, a junction. branch: (fraction, [via...],
    plug sprite) for a split end, which ends lying loose."""
    def __init__(self, a, b, via, t0, t1, colour, width=3, plug_a=None, plug_b=None, beads=(), branch=None,
                 rise=12):
        self.a, self.b, self.via, self.t0, self.t1 = a, b, list(via), t0, t1
        self.colour, self.width, self.plug_a, self.plug_b = colour, width, plug_a, plug_b
        self.beads, self.branch, self.rise = list(beads), branch, rise

    @staticmethod
    def point(p, t):
        if isinstance(p, tuple) and len(p) == 2 and isinstance(p[0], Actor):
            return p[0].anchor(p[1], t)
        if isinstance(p, tuple) and len(p) == 2 and isinstance(p[0], Cable):
            pts = p[0].path(t)
            return pts[int((len(pts) - 1) * p[1])]
        return p

    def ends(self, t):
        out = []
        for end, plug in ((self.a, self.plug_a), (self.b, self.plug_b)):
            x, y = self.point(end, t)
            if plug is not None:
                tx, ty = plug.anchors["tip"]
                tail = (x, y - ty)                      # the plug's top, where the lead leaves it
                out.append(((x, y), tail, (tail[0], tail[1] - self.rise)))
            else:
                out.append(((x, y), (x, y), (x, y)))
        return out

    def path(self, t):
        (pa, ta, ua), (pb, tb, ub) = self.ends(t)
        return catmull([ta, ua] + self.via + [ub, tb])


class Label:
    def __init__(self, text, target, at, t0, t1=1e9):
        self.text, self.target, self.at, self.t0, self.t1 = text, target, at, t0, t1


def draw_lead(d, pts, colour, width):
    if len(pts) < 2:
        return
    ipts = [(round(x), round(y)) for x, y in pts]
    d.line(ipts, fill=shade(colour, 0.45) + (255,), width=width + 2, joint="curve")
    d.line(ipts, fill=colour + (255,), width=width, joint="curve")
    hl = shade(colour, 1.45) + (255,)
    for (x0, y0), (x1, y1) in zip(ipts[::2], ipts[2::2]):
        dx, dy = x1 - x0, y1 - y0
        if dx * dx + dy * dy == 0:
            continue
        nx, ny = (-dy, dx) if dx >= 0 else (dy, -dx)        # the side facing up/left
        if ny > 0:
            nx, ny = -nx, -ny
        m = math.hypot(nx, ny)
        o = (width - 1) / 2
        d.point((round(x0 + nx / m * o), round(y0 + ny / m * o)), fill=hl)


class Scene:
    def __init__(self, duration):
        self.duration = duration
        self.actors, self.cables, self.labels, self.captions, self.badges = [], [], [], [], []
        self.terminal = None

    def add(self, actor):
        self.actors.append(actor)
        return actor

    def caption(self, t, text, step=None):
        self.captions.append((t, text, step))

    def badge(self, t, actor, anchor, text):
        self.badges.append((t, actor, anchor, text))

    def background(self):
        if hasattr(self, "_bg"):
            return self._bg.copy()
        img = Image.new("RGBA", (CW, CH))
        d = ImageDraw.Draw(img)
        top, low = rgb("#232a48"), rgb("#1a2038")
        for y in range(CH):
            d.line([(0, y), (CW, y)], fill=tuple(int(lerp(a, b, y / CH)) for a, b in zip(top, low)) + (255,))
        for x in range(0, CW, 3):                     # a woven desk mat
            for y in range(0, CH, 3):
                if (x * 7 + y * 13) % 29 == 0:
                    d.point((x, y), fill=shade(top, 1.12) + (255,))
        self._bg = img
        return img.copy()

    def _draw_cable(self, art, d, c, t, plugs_only=False):
        pts = c.path(t)
        k = ease((t - c.t0) / max(1e-6, c.t1 - c.t0))
        n = max(2, int(len(pts) * k))
        done = n >= len(pts)
        if not plugs_only:
            draw_lead(d, pts[:n], c.colour, c.width)
            if c.branch and done:
                f, via, plug = c.branch
                j = pts[int(len(pts) * f)]
                bpts = catmull([j] + via)
                draw_lead(d, bpts, c.colour, c.width)
            return
        # plugs and beads on top of the leads
        for frac, spr in c.beads:
            i = int(len(pts) * frac)
            if i < n:
                x, y = pts[i]
                art.alpha_composite(spr.img, (int(x - spr.size[0] / 2), int(y - spr.size[1] / 2)))
        (pa, ta, _), (pb, tb, _) = c.ends(t)
        if c.plug_a is not None:
            tx, ty = c.plug_a.anchors["tip"]
            art.alpha_composite(c.plug_a.img, (int(pa[0] - tx), int(pa[1] - ty)))
        if c.plug_b is not None:
            tx, ty = c.plug_b.anchors["tip"]
            x, y = (pb[0], pb[1]) if done else (pts[n - 1][0], pts[n - 1][1] + ty)
            if done or n > 3:
                art.alpha_composite(c.plug_b.img, (int(x - tx), int(y - ty)))
        if c.branch and done:
            f, via, plug = c.branch
            x, y = via[-1]
            tx, ty = plug.anchors["tail"]
            art.alpha_composite(plug.img, (int(x - tx), int(y - ty)))

    def render(self, t):
        art = self.background()
        d = ImageDraw.Draw(art)
        live = [c for c in self.cables if t >= c.t0]
        for c in live:
            self._draw_cable(art, d, c, t)
        for a in sorted((a for a in self.actors if a.visible(t)), key=lambda a: a.z):
            x, y = a.pos(t)
            img = a.s.img
            if a.squash:
                t0, t1, f0, f1 = a.squash
                k = lerp(f0, f1, ease((t - t0) / max(1e-6, t1 - t0))) if t >= t0 else f0
                w = max(1, int(img.size[0] * k))
                img = img.resize((w, img.size[1]), Image.NEAREST)
                x += (a.s.size[0] - w) / 2
            art.alpha_composite(img, (int(round(x)), int(round(y))))
            if a.on_at is not None and t >= a.on_at and "led" in a.s.anchors:
                lx, ly = a.anchor("led", t)
                d.rectangle([lx, ly, lx + 1, ly], fill=(110, 250, 120, 255))
            if a.screen and "screen" in a.s.anchors:
                sc = a.screen(t)
                if sc is not None:
                    sx, sy, sw, sh = a.s.anchors["screen"]
                    art.paste(sc.convert("RGBA").resize((sw, sh), Image.BOX), (int(x + sx), int(y + sy)))
        for c in live:
            self._draw_cable(art, d, c, t, plugs_only=True)
        big = art.resize((SIZE, SIZE), Image.NEAREST).convert("RGB")
        g = ImageDraw.Draw(big)
        if self.terminal:
            actor, lines_fn = self.terminal
            if actor.visible(t):
                sx, sy, sw, sh = actor.s.anchors["screen"]
                px, py = actor.pos(t)
                X, Y = int((px + sx) * SCALE) + 8, int((py + sy) * SCALE) + 6
                f = font("VT323-Regular.ttf", 19)
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
        fl = font("Jersey10.ttf", 34)
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
                X, Y = ax * SCALE + 40, ay * SCALE - 30
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
