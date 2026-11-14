"""pixel.py - drawing pixel-art sprites in code: no anti-aliasing, a palette per part, and the finishing
passes that make shapes read as pixel art (a dark selective outline, a light rim along the top-left
edges and a shadow along the bottom-right ones).

A Sprite is an RGBA image at native size (one pixel = one art pixel) with named anchor points, such
as where a link plug goes in or where a screen sits, so scenes can join parts up and animate them.
"""
from PIL import Image, ImageDraw


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def shade(c, f):
    """f < 1 darker (towards a cool shadow), f > 1 lighter (towards a warm highlight)."""
    if f < 1:
        return tuple(int(v * f + (s * (1 - f) * 0.25)) for v, s in zip(c, (40, 30, 80)))
    return tuple(min(255, int(v + (255 - v) * (f - 1))) for v in c)


class Sprite:
    def __init__(self, w, h):
        self.img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        self.anchors = {}

    @property
    def size(self):
        return self.img.size

    # -- shapes (all aliased) ------------------------------------------------------------------------
    def rect(self, x0, y0, x1, y1, c):
        self.d.rectangle([x0, y0, x1, y1], fill=c + (255,) if len(c) == 3 else c)

    def rrect(self, x0, y0, x1, y1, r, c):
        self.d.rounded_rectangle([x0, y0, x1, y1], r, fill=c + (255,))

    def ellipse(self, x0, y0, x1, y1, c):
        self.d.ellipse([x0, y0, x1, y1], fill=c + (255,))

    def poly(self, pts, c):
        self.d.polygon(pts, fill=c + (255,))

    def line(self, pts, c, w=1):
        self.d.line(pts, fill=c + (255,), width=w)

    def px(self, x, y, c):
        if 0 <= x < self.size[0] and 0 <= y < self.size[1]:
            self.img.putpixel((x, y), c + (255,))

    def hline(self, x0, x1, y, c):
        self.line([(x0, y), (x1, y)], c)

    def vline(self, x, y0, y1, c):
        self.line([(x, y0), (x, y1)], c)

    def text(self, x, y, s, c, font):
        """Tiny lettering from a glyph table (TINY) or a pixel font, unblurred."""
        for ch in s:
            g = TINY.get(ch.upper())
            if g is None:
                x += 4
                continue
            for j, row in enumerate(g):
                for i, b in enumerate(row):
                    if b == "#":
                        self.px(x + i, y + j, c)
            x += len(g[0]) + 1

    # -- finishing passes ------------------------------------------------------------------------------
    def region_light(self, box, light, dark, depth=1):
        """Within box, a highlight along the top and left inner edges of opaque pixels and a shadow along
        the bottom and right ones (light from the top left)."""
        x0, y0, x1, y1 = box
        a = self.img.load()
        src = self.img.copy().load()
        w, h = self.size
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if src[x, y][3] == 0:
                    continue

                def empty(xx, yy):
                    return not (x0 <= xx <= x1 and y0 <= yy <= y1) or src[xx, yy][3] == 0
                for k in range(1, depth + 1):
                    if empty(x, y - k) or empty(x - k, y):
                        a[x, y] = light + (255,)
                        break
                    if empty(x, y + k) or empty(x + k, y):
                        a[x, y] = dark + (255,)
                        break

    def outline(self, colour=(24, 20, 36), sel=True):
        """A 1-pixel outline outside the silhouette. sel: each outline pixel darkened from its neighbour
        (selective outline), which reads softer than flat black."""
        w, h = self.size
        src = self.img.copy().load()
        out = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
        out.paste(self.img, (1, 1))
        o = out.load()
        for y in range(h + 2):
            for x in range(w + 2):
                if o[x, y][3]:
                    continue
                nb = [src[x - 1 + dx, y - 1 + dy] for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
                      if 0 <= x - 1 + dx < w and 0 <= y - 1 + dy < h and src[x - 1 + dx, y - 1 + dy][3]]
                if nb:
                    if sel:
                        c = nb[0][:3]
                        o[x, y] = tuple(int(v * 0.3 + k * 0.7) for v, k in zip(c, colour)) + (255,)
                    else:
                        o[x, y] = colour + (255,)
        self.img = out
        self.d = ImageDraw.Draw(self.img)
        self.anchors = {k: (v[0] + 1, v[1] + 1) + tuple(v[2:]) for k, v in self.anchors.items()}
        return self


# 3x5 lettering for printed text on parts (model numbers, P1/P2 marks)
TINY = {
    "A": ["###", "#.#", "###", "#.#", "#.#"], "B": ["##.", "#.#", "##.", "#.#", "##."],
    "C": ["###", "#..", "#..", "#..", "###"], "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "E": ["###", "#..", "##.", "#..", "###"], "F": ["###", "#..", "##.", "#..", "#.."],
    "G": ["###", "#..", "#.#", "#.#", "###"], "H": ["#.#", "#.#", "###", "#.#", "#.#"],
    "I": ["###", ".#.", ".#.", ".#.", "###"], "K": ["#.#", "#.#", "##.", "#.#", "#.#"],
    "L": ["#..", "#..", "#..", "#..", "###"], "M": ["#.#", "###", "###", "#.#", "#.#"],
    "N": ["##.", "#.#", "#.#", "#.#", "#.#"], "O": ["###", "#.#", "#.#", "#.#", "###"],
    "P": ["###", "#.#", "###", "#..", "#.."], "R": ["##.", "#.#", "##.", "#.#", "#.#"],
    "S": ["###", "#..", "###", "..#", "###"], "T": ["###", ".#.", ".#.", ".#.", ".#."],
    "U": ["#.#", "#.#", "#.#", "#.#", "###"], "V": ["#.#", "#.#", "#.#", "#.#", ".#."],
    "W": ["#.#", "#.#", "###", "###", "#.#"], "X": ["#.#", "#.#", ".#.", "#.#", "#.#"],
    "Y": ["#.#", "#.#", ".#.", ".#.", ".#."], "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"], "2": ["###", "..#", "###", "#..", "###"],
    "3": ["###", "..#", ".##", "..#", "###"], "4": ["#.#", "#.#", "###", "..#", "..#"],
    "5": ["###", "#..", "###", "..#", "###"], "6": ["###", "#..", "###", "#.#", "###"],
    "8": ["###", "#.#", "###", "#.#", "###"], "-": ["...", "...", "###", "...", "..."],
    " ": ["..", "..", "..", "..", ".."],
}
