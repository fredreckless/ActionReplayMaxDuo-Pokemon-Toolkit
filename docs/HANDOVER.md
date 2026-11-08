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
- **The user's PC:** Windows; Python 3.10 (Thonny); `C:\Users\fredr\ActionReplay`. Files reach it
  through the desktop bridge when the chat is linked. **After copying a file there, read it back and
  compare SHA-1s**, with a fresh staged file name each time. Run logs are in `logs\` there: read them
  through the bridge rather than asking for pasted output.
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

**Hardware next:** docs/HARDWARE_QUEUE.md, from the top: a single battle at medium, then impossible,
then a double battle; Record Mixing with the player in the DUO's way.

## What changed on 8 November

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
4. Multi battles: docs/MULTI.md (the Battle Tower's link multi battle first: two GBAs).

## Space in the programs (bytes below 0x0203AE00)

- `trade`: about 190 spare (its screen lines were shortened on 8 November to make room after the
  room walk grew). Keep an eye on it before adding to `trade.c` or `room_walk.h`.
- `mix`: about 2.4 KB; `colosseum`: about 650 bytes; `adapter_lab`: about 20 (trim `SCOPE_N`,
  `CAP_CMDS`/`CAP_WORDS` or `W_MAX` before the next lab feature).

## Code facts

- **Repository:** `fredreckless/ActionReplayMaxDuo-Pokemon-Toolkit`. Push with
  `git push origin v42-local && git push origin v42-local:main`.
- **Programs** (`firmware/programs/*.c`, clang 18 + lld; `firmware/programs.py`): `adapter`,
  `adapter_lab`, `adapter_probe`, `ereader`, `trade`, `mix`, `colosseum`; `room_walk.h` is shared.
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
