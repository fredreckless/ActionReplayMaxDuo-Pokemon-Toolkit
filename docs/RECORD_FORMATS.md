# Record files: every part of a Record Mixing record

**Status (6 November 2026): specification, draft 1, in use for Ruby and Sapphire; the user's decisions are
at the end.** `records.py` reads, checks, writes and predicts every part; `duo_events.py mix` sends any of
them; the Record Workshop page makes old men, trends and whole records. It extends
`.sb3` (docs/SB3_FORMAT.md) to everything else a Record Mixing record carries. The tool and the web
page that will use it are planned in docs/RECORD_WORKSHOP.md.

Sources: pokeemerald `src/record_mixing.c` (the record and the order the game takes its parts in),
`include/global.h`, `include/global.tv.h`, `include/constants/tv.h`, `include/battle_tower.h`,
`include/daycare.h`, `include/record_mixing.h`, `src/tv.c`, `src/dewford_trend.c`,
`src/mauville_old_man.c`, `src/lilycove_lady.c`, `src/battle_tower.c`; pokeruby
`src/record_mixing.c`, `include/global.h`. All sizes below were checked against the offsets the
sources give for `struct PlayerRecordEmerald`.

## The idea, as for `.sb3`

- **Each file holds the game's own bytes**, exactly as the game keeps them and sends them, with no
  header or wrapper of ours. Anything that knows the game knows the file; the file name carries the
  human description ("BARD - song by WILLOW (ENG).om3").
- **One thing per file**: one TV show, one trend, one Battle Tower trainer. A sitting loads as many
  as the record has room for, as the tool already does for bases.
- **Little-endian**, as on the GBA. Text is Gen 3 text, ended and padded with 0xFF.
- **Emerald's layout where the games differ only by additions**, so that one file serves Ruby,
  Sapphire and Emerald. Where the layouts really differ (the Battle Tower trainer), both forms are
  allowed and told apart by size, and the tool converts between them as Emerald does.
- **Fields that describe the receiving player's copy, not the thing itself, are 0 in a file**
  (as with a base's "registered" and "times entered"). A reader accepts other values and warns.
- **Checksums**: where the game keeps one (the Battle Tower trainer, apprentices), the file keeps
  it too and the tool recomputes it on writing. Elsewhere there is none, as in the game.

## The whole record: `.rm3`

A `.rm3` is one player's whole record, exactly as it travels over the link: the bytes a game sends
in its 200-byte blocks, without the filler of the last block. Its size says its layout:

| Size | Layout | Used when |
|---|---|---|
| 4,656 (0x1230) | Ruby/Sapphire (`PlayerRecordRS`) | any player in the sitting is Ruby or Sapphire |
| 5,188 (0x1444) | Emerald (`PlayerRecordEmerald`) | only Emeralds are mixing |

A `.rm3` is what the DUO will send (today it sends only bases of its own and hands the game's other
parts back: docs/RECORD_WORKSHOP.md), and what it keeps from the game after a sitting ("what the
game sent"). The tool builds one from part files and takes one apart into them. Because a record's
meaning depends on who sent it (version and language: Emerald rewrites Ruby's TV shows and
Japanese text on receipt), a `.rm3` on its own doesn't say whose it is; the tool records the
sender's version and language in the file name, and asks when it isn't there.

### Its parts

| Offset (Ruby) | Offset (Emerald) | Part | Size | Part file |
|---|---|---|---|---|
| 0x0000 | 0x0000 | Secret Bases, 20 | 20 × 160 | `.sb3` (exists) |
| 0x0C80 | 0x0C80 | TV shows, 25 | 25 × 36 | `.tv3` |
| 0x1004 | 0x1004 | PokéNews, 16 | 16 × 4 | `.pn3` (the set of 16) |
| 0x1044 | 0x1044 | The Mauville old man | 64 | `.om3` |
| 0x1084 | 0x1084 | Dewford trends, 5 | 5 × 8 | `.dt3` |
| 0x10AC | 0x10AC | Day-care mail | 120 | `.dm3` (one letter) |
| 0x1124 | 0x1124 | Battle Tower trainer | 164 / 236 | `.bt3` |
| 0x11C8 | 0x1210 | Gift item | 2 | none: a setting |
| 0x11CA | — | (filler) | 102 | — |
| — | 0x1214 | Lilycove lady | 64 | `.ll3` |
| — | 0x1254 | Apprentices, 2 | 2 × 68 | `.ap3` |
| — | 0x12DC | Battle Frontier hall records | 344 | `.hr3` (the set) |
| — | 0x1434 | (filler) | 16 | — |

## The part files

For each: what it holds, what the game does with it when it arrives (pokeemerald's
`ReceiveExchangePacket` takes the parts in the order of the table above), and what the tool checks.
"Structural" problems are refused; "fair play" ones (things a real player's game couldn't have
made) are warnings, refused with `--strict`, as for `.sb3`.

### `.sb3` Secret Base (160 bytes)

Specified in docs/SB3_FORMAT.md; unchanged.

### `.tv3` one TV show (36 bytes, `TVShow`)

- **Layout:** byte 0 the kind (`TVSHOW_*`, 1-41), byte 1 "on the air", then the kind's own fields
  (`include/global.tv.h`: about thirty layouts: Fan Club letters, Bravo Trainer, Contest Live
  Updates, the Lotto winner, Secret Base visits, mass outbreaks and so on). Bytes 0x1C-0x23 of most
  kinds hold up to four trainer IDs: whose show it was and who passed it on.
- **In a record:** the first five slots are the sender's own local shows; the other twenty are
  shows that can travel. The receiving game merges them (`ReceiveTvShowsData`, `SetMixedTVShows`):
  it skips shows it already has and shows that came from itself, keeps a limited number, takes
  shows off the air if they mention a Pokémon the player hasn't seen, or post-game things before
  the player has finished the game. Emerald translates Ruby's shows and Japanese Emerald's
  (`TranslateRubyShows`, `TranslateJapaneseEmeraldShows`).
- **In a file:** "on the air" = 1; the kind's fields as the game would fill them.
- **Checks:** a known kind that can travel; species, items, moves and Easy Chat words that exist;
  text that fits; fair play: values a game could produce (a Lotto number of five digits, a win
  streak a real player could have).
- **To settle in research step 1:** which kinds travel at all, and Ruby's kind numbers against
  Emerald's.

### `.pn3` PokéNews (64 bytes: the set of 16)

- **Layout:** 16 × {kind, state, days left (u16)}: the news items (Slateport sale, Gamer, Lilycove
  festival, Blend Master) that make in-game events happen for a few days.
- **In a record:** mixed by `SetMixedPokeNews`; items the game already has, or that it can't use
  yet, are cleared. Kept as one file because a single item is four bytes and means little alone.
- **Checks:** known kinds; days left within what the game sets.

### `.om3` the Mauville old man (64 bytes, `OldMan`)

- **Layout:** byte 0 says which of the five characters he is: the **Bard** (a six-word song),
  the **Hipster** (teaches an Easy Chat word), the **Trader** (four decorations and who traded
  them), the **Storyteller** (four tales of game records and whose they were), or **Giddy** (ten
  random words, eight questions). Each has its own layout in `include/global.h`.
- **In a record:** the receiving game takes the old man of the player it is paired with, whole,
  after tidying his text for its language (`ReceiveOldManData`). **With the DUO as the only
  partner, the player gets exactly the DUO's old man.**
- **Checks:** a known character; real Easy Chat words, decorations and game-record kinds; names
  that fit; fair play: a Storyteller's numbers a game could reach.

### `.dt3` one Dewford trend (8 bytes, `DewfordTrend`)

- **Layout:** trendiness (7 bits), maximum trendiness (7 bits), rising or falling (1 bit); a random
  number (u16); the two-word phrase (two Easy Chat words).
- **In a record:** up to five. The game pools everyone's, keeps the trendier copy of any phrase it
  already has, sorts by trendiness and keeps the top five (`ReceiveDewfordTrendData`). The top
  phrase is what Dewford's people talk about.
- **Checks:** two real Easy Chat words from the groups the game allows for trends; trendiness not
  above its maximum (at most 98 and 120 in the game's own rules: to confirm).

### `.dm3` one day-care letter (56 bytes, `DaycareMail`)

- **Layout:** the letter (`struct Mail`: nine Easy Chat words, the writer's name and ID, the
  species and the kind of Mail) and the names of the Pokémon's trainer and the Pokémon, and their
  languages. In a record, two of these, how many Pokémon are in the day care, and whether each
  can hold an item.
- **In a record:** the games **swap letters** between Pokémon in their day cares that hold Mail
  (`ReceiveDaycareMailData`, the same random choice on every GBA, seeded by player 0's ID). So a
  letter can reach the player only if their own day-care Pokémon is holding Mail.
- **Checks:** real words, a real Mail item, names that fit.

### `.bt3` one Battle Tower trainer (164 or 236 bytes)

- **Two forms:** Ruby/Sapphire's (`RSBattleTowerRecord`, 164 bytes: level mode, trainer class, win
  streak, name, ID, a six-word greeting, three Pokémon, checksum) and Emerald's
  (`EmeraldBattleTowerRecord`, 236 bytes: the same plus won and lost speeches, four Pokémon and
  the language). Each Pokémon is 44 bytes: species, item, moves, level, PP bonuses, six EVs, OT ID,
  IVs and ability bit, personality, nickname, friendship.
- **In a record:** the receiving game adds the trainer to the ones it can meet in its Battle Tower
  (`ReceiveBattleTowerData`, `PutNewBattleTowerRecord`), converting Ruby's form to Emerald's.
- **Checksum:** the sum of the record's 32-bit words before the checksum (`CalcRubyBattleTowerChecksum`;
  Emerald's is the same over its own size: to confirm). The tool writes it.
- **Checks:** legal Pokémon (species, moves it can learn, items, EVs totalling at most 510, IVs
  0-31, level 50 or 100 for the mode); no duplicate species or items as the Tower requires; fair
  play: a win streak a real player could have.

### `.ll3` the Lilycove lady (64 bytes, Emerald only)

- **Layout:** byte 0 says which lady: the **Favor** lady (an item she wanted and who gave the best),
  the **Quiz** lady (a nine-word question, its answer and a prize) or the **Contest** lady
  (Pokéblocks for a contest category).
- **In a record:** the game swaps ladies with its partner (`ReceiveLilycoveLadyData`): the player
  meets the DUO's lady, and the quiz is reset for a new challenger.
- **Checks:** a known lady; real words and items.

### `.ap3` one apprentice (68 bytes, Emerald only)

- **Layout:** which apprentice (id), level mode, number of questions answered, three Pokémon
  (species, moves, item), a six-word winning speech, the player's ID, name and language, checksum.
- **In a record:** two; the game keeps those it hasn't already got (`ReceiveApprenticeData`). They
  appear at the Battle Tower as trainers to battle.
- **Checks:** a real apprentice id; legal Pokémon; the checksum.

### `.hr3` Battle Frontier hall records (344 bytes, Emerald only)

- **Layout:** for nine facilities × two level modes, the best single-player streak (ID, streak,
  name, language), and the best two-player streaks: the Ranking Hall's lists.
- **In a record:** merged into the receiving game's rankings (`ReceiveRankingHallRecords`).
- **Checks:** streaks a real player could have (fair play), names that fit.

### The gift item (2 bytes in the record, no file)

A Key Item that player 0 passes on to everyone else (`ReceiveGiftItem`): the Eon Ticket, in the
games' own Mystery Gift route. Only from player 0, only a Key Item the player hasn't got. The tool
already sends it (`mix --gift`).

## What stays the same for every part

- **Names in files:** `KIND - description (LANG).ext`, as for `.sb3`, made by the tool and the
  workshop; the name is never read for data.
- **Language:** a part's text is the sender's language. The tool writes the `language` fields where
  a part has them and refuses a Japanese name in a non-Japanese part (and the other way round).
- **From a save backup:** every part can be read from a Ruby, Sapphire or Emerald save backup, as
  the bases already are (`duo_events.py bases`), so a player's real shows, trends and old man can be
  kept and passed on.
- **Versioning:** each file format is version 1 as specified here; a later version may only add
  meaning to bytes this version requires to be 0.

## Ruby and Sapphire: what the research found (step 1, begun 6 November)

Read in pokeruby (`record_mixing.c`, `tv.c`, `mauville_man.c`, `battle_tower.c`, `daycare.c`):

- **Order:** bases, TV shows, news, old man, trends, day-care letters, Battle Tower, gift
  (`RecordMixing_ReceiveExchangePacket`).
- **TV shows:** Ruby and Sapphire know only 12 kinds: 1-6 (interviews: Fan Club letter and
  opinions, Recent happenings, Name Rater, two Bravo Trainer profiles), 21-25 (Pokémon Today
  caught and failed, Smart Shopper, Fishing advice, World of Masters) and 41 (mass outbreak).
  Before sending, a game takes its own interviews in the first five slots off the air
  (`sub_80C045C`). On receipt, a show is passed on only if it didn't come from the receiver (the
  trainer IDs in bytes 0x1C-0x23 are checked and shifted along, `sub_80C004C`/`sub_80C00B4`); shows
  about a Pokémon the player hasn't registered, and Battle Tower and outbreak shows before the
  player has beaten the game, are taken off the air; other kinds are always taken off.
- **The old man** (Ruby's layout has no language byte): swapped whole with the paired player's
  (`ReceiveOldManData`), then his "already" flag reset, so he talks afresh.
- **Battle Tower:** the paired player's trainer replaces one of the five the game keeps (the same
  trainer's earlier record, an empty slot, or one of the lowest streaks at random,
  `sub_8134AC0`). The game only puts that trainer in front of the player when **their win streaks
  match** at the same level, and drops any record whose checksum is wrong
  (`ValidateBattleTowerRecordChecksums`).
- **Day-care letters:** Pokémon in the day care that hold no item can swap letters (one left there
  holding Mail counts: the game takes the letter off it and keeps it beside the Pokémon). When the
  player takes the Pokémon back, the swapped letter comes with it (`daycare.c`).
- **Gift item:** Ruby and Sapphire accept **any item** from player 0, not only Key Items (Emerald
  accepts only Key Items); a Key Item they already have is refused.

`records.py` (6 November) reads a Ruby or Sapphire save's own record exactly as the game would
send it, splits and joins `.rm3` files, and checks each part. Still to do in step 1: the TV and
news merging, the trends' merging and the old man's per-character resets in the game model, so
the tool can say beforehand what the game will keep.

## Decisions (the user, 6 November)

1. **Both:** a whole-record file (`.rm3`) and a file per part.
2. **Ruby first:** the Ruby/Sapphire layout (which mixes with all three games); the Emerald-only
   parts (lady, apprentices, Ranking Hall) once the DUO can mix as an Emerald.
3. **The game's own lines, one for one,** read from the user's own cartridge copy (as the pictures
   are), never stored in the repository.
