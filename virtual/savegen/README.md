# The save generator

`savegen.py` makes a save, and the rehearsals' save states, from a ROM alone: no hand-made save,
no hand-made states, and the game's own code does all the writing.

    python3 virtual/savegen/savegen.py --rom ruby.gba --out DIR [--pk3s DIR/pk3] [--name TESTER]

It writes `DIR/ruby.sav`, the five states the rehearsals take (`at_trade_question`,
`at_colosseum_question`, `at_record_question`, `at_blender_question`, `at_link_standby`, each
`.state` with a `.png` of the screen beside it), and with `--pk3s` three made-up Pokemon for the
DUO's side (`offer.pk3`, `team1.pk3`, `team2.pk3`). English Ruby takes about ten seconds.

## How

1. **The opening, by button presses.** The ROM boots with no save; A through the intro, the title
   screen, NEW GAME and the professor's talk (a boy; the naming screen gets START then A); then
   START until it opens a menu, which the game allows only once the player has control.
2. **What the Cable Club needs, in RAM** (the profile's list, nothing else): the player's name,
   fast text, six made-up Pokemon at level 50 with their level-up moves (the toolkit's own .pk3
   code: `duo_battle.check_legal` passes each, and the trainer is the player, so they're the
   player's own), a Pokeblock Case and ten each of twenty berries, and the flags (the Pokemon and
   the Pokedex received, the cities visited, the clock set, Mystery Events on, the Pokeblock Case
   received).
3. **Where CONTINUE puts the player:** the game's own special warp (`gSaveBlock2.specialSaveWarp`
   and `gSaveBlock1.warp1`, used after a link save), pointed at Mossdeep's Pokemon Center upper floor.
   So the game itself loads that map fresh, with its own people, when the save is continued.
4. **START > SAVE > YES**, and the game writes the save in its own layout with its own checksums.
   `check_save` then reads it back (14 sectors, signatures and checksums).
5. **The states.** For each, a fresh boot from that save; on the title menu the special warp is
   pointed at the attendant's counter (or the Contest Lobby's Berry Blender), then CONTINUE, a tap
   to face the counter, and A until the game's YES/NO (or YES/NO/INFO) box is up. The Mystery
   Events state is the title menu's third item, waiting at "Link standby". The save on disk is the
   same for every state: only where the player stands differs, as if they'd walked there.

## Profiles

`profiles.py` holds what differs between games: RAM and code addresses (from pret's symbols),
the save blocks' offsets (Ruby's are fixed; Emerald's and FireRed/LeafGreen's move, so they are
read through `gSaveBlock1Ptr`/`gSaveBlock2Ptr`, and their bag quantities are XORed with the save's
encryption key), the flags, item numbers, the maps and the attendants' spots. A ROM is matched by
its header's game code and version byte.

| ROM | Save | States |
|---|---|---|
| English Ruby 1.1 (AXVE v1) | `ruby.sav` | `at_trade_question`, `at_colosseum_question`, `at_record_question` (Mossdeep), `at_blender_question` (Lilycove's Contest Lobby), `at_link_standby` (MYSTERY EVENTS) |
| English Emerald (BPEE v0) | `emerald.sav` | `at_cable_club_menu` (Mossdeep's Direct Corner, which with no Wireless Adapter is the Cable Club: TRADE CENTER, COLOSSEUM, RECORD CORNER), `at_blender_question`, `at_contest_question` (the link contest's ENTER/INFO/EXIT), `at_title_mystery_gift` |
| English LeafGreen 1.1 (BPGE v1) | `leafgreen.sav` | `at_cable_club_menu` (Viridian: TRADE CENTER, COLOSSEUM), `at_title_mystery_gift` |

English Emerald's and LeafGreen's MYSTERY GIFT won't open without a Wireless Adapter (the DUO's
part), so those states stop with it highlighted on the title menu, for a rehearsal to press A.
FireRed/LeafGreen have no Pokeblock Case, Record Corner, Blender or contests. The other
languages need a code search for their addresses (pret has symbols for the English ROMs only).

## Proven (13 November 2026)

From a generated English Ruby save and its states, all seven rehearsals pass (`rehearsals/all.sh`):
trade, single and double battle, Record Mixing, Mystery Event, the Blender from either end. The
states match Fred's hand-made ones screen for screen. One rehearsal fix came out of it: with a
party the DUO can beat, the game's side faints a Pokemon, and pressing A in the party menu only
says the fainted one can't battle; `ruby.battle_press` now moves to the next one and shifts.

Emerald and LeafGreen (13 November, later): saves and states made and checked (14 of 14 sections,
the party and the decrypted bag read back, every state's screen as intended). They have no
rehearsals yet: `rehearsals/` is still English Ruby's.
