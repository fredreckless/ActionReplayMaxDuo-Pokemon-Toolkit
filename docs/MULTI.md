# Multi battles: a design (8 November 2026)

The last kinds of link battle: battles with four battlers on the field. They split by how many
GBAs the game expects on the cable, which decides how hard each is. Sources: pret's pokeemerald
(`battle_main.c`, `include/link.h`, `include/constants/battle.h`) and pokeruby.

## 1. Emerald's Battle Tower link multi battle: two GBAs (built 8 November, simulator)

**Built:** `firmware/programs/tower.c`, `python duo_events.py tower --pk3 A.pk3 B.pk3 [--level ...]
[--retire-after N]`, `duo_battle.TowerLink`, and `tests/tower_game_model.py`. What it does, from
pret's sources (cable_club.c, battle_tower.c, field_specials.c, start_menu.c, save.c, battle_main.c):

1. **The lobby** (0x2266 level 50 / 0x2277 open): link players (the DUO says Emerald, with the
   progress flags), the trainer cards (the DUO's two species at 0x54; the game refuses a partner with
   the same species, `AreBattleTowerLinkSpeciesSame`), the link save (`Task_LinkFullSave`: three
   "ready" barriers), the win streaks (4 bytes each) and the Tower trainers' list (40 bytes; the game
   keeps player 0's, so the DUO only echoes the game's), then closed.
2. **Each battle** (0x2288, `CB2_HandleStartMultiPartnerBattle`): link players, then seven blocks each
   way: the header (the game's own signature: player 0, the game, runs the battle), the party (two
   Pokemon, then a third, empty), three blocks of the Tower trainers' party (the follower's are
   ignored: zeros), the recorded battle's seed. Four battlers: the player 0, the DUO 2, the Tower's
   trainers 1 and 3 (the game's AI). The DUO answers battler 2's choices, the PC choosing (as in the
   Colosseum, aimed only at the Tower's trainers); its Pokemon are party slots 3 and 4.
3. **After a win that isn't the seventh** (`Task_LinkRetireStatusWithBattleTowerPartner`): the link
   again; the DUO, the follower, sends its choice first (carry on, or retire after the battle given by
   `--retire-after`), the game its verdict, a "ready" barrier, closed. A loss, the seventh win or a
   verdict to stop ends the challenge.

**The DUO as player 0 (11 November)**, its GBA on the master end. Player 0's copy of the trainers'
list and of their party is the one the battle uses; the DUO has no Tower data of its own, but the
game, as player 1, sends its own copies first, so the DUO sends them straight back and the game
battles the trainers it chose itself. The rest of player 0's jobs:
- the lobby: it asks for the trainer cards (0xCCCC 2), as a link-up's leader does;
- the header: signature 0x0001. `FindLinkBattleMaster` (two players on different versions): the
  lowest-numbered player on 0x0300 or above is master, so the game, player 1 on 0x0300, runs the
  battle (0x0100 would have made player 0 the master; 0x0300 too, as the same version);
- the battle: the link players' ids are fixed (`gLinkPlayers[0].id = 0`, `[1].id = 2`), so the DUO
  is battler 0 with party slots 0-2, and the player battler 2 with 3-5. The game's engine sends every
  command; the DUO answers battler 0's;
- after a win: the game, the member, sends its choice; the DUO, the leader, sends the verdict
  (`BOTH_RETIRE` 1, `MEMBER_RETIRE` 2 when only the player retires, `LEADER_RETIRE` 3 when only the
  DUO does, else `CONTINUE` 0), and the game says "your partner has retired" for 3.
The recorded battle's seed is the master's, the game's, so the DUO's zeros are never read.

Tested in the simulator: a three-battle challenge (with the carry-on exchanges), the DUO retiring
after the first battle, a lost battle, a link-up refused for the same species, one battle at the
impossible level; as player 0, a three-battle challenge (the model checking the DUO's header, its
trainers' list and Tower party, its card request and its battler) and the verdicts both ways;
planted bugs for each. Hardware next: Emerald with the Battle Frontier open.

### The design, as first written

**What it is.** In the Battle Tower's multi room, two Emerald players team up, each with two
Pokemon, against two of the Tower's trainers, over a normal two-player cable
(`LINKTYPE_BATTLE_TOWER_50` 0x2266, `_OPEN` 0x2277, then 0x2288). The battle is
`BATTLE_TYPE_TOWER_LINK_MULTI | BATTLE_TYPE_MULTI | BATTLE_TYPE_DOUBLE | BATTLE_TYPE_LINK`; its start
is `CB2_HandleStartMultiPartnerBattle`.

**What's different from the Colosseum.**
- The link players get fixed battle positions (`gLinkPlayers[0].id = 0`, `[1].id = 2`), and the
  two Tower trainers fill players 2 and 3 locally (names and languages from the Tower's data).
- The header has signature 0x0300 (Emerald), and both players must be Emerald: the DUO has to say
  Emerald here, not Ruby, so the recorded battle's seed step (Colosseum notes) comes back.
- The parties are exchanged as partners: two Pokemon, then the third, each copied into the
  player's party beside the partner's (`MULTI_PARTY_SIZE`).
- In the battle, the DUO is the player's **partner**, battler 2 (on the player's side), not an
  opponent. The game runs the battle and the Tower's trainers (its AI); every command still comes
  over the link. The DUO answers only for battler 2, and its target is one of the Tower's trainers'
  Pokemon (battlers 1 and 3). The PC's double-battle chooser serves with "foes" and "partner"
  swapped round.
- Before the battle: the lobby (choosing the partner, the level, the Pokemon), which has its own
  link exchanges in the Battle Tower's scripts and `frontier_util.c`/`battle_tower.c`. These need
  reading before anything is built.
- After it: the Tower's streak, and Emerald's recorded-battle offer.

**Steps.** Read the lobby and the start (`battle_tower.c`, `frontier_util.c`, the multi room's
scripts); a model of it in the simulator (`tests/battle_game_model.py` as a Tower variant); then a
`tower` program (or `colosseum.c` with a Tower mode, if space allows: about 650 bytes are free).
Hardware: Emerald with a Battle Tower open (after the Hall of Fame).

## 2. Four-player battles in the Colosseum: four GBAs on the cable

**What they are.** RS's `DoubleBattleColosseum` and E/FRLG's `BattleColosseum_4P` (the room with
the wider door), link type `LINKTYPE_MULTI_BATTLE` (0x2255): four players, two teams of two, each
with three Pokemon. The game expects **four units** on the link.

**The hard part is the cable itself.** In multiplayer mode the four units share one data line:
the master sends its word in slot 0, then each slave in turn sends in its own slot once the unit
before it has finished (SI/SO daisy-chain). One GBA's serial hardware only ever sends its own slot.
With the game and the DUO alone, slots 2 and 3 stay empty (0xFFFF), so the game would see two
players, not four.

**An idea to test, not a promise.** As player 0 the DUO drives the clock. During slots 2 and 3 it
could drive the data line itself, bit by bit in general-purpose mode (at 115,200 baud, about 146
CPU cycles a bit), so that the game hears three players besides itself. The firmware already times
the link closely in places (the Wireless Adapter work), but this would have to be exact to the
bit, and only real hardware can tell whether the game's GBA accepts it. The PC would then play
three link players: the user's partner and both opponents, each answering as a link partner does.

**Steps if it works.** A lab program that sends a known pattern in slots 2 and 3 while the game
sits in the Cable Club, and the game's own view of how many players there are (the Cable Club says
"Please wait" until four have joined). Only then the room (the 4P layout, four spots) and the
battle (four sets of answers, three parties).

### The lab program (built 8 November, simulator)

`firmware/programs/lab4p.c`, run with `python duo_events.py lab4p` (**the DUO's GBA on the cable's
master end**, the purple plug; the opposite of the Tower, Blender and Contest). The DUO leaves its
multi-player hardware alone and drives the port in general-purpose mode (RCNT), timed by timer 0
(145.64 CPU cycles a bit): SC low; its word on SD (a low start bit, 16 bits from the lowest, a
high stop bit); SO low to give the game its turn; the game's word read off SD at the middle of
each bit; then, as children 2 and 3, two more words a bit apart (`--gap`, in quarter bits); SC
high. Above the bits, link.c's link layer for four slots: the handshake (`DoHandshake` counts the
handshake words in a row), commands of eight words and a checksum over four slots, and, with
`--link trade`, link players: 0x2222 from slot 0 and a link player from each of the DUO's slots
("DUO", "DUO2", "DUO3"). `--players 1` is the control: the same bit-by-bit link as one player.

What to look for, in the Trade Center (two players only):
- `--players 1`: the trade goes on as usual (the game's link player arrives; its checksums match).
  That proves the bit-by-bit link itself.
- `--players 3`: a game that counted four players says the number of participants is wrong and
  closes the link; the tool also sees the game's checksums take in slots 2 and 3. A game that
  counted two carries on as usual: then the game's hardware didn't take slots 2 and 3 (try a
  shorter `--gap`; the record shows how soon the game's own start bit followed its turn).

Tested against `tests/gp_link_model.py`, a model of the game's serial hardware at the level of the
lines (it reads SD as a GBA's hardware would, and needs each unit's start bit within a window
after the previous stop bit) and of its link layer. The real hardware's window, how soon a child
answers, and whether the DUO's timing from EWRAM is steady enough are what the hardware run tells.

## 3. The Union Room (Emerald, FireRed/LeafGreen): wireless only

Battles and trades in the Union Room go through the Wireless Adapter's RFU protocol, not the
cable. The project already plays the adapter for Mystery Gift (`adapter.c`), but the Union Room
needs the adapter's full multi-player side. It's out of reach while the cable stays fitted, and is
noted here only so the list is complete.

## Order

1. The Battle Tower link multi battle (section 1): built (simulator), hardware next.
2. The four-player experiment (section 2): the lab program is built (`lab4p`, simulator); a short
   hardware run next, then the four-player features only if it works.
3. The Union Room (section 3): with the Wireless Adapter work, later.
