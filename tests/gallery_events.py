"""gallery_events.py - real event files from the Events Gallery through the real tool and the real DUO
programs, in the simulator, against its models of the games (14 November 2026). For the files the
Virtual DUO can't rehearse yet: Mystery Gift (the DUO's adapter program depends on real-hardware
line timing the emulator doesn't model) and Mystery Event in every language.

    python3 tests/gallery_events.py one FILE GAME      one file against one game: PASS or FAIL last
    python3 tests/gallery_events.py list GALLERY       every (file, game) pair it would run

A .wc3 runs against each game its name gives (E - ... Emerald; FL - ... FireRed and LeafGreen), in
its own language: the simulated game searches, connects and receives, and must end up holding exactly
the file's Wonder Card and RAM script. A .me3 (the Eon Ticket) runs against Ruby and Sapphire in its
language: the game must receive exactly what the tool sends, and the Mystery Event model (every
language: Japanese, English, French, German, Italian, Spanish) must store the ticket.
The files stay where they are and are only read.
"""
import contextlib, glob, io, os, re, sys

sys.argv, _argv = [sys.argv[0]], sys.argv
import test_v4 as T                                    # (the simulator, the models and the helpers)
sys.argv = _argv
W, RFU, LG, ME = T.W, T.RFU, T.LG, T.ME

LANG_IDS = {"Japanese": 1, "English": 2, "French": 3, "Italian": 4, "German": 5, "Spanish": 7}
VERSION = {"Emerald": 3, "FireRed": 4, "LeafGreen": 5}


def pairs(gallery):
    files = sorted(glob.glob(os.path.join(gallery, "**", "*.wc3"), recursive=True) +
                   glob.glob(os.path.join(gallery, "**", "*.me3"), recursive=True))
    out = []
    for f in files:
        if f.lower().endswith(".me3"):
            out += [(f, g) for g in ("Ruby", "Sapphire")]
        else:
            out += [(f, g) for g in (W.file_games(f) or ())]
    return out


def wc3_parts(data):
    size = 0xA4 if len(data) == 4 + 0xA4 + 0x50 + 4 + 1000 else 0x14C
    card = data[4:4 + size]
    script = data[4 + size + 0x50 + 4:4 + size + 0x50 + 4 + 1000]
    return card, script


def gift(path, game):
    lang = W.file_language(path) or "English"
    compat = LANG_IDS[lang] | VERSION[game] << 10 | 0x0380
    card, script = wc3_parts(open(path, "rb").read())
    hw, g, trace, st, counters = T.adapter_session(lambda gm: T.gift_script(gm, compat=compat), first_bit=True,
                                                   seconds=150, wonder_card=path)
    if hw.lg_error is not None or not hw.lg_done:
        return False, f"the link didn't finish: {hw.lg_error!r}"
    child, client = hw.lg_result
    if client.result != RFU.CLI_MSG_CARD_RECEIVED:
        return False, f"the game's Mystery Gift ended with {client.result}"
    if client.saved_card != card or client.saved_ram_script != script:
        return False, "the game saved a different card or script from the file's"
    return True, f"{lang} {game} received and saved the card and its script intact"


def event(path, game):
    lang = W.file_language(path) or "English"
    model = LG.RubyMysteryEvent(master=True, language=LANG_IDS[lang])
    hw, report = T.ereader_run(model, path=path, seconds=90)
    if "Mystery Event not loaded" in hw.text:            # the tool declines it: a limit, not a fault
        why = hw.text[hw.text.index("Mystery Event not loaded"):].split("\n")[0]
        return None, f"not supported by the tool yet ({why[len('Mystery Event not loaded '):].strip('() ')})"
    if hw.lg_error is not None or not hw.lg_done:
        return False, f"the link didn't finish: {hw.lg_error!r}"
    sent = W.prepare_event(open(path, "rb").read(), os.path.basename(path))[0]
    if hw.lg_result != T.sent_as(sent):
        return False, "the game received something other than the tool's event"
    if lang not in ME.LANGUAGE_MASK:
        return True, f"{lang} {game} received the event intact (its script isn't modelled for {lang}: transfer only)"
    data = open(path, "rb").read()
    status, saved, store = ME.run(hw.lg_result, lang, game)
    if status not in (ME.LOAD_OK, ME.SUCCESS) or not saved or store["ram_script"] != data[:1004]:
        return False, f"the game's script engine said {status}, saved {saved}"
    return True, f"{lang} {game} received the event and its script stored it"


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "list":
        for f, g in pairs(sys.argv[2]):
            print(f"{g}\t{f}")
        return 0
    if len(sys.argv) == 4 and sys.argv[1] == "one":
        path, game = sys.argv[2], sys.argv[3]
        try:
            with contextlib.redirect_stdout(io.StringIO()) as noise:
                ok, why = (event if path.lower().endswith(".me3") else gift)(path, game)
        except Exception as err:
            ok, why = False, f"{type(err).__name__}: {err}"
        word = "PASS" if ok else "NOT SUPPORTED" if ok is None else "FAIL"
        print(f"{word}: {os.path.basename(path)} with {game}: {why}")
        return 0 if ok else 3 if ok is None else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
