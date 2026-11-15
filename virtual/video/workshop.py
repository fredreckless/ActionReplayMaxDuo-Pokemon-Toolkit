"""workshop.py - the Secret Base Workshop (secret_base_workshop.html), driven in a real browser to
make the .sb3 the Record Mixing video brings, with screenshots of each step for the video: a tree
house, designed by the workshop's own Generate (decorations by the game's rules, an owner, a team).
The room is drawn from the ROM's own tiles and decorations (the workshop reads them from the ROM).

    python3 virtual/video/workshop.py --rom RUBY.gba --out DIR

DIR gets step_NN.png and steps.json (each step's picture and words) and the base, willow.sb3.
Needs Playwright with Chrome (pip install playwright; it uses the installed google-chrome).
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLKIT = os.path.dirname(os.path.dirname(HERE))
PAGE = os.path.join(TOOLKIT, "secret_base_workshop.html")



def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rom", required=True)
    ap.add_argument("--out", required=True)
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
        # Generate: the workshop's own designer fills the room with a themed set of decorations that
        # keep to the game's rules, and gives the base an owner and a team; twice, for two ideas
        for k in range(2):
            page.click("#genBtn")
            page.wait_for_timeout(400)
            note = page.inner_text("#genNote")
            if k == 0:
                shot("Generate: the workshop designs a room by the game's rules (Solid Boards over the holes)")
            else:                                         # the whole designer: the slide scrolls down it
                page.evaluate("() => document.querySelectorAll('.panel details').forEach(d => d.open = false)")
                page.wait_for_timeout(200)
                shot("Generate again for another idea: " + note.split(":")[0].lower(), ".panel:has(#board)")
        shot("The owner and their team, ready to battle anyone who visits", "#team")
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
    print(("PASS" if size == 160 else "FAIL") + f": a generated base, {path} ({size} bytes)")
    return 0 if size == 160 else 1


if __name__ == "__main__":
    sys.exit(main())
