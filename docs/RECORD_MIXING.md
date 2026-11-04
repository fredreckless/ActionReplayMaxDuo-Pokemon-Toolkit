# Record Mixing and Secret Bases

**Status (4 November 2026): step 2 done in the simulator.** `python duo_events.py mix` runs
`firmware/programs/mix.c` against the game; `tests/mix_game_model.py` models Ruby's Record Corner and
its filing rules, ported from pokeruby on their own, and checks the tool's copy of them
(`secret_bases.py`). Six tests and nineteen planted bugs cover it. Step 3, hardware (Ruby, then
Emerald), is next. The `.sb3` file is specified in `docs/SB3_FORMAT.md`.

This reads pokeruby and pokeemerald to see how the DUO can sit in a Record Corner as the other
player and hand the game Secret Bases, so that the game merges them and **saves them itself**, the
same way the trade works.

Sources: pokeruby `record_mixing.c`, `secret_base.c`, `global.h`, `mystery_event_script.c`,
`data/scripts/cable_club.inc`; pokeemerald `src/record_mixing.c`, `src/secret_base.c`,
`src/pokemon.c` (`CreateSecretBaseEnemyParty`), `include/global.h`, `include/link.h`,
`include/constants/secret_bases.h`, `include/constants/decorations.h`, `data/maps/*/map.json`.

## The short answer

Yes, and it fits what the DUO already does.

- The Record Corner is the Cable Club again: the same link layer, the same "please wait" set-up
  as the trade (`docs/TRADE.md`), link type **0x3311** while joining and **0x3322** back in the
  room afterwards, two to four players.
- Each player sends one record of about 4.6 KB in 200-byte blocks. The first part of it is the
  sender's **twenty Secret Bases**, each exactly as it sits in their save (160 bytes).
- The game checks almost nothing about a received base. It does not checksum it, and it does not
  check the team or the decorations. It only decides *where* to file it (below). So a base we
  write ourselves is received exactly like one from a real player.
- After mixing, the game runs its own link save. **We never touch the cartridge save.**
- One sitting can deliver **up to twenty bases**: the "owner's" base in slot 0 and nineteen
  others in slots 1 to 19, just as a real player passes on the bases they have collected.
- The game only takes bases at all once the player has **Secret Power** (`FLAG_RECEIVED_SECRET_POWER`);
  without it, the rest of the record is still mixed, but bases are ignored.
- The same sitting can hand over a **gift item**, which is how the Eon Ticket was passed on, but
  only from player 0 (below).

## The link: the Record Corner

The player talks to the right-hand attendant on the Pokémon Center's upper floor and chooses the
Record Corner. Everyone joins with link type 0x3311 (`LINKTYPE_RECORD_MIX_BEFORE`), enters the room
and walks onto a seat; stepping on a seat (`RecordMixingPlayerSpotTriggered`) starts
`Task_RecordMixing_Main` on that GBA. It clears the link callback, waits for the link players, and
then exchanges records:

- the master (player 0) asks for each block in turn with `0xCCCC 1` (`sub_8007E9C(1)` in Ruby);
- every player copies the next 200 bytes of its own record into `gBlockSendBuffer` and sends it;
- everyone stores every player's blocks at `record + player × sizeof(record)`.

| Who is mixing | Record layout | Size | Blocks of 200 bytes |
|---|---|---|---|
| Ruby/Sapphire with anyone | `struct PlayerRecords` (Ruby) / `PlayerRecordRS` (Emerald) | 0x1230 (4,656) | 24 |
| Emerald with only Emeralds | `struct PlayerRecordEmerald` | 0x1444 (5,188) | 26 |

The block count is `size / 200 + 1`, so the last block is partly filler.

Then each game merges what it received (`RecordMixing_ReceiveExchangePacket` in Ruby,
`ReceiveExchangePacket` in Emerald), runs its link save (`sub_8125E2C`/`sub_8125E6C` in Ruby), and
goes back to the room with link type 0x3322 (`LINKTYPE_RECORD_MIX_AFTER`). Leaving is the same walk
to the door and close that the trade already does.

**Emerald follows Ruby's layout whenever any partner reports Ruby or Sapphire**
(`Link_AnyPartnersPlayingRubyOrSapphire`). So if the DUO's link player says "Ruby" (version 2), one
record format serves Ruby, Sapphire and Emerald alike. That is my suggestion for the first version.

### What a Ruby record holds (offsets in the record)

| Offset | Field | Size |
|---|---|---|
| 0x0000 | `secretBases[20]` | 20 × 0xA0 |
| 0x0C80 | `tvShows[25]` | 25 × 0x24 |
| 0x1004 | `pokeNews[16]` | 16 × 4 |
| 0x1044 | the Mauville old man | 0x40 |
| 0x1084 | Dewford trends (`easyChatPairs[5]`) | 5 × 8 |
| 0x10AC | day-care mail | 0x78 |
| 0x1124 | Battle Tower record | 0xA4 |
| 0x11C8 | `giftItem` (u16) | 2 |
| 0x11CA | filler | 0x66 |

Emerald's own layout adds the Lilycove lady, two apprentices and the Battle Frontier hall records
after the gift item.

### Who takes whose record

Each game reads the other records in a fixed rotation by its own player number. With two players
the game blanks the two missing records itself (`memset` of slots 2 and 3), so the partner's record
is the only one it learns from, and an all-zero record is something every receiver already sees
in an ordinary two-player sitting.

## How a game files the bases it receives

Ruby `ReceiveSecretBasesData` → `sub_80BD610`; Emerald `ReceiveSecretBasesData` →
`SaveRecordMixBases`. They are the same rules with new names. For each partner's twenty bases:

1. **The player's own base is removed from what came in.** The first incoming base whose gender,
   trainer ID and name match the player is cleared (`SecretBaseBelongsToPlayer`). So a card can't
   overwrite the player's own base, even by accident.
2. **Duplicates are resolved.** Two bases "belong to the same trainer" when gender, all four
   trainer-ID bytes and the name match. If the player already has a base from that trainer, the
   one with the higher `numSecretBasesReceived` wins; incoming copies among partners are cleared.
   A registered base deleted this way is marked to be re-registered afterwards.
3. **Bases are saved in order:** registered duplicates first, then each partner's own base
   (slot 0), then their registered bases (`registryStatus` 1), then the unregistered ones (0).
4. **Where one goes** (`sub_80BD1FC` / `TrySaveFriendsSecretBase`):
   - a base with `secretBaseId` 0 is empty and skipped;
   - if the player's **own** base is at that location, the incoming one is dropped;
   - if another base is already at that location, it is replaced, unless that one is registered,
     or new from this same sitting (and the incoming one isn't marked to register);
   - otherwise it takes an empty slot (1 to 19), or else replaces the first unregistered base;
   - if all nineteen are registered, it is dropped.
5. A saved base is marked new (`registryStatus` 2) for the sort, then unregistered (0). The player
   can register it later at its PC, which protects it from being replaced.
6. `battledOwnerToday` is cleared on everything received. The player's own
   `numSecretBasesReceived` goes up by one.

**Emerald's extras:** `struct SecretBase` uses the spare byte at 0x0D for `language`. Bases arriving
from Ruby or Sapphire get the receiving game's language; a Japanese Emerald base with a name longer
than five characters is relabelled; and Emerald never sends Japanese bases to Ruby
(`ClearJapaneseSecretBases`). None of that gets in our way.

## What one base is (160 bytes, the same in both games)

| Offset | Field | Notes |
|---|---|---|
| 0x00 | `secretBaseId` | the location (table below); 0 means empty |
| 0x01 | bits 0–3 `toRegister`, bit 4 `gender`, bit 5 `battledOwnerToday`, bits 6–7 `registryStatus` | send 0 except gender |
| 0x02 | owner's name, 7 bytes | Gen 3 text, 0xFF-padded |
| 0x09 | trainer ID, 4 bytes | public ID then secret ID; byte 0 also picks the owner's look |
| 0x0D | Ruby: padding. Emerald: `language` | |
| 0x0E | `numSecretBasesReceived` (u16) | decides duplicates; 0 is fine |
| 0x10 | `numTimesEntered` | |
| 0x11 | unused | |
| 0x12 | `decorations[16]` | decoration IDs (list at the end); 0 = none |
| 0x22 | `decorationPos[16]` | x in the high four bits, y in the low four |
| 0x32 | padding (2) | |
| 0x34 | team: `personality[6]` (u32) | |
| 0x4C | team: `moves[24]` (u16, four per Pokémon) | |
| 0x7C | team: `species[6]` (u16) | 0 = no Pokémon |
| 0x88 | team: `heldItems[6]` (u16) | |
| 0x94 | team: `levels[6]` | |
| 0x9A | team: `EVs[6]` | one number per Pokémon |

**The owner's team in battle** (Emerald `CreateSecretBaseEnemyParty`): each Pokémon is made with its
species, level and personality (so its nature, gender and ability follow from the personality),
**IVs all 15**, a random trainer ID that is never shiny, its held item, its four moves with full
PP, and **the one EV number in every stat**. So a base's team can't be shiny and can't have chosen
IVs; everything else is ours to choose.

**The owner's look:** Emerald picks the trainer class from `trainerId[0] % 5` and the gender (five
classes each for boys and girls). Ruby is believed to do the same; hardware will confirm it.

## The gift item (and the Eon Ticket)

Only player 0 fills in `giftItem` (from its own stored Record Mixing gift, `GetRecordMixingGift`),
and only players other than 0 accept one (`ReceiveGiftItem`):

- a **key item** is given only if the player has none in the Bag or PC; the Eon Ticket also sets
  the flag that opens the Southern Island ferry (`FLAG_SYS_HAS_EON_TICKET` in Ruby,
  `FLAG_ENABLE_SHIP_SOUTHERN_ISLAND` in Emerald);
- Ruby also accepts an ordinary item, if the Bag has room.

**For the DUO to give a gift, it must be player 0**: the GBA on the master end of the cable, which is
the other way round from how the cable is usually set up for trades now. Bases themselves flow
both ways, so either end works for those.

## What the DUO sends (mix.c)

A record in Ruby's layout:

- **slot 0** the first `.sb3`'s base (in a real record, its owner's own), slots 1 to 19 the rest,
  all with `registryStatus` 0 and `toRegister` 0. That is rounds 0 to 15 exactly (20 x 160 = 16 x 200);
- **from round 16 on, the game's own sections handed straight back**: its TV shows, PokéNews, Mauville
  old man, Dewford trends and day-care mail. Each game takes the other's old man outright and merges
  the rest, so mixing with a copy of itself changes nothing: trends with equal words are merged
  (`GetEqualEasyChatPairIndex`), a TV show the game already has goes back where it came from, and
  day-care mail swaps with an identical copy. An empty record would have been worse: an all-zero
  Mauville old man, and the player's TV shows moved out into the DUO's list and lost. To hand them
  back, the DUO waits for the game's block of each of these rounds before sending its own (the game
  waits for every player's block, so this costs only time: about 16 frames a round);
- **the Battle Tower record empty**, as from a friend who hasn't been there (sub_8134AC0 files an
  empty record into an empty slot);
- `giftItem` from `--gift` (only player 0's is read), the filler zero.

The game's own rounds 0 to 15, its twenty bases, are kept in the same buffer as each of ours goes
out, and read by the PC afterwards: its own base (slot 0) arrives with its team, as the game fills
that in when it mixes. The PC then runs secret_base.c's filing on both sets to say which of ours the
game kept.

The rest of the sitting, as the program plays it:

- **Joining:** the attendant's link (0x3311) is the trade's: link players, then the trainer cards
  (0xCCCC 2), then room keys (0xCAFE) one a frame. The DUO's trainer card and link player show the
  first base's owner.
- **Sitting down:** the room is 20 x 10 with four seats round a table, (6,4), (13,4), (6,6) and
  (13,6). Players arrive side by side at (8,9) and (9,9). The DUO walks to a seat on its own side:
  player 0 up, up, left, left, up to (6,6); player 1 up, up, right x4, up to (13,6). Then it sends
  key 22 ("seated"). When every player is seated, each game starts `Task_RecordMixing_Main`: its
  room keys stop (`ClearLinkCallback_2`), so the DUO's do too.
- **The rounds:** 20 + 60 frames, then 24 rounds. In each, the master asks with 0xCCCC 1 and every
  player sends 200 bytes from its `gBlockSendBuffer`. A game copies its next chunk two frames after a
  round completes, so as master the DUO waits 8 frames between rounds, and 150 frames before the
  first.
- **The save:** the game merges, then saves by itself (`sub_8125E2C`, no link barrier), and after 10
  frames closes the link (0x5FFF).
- **Back in the room:** the game reopens the link as 0x3322 (`sub_8083664`, `VAR_0x8004` = 4). The
  room is not reloaded and everyone is still "seated" (status 0x82), so a player must send 26 before
  moving. The DUO sends 26, walks back to the door and leaves (23), or follows the player out as
  soon as they leave.

### Still to see on hardware (step 3)

- How long Ruby takes between the last round and closing the link (the model allows 19 frames).
- That the DUO, sitting first, never blocks the player's way to their seat.
- Emerald: the DUO's link player copies the game's version, so Emerald would mix in its own
  layout, which the DUO doesn't speak yet. The plan is for the DUO to say "Ruby" to Emerald, so that
  Emerald uses Ruby's layout (`Link_AnyPartnersPlayingRubyOrSapphire`). Until then the tool warns
  and suggests leaving the room.

## The Secret Base card

Decided on 4 November: the shared file is **`.sb3`, one base per file, the game's own 160-byte
record**, in the spirit of `.pk3` and `.wc3`. Several files go together for one sitting, bases
can be read out of save backups in the first version, and a text "base card" makes hand-made
ones (most bases will be hand-made). The specification is `docs/SB3_FORMAT.md`.

## Appendix: the 75 Secret Base locations (from Emerald's maps)

The ID's tens digit picks the room (the same room shape for every location in that group); the
units digit tells apart the locations sharing that room. The x, y are the entrance's tile on the
route.

| ID | Kind | Route | Entrance (x, y) |
|---|---|---|---|
| 1 | Red cave, room 1 | Route 118 | 47, 14 |
| 2 | Red cave, room 1 | Route 125 | 53, 10 |
| 3 | Red cave, room 1 | Route 113 | 49, 8 |
| 11 | Red cave, room 2 | Route 118 | 67, 6 |
| 12 | Red cave, room 2 | Route 121 | 40, 11 |
| 13 | Red cave, room 2 | Route 111 | 35, 1 |
| 21 | Red cave, room 3 | Route 115 | 20, 53 |
| 22 | Red cave, room 3 | Route 121 | 18, 13 |
| 23 | Red cave, room 3 | Route 119 | 26, 81 |
| 31 | Red cave, room 4 | Route 127 | 59, 67 |
| 32 | Red cave, room 4 | Route 125 | 55, 11 |
| 33 | Red cave, room 4 | Route 111 | 27, 27 |
| 41 | Brown cave, room 1 | Route 114 | 9, 47 |
| 42 | Brown cave, room 1 | Route 115 | 32, 39 |
| 43 | Brown cave, room 1 | Route 115 | 23, 8 |
| 51 | Brown cave, room 2 | Route 114 | 30, 51 |
| 52 | Brown cave, room 2 | Route 115 | 26, 15 |
| 53 | Brown cave, room 2 | Route 115 | 32, 46 |
| 61 | Brown cave, room 3 | Route 114 | 11, 62 |
| 62 | Brown cave, room 3 | Route 115 | 21, 18 |
| 63 | Brown cave, room 3 | Route 115 | 25, 24 |
| 71 | Brown cave, room 4 | Route 114 | 19, 70 |
| 72 | Brown cave, room 4 | Route 115 | 32, 6 |
| 73 | Brown cave, room 4 | Route 114 | 32, 57 |
| 81 | Blue cave, room 1 | Route 116 | 71, 4 |
| 82 | Blue cave, room 1 | Route 123 | 47, 3 |
| 83 | Blue cave, room 1 | Route 123 | 57, 5 |
| 91 | Blue cave, room 2 | Route 116 | 79, 11 |
| 92 | Blue cave, room 2 | Route 123 | 49, 3 |
| 93 | Blue cave, room 2 | Route 120 | 18, 12 |
| 101 | Blue cave, room 3 | Route 120 | 28, 62 |
| 102 | Blue cave, room 3 | Route 116 | 56, 6 |
| 103 | Blue cave, room 3 | Route 119 | 16, 81 |
| 111 | Blue cave, room 4 | Route 120 | 30, 62 |
| 112 | Blue cave, room 4 | Route 116 | 55, 15 |
| 113 | Blue cave, room 4 | Route 119 | 16, 28 |
| 121 | Yellow cave, room 1 | Route 111 | 33, 34 |
| 122 | Yellow cave, room 1 | Route 118 | 29, 5 |
| 123 | Yellow cave, room 1 | Route 127 | 45, 24 |
| 131 | Yellow cave, room 2 | Route 111 | 24, 36 |
| 132 | Yellow cave, room 2 | Route 125 | 7, 25 |
| 133 | Yellow cave, room 2 | Route 115 | 8, 30 |
| 141 | Yellow cave, room 3 | Route 111 | 34, 50 |
| 142 | Yellow cave, room 3 | Route 127 | 59, 72 |
| 143 | Yellow cave, room 3 | Route 127 | 61, 21 |
| 151 | Yellow cave, room 4 | Route 127 | 67, 63 |
| 152 | Yellow cave, room 4 | Route 125 | 24, 32 |
| 153 | Yellow cave, room 4 | Route 111 | 35, 31 |
| 161 | Tree, room 1 | Route 111 | 13, 19 |
| 162 | Tree, room 1 | Route 121 | 43, 7 |
| 163 | Tree, room 1 | Route 118 | 47, 5 |
| 164 | Tree, room 1 | Route 111 | 14, 19 |
| 171 | Tree, room 2 | Route 118 | 46, 5 |
| 172 | Tree, room 2 | Route 121 | 42, 7 |
| 173 | Tree, room 2 | Route 119 | 19, 76 |
| 174 | Tree, room 2 | Route 115 | 7, 20 |
| 181 | Tree, room 3 | Route 110 | 16, 25 |
| 182 | Tree, room 3 | Route 114 | 11, 27 |
| 183 | Tree, room 3 | Route 115 | 8, 20 |
| 191 | Tree, room 4 | Route 110 | 17, 25 |
| 192 | Tree, room 4 | Route 114 | 12, 27 |
| 193 | Tree, room 4 | Route 119 | 18, 76 |
| 201 | Shrub, room 1 | Route 119 | 5, 2 |
| 202 | Shrub, room 1 | Route 119 | 4, 89 |
| 203 | Shrub, room 1 | Route 120 | 38, 54 |
| 204 | Shrub, room 1 | Route 120 | 5, 76 |
| 211 | Shrub, room 2 | Route 119 | 5, 15 |
| 212 | Shrub, room 2 | Route 119 | 7, 101 |
| 213 | Shrub, room 2 | Route 120 | 31, 23 |
| 221 | Shrub, room 3 | Route 119 | 34, 24 |
| 222 | Shrub, room 3 | Route 120 | 26, 10 |
| 223 | Shrub, room 3 | Route 119 | 4, 15 |
| 231 | Shrub, room 4 | Route 119 | 31, 73 |
| 232 | Shrub, room 4 | Route 120 | 29, 85 |
| 233 | Shrub, room 4 | Route 119 | 6, 2 |

## Appendix: decoration IDs (pokeemerald `include/constants/decorations.h`)

0 is no decoration. 1 Small Desk, 2 Pokemon Desk, 3 Heavy Desk, 4 Ragged Desk, 5 Comfort Desk, 6 Pretty Desk, 7 Brick Desk, 8 Camp Desk, 9 Hard Desk, 10 Small Chair, 11 Pokemon Chair, 12 Heavy Chair, 13 Pretty Chair, 14 Comfort Chair, 15 Ragged Chair, 16 Brick Chair, 17 Camp Chair, 18 Hard Chair, 19 Red Plant, 20 Tropical Plant, 21 Pretty Flowers, 22 Colorful Plant, 23 Big Plant, 24 Gorgeous Plant, 25 Red Brick, 26 Yellow Brick, 27 Blue Brick, 28 Red Balloon, 29 Blue Balloon, 30 Yellow Balloon, 31 Red Tent, 32 Blue Tent, 33 Solid Board, 34 Slide, 35 Fence Length, 36 Fence Width, 37 Tire, 38 Stand, 39 Mud Ball, 40 Breakable Door, 41 Sand Ornament, 42 Silver Shield, 43 Gold Shield, 44 Glass Ornament, 45 Tv, 46 Round Tv, 47 Cute Tv, 48 Glitter Mat, 49 Jump Mat, 50 Spin Mat, 51 C Low Note Mat, 52 D Note Mat, 53 E Note Mat, 54 F Note Mat, 55 G Note Mat, 56 A Note Mat, 57 B Note Mat, 58 C High Note Mat, 59 Surf Mat, 60 Thunder Mat, 61 Fire Blast Mat, 62 Powder Snow Mat, 63 Attract Mat, 64 Fissure Mat, 65 Spikes Mat, 66 Ball Poster, 67 Green Poster, 68 Red Poster, 69 Blue Poster, 70 Cute Poster, 71 Pika Poster, 72 Long Poster, 73 Sea Poster, 74 Sky Poster, 75 Kiss Poster, 76 Pichu Doll, 77 Pikachu Doll, 78 Marill Doll, 79 Togepi Doll, 80 Cyndaquil Doll, 81 Chikorita Doll, 82 Totodile Doll, 83 Jigglypuff Doll, 84 Meowth Doll, 85 Clefairy Doll, 86 Ditto Doll, 87 Smoochum Doll, 88 Treecko Doll, 89 Torchic Doll, 90 Mudkip Doll, 91 Duskull Doll, 92 Wynaut Doll, 93 Baltoy Doll, 94 Kecleon Doll, 95 Azurill Doll, 96 Skitty Doll, 97 Swablu Doll, 98 Gulpin Doll, 99 Lotad Doll, 100 Seedot Doll, 101 Pika Cushion, 102 Round Cushion, 103 Kiss Cushion, 104 Zigzag Cushion, 105 Spin Cushion, 106 Diamond Cushion, 107 Ball Cushion, 108 Grass Cushion, 109 Fire Cushion, 110 Water Cushion, 111 Snorlax Doll, 112 Rhydon Doll, 113 Lapras Doll, 114 Venusaur Doll, 115 Charizard Doll, 116 Blastoise Doll, 117 Wailmer Doll, 118 Regirock Doll, 119 Regice Doll, 120 Registeel Doll.
