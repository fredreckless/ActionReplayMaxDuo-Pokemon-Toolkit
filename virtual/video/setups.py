"""setups.py - the animated setup scenes, built from parts.py's sprites:

    backup(game)                       the laptop, the USB lead and one GBA: the DUO in the GBA, the game
                                       in the DUO's slot, then maxduo_saves.py --gba-save
    link(game, cable, master, lines)   two GBAs: the DUO (with any cartridge fitted, so it starts) in one,
                                       the game in the other, the link cable between them and the USB
                                       lead to the laptop; then the tool's command, the DUO's GBA on,
                                       "Ready", the game's GBA on
        cable "agb005": the GBA Game Link Cable; master "game" or "duo" puts its small purple plug in
                        that GBA, "either" means it doesn't matter
        cable "mgb010": the Universal Game Link Cable (cross-wired), for Mystery Gift

Each returns a Scene; scene.render(t) is a 1080x1080 frame.
"""
import parts
from pixel import rgb
from scene import Scene, Actor, Cable, Label

GAME_NAMES = {"ruby": "Pokémon Ruby", "sapphire": "Pokémon Sapphire", "emerald": "Pokémon Emerald",
              "firered": "Pokémon FireRed", "leafgreen": "Pokémon LeafGreen"}
TERM_CMD, TERM_OUT = (130, 230, 150), (214, 220, 230)
PROMPT = "C:\\ActionReplay>"


def typed(cmd, t0, cps=16):
    """A terminal: the prompt, then cmd typed from t0."""
    def lines(t, extra=()):
        k = int(max(0, t - t0) * cps)
        out = [(TERM_CMD, PROMPT + " " + cmd[:k] + ("_" if k < len(cmd) and int(t * 3) % 2 == 0 else ""))]
        return out + list(extra)
    return lines


def screen_on(colour):
    from PIL import Image
    return Image.new("RGB", (240, 160), colour)


def fit_pak(sc, holder, pak_sprite, t0, label=None, label_at=None, behind=True):
    """A pak dropping into a holder's slot: it ends standing up out of the slot, behind the holder."""
    hx, hy = holder.pos(10)
    sx, sy = holder.s.anchors["slot"][:2]
    px = hx + sx - pak_sprite.size[0] / 2
    py = hy + sy - pak_sprite.size[1] + 6
    a = sc.add(Actor(pak_sprite, px, py, z=holder.z - 1, t_in=t0))
    a.move(t0, t0 + 0.7, (px, py - 70), (px, py))
    if label:
        sc.labels.append(Label(label, (a, "top"), label_at, t0 + 0.5))
    return a


def backup(game="ruby", duo_screen=None):
    sc = Scene(13.0)
    lap = sc.add(Actor(parts.laptop(), 10, 104, z=1))
    lap.move(0, 0.7, (-170, 104), (10, 104))
    g = parts.gba("indigo")
    gb = sc.add(Actor(g, 222, 152, z=5))
    gb.move(0, 0.7, (370, 152), (222, 152))
    d = parts.duo()
    gx, gy = 222, 152
    dx = gx + g.anchors["slot"][0] - d.size[0] / 2
    dy = gy + g.anchors["slot"][1] - d.size[1] + 8
    du = sc.add(Actor(d, dx, dy, z=4, t_in=1.0))
    du.move(1.0, 1.7, (dx, dy - 80), (dx, dy))
    sc.labels.append(Label("Action Replay MAX DUO", (du, "edge"), (300, 60), 1.4, 6.5))
    pak = parts.game_pak(game)
    fit_pak(sc, du, pak, 2.4, "your game, in the DUO's slot", (300, 22))
    sc.labels.append(Label("Game Boy Advance", (gb, "led"), (288, 296), 0.9, 6.5))
    mini, usba = parts.usb_mini_b(), parts.usb_a()
    sc.cables.append(Cable((lap, "usb"), (du, "usb"), 3.8, 5.2, rgb("#2c2d35"), width=3, sag=34,
                           plug_a=None, plug_b=mini))
    sc.labels.append(Label("USB lead: Mini-B into the DUO, A into the PC", (lap, "usb"), (170, 250), 4.6, 9))
    sc.caption(0.0, "Backing up a save needs one GBA: the DUO goes in its slot, your game in the DUO", "Step 1")
    sc.caption(3.8, "Connect the DUO to the PC with its USB lead (Mini-B to A)", "Step 1")
    term = typed("python maxduo_saves.py --gba-save", 6.0)
    sc.caption(6.0, "Run maxduo_saves.py --gba-save, then switch the GBA on when it asks", "Step 1")
    sc.terminal = (lap, lambda t: term(t, [(TERM_OUT, "")] + ([(TERM_OUT, "Switch the GBA on...")] if t > 8.6 else [])))
    gb.on_at = 9.6
    gb.screen = lambda t: (duo_screen or screen_on((200, 214, 230))) if t >= 9.6 else None
    sc.caption(9.6, "The save is copied to the saves folder on the PC; the cartridge is only read", "Step 1")
    return sc


def link(game="ruby", cable="agb005", master="either", lines=(), cmd="python duo_events.py", duo_screen=None,
         game_screen=None):
    """The whole link setup and the power-on order."""
    sc = Scene(22.0)
    lap = sc.add(Actor(parts.laptop(left_usb=True), 102, 30, z=1))
    lap.move(0, 0.7, (102, -120), (102, 30))
    gl = parts.gba("glacier")
    gr = parts.gba("indigo")
    L = sc.add(Actor(gl, 16, 200, z=5))
    R = sc.add(Actor(gr, 236, 200, z=5))
    L.move(0, 0.7, (-120, 200), (16, 200))
    R.move(0, 0.7, (370, 200), (236, 200))
    sc.labels.append(Label("the DUO's GBA", (L, "led"), (70, 296), 0.9, 2.3))
    sc.labels.append(Label("the game's GBA", (R, "led"), (290, 296), 0.9, 7))
    # the DUO in the left GBA, with any cartridge in its slot (it needs one to start)
    d = parts.duo()
    dx = 16 + gl.anchors["slot"][0] - d.size[0] / 2
    dy = 200 + gl.anchors["slot"][1] - d.size[1] + 8
    du = sc.add(Actor(d, dx, dy, z=4, t_in=1.2))
    du.move(1.2, 1.9, (dx, dy - 90), (dx, dy))
    sc.labels.append(Label("the DUO", (du, "edge"), (40, 150), 1.6, 5))
    fit_pak(sc, du, parts.game_pak("other"), 2.4, "any GBA cartridge: the DUO needs one to start", (120, 296))
    # the game in the right GBA
    fit_pak(sc, R, parts.game_pak(game), 3.6, f"your game: {GAME_NAMES[game]}", (300, 150))
    # the link cable
    t_c = 5.0
    if cable == "mgb010":
        small, large = parts.mgb010_plug("small"), parts.mgb010_plug("large")
        sc.cables.append(Cable((L, "ext"), (R, "ext"), t_c, t_c + 1.6, rgb("#8f9099"), width=3, sag=56,
                               plug_a=small, plug_b=small, dangling=(large, (-30, -14))))
        sc.labels.append(Label("Universal Game Link Cable MGB-010 (cross-wired)", ((180, 150)), (180, 196), t_c + 1.0, 14))
        sc.labels.append(Label("its split end's big plug isn't used", ((R, "ext")), (250, 120), t_c + 1.8, 11))
        sc.caption(t_c, "Mystery Gift needs a cross-wired Game Boy cable: a Nintendo MGB-010. A GBA cable won't do",
                   "Step 2")
    else:
        purple, grey = parts.agb005_plug(True), parts.agb005_plug(False)
        pa, pb = (purple, grey) if master == "duo" else (grey, purple)
        sc.cables.append(Cable((L, "ext"), (R, "ext"), t_c, t_c + 1.6, rgb("#9c9ea8"), width=2, sag=56,
                               plug_a=pa, plug_b=pb, hub=parts.agb005_hub()))
        sc.labels.append(Label("GBA Game Link Cable AGB-005", ((180, 168)), (180, 196), t_c + 1.0, 14))
        if master == "either":
            sc.caption(t_c, "Both GBAs off. A GBA link cable (AGB-005) joins them, either way round", "Step 2")
        else:
            who = "the game's" if master == "game" else "the DUO's"
            tgt = (R, "ext") if master == "game" else (L, "ext")
            sc.labels.append(Label("small purple plug: the master end", tgt, (300 if master == "game" else 60, 176),
                                   t_c + 1.8, 14))
            sc.caption(t_c, f"Both GBAs off. AGB-005 cable: its small purple plug into {who} GBA (the master)",
                       "Step 2")
    # the USB lead
    mini = parts.usb_mini_b()
    sc.cables.append(Cable((lap, "usb"), (du, "usb"), 7.2, 8.4, rgb("#2c2d35"), width=3, sag=30, plug_b=mini))
    sc.labels.append(Label("USB lead (Mini-B to A)", (lap, "usb"), (60, 60), 7.8, 12))
    sc.caption(7.2, "The DUO's USB lead goes to the PC", "Step 2")
    # the tool, then power on in order
    first = [l for l in lines]
    ready = next((i for i, l in enumerate(first) if "Ready" in l), len(first))
    t_cmd = 10.0
    term = typed(cmd, t_cmd)

    def term_lines(t):
        out = []
        if t > t_cmd + 3.4:
            k = int((t - t_cmd - 3.4) * 5)
            out = [(TERM_OUT, l) for l in first[:min(k, ready + 1)]]
        return term(t, out)
    sc.terminal = (lap, term_lines)
    sc.caption(t_cmd, "Run the tool, and switch on the DUO's GBA when it asks", "Step 3")
    L.on_at = t_cmd + 3.0
    L.screen = lambda t: (duo_screen or screen_on((210, 220, 236))) if t >= t_cmd + 3.0 else None
    sc.badge(t_cmd + 3.0, L, "led", "1")
    t_ready = t_cmd + 3.4 + (ready + 1) / 5 + 0.5
    sc.caption(t_ready, "\"Ready\": now switch on the game's GBA", "Step 4")
    R.on_at = t_ready + 1.0
    R.screen = lambda t: (game_screen or screen_on((248, 248, 248))) if t >= t_ready + 1.0 else None
    sc.badge(t_ready + 1.0, R, "led", "2")
    sc.duration = t_ready + 4.0
    return sc


def games(focus=None):
    """All five Generation III games and what each needs: Ruby and Sapphire take Mystery Events over a
    GBA cable with the game on the master end; Emerald, FireRed and LeafGreen take Mystery Gifts over a
    cross-wired MGB-010; everything else (trades, battles, Record Mixing, the Blender, contests, the
    Battle Tower) goes over a GBA cable either way round."""
    from scene import draw_band
    sc = Scene(9.0)
    order = ["ruby", "sapphire", "emerald", "firered", "leafgreen"]
    xs = [26, 80, 172, 226, 280]
    for i, (g, x) in enumerate(zip(order, xs)):
        a = sc.add(Actor(parts.game_pak(g), x, 66, z=2, t_in=0.25 * i))
        a.move(0.25 * i, 0.25 * i + 0.5, (x, -40), (x, 66))
    purple, grey, hub = parts.agb005_plug(True), parts.agb005_plug(False), parts.agb005_hub()
    small, large = parts.mgb010_plug("small"), parts.mgb010_plug("large")
    sc.cables.append(Cable((40, 176), (110, 176), 2.0, 2.8, rgb("#9c9ea8"), width=2, sag=-34, plug_a=purple,
                           plug_b=grey, hub=hub))
    sc.labels.append(Label("Mystery Event:\nGBA cable AGB-005,\nthe game on the\nsmall purple plug", (75, 202), (75, 256), 2.4))
    sc.cables.append(Cable((190, 176), (296, 176), 4.0, 4.8, rgb("#8f9099"), width=3, sag=-34, plug_a=small,
                           plug_b=small, dangling=(large, (30, 22))))
    sc.labels.append(Label("Mystery Gift:\ncross-wired Game Boy\ncable MGB-010", (243, 202), (243, 256), 4.4))
    sc.labels.append(Label("Ruby, Sapphire", (75, 96), (75, 120), 2.0))
    sc.labels.append(Label("Emerald, FireRed, LeafGreen", (243, 96), (243, 120), 4.0))
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
    for name, sc in (("games", games()), ("backup", backup()), ("link_either", link(lines=demo, cmd="python duo_events.py trade --pk3 offer.pk3")),
                     ("link_event", link("ruby", "agb005", "game", demo)), ("link_gift", link("emerald", "mgb010", lines=demo))):
        for t in (2.0, 4.5, 8.0, sc.duration - 0.5):
            sc.render(t).save(os.path.join(out, f"{name}_{t:04.1f}.png"))
        print(name, sc.duration)
