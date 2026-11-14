"""setups.py - the animated setup scenes, built from parts.py's sprites, laid out as in Fred's photos:

    games()                            the five Generation III games and the cable each feature needs
    backup(game)                       the laptop, the USB lead and one GBA: the game into the DUO's slot
                                       (seen from the back), the GBA turned over, USB, maxduo_saves.py
    link(game, cable, master, lines)   any cartridge into the DUO (back view), turned over; the game's GBA
                                       with its game; the link cable flowing between the two ports; the
                                       USB lead; the tool's command on the laptop, the DUO's GBA on, then
                                       at "Ready" the game's
        cable "agb005": GBA Game Link Cable, grey with a purple hub; master "game" or "duo" puts its small
                        purple plug in that GBA, "either" means it doesn't matter
        cable "mgb010": Universal Game Link Cable (black, cross-wired), for Mystery Gift; its split end's
                        wide original Game Boy plug lies unused

Each returns a Scene; scene.render(t) is a 1080x1080 frame.
"""
from PIL import Image

import parts
from pixel import Sprite, rgb
from scene import Scene, Actor, Cable, Label

GAME_NAMES = {"ruby": "Pokémon Ruby", "sapphire": "Pokémon Sapphire", "emerald": "Pokémon Emerald",
              "firered": "Pokémon FireRed", "leafgreen": "Pokémon LeafGreen"}
TERM_CMD, TERM_OUT = (130, 230, 150), (214, 220, 230)
PROMPT = "C:\\ActionReplay>"
GREY_LEAD, BLACK_LEAD, USB_LEAD = rgb("#9a9ca6"), rgb("#2a2a30"), rgb("#2a2a30")


def typed(cmd, t0, cps=16):
    def lines(t, extra=()):
        k = int(max(0, t - t0) * cps)
        cur = "_" if k < len(cmd) and int(t * 3) % 2 == 0 else ""
        return [(TERM_CMD, PROMPT + " " + cmd[:k] + cur)] + list(extra)
    return lines


def plain(colour):
    return Image.new("RGB", (240, 160), colour)


def composite(layers):
    """One sprite from several (sprite, x, y) layers, back to front (for turning a GBA over whole)."""
    x0 = min(x for s, x, y in layers)
    y0 = min(y for s, x, y in layers)
    x1 = max(x + s.size[0] for s, x, y in layers)
    y1 = max(y + s.size[1] for s, x, y in layers)
    out = Sprite(int(x1 - x0), int(y1 - y0))
    for s, x, y in layers:
        out.img.alpha_composite(s.img, (int(x - x0), int(y - y0)))
    return out, (x0, y0)


def duo_gba(sc, x, y, cart, colour, t0, label_at, cart_label):
    """A GBA with the DUO in its slot: seen from the back first, a cartridge slides into the DUO and
    lies flat on the GBA's back; then the GBA is turned over. Returns the front actors (gba, duo)."""
    back, front = parts.gba_back(colour), parts.gba(colour)
    db, df = parts.duo_back(), parts.duo()
    pak = parts.game_pak(cart)
    sx, sy = back.anchors["slot"]
    dbx, dby = x + sx - db.size[0] / 2, y + sy - db.size[1] + 3
    px, py = x + sx - pak.size[0] / 2, dby + db.anchors["slot"][1] - 2
    tb = t0 + 2.2                                        # when the turn-over starts
    A = sc.add(Actor(back, x, y, z=5, t_in=t0, t_out=tb))
    A.move(t0, t0 + 0.6, (x, y + 160), (x, y))
    D = sc.add(Actor(db, dbx, dby, z=6, t_in=t0, t_out=tb))
    D.move(t0, t0 + 0.6, (dbx, dby + 160), (dbx, dby))
    P = sc.add(Actor(pak, px, py, z=7, t_in=t0 + 0.9, t_out=tb))
    P.move(t0 + 0.9, t0 + 1.6, (px, py + 60), (px, py))
    sc.labels.append(Label(cart_label, (P, "edge"), label_at, t0 + 1.2, tb))
    # turned over: the back squashes away, the front opens out
    bsp, (bx, by) = composite([(back, x, y), (db, dbx, dby), (pak, px, py)])
    B = sc.add(Actor(bsp, bx, by, z=5, t_in=tb, t_out=tb + 0.3))
    B.squash = (tb, tb + 0.3, 1.0, 0.02)
    fx, fy = front.anchors["slot"]
    dfx, dfy = x + fx - df.size[0] / 2, y + fy - df.size[1] + 3
    fsp, (cx, cy) = composite([(df, dfx, dfy), (front, x, y)])
    F = sc.add(Actor(fsp, cx, cy, z=5, t_in=tb + 0.3, t_out=tb + 0.6))
    F.squash = (tb + 0.3, tb + 0.6, 0.02, 1.0)
    G = sc.add(Actor(front, x, y, z=5, t_in=tb + 0.6))
    U = sc.add(Actor(df, dfx, dfy, z=4, t_in=tb + 0.6))
    return G, U, tb + 0.6


def backup(game="ruby", duo_screen=None):
    sc = Scene(15.0)
    G, U, t = duo_gba(sc, 200, 150, game, "indigo", 0.0, (300, 290), "your game, into the DUO's back")
    sc.caption(0.0, "The DUO goes in the GBA's cartridge slot, and your game into the back of the DUO", "Step 1")
    lap = sc.add(Actor(parts.laptop(), 8, 60, z=1, t_in=t))
    lap.move(t, t + 0.6, (-170, 60), (8, 60))
    sc.labels.append(Label("Action Replay MAX DUO", (U, "base"), (236, 60), t + 0.2, t + 4))
    a = parts.usb_a()
    lx, ly = lap.anchor("usb", t + 1)
    tu = t + 1.0
    sc.cables.append(Cable((lx, ly), (U, "usb"), [(190, 150), (215, 100), (236, 92)], tu, tu + 1.4, USB_LEAD,
                           width=2, plug_b=parts.usb_mini_b(), rise=8))
    sc.add(Actor(a, lx - 1, ly - a.anchors["tip"][1], z=3, t_in=tu))
    sc.labels.append(Label("USB lead: mini-B into the DUO, A into the PC", (190, 150), (150, 250), tu + 0.8, tu + 5))
    sc.caption(tu, "Connect the DUO's mini-B socket to the PC with its USB lead", "Step 1")
    tc = tu + 2.2
    term = typed("python maxduo_saves.py --gba-save", tc)
    sc.terminal = (lap, lambda tt: term(tt, [(TERM_OUT, "")] + ([(TERM_OUT, "Switch the GBA on...")] if tt > tc + 2.6 else [])))
    sc.caption(tc, "Run maxduo_saves.py --gba-save, and switch the GBA on when it asks", "Step 1")
    G.on_at = tc + 3.6
    G.screen = lambda tt: (duo_screen or plain((200, 214, 230))) if tt >= tc + 3.6 else None
    sc.caption(tc + 3.6, "The save is copied to the saves folder on the PC; the cartridge is only read", "Step 1")
    sc.duration = tc + 7.0
    return sc


def link(game="ruby", cable="agb005", master="either", lines=(), cmd="python duo_events.py", duo_screen=None,
         game_screen=None):
    sc = Scene(30.0)
    # the DUO's GBA (indigo), top left: any cartridge into the DUO from the back, then turned over
    G, U, t = duo_gba(sc, 24, 104, "other", "indigo", 0.0, (85, 250),
                      "any GBA cartridge, into the DUO's back")
    sc.caption(0.0, "The DUO in one GBA, with any GBA cartridge in its back: it needs one to start", "Step 2")
    # the game's GBA (glacier), bottom right, its game standing in the slot
    R = sc.add(Actor(parts.gba("glacier"), 214, 216, z=5, t_in=t))
    R.move(t, t + 0.6, (380, 216), (214, 216))
    pak = parts.game_pak(game)
    px, py = 214 + R.s.anchors["slot"][0] - pak.size[0] / 2, 216 + 6 - pak.size[1] + 8
    P = sc.add(Actor(pak, px, py, z=4, t_in=t + 0.8))
    P.move(t + 0.8, t + 1.4, (px, py - 90), (px, py))
    sc.labels.append(Label(f"your game: {GAME_NAMES[game]}", (P, "top"), (250, 150), t + 1.2, t + 4.2))
    sc.labels.append(Label("the DUO's GBA", (G, "led"), (60, 205), t, t + 3))
    sc.labels.append(Label("the game's GBA", (R, "led"), (300, 312 - 14), t + 0.6, t + 4.2))
    sc.caption(t, "Your game goes in the other GBA. Both GBAs stay switched off for now", "Step 2")
    # the link cable, flowing from the DUO's GBA over and down into the game's GBA
    tc = t + 2.4
    via = [(112, 66), (150, 74), (166, 118), (150, 168), (176, 196), (232, 176), (262, 168)]
    if cable == "mgb010":
        small, dmg = parts.link_plug("gbc_black"), parts.link_plug("dmg_black")
        c = Cable((G, "ext"), (R, "ext"), via, tc, tc + 1.8, BLACK_LEAD, width=3, plug_a=small, plug_b=small,
                  beads=[(0.1, parts.ferrite(BLACK_LEAD)), (0.84, parts.mgb010_junction())],
                  branch=(0.84, [(226, 192), (212, 222), (204, 248)], dmg))
        sc.cables.append(c)
        sc.labels.append(Label("Universal Game Link Cable MGB-010\n(cross-wired)", (c, 0.45), (110, 296), tc + 1.0,
                               tc + 6))
        sc.labels.append(Label("its split end's wide plug\nisn't used", (204, 248), (150, 214), tc + 2.0, tc + 6))
        sc.caption(tc, "Mystery Gift: a cross-wired Game Boy cable, Nintendo's MGB-010. A GBA cable won't do",
                   "Step 2")
    else:
        purple, grey = parts.link_plug("gba_purple"), parts.link_plug("gba_grey")
        pa, pb = (purple, grey) if master == "duo" else (grey, purple)
        hub_at = 0.22 if master == "duo" else 0.78
        c = Cable((G, "ext"), (R, "ext"), via, tc, tc + 1.8, GREY_LEAD, width=2, plug_a=pa, plug_b=pb,
                  beads=[(0.08, parts.ferrite(GREY_LEAD)), (hub_at, parts.agb005_hub()),
                         (0.94 if master == "duo" else 0.5, parts.ferrite(GREY_LEAD))])
        sc.cables.append(c)
        sc.labels.append(Label("GBA Game Link Cable AGB-005", (c, 0.42), (110, 296), tc + 1.0, tc + 6))
        if master == "either":
            sc.caption(tc, "A GBA link cable (AGB-005) joins the two GBAs, either way round", "Step 2")
        else:
            who = "the game's" if master == "game" else "the DUO's"
            tgt = (R, "ext") if master == "game" else (G, "ext")
            sc.labels.append(Label("small purple plug:\nthe master end", tgt, (330 if master == "game" else 40, 176)
                                   if master == "game" else (40, 60), tc + 2.0, tc + 6))
            sc.caption(tc, f"AGB-005 cable: its small purple plug into {who} GBA (the master end)", "Step 2")
    # the laptop and the USB lead
    tl = tc + 4.4
    lap = sc.add(Actor(parts.laptop(left_usb=True), 198, 6, z=1, t_in=tl))
    lap.move(tl, tl + 0.6, (380, 6), (198, 6))
    lx, ly = 198 + lap.s.anchors["usb"][0], 6 + lap.s.anchors["usb"][1]
    a = parts.usb_a()
    ax = lx - a.anchors["tip"][0]
    sc.add(Actor(a, ax, ly - a.anchors["tip"][1], z=3, t_in=tl + 0.8))
    cu = Cable((ax, ly), (U, "usb"), [(172, 104), (150, 56), (110, 40), (78, 50)], tl + 0.8, tl + 2.0,
               USB_LEAD, width=2, plug_b=parts.usb_mini_b(), rise=8)
    sc.cables.append(cu)
    sc.labels.append(Label("USB lead: mini-B into the DUO, A into the PC", (cu, 0.4), (150, 16), tl + 1.6, tl + 5))
    sc.caption(tl, "The DUO's USB lead goes to the PC", "Step 2")
    # the tool, then switching on in order
    first = list(lines)
    ready = next((i for i, l in enumerate(first) if "Ready" in l), len(first) - 1)
    tt = tl + 3.2
    term = typed(cmd, tt)

    def term_lines(t):
        out = []
        if t > tt + 3.4:
            k = int((t - tt - 3.4) * 5)
            out = [(TERM_OUT, l) for l in first[:min(k, ready + 1)]]
        return term(t, out)
    sc.terminal = (lap, term_lines)
    sc.caption(tt, "Run the tool, and switch on the DUO's GBA when it asks", "Step 3")
    G.on_at = tt + 3.0
    G.screen = lambda t: (duo_screen or plain((210, 220, 236))) if t >= tt + 3.0 else None
    sc.badge(tt + 3.0, G, "led", "1")
    t_ready = tt + 3.4 + (ready + 1) / 5 + 0.5
    sc.caption(t_ready, "\"Ready\": now switch on the game's GBA", "Step 4")
    R.on_at = t_ready + 1.0
    R.screen = lambda t: (game_screen or plain((248, 248, 248))) if t >= t_ready + 1.0 else None
    sc.badge(t_ready + 1.0, R, "led", "2")
    sc.duration = t_ready + 4.0
    return sc


def games(focus=None):
    """All five Generation III games and what each needs: Ruby and Sapphire take Mystery Events over a
    GBA cable with the game on the master end; Emerald, FireRed and LeafGreen take Mystery Gifts over a
    cross-wired MGB-010; everything else goes over a GBA cable either way round."""
    sc = Scene(9.0)
    order = ["ruby", "sapphire", "emerald", "firered", "leafgreen"]
    xs = [22, 76, 168, 222, 276]
    for i, (g, x) in enumerate(zip(order, xs)):
        a = sc.add(Actor(parts.game_pak(g), x, 62, z=2, t_in=0.25 * i))
        a.move(0.25 * i, 0.25 * i + 0.5, (x, -40), (x, 62))
    purple, grey = parts.link_plug("gba_purple"), parts.link_plug("gba_grey")
    sc.cables.append(Cable((34, 196), (112, 196), [(52, 150), (78, 172), (98, 150)], 2.0, 2.8, GREY_LEAD,
                           width=2, plug_a=purple, plug_b=grey,
                           beads=[(0.25, parts.agb005_hub()), (0.8, parts.ferrite(GREY_LEAD))]))
    sc.labels.append(Label("Mystery Event:\nGBA cable AGB-005,\nthe game on the\nsmall purple plug", (73, 172),
                           (73, 262), 2.4))
    small, dmg = parts.link_plug("gbc_black"), parts.link_plug("dmg_black")
    sc.cables.append(Cable((196, 196), (292, 196), [(212, 150), (244, 176), (276, 150)], 4.0, 4.8, BLACK_LEAD,
                           width=3, plug_a=small, plug_b=small,
                           beads=[(0.18, parts.ferrite(BLACK_LEAD)), (0.78, parts.mgb010_junction())],
                           branch=(0.78, [(300, 158), (318, 170), (326, 190)], dmg)))
    sc.labels.append(Label("Mystery Gift:\ncross-wired Game Boy\ncable MGB-010", (244, 176), (244, 262), 4.4))
    sc.labels.append(Label("Ruby, Sapphire", (72, 92), (72, 116), 2.0))
    sc.labels.append(Label("Emerald, FireRed, LeafGreen", (245, 92), (245, 116), 4.0))
    sc.caption(0.0, "Every Generation III Pokémon game works with the DUO", "Games")
    sc.caption(2.0, "Ruby and Sapphire take Mystery Events from the e-Reader: the DUO plays it", "Games")
    sc.caption(4.0, "Emerald, FireRed and LeafGreen take Mystery Gifts: the DUO plays a Wireless Adapter", "Games")
    sc.caption(6.2, "Trades, battles, mixing, the Blender, contests and the Tower: a GBA cable, either way round",
               "Games")
    return sc


if __name__ == "__main__":
    import sys, os
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/setups"
    os.makedirs(out, exist_ok=True)
    demo = ["Before you start: both GBAs should be switched off.", "Connected to Action Replay MAX DUO",
            "  Setting up the DUO's GBA     [########] 100%", "  Ready. Now switch on the game's GBA"]
    for name, sc in (("games", games()), ("backup", backup()),
                     ("link_either", link(lines=demo, cmd="python duo_events.py trade --pk3 offer.pk3")),
                     ("link_event", link("ruby", "agb005", "game", demo)),
                     ("link_gift", link("emerald", "mgb010", lines=demo))):
        for t in sorted({1.4, 2.4, 6.0, 9.0, sc.duration - 0.5}):
            sc.render(t).save(os.path.join(out, f"{name}_{t:04.1f}.png"))
        print(name, round(sc.duration, 1))
