"""stories.py - what each video shows: the kit, the backup, the cable, the tool's command, and then
the recorded rehearsal with the instruction bar following the tool's own progress lines.

A story is a dict: title, sub, game (ruby|emerald|leafgreen), game_name, master (game|duo|either),
cable (gba|gb), and cues: (text in a tool line, the bar's words) in order. Optional: speed,
((from text, to text, speed), ...) to fast-forward a long stretch; finish, the last words; intro,
the words over the first stretch of the game; unlock, a recorded unlock (see unlock_story).
"""
import re

import setups
from compose import Video, Recording

DROP = ("The DUO's GBA was already on",)       # only ever seen because the emulated DUO starts on


def tidy(line):
    """What the tool prints on the laptop: paths as the person would see them, beside the tools."""
    line = re.sub(r"(/[^\s/]+)+/(received|records|bases|saves)/", r"\2\\", line)
    return line


def lines_of(rec):
    for e in rec.events:
        if "line" in e:
            e["line"] = tidy(e["line"])
    rec.events = [e for e in rec.events if not any(d in e.get("line", "") for d in DROP)]


STORIES = {
    "trade": dict(
        title="Trading a Pokémon to Ruby", sub="duo_events.py trade: any .pk3 goes over by a real trade",
        game="ruby", game_name="Pokémon Ruby (English)", master="either", cable="gba",
        intro="Upstairs in a Pokémon Center: TRADE CENTER with the Cable Club attendant, and let the game save",
        cues=[("in the Trade Center", "In the room, sit at the table: the DUO walks to the other seat"),
              ("chosen: waiting", "Choose a Pokémon you can spare, then YES"),
              ("the trade scene", "The game checks the Pokémon, trades and saves by itself"),
              ("leaving the trade screen", "Whatever you gave is kept on the PC, in the received folder"),
              ("back to the Trade Center", "Choose CANCEL: the DUO walks to the door, and the game follows it out")],
        finish="Done: the game has the Pokémon and has saved. The DUO wrote nothing to either cartridge"),
    "blender": dict(
        title="The Berry Blender with Ruby", sub="duo_events.py blender: a second player for the link Berry Blender",
        game="ruby", game_name="Pokémon Ruby (English)", master="either", cable="gba",
        intro="In a Contest Lobby, talk to a link Berry Blender and let the game save",
        cues=[("the link-up", "Linked: the DUO joins the blender as the second player"),
              ("the countdown", "Choose a berry: the DUO brings an Oran"),
              ("blending", "Press A as your arrow passes the top: the DUO presses for its own"),
              ("blend another berry", "Your Pokéblock is made: choose not to blend another"),
              ("done", "The link is closed, and the tool reports both players' hits")],
        finish="Done: a Pokéblock in the game's case, and the hits for both players on the PC"),
    "battle": dict(
        title="A link battle with Ruby", sub="duo_events.py colosseum: the DUO's team in the Colosseum",
        game="ruby", game_name="Pokémon Ruby (English)", master="either", cable="gba",
        intro="Upstairs in a Pokémon Center: COLOSSEUM with the attendant, then SINGLE BATTLE, and let the game save",
        cues=[("in the Cable Club", "In the Colosseum, stand on your spot: the DUO walks to the other"),
              ("swapping teams", "The game and the DUO swap teams over the link"),
              ("battling", "The battle: you choose your moves, and the DUO plays its team"),
              ("the battle is over", "The battle's over: both players walk back out of the room")],
        speed=[("battling", "the battle is over", 3)],
        finish="Done: a whole link battle, with the PC following every turn"),
    "double_battle": dict(
        title="A double battle with Ruby", sub="duo_events.py colosseum: two at a time in the Colosseum",
        game="ruby", game_name="Pokémon Ruby (English)", master="either", cable="gba",
        intro="Upstairs in a Pokémon Center: COLOSSEUM with the attendant, then DOUBLE BATTLE, and let the game save",
        cues=[("in the Cable Club", "In the Colosseum, stand on your spot: the DUO walks to the other"),
              ("swapping teams", "The game and the DUO swap teams over the link"),
              ("battling", "A double battle: two of yours against two of the DUO's"),
              ("the battle is over", "The battle's over: both players walk back out of the room")],
        speed=[("battling", "the battle is over", 3)],
        finish="Done: a double battle, with the PC following every turn"),
    "record_mixing": dict(
        title="Secret Bases by Record Mixing", sub="duo_events.py mix: bases, songs and trends go into Ruby",
        game="ruby", game_name="Pokémon Ruby (English)", master="either", cable="gba",
        intro="Upstairs in a Pokémon Center: RECORD CORNER with the attendant on the right, and let the game save",
        cues=[("in the Record Corner", "In the room, sit at the table on your side: the DUO takes a seat on its side"),
              ("mixing records", "Mixing records: the DUO brings a Secret Base, the old man's song and a trend"),
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
    v = Video(out, s["title"], s["game_name"], crf=crf)
    v.title_card(s["title"], s["sub"])
    v.scene(setups.games())
    v.scene(setups.backup(game, duo_screen=rec.image(40, "duo")))
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
    v.title_card(s["title"], END, 4)
    return v.close()


def gift_story(out, unlock_rec, crf=20):
    """Mystery Gift: the questionnaire unlock (recorded), then the cable and the steps to receive a card.
    (No rehearsal of receiving yet, so no game footage of it, and no tool output is shown.)"""
    rec = Recording(unlock_rec)
    title = "Mystery Gift with Emerald"
    v = Video(out, title, "Pokémon Emerald (English)", crf=crf)
    v.title_card(title, "duo_events.py gift: the DUO's GBA plays a Wireless Adapter\nover a cross-wired Game Boy cable")
    v.scene(setups.games())
    v.scene(setups.backup("emerald"))
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
    v.title_card(title, "Received on hardware: Japanese Emerald, English LeafGreen\n(English Emerald in the simulator)", 5)
    return v.close()


def make(name, out, rec_dir, crf=20, unlock_rec=None):
    if name == "mystery_gift":
        return gift_story(out, unlock_rec, crf)
    s = dict(STORIES[name])
    if s.get("unlock"):
        s["unlock_rec"] = unlock_rec
    return link_story(out, rec_dir, s, crf)
