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
from pixel import Sprite, rgb, shade

COLOURWAYS = {
    "indigo": dict(face=rgb("#4f47b0"), shell=rgb("#c9cbd3"), btn=rgb("#dfe1e8"), dpad=rgb("#dfe1e8")),
    "glacier": dict(face=rgb("#6fb6e6"), shell=rgb("#8cc6ec"), btn=rgb("#4f9fd8"), dpad=rgb("#4f9fd8")),
}
GAMES = {   # translucent shell colour, name in plain letters
    "ruby": (rgb("#c2262e"), "RUBY"), "sapphire": (rgb("#2850c4"), "SAPPHIRE"),
    "emerald": (rgb("#1e9a48"), "EMERALD"), "firered": (rgb("#e0401e"), "FIRERED"),
    "leafgreen": (rgb("#3fae3c"), "LEAFGREEN"), "other": (rgb("#8a8c96"), "ANY GAME"),
}
SILVER = rgb("#c3c8d0")
BLACK = rgb("#26262c")


def gba(colourway="indigo"):
    c = COLOURWAYS[colourway]
    W, H, top = 122, 70, 6
    s = Sprite(W, H + top)
    # grey shell showing at the shoulders, and the shoulder buttons
    s.rrect(4, top - 2, 40, top + 18, 10, shade(c["shell"], 0.85))
    s.rrect(W - 41, top - 2, W - 5, top + 18, 10, shade(c["shell"], 0.85))
    s.rrect(0, top + 3, W - 1, top + H - 1, 28, c["shell"])
    # the coloured face: rounded ends, gently bowed top and bottom
    face = c["face"]
    s.rrect(2, top + 3, W - 3, top + H - 3, 27, face)
    s.d.chord([20, top - 6, W - 21, top + 14], 180, 360, fill=face + (255,))
    s.d.chord([16, top + H - 19, W - 17, top + H], 0, 180, fill=face + (255,))
    s.region_light((0, 0, W - 1, top + H - 1), shade(face, 1.25), shade(face, 0.72))
    s.d.rounded_rectangle([W // 2 - 11, top + 1, W // 2 + 10, top + 5], 2, outline=shade(face, 0.75) + (255,))
    # the screen surround (black, glossy) and the screen (3:2)
    s.rrect(34, top + 8, W - 35, top + 56, 7, rgb("#17171c"))
    s.hline(40, W - 41, top + 9, rgb("#3a3a44"))
    sx, sy, sw, sh = 40, top + 13, 42, 28
    s.rect(sx, sy, sx + sw - 1, sy + sh - 1, rgb("#2e3529"))
    s.anchors["screen"] = (sx, sy, sw, sh)
    s.hline(46, W - 47, top + 50, rgb("#9aa0aa"))           # where the console's name is printed
    s.hline(52, W - 53, top + 51, rgb("#6a707a"))
    # POWER lamp right of the screen, top
    s.px(W - 26, top + 13, rgb("#2b4a30"))
    s.px(W - 25, top + 13, rgb("#2b4a30"))
    s.hline(W - 22, W - 15, top + 13, shade(face, 0.78))
    s.anchors["led"] = (W - 26, top + 13)
    # d-pad, left
    dx, dy = 18, top + 27
    for (a, b, cc, d) in ((dx - 8, dy - 3, dx + 8, dy + 3), (dx - 3, dy - 8, dx + 3, dy + 8)):
        s.rect(a, b + 1, cc, d + 1, shade(c["dpad"], 0.6))
        s.rect(a, b, cc, d, c["dpad"])
    s.hline(dx - 7, dx + 7, dy - 3, shade(c["dpad"], 1.2))
    s.px(dx, dy, shade(c["dpad"], 0.8))
    # A (upper right) and B, round
    for bx, by in ((W - 15, top + 24), (W - 27, top + 30)):
        s.ellipse(bx - 5, by - 4, bx + 5, by + 6, shade(c["btn"], 0.6))
        s.ellipse(bx - 5, by - 5, bx + 5, by + 5, c["btn"])
        s.px(bx - 2, by - 3, shade(c["btn"], 1.3))
    # START and SELECT: small round buttons beside labelled recesses
    for by in (top + 43, top + 50):
        s.rrect(9, by - 2, 27, by + 3, 3, shade(face, 0.82))
        s.ellipse(25, by - 2, 30, by + 3, c["btn"])
    # speaker: six slanted slots, lower right
    for i in range(6):
        y = top + 41 + i * 3
        s.line([(W - 32 + i, y), (W - 18 + i, y - 3)], shade(face, 0.55))
    # top edge: the EXT port right of centre; the slot behind
    ex = W // 2 + 8
    s.rect(ex - 5, top - 3, ex + 5, top - 2, rgb("#121216"))
    s.rect(ex - 6, top - 4, ex + 6, top - 4, shade(c["shell"], 0.7))
    s.anchors["ext"] = (ex, top - 3)
    s.anchors["slot"] = (W // 2, top + 2)
    s.outline()
    return s


def gba_back(colourway="indigo"):
    """The back: the shell, the battery cover, and the cartridge slot along the top."""
    c = COLOURWAYS[colourway]
    W, H, top = 122, 70, 6
    s = Sprite(W, H + top)
    shell = c["shell"] if colourway == "glacier" else rgb("#b9bbc4")
    s.rrect(4, top - 2, 40, top + 18, 10, shade(shell, 0.85))
    s.rrect(W - 41, top - 2, W - 5, top + 18, 10, shade(shell, 0.85))
    s.rrect(0, top + 3, W - 1, top + H - 1, 28, shell)
    s.region_light((0, 0, W - 1, top + H - 1), shade(shell, 1.2), shade(shell, 0.72))
    s.rect(W // 2 - 31, top + 2, W // 2 + 31, top + 9, shade(shell, 0.6))
    s.rrect(W // 2 - 24, top + 42, W // 2 + 24, top + 62, 4, shade(shell, 0.9))
    s.hline(W // 2 - 22, W // 2 + 22, top + 43, shade(shell, 1.15))
    for x in (12, W - 13):
        s.px(x, top + 40, shade(shell, 0.5))
    s.anchors["slot"] = (W // 2, top + 2)
    s.outline()
    return s


def _moulded(s, x, y, text):
    s.text(x - 1, y, text, shade(SILVER, 1.5), None)
    s.text(x + 1, y + 2, text, shade(SILVER, 0.55), None)
    s.text(x, y + 1, text, shade(SILVER, 0.9), None)


def duo():
    W, H = 48, 32
    s = Sprite(W, H)
    s.rect(7, 1, 12, 4, rgb("#33333b"))                # AR switch, left
    s.rect(8, 0, 10, 1, rgb("#55555f"))
    s.rect(20, 2, 27, 4, rgb("#1c1c20"))               # mini-USB socket
    s.rect(21, 3, 26, 3, rgb("#b8b0a0"))
    s.rect(36, 1, 40, 4, rgb("#33333b"))               # AR button, right
    s.rrect(4, 4, W - 5, 20, 3, SILVER)                # the narrower upper block
    s.rrect(0, 16, W - 1, H - 1, 3, shade(SILVER, 0.95))   # the wide base
    s.region_light((0, 4, W - 1, H - 1), shade(SILVER, 1.3), shade(SILVER, 0.7))
    s.hline(5, W - 6, 16, shade(SILVER, 0.75))
    for x in (4, W - 5):                                # screws
        s.px(x, 24, rgb("#6a6e76"))
        s.px(x, 23, rgb("#e8ecf0"))
    _moulded(s, W // 2 - 4, 8, "DS")
    s.anchors["usb"] = (23, 2)
    s.anchors["base"] = (W // 2, H - 1)
    s.outline()
    return s


def duo_back():
    W, H = 48, 32
    s = Sprite(W, H)
    s.rrect(4, 4, W - 5, 20, 3, SILVER)
    s.rrect(0, 16, W - 1, H - 1, 3, shade(SILVER, 0.95))
    s.region_light((0, 4, W - 1, H - 1), shade(SILVER, 1.3), shade(SILVER, 0.7))
    _moulded(s, W // 2 - 6, 7, "GBA")
    s.rect(5, H - 6, W - 6, H - 3, rgb("#18181c"))
    for x in range(7, W - 7, 2):
        s.px(x, H - 4, rgb("#8a7a40"))
    s.anchors["slot"] = (W // 2, H - 3)
    s.outline()
    return s


def game_pak(game):
    W, H = 47, 29
    col, name = GAMES[game]
    s = Sprite(W, H)
    s.rrect(0, 3, W - 1, H - 1, 2, shade(col, 0.8))
    s.rect(6, 0, W - 7, 4, shade(col, 0.8))
    s.rrect(1, 4, W - 2, H - 2, 2, col)
    s.rect(7, 1, W - 8, 4, col)
    s.region_light((0, 0, W - 1, H - 1), shade(col, 1.35), shade(col, 0.6))
    for x in range(9, W - 9, 4):
        s.vline(x, 1, 2, shade(col, 0.75))
    s.rrect(4, 8, W - 5, H - 5, 1, rgb("#e9e6dc"))
    s.rect(5, 9, W - 6, 11, shade(col, 1.15))
    s.rect(5, H - 7, W - 6, H - 6, shade(col, 1.15))
    tw = len(name) * 4 - 1
    s.text((W - tw) // 2, 14, name, shade(col, 0.55), None)
    s.anchors["top"] = (W // 2, 0)
    s.anchors["edge"] = (W // 2, H - 1)
    s.outline()
    return s


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
    if left_usb:
        s.rect(3, 96, 5, 98, rgb("#15161b"))
        s.anchors["usb"] = (3, 97)
    else:
        s.rect(W - 6, 96, W - 4, 98, rgb("#15161b"))
        s.anchors["usb"] = (W - 4, 97)
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
    if style == "dmg_black":
        return _plug(BLACK, None, 11, 16, 7, 4, shroud=rgb("#c8ccd2"))
    raise ValueError(style)


def usb_mini_b():
    return _plug(BLACK, None, 7, 12, 3, 3, shroud=rgb("#c8ccd2"))


def usb_a():
    s = Sprite(16, 9)
    s.rrect(0, 0, 10, 8, 2, BLACK)
    s.vline(1, 1, 7, shade(BLACK, 1.6))
    s.rect(10, 1, 15, 7, rgb("#c8ccd2"))
    s.rect(12, 3, 13, 5, rgb("#7a7e86"))
    s.anchors["tip"] = (15, 4)
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
    items = [gba("indigo"), gba("glacier"), gba_back("glacier"), duo(), duo_back(), laptop()] + \
        [game_pak(g) for g in GAMES] + \
        [usb_mini_b(), usb_a(), link_plug("gba_purple"), link_plug("gba_grey"), link_plug("gbc_black"),
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
