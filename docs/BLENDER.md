# The Berry Blender partner (8 November 2026)

The DUO blends berries with you at a link Berry Blender in Ruby, Sapphire or Emerald: it puts in a
berry of its own, presses A as its arrow passes, answers "blend another berry?", and the PC tells
you which Pokéblock you made. Nothing is written to either cartridge; the game saves its own
Pokéblock as usual.

```
python duo_events.py blender
python duo_events.py blender --berry Oran Sitrus --skill expert --blends 3
```

Use one of the link Berry Blenders in Lilycove City (Emerald: the Contest Lobby), with a Pokéblock
Case. The cable can go either way round (11 November): whichever GBA is on the master end leads.
When the DUO leads it asks for the trainer cards and, after each blend's barrier, the berries;
sends the leader's block (the time and best RPM, by its own count); and gives the verdict on
"another berry?" from both answers (naming the first player, in order, who said no). As master the
DUO sets the link's pace while the game keeps its own frames, so its copy of the arrow can be a
frame or two out; the game takes the DUO's time and RPM, and the tool's Pokéblock then matches it
exactly.

- `--berry`: the DUO's berries in order of choice, up to four. It waits for yours, then puts in the
  first that isn't the same (the same berry twice makes a black Pokéblock). The default is Oran,
  then Sitrus: each has ten of every flavour, and the game takes each flavour from the one before
  it, so they leave your Pokéblock's flavours as they are and only add the RPM's boost. Bring a
  flavoured berry (Pecha, Watmel...) to change the Pokéblock on purpose.
- `--skill`: `expert` (the best spot every pass; once the arrow outruns it, the good spot, as for
  any player), `good` (one good press in four) or `casual` (best, good, a miss, in turn).
- `--blends N`: how many blends it stays for (1-9). After the last it answers no, and the game
  closes the link.

## How it works

From pret's pokeemerald (`berry_blender.c`, `cable_club.c`, `link.c`, `data/scripts/berry_blender.inc`)
and pokeruby's `berry_blender.c`, whose protocol is the same. The program is
`firmware/programs/blender.c`.

1. **The link-up** (`LINKTYPE_BERRY_BLENDER_SETUP` 0x4411, `TryBerryBlenderLinkup`): the link
   players (the DUO copies the game's version and link type) and the trainer cards (the DUO's card:
   its name, a Pokédex, a new save's money and profile). The link stays open while you choose a
   berry.
2. **The berries** (`CB2_StartBlenderLink`): a "ready" barrier, then the leader's block request
   (0xCCCC 4) and a 40-byte block from each: `struct BlenderBerry` (the item, the name, five
   flavours and smoothness), as the games keep them. Then the berries go in, the countdown, and a
   second barrier.
3. **The play.** Every frame each GBA sends 0x4444, with word 2 a hit: BEST 0x4523, GOOD 0x5432,
   MISS 0x2345. There is no arrow on the cable: each GBA runs it itself from the hits that arrive
   (`UpdateBlenderCenter`, `HandlePlayerInput`, `UpdateOpponentScores`, `TryUpdateProgressBar`).
   The DUO runs the same arithmetic, frame by frame: the arrow starts at 0xC000 (two players) and
   moves by the speed each frame; the speed falls by one every six frames (to 128 at least); a
   best hit adds 384 (128 above 1500), a good one 256 (nothing above 1500), a miss takes 256 away;
   best and good hits fill the progress bar by the speed over 55 and over 70; the blend ends when
   the bar, which climbs two a frame, reaches 1000. The DUO's spot is the player-1 spot of a
   two-player blend (arrow 2, `sArrowHitRangeStart` 96): the good spot is 48 places wide, the best
   the 8 in its middle. Each hit the DUO sends is scored by its own copy of the arrow, as each GBA
   scores its own player's press.
4. **The end**: the game stops sending 0x4444 once the arrow has stopped; the leader sends a 40-byte
   block (the time in frames and the best RPM, in hundredths); each player answers "blend another
   berry?" (0x2FFF with 0x7779 for yes, 0x8888 for no); the leader sends its verdict (0x2FFF with
   0x2222, again, or 0x1111, stop); four "ready" barriers round the link save; then the next blend,
   or the link closed (0x5FFF).

The PC reads the program's record and works out the Pokéblock as the game does
(`CalculatePokeblock`): each flavour less the next, negatives counted and taken off, the best RPM's
boost (RPM / 333 + 100 per cent), the colour from the flavours left, and the feel from the
smoothness. The record is kept in the `battles` folder (`... blender.txt`).

Berry names are sent in capitals, as the games write them. A Japanese game shows them in its own
Latin capitals.

## Tested

In the simulator, against `tests/blender_game_model.py` (the game's side, written again from the
same sources): one blend (every hit the DUO claims checked against the game's own arrow over the
frames before it arrived, and the DUO's count of frames matching the game's), two blends, the
player bringing the DUO's first berry, a casual DUO with a player who misses, and the DUO leaving
while the player wants more; planted bugs for each. **Hardware next** (docs/HARDWARE_QUEUE.md).

Not yet: three or four players (the four-player cable experiment,
docs/MULTI.md), and Emerald's wireless blending.
