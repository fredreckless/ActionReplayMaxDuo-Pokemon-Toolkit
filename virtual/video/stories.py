"""stories.py - what each video shows: the kit, the backup, the cable, the tool's command, and then
the recorded rehearsal with the instruction bar following the tool's own progress lines.

A story is a dict: title, sub, game (ruby|emerald|leafgreen), game_name, master (game|duo|either),
cable (gba|gb), and cues: (text in a tool line, the bar's words) in order. Optional: speed,
((from text, to text, speed), ...) to fast-forward a long stretch; finish, the last words; intro,
the words over the first stretch of the game; unlock, a recorded unlock (see unlock_story).
"""
import os, re

import setups
from PIL import Image
from compose import Video, Recording

DROP = ("The DUO's GBA was already on",)       # only ever seen because the emulated DUO starts on


def tidy(line):
    """What the tool prints on the laptop: paths as the person would see them, beside the tools."""
    line = re.sub(r"(/[^\s/]+)+/(received|records|bases|saves)/", r"\2\\", line)
    return line


GBA_FPS = 16777216 / 280896                    # 59.7275 frames a second
REC_STEP = 2                                   # recorded every second frame (make_videos.py's VDUO_RECORD_STEP)


def lines_of(rec):
    """The tool's lines as the laptop shows them. The tool times its progress lines ("[  2.5 s]")
    by the PC's clock, which in a rehearsal runs at the emulator's speed, not the game's: they're
    timed again here from the frame each line came at (the first keeps its own time)."""
    stamp = re.compile(r"^(\s*)\[\s*([\d.]+) s\]")
    first = None
    for e in rec.events:
        if "line" not in e:
            continue
        e["line"] = tidy(e["line"])
        m = stamp.match(e["line"])
        if m:
            if first is None:
                first = (e["n"], float(m.group(2)))
            t = first[1] + (e["n"] - first[0]) * REC_STEP / GBA_FPS
            e["line"] = f"{m.group(1)}[{t:6.1f} s]" + e["line"][m.end():]
    rec.events = [e for e in rec.events if not any(d in e.get("line", "") for d in DROP)]


STORIES = {
    "trade": dict(
        title="Trading a Pokémon to FireRed", sub="duo_events.py trade: any .pk3 goes over by a real trade",
        game="firered", game_name="Pokémon FireRed (English)", master="either", cable="gba",
        intro="Upstairs in a Pokémon Center: the Cable Club attendant, TRADE CENTER, and let the game save",
        cues=[("in the Trade Center", "In the room, sit at the table: the DUO walks to the other seat"),
              ("chosen: waiting", "Choose a Pokémon you can spare, then YES: the DUO offers a real event Pokémon"),
              ("the trade scene", "The game checks the Pokémon, trades and saves by itself"),
              ("leaving the trade screen", "Whatever you gave is kept on the PC, in the received folder"),
              ("back to the Trade Center", "Choose CANCEL: the DUO walks to the door, and the game follows it out")],
        finish="Done: the game has the Pokémon and has saved. The DUO wrote nothing to either cartridge"),
    "blender": dict(
        title="The Berry Blender with Sapphire", sub="duo_events.py blender: a second player for the link Berry Blender",
        game="sapphire", game_name="Pokémon Sapphire (English)", master="either", cable="gba",
        intro="In a Contest Lobby, talk to a link Berry Blender and let the game save",
        cues=[("the link-up", "Linked: the DUO joins the blender as the second player"),
              ("the countdown", "Choose a berry: the DUO brings an Oran"),
              ("blending", "Press A as your arrow passes the top: the DUO presses for its own"),
              ("blend another berry", "Your Pokéblock is made: choose not to blend another"),
              ("done", "The link is closed, and the tool reports both players' hits")],
        finish="Done: a Pokéblock in the game's case, and the hits for both players on the PC"),
    "battle": dict(
        title="A link battle with LeafGreen", sub="duo_events.py colosseum: the DUO's team in the Colosseum",
        game="leafgreen", game_name="Pokémon LeafGreen (English)", master="either", cable="gba",
        intro="Upstairs in a Pokémon Center: the Cable Club attendant, COLOSSEUM, SINGLE BATTLE, and let the game save",
        cues=[("in the Cable Club", "In the Colosseum, stand on your spot: the DUO walks to the other"),
              ("swapping teams", "The game and the DUO swap teams over the link"),
              ("battling", "The battle: you play your moves, and the PC plays the DUO's event Pokémon"),
              ("the battle is over", "The battle's over: both players walk back out of the room")],
        speed=[("battling", "the battle is over", 3)],
        finish="Done: a whole link battle, with the PC following every turn"),
    "double_battle": dict(
        title="A double battle with Sapphire", sub="duo_events.py colosseum: two at a time in the Colosseum",
        game="sapphire", game_name="Pokémon Sapphire (English)", master="either", cable="gba",
        intro="Upstairs in a Pokémon Center: COLOSSEUM with the attendant, then DOUBLE BATTLE, and let the game save",
        cues=[("in the Cable Club", "In the Colosseum, stand on your spot: the DUO walks to the other"),
              ("swapping teams", "The game and the DUO swap teams over the link"),
              ("battling", "A double battle: two of yours against two of the DUO's"),
              ("the battle is over", "The battle's over: both players walk back out of the room")],
        speed=[("battling", "the battle is over", 3)],
        finish="Done: a double battle, with the PC following every turn"),
    "record_mixing": dict(
        title="Secret Bases by Record Mixing", sub="duo_events.py mix: a Secret Base made in the workshop goes into Ruby",
        game="ruby", game_name="Pokémon Ruby (English)", master="either", cable="gba",
        intro="Upstairs in a Pokémon Center: RECORD CORNER with the attendant on the right, and let the game save",
        cues=[("in the Record Corner", "In the room, sit at the table on your side: the DUO takes a seat on its side"),
              ("mixing records", "Mixing records: the DUO brings the Secret Base"),
              ("mixed: the game is saving", "The game files what it was given by its own rules, and saves"),
              ("walking back to the door", "Walk out, or wait: the DUO stands up and leaves, and the game follows")],
        finish="Done: the base is in the game, and the game's own bases are kept on the PC"),
    "mystery_event": dict(
        title="Mystery Event with Ruby", sub="duo_events.py event: the DUO plays the e-Reader over the link cable",
        game="ruby", game_name="Pokémon Ruby (English)", master="game", cable="gba",
        intro="On the title menu, choose MYSTERY EVENTS, and press A when it asks", unlock="mystery_event",
        cues=[("link up", "Linked: the DUO plays the e-Reader"),
              ("sent the Mystery Event", "The event goes over, and the game checks it"),
              ("the game closed the link", "The game runs the event, saves, and shows its message")],
        finish="Done: for the Eon Ticket, go and see your Dad at Petalburg City Gym"),
    "contest": dict(
        title="A link contest with Emerald", sub="duo_events.py contest: the DUO enters a Pokémon of its own",
        game="emerald", game_name="Pokémon Emerald (English)", master="either", cable="gba",
        intro="In Lilycove's Contest Hall, talk to the link contest receptionist and let the game save",
        cues=[("the link-up", "Linked: the DUO enters as the other contestant"),
              ("setting up", "The game sets out the contestants, the category and the order"),
              ("the contest", "The contest: the PC plans the DUO's appeals from their contest effects"),
              ("the results", "The results: the game works out who came where")],
        speed=[("the contest", "the results", 2)],
        finish="Done: the tool says where each of you came"),
    "battle_tower": dict(
        title="The Battle Tower with Emerald", sub="duo_events.py tower: the DUO as your multi battle partner",
        game="emerald", game_name="Pokémon Emerald (English)", master="either", cable="gba",
        intro="In the Battle Tower, choose LINK MULTI BATTLE with the attendant, then your two Pokémon",
        cues=[("the lobby's link-up", "Linked: the game saves, and the DUO joins you as your partner"),
              ("between battles", "Up in the elevator and along the corridor, side by side"),
              ("a battle's link", "Into the battle room: the game and the DUO swap teams"),
              ("battling", "A multi battle: you and the DUO each command your own two"),
              ("carry on or retire", "Carry on or retire? The DUO retires after the first battle here")],
        speed=[("battling", "carry on or retire", 3)],
        finish="Done: the challenge is over and the game has saved"),
}


UNLOCKS = {
    "mystery_event": dict(
        menu="MYSTERY EVENTS",
        cues=[("boot", "Switch on the game on its own (no cable needed for this part), and CONTINUE"),
              ("talk", "In Petalburg City's Pokémon Center, after beating Norman: talk to the man by the PC"),
              ("profile", "YES: he wants to see your profile. SELECT for A-Z mode, then each word by its letter"),
              ("MYSTERY", "Word 1: MYSTERY, the last word under M"),
              ("EVENT", "Word 2: EVENT, under E"),
              ("IS", "Word 3: IS, under I"),
              ("EXCITING", "Word 4: EXCITING, under E"),
              ("ok", "OK, then YES"),
              ("secret", "\"You know the secret saying!\" MYSTERY EVENT is unlocked"),
              ("save", "Save the game: START, then SAVE"),
              ("restart", "Switch the game off and on again"),
              ("menu", "The title menu now has MYSTERY EVENTS")],
        speed=[("boot", "talk", 3), ("restart", "menu", 2)]),
    "mystery_gift": dict(
        menu="MYSTERY GIFT",
        cues=[("boot", "Switch on the game on its own (no cable needed for this part), and CONTINUE"),
              ("talk", "In any Poké Mart, once you have the Pokédex: read the questionnaire on the counter"),
              ("profile", "Fill it out: SELECT for A-Z mode, then each word by its letter"),
              ("LINK", "Word 1: LINK, under L"),
              ("TOGETHER", "Word 2: TOGETHER, under T"),
              ("WITH", "Word 3: WITH, under W"),
              ("ALL", "Word 4: ALL, under A"),
              ("ok", "OK, then YES"),
              ("secret", "\"You know those words!\" MYSTERY GIFT is unlocked"),
              ("save", "Save the game: START, then SAVE"),
              ("restart", "Switch the game off and on again"),
              ("menu", "The title menu now has MYSTERY GIFT")],
        speed=[("boot", "talk", 3), ("restart", "menu", 2)]),
}


def play_marked(v, rec, cues, speed, step):
    """A recording with marks (unlock.py's): the bar follows the marks, some stretches fast."""
    at = {e["mark"]: e["n"] for e in rec.events if "mark" in e}
    cue = sorted((at[m], words, step) for m, words in cues if m in at)
    marks = sorted({0, rec.n} | {at[a] for a, b, x in speed if a in at} | {at[b] for a, b, x in speed if b in at})
    fast = {at[a]: x for a, b, x in speed if a in at}
    v.say(cue[0][1], step)
    for a, b in zip(marks, marks[1:]):
        v.play(rec, a, b, speed=fast.get(a, 1), cues=[c for c in cue if a <= c[0] < b], shown_from=0)


END = "Action Replay MAX DUO, Reckless firmware\ngithub.com/fredreckless/ActionReplayMaxDuo-Pokemon-Toolkit"


def link_story(out, rec_dir, s, crf=20):
    rec = Recording(rec_dir)
    lines_of(rec)
    game = s["game"]
    v = Video(out, s["title"], s["game_name"], crf=crf, theme=s.get("theme"))
    v.overview()
    v.setup()
    v.title_card(s["title"], s["sub"])
    v.scene(setups.games("gba", focus=game))
    if s.get("workshop"):
        import json
        from PIL import Image
        steps = json.load(open(os.path.join(s["workshop"], "steps.json")))
        main = ("Open", "Generate again", "The owner", "Save")     # the main parts only, as slides
        for st in steps:
            if st["words"].startswith(main):
                v.still(Image.open(os.path.join(s["workshop"], st["png"])), st["words"], "Workshop", secs=3.4)
    if s.get("unlock"):
        u = UNLOCKS[s["unlock"]]
        play_marked(v, Recording(s["unlock_rec"]), u["cues"], u["speed"], "Unlock")
        v.crossfade()
    first = [e["line"] for e in rec.events if "line" in e and e["n"] == 0]
    cable = "agb005"
    v.scene(setups.link(game, cable, s["master"], first, rec.cmd, duo_screen=rec.image(40, "duo"),
                        game_screen=rec.image(0, "partner")))
    # the panels pick up where the scene left off: the command and the tool's opening lines
    v.term = [("cmd", "C:\\ActionReplay> " + rec.cmd)]
    v.print_lines(first)
    cues, after = [(0, s["intro"], "In the game")], 0
    for text, words in s["cues"]:
        n = rec.find(text, after)
        if n is not None:
            cues.append((n, words, "In the game"))
            after = n
    last = min(rec.n, max(e["n"] for e in rec.events) + 30)
    marks, speeds = [0], {}
    for start, stop, x in s.get("speed", ()):
        a, b = rec.find(start), rec.find(stop)
        if a is not None and b is not None and b > a:
            marks += [a, b]
            speeds[a] = x
    marks = sorted(set(m for m in marks if m < last)) + [last]
    shown = len(first)
    for a, b in zip(marks, marks[1:]):
        v.play(rec, a, b, speed=speeds.get(a, 1), cues=[c for c in cues if a <= c[0] < b], shown_from=shown)
        shown = len(rec.lines_until(b - 1))
    v.say(s["finish"], "Done")
    v.hold(5)
    v.crossfade()
    if s.get("visit_rec"):
        c = Recording(s["visit_rec"])
        v.term, v.duo = [], None
        play_marked(v, c, VISIT, [], "In the game")
        v.crossfade()
    v.title_card(s["title"], END, 4)
    return v.close()


CLAIM = [("title", "Proof: the card, kept as the game keeps one it has received (put in the save here: the "
                    "emulator can't rehearse the adapter yet)"),
         ("continue", "CONTINUE, and upstairs in a Pokémon Center"),
         ("talk", "Talk to the Mystery Gift man, in green, on the left"),
         ("got", "He hands over what the card promised: it's in the bag")]


def gift_story(out, unlock_rec, crf=20, claim_rec=None, theme=None):
    """Mystery Gift: the questionnaire unlock (recorded), then the cable and the steps to receive a card.
    (No rehearsal of receiving yet, so no game footage of it, and no tool output is shown.)"""
    rec = Recording(unlock_rec)
    title = "Mystery Gift with Emerald"
    v = Video(out, title, "Pokémon Emerald (English)", crf=crf, theme=theme)
    v.overview()
    v.setup()
    v.title_card(title, "duo_events.py gift: the DUO's GBA plays a Wireless Adapter\nover a cross-wired Game Boy cable")
    v.scene(setups.games("gb", focus="emerald"))
    u = UNLOCKS["mystery_gift"]
    play_marked(v, rec, u["cues"], u["speed"], "Unlock")
    menu = v.game
    sc = setups.link("emerald", "mgb010", "either", [], 'python duo_events.py gift --card "YOUR CARD.wc3"',
                     game_screen=menu)
    v.scene(sc)
    v.term = [("cmd", 'C:\\ActionReplay> python duo_events.py gift --card "YOUR CARD.wc3"')]
    v.game, v.duo = menu, None
    v.say("On the game: MYSTERY GIFT, then WONDER CARDS, then WIRELESS COMMUNICATION", "Step 5")
    v.hold(5)
    v.say("The game receives the card and saves it; the tool stops by itself", "Step 6")
    v.hold(4)
    v.say("Then collect the gift as the card says: in Emerald, upstairs in any Pokémon Center", "Done")
    v.hold(4)
    v.crossfade()
    if claim_rec:
        c = Recording(claim_rec)
        v.term, v.duo = [], None
        play_marked(v, c, CLAIM, [], "In the game")
        v.crossfade()
    v.title_card(title, "Received on hardware: Japanese Emerald, English LeafGreen\n(English Emerald in the simulator)", 5)
    return v.close()


VISIT = [("arrive", "Then go and see it: here, straight to its spot on the route (the emulator's shortcut)"),
         ("walk", "Its entrance is open on the map: walk in"),
         ("inside", "The base, as it was made in the workshop, with its owner waiting to battle"),
         ("talk", "Talk to the owner (after the Champion, they'll battle)"),
         ("battle", "The owner battles with the team made in the workshop")]


def make(name, out, rec_dir, crf=20, unlock_rec=None, workshop=None, claim_rec=None, visit_rec=None, theme=None):
    if name == "mystery_gift":
        return gift_story(out, unlock_rec, crf, claim_rec, theme)
    s = dict(STORIES[name])
    s["theme"] = theme
    if workshop:
        s["workshop"] = workshop
    if visit_rec:
        s["visit_rec"] = visit_rec
    if s.get("unlock"):
        s["unlock_rec"] = unlock_rec
    return link_story(out, rec_dir, s, crf)


# ------------------------------------------------------------------ Mystery Gift with LeafGreen (21 November 2026)
# The first Mystery Gift video with the transfer itself recorded: the Virtual DUO's normal-mode wire
# (runner/vduo.c) lets the real game and the real DUO program talk as the game and its Wireless Adapter.

FRLG_UNLOCK = [("boot", "Switch on the game on its own (no cable needed for this part), and CONTINUE"),
               ("talk", "In any Poké Mart once you have the Pokédex (here Pewter City's): the questionnaire"),
               ("profile", "Fill it out: SELECT for A-Z mode, then each word by its letter"),
               ("word1", "Word 1: LINK, under L"),
               ("word2", "Word 2: TOGETHER, under T"),
               ("word3", "Word 3: WITH, under W"),
               ("word4", "Word 4: ALL, under A"),
               ("ok", "OK, then YES"),
               ("secret", "MYSTERY GIFT is unlocked"),
               ("save", "Save the game: START, then SAVE"),
               ("restart", "Switch the game off and on again"),
               ("menu", "The title menu now has MYSTERY GIFT")]
FRLG_GIFT_CUES = [("ID exchange completed", "The game finds a Wireless Adapter: the DUO's GBA is playing one"),
                  ("start searching", "The game searches for a distributor: the DUO is that too"),
                  ("the game connected to the distributor", "Connected: the distributor starts sending"),
                  ("Mystery Gift server step 3", "The Wonder Card goes over, then the script that comes with it"),
                  ("disconnect", "Done: the link closes, and the tool stops by itself")]
FRLG_CLAIM = [("title", "Afterwards: switch the game on again, and CONTINUE"),
              ("continue", "Upstairs in any Pokémon Center: the delivery person in green has come"),
              ("walk", "Walk over and talk to them, across the counter"),
              ("got", "The MYSTIC TICKET, in the KEY ITEMS pocket"),
              ("bag", "BAG, KEY ITEMS: the ticket to Navel Rock")]
JAPANESE = re.compile(r"[\u3040-\u30ff]")


NAVEL = [("vermilion", "With the Rainbow Pass, Vermilion City's harbour: show the sailor the ticket"),
         ("sail", "NAVEL ROCK: the Seagallop sets sail"),
         ("harbor", "Navel Rock, an island only the ticket reaches"),
         ("exterior", "Up to the rock itself, and in"),
         ("base", "Down through the rock to its foot (the climb skipped here)"),
         ("lugia", "And there it is")]


def play_full(v, rec, a, b, cues=(), speed=1.0, step=None):
    """Recorded frames a..b with the game full width (no terminal or DUO panels: the game alone),
    its own sound, and the band below for the words."""
    from compose import S, BG, blank
    from scene import draw_band
    cues = sorted(cues)
    caption, stp = None, step
    pos = float(a)
    while pos < b:
        i = int(pos)
        while cues and cues[0][0] <= i:
            _, caption, stp = cues.pop(0)
        frame = Image.new("RGB", (S, S), BG)
        g = rec.image(i, "partner")
        frame.paste(g.resize((S, 720), Image.NEAREST), (0, 90))
        if caption:
            draw_band(frame, caption, stp, S - 132)
        snd = rec.sound(i) if speed <= 1 else None
        if snd:
            v.sounds.append((v.frames, rec.pcm) + snd)
        v.emit(full=frame)
        pos += speed


def frlg_gift_story(out, gift_rec, unlock_rec, claim_rec, card_name, crf=20, theme=None, navel_rec=None):
    title = "The Mystic Ticket in LeafGreen"
    rec = Recording(gift_rec)
    lines_of(rec)
    rec.events = [e for e in rec.events if not JAPANESE.search(e.get("line", ""))]
    rec.cmd = f'python duo_events.py gift --card "{card_name}"'
    v = Video(out, title, "Pokémon LeafGreen (English)", crf=crf, theme=theme)
    nav = Recording(navel_rec) if navel_rec else None
    if nav:                                                   # the cold open: up to Lugia, the battle fading in
        at = {e["mark"]: e["n"] for e in nav.events if "mark" in e}
        # up to the moment the screen has faded to black for the battle: not the battle itself
        black = next((i for i in range(at["lugia"], at["battle"]) if max(nav.image(i, "partner").getextrema(),
                                                                          key=lambda e: e[1])[1] < 12), at["battle"])
        # from once the arrival's fade and the map's name have cleared (unlock.py's "approach")
        start = next((i for i in range(at.get("approach", at["base"]), at["lugia"])
                      if not any(x >= 200 for x in nav.image(i, "partner").convert("L").crop((60, 150, 180, 160)).get_flattened_data())
                      and nav.image(i, "partner").convert("L").getpixel((120, 10)) < 240),
                     at["base"])
        play_full(v, nav, start, black + 1)
        v.dip(out=0.2, black=0.8, back=0.8)                   # (the game's own fade to black, held)
        v.title_card("Handing out a Pokémon event\nwith an Action Replay",
                     "The Mystic Ticket in LeafGreen, by real Mystery Gift:\n"
                     "from a MAX DUO on the PC to the game, over a link cable", 5)
        v.dip()
    v.overview(secs=15)
    v.dip(out=0.3, black=0.3, back=0.3)
    v.setup()
    v.dip()
    v.title_card(title, "duo_events.py gift: the DUO's GBA plays the Wireless Adapter and the\n"
                        "distributor, over a cross-wired Game Boy Color link cable")
    v.dip()
    v.scene(setups.games("cgb", focus="leafgreen"))
    u = Recording(unlock_rec)
    play_marked(v, u, FRLG_UNLOCK, [("boot", "talk", 3), ("word1", "ok", 5), ("restart", "menu", 2)], "Unlock")
    v.dip()
    first = [e["line"] for e in rec.events if "line" in e and e["n"] == 0]
    v.scene(setups.link("leafgreen", "cgb003", "either", first, rec.cmd, duo_screen=rec.image(40, "duo"),
                        game_screen=rec.image(0, "partner")))
    v.term = [("cmd", "C:\\ActionReplay> " + rec.cmd)]
    v.print_lines(first)
    cues, after = [(0, "On the game: MYSTERY GIFT, then A: it looks for a Wireless Adapter", "In the game")], 0
    for text, words in FRLG_GIFT_CUES:
        n = rec.find(text, after)
        if n is not None:
            cues.append((n, words, "In the game"))
            after = n
    end = max(e["n"] for e in rec.events if "line" in e)
    cues.append((min(rec.n - 1, end + 20), "The game saves the card by itself: \"Save completed\"", "In the game"))
    bar = rec.image(end, "partner").getpixel((120, 4))        # the Mystery Gift screen's title bar
    card_at = next((i for i in range(end, rec.n) if rec.image(i, "partner").getpixel((120, 4)) != bar
                    and max(rec.image(i, "partner").getpixel((120, 4))) > 100), rec.n - 1)
    cues.append((card_at, "WONDER CARDS: the Mystic Ticket's Exchange Card, as the event's", "In the game"))
    v.play(rec, 0, card_at, cues=[c for c in cues if c[0] < card_at], shown_from=len(first))
    v.play(rec, card_at, rec.n, cues=[c for c in cues if c[0] >= card_at], idle=4.5,     # (the card: time to read it)
           shown_from=len(rec.lines_until(card_at - 1)))
    v.dip()
    c = Recording(claim_rec)
    c_end = next((e["n"] for e in c.events if e.get("mark") == "end"), None)
    if c_end:
        c.n = min(c.n, c_end + 30)                            # (not the save made afterwards for the trip)
    v.term, v.duo = [], None
    play_marked(v, c, FRLG_CLAIM, [], "In the game")
    v.dip()
    v.title_card("As legit as it gets", "To the game this was a real Mystery Gift: its own menu, its own\n"
                 "checks, its own save. The card is the event's own, byte for byte,\n"
                 "and the ticket and the ferry's flag came from the game's own script.\n"
                 "The DUO writes nothing to either cartridge.", 7)
    v.dip()
    if nav:
        cues = [(at[m], words, "Navel Rock") for m, words in NAVEL if m in at]
        play_full(v, nav, at["vermilion"], at["cave"], cues=[c for c in cues if c[0] < at["cave"]])
        v.dip()
        play_full(v, nav, at.get("approach", at["base"]) - 40, at["end"], cues=[c for c in cues if c[0] >= at["base"]])
        v.emit(v.seconds(1.5), full=v._shown)                 # (Lugia, held: nothing sent out)
        v.dip()
    v.title_card(title, "Recorded in the Virtual DUO: the real game, the DUO's real program\n"
                        "(the save's story set ahead for the ferry: it wants the Rainbow Pass)\n\n"
                        + END, 7)
    return v.close()
