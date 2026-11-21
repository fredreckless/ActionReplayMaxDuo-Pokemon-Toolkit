"""parts.py - every component as a pixel sprite with anchors, drawn from reference photos (Fred's own
setup and product photos) at about 0.83 art pixels per millimetre:

    gba(colourway)          AGB-001 front: the colour face on a grey shell, grey shoulder buttons, the
                            black screen surround, light d-pad and round A/B, START/SELECT in labelled
                            recesses, six slanted speaker slots, the POWER lamp right of the screen;
                            the EXT (link) port on the top edge, right of centre. Anchors: ext, slot,
                            screen, led
    gba_back(colourway)     its back, for fitting a cartridge into the DUO
    duo()                   Action Replay MAX DUO from the front, as it stands above the GBA's slot:
                            a wide silver base with two screws, a narrower block with "DS" moulded in,
                            and on top the AR switch (left), the mini-USB socket and the AR button
    duo_back()              its other face (with "GBA" moulded in) and the slot a cartridge plugs
                            into, lying flat against the GBA's back
    game_pak(game)          a Game Pak in its translucent colour, the label with the name in plain letters
    laptop()                a laptop; its screen is the terminal
    plugs: usb_a(), usb_mini_b(), link_plug(style) for "gba_purple" (AGB-005 master end), "gba_grey",
           "gbc_black" (MGB-010's small plugs), "dmg_black" (MGB-010's wide original Game Boy plug)
    agb005_hub(), mgb010_junction(), ferrite(colour)

No logos or label art.
"""
from pixel import Sprite, rgb, shade, TINY

TINY_W = {k: v[0] for k, v in TINY.items()}

COLOURWAYS = {
    "indigo": dict(face=rgb("#4f47b0"), bump=rgb("#c9cbd3"), btn=rgb("#dfe1e8"), dpad=rgb("#dfe1e8")),
    "glacier": dict(face=rgb("#6fb6e6"), bump=rgb("#b4dcf4"), btn=rgb("#4f9fd8"), dpad=rgb("#4f9fd8")),
}
GAMES = {   # translucent shell colour, name in plain letters
    "ruby": (rgb("#c2262e"), "RUBY"), "sapphire": (rgb("#2850c4"), "SAPPHIRE"),
    "emerald": (rgb("#1e9a48"), "EMERALD"), "firered": (rgb("#e0401e"), "FIRERED"),
    "leafgreen": (rgb("#3fae3c"), "LEAFGREEN"), "other": (rgb("#8a8c96"), "ANY GAME"),
}
SILVER = rgb("#c3c8d0")
BLACK = rgb("#26262c")


# Measured from the reference drawings (refs/front top bottom back views.jpg, 1.88 px/mm, and
# refs/cartridge front view.PNG, 8.2 px/mm) against the AGB-001's 144.5 x 82 x 24.5 mm and a Game
# Pak's 57.5 x 35 mm, at K = 0.83 art pixels per millimetre: the GBA is 120 x 68, a Game Pak 48 x 29.
K = 0.83
# the front's outline, row by row (x from, x to): the reference's silhouette scaled to 120 x 68
GBA_ROWS = [(31, 91), (30, 92), (21, 98), (16, 102), (12, 107), (9, 110), (6, 112), (5, 113), (5, 113),
            (5, 113), (5, 113), (5, 114), (5, 114), (5, 114), (4, 115), (4, 115), (4, 115), (3, 115),
            (3, 116), (3, 116), (3, 116), (3, 117), (3, 117), (2, 117), (2, 117), (2, 117), (2, 117),
            (2, 117), (1, 118), (1, 118), (1, 118), (1, 118), (1, 118), (1, 118), (1, 118)] + \
           [(1, 119)] * 15 + \
           [(1, 118), (2, 118), (2, 118), (3, 117), (4, 116), (5, 116), (6, 114), (7, 113), (9, 112),
            (11, 109), (15, 104), (19, 100), (23, 97), (26, 95), (27, 92), (30, 90), (33, 85), (40, 78)]
# the face's own outline at the top (the shoulder bumpers show outside it, rows 2 to 8)
GBA_FACE_TOP = [(31, 91), (30, 92), (26, 95), (24, 96), (22, 99), (17, 102), (10, 106), (8, 109), (7, 110)]
GBA_W, GBA_H, GBA_TOP = 120, 68, 3
GBA_EXT_X = 68          # the EXT port: 81.5 mm from the left of the front, 9 mm right of centre
GBA_SLOT = (35, 85)     # the cartridge slot: 43 to 103 mm


def _shell(s, rows, top, body, mirror=False):
    for y, (a, b) in enumerate(rows):
        if mirror:
            a, b = GBA_W - 1 - b, GBA_W - 1 - a
        s.hline(a, b, top + y, body)


def gba(colourway="indigo"):
    c = COLOURWAYS[colourway]
    W, H, top = GBA_W, GBA_H, GBA_TOP
    face = c["face"]
    s = Sprite(W, H + top)
    _shell(s, GBA_ROWS, top, c["bump"])                    # the shoulder bumpers show at the top corners
    _shell(s, GBA_FACE_TOP + GBA_ROWS[len(GBA_FACE_TOP):], top, face)
    s.region_light((0, 0, W - 1, top + H - 1), shade(face, 1.22), shade(face, 0.72))
    s.rrect(53, top + 3, 70, top + 5, 1, shade(face, 0.8))      # the moulded maker's name (left blank)
    # the black screen surround (35.5 to 110.5 mm, 8.5 to 72 mm) and the screen (61 x 41 mm, 3:2)
    s.rrect(30, top + 7, 91, top + 59, 6, rgb("#17171c"))
    s.hline(36, 85, top + 8, rgb("#3a3a44"))
    sx, sy, sw, sh = 34, top + 12, 54, 36
    s.rect(sx, sy, sx + sw - 1, sy + sh - 1, rgb("#2e3529"))
    s.anchors["screen"] = (sx, sy, sw, sh)
    s.hline(45, 76, top + 53, rgb("#9aa0aa"))                  # where the console's name is printed
    # POWER lamp (121 x 13 mm) and its label
    s.px(99, top + 11, rgb("#2b4a30"))
    s.px(100, top + 11, rgb("#2b4a30"))
    s.hline(103, 108, top + 11, shade(face, 0.78))
    s.anchors["led"] = (99, top + 11)
    # d-pad: centre 19 x 33 mm, 20 mm across, arms 6.5 mm wide
    dx, dy, r, w = 16, top + 27, 8, 2
    for (a, b, cc, d) in ((dx - r, dy - w, dx + r, dy + w), (dx - w, dy - r, dx + w, dy + r)):
        s.rect(a, b + 1, cc, d + 1, shade(c["dpad"], 0.6))
        s.rect(a, b, cc, d, c["dpad"])
    s.hline(dx - r + 1, dx + r - 1, dy - w, shade(c["dpad"], 1.2))
    s.px(dx, dy, shade(c["dpad"], 0.8))
    # A (135.6 x 31.4 mm) and B (121.1 x 35.8 mm), 10 mm across
    for bx, by in ((112, top + 26), (100, top + 30)):
        s.ellipse(bx - 4, by - 3, bx + 4, by + 5, shade(c["btn"], 0.6))
        s.ellipse(bx - 4, by - 4, bx + 4, by + 4, c["btn"])
        s.px(bx - 2, by - 2, shade(c["btn"], 1.3))
    # START and SELECT (29 x 54 and 29 x 62 mm), their names in recesses to the left
    for by in (top + 45, top + 52):
        s.rrect(11, by - 1, 20, by + 1, 1, shade(face, 0.82))
        s.ellipse(22, by - 2, 26, by + 2, c["btn"])
    # speaker: six slots, 116 to 132 mm across and 49 to 65 mm down, rising to the right
    for i in range(6):
        y = top + 42 + i * 2.4
        s.line([(97, round(y + 1)), (109, round(y - 1))], shade(face, 0.55))
    # the top edge: the EXT port, and the slot behind it
    ex = GBA_EXT_X
    s.rect(ex - 4, top - 2, ex + 4, top, rgb("#121216"))
    s.hline(ex - 5, ex + 5, top - 3, shade(face, 0.7))
    s.anchors["ext"] = (ex, top - 1)
    s.anchors["slot"] = (sum(GBA_SLOT) // 2, top)
    s.outline()
    return s


def gba_back(colourway="indigo"):
    """The back, in the face's colour as the real shell is: the darker upper plate, six screws, the
    label (left plain), the battery cover with its tab, and the cartridge slot along the top. The EXT
    port is left of centre from here."""
    c = COLOURWAYS[colourway]
    W, H, top = GBA_W, GBA_H, GBA_TOP
    shell = c["face"]
    s = Sprite(W, H + top)
    _shell(s, GBA_ROWS, top, c["bump"], mirror=True)
    _shell(s, GBA_FACE_TOP + GBA_ROWS[len(GBA_FACE_TOP):], top, shell, mirror=True)
    s.region_light((0, 0, W - 1, top + H - 1), shade(shell, 1.18), shade(shell, 0.72))
    s.rrect(7, top + 2, W - 8, top + 33, 8, shade(shell, 0.86))      # the upper plate
    a, b = W - 1 - GBA_SLOT[1], W - 1 - GBA_SLOT[0]
    s.rect(a + 4, top + 10, b - 4, top + 17, shade(shell, 0.74))    # the slot's recess
    s.rect(a, top, b, top + 1, rgb("#121216"))                       # the slot
    s.rect(30, top + 19, 88, top + 30, rgb("#3c3c46"))                # the label, left plain
    s.hline(33, 60, top + 21, rgb("#8a8a94"))
    s.rect(34, top + 33, 87, top + 65, shade(shell, 0.92))           # the battery cover
    s.vline(34, top + 33, top + 65, shade(shell, 0.7))
    s.vline(87, top + 33, top + 65, shade(shell, 0.7))
    s.rect(55, top + 30, 66, top + 37, shade(shell, 0.68))           # its tab
    s.rect(50, top + 46, 72, top + 54, rgb("#3c3c46"))                # its small label
    for x, y in ((31, 3), (89, 3), (21, 15), (100, 15), (7, 51), (113, 51)):
        s.px(x, top + y, shade(shell, 0.45))
    s.anchors["slot"] = ((a + b) // 2, top)
    s.anchors["ext"] = (W - 1 - GBA_EXT_X, top - 1)
    s.outline()
    return s


def _moulded(s, x, y, text, upside_down=False):
    """Lettering moulded into the silver: light above, shadow below. Upside down: as the DUO's "DS"
    reads from the front of a GBA it's in (refs/max duo in gba.jpg)."""
    w = len(text) * 4 + 2
    t = Sprite(w, 8)
    t.text(0, 0, text, shade(SILVER, 1.5), None)
    t.text(2, 2, text, shade(SILVER, 0.55), None)
    t.text(1, 1, text, shade(SILVER, 0.9), None)
    img = t.img.rotate(180) if upside_down else t.img
    s.img.alpha_composite(img, (x, y))


# The MAX DUO, measured with a ruler (Fred's photos, 15 November): a block 65 x 32 mm (switch, mini-USB
# socket and button along one edge) and the cartridge-shaped part that goes into the GBA's slot, 52 x
# 34 mm: 54 x 27 and 43 x 28 art pixels. In a GBA the block stands above the slot, its "DS" face to
# the front (upside down from there), and the rest is inside.
DUO_W, DUO_BLOCK, DUO_TONGUE_W, DUO_TONGUE = 54, 27, 43, 28


def _duo_shape(s, top):
    W = DUO_W
    tx = (W - DUO_TONGUE_W) // 2
    # the part that goes into the GBA: plainer, with a raised panel and the contacts' edge at its end
    s.rrect(tx, top + DUO_BLOCK - 3, tx + DUO_TONGUE_W - 1, top + DUO_BLOCK + DUO_TONGUE - 1, 2, shade(SILVER, 0.9))
    s.rrect(tx + 1, top + DUO_BLOCK - 2, tx + DUO_TONGUE_W - 2, top + DUO_BLOCK + DUO_TONGUE - 2, 2, SILVER)
    s.region_light((tx, top + DUO_BLOCK - 3, tx + DUO_TONGUE_W - 1, top + DUO_BLOCK + DUO_TONGUE - 1),
                   shade(SILVER, 1.25), shade(SILVER, 0.7))
    s.hline(tx + 3, tx + DUO_TONGUE_W - 4, top + DUO_BLOCK + DUO_TONGUE - 3, shade(SILVER, 0.6))
    # the block
    s.rrect(0, top, W - 1, top + DUO_BLOCK - 1, 3, shade(SILVER, 0.95))
    s.region_light((0, top, W - 1, top + DUO_BLOCK - 1), shade(SILVER, 1.3), shade(SILVER, 0.68))
    s.hline(2, W - 3, top + DUO_BLOCK - 1, shade(SILVER, 0.6))
    return tx


def duo():
    """Its "DS" face, in a GBA's orientation (the block on top, the part for the slot below): the
    switch, the mini-USB socket and the button on the top edge, two screws, the recessed panel with
    "DS" (upside down from here), the cartridge slot's notch; below, the slot part with its screws
    and panel. Anchors: usb, base (where it meets the GBA's top edge), led."""
    W, top = DUO_W, 3
    s = Sprite(W, top + DUO_BLOCK + DUO_TONGUE)
    s.rect(10, 0, 16, top, rgb("#33333b"))                # the switch, left (19-31% along)
    s.rect(11, 0, 13, 1, rgb("#55555f"))
    s.rect(23, 1, 29, top, rgb("#1c1c20"))                # the mini-USB socket (42-55%)
    s.rect(24, 2, 28, 2, rgb("#b8b0a0"))
    s.ellipse(37, 0, 41, top + 1, rgb("#2a2a30"))         # the round button (68-76%)
    tx = _duo_shape(s, top)
    for x in (4, W - 5):                                  # screws at the block's top corners
        s.px(x, top + 4, rgb("#6a6e76"))
        s.px(x, top + 3, rgb("#e8ecf0"))
    s.rrect(10, top + 7, W - 11, top + DUO_BLOCK - 4, 2, shade(SILVER, 0.86))     # the recessed panel
    s.hline(11, W - 12, top + DUO_BLOCK - 4, shade(SILVER, 1.25))
    _moulded(s, W // 2 - 5, top + 11, "DS", upside_down=True)
    s.d.chord([W // 2 - 4, top + 4, W // 2 + 3, top + 10], 0, 180, fill=rgb("#3a3a42") + (255,))  # the slot's notch
    yb = top + DUO_BLOCK
    s.rect(tx + 8, yb + 6, tx + DUO_TONGUE_W - 9, yb + 15, shade(SILVER, 0.88))  # the slot part's panel
    s.vline(tx + 5, yb + 2, yb + DUO_TONGUE - 6, shade(SILVER, 0.78))
    s.vline(tx + DUO_TONGUE_W - 6, yb + 2, yb + DUO_TONGUE - 6, shade(SILVER, 0.78))
    for x in (tx + 3, tx + DUO_TONGUE_W - 4):
        s.px(x, yb + DUO_TONGUE - 5, rgb("#6a6e76"))
    s.anchors["usb"] = (26, 1)
    s.anchors["base"] = (W // 2, yb)
    s.anchors["plug"] = (W // 2, yb)
    s.outline()
    return s


def duo_back():
    """Its other face, "GBA" moulded in (upside down too). From the GBA's back the cartridge goes in
    along the block's lower edge, contacts first, label outwards and so upside down, and lies flat on
    the GBA's back (Fred's photo, 15 November): the slot is that edge. The slot part below is drawn
    for when the DUO is seen alone; in a GBA it's inside."""
    W, top = DUO_W, 3
    s = Sprite(W, top + DUO_BLOCK + DUO_TONGUE)
    tx = _duo_shape(s, top)
    _moulded(s, W // 2 - 7, top + 8, "GBA", upside_down=True)
    yb = top + DUO_BLOCK
    s.rect(4, yb - 3, W - 5, yb - 1, rgb("#18181c"))     # the cartridge slot, along the lower edge
    for x in range(6, W - 6, 2):
        s.px(x, yb - 2, rgb("#8a7a40"))
    s.rrect(tx + 4, yb + 3, tx + DUO_TONGUE_W - 5, yb + DUO_TONGUE - 6, 2, shade(SILVER, 0.86))
    s.anchors["slot"] = (W // 2, yb - 2)
    s.anchors["plug"] = (W // 2, yb)
    s.outline()
    return s


def duo_block(sprite):
    """Just the block of a DUO sprite (its slot part cut off): as it shows over a GBA's back."""
    out = Sprite(sprite.size[0], 3 + DUO_BLOCK)
    out.img.alpha_composite(sprite.img.crop((0, 0, sprite.size[0], 3 + DUO_BLOCK)))
    out.anchors = dict(sprite.anchors)
    return out


# how far a cartridge goes into the DUO's slot from the GBA's back: 10 mm
PAK_IN_DUO = 8


def _pak_shape(s, col):
    """A Game Pak's outline (refs/cartridge front view.PNG): the grip along the top is the full 57.5 mm,
    the body below it 1.4 mm narrower each side; rounded corners."""
    W, H = 48, 29
    s.rrect(0, 0, W - 1, 8, 3, shade(col, 0.8))
    s.rrect(1, 4, W - 2, H - 1, 2, shade(col, 0.8))
    s.rrect(1, 1, W - 2, 7, 2, col)
    s.rrect(2, 5, W - 3, H - 2, 2, col)
    s.region_light((0, 0, W - 1, H - 1), shade(col, 1.35), shade(col, 0.6))
    s.hline(4, W - 5, 7, shade(col, 0.72))                  # the grip's edge
    for x in range(6, W - 6, 3):
        s.vline(x, 2, 5, shade(col, 0.82))


def game_pak(game):
    """The front, label side: the label (left plain but for the name), centred, 10 to 33 mm down."""
    W, H = 48, 29
    col, name = GAMES[game]
    s = Sprite(W, H)
    _pak_shape(s, col)
    s.rect(5, 9, 42, 26, rgb("#e9e6dc"))                  # (centred: Fred's choice over the real offset)
    s.rect(6, 10, 41, 12, shade(col, 1.15))
    s.rect(6, 23, 41, 25, shade(col, 1.15))
    tw = sum(len(TINY_W.get(c.upper(), "x" * 3)) + 1 for c in name) - 1
    s.text(5 + (38 - tw) // 2, 15, name, shade(col, 0.55), None)
    s.anchors["top"] = (W // 2, 0)
    s.anchors["edge"] = (W // 2, H - 1)
    s.outline()
    return s


def game_pak_back(game):
    """The back, as it shows above a GBA seen from the front (the label faces the GBA's back): plain."""
    W, H = 48, 29
    col, _ = GAMES[game]
    s = Sprite(W, H)
    _pak_shape(s, col)
    s.rrect(12, 12, W - 13, 20, 2, shade(col, 0.9))
    s.px(W // 2, 22, shade(col, 0.5))
    s.anchors["top"] = (W // 2, 0)
    s.anchors["edge"] = (W // 2, H - 1)
    s.outline()
    return s


# how much of a Game Pak shows above the GBA's top edge when it's in: 13 mm
PAK_SHOWS = 11


def laptop(left_usb=False):
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
    s.rect(60, 96, W - 61, 97, rgb("#3d424d"))
    # a USB-A socket in the side of the base (seen edge-on: a dark slot with its tongue)
    if left_usb:
        s.rect(2, 95, 3, 99, rgb("#15161b"))
        s.px(3, 97, rgb("#7a7e86"))
        s.anchors["usb"] = (2, 97)
    else:
        s.rect(W - 4, 95, W - 3, 99, rgb("#15161b"))
        s.px(W - 4, 97, rgb("#7a7e86"))
        s.anchors["usb"] = (W - 3, 97)
    s.outline()
    return s


def _plug(body, tip, w, h, tw, th, ridges=3, shroud=None):
    """A plug pointing down: ridged strain relief at the top, a tapered body, the tip below."""
    s = Sprite(w, h + th)
    rl = 4
    s.rect(w // 2 - 2, 0, w // 2 + 1, rl, body)
    for i in range(ridges):
        s.hline(w // 2 - 2, w // 2 + 1, 1 + i, shade(body, 0.6))
    s.poly([(w // 2 - 3, rl), (w // 2 + 2, rl), (w - 1, rl + 4), (w - 1, h - 1), (0, h - 1), (0, rl + 4)], body)
    s.vline(1, rl + 4, h - 2, shade(body, 1.35))
    s.vline(w - 2, rl + 4, h - 2, shade(body, 0.7))
    x0 = (w - tw) // 2
    s.rect(x0, h, x0 + tw - 1, h + th - 1, shroud or tip)
    s.rect(x0 + 1, h, x0 + tw - 2, h, shade(shroud or tip, 0.7))
    s.anchors["tip"] = (w // 2, h + th - 1)
    s.anchors["tail"] = (w // 2, 0)
    s.outline()
    return s


def link_plug(style):
    if style == "gba_purple":
        return _plug(rgb("#6a52c8"), rgb("#4a3a90"), 9, 15, 5, 3)
    if style == "gba_grey":
        return _plug(rgb("#9a9ca6"), rgb("#6e707a"), 9, 15, 5, 3)
    if style == "gbc_black":
        return _plug(BLACK, None, 9, 14, 5, 3, shroud=rgb("#c8ccd2"))
    if style == "gbc_grey":                  # the Game Boy Color cable CGB-003's small plugs
        return _plug(rgb("#a4a6ae"), None, 9, 14, 5, 3, shroud=rgb("#c8ccd2"))
    if style == "dmg_black":
        return _plug(BLACK, None, 11, 16, 7, 4, shroud=rgb("#c8ccd2"))
    raise ValueError(style)


def usb_mini_b():
    return _plug(BLACK, None, 7, 12, 3, 3, shroud=rgb("#c8ccd2"))


def usb_a(inserted=False):
    """A USB-A plug pointing right; inserted, its metal is inside the PC and only the body shows,
    right up against the socket."""
    s = Sprite(11 if inserted else 16, 9)
    s.rrect(0, 0, 10, 8, 2, BLACK)
    s.vline(1, 1, 7, shade(BLACK, 1.6))
    s.hline(2, 8, 1, shade(BLACK, 1.4))
    if not inserted:
        s.rect(10, 1, 15, 7, rgb("#c8ccd2"))
        s.rect(12, 3, 13, 5, rgb("#7a7e86"))
    s.anchors["tip"] = (10 if inserted else 15, 4)
    s.anchors["tail"] = (0, 4)
    s.outline()
    return s


def agb005_hub():
    col = rgb("#4f48b0")
    s = Sprite(14, 12)
    s.rrect(0, 0, 13, 11, 3, col)
    s.region_light((0, 0, 13, 11), shade(col, 1.35), shade(col, 0.65))
    s.rrect(4, 3, 9, 7, 1, rgb("#18181e"))
    s.outline()
    return s


def mgb010_junction():
    s = Sprite(16, 10)
    s.rrect(0, 0, 15, 9, 2, BLACK)
    s.region_light((0, 0, 15, 9), shade(BLACK, 1.8), shade(BLACK, 0.6))
    s.rrect(3, 3, 12, 6, 1, shade(BLACK, 1.5))
    s.outline()
    return s


def ferrite(colour):
    s = Sprite(8, 8)
    s.rrect(0, 0, 7, 7, 3, colour)
    s.region_light((0, 0, 7, 7), shade(colour, 1.4), shade(colour, 0.6))
    s.outline()
    return s


def sheet(path, scale=4):
    from PIL import Image
    items = [gba("indigo"), gba_back("indigo"), gba("glacier"), gba_back("glacier"), duo(), duo_back(),
             laptop()] + [game_pak(g) for g in GAMES] + [game_pak_back(g) for g in GAMES] + \
        [usb_mini_b(), usb_a(), usb_a(True), link_plug("gba_purple"), link_plug("gba_grey"), link_plug("gbc_black"),
         link_plug("dmg_black"), agb005_hub(), mgb010_junction(), ferrite(rgb("#9a9ca6")), ferrite(BLACK)]
    W = 540
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
    img = Image.new("RGBA", (W, y + rowh + 4), (42, 47, 79, 255))
    for it, p in zip(items, pos):
        img.alpha_composite(it.img, p)
    img.resize((img.size[0] * scale, img.size[1] * scale), Image.NEAREST).save(path)


if __name__ == "__main__":
    import sys
    sheet(sys.argv[1] if len(sys.argv) > 1 else "/tmp/sheet.png")
