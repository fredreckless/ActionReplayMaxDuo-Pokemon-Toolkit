# The Record Workshop: a plan

**Status (6 November 2026, late): steps 1-3 done in the simulator; hardware next.** The formats
are in docs/RECORD_FORMATS.md.

- Step 1: the game model (`tests/mix_game_model.py`) merges TV shows, news, the old man, trends,
  day-care letters and the Battle Tower as pokeruby does; `records.py predict` is the tool's own
  port, and a test checks the two agree in 120 random sittings (both are this session's work, so
  hardware still has the last word).
- The DUO sends a whole record (`mix.c`): the PC's file now lives in the firmware's save-transfer
  buffer (0x02010030, unused while a program runs), which also freed 3 KB of the program's area;
  parts we don't bring are handed back from the game's own chunks, as before; the game's whole
  record comes back to the PC (`records\` folder).
- Steps 3-5 (7 November): **every Ruby/Sapphire part has its tab**: Secret Bases, the Mauville
  old man (all five), Dewford trends, TV shows (all twelve Ruby kinds), PokéNews, day-care
  letters, the Battle Tower trainer, and the whole record. With the user's ROM loaded, the page
  shows the game's own lines one for one: each TV show played as pokeruby's `DoTVShow*` plays it
  (its random choices too: "Another take"), the Bard's verses and lines, the Storyteller's tales,
  Dewford's trendy boy, the TV's PokéNews announcement, trainer classes and place names. The text
  is found by pret's addresses for English Ruby (revisions 0-2) and Sapphire (revision 0), and
  `duo_rom.py` copies it into its "workshop parts" file. Checked with a real Ruby 1.1 ROM in the
  browser (locally; nothing of it kept).
- Still to come: Emerald (its own layout, and the Lilycove lady, apprentices and Ranking Hall:
  step 7, once the DUO can mix as an Emerald), Sapphire revisions 1-2 and non-English games' lines.

The Secret Base Workshop (`secret_base_workshop.html`) grows into a **Record Workshop**: one page,
still a single file that works offline and on GitHub Pages, with a tab for each part of a record,
and a Record tab that puts a whole record together for the DUO to send.

## What it's for

- Make anything a Record Mixing partner can hand over: bases, TV shows, the Mauville old man,
  Dewford trends, day-care letters, a Battle Tower trainer, and (Emerald) the Lilycove lady,
  apprentices and Ranking Hall records.
- Open what a game already has (a save backup, or what the game sent the DUO) and edit or keep it.
- Show, before mixing, what the game will do with it ("the Bard will sing this song", "this trend
  will be top in Dewford", "this show stays off the air until you've seen Feebas").
- Keep everything a real game could have made, with warnings where it couldn't, as now.

## The page

A tab bar along the top; each tab has the same shape as today's workshop: an editor on the left, a
picture or preview on the right, the checks and the bytes below, and Open / Save / New.

| Tab | Editor | Preview |
|---|---|---|
| **Record** | load a `.rm3` or a save backup; see every part; choose which files go in; layout (Ruby or Emerald); gift item | the record as a map of its 4.6 KB, part by part, with what the game will keep |
| **Secret Bases** | today's workshop, unchanged | today's room |
| **TV** | choose a show kind, then its fields (species, words, numbers, names) | the TV screen with the show's lines |
| **PokéNews** | the sixteen items, kind and days left | which events will be on in which towns |
| **Old man** | choose the character, then: the Bard's six-word song, the Hipster's word, the Trader's four decorations, the Storyteller's four tales, Giddy's words | Mauville's old man with his speech |
| **Trends** | up to five two-word phrases and their trendiness | the Dewford townsfolk's line; the top five after mixing with the player's own |
| **Mail** | a letter: kind of Mail, nine words, signature | the letter on its stationery |
| **Battle Tower** | trainer class, name, greeting (and Emerald's speeches), three or four Pokémon | the trainer card the Tower shows |
| **Lilycove lady** (Emerald) | which lady and her request or quiz | the lady with her line |
| **Apprentices** (Emerald) | an apprentice's three Pokémon and speech | the apprentice at the Tower |
| **Ranking Hall** (Emerald) | nine facilities' best streaks | the Ranking Hall board |

### Pieces shared by several tabs

- **The Easy Chat word picker** (trends, Bard, Hipster, Giddy, mail, Tower greetings, quiz): the
  game's groups and words, searchable, with the rules for which groups each place allows.
- **The Pokémon editor** (Tower trainer, apprentices, the bases' teams): species, level, moves it
  can learn, item, EVs, IVs, nature and ability, with the battle partner's legality checks
  (`duo_battle.py` already knows every species and move).
- **Name and ID fields** with Gen 3 text, the language and its limits (today's owner fields).
- **Checks and bytes** for every tab, the same panel as today's.
- **Help** ("How to use" per tab, as today's) and Generate where it makes sense (a random but
  sensible Bard song, trend, Tower trainer).

### The game's own text and pictures

The page draws with nothing of the game's by default, so the repository stays free of Nintendo's
data. "Use my ROM…" (today's button) will also read, from the user's own cartridge copy, the TV
scripts, the old man's lines, the Easy Chat words and the trainer pictures, so previews show the
game's own words and faces. `duo_rom.py` gains those parts for its targeted copy. Without a ROM,
previews say the same things in our own words.

## On the PC and the DUO

- **`records.py`** (new, beside `secret_bases.py`): read, check and write every part file and the
  whole record; take a record apart and put one together; read every part from a save backup;
  predict what the game keeps (as `predict_mix` does for bases: trends, TV shows and Tower trainers
  next). The web page and the Python agree byte for byte (tested, as the workshop's tables are now).
- **`duo_events.py mix`** gains `--record FILE.rm3` and part options (`--tv`, `--old-man`, `--trend`,
  `--mail`, `--tower`…), and saves what the game sent as a `.rm3` and as part files.
- **The DUO's program** (`mix.c`) today holds only the PC's twenty bases (3,200 bytes); for the
  rest of the record it hands the game's own parts straight back, so that nothing else in the
  game changes, with an empty Battle Tower trainer. To send our TV shows, old man and the rest it
  must hold the PC's whole record (4,656 bytes) instead, and `mix.c` is at its size limit (0 bytes
  spare). So the first DUO task is room: a larger buffer outside the program's area if the DUO's
  RAM allows it, or the PC passing the record in pieces between rounds. **Mixing as an Emerald**
  (for the Emerald-only parts) also needs the DUO's link player to say Emerald, which is the known
  "DUO says Ruby" problem.

## Steps

1. **Research and the game model.** Read every `Receive*` and `Sanitize*` function in full, the TV
   show kinds that travel, the trend and checksum rules; extend `tests/mix_game_model.py` so the
   simulated Ruby and Emerald merge every part as the games do. Settle the open questions in
   RECORD_FORMATS.md.
2. **`records.py`** and its tests: every part read, checked, written, and round-tripped through a
   save backup and the model.
3. **The Record tab and the simple parts** (Old man, Trends, Mail, PokéNews) in the page, with the
   Easy Chat picker; Playwright tests as for the base workshop.
4. **The Battle Tower trainer** with the shared Pokémon editor.
5. **TV shows**, kind by kind, starting with those players see most.
6. **Hardware with Ruby:** a sitting that hands over an old man, a trend and a Tower trainer, then
   checking each in the game (the Bard's song in Mauville, the phrase in Dewford, the trainer in
   the Tower).
7. **Emerald:** mixing as an Emerald, then the lady, apprentices and Ranking Hall tabs.

Between steps 2 and 3, **the DUO sends a whole record** (`mix.c`: room for it, then sending the
PC's record instead of handing the game's parts back), tested in the simulator before any page
work depends on it.

Each step ends with its tests and a push, as usual; once the DUO sends whole records, each tab can
be used as soon as it lands.
