# A battle partner in the Colosseum (design, 5 November 2026)

Asked for on 5 November as part of using every service upstairs in the Pokémon Centre (ROADMAP
Stage 11). The user's choices: the DUO's team is **a set of `.pk3` files**; it plays at **three
levels** - easy, medium and an elite one that is highly intelligent and strategic - and **easy must
not be stupidly easy**. Nothing is built yet: this is the plan, read from pret/pokeemerald and
pret/pokeruby (`battle_main.c`, `battle_controllers.c`, `battle_controller_player.c`,
`battle_controller_link_opponent.c`).

## How a Gen 3 link battle works

- **Starting.** At the Colosseum attendant the player chooses single or double (link types 0x2233
  and 0x2244; multi, 0x2255, needs four players and is out of reach for one DUO on a two-player
  cable). Both walk into the Colosseum and sit down, the same room walk as the Trade Center's
  (now `room_walk.h`), then the battle's own link opens.
- **Who runs the battle.** Each GBA sends a small header (`linkBattlerHeader`) whose version
  signature is 0x0101 from Ruby/Sapphire and 0x0300 from Emerald. `FindLinkBattleMaster`: when every
  player sends the same signature, **player 0 is the battle master**. So the DUO sends the game's
  own signature back, and with the cable as fitted (the game on the master end, player 0) **the
  game runs the battle**: its battle engine, its random numbers, every calculation. The DUO only
  ever plays the other side's controller. If the DUO comes up as player 0, the tool says to swap the
  cable's ends, as the e-Reader route already does.
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
   battle and the way back to the room.
2. A hardware probe: the DUO sits in the Colosseum and only records the first blocks.
3. The master model and the DUO's program, with the Colosseum walk.
4. The PC's battle model and damage calculator, then easy, medium and elite.
5. Hardware: singles, then doubles, with English Ruby, Japanese Emerald and LeafGreen.
