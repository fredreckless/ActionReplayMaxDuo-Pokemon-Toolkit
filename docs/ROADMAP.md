# Roadmap: the events tool (`duo_events.py`)

Each stage builds on the last. The cheapest and most useful steps come first. Every stage goes
through the simulator (with a planted bug for each new behaviour) before it touches real hardware.

## The goal (agreed 30 October 2026)

> Support every Gen 3 Project Pokémon file meant for a GBA Pokémon game, by the route it
> originally came by, wherever that route leaves the game to save the event itself. Where it
> doesn't, offer the nearest route that does, and say so.

The files are those in Project Pokémon's events gallery (`projectpokemon/EventsGallery`,
`Released/Gen 3` and `Unreleased/Gen 3`). They stay on the user's PC and never enter this
repository.

| Files | Authentic route | Where we are |
|---|---|---|
| `.wc3` Wonder Cards (68) | Mystery Gift, as the distributions sent them | Japanese Emerald and English LeafGreen on hardware; other games and languages next (Stage 1) |
| Wonder News | The same route | Simulator only; the gallery has no Gen 3 news files yet (Stage 2) |
| `.me3` Mystery Events (13, all the Eon Ticket) | e-Reader to Ruby/Sapphire | Working on hardware: English Ruby received the Eon Ticket (lab session 26) |
| `.ecb` e-Card berries (18) | e-Reader Mystery Event (`setenigmaberry`) | English: working on hardware, the PUMKIN BERRY (lab session 27); Japanese: simulator done (Stage 7) |
| e-Card `.raw` scans (R/S trainers and promos; Emerald and FRLG trainers, Japanese) | Decode the dot codes and do what the e-Reader did | Ruby/Sapphire: all cards decode and pass the model; the DRASH BERRY on hardware (lab session 28); short cards fixed after lab session 29. Japanese Emerald's 66 Trainer Hill cards and Japanese FireRed/LeafGreen's 37 Trainer Tower cards: simulator done (Stage 8). The Berry Glitch Fixing Program is refused (it writes the save) |
| `.pk3` Pokémon (3,344) | Varies by event: see docs/PK3_EVENTS.md | **By trade for all** (decided 31 October), each labelled with its original route: working on hardware into English Ruby (lab sessions 29–30); Emerald and FireRed/LeafGreen in the simulator; up to six per sitting (Stage 9) |
| `.ect` e-Reader trainers (166) | e-Reader Mystery Event (`addtrainer`) | Simulator done: each matches its card's trainer byte for byte |

**Out of scope:** files meant for other games or for the GameCube (the Channel, Colosseum and
Pinball e-Cards; Pokémon from GameCube bonus discs).

**Routes that write the save directly.** Some original routes (many Pokémon distributions, as
far as we know, and the Berry Glitch Fixing Program) sent a program over the cable that wrote
the save itself, without the game's menus. That conflicts with the rule that our code never
writes cartridge saves. **The user decides** how to handle these; until then, the nearest route
that leaves the game in charge (for Pokémon, a trade through the game's own Trade Centre) is the
one to plan for, labelled as such.

## Stage 0: Make room and tidy up (done, 29 October 2026)

- **Free up memory.** Move the lab instrumentation (flick tables, link scope, command capture,
  timing calibration) into a separate lab build, so the everyday distributor has room to grow.
  Before this, 64 bytes were left below `0x0203AE00`.
- **Settings from the PC.** The serial number and the host's language come from the PC (or the
  game; see Stage 1) rather than being fixed in the code.
- **Check cards before sending them.** When loading a `.wc3`, check the card's and the script's
  CRC-16 (the game's own `CalcCRC16WithTable`), the script's magic and empty map fields, and the
  card size against the language. Warn about anything odd.
- **Small fixes.**
  - Ignore the harmless echoed acknowledgements ("unknown command 0xBD / 0x96"). Done: a word is
    ignored only when it is exactly our own last acknowledgement, so a genuinely unknown command
    is still refused.
  - The "second visit" to the Mystery Gift menu: the game had been started before the adapter
    was ready. On opening ふしぎな おくりもの, it found no adapter and offered the e-Reader instead
    (corrected in lab session 22). The fix is the start-up order: see the hand-over's to-do list.

Results:
- The everyday adapter build is 10,792 bytes, with about 960 bytes spare.
- The lab build (`--lab`) is 11,660 bytes. It keeps the instruments but leaves out the serial
  sweep.

## Stage 1: Wonder Cards for every Gen 3 game (simulator done; Japanese Emerald confirmed on hardware)

- **Recognise the game.** The adapter reads the version and language from the game's own
  broadcast data (command 0x16), then picks the distributor serial and card size itself.
- **A table of serials**, with a `--serial` override:

  | Game | Serial | Status |
  |---|---|---|
  | Japanese Emerald | 0x7F7F | confirmed on hardware (lab session 19); chosen automatically (session 21) |
  | English LeafGreen | 0x7F7D | confirmed on hardware (lab session 23) |
  | Others | 0x7F7D | from the English decomps; confirm with `--sweep-serial` |

  Each confirmed result goes into the table.
- **FireRed and LeafGreen.** Their Mystery Gift is the same protocol (pret/pokefirered), and
  `Rfu_GetWonderDistributorPlayerData` is identical. In the simulator, an English FireRed now
  receives a full-size (0x14C) card from serial 0x7F7D with an English host.
- **The host's language follows the game,** both in its broadcast data and in its link-player
  block. The trace names the game, for example "broadcast data (0x16) … - Japanese Emerald".
- **Hardware.** Japanese Emerald: game recognised, serial chosen and two cards received back to
  back without `--serial` (lab session 21). English LeafGreen: the full-size Aurora Ticket card, first time, serial 0x7F7D (lab session 23).
  Still to do, a short session per cartridge: English and European Emerald, FireRed, and
  LeafGreen in other languages. **Testers welcome.**

## Stage 2: Wonder News (simulator done, 29 October 2026; hardware to come)

The same Mystery Gift steps, but the server tells the game to save news rather than a card.
After receiving news, the delivery man gives berries.

- `news --news FILE` (formerly `--wonder-news`): the distributor advertises news (hasNews, `ACTIVITY_WONDER_NEWS`).
  - It sends the news under `MG_LINKID_NEWS`, and reads the game's answer: FALSE if the game saved
    it, TRUE if it already had the same news.
  - It then ends with "news received" or "you already had it", as the decomp's server does.
- **Sizes.**
  - English news is 444 bytes (pokeemerald).
  - **Japanese news is taken to be 202 bytes.** That's unconfirmed: the Japanese Old Sea Map card
    showed that Japanese text fields are 18 bytes, against 40 in English. A real Japanese news
    item will settle it.
- **File checks.** Files can be the bare news, or the save's form with the CRC-16 in front. The
  CRC is checked, and news ID 0 is reported, since the game treats it as no news.
- **The lab build** leaves Wonder News out, to stay inside the memory limit.

**Needs:** a real Wonder News file for the game and language, and one hardware run.

## Stage 3: Mystery Event for Ruby and Sapphire (the e-Reader route; done on hardware: the Eon Ticket, session 26)

Done in the simulator:
- `firmware/programs/ereader.c` (4 KB) plays the e-Reader in either cable role.
- `tests/link_game_model.py` is a Ruby written from the behaviour in docs/EREADER.md.
- The simulator models the four-player link mode (`attach_mp_game`).
- Three tests (game as master, game as slave, dry run) and seven planted bugs.

On hardware (sessions 24–25):
- With the game as master, link players were exchanged with 0 mismatches, and a 1,012-byte
  block went across.
- Ruby's menu needs the game to be master; the tool now says to swap the ends otherwise.
- The `.me3` file is the game's *saved* form: sent raw, the game stores nothing. The tool now
  wraps it in a Mystery Event script that makes the game store exactly its contents, checked
  with a model of Ruby's engine (`tests/mevent_model.py`).

On hardware (session 26): the wrapped Eon Ticket went across with 0 mismatches, Ruby saved it,
and Norman gave the ticket in Petalburg City Gym.

Still to come: Sapphire and other languages. (The Eon Ticket as a Record Mixing gift works on hardware too: Stage 12's table.)

- **The DUO plays the e-Reader** on the standard link (two-player mode at 115 kbit/s), as a
  separate GBA program.
- **How Ruby receives an event** (pret/pokeruby):
  - the link-player exchange, where the languages must match;
  - one block of up to about 2 KB, holding a Mystery Event script;
  - the game runs the script, then saves.
- **The simulator** gains a model of two-player link mode and Ruby's Mystery Event menu.
- **Needs** a GBA link cable (AGB-005), because two-player mode uses the SD line, which Game Boy
  and Game Boy Color cables don't carry.
- **First goal:** the English Eon Ticket, from carefully checked data.

## Stage 4: Enigma Berries (done on hardware: the PUMKIN BERRY, session 27)

- A `.ecb` is the saved `EnigmaBerry` record (1,328 bytes; docs/EREADER.md). The tool checks it
  (checksum with the pointers as 0, growth time, yield) and wraps it: `checkcompat`, `checksum`,
  `setenigmaberry`, `end`.
- The model of Ruby's engine (`tests/mevent_model.py`) now carries out `setenigmaberry` and the
  game's validity check. Two tests and three planted bugs.
- Checked locally with the six English e-Card berries: each stored exactly, in Ruby and Sapphire.
- **On hardware (session 27):** the PUMKIN BERRY went across with 0 mismatches, and Norman gave
  it. He won't give one while the bag or PC holds an e-Reader berry already.
- **Found on the way:** the "player 0" report can be wrong (session 27). To fix: decide the role
  from SIOCNT's player ID after each transfer, not from SI.

## Stage 5: Wonder Cards for every game (waiting)

Check all 68 `.wc3` files with the tool's own checks, then hardware runs on the cartridges to
hand. **Waiting:** the user's cable stays fitted for the e-Reader route for now.

## Stage 6: e-Card scans (simulator done, 31 October 2026; hardware next)

- `duo_events.py` reads `.raw` strips: blocks, interleaved Reed-Solomon codewords (parity
  checked), strip headers and titles, strips joined, vpk0 unpacked; then it finds the card's own
  Mystery Event script and sends it as the e-Reader did (docs/EREADER.md).
- All 186 Ruby/Sapphire cards in the gallery decode (berries, Battle-e trainers, the US Eon
  Ticket, the Japanese Decoration Present); the model accepts each in its own language, every
  trainer passes the game's checksum, and the berries and the Eon Ticket match the community's
  saved files byte for byte.
- The model now carries out `addtrainer` (the game's own check) and records `runscript`.
- Two tests (with made-up cards built by `tests/ecard_fixtures.py`) and five planted bugs.
- **On hardware:** send a trainer card, e.g. `08-A001 RS - Cool Trainer Devin (USA).raw`, then
  visit the old man's house in Mossdeep City.

## Stage 7: Japanese Ruby and Sapphire (simulator done, 31 October 2026)

- The Japanese language mask is **0x0001**, read from Nintendo's own Japanese cards. Japanese
  `.me3` and `.ecb` files are wrapped with it; Japanese cards go as they are.
- The tool warns at link-up when the event's language isn't the game's.
- The guided start-up gives the Japanese menu (ふしぎな できごと). The Japanese unlock phrase is
  still unconfirmed.
- **Needs** a Japanese Ruby or Sapphire for a hardware run.

## Stage 8: The other e-Reader protocols (Japanese; part 1 done in the simulator, 1 November 2026)

1. **Emerald's Trainer Hill e-Cards: simulator done.** Not a new protocol after all: the e-Reader
   screen gives a partner 10 frames, and one that answers in time is treated as an e-Reader
   already running Emerald's program, so the Mystery Event link carries the Trainer Hill set.
   All 66 cards decode (docs/EREADER.md). Hardware next, with the user's Japanese Emerald.
2. **FireRed/LeafGreen's Trainer Tower e-Cards: simulator done** (link type 0x5502, the same
   screen; one floor per card; all 37 decode). Japanese cartridges only.

## Stage 9: Pokémon (`.pk3`; step 1 done, 31 October 2026)

1. **Done: how each event was given out** (docs/PK3_EVENTS.md). `duo_events.py pk3-info` reads
   both PKHeX's decrypted form and the game's own. Of 3,344 files: 435 by trade (the Mystery
   Mew), about 2,700 by routes that wrote the save (multiboot cartridges such as Aura Mew, event
   machines such as PCNY's, GameCube discs), 167 never distributed, 17 unknown.
2. **Decided (31 October): the trade route for all.** Authentic for the Mystery Mew; for the
   rest, labelled as the nearest route that leaves the game in charge. Never-distributed
   Pokémon are offered the same way, marked as such. No multiboot save writer.
3. **The trade distributor: working on hardware with English Ruby (lab session 29)**, both cable
   roles in the simulator (docs/TRADE.md). `duo_events.py trade --pk3 FILE`. Leaving the room
   fixed afterwards in the simulator.
4. **Emerald and FireRed/LeafGreen: working on hardware (lab session 31).** The same protocol;
   the DUO sends the progress flags they check, and the tool warns before a trade they'd refuse.
   A Jirachi into Japanese Emerald, the Aura Mew into English LeafGreen, and two of four in one
   LeafGreen sitting. The walk out when the player stands in the way was fixed afterwards, and since
   8 November the walk waits a moment for a player in its way, then goes round, and never gives up.

## Stage 10: Secret Bases by Record Mixing (working on hardware with English Ruby, 6-7 November 2026)

Not part of the original goal; asked for on 3 November. The DUO sits in the Record Corner as the
other player and hands the game up to twenty Secret Bases (`.sb3`, docs/SB3_FORMAT.md, made from
base cards or read from save backups); the game files them and saves itself, and its own bases come
back to the PC. `python duo_events.py mix --base FILE.sb3 ...`. Details: docs/RECORD_MIXING.md.

- Step 1 (research) and step 2 (`secret_bases.py`, `mix.c`, the Record Corner model, six tests)
  done.
- Step 3: hardware. The black screen of lab session 31 (the fade-in's "ready" barrier) was fixed;
  on 6-7 November English Ruby mixed bases, an old man, a trend, TV shows and news, and a whole
  record made in the Record Workshop, and the game's own record came back. The user considers Secret
  Bases and Record Mixing done for now. Emerald (its own layout) is next when wanted.
- 7 November (hardware): the DUO paced along the left wall when the player stood in its way. The
  cause was the route planner reading leftover bytes beside the room; fixed on 8 November, with a
  walk that waits, then goes round, and never crosses another seat.

## Stage 11: Everything upstairs in the Pokémon Centre (asked for on 5 November 2026; to plan first)

The user would like the DUO to be a partner for every service on a Pokémon Centre's upper floor.
**A plan is to be agreed before any coding.** Where each service stands:

| Service | Games | Where we are |
|---|---|---|
| Trade Center | all five | Working on hardware (Stage 9) |
| Record Corner | Ruby, Sapphire, Emerald | Working on hardware with Ruby (6 November). Every part of a record, not only bases: formats docs/RECORD_FORMATS.md, plan docs/RECORD_WORKSHOP.md |
| **Colosseum: single and double battles** | all five | **A battle partner**: the probe's battle worked on hardware with English Ruby (7 November); since 8 November the PC chooses the DUO's moves (easy, medium, elite, impossible), singles and doubles, in the simulator; hardware next. Ruby and Sapphire so far |
| Colosseum: multi battle | all five | Needs four players: Stage 12, step C (cable) or W (wireless) |
| Union Room, wireless trade/battle/Record Mixing, Berry Crush and the rest | Emerald, FireRed/LeafGreen | Wireless Adapter only: all of them listed in Stage 12 |
| Mystery Gift | Emerald, FireRed/LeafGreen | Working (Stage 1) |

**The battle partner: the design is docs/BATTLE.md** (5 November): a set of `.pk3` files for its
team; easy, medium and elite levels (easy not stupidly easy; elite highly intelligent and
strategic). Its outline: In a Gen 3 link battle the master's GBA runs the battle and
sends the other GBA a stream of controller commands for its own Pokémon (show this, play that,
choose an action, choose a move); the other GBA answers each one. With the cable as fitted the
game is the master, so the DUO plays the follower: it answers every command, and for the choices it
asks the PC, which picks moves for a team given as files (`.pk3`s, a Secret Base's team, an
e-Reader trainer). Steps: read pokeruby/pokeemerald's link battle (setup, the controller commands,
the follower's controller); a hardware probe that only records what the game sends; a model; the
program; then the PC's choices.

## Stage 12: Every link and wireless feature, even the obscure ones (asked for on 7 November 2026)

The user would like the DUO to take part in **every** multiplayer feature of Ruby, Sapphire,
Emerald, FireRed and LeafGreen. This is the full list, with where each stands. Sources: pret's
pokeruby, pokeemerald and pokefirered (`cable_club.c`, `record_mixing.c`, `berry_blender.c`,
`contest_link.c`, `union_room*.c`, `berry_crush.c`, `pokemon_jump.c`, `dodrio_berry_picking.c`,
`battle_tower.c`, `mystery_gift*.c`, `link_rfu*.c`); Bulbapedia's multiplayer and Wireless
Adapter pages for the player counts.

**Two ways in.** *The cable as fitted* is a two-player Game Link Cable: with the serial port
working normally the DUO's GBA is one player. To fill the extra places of a four-player feature
on the cable it would have to drive the data line by hand and play three GBAs at once (step C
below: possible in principle, untried). *The Wireless Adapter* (Emerald, FireRed, LeafGreen only) goes through the
adapter the DUO already plays for Mystery Gift (docs/WIRELESS.md): there, every other player's
traffic comes through the adapter, so in principle the DUO can be **several players at once**
(up to the four others a wireless group allows). That is the only route to the four-player
features. Each wireless feature first needs the adapter emulation to grow from Mystery Gift's
one exchange to a game's full wireless session (finding and joining a group, then the feature's
own link traffic): step W below.

| Feature | Games | Link | Players | The DUO's part | Where we are |
|---|---|---|---|---|---|
| **Trade Center** | all five | cable; wireless (E, FRLG) | 2 | trade partner: Pokémon in, Pokémon out | **Working on hardware** (Ruby, Japanese Emerald, LeafGreen); wireless after step W |
| **Record Corner** (Record Mixing) | R, S, E | cable; wireless (E with E only) | 2-4 | a whole record (docs/RECORD_FORMATS.md) | **Working on hardware with Ruby** (bases); the rest of the record in the simulator; **Emerald in Ruby's layout (the DUO a Ruby player) built 8 November, simulator**; Emerald's own layout later; 3-4 players only over wireless |
| **Colosseum: single and double battles** | all five | cable; wireless (E, FRLG) | 2 | the battle partner (docs/BATTLE.md) | The battle link worked on hardware (7 November); the PC choosing, singles and doubles, four levels (8 November): hardware next. Emerald and FRLG next |
| Colosseum: multi battle | all five | cable; wireless (E, FRLG) | 4 | three of the four trainers | Needs step C (cable) or step W (wireless), and doubles in the battle model |
| **Battle Tower link multi battle** | E | cable; wireless | 2 | the player's Tower partner (two Pokémon each) | After the battle partner: doubles, and the Tower's rules and teams |
| **Berry Blender** | R, S, E | cable; wireless (E) | 2-4 | a blending partner: presses on the beat (easy to perfect) | **Built 8 November (two players, the DUO as player 1): `duo_events.py blender`, docs/BLENDER.md; simulator, hardware next** |
| **Pokémon Contests (link)** | R, S, E | cable; wireless (E) | 2-4 (NPCs fill the rest) | a contest entrant: a Pokémon, its condition, its appeals | **Emerald E MODE built 8 November (`duo_events.py contest`, docs/CONTEST.md; simulator, hardware next). Ruby/Sapphire (and G MODE) need exactly four players: with the four-player experiment** |
| **Union Room** | E, FRLG | wireless | up to 5 | a player in the room: greetings, chat (Easy Chat words), trainer cards, invitations to trade and battle, the trade board | After step W |
| Union Room chat | E, FRLG | wireless | up to 5 | a chatting player (fixed or scripted lines, or the PC typing) | After step W |
| Trainer Card exchange | all five (in the Colosseum and Trade Center; Union Room) | cable; wireless | 2 | a realistic card | **Working** (the trade's card, 6 November) |
| **Berry Crush** | E, FRLG | wireless | 2-5 | a crusher: presses with good timing | After step W: `berry_crush.c` |
| **Pokémon Jump** | E, FRLG | wireless | 2-5 | a jumper | After step W: `pokemon_jump.c` |
| **Dodrio Berry Picking** | E, FRLG | wireless | 2-5 | a picker | After step W: `dodrio_berry_picking.c` |
| **Mystery Gift: a distribution** | E, FRLG | wireless | 1 + the distributor | the distributor | **Working on hardware** (Stage 1; Wonder News in the simulator, Stage 2) |
| Mystery Gift: "Send" and "Receive" with a friend | E, FRLG | wireless | 2 | the friend: takes a game's Wonder Card or News (so the PC can keep it), or gives one | Not started: `mystery_gift_menu.c`'s Send/Receive and the Union Room's Wonder Card/News activities; small once step W is done |
| Mystery Event (e-Reader) | R, S | cable (the e-Reader's) | 1 | the e-Reader | **Working on hardware** (Eon Ticket, berries, Battle e-Card trainers: Stages 3, 4, 6) |
| e-Reader Trainer Hill / Trainer Tower cards | Japanese E; Japanese FRLG | cable | 1 | the e-Reader | Simulator done (Stage 8); hardware next |
| Eon Ticket by Record Mixing (the gift item) | R, S, E | cable | 2 | player 0's gift | **Working on hardware** (Ruby) |
| Ruby/Sapphire with FireRed/LeafGreen | R, S, E with FRLG | cable; wireless (E-FRLG) | 2 | trade and battle across the regions (FRLG need the National Pokédex for trades with Hoenn) | Trades working; battles with the battle partner |

**Obscure, and why they're harder or out of reach:**

| Feature | Games | Why |
|---|---|---|
| Four-player cable features (multi battle, 3-4 player Record Mixing, Blender, Contests) on the cable | R, S, E, FRLG | In the GBA's multiplayer serial mode each GBA sends one word per exchange, so the way the DUO links today it is one player. But players 2 and 3 are only time slots on the cable's shared data line, which a two-player cable carries too: if the DUO drives that line itself (the serial port's general-purpose mode, bit by bit at the games' 115,200 baud, about 145 GBA cycles a bit), it could send three players' words in a row and be three GBAs. Possible in principle: **the lab program is built (8 November, `duo_events.py lab4p`, docs/MULTI.md), simulator only; a hardware run next** (step C below). |
| GameCube connections: Pokémon Colosseum and XD (trading, the Jirachi bonus disc), Pokémon Box Ruby & Sapphire, Pokémon Channel (Jirachi) | R, S, E, FRLG | The GameCube is the master of the JOY Bus; a GBA can only be the follower, so the DUO's GBA can't stand in for a GameCube. Out of reach (and out of scope: Stage 0's goal). |
| The Berry Glitch Fixing Program | R, S | Sent by the e-Reader or a cable as a program that rewrites the save's clock: it writes the save directly, which our rule forbids. Refused, unless the user decides otherwise. |
| Wireless Record Mixing between Emerald and Ruby/Sapphire | E with R/S | The games don't do it (Ruby and Sapphire have no wireless); cable only. |

**Order of work** (each step through the simulator, with planted bugs, before hardware):

1. Done: Record Mixing's whole record on hardware with Ruby (7 November). Emerald's own layout
   and parts (the DUO saying "Emerald") when the user wants them.
2. The battle partner on the DUO: singles and doubles chosen by the PC (8 November, simulator);
   Emerald and FireRed/LeafGreen's Colosseums and elite in doubles followed the same day; hardware
   next; then the multi battles (docs/MULTI.md: the Battle Tower's link multi battle first).
3. The Berry Blender and link Contests (cable, Ruby/Sapphire/Emerald): one model each, from pret.
4. **Step W, the wireless session**: the adapter emulation from Mystery Gift grown into a full
   wireless group (pret's `link_rfu*.c`, then a hardware probe that only records), first as one
   player (wireless Trade Center and Colosseum), then as several.
5. **Step C, three players on the cable** (for Ruby and Sapphire especially, which have no
   wireless): a probe that drives the data line by hand and answers in players 2 and 3's slots
   while the game is only looking for players; then the link stages of the four-player features.
6. On top of step W: the Union Room (cards, chat, invitations), Mystery Gift with a friend, the
   wireless minigames (Berry Crush, Pokémon Jump, Dodrio Berry Picking), and the four-player
   features (multi battle, 3-4 player Record Mixing, Blender and Contests) over wireless.

## Tidying done on 30 October

- **One events tool**, `duo_events.py`, with `gift`, `news` and `event` commands.
  `duo_wireless.py` is a stub that translates the old options.
- **A guided start-up.** Both GBAs off; the DUO's on; progress bars; "Ready", then the game, with
  each game's menu and unlock phrase.
- **It finishes by itself** when the game has the gift.
- **It warns** when a card's file name names another game.
- **Missing Datel builds** skip tests rather than failing them.

## Throughout

- The DUO never writes to cartridges. Back up before any gift.
- No Nintendo files (ROMs, `.wc3` files, distribution software) or personal data in the
  repository.
