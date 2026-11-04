# The `.sb3` file: one Secret Base

**Status (4 November 2026): specification, version 1, for review. Nothing reads or writes it yet.**
Background and the Record Mixing protocol are in `docs/RECORD_MIXING.md`.

## The idea

`.pk3`, `.wc3` and `.me3` files all hold **the game's own structure, byte for byte**, with no
header or wrapper of their own. A `.pk3` is the 80 or 100 bytes of a Pokémon as the game stores
it. A `.wc3` is the Wonder Card as the game stores it. A `.me3` is the Mystery Event as the game
receives it. Anything that knows the game knows the file, and the file name carries the human
description.

`.sb3` follows the same pattern. **An `.sb3` file is exactly 160 bytes: one `struct SecretBase`,
as it sits in a Gen 3 save's list of twenty bases and as it travels in a Record Mixing record.**

- **One base per file.** The tool loads several files for one sitting, up to twenty.
- **Byte order:** little-endian throughout, as on the GBA.
- **Layout:** Emerald's, which is the same as Ruby's and Sapphire's except for one byte (0x0D, the
  language). The file therefore works for all three games.
- **No checksum.** The game keeps none for a base, so the file has none either. The tool's
  checks (below) do that job.

## Layout

| Offset | Size | Field | In a file |
|---|---|---|---|
| 0x00 | 1 | location (`secretBaseId`) | one of the 75 location IDs (appendix of `RECORD_MIXING.md`); never 0 |
| 0x01 | 1 | flags | bit 4 = owner's gender (0 boy, 1 girl); **all other bits 0** |
| 0x02 | 7 | owner's name | Gen 3 text, ended and padded with 0xFF; at most 7 characters (Japanese: 5) |
| 0x09 | 2 | owner's trainer ID | u16, the public ID players see |
| 0x0B | 2 | owner's secret ID | u16 |
| 0x0D | 1 | language | the name's language: 1 Japanese, 2 English, 3 French, 4 Italian, 5 German, 7 Spanish; 0 = not known |
| 0x0E | 2 | bases the owner has received | u16 (`numSecretBasesReceived`); 0 for a hand-made base |
| 0x10 | 1 | times entered | **0** |
| 0x11 | 1 | unused | **0** |
| 0x12 | 16 | decorations | decoration IDs 1–120, used slots first, then 0s |
| 0x22 | 16 | decoration positions | for each decoration: x in the high four bits, y in the low four; 0 for an empty slot |
| 0x32 | 2 | padding | **0** |
| 0x34 | 24 | team: personality | six u32 |
| 0x4C | 48 | team: moves | six × four u16 move IDs (1–354), 0 = no move |
| 0x7C | 12 | team: species | six u16, the games' internal species numbers (the same numbers a `.pk3` uses); 0 = empty |
| 0x88 | 12 | team: held items | six u16 item IDs, 0 = none |
| 0x94 | 6 | team: levels | 1–100 |
| 0x9A | 6 | team: EVs | 0–255, one number per Pokémon (the game puts it in all six stats) |

The team's six entries line up across the arrays: entry *k* is `personality[k]`, `moves[4k..4k+3]`,
`species[k]`, `heldItems[k]`, `levels[k]` and `EVs[k]`.

### Why some fields are always 0 in a file

A few bytes describe **the receiving player's** copy of a base, not the base itself:

- whether that player has registered the base, and the "new" and "to register" markers (bits 0–3
  and 6–7 of 0x01);
- whether they've battled the owner today (bit 5);
- how often they've entered it (0x10).

A file is the base as its owner would hand it over, so these are 0. A reader **accepts** a file
with them set and clears them. The game clears most of them itself on receipt anyway.

### The language byte

Ruby and Sapphire have no language byte (0x0D is padding there, normally 0). Emerald stores one,
and overwrites it with its own language when the base comes from a Ruby or Sapphire. In a file,
0x0D says **which alphabet the name is written in**, so the tool can show it and refuse to send
a Japanese name to a European game or the other way round. A base read from a Ruby or Sapphire
save gets the language from the cartridge's game code (AXV**E** English, AXV**D** German, and so
on). A base whose language really isn't known keeps 0, and the tool treats it as matching the
game it's sent to.

## What a valid `.sb3` is

The tool refuses a file, and gives the reason, when any of these fail.

**Structure** (the game would misbehave otherwise):

1. The file is exactly 160 bytes.
2. The location is one of the 75 real IDs.
3. The name has 1 to 7 characters (Japanese: 1 to 5), uses only characters of its language's
   alphabet, and is padded with 0xFF.
4. Decorations: IDs 1–120, packed from the first slot, each with its position. Empty slots are 0
   in both arrays.
5. Team: between 1 and 6 Pokémon, packed from the first entry. Each has:
   - a real species (internal 1–411, excluding the unused 252–276, and never the Egg, 412);
   - a level from 1 to 100;
   - at least one move, all moves real (1–354) and none repeated;
   - an item that's 0 or one the target game has (Ruby and Sapphire 1–348, Emerald 1–376) and isn't
     a key item.
   Entries after the team are all 0.

**Fair play** (the game would accept it, but a real player couldn't have made it): the tool warns
by default, and refuses with `--strict`.

6. Every decoration sits on the floor of its location's room, and none overlap. The room's size
   and walls come from its map. The 24 room shapes are listed below.
7. No decoration appears more often than a player could own it. Step 2 will work out the game's
   limits from its decoration and shop data.
8. Each Pokémon's moves are ones its species can know at that level, and its EV number is at most
   85 (the most a real Pokémon's average can be: 510 ÷ 6).

What a base **can't** carry: a shiny Pokémon or chosen IVs. In battle the game makes every base
Pokémon with IVs of 15 and a random, never-shiny trainer ID, so the personality decides only its
nature, gender and ability.

## Sending several

`duo_events.py` (step 2) will take a list, for example:

```
python duo_events.py mix --base "WILLOW - Tree, Route 121 (ENG).sb3" "ODA - Red cave, Route 118 (ENG).sb3" ...
```

- **Up to 20 files.** The first one goes in slot 0, where a real player's own base would be; the
  rest go in slots 1 to 19. The game can keep at most 19 bases from others, so a twentieth is
  only worth sending if one of the others is sure to be refused.
- **The tool refuses a set** that would trip the game's own filing rules:
  - two bases at the same location (the game keeps only the first);
  - two bases with the same owner, i.e. the same gender, IDs and name (the game keeps only one).
- **It warns at the link** when a base's owner matches the player in the game (the game would
  delete it as the player's own). The game's link player gives its name and trainer ID.
- **What it can't see:** where the player's own base is, and how many bases they've registered. A
  base at their own base's location, or one that finds all nineteen slots registered, is quietly
  dropped. After the sitting the tool says how many bases it sent. Visiting the routes shows
  which ones arrived.

## Reading bases out of a game

`duo_events.py bases SAVE` (step 2) will read a save backup made by `maxduo_saves.py`, on the PC.
It never touches the cartridge.

- It finds the newest valid copy of the save, puts SaveBlock 1 together from sections 1 to 4, and
  reads the twenty bases. They start at 0x1A08 in Ruby and Sapphire and at 0x1A9C in Emerald.
  FireRed and LeafGreen have no Secret Bases.
- **It tells the game apart by the cartridge's game code**, which `maxduo_saves.py` puts in the
  backup's folder name (AXV/AXP Ruby/Sapphire, BPE Emerald, BPR/BPG FireRed/LeafGreen). A save's
  own bytes don't reliably say: a test on an English Ruby save looked like Emerald.
- It writes one `.sb3` for every slot that holds a base. Each file is cleaned up as above:
  receiver-only fields set to 0, the language byte filled in.
- **Slot 0 is the player's own base, and its team in the save is out of date.** The game only
  fills that team in at the moment it mixes records (`SetPlayerSecretBaseParty`), from the party
  it has then. So for slot 0 the tool builds the team the same way, from the save's party:
  - species, level, personality, held item and moves;
  - the average of each Pokémon's six EVs;
  - Eggs left out.
  That's exactly what a real Record Mixing would hand over.
- **File names** follow the EventsGallery's style, with the owner, the room kind and the route, for
  example `WILLOW - Tree, Route 121 (ENG).sb3`. When read from a save, the save it came from is
  added, so the file can be traced.

*Checked against a real save:* an English Ruby backup holds the player's own base in slot 0 at
location 222 (shrub, room 3, Route 120). Its team was empty, as expected, and the language byte
was 0.

## Making one by hand: the base card

Most `.sb3` files will be written by hand, so the tool will also turn a short text **base card**
into an `.sb3`, and an `.sb3` back into a card:

```
python duo_events.py base make "Willow.txt"         # writes "WILLOW - Tree, Route 121 (ENG).sb3"
python duo_events.py base show "WILLOW - Tree, Route 121 (ENG).sb3"
```

The card is only a way of writing an `.sb3`. **The `.sb3` is what's shared, checked and sent.** A
card looks like this:

```
# Secret Base card
owner      = WILLOW
gender     = girl
language   = English
id         = 01234
secret id  = 56789          # optional: chosen at random if left out
received   = 0              # optional
location   = Tree, Route 121           # or the ID: 162

decoration = Small Desk at 2, 3        # up to 16
decoration = Pikachu Doll at 5, 4
decoration = Red Plant at 6, 3

# up to 6: species, level, item, moves, EV number, and a nature (or an exact personality)
pokemon = Swampert  Lv 45 @ Leftovers : Surf, Earthquake, Protect, Rest   EV 85  nature Brave  male
pokemon = Manectric Lv 43 @ Magnet    : Thunderbolt, Roar, Quick Attack, Bite   EV 60
```

- Names of species, moves, items, decorations and locations are matched without minding capitals
  or spaces. A misspelling is answered with the nearest real name.
- `nature`, `male`/`female` and `ability 1`/`ability 2` make the tool choose a personality value that
  gives them. `personality = 0x1234ABCD` sets one exactly.
- `base make` runs every check above and won't write a file that fails the structural ones.
- `base show` prints the card for any `.sb3`, including ones read from saves, so a real player's
  base can be copied, changed and sent on.

## Appendix: the 24 rooms

A location's room is decided by its ID's tens digit. These are the rooms' map sizes in tiles,
walls included, from pokeemerald's layouts. Decoration positions are tiles inside them (0–15 each
way).

| Room | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| Red cave | 11 × 9 | 7 × 16 | 15 × 8 | 9 × 15 |
| Brown cave | 11 × 9 | 14 × 9 | 15 × 11 | 14 × 12 |
| Blue cave | 11 × 9 | 15 × 7 | 10 × 17 | 9 × 17 |
| Yellow cave | 11 × 9 | 14 × 9 | 12 × 11 | 13 × 14 |
| Tree | 11 × 9 | 7 × 16 | 17 × 8 | 14 × 14 |
| Shrub | 11 × 9 | 15 × 7 | 13 × 11 | 14 × 11 |

Which tiles count as floor will be read from each room's map in step 2. That's also where the
decorations' own sizes come in: a desk takes more than one tile.

## Version

This is version 1. If it ever needs to change, the 160-byte record stays as it is. Anything extra
would go beside it, never inside it, so every `.sb3` stays exactly what the game holds.
