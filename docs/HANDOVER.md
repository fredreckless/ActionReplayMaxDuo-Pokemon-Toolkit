# Hand-over (start here in a fresh chat)

Written overnight on 29–30 October 2026, after lab sessions 21–25 and the work that followed
them. Last commit: see `git log -1` on `main` (`v42-local` is kept identical).

## In one paragraph

The project gives a Datel Action Replay MAX DUO (a GBA cartridge with USB) a second life. One
custom firmware, **Reckless v4.2**, serves two Python tools:
- **`maxduo_saves.py`** backs up GBA saves. It's finished; leave it alone.
- **`duo_events.py`** (renamed from `duo_wireless.py` overnight) runs small GBA programs on the
  DUO's GBA so that it plays the hardware a distribution used. A Pokémon game on a second GBA
  then receives the event through its own menus and saves it itself.

Mystery Gift works on real hardware for **Japanese Emerald** and **English LeafGreen**. The
**e-Reader route** (Mystery Event, Ruby/Sapphire) works end to end on hardware: English Ruby
received the wrapped Eon Ticket and Norman gave it (lab session 26, 30 October).

**The project's goal** (agreed 30 October; see docs/ROADMAP.md): support every Gen 3 Project
Pokémon file meant for a GBA Pokémon game, by its authentic route, wherever that leaves the game
to save the event itself. Routes that write the save directly are the user's decision.

## Ground rules (from the user; keep them)

- **Pushing:** standing permission to push. Keep `main` and `v42-local` identical, and push both
  together. Any *other* GitHub change (settings, releases, issues) needs asking first. That
  includes the release on the to-do list.
- **Tiered testing, kept short** (agreed 30 October; **revised 5 November** because long runs were
  holding development back; `python tests/check.py`):
  - `quick` (about 50 s) after each small change while working;
  - **`changed` before every push** (the tests and planted bugs for the files changed since
    `origin/main`: usually a few minutes). This is the only test step a push waits for;
  - `full --all-bugs` (about 30 minutes) only **before a GitHub release, or once at the end of a
    long session**, or when the shared machinery changes (`tests/hwsim.py`, `tests/mutate4.py`, the
    firmware builds). Start it in the background and **keep working; never sit waiting for it**.
    If it finds something, fix it in the next push;
  - adding or changing a test doesn't need every planted bug (more tests can only catch more);
  - nothing for documentation-only changes (`*.md`, `lab/`, `docs/`);
  - never restart a run that is already going: let it finish (and `pkill -f` matches your own
    shell: stop a run by its task, not by pattern).
- **No Mystery Gift hardware runs for now:** the user's GBA link cable is fitted for the e-Reader
  route and is very tight to remove. Plan hardware tests around the e-Reader cable.
- **Never write cartridge saves** from our code. Leave the DUO's button, the AT switch and the
  clock alone. Never send flash erase/program commands (0x80/0xA0).
- **The user installs firmware themselves** (typing UPDATE). Nothing tonight needs new firmware.
- **Never commit** Datel firmware, Nintendo data (`.wc3`, `.me3`, ROM contents) or personal data.
  That includes the player's trainer ID and name from traces; leave those out of lab notes.
- **Tone:** warm, natural British English; concise. Ask for just the end of each trace.
- **The user's PC:** Windows; Python 3.10 (Thonny); an `ActionReplay` folder in their user folder.
  - Files reach it through the desktop bridge when the chat is linked.
  - **After copying a file there, read it back and compare SHA-1s**: a copy once silently reused
    an earlier upload. Use a fresh staged file name each time.

## What works, and where

| | Status | Lab notes |
|---|---|---|
| Mystery Gift, Japanese Emerald | Old Sea Map and MysticTicket received; serial 0x7F7F chosen automatically | sessions 16–22 |
| Mystery Gift, English LeafGreen | Aurora Ticket (full-size card) received first time; serial 0x7F7D | session 23 |
| Wonder News | simulator only (needs a real news file) | — |
| e-Reader → Ruby | Eon Ticket (wrapped `.me3`) and the PUMKIN BERRY (wrapped `.ecb`) received, 0 mismatches, both collected from Norman | sessions 24–27 |

Lab notes: `lab/sessions/sessionNN/README.md`; index in `lab/README.md`.

## What to do next

- **7 November, evening: the battle partner's DUO side, step 2 (the user chose it while testing
  Record Mixing).** `firmware/programs/colosseum.c` (9.5 KB, 2.3 KB spare): the DUO walks to a
  Colosseum spot, battles once with the PC's `.pk3` team, playing simply (fight, first move with
  PP, next Pokémon after a faint), and logs every block both ways into the save-transfer buffer;
  `duo_events.py colosseum --pk3 ...` keeps it in `battles\` as `.bin` and a decoded `.txt`. The
  research is in docs/BATTLE.md ("What the game sends, in detail"): the key finds are that the DUO
  can always leave the battle to the game (signature 0x0001 as player 0), that GETMONDATA needs no
  answer from the partner (the game's own copy answers it), and that singles and doubles share one
  room. Tests "battle probe" (five, with `tests/battle_game_model.py`) and planted bugs of the new
  kind `colosseum`. **Next on hardware:** a single battle with the probe; read the newest
  `battles\*.txt` and `logs\latest.log` through the bridge. Then step 3: the PC choosing (the
  `duo_battle.py` levels) instead of the probe's simple play.
  - **Status at the end of the session (7 November, 20:20):** pushed (`main` = `v42-local` =
    `6d8c3f4`). Changed tier before the push: 161 tests passed; all 137 planted bugs caught (one
    PC bug's anchor had been doubled by the probe's log copier: reworded, re-run, caught).
  - **Not done yet, on purpose:** the new files are **not on the user's PC**
    (`C:\Users\fredr\ActionReplay`); the user was testing Record Mixing tonight with the old
    tools and the `tonight` folder (TONIGHT.md: bases with Alicia, a whole sitting with WILLOW's
    base, old man, trend, TV and news; Ctrl+C recovery; the workshop). Copy `duo_events.py` (and
    nothing else changed for the PC) with fresh staged names and SHA-1 checks **after** reading
    those results.
  - **First thing next session:** read tonight's logs through the bridge
    (`C:\Users\fredr\ActionReplay\logs`, newest first; `records\` for the game's `.rm3`), check
    each TONIGHT.md test against what the model predicted, and fix what they show. Then copy the
    probe across and give the user a short single-battle test: Ruby with two or three Pokémon, the
    DUO with one or two `.pk3` files; afterwards read the newest `battles\*.txt` and
    `logs\latest.log`.
  - **Things the probe's hardware run should settle:** that Ruby accepts the 31-byte header and
    our party blocks (the DUO's Pokémon shown with the right name, level and HP); that the
    0x0001 signature hands the battle to Ruby when the DUO is player 0 (untested anywhere but the
    model); that instant "done" replies don't upset the game; the walk out after the battle. The
    model is this session's reading of pokeruby, not observed behaviour.
- **7 November: the Record Workshop complete for Ruby and Sapphire (the user asked for it "fully
  complete").** New tabs: TV shows (12 kinds, `TV_SPEC`), PokéNews, day-care letters, the Battle
  Tower trainer (the class follows the trainer ID; Ruby's banned species; checksum). The game's own
  lines come from the ROM by pret's addresses (`ROM_TEXT_AT` in the page, `text=` in
  duo_rom.WORKSHOP_PARTS): `playShow` is a port of pokeruby's twelve `DoTVShow*`. Tests: "Record
  Workshop: the TV..." and the ROM copy test (made-up lines in the test ROM). Emerald is next once
  the DUO can mix as one.
- **6 November, late: hardware results and the record work (the user's three steps).**
  - **Hardware (lab, the user's cmd output):** Record Mixing with English Ruby **works**: the room
    fades in, both bases rounds go across, WILLOW's base was kept, and the DUO walks round a
    blocking player. Two runs hung after "done" while copying the game's bases (800 polls); Ctrl+C
    then left the mix program running, and the next run failed its hello. Fixed: the copy shows
    progress and logs its timings, Ctrl+C always ends cleanly (and stops a running program), and
    `connect` ends a left-over program. The hang's cause isn't known yet: the next log will say
    how long each poll took.
  - **Logs:** every tool run now writes `logs\YYYY-MM-DD HHMMSS tool command.log` beside the tools
    (`runlog.py`; `logs\latest.log` the newest). Read them through the device bridge
    (`C:\Users\fredr\ActionReplay\logs`) instead of asking for pasted output.
  - **Done:** Ruby's merges in the model and `records.py predict`; the DUO sends whole records
    (`mix --record/--tv/--news/--old-man/--trend/--mail/--tower`) and brings the game's whole
    record back; the Record Workshop's old man, trends and whole-record tabs. All in
    RECORD_WORKSHOP.md's status.
  - **Next on hardware:** a sitting with an old man (a Bard's song) and a trend, then listen to the
    Bard in Mauville and ask in Dewford; and the game's `records\*.rm3` checked with
    `records.py show`.
- **6 November, evening: every part of a record (asked for by the user).** The Secret Base
  Workshop is to grow into a Record Workshop with a tool for each part of a Record Mixing record.
  Formats: docs/RECORD_FORMATS.md (draft 1: `.rm3` whole records and a file per part, `.tv3`,
  `.om3`, `.dt3`, `.bt3`...); plan: docs/RECORD_WORKSHOP.md. The user agreed (end of RECORD_FORMATS.md): `.rm3` and part files;
  Ruby first; the game's own lines one for one, read from their ROM. Step 1 begun: `records.py`
  (a save's own record, split/join/show, checks; test "Record files") and Ruby's rules in
  RECORD_FORMATS.md; next the game model for TV, news, trends and the old man.
- **6 November: the battle partner's thinking side, on the PC (the user can't test Record Mixing
  for now and asked for something else).**
  - `duo_battle.py` (new, beside the tools; the release must include it and `battle_data.py`): a
    Gen 3 singles battle with pokeemerald's damage step by step, and easy, medium and elite
    players; `.pk3` files become its Pokémon (`mon_from_pk3`). `battle_data.py` is generated by
    `tools/make_battle_data.py` from pret's sources (don't edit it). Strength and design:
    docs/BATTLE.md, "Progress". Tests: "battle:" in test_v4.py (about 25 s).
  - Elite is rollout improvement over medium (playing each choice on to the end in imagined
    copies) and only leaves medium's choice on a clear margin; a two-turn expectimax was worse
    than medium and was dropped. Its weakness is guessing the other side's moves: knowing them is
    worth about 7 points against medium.
  - Not yet: doubles; hiding the other side's unseen party members; the DUO's `battle.c` and the
    Colosseum walk (docs/BATTLE.md steps 1-3).
- **5 November, late (after lab session 31): the plan agreed and most of it done; hardware next.**
  - **The user's choices:** the trainer card as realistic to the event as possible; the battle
    partner's team is a set of `.pk3` files, with easy, medium and elite levels (elite highly
    intelligent and strategic; easy not stupidly easy); the ROM reader targets the parts of the
    game the workshop needs; the workshop gets a Generate button, more help, one placement per pick,
    and a "save first?" question that clears the room when changing spot.
  - **Done (simulator; all pushed):** the Record Corner's black screen (the fade-in's "ready"
    barrier, 0x2FFE, unanswered: docs/RECORD_MIXING.md); walking round the player to the seat and
    the door (`firmware/programs/room_walk.h`, docs/TRADE.md); the trainer card (`trade_card`);
    a line when nothing changes for 30 s, a line when the player blocks the DUO, and Ctrl+C now
    stops a session cleanly and still keeps what was traded; `duo_rom.py` reads only the
    workshop's parts by pret's addresses (English Ruby revs 0-2, Sapphire rev 0, Emerald) in about
    two minutes, refuses games without Secret Bases unless `--whole`, and caps Pokémon cartridges at
    16 MB; the workshop's Generate (six themes, every spot tested), help, mover buttons and spot
    dialog. The battle partner's design: docs/BATTLE.md (nothing built yet).
  - **Next on hardware:** Record Mixing with English Ruby again (the room should fade in now), then
    the Eon Ticket gift as player 0; a trade where the player stands in the way out; the trainer
    card in Ruby, Emerald and LeafGreen; `python duo_rom.py` with the Ruby cartridge, then the
    workshop with the file it makes.
  - **Not yet:** Emerald Record Mixing (the DUO saying "Ruby"); the targeted ROM reader for
    Japanese and European cartridges (no pret addresses: a GBA-side search would do it, so the
    user's Japanese Emerald needs `--whole` for now); the battle partner (docs/BATTLE.md, step 1).
  - **Space:** `mix` had 0 bytes spare after the room walk (since 6 November its record lives at 0x02010030: 3 KB spare); `trade`
    has about 500 bytes. Before adding to `mix`, find room (its screen lines, or share more buffers).
  - The user's Aura Mew trade on LeafGreen (session 31) wasn't kept in `received\`: Ctrl+C skipped
    the saving then (fixed since).
- **Record Mixing and Secret Bases (4 November): steps 1 and 2 done; hardware next.**
  - The user's choices: a proper `.sb3` format in the spirit of `.pk3`/`.wc3` (one base per file,
    the game's own 160 bytes; `docs/SB3_FORMAT.md`), several per sitting, bases read from games in
    the first version, mostly hand-made bases.
  - `secret_bases.py` (new, beside the tools; the release must include it): `.sb3` checks
    (structural: refuse; fair play: warn, `--strict` refuses), base cards (`make`/`show`), bases from
    save backups (slot 0's team from the party, as the game does), and `predict_mix`, the game's
    filing on the PC. The data tables at its end come from pokeemerald (generator kept in the
    scratch folder only, `gen_tables.py`).
  - `firmware/programs/mix.c` + `duo_events.py mix [--base ...] [--gift ITEM]`, `bases SAVE`,
    `base make|show`. Docs: `docs/RECORD_MIXING.md` (protocol, what the DUO sends and why), README.
  - Tests: `tests/mix_game_model.py` (Ruby's Record Corner and its own port of the filing), six
    tests ("Record Mixing", "Secret Base"), 12 `mix` and 7 `pc` planted bugs.
  - `secret_base_workshop.html` (5 November): a browser page that designs a base and saves the
    `.sb3`; same tables as `secret_bases.py` (a test checks), byte-for-byte the same output. Also
    published as a private claude.ai artifact (the user shares it). No game graphics in it: the
    user asked; declined to copy Nintendo's art; offered reading it from their own ROM at run time.
  - Next: hardware with English Ruby (both cable ways; then `--gift "Eon Ticket"` as player 0),
    then Emerald (the DUO to say "Ruby" so Emerald uses Ruby's layout).
- **The user chooses what to work on next.** Don't start new features unasked; the ideas
  discussed on 30 October (Enigma Berries from `.ecb`, ribbons, e-Card trainers, a trade
  distributor) are in the roadmap's goal table.
- **Enigma Berries work on hardware** (session 27: the PUMKIN BERRY from Norman). The user's
  berry files are in `EventsGallery\Released\Gen 3\ENG\e-Card Berries`.
- **Fixed overnight (30–31 October):** the false "the DUO is player 0" (session 27). `ereader.c`
  now takes its role from SIOCNT's player ID after each transfer.
- **Stages 6 and 7 done in the simulator (overnight):** e-Card `.raw` scans and Japanese
  Ruby/Sapphire. **Next hardware test:** a trainer card, e.g.
  `python duo_events.py event --event "EventsGallery\Released\Gen 3\ENG\e-Card .raws\Ruby & Sapphire\Trainers\08-A001 RS - Cool Trainer Devin (USA).raw"`,
  then the old man's house in Mossdeep City. Any e-Reader trainer already in the save is replaced.
- **Copy to the PC:** the PC was asleep at the end of the overnight session, so its
  `duo_events.py` and `HANDOVER.md` are older than `main`. Copy them across (and check SHA-1s)
  before the next hardware test.
- **31 October:** a planted bug that matches its code more than once, or no longer at all, now
  reports BROKEN instead of stopping the run. The bad-program test gained a case with intact code
  and a wrong stored CRC, so "run skips the program's CRC check" is caught every time (damaged
  code could crash the emulator first).
- **Also overnight:** the `finishing` test's `--keep-going` check now runs 45 s (12 s let a
  planted bug through once under load).
- **Stage 9, step 1 done (31 October):** `pk3-info`, `.ect` trainers, and docs/PK3_EVENTS.md.
  Only the Mystery Mew was a trade; nearly every other released event wrote the save directly.
  **Decided (31 October): the trade route for all** (labelled as the nearest where it isn't the
  original). No multiboot save writer.
- **1 November, evening (the user's go-ahead for all but Pinball):** `trade --pk3` names each
  event's original route (all 3,344 gallery files recognised; a trade is "the nearest route" except
  for the Mystery Mew), takes **up to six Pokémon in one sitting**, and the DUO's **trainer card and
  link player carry the event trainer** (name, ID, gender). The GitHub release was approved too.
- **1 November, afternoon:** the Mystery Gift program writes lines on the DUO's screen too, but
  **only where the wireless link can't be affected** (the user's priority): at start, when the
  card is loaded if the game hasn't sent a word yet, and after the PC has stopped the program.
  The simulator now stalls the GBA on log lines for the wireless game as well, and a test checks
  no line falls while the game is on the link. Normal build only; the lab build is unchanged.
- **Session 30 (1 November):** on hardware, the Devin e-Card now works (Ruby stored exactly the
  card's trainer; save backups compared), a trade ran cleanly through to leaving the room, and a
  Trainer Hill e-Card went into Japanese Emerald (link type 0x5503, closed after its check; the
  Trainer Hill itself not yet visited). The PC's copies match `main` as of commit afe48e4.
- **Overnight 31 October–1 November:** trades into **Emerald and FireRed/LeafGreen** (same
  protocol; the DUO now sends the progress flags they check; the tool names the game and warns
  before a refusal: Mew/Deoxys without the fateful mark, Emerald's Hoenn-only rule) and **Japanese
  Emerald's Trainer Hill e-Cards** and **Japanese FireRed/LeafGreen's Trainer Tower e-Cards**
  (`event --event` with up to four cards; docs/EREADER.md), all in the simulator. (Copied to the PC on 1 November.)
- **Session 29 (31 October, late):** **the trade works on hardware** (WISHMKR Jirachi into English
  Ruby, twice). Fixed since: leaving the room (Ruby reopens the link as 0x1111 and the DUO must
  walk out; the game froze), and short Mystery Events (Ruby only runs blocks over 256 bytes, so
  Devin's 212-byte card stored nothing: every event now goes as the full 2,004-byte buffer).
  Received Pokémon now go to `received\` beside the tools. The trade and e-Reader programs write
  short lines on the DUO's screen, only between link sessions. **To check on hardware:** the Devin
  card again (then Mossdeep), and a trade through to leaving the room.
- **Session 28 (31 October, evening):** the Drash Berry e-Card and both MysticTickets worked; the
  trade reached the Trade Center but the DUO stood at the door. **Fixed:** the Cable Club's link
  type is 0x1133, not 0x1111. **Unexplained:** the Devin trainer card (USA) left Mossdeep's door
  locked although the card's record is intact; next, a read-only save backup to look at the
  stored trainer. `gift` now turns away a `.me3` (and every command a file meant for another).
- **The trade distributor works in the simulator (31 October):** `trade --pk3 FILE`, program
  `trade.c`, model `tests/trade_game_model.py`, docs/TRADE.md. **Next: a hardware run** with English
  Ruby on the GBA cable as fitted: back up the save, go to a Pokémon Center's Cable Club (2nd floor),
  TRADE CENTER, sit at the table, offer a spare Pokémon. Whatever Ruby gives is kept in
  `received\` beside the event file.
- **For the user to decide:** the Berry Glitch Fixing Program cards are refused (an e-Reader
  program that writes the save itself), and so would be any card that turns on the clock reset
  (`enableresetrtc`; none of the gallery's does).
- Not yet checked on hardware: the Eon Ticket's Record Mixing gift; Mystery Gift through the new
  guided start-up (waiting: the cable stays fitted for the e-Reader route).
- **The user's folder:** `tidy_folder.bat` (30 October) moves the older files into `old\` when run;
  it leaves `EventsGallery`, `EventsGallery-master`, `Datel`, `saves` and the tools alone.
- The PC's copies of `duo_events.py`, `duo_wireless.py`, `maxduo_saves.py` and this file matched
  `main` (SHA-1) on 30 October; this file has changed since, so copy it across again.

## The `.me3` discovery (session 25; details in docs/EREADER.md)

- **What a `.me3` is.** A community `.me3` holds what Ruby **stores** after an event: the RAM
  script block (byte-sum checksum, magic 0x33, map group, map number, person, script) and the
  Record Mixing gift. It is **not** the Mystery Event script the e-Reader sent.
- **Why the raw file fails.** Ruby runs the received buffer as a script. 0xF0 isn't a command,
  so the engine stops with status 0, "loaded OK". The menu shows its success message and saves,
  having stored nothing.
- **What the tool does now.** It wraps a `.me3` in `checkcompat` (English/German from the file
  name; Ruby and Sapphire), `checksum`, `initramscript`, `setrecordmixinggift` and `end`.
  - `tests/mevent_model.py` is a model of Ruby's engine, written from pokeruby. It confirms
    that the game then stores exactly the file's bytes.
  - It did so locally for the real Eon Ticket file too: 1,012 of 1,012 bytes. That file isn't
    in the repository.
- **Ruby's MYSTERY EVENT menu only carries on as the link master** (`gLinkStatus & 0x20`; it
  closes the link if connected and not master). If the DUO comes up as player 0, the tool says
  to swap the cable's ends.

## What changed overnight (all pushed, if the session finished)

- **`duo_events.py`** replaces `duo_wireless.py`:
  - **Commands:** `gift --card`, `news --news`, `event --event`, plus `adapter-test`, `probe`
    and `find-serial`. Options include `--seconds`, `--keep-going`, `--serial`,
    `--sweep-serial`, `--check-search` and `--lab`, with the global `--wait`.
  - **`duo_wireless.py` is now a stub.** Old flags are translated (`translate_legacy`), with a
    note giving the new command.
- **The guided start-up** (the user's design):
  - Both GBAs off, and the cable for that command.
  - The DUO's GBA on, the game's off.
  - **Progress bars** while the program uploads ("Setting up the DUO's GBA") and the file loads.
  - "Ready. Now switch on the game's GBA, then:" followed by each game's menu path.
    - Japanese Emerald's path comes with romaji, and the おくりもの/もらいもの sign: もらいもの
      means it was switched on too early.
    - The unlock phrases and places are given too.
  - `uprint` never fails on a console that can't show kana.
- **It finishes by itself:**
  - Mystery Gift: after a disconnect (0x30) with server step 6.
  - e-Reader: when the game closes the link after the event; it then says where to go in the
    game.
  - `--keep-going` turns this off.
- **The card/game check.** It warns if a card's file name (Project Pokémon's "E - ", "FL - ",
  "RS - ") names another game than the one the trace detects. The cards themselves don't show
  their game reliably: only the RAM scripts' `setvaddress` bases differed in the three files
  looked at (Emerald 0x0200025x, FRLG 0x020131xx). That's not used.
- **`ereader.c`:**
  - **In-flight flag.** It fixes a race: as master, a transfer could start before the previous
    one had been handled, if it finished between the IF and SIOCNT reads.
  - **Restarts.** It follows the game starting over after a close (three handshake words in a
    row), so two events can go in one session.
  - **Diagnostics for the PC:** mismatch stage counts, the first four mismatches, the longest
    gap, and events sent.
  - **Master pacing** (from session 24): one handshake transfer per frame, a two-frame pause at
    link up, one command cycle per frame, and 13 scanlines from each transfer's end. Only the
    slave role matters for Ruby, but this is kept and tested.
- **The simulator is stricter:**
  - five-scanline transfers;
  - a slave game that needs 0.6 ms to load its next word (it misses transfers started sooner);
  - the game takes in one command per frame, with room for 50;
  - Ruby's master-only menu rule (`menu_rules`).
- **Tests:**
  - missing Datel builds (`paths.MissingBuild`), or an `fw.bin` that isn't Datel's untouched
    firmware, now **skip** instead of failing;
  - new tests: `.me3` files, the master advice, two events per session, connect retry, upload
    retry;
  - **Final run:** 106 tests, 97 passed and 6 skipped (no Datel builds). Three timed out in the
    simulator under heavy load, and passed when re-run alone. 79 planted bugs: the 72 that can
    run here (`prog`, `ereader`, `pc`) were all caught.
- **Docs:** README (new commands, per-game menus, unlock phrases, cable notes), docs/EREADER.md
  (menu statuses, script commands, the `.me3` layout and wrapping), ROADMAP, and lab notes for
  sessions 21–25.

## Still on the to-do list

- **A GitHub release** (a zip of the scripts plus short instructions): **ask the user first.**
- **The lab build (`adapter_lab`) has about 20 bytes spare.** `-Oz` isn't an option, because it
  pulls in `__aeabi_uidiv`, which we can't link. Before the next lab feature, trim `SCOPE_N`,
  `CAP_CMDS`/`CAP_WORDS` or `W_MAX` in `adapter.c`.
- **Wonder News on hardware** needs a real news file. Japanese news is assumed to be 202 bytes.
- **More games on hardware:** English/European Emerald, FireRed, other languages. Use
  `gift --sweep-serial` if a game never finds the distributor.
- **Japanese Emerald's Mystery Event (ふしぎな できごと):**
  - **Unlocked on hardware (session 28):** the phrase ふしぎ できごと ワクワク ドキドキ at a Poké
    Mart questionnaire; both ふしぎなおくりもの and ふしぎなできごと then appear.
  - Japanese `checkcompat` uses language mask 1 (Stage 7).
  - Its もらいもの entry is something else: the Trainer Hill e-Reader (`ereader_screen.c`), a
    different protocol.
- **Unexplained:** straight after a successful run, a program upload sometimes stalled (sessions
  16, 21). The retry handles it, and handing the link port back (RCNT/SIOCNT) may have cured it.
  Session 22 was clean.

## Code facts

- **Repository:** `fredreckless/ActionReplayMaxDuo-Pokemon-Toolkit`. The working clone was at
  `/home/claude/v42-wt` (branch `v42-local`). Push with
  `git push origin v42-local && git push origin v42-local:main`.
- **Programs** (`firmware/programs/*.c`, clang 18 + lld; `firmware/programs.py`):
  - `adapter` (everyday Mystery Gift), `adapter_lab` (`-DLAB`), `adapter_probe` (`-DPROBE`),
    `ereader`, `trade`, `mix` (Record Corner; 8.6 KB since its record moved to 0x02010030).
  - Everything, variables included, must end below `0x0203AE00` (`programs.py` asserts it). Above
    that are the firmware's messages, and from `0x0203AF00` its transfer state.
  - There's no hardware divide: no `/` or `%` on variables.
  - **After any change to a program, run `python firmware/embed_programs.py`.** That refreshes
    the copies embedded in `duo_events.py`, and a test checks them against a fresh build.
- **Sizes:** `adapter` 11,264 bytes, `adapter_lab` 11,740, `ereader` about 5.2 KB.
- **Program protocol** (v4.2 firmware):
  - `0x23` RUN runs the staged image (`RKR1` header, CRC-checked);
  - `0x2A` POLL with an argument (low byte selects; `idx << 8`);
  - `0x2B` STOP;
  - `0x2C` PUT loads a file a word at a time (poll 20 starts the load, poll 21 checks its CRC).
  - The link to the PC strictly alternates: one PC packet, then one GBA packet.
- **Mystery Gift facts:**
  - the serial is chosen from the game's 0x16 broadcast: Japanese Emerald 0x7F7F, others 0x7F7D;
  - card checks use the game's CRC-16 (init 0x1121, reflected polynomial 0x8408, inverted);
  - a JP card is 0xA4 bytes, EN 0x14C;
  - news is 202 bytes (JP, assumed) or 444 (EN);
  - polls 20/21 load, 22 the link state (`mg_step` in bits 4–7), 26 check/sweep, 27 serial,
    28 the news result.
- **e-Reader facts:**
  - SIO multi-player mode, 115,200 bit/s;
  - handshake 0x8FFF (master) / 0xB9A0 (slave);
  - commands of 8 words plus a checksum slot (nine transfers per cycle);
  - `0x2222` link players, `0xBBBB` + size + id block header, `0x8888` + 7 words per chunk,
    `0x5FFF` close;
  - link type 0x5501;
  - polls: 0 = state | master<<4 | sessions<<5 | transfers<<8; 1 = bad checksums; 2 = the game's
    link type and language; 3 = the game's player bytes; 4–6 = the mismatch log; 7 = mismatches
    by state; 8 = longest gap | events sent<<16.
- **Tests:**
  - `python tests/check.py quick|changed|full|what`: the tiers (see the ground rules). The
    workspace has 2 cores; the runners default to one job per core (3 made tests time out).
  - `python tests/run_each.py [FILTER]`: every test (or those matching) in its own process, about
    6.5 minutes for all 106 here.
  - `python tests/mutate4.py [KIND ...]`: planted bugs, all or by kind (`fw`, `fw42`, `prog`,
    `ereader`, `pc`). The `fw`/`fw42` kinds need Datel's untouched firmware (`fw.bin`).
  - Without the firmware built, tests that need it are reported as skipped, and the rest run.
  - The models live in `tests/`: `hwsim.py` (the DUO; the multi-player link model with timing),
    `rfu_game_model.py` (Mystery Gift client), `link_game_model.py` (Ruby's link layer and
    Mystery Event menu), `mevent_model.py` (Ruby's Mystery Event script engine).
- **Firmware builds:** reproducible from Datel's 1.06 update file
  (`firmware/build_firmware.py FILE --all`): v4.1 has update CRC `A5303402`, v4.2 `DD59ED8A`.
  **Each new chat's workspace starts without them:** stage Datel's update file from the user's
  PC (`ActionReplay\Datel\us_update_v1_06\us_update_v1_06\us_update_v1_06.bin`) and build
  first. With it, all 106 tests pass and none skip (30 October).

## References (not in the repo)

- `github.com/pret/pokeruby`: `mystery_event_menu.c`, `mystery_event_script.c`, `script.c`
  (`RunScriptCommand`, `InitRamScript`), `link.c`, `data/script_cmd_table.inc`,
  `include/macros/event.inc`, `include/constants/flags.h`. Raw files can be fetched with curl
  from raw.githubusercontent.com; the GitHub API is blocked here.
- `pret/pokeemerald`, `pret/pokefirered`: librfu, link_rfu, `mystery_gift_*`, `main_menu.c`,
  `ereader_screen.c`.
- GBATEK (SIO modes); suloku's tools (the `.wc3` layout); Project Pokémon's event gallery (the
  user's files).
