# A battle partner in the Colosseum (design, 5 November 2026; the probe, 7 November)

Asked for on 5 November as part of using every service upstairs in the Pokémon Centre (ROADMAP
Stage 11). The user's choices: the DUO's team is **a set of `.pk3` files**; it plays at **three
levels** - easy, medium and an elite one that is highly intelligent and strategic - and **easy must
not be stupidly easy**. Nothing is built yet: this is the plan, read from pret/pokeemerald and
pret/pokeruby (`battle_main.c`, `battle_controllers.c`, `battle_controller_player.c`,
`battle_controller_link_opponent.c`).

## How a Gen 3 link battle works

- **Starting.** At the Colosseum attendant the player chooses single or double (link types 0x2233
  and 0x2244; multi, 0x2255, needs four players: ROADMAP step C). Both singles and doubles use the
  same room, SingleBattleColosseum; the attendant heals the party first. Both walk in and stand on a
  spot by the table, the same room walk as the Trade Center's (now `room_walk.h`); when both are
  seated, the game closes that link and the battle opens its own (0x2211).
- **Who runs the battle.** Each GBA sends a small header (`linkBattlerHeader`) whose version
  signature is 0x0101 from Ruby/Sapphire and 0x0300 from Emerald. `FindLinkBattleMaster`: when every
  player sends the same signature, **player 0 is the battle master**; otherwise the highest wins
  and, failing that, the game that sees no higher one takes it. So the DUO can always leave the
  battle to the game: as player 1 it sends the game's own signature, and as player 0 it sends
  0x0001, lower than any game's (pokeruby `CB2_HandleStartBattle` case 1; pokeemerald's
  `FindLinkBattleMaster` reads the same way). The cable can go either way round. The game then runs
  the battle: its engine, its random numbers, every calculation. The DUO only ever plays the other
  side's controller.
- **The parties.** Then each side sends its party, two Pokémon (2 x 100 bytes) at a time, three
  times; Emerald with Emerald also swaps a random seed for recorded battles.
- **During the battle.** The master's engine emits a controller command for a battler (show the
  Pokémon, play an animation, print a line, *choose an action*, *choose a move*, *choose a
  Pokémon to switch in*, get or set a Pokémon's data, and so on: about 60 kinds). In a link battle
  every command goes over the link as a block: a header (buffer id, active battler, attacker,
  target, size, absent battlers, effect battler) and the command's bytes. The GBA whose battler it
  is runs it and answers to the engine (`B_COMM_TO_ENGINE`: the chosen action, move and target, a
  Pokémon's data); **every** player then reports that it has finished that command
  (`B_COMM_CONTROLLER_IS_DONE`), and the engine waits for all of them before going on.

## What the game sends, in detail (read 7 November)

From pokeruby (`cable_club.c`, `battle_main.c`, `battle_controllers.c`,
`battle_controller_player.c`, `battle_controller_link_opponent.c`, `link.c`); Emerald's are the
same in shape.

- **The room.** `sub_808347C` sets 0x2233 or 0x2244 and opens the Cable Club's link (link players,
  trainer cards on 0xCCCC 2, as the Record Corner). The Colosseum is 14 x 9: open floor from (1,3)
  to (12,7), the attendant at (9,3), the spots at (3,5) (`VAR_0x8005` = 0) and (10,5) (= 1), the
  door at (6,8)-(7,8), and the players appear at (6,8) and (7,8). Either player may take either
  spot. Seated is key 22, as in the other rooms. `sub_808382C` then sets 0x2211, stops the room
  keys, fades, waits 20 frames and closes the link (0x5FFF).
- **The battle's link.** `HandleLinkBattleSetup` opens it; link players must arrive within 300
  frames (`sub_8083C50`), or "link error". Each GBA's link player now carries its spot as `id`.
  `CB2_HandleStartBattle`: the header (31 bytes in Ruby: signature, two bits a Pokemon for the
  versus screen - 1 fit, 2 asleep or an Egg, 3 fainted - and the Enigma Berry), then the party in
  three blocks of 200 bytes (two Pokemon each, the game's own encrypted form). Each block goes once
  `IsLinkTaskFinished`, and the next only when both players' blocks of this turn are in; the
  receiver's flags are reset each turn, so a partner must not send ahead.
- **Who is who.** Battlers: the master's are 0 (and 2 in a double), the follower's 1 (and 3)
  (`InitLinkBtlControllers`).
- **Commands.** The engine's `BtlController_Emit*` goes, in a link battle, to
  `PrepareBufferDataTransferLink`: a block of an 8-byte header (state 0, the battler, attacker,
  target, size, absent battlers, effect battler) and the command, its size rounded up past a
  multiple of four (4 bytes -> 8). `Task_HandleSendLinkBuffersData` sends them one block at a time
  to everyone (after a 100-frame wait at the start). Every GBA, the sender too, copies each into
  its `linkRecv` ring (`sub_800C35C`, every frame) and runs it in order
  (`Task_HandleCopyReceivedLinkBuffersData`): state 0 is a command for that battler's controller
  (it waits while the last one for that battler is still running there), state 1 an answer into
  `gBattleBufferB`, state 2 a "done" that clears that player's bit for that battler. The engine
  waits for every player's bit (`sub_80155A4` sets one per player per command). So every GBA
  answers every command with its own done (state 2, data: its multiplayer ID), and the one whose
  battler it is answers first where the command asks for something.
- **What asks for something.** `CHOOSEACTION` (18; answer `TWORETURNVALUES` 33: 0 fight, 1 bag,
  2 switch, 3 run), `CHOOSEMOVE` (20; its data: the four moves, PP, max PP, species and types;
  answer 33, 10, the slot, the target battler), `CHOOSEPOKEMON` (22; answer
  `CHOSENMONRETURNVALUE` 34, the party slot, and three bytes of party order that only a multi
  battle reads). `GETMONDATA` (0) asks too, but the master's own copy of the partner's party
  answers it (`LinkOpponentHandleGetAttributes`), so the partner needn't; a partner that does
  answer must send exactly the game's view of its Pokemon, or the battle would use its bytes.
  The engine never sends `GETRAWMONDATA` in a battle.
- **The end.** `ENDLINKBATTLE` (55, with the outcome) to every battler; each GBA fades and closes the
  link (0x5FFF). The game goes back to the Colosseum (`sub_8083958`, then `sub_805465C`: everyone
  standing on their spot, facing down) and opens the room's link again; `sub_800826C` makes sure
  the partner is the same trainer (ID and name) as before, or "link error". Then out of the door,
  as after a trade.

## The probe (`colosseum.c`, 7 November): step 2

`python duo_events.py colosseum --pk3 A.pk3 [B.pk3 ...]` (1 to 6 Pokemon). The DUO walks to a spot
(player 0 left, player 1 right, or the other one if the player is on its own), battles once and
walks out. It plays as simply as it can: fight, the first move that has PP, the foe opposite, and
after a faint the next Pokemon that can battle. Every block the game sends - link players, cards,
headers, parties, every command and its answers - and every block the DUO sends goes into a log in
the firmware's save-transfer buffer (up to 126 KB), and afterwards the PC keeps it in `battles\`
as `... colosseum.bin` and a readable `... colosseum.txt` (each block named and decoded). The run
log has the rest.

Tested in the simulator against a model of the game (`tests/battle_game_model.py`): either end of
the cable, the player on the DUO's usual spot, a double battle, the DUO winning and losing, the
player leaving first; and planted bugs (a wrong signature, a done with the wrong ID, answering for
the game's battlers, a Pokemon already on the field sent in, and others) are caught. The model is
this session's reading of the code, so hardware has the last word: the probe exists to check it.

**On hardware (next session):** Ruby with two or three Pokemon of its own, the DUO with one or two
`.pk3` files (a short battle), single battle first. Afterwards send the `battles\` folder's newest
`.txt` and `logs\latest.log`. What to look for: the battle starting at all (the header and the
party blocks), the DUO's Pokemon on the game's screen with the right name, level and HP, the
battle reaching its end, and the walk out. If the game stops, note what its screen shows.

## What the DUO's program does (`battle.c`, to write)

- The Cable Club and the room as now (`trade.c`/`mix.c`'s engine and `room_walk.h`), then the battle
  link: the header (the game's signature), the party blocks (the DUO's team in the game's form,
  as the trade sends it).
- For each command block: if it's for one of the DUO's battlers, act on it - most commands only
  need "done"; `GETMONDATA` is answered from the DUO's copy of its party (the game's own encrypted
  form, as in `CopyPlayerMonData`), `SETMONDATA` updates that copy (HP, status, PP); the choices
  (`CHOOSEACTION`, `CHOOSEMOVE`, `CHOOSEPOKEMON`, and doubles' targets) are asked of the PC. For
  every block, the DUO reports "done" for itself, paced like a GBA that has just played the
  animation, so the game never waits on it and never runs ahead.
- It passes the PC everything the battle reveals as it goes: the game's Pokémon as they come out,
  moves used, damage, misses, critical hits, status, weather, items and abilities shown.
- Size: the program area has about 11.7 KB, and the link battle buffers are 4 KB each way in the
  game. The command handling is a table; the DUO keeps only its own six Pokémon and a short
  receive buffer, and the PC does the thinking.

## How the PC plays (`duo_events.py battle --pk3 ... --level easy|medium|elite`)

The PC keeps its own model of the battle from what the commands reveal, and chooses with a full
Gen 3 damage calculator (base stats, natures, IVs and EVs of its own Pokémon; the game's as far as
they're shown; types, STAB, weather, abilities, held items, stat stages, critical hits, the 85-100%
damage roll, accuracy and evasion, priority and speed order).

- **Easy** plays like a sensible young trainer: it knows type match-ups and never uses a move that
  can't work (an immune target, a status move on a Pokémon that already has one, a second Sunny
  Day); it mostly picks a strong, effective move, sometimes a status or set-up move; it switches
  only when its Pokémon faints. It doesn't look ahead or predict.
- **Medium** plays like a good player: it works out each move's expected damage and the chance of a
  knock-out, finishes off weakened Pokémon, uses set-up moves and status when it's safe to, keeps
  priority moves for the right moment, and switches out of a clearly bad match-up when a better
  Pokémon waits on the bench.
- **Elite** plays to win: for each choice it has, it plays the battle on to the end in several
  imagined copies (the other side answering as a good player would, then both sides playing on as
  good players), with the same damage rolls, accuracy checks and critical hits for every choice so
  they're compared fairly, and each copy with its own guess at what it can't see (moves, items,
  IVs, EVs, nature, ability). It takes the choice that ends best on average - but leaves the good
  player's choice only when the playouts clearly say so, as they're only as right as its guesses.
  (A two-turn expectimax was tried first and played worse than medium: its evaluation of positions
  was too rough. Playing on to the end - rollout improvement - is what made the difference.)

**Fair play.** The game sends its whole party at the start, so the PC *could* know every move and
item the player has. By default every level uses only what a human opponent would see (species,
level, HP bar, status, moves and items as they're revealed), with each species' likely sets as a
prior for the elite level. Whether the elite level may "see everything" is for the user to decide.

## Testing

- A model of the master's side in `tests/` (like the trade and Record Corner models): the battle
  link's start, the party blocks, and a battle engine that emits the commands a real one does for a
  scripted battle - enough to drive the DUO's program through singles and doubles, a switch, a
  faint, a win and a loss.
- The AI tested on its own: damage numbers against known Gen 3 results, and each level against
  fixed positions (it must find a knock-out, must not use a move that can't work, and so on), and
  the levels against each other in simulated battles (elite should beat medium, medium easy).
- Then hardware: a first run that only records what the game sends, then a battle.

## Progress (6 November 2026)

Step 4 is done on the PC: `duo_battle.py`, with `battle_data.py` made from pret's sources by
`tools/make_battle_data.py` (base stats, types, abilities, every move's numbers and flags, the type
chart, held items). Singles only so far. The damage follows pokeemerald's `CalculateBaseDamage` and
the battle script commands step by step, rounding where the game rounds; the move effects,
abilities and items that change battles most are modelled, the rarest do nothing (that only
affects choosing - in a real link battle the game runs the battle itself).

    python duo_battle.py --demo                          a battle between two made-up teams
    python duo_battle.py --pk3 my/*.pk3 --level elite    your .pk3 files as the elite level's team
    python duo_battle.py --tournament 40 --level medium --opponent easy

Strength, playing both ways round on the same made-up teams (fully evolved, trained, level 50,
three each), all levels using only what they could see:

| match | wins |
|---|---|
| easy against random choices | 92% (100 battles) |
| medium against easy | 72% (200) |
| elite against medium | 56-57% (160 each, two settings) |
| elite against medium, elite seeing everything | 59-62% |

Gen 3 battles are very random, so these are clear but not crushing margins; easy is a real
opponent (it isn't "stupidly easy"). An elite choice takes well under a second.

Tests (`tests/test_v4.py`, "battle:"): damage worked by hand against the game's steps; a .pk3's
stats against duo_events' party fields; 150 battles with every species, move and item; fixed
positions (no level uses a move that can't work; medium and elite always take a sure knock-out);
and the levels in order of strength.

Next: what a human sees of the other side's party in a link battle (now each level knows the
other side's species from the start), doubles, and the DUO side (steps 1-3).

## Steps

1. Read the battle code fully: the link start (`CB2_HandleStartBattle` in both games), the
   controller commands and their data, `CopyPlayerMonData`/`SetPlayerMonData`, the end of the
   battle and the way back to the room. **Done for Ruby (7 November).**
2. A hardware probe: the DUO sits in the Colosseum and records everything. **Built and tested in
   the simulator (7 November): `colosseum.c`; hardware next.**
3. The master model and the DUO's program, with the Colosseum walk.
4. The PC's battle model and damage calculator, then easy, medium and elite.
5. Hardware: singles, then doubles, with English Ruby, Japanese Emerald and LeafGreen.
