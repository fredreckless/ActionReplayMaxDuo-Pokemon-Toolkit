"""workshop.py - the Secret Base Workshop (secret_base_workshop.html), driven in a real browser to
make the .sb3 the Record Mixing video brings, with screenshots of each step for the video. The room
is drawn from the ROM's own tiles and decorations (the workshop reads them from the ROM it's given).

    python3 virtual/video/workshop.py --rom RUBY.gba --out DIR

DIR gets step_NN.png and steps.json (each step's picture and words) and the base, willow.sb3.
Needs Playwright with Chrome (pip install playwright; it uses the installed google-chrome).
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLKIT = os.path.dirname(os.path.dirname(HERE))
PAGE = os.path.join(TOOLKIT, "secret_base_workshop.html")

# the base: a tree house on Route 119... whichever spot the list offers first of the kind; then
# (decoration name, x, y): its bottom-left tile
LAYOUT = [("RED BRICK", 1, 6), ("RED BRICK", 2, 6), ("PRETTY DESK", 4, 5), ("PRETTY CHAIR", 4, 6),
          ("SMALL DESK", 7, 5), ("TV", 7, 4), ("PIKACHU DOLL", 1, 4), ("RED PLANT", 9, 6),
          ("PIKA POSTER", 5, 1)]
TEAM = [("SALAMENCE", 50), ("METAGROSS", 50), ("MILOTIC", 50)]


def strong_moves(species, level):
    """savegen's elite_moves (the strongest attack of each type it can know), by name."""
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "savegen"))
    sys.path.insert(0, TOOLKIT)
    import duo_battle as B
    import savegen
    return [B.move_name(m).title() for m in savegen.elite_moves(B.species_id(species), level)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rom", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="WILLOW")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    os.makedirs(a.out, exist_ok=True)
    steps = []
    with sync_playwright() as pw:
        br = pw.chromium.launch(executable_path="/usr/bin/google-chrome" if os.path.exists("/usr/bin/google-chrome")
                                else None, args=["--allow-file-access-from-files"])
        page = br.new_page(viewport={"width": 1280, "height": 1000}, accept_downloads=True)
        page.goto("file://" + PAGE)
        page.wait_for_timeout(800)

        def shot(words, sel=".boardbox"):
            path = os.path.join(a.out, f"step_{len(steps):02d}.png")
            if sel is None:                                # the page as it first looks
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(250)
                page.screenshot(path=path)
            else:
                el = page.locator(sel).first
                el.scroll_into_view_if_needed()
                page.wait_for_timeout(250)
                el.screenshot(path=path)
            steps.append(dict(png=os.path.basename(path), words=words))

        page.set_input_files("#romFile", a.rom)
        page.wait_for_function("document.getElementById('romNote').textContent.startsWith('Using')", timeout=60000)
        shot("Open the Secret Base Workshop, and give it your ROM: the room is drawn from the game's own tiles",
             None)
        page.click("#newBtn")                             # an empty base (it opens with an example)
        page.wait_for_timeout(300)
        page.select_option("#kind", "tree")
        page.wait_for_timeout(300)
        big = page.evaluate("""() => { const o = [...document.querySelectorAll('#spot option')];
            const r4 = o.find(x => x.textContent.includes('room 4')); return (r4 || o[0]).value }""")
        page.select_option("#spot", big)
        page.wait_for_timeout(400)
        shot("Choose where the base is: the kind of spot, then the spot itself")
        names = page.evaluate("""() => [...document.querySelectorAll('#cats button[data-cat]')].map(b => b.dataset.cat)""")
        def find_button(name):
            for cat in names:
                page.click(f"#cats button[data-cat='{cat}']")
                page.wait_for_timeout(80)
                b = page.evaluate("""(n) => { const x = [...document.querySelectorAll('#palette button[data-d]')]
                    .find(b => (b.title || b.textContent).toUpperCase().includes(n)); return x ? x.dataset.d : null }""", name)
                if b:
                    return b
            return None
        placed = 0
        for name, x, y in LAYOUT:
            d = find_button(name)
            if d is None:
                print(f"  (no {name} in the palette)")
                continue
            # the tile asked for if it's free floor that fits; otherwise the next one that does (the
            # workshop says "(but ...)" when a placement breaks one of the game's rules: remove it, try on)
            floor = page.evaluate("""() => [...document.querySelectorAll('#board .cell')]
                .filter(c => c.dataset.t === '.').map(c => [+c.dataset.x, +c.dataset.y])""")
            floor.sort(key=lambda c: (abs(c[0] - x) + abs(c[1] - y), c))
            ok = False
            for cx, cy in floor[:40]:
                page.click(f"#palette button[data-d='{d}']")
                page.click(f"#board .cell[data-x='{cx}'][data-y='{cy}']")
                page.wait_for_timeout(120)
                if "(but " not in page.inner_text("#tileStatus"):
                    ok = True
                    break
                page.click("#moverDel")                    # (it's selected once placed: remove it)
                page.wait_for_timeout(80)
            if not ok:
                continue
            placed += 1
            shot(f"Decorations: pick one, then the tile for its bottom-left corner ({name.title()})")
        page.fill("#oname", a.name)
        page.dispatch_event("#oname", "change")
        for i, (sp, lv) in enumerate(TEAM):
            page.click("#addMon")
            page.wait_for_timeout(150)
            box = page.locator(f"#team .mon[data-k='{i}'] input[data-f='species']")
            box.fill(sp)
            box.dispatch_event("change")
            lvl = page.locator(f"#team .mon[data-k='{i}'] input[data-f='level']")
            if lvl.count():
                lvl.fill(str(lv))
                lvl.dispatch_event("change")
            for j, mv in enumerate(strong_moves(sp, lv)):  # four strong moves of different types
                box = page.locator(f"#team .mon[data-k='{i}'] input[data-f='move'][data-j='{j}']")
                if box.count():
                    box.fill(mv)
                    box.dispatch_event("change")
                    page.wait_for_timeout(60)
        page.wait_for_timeout(300)
        shot("The owner's name, and the team they'll battle with if someone visits", "#team")
        shot("The Checks: everything the game will check, before it's saved", "#checks")
        with page.expect_download() as dl:
            page.click("#saveSb3")
        path = os.path.join(a.out, "willow.sb3")
        dl.value.save_as(path)
        shot("Save the .sb3: the exact 160 bytes the game keeps for a base", "#bytes")
        br.close()
    with open(os.path.join(a.out, "steps.json"), "w") as f:
        json.dump(steps, f, indent=1)
    size = os.path.getsize(path)
    print(("PASS" if size == 160 and placed else "FAIL") + f": {placed} decorations, {path} ({size} bytes)")
    return 0 if size == 160 else 1


if __name__ == "__main__":
    sys.exit(main())
