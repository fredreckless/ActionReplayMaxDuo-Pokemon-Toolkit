# Hand-over (start here in a fresh chat)

Written on 8 November 2026. The history up to 7 November is in
[lab/handover_history_to_2026-11-07.md](../lab/handover_history_to_2026-11-07.md); the lab notes are in
`lab/`. Last commit: `git log -1` on `main` (`v42-local` is kept identical).

## In one paragraph

The project gives a Datel Action Replay MAX DUO (a GBA cartridge with USB) a second life. One
custom firmware, **Reckless v4.2**, serves the Python tools. `maxduo_saves.py` backs up GBA saves
(finished; leave it alone). `duo_events.py` runs small programs on the DUO's GBA so that it plays
whatever a Pokémon game's link features expect: the Wireless Adapter for Mystery Gift, the e-Reader
for Mystery Events, a partner in the Trade Center, the Record Corner and the Colosseum. The game
always receives and saves through its own menus.

**The goal:** support every Gen 3 Project Pokémon event file by its authentic route, wherever that
leaves the game to save it itself (docs/ROADMAP.md), and, since 5-7 November, take part in every
multiplayer feature of the five games (ROADMAP Stage 12).

## Ground rules (from the user; keep them)

- **Pushing:** standing permission to push. Keep `main` and `v42-local` identical and push both
  together. Any *other* GitHub change (settings, releases, issues) needs asking first. **The GitHub
  release is the user's own business now** (8 November: "I have sorted it"); don't raise it.
- **Tiered testing, kept short** (`python tests/check.py`):
  - `quick` (about 60 s) after each small change while working;
  - **`changed` before every push** (the only test step a push waits for);
  - `full --all-bugs` (about 30 minutes) only before a release, at the end of a long session, or when
    `tests/hwsim.py`, `tests/mutate4.py` or the firmware builds change. Start it in the background
    and keep working; if it finds something, fix it in the next push;
  - nothing for documentation-only changes (`*.md`, `lab/`, `docs/`);
  - never restart a run that's already going.
- **No Mystery Gift hardware runs for now:** the GBA link cable is fitted and is very tight to
  remove. Plan hardware tests around the cable (docs/HARDWARE_QUEUE.md).
- **Never write cartridge saves** from our code. Leave the DUO's button, the AT switch and the clock
  alone. Never send flash erase/program commands (0x80/0xA0).
- **The user installs firmware themselves** (typing UPDATE). Nothing since v4.2 needs new firmware.
- **Never commit** Datel firmware, Nintendo data (`.wc3`, `.me3`, ROM contents) or personal data,
  including the player's trainer ID and name from traces.
- **Tone:** warm, natural British English; concise.
- **The user's PC:** Windows; Python 3.10 (Thonny); `C:\Users\fredr\ActionReplay`. **Since 13
  November that folder is a git clone of this repository** (`core.autocrlf false`, so files are
  byte-identical to GitHub; tracking origin/main): after a push, Fred updates it with `git pull` in
  PowerShell there, and the old copy-and-SHA-1 routine is retired. His personal files there (ROMs,
  saves, logs, received, bases, records, battles, Datel, EventsGallery, tonight, old, release,
  .me3/.wc3/.pk3, virtual/runs and virtual/states) are all git-ignored and must stay so; never run
  `git add .` there. If a file must still go across the desktop bridge (a save state, a script for
  him to run), read it back and compare SHA-1s. Run logs are in `logs\` there: read them through
  the bridge rather than asking for pasted output. The bridge can't reach WSL's own folders.
- **The user chooses what to work on.** On 8 November they asked for: the room walk always reaching
  its spot, results kept safely, the workshop's "Put it in the record" for bases, an impossible
  battle level, and **all aspects of link battling, doubles included** (keep going towards that).

## Where things stand (8 November)

| Feature | Status |
|---|---|
| Mystery Gift | Japanese Emerald, English LeafGreen on hardware; others waiting for the cable to come out |
| e-Reader route (Ruby/Sapphire) | Eon Ticket, berries, Battle-e trainers on hardware |
| Trades | Ruby, Emerald, LeafGreen on hardware; up to six a sitting |
| Record Mixing (Ruby) | Everything in a record, on hardware (6-7 November); the user considers it done for now |
| Colosseum | The battle link worked on hardware (7 November, the probe). **The PC choosing (easy, medium, elite, impossible), singles and doubles, Ruby/Sapphire, Emerald (as a Ruby player) and FireRed/LeafGreen: simulator only, hardware next** |
| Battle Tower link multi battle (Emerald) | Built 8 November (`tower`, the DUO as partner): simulator only |
| Link Contest (Emerald, E MODE) | Built 8 November (`contest`, docs/CONTEST.md; the DUO as player 1): simulator only. Ruby/Sapphire need four players |
| Berry Blender (Ruby/Sapphire/Emerald) | Built 8 November (`blender`, docs/BLENDER.md; two players, the DUO as player 1): simulator only |

**Hardware next:** docs/HARDWARE_QUEUE.md, from the top: a single battle at medium, then impossible,
then a double battle; Record Mixing with the player in the DUO's way.

## What changed on 12 November (the first checklist results)

- **Colosseum link-player id = the spot sat on** (`colosseum.c`): the double-battle garbling of
  test 3. The battle model now checks it.
- **The PC's choices printed** in battles and the Battle Tower (`LinkBattle.explain`).
- **Contest:** Ruby's four-player counter (0x6601) is named as such.
- **Checksum mismatches by state** (trade, mix, colosseum: poll 30), for the Japanese Emerald mix.
- **lab4p:** handshake after ~20 of the game's (not 20 in a row); figures from the game's first real
  word; the line-level model reads slot 1 as the game's own word.
- Open: LeafGreen's hang when the player blocked the DUO (3a); the double battle's end freeze
  (retest after the id fix).

## Also on 12 November: the Virtual DUO (`virtual/`)

- **An emulated MAX DUO** in mGBA, moved in with its history (see virtual/README.md): a shared C
  core for the DUO's chips, USB at register level so Datel's own code runs, and `vduo`, two GBAs on
  a link cable with the DUO's USB on a TCP port. It needs Linux (WSL2 on Windows) and changes
  nothing outside its folder: tests and the release are as they were.
- **`duo_events.py --virtual HOST:PORT`** (and `VirtualTransport` in maxduo_saves.py): the tool
  talks to the emulated DUO instead of USB. Nothing else in the tool changes.
- **Rehearsals against Fred's English Ruby** (virtual/rehearsals, `all.sh`): trade, single and
  double battle, Record Mixing, Mystery Event, the Blender from either end: all pass, and match
  the hardware's own records where they exist (the trade's .pk3 byte for byte).
- **Two blender bugs the hardware logs show too:** as the child the DUO counts a blend for each of
  the game's three copies of the verdict ("Blend 3 done"; `blends++` in blender.c); as the leader
  the summary reads the game's berry block as the leader's block ("RPM in 893801:51",
  `blender_blends`). Fixed on 13 November: the child counts the first copy only, and the DUO's
  own leader's block is now recorded (K_OURS) for the summary; both proved by the blender
  rehearsals from either end ("Blend 1 done"; "77.12 RPM in 1:58").
- **The core is behind tests/hwsim.py** (13 November, Fred's choice): the tests now run Datel's own
  USB routines, the flash's real command set and the Action Replay switch, through the same C
  model the emulator uses. **So the tests run in Ubuntu (WSL) or anywhere with a C compiler**, not
  in Windows Python; the tool itself, with a real DUO, still runs on Windows as before. The old
  Python hwsim is frozen as virtual/tests/hwsim_python.py, for `python3 virtual/check.py`.

## Next for the Virtual DUO (start here in a new conversation, 13 November)

- **Fred's laptop runs it.** Ubuntu 26.04 in WSL2 (CMake 4.2, Python 3.14), clone at `~/toolkit`,
  venv `~/venv`. Built firmware and `firmware/build/duo_flash.bin` (from
  `virtual/runner/prepare_flash.py`) are there. All seven Ruby rehearsals passed on it (twice).
  **Three copies, one master:** GitHub; the WSL clone (for the emulator and the tests, which now
  need a C compiler); the Windows clone (for the real DUO over USB). Both clones update with
  `git pull`; nothing is edited in either by hand.
  `~/runs` is a link to `C:\Users\fredr\ActionReplay\virtual\runs`, so results land in the folder
  the session can read through the device link (WSL's own folders can't be reached from it, and
  terminals can't be typed into with computer use: give Fred one line to run, or a script put in
  `ActionReplay\virtual\`). His inputs are linked under `~/kit`; the rehearsals' save states
  (made from his English Ruby save, at each attendant) are in `ActionReplay\virtual\states`.
  `ActionReplay\virtual\run_second.sh` is the pattern for a one-line run.
- **ROMs on the PC** (`ActionReplay\roms`, his own dumps, never committed): Emerald and LeafGreen
  in all six languages (Japan, USA/Europe or Europe Rev 1, France, Germany, Italy, Spain); English
  Ruby 1.1 in the ActionReplay folder. Saves: his English Ruby, a Japanese Emerald and LeafGreen.
- **The save generator: English Ruby done (13 November, evening).** `virtual/savegen/savegen.py
  --rom ROM --out DIR --pk3s DIR/pk3` boots the ROM with no save, presses through the opening, sets
  in RAM only what the Cable Club needs (name, six made-up level-50 Pokemon that pass
  `check_legal`, berries, a Pokeblock Case, the flags), points the game's own special warp
  (`specialSaveWarp` + `warp1`) at Mossdeep's Pokemon Center upper floor, and saves through
  START > SAVE; then, from that save, makes the five states (the warp pointed at each counter on
  the title menu before CONTINUE, then talk until the YES/NO box). About ten seconds for Ruby.
  **All seven rehearsals pass from it** (in the cloud workspace, twice). One rehearsal fix: the
  game's side now gets past a fainted Pokemon (`ruby.battle_press`). Details:
  virtual/savegen/README.md. Fred's one-line run: `bash
  /mnt/c/Users/fredr/ActionReplay/virtual/run_savegen.sh` (results in `virtual\runs\savegen`). **Passed
  on the laptop too (13 November, 21:50): the save in 6 s, then 7 of 7.** But slowly (the single
  battle 13 minutes): the rehearsals' link logs (hundreds of MB) were written straight onto the
  Windows drive, which WSL does slowly. The script now works in `~/work/savegen` and copies
  everything but the link logs across at the end; do the same in any new run script.
- **English Emerald and LeafGreen 1.1 too (13 November, late evening):** profiles in
  `savegen/profiles.py` (pret's symbols; save blocks through their pointers; bag quantities XORed
  with the save's key). Emerald: the Cable Club menu at Mossdeep's Direct Corner, the Blender, the
  link contest, MYSTERY GIFT highlighted; LeafGreen: the Cable Club menu at Viridian, MYSTERY GIFT
  highlighted (English MYSTERY GIFT needs the Wireless Adapter before it opens). Checked by
  reading the saves and states back; **no Emerald or LeafGreen rehearsals yet**.
- **And every language of Emerald and LeafGreen (13 November, night):** `savegen/findsyms.py`
  finds the addresses in the Japanese, French, German, Italian and Spanish ROMs from pret's
  English symbols; `profiles.DERIVED` holds them. All ten made saves and states, checked by eye
  and read back. (Fred has English Ruby only; no other Ruby ROMs to profile.)
- **Next:** rehearsals for Emerald and LeafGreen (the helpers in `rehearsals/ruby.py` made
  per-ROM, from the same profiles: gObjectEvents, gMain, the party menu's CB2, the rooms' spots);
  then the matrix: every
  ROM x activity x cable end, in parallel on the laptop, with one summary written to
  `ActionReplay\virtual\runs` for the session to read (keep check-ins few: each costs a turn).
  Videos of each run (both screens, MP4) are a wanted extra.
- **Rehearsal know-how:** `virtual/rehearsals/ruby.py` (closed-loop walker on gMapObjects at
  0x030048A0 in English Ruby 1.1; in a link room the player's object has the link player's number
  as its local id; tap A until the DUO reports the link). Run the tool with `python -u` (fixed).
  Never run heavy jobs beside `tests/check.py`: under load, timing-sensitive tests miss.

## What changed on 11 November

- **The Record Workshop's map**: a sketch of Hoenn (from the game's region-map grid and the routes'
  sizes) with the base's entrance pinned, the other spots of its kind clickable, and directions.
  With the user's ROM loaded it also draws the route itself round the entrance (gMapLayouts entries
  16-49, the rooms' own drawing code); `duo_rom.py` now copies the routes with bases too.
- **The DUO can lead** the Berry Blender, the Contest and the Battle Tower (player 0, its GBA on
  the master end). At the Tower the game still runs the battles: the DUO asks for the cards, sends
  the game's own trainers' list and Tower party back (player 1 keeps player 0's), says 0x0001 in the
  header (below Emerald's 0x0300, so `FindLinkBattleMaster` picks the game), plays battler 0 from
  party slots 0-2, and gives the verdict on carrying on from both choices.
- **Contest moves planned by the PC** (`contest_data.py`, from pret's contest moves), and then
  **chosen live** each round from the appeals' state: the applause meter, the turn order, the
  rounds left (`ContestWatch`, `choose_live`; the DUO's poll 11).
- **link_core.h / link_tail.h**: blender.c and contest.c share their link layer (byte-identical builds).
- **The hardware checklist page** (the "DUO Hardware Checklist" artifact): the queue to tick at the
  console; the results are kept with the page for Claude to read back (the `results` collection).
- Emerald's own Record Mixing layout: looked at and left for now. With an Emerald partner, Emerald
  copies the partner's Lilycove lady straight into its save and keeps its apprentices, hall records
  and Tower record, so the DUO must send real ones; until it can build them, Ruby's layout is the
  safe way.

## What changed on 8 November

- **The four-player experiment** (`firmware/programs/lab4p.c`, `duo_events.py lab4p`,
  `tests/gp_link_model.py`, docs/MULTI.md section 2): the DUO, as master, drives the port bit by bit
  and sends slots 0, 2 and 3 itself. Simulator only; a hardware run with Ruby's Trade Center is in
  docs/HARDWARE_QUEUE.md (the DUO on the master end).
- **Record Mixing with Emerald** (`mix.c`): the DUO says Ruby to Emerald, so Emerald mixes in
  Ruby's layout, saves and closes as Ruby does. Simulator only.
- **Emerald's link Contest, E MODE** (`firmware/programs/contest.c`, `duo_events.py contest`,
  `tests/contest_game_model.py`, docs/CONTEST.md): the DUO's contestant (built as the game builds its
  own), its moves in turn, and every leader's-copy block sent straight back (the game leads, so the
  DUO needs no contest rules). Ruby/Sapphire contests need exactly four players.
- **The Berry Blender** (`firmware/programs/blender.c`, `duo_events.py blender`,
  `tests/blender_game_model.py`, docs/BLENDER.md): the link-up (0x4411), the berries (a 40-byte
  `BlenderBerry` each; the DUO's first berry that isn't the player's), the play (0x4444 each frame,
  the DUO running the game's own arrow arithmetic and pressing as its arrow passes), the leader's
  time and RPM, "another berry?", the link save, the close. The PC names the Pokéblock.
- **The room walk** (`firmware/programs/room_walk.h`, shared by trade, mix and colosseum). The
  7 November pacing along the Record Corner's left wall was a bug, not the player: the planner only
  cleared the 16 walkable columns, and the Record Corner's start at column 4, so column 3 kept old
  bytes and the left wall looked near the seat. Now every column is cleared; the walk plans twice
  (an empty room, then around the tiles the player is on or has just used), waits 60 frames for a
  player in its way, then goes round, and never walks across another seat (each is a trigger that
  would stop it). In the Record Corner, if the player sits in its seat it takes the one behind.
- **Keeping what the DUO gathers** (`duo_events.py`, `Copier`). The two "hangs" of 6-7 November were
  the DUO's GBA being switched off before the PC had copied the record. Now the battle's record, the
  game's whole record (round by round as each is final) and traded Pokémon are copied *during* the
  session; the tool says "Keep the DUO's GBA switched on until this says safe to switch off" and then
  "safe to switch off"; a DUO that stops answering is reported as probably switched off, with what
  was copied kept; a battle counts as finished by the furthest state seen.
- **Record Workshop:** "Put it in the record" on the Secret Bases tab (no `.sb3` download needed;
  the same owner's base at the same spot is replaced, not doubled).
- **The battle partner** (docs/BATTLE.md, "The battle partner"): the DUO holds each choice for the PC
  (polls 12 and 13), checks its answer against the rules, and chooses by itself if the PC is silent
  for `--fallback` seconds or answers against the rules. The PC's picture of the battle is
  `duo_battle.LinkBattle`. **Impossible** (`duo_battle.Impossible`) sees the player's whole team and
  waits for the player's choice each turn (it reaches every GBA over the link) before choosing.
  Doubles have their own chooser. Every `.pk3` is checked first (`duo_battle.check_legal`); one that
  couldn't exist is refused unless `--allow-unchecked`.
- **Tests:** the player pacing in, shadowing and sitting in the DUO's way; switched off after a
  battle and after Record Mixing; the workshop's button; the battle partner (medium, impossible,
  the PC failing, an answer against the rules, doubles, an impossible Pokémon); planted bugs for each,
  including in `room_walk.h` (`mutate4.py` now plants bugs in the shared header and in `duo_battle.py`).
  The battle model (`tests/battle_game_model.py`) is closer to the real engine now.

## Next (towards every kind of link battle)

1. Hardware: the battle queue (HARDWARE_QUEUE.md 1-3), then fix what it shows.
2. Done 8 November (simulator): Emerald and FireRed/LeafGreen Colosseums (docs/BATTLE.md).
3. Done 8 November: elite and impossible plan a double battle's turn (`LinkBattle._double_plan`).
4. Multi battles: docs/MULTI.md. The Battle Tower's link multi battle is built (`tower.c`,
   `duo_events.py tower`, simulator, 8 November); hardware next. Four-player battles: an experiment.

## Space in the programs (bytes below 0x0203AE00)

- `trade`: about 190 spare (its screen lines were shortened on 8 November to make room after the
  room walk grew). Keep an eye on it before adding to `trade.c` or `room_walk.h`.
- `mix`: about 2.4 KB; `colosseum`: about 650 bytes; `adapter_lab`: about 20 (trim `SCOPE_N`,
  `CAP_CMDS`/`CAP_WORDS` or `W_MAX` before the next lab feature).

## Code facts

- **Repository:** `fredreckless/ActionReplayMaxDuo-Pokemon-Toolkit`. Push with
  `git push origin v42-local && git push origin v42-local:main`.
- **virtual/** is the Virtual DUO: its own check is `python3 virtual/check.py` (Linux); run it when
  anything under virtual/ changes. It never needs to pass for an ordinary toolkit push.
- **Programs** (`firmware/programs/*.c`, clang 18 + lld; `firmware/programs.py`): `adapter`,
  `adapter_lab`, `adapter_probe`, `ereader`, `trade`, `mix`, `colosseum`, `tower`; `room_walk.h` is shared.
  Everything must end below `0x0203AE00`. No hardware divide: no `/` or `%` on variables.
  **After any change to a program, run `python firmware/embed_programs.py`.**
- **Program protocol** (v4.2): `0x23` RUN, `0x2A` POLL (low byte selects; `idx << 8`), `0x2B` STOP,
  `0x2C` PUT (poll 20 starts a load, 21 checks its CRC). The link to the PC strictly alternates.
- **Colosseum polls:** 0 state; 2 link type and language; 3 commands/answers/outcome; 4 the record a
  word at a time; 5 its length; 11 fainted/choices/dropped/lost; **12 what's waiting for the PC
  (and the PC's heartbeat); 13 the PC's answer**. The blob: byte 2 = the PC chooses, byte 3 = the
  fallback in seconds.
- **Battle facts** (pokeruby): commands broadcast to every GBA as blocks (8-byte header, then data);
  the game's battlers are even, the DUO's odd; `SETMONDATA` request 42 is HP, 40 status, 8-12 PP,
  0 the whole `BattlePokemon`; every player's answers (state 1) reach every GBA in a link battle.
- **Tests:** `python tests/check.py quick|changed|full|what`; `python tests/run_each.py [FILTER]`;
  `python tests/mutate4.py [KIND ...]` (kinds `fw`, `fw42`, `prog`, `ereader`, `trade`, `mix`,
  `colosseum`, `pc`). Each new workspace starts without Datel's firmware: stage
  `ActionReplay\Datel\us_update_v1_06\us_update_v1_06\us_update_v1_06.bin` from the user's PC and run
  `python firmware/build_firmware.py FILE --all` first (v4.1 CRC `A5303402`, v4.2 `DD59ED8A`).
- **References (not in the repo):** pret's pokeruby, pokeemerald and pokefirered (raw files can be
  fetched from raw.githubusercontent.com; the GitHub API is blocked here); GBATEK; Project Pokémon's
  event gallery (the user's files).
