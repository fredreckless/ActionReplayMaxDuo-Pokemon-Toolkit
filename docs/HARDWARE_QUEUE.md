# What's waiting for real hardware

Everything the simulator has passed but a real GBA hasn't seen yet, in one list (8 November 2026).
It's ordered around the GBA link cable staying fitted (it's tight to remove), so the wireless tests
come last. Each run writes `logs\latest.log`; battles also keep `battles\*.txt`, Record Mixing
`records\*.rm3`. Keep the DUO's GBA switched on until the tool says it's safe to switch off.

When a test has been done, move it to "Done" with the date and what was seen (or ask Claude to).

## With the link cable as fitted

| # | Test | Command | What to look for |
|---|---|---|---|
| 1 | **A single battle, medium** (Ruby with 2-3 Pokemon; the DUO with 1-2) | `python duo_events.py colosseum --pk3 A.pk3 B.pk3` | The DUO uses sensible moves; the battle reaches its end; the tool says "safe to switch off" and keeps `battles\*.txt`. In the record: the game's own answers (state 1 for battler 0) and a `SETMONDATA` after each hit |
| 2 | **A single battle, impossible** | `... --level impossible` | A short pause after you choose each turn (it waits for your choice), then a strong answer; never anything the game wouldn't allow |
| 3 | **A double battle** (Ruby with 3-4 Pokemon; the DUO with 3-4) | `... --level medium`, choose DOUBLE BATTLE | Both of the DUO's Pokemon act; each aims at a foe it can hurt; a fit replacement after a faint |
| 3a | **A battle with Emerald, then LeafGreen** | as 1 | The same as with Ruby. To Emerald the DUO is a Ruby player (its card and sprite); LeafGreen sees a LeafGreen player |
| 3b | **Emerald's Battle Tower link multi battle** (the Battle Frontier open; the game's GBA on the cable's master end) | `python duo_events.py tower --pk3 A.pk3 B.pk3` | The link-up at the counter, the trainers, the battles with the DUO as your partner, "carry on?" between them |
| 3c | **The Berry Blender** (Ruby or Emerald, Lilycove; the game's GBA on the master end; a berry and a Pokéblock Case) | `python duo_events.py blender --blends 2` | The DUO's arrow presses as it passes the top (mostly the best spot); the blend ends; "another berry?" once more, then the link closes. The tool's Pokéblock matches the one in your case |
| 3d | **Emerald's link Contest, E MODE** (Lilycove's Contest Lobby, the link counter; the game's GBA on the master end) | `python duo_events.py contest --pk3 X.pk3 --category cool` | The DUO's Pokémon appears with its name and trainer; it appeals each round with a different move; the results match what the tool says |
| 3e | **Record Mixing with Emerald** (the DUO a Ruby player) | `python duo_events.py mix --base X.sb3` | The 24 rounds go across, Emerald saves; the base appears on its route (with Secret Power) |
| 4 | **Record Mixing, standing in the DUO's way** on purpose on its way to the table | `python duo_events.py mix --base X.sb3` | The DUO waits a moment, then goes round the other side of the table to its seat: no pacing along a wall |
| 5 | **A trade, standing in the way out** | `python duo_events.py trade --pk3 X.pk3` | The DUO goes round you to the door, and the received Pokemon is kept straight after the trade |
| 6 | Record Mixing's results in the game | (after a mix with a trend and news) | Ask about the trend in Dewford; the news on the TV (Slateport's sale). The TV show and the Bard's song were seen on 7 November |
| 7 | The Record Workshop's **Put it in the record** | the workshop, then `mix --record FILE.rm3` | A base designed and put straight into the record arrives in the game |
| 8 | The trade's **trainer card** in Ruby, Emerald and LeafGreen | a trade; look at the partner's card | The event trainer's name, ID and gender; a realistic card |
| 9 | **`duo_rom.py`** with the Ruby cartridge, then the workshop | `python duo_rom.py` | The file loads in the workshop ("Use my ROM's graphics…") and draws the rooms and words |
| 10 | Japanese Emerald's **Trainer Hill** after its e-Card (session 30) | — | Visit the Trainer Hill: the card's trainers are there |
| 11 | Japanese FireRed/LeafGreen's **Trainer Tower** e-Cards (needs a Japanese cartridge) | `python duo_events.py event --event "...Trainer Tower....raw"` | The floor is there in the Trainer Tower |
| 12 | Sapphire, and other languages of Ruby/Sapphire, for the e-Reader route | `python duo_events.py event --event ...` | As English Ruby (sessions 24-30) |

## The four-player experiment (the DUO's GBA on the cable's master end, the purple plug)

| # | Test | Command | What to look for |
|---|---|---|---|
| 12a | **The control**: the bit-by-bit link as one player (Ruby, the Trade Center) | `python duo_events.py lab4p --players 1` | The game links and the trade screen comes as usual (cancel it). The tool shows the game's words (0xb9a1 first) and no missing stop bits |
| 12b | **Three players** (Ruby, the Trade Center) | `python duo_events.py lab4p --players 3` | The game says the number of participants is wrong (it counted four), and the tool says the game's checksums took in four slots. If the trade carries on as usual instead, try `--gap 2`, then `--gap 1` |

## With the Wireless Adapter (once the cable comes out)

| # | Test | Command | What to look for |
|---|---|---|---|
| 13 | Mystery Gift through the guided start-up | `python duo_events.py gift --card X.wc3` | Received first time; the start-up's order is right |
| 14 | English and European Emerald, FireRed, LeafGreen in other languages | `gift --card ...` (and `--sweep-serial` if a game never finds the distributor) | The serial table gains a line per game |
| 15 | Wonder News (needs a real news file) | `python duo_events.py news --news X` | "News received"; the delivery man's berries |

## Done

- 7 November: the first link battle (the probe, a single battle against English Ruby, to the end and
  out of the room); Record Mixing with a whole record (Arthur's Blue Cave); TV and the Bard's song.
- 6 November: Record Mixing with English Ruby (both bases rounds; the DUO walked round a blocking player).
- Sessions 16-31 (lab notes, `lab/sessions/`): Mystery Gift (Japanese Emerald, English LeafGreen),
  the e-Reader route (Eon Ticket, berries, Devin), trades into Ruby, Emerald and LeafGreen.
