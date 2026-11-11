# The link Contest entrant (8 November 2026)

The DUO enters a Pokémon of its own (a `.pk3`) in Emerald's link Contest against yours. The game
works out the contest, as the leader of a link contest always does; the DUO's Pokémon makes its
appeals with its own moves. Nothing is written to either cartridge; the game saves its results
(and the painting, if you win) itself.

```
python duo_events.py contest --pk3 "mine\SKITTY.pk3" --category cute
python duo_events.py contest --pk3 "mine\MILOTIC.pk3" --category beauty --order 2 1 3 4
```

At Lilycove City's Contest Lobby, use the link contest counter, choose **E MODE**, the same
category you gave the DUO, and your Pokémon. The cable can go either way round (11 November); the
game always works out the contest:
- the game's GBA on the master end: the game is player 0 and picks the other two contestants;
- the DUO's GBA on the master end: the DUO is player 0, so it asks for the trainer cards and sends
  the random seed and the two other contestants (player 0's jobs: `--rivals A.pk3 B.pk3`, each with
  the game's full contest AI; without them, two more of its own Pokémon), and a leader ID of 0,
  below the game's 0x6E, so that the game still leads.

**The moves (11 November).** Unless `--order` is given, the PC plans the five rounds from pret's
contest move data (`contest_data.py`): each move's appeal, a combo after its starter (its appeal
again), half its jam, the crowd's excitement (+/-10 for a move in or against the contest's
category) and the judges' mark-down for the same move twice running. What the other contestants
will do can't be known beforehand, so the plan doesn't guess at it.

**Live moves (11 November).** During the contest the PC reads the appeals' state as it arrives in
the DUO's record (`contest_data.ContestWatch`) and, before each round from the second, sends the
DUO that round's move (poll 11; the DUO keeps to the plan for any round the PC hasn't answered in
time, and the tool says if it was too late). What it follows:
- the applause meter, as every GBA keeps it (`APPEALSTATE_UPDATE_CROWD`): each appeal's excitement,
  nothing while another's move has frozen the crowd, 1 for a move that overrides it, 0 for a liked
  move used twice running; at 5 it empties. A move the crowd likes adds 10 to its appeal, or 60 when
  it fills the meter (`excitementAppealBonus`);
- the next round's turn order (the last 4-byte block), and so how many appeal before the DUO: its
  jam only counts when someone does, and the meter at its turn is guessed by assuming each of those
  uses a move of the same category as last time (not the same move: that would excite no one);
- then the plan's rules for the rounds left, from the move it just used (combos, repeats).
So a weaker move in the contest's category can win the +60 that the plan, knowing nothing of the
crowd, would never have used.

- `--category`: the category you'll choose. The DUO then gives its ribbon rank in that category, as
  the game does for its own Pokémon (the leader picks the other two contestants from the highest
  rank, less one). Without it the DUO says it has no ribbons there.
- `--order`: the move slots in the order the DUO uses them, one a round (five rounds), in place of
  the PC's plan.
- The Pokémon is checked against the games' rules first, as for a battle (`--allow-unchecked` to
  enter one anyway). Its condition (cool, beauty, cute, smart, tough, sheen) comes from the `.pk3`,
  with a matching scarf's +20, as the game works it out.

## Ruby and Sapphire

Their link contests (and Emerald's G MODE, which mixes the games) need exactly four players
(`TryContestGModeLinkup`, pokeruby's `sub_808363C`: `CreateLinkupTask(4, 4)`). On a two-player
cable the DUO is one player, so these wait for the four-player cable experiment (docs/MULTI.md).

## How it works

From pret's pokeemerald (`contest_link.c`, `contest_link_util.c`, `contest.c`, `contest_util.c`,
`cable_club.c`, the Contest Lobby's scripts). The program is `firmware/programs/contest.c`.

1. **The link-up** (`LINKTYPE_CONTEST_EMODE` 0x6602, 2-4 players): the link players (the DUO says
   Emerald: E mode is Emerald only) and the trainer cards.
2. **The set-up** (`Task_LinkContest_StartCommunicationEm`), each step after a "ready" barrier. Each
   player sends its block straight away (no request):
   - each player's `struct ContestPokemon` (64 bytes). The DUO's is built on the PC as the game
     builds its own (`CreateContestMonFromParty`): species, nickname and trainer name in the link's
     form (the first five characters, an end, the rest after, the sixth kept last), the link
     Brendan or May, the moves, the condition, the ribbon rank, "game cleared", personality, OT;
   - the leader's random seed (4 bytes): only the leader sends it;
   - each player's leader ID (2 bytes, always 0x6E; the highest leads, so on a tie player 0, the
     game);
   - each player's category (2 bytes); differing categories end the link-up;
   - the leader's AI contestants (two of 64 bytes): only the leader sends them;
   - each player's round-1 points (8 bytes) and turn order (4 bytes): the leader's are used.
3. **The contest**: each player's contestant number (1 byte); in each of five rounds each player's
   move (2 bytes: the DUO's own, in turn); after each appeal, at the end of each round and before the
   next, the appeals' state (`Task_LinkContest_CommunicateAppealsState`: four blocks of 112, 18, 3
   and 4 bytes); at the end the final standings (8, 8, 8 and 4 bytes).
4. **The results**: each player's contestant number again, then the link closed (0x5FFF).

Every "each player's" block apart from the DUO's own contestant, number and moves is one where
every GBA sends its own copy and keeps the leader's (`gBlockRecvBuffer[gContestLinkLeaderIndex]`).
As the game is the leader, the DUO sends the game's own block straight back: it has the size the
game expects, and it is never read. So the DUO needs no copy of the contest's rules to take part.
The final standings block tells the PC the places.

## Tested

In the simulator, against `tests/contest_game_model.py` (the game's side, from the same sources): a
whole contest (the DUO's contestant checked field by field, nothing sent where only the leader
sends, every block answered at its size, the DUO's own move each round), and a beauty contest with
the moves in a given order; planted bugs for each. **Hardware next** (docs/HARDWARE_QUEUE.md).

A whole contest with the crowd worked out (the appeals' state filled in as the leader does: each
move's excitement, the meter, the bonus, the turn order), where the PC must follow the meter exactly
and play its weaker cool move only when it fills the meter; planted bugs for it.

Not yet: wireless contests; a deeper model of the others' moves (what the game's own contest AI
would pick) for the guess at the meter.
