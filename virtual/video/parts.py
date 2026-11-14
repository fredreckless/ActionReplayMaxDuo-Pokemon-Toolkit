"""parts.py - every component of the setup as a pixel sprite with anchors, drawn to the real parts'
proportions (millimetres from their published sizes, at 0.75 art pixels per millimetre):

    GBA (AGB-001, 144.5 x 82 mm)        gba(colourway)          anchors: ext, slot, screen, led
    Game Pak (57 x 35 mm)               game_pak(game)          anchors: top, edge
    Action Replay MAX DUO               duo()                   anchors: usb, edge, slot
    laptop                              laptop()                anchors: usb, screen
    USB lead, Mini-B to A               usb_mini_b(), usb_a()   anchors: tip, tail
    GBA Game Link Cable (AGB-005)       agb005_plug(master)     the small purple plug is the master end
                                        agb005_hub()
    Universal Game Link Cable (MGB-010) mgb010_plug(kind)       "small" (Pocket/Color size), "large"

No logos or label art: each game's pak is its own colour with its name in plain letters.
"""
from pixel import Sprite, rgb, shade

COLOURWAYS = {
    "indigo": dict(body=rgb("#4b40a8"), light=rgb("#6e64cc"), dark=rgb("#2e2672"), btn=rgb("#9089cc"),
                   btnd=rgb("#5d55a0")),
    "glacier": dict(body=rgb("#8fa3d6"), light=rgb("#b7c6ec"), dark=rgb("#5d6fa8"), btn=rgb("#d9e0f4"),
                    btnd=rgb("#8a97c4")),
    "orange": dict(body=rgb("#e57a2e"), light=rgb("#f6a35c"), dark=rgb("#a34d16"), btn=rgb("#f4d2b0"),
                   btnd=rgb("#c0875a")),
    "black": dict(body=rgb("#34343c"), light=rgb("#55555f"), dark=rgb("#1e1e24"), btn=rgb("#6c6c78"),
                  btnd=rgb("#45454e")),
}

GAMES = {   # (label colour, name as printed in plain letters)
    "ruby": (rgb("#c42a35"), "RUBY"), "sapphire": (rgb("#2c55c0"), "SAPPHIRE"),
    "emerald": (rgb("#1f9a5a"), "EMERALD"), "firered": (rgb("#e05a26"), "FIRERED"),
    "leafgreen": (rgb("#6cb83e"), "LEAFGREEN"), "other": (rgb("#6d7b8f"), "ANY GAME"),
}
GREY_PAK = rgb("#8e8f98")
SILVER = rgb("#bfc5cf")
INK = rgb("#1b1a26")


def gba(colourway="indigo"):
    """The front of an AGB-001: a wide body with round grips, the screen in its dark surround, the
    d-pad, A and B, START and SELECT, the power lamp and the speaker. The cartridge slot and the EXT
    (link) port are on the top edge."""
    c = COLOURWAYS[colourway]
    W, H = 108, 62
    s = Sprite(W, H + 6)
    top = 6                                  # room above for the shoulder buttons
    # shoulder buttons (L, R) behind the body's top corners
    for x0 in (8, W - 30):
        s.rrect(x0, top - 4, x0 + 21, top + 8, 4, c["dark"])
        s.hline(x0 + 3, x0 + 18, top - 3, shade(c["dark"], 1.3))
    # body: round grips joined by a straight top edge and a gently bowed bottom
    s.rrect(0, top, W - 1, H + top - 1, 26, c["body"])
    s.rrect(14, top, W - 15, H + top - 3, 8, c["body"])
    s.region_light((0, top, W - 1, H + top - 1), c["light"], c["dark"], depth=2)
    # face bevel: a faint line inside the edge
    # screen surround (dark, glossy) and the screen
    s.rrect(31, top + 5, W - 32, top + 41, 4, rgb("#2a2933"))
    s.hline(34, W - 35, top + 6, rgb("#45434f"))
    sx, sy, sw, sh = 36, top + 9, 36, 24      # 3:2 like the real 240x160 screen
    s.rect(sx, sy, sx + sw - 1, sy + sh - 1, rgb("#3c4638"))
    s.anchors["screen"] = (sx, sy, sw, sh)
    s.hline(42, W - 43, top + 37, rgb("#4b4957"))          # (where the console's name is printed)
    s.px(33, top + 13, rgb("#5a2a2a"))                   # the power lamp, off
    s.anchors["led"] = (33, top + 13)
    # d-pad
    dx, dy = 15, top + 24
    for (x0, y0, x1, y1) in ((dx - 6, dy - 2, dx + 6, dy + 2), (dx - 2, dy - 6, dx + 2, dy + 6)):
        s.rect(x0, y0, x1, y1, rgb("#26252c"))
    s.hline(dx - 5, dx + 5, dy - 2, rgb("#45444e"))
    s.vline(dx - 2, dy - 5, dy + 5, rgb("#3a3942"))
    s.px(dx, dy, rgb("#1a1a20"))
    # A (upper right) and B
    for bx, by in ((W - 13, top + 21), (W - 23, top + 28)):
        s.ellipse(bx - 4, by - 4, bx + 4, by + 4, c["btnd"])
        s.ellipse(bx - 4, by - 4, bx + 4, by + 3, c["btn"])
        s.px(bx - 2, by - 2, shade(c["btn"], 1.4))
    # START, SELECT below the d-pad
    for by in (top + 38, top + 44):
        s.rrect(10, by, 16, by + 3, 1, c["btnd"])
        s.hline(11, 15, by, shade(c["btnd"], 1.3))
    # speaker holes, lower right
    for i in range(5):
        for j in range(3):
            s.px(W - 26 + i * 3 + j, top + 46 - j * 2 + i, c["dark"])
    # top edge: the EXT port (centre) and the slot behind it
    s.rect(W // 2 - 6, top, W // 2 + 5, top + 1, rgb("#18171f"))
    s.anchors["ext"] = (W // 2, top)
    s.anchors["slot"] = (W // 2, top)          # a pak stands up out of the slot, behind
    s.outline()
    return s


def game_pak(game, back=False):
    """A Game Boy Advance Game Pak from the front: grey, the label inset, the gripping ridges along the
    top, the contacts' edge at the bottom (hidden in a slot)."""
    W, H = 43, 26
    lab, name = GAMES[game]
    s = Sprite(W, H)
    s.rrect(0, 0, W - 1, H - 1, 3, GREY_PAK)
    s.rect(0, H - 4, W - 1, H - 1, GREY_PAK)
    for x in range(4, W - 4, 3):                         # ridges along the top
        s.vline(x, 1, 3, shade(GREY_PAK, 0.8))
    if back:
        s.rect(6, 8, W - 7, H - 6, shade(GREY_PAK, 0.9))
    else:
        s.rrect(3, 6, W - 4, H - 4, 2, lab)
        s.rect(5, 7, W - 6, 8, shade(lab, 1.25))
        s.rect(5, H - 6, W - 6, H - 5, shade(lab, 0.75))
        tw = len(name) * 4 - 1
        s.text((W - tw) // 2, 12, name, rgb("#fff6e8"), None)
    s.region_light((0, 0, W - 1, H - 1), shade(GREY_PAK, 1.3), shade(GREY_PAK, 0.7))
    s.anchors["top"] = (W // 2, 0)
    s.anchors["edge"] = (W // 2, H - 1)
    s.outline()
    return s


def duo():
    """The Action Replay MAX DUO, front: a silver cartridge, taller than a Game Pak. Along its top edge
    (as on the board): the button, the mini-USB socket and the slide switch; across its face, the clear
    pass-through slot that a GBA Game Pak plugs into (the DUO needs a cartridge fitted to start)."""
    W, H = 48, 44
    s = Sprite(W, H + 4)
    t = 4
    s.rect(9, 0, 13, t, rgb("#2b2b33"))                  # button
    s.rect(21, 1, 27, t, rgb("#c9a640"))                 # mini-USB socket (gold, as on the board)
    s.rect(22, 2, 26, 3, rgb("#5a4a1a"))
    s.rect(34, 1, 41, t, rgb("#8a8a90"))                 # slide switch
    s.rect(35, 0, 37, 1, rgb("#2b2b33"))
    s.rrect(0, t, W - 1, H + t - 1, 4, SILVER)
    s.region_light((0, t, W - 1, H + t - 1), shade(SILVER, 1.35), shade(SILVER, 0.7))
    s.rect(3, t + 6, W - 4, t + 18, rgb("#d8e2ea"))     # the clear slot, its contacts showing
    for x in range(5, W - 5, 2):
        s.vline(x, t + 8, t + 16, rgb("#b0b8c0"))
    s.rect(3, t + 6, W - 4, t + 6, rgb("#f4f8fb"))
    s.rrect(8, t + 23, W - 9, t + 35, 2, rgb("#30343e"))   # the label panel
    s.text(W // 2 - 5, t + 27, "DUO", rgb("#e8eef6"), None)
    s.anchors["usb"] = (24, 1)
    s.anchors["slot"] = (W // 2, t + 6)
    s.anchors["edge"] = (W // 2, H + t - 1)
    s.outline()
    return s


def laptop(left_usb=False):
    """A laptop, open, with its screen free for the terminal, and a USB-A socket on its side."""
    W, H = 156, 104
    s = Sprite(W, H)
    s.rrect(10, 0, W - 11, 84, 3, rgb("#3b3f4a"))
    s.hline(13, W - 14, 1, rgb("#555a66"))
    s.rect(14, 4, W - 15, 80, rgb("#0c0f14"))
    s.anchors["screen"] = (14, 4, W - 28, 77)
    s.poly([(2, 95), (10, 85), (W - 11, 85), (W - 3, 95)], rgb("#4b505c"))
    s.rect(2, 95, W - 3, 99, rgb("#2d3139"))
    for r in range(3):
        for k in range(19):
            s.rect(16 + k * 6 + r, 87 + r * 3, 19 + k * 6 + r, 87 + r * 3, rgb("#363a44"))
    s.rect(60 + 0, 96, W - 61, 97, rgb("#3d424d"))
    if left_usb:
        s.rect(3, 96, 5, 98, rgb("#15161b"))
        s.anchors["usb"] = (3, 97)
    else:
        s.rect(W - 6, 96, W - 4, 98, rgb("#15161b"))
        s.anchors["usb"] = (W - 4, 97)
    s.outline()
    return s


def usb_mini_b():
    """The DUO's end of its lead: a Mini-B plug (seen from the side), the cable leaving upwards."""
    s = Sprite(9, 12)
    s.rrect(0, 0, 8, 7, 2, rgb("#2b2c33"))
    s.rect(2, 8, 6, 11, rgb("#c0c4cc"))
    s.anchors["tip"] = (4, 11)
    s.anchors["tail"] = (4, 0)
    s.outline()
    return s


def usb_a():
    s = Sprite(14, 9)
    s.rrect(0, 0, 9, 8, 2, rgb("#2b2c33"))
    s.rect(9, 1, 13, 7, rgb("#c0c4cc"))
    s.anchors["tip"] = (13, 4)
    s.anchors["tail"] = (0, 4)
    s.outline()
    return s


def agb005_plug(master):
    """An AGB-005 plug. The master end is the small purple one; the other end's plug is grey and larger."""
    if master:
        s = Sprite(9, 11)
        col = rgb("#8a58cf")
        s.rrect(0, 0, 8, 7, 2, col)
        s.rect(2, 8, 6, 10, rgb("#5d3d94"))
    else:
        s = Sprite(12, 12)
        col = rgb("#9c9ea8")
        s.rrect(0, 0, 11, 8, 2, col)
        s.rect(3, 9, 8, 11, rgb("#6c6e78"))
    s.region_light((0, 0, s.size[0] - 1, s.size[1] - 1), shade(col, 1.3), shade(col, 0.7))
    s.anchors["tip"] = (s.size[0] // 2, s.size[1] - 1)
    s.anchors["tail"] = (s.size[0] // 2, 0)
    s.outline()
    return s


def agb005_hub():
    s = Sprite(16, 10)
    col = rgb("#9c9ea8")
    s.rrect(0, 0, 15, 9, 2, col)
    s.rect(4, 3, 11, 6, rgb("#2a2a32"))
    s.region_light((0, 0, 15, 9), shade(col, 1.3), shade(col, 0.7))
    s.anchors["left"] = (0, 5)
    s.anchors["right"] = (15, 5)
    s.outline()
    return s


def mgb010_plug(kind="small"):
    """MGB-010, the Universal Game Link Cable: a small (Pocket/Color) plug at one end; the other end
    splits into a small plug and a large original Game Boy plug (only one is used)."""
    col = rgb("#8f9099")
    if kind == "small":
        s = Sprite(12, 13)
        s.rrect(0, 0, 11, 9, 2, col)
        for y in (2, 4, 6):
            s.hline(2, 9, y, shade(col, 0.8))
        s.rect(3, 10, 8, 12, rgb("#5f6068"))
    else:
        s = Sprite(17, 15)
        s.rrect(0, 0, 16, 11, 2, col)
        for y in (2, 4, 6, 8):
            s.hline(2, 14, y, shade(col, 0.8))
        s.rect(4, 12, 12, 14, rgb("#5f6068"))
    s.region_light((0, 0, s.size[0] - 1, s.size[1] - 1), shade(col, 1.3), shade(col, 0.7))
    s.anchors["tip"] = (s.size[0] // 2, s.size[1] - 1)
    s.anchors["tail"] = (s.size[0] // 2, 0)
    s.outline()
    return s


def sheet(path, scale=4):
    """Every sprite on one sheet, to look at."""
    from PIL import Image
    items = [gba("indigo"), gba("glacier"), duo(), laptop()] + [game_pak(g) for g in GAMES] + \
        [usb_mini_b(), usb_a(), agb005_plug(True), agb005_plug(False), agb005_hub(), mgb010_plug("small"),
         mgb010_plug("large")]
    W = 520
    x = y = 4
    rowh = 0
    pos = []
    for it in items:
        w, h = it.size
        if x + w > W:
            x, y = 4, y + rowh + 6
            rowh = 0
        pos.append((x, y))
        x += w + 6
        rowh = max(rowh, h)
    img = Image.new("RGBA", (W, y + rowh + 4), (36, 42, 66, 255))
    for it, p in zip(items, pos):
        img.alpha_composite(it.img, p)
    img.resize((img.size[0] * scale, img.size[1] * scale), Image.NEAREST).save(path)


if __name__ == "__main__":
    import sys
    sheet(sys.argv[1] if len(sys.argv) > 1 else "/tmp/sheet.png")
