# The Union Room (Emerald, FireRed/LeafGreen)

**Goal:** the DUO as a player in the game's Union Room: listed in the room, its trainer card
readable, then trades (and later battles and chat), all over the Mystery Gift cable (MGB-010, or any
Game Boy Color cable: a GBA link cable won't do, see WIRELESS.md). No Wireless Adapter: the DUO
plays the adapter *and* the player behind it, as it already does for Mystery Gift.

**Status (18 November):** planned from the source; simulator work under way overnight. Nothing on
hardware yet - it needs the cable swapped.

## What is already there

The Mystery Gift distributor (`firmware/programs/adapter.c`, WIRELESS.md, DISTRIBUTOR.md) already
does most of the wireless plumbing, working on hardware with Japanese Emerald and LeafGreen:

- the adapter's ID exchange and command layer at 2 MHz, with the first-bit and ready-flick fixes;
- hosting with a broadcast (serial number, game name, user name), the game connecting as child;
- the child's name over librfu's NI channel, then "you may join";
- link_rfu_2's UNI command table every frame, blocks (`0x8800`/`0x8900`), the link-player exchange
  (`0x7700`, `0xA100`), the standby and close barriers (`0x6600`, `0x5F00`).

The game's side of that is modelled in `tests/rfu_game_model.py` (`ChildLink`: link_rfu_2's child).

So the Union Room is mostly *what is said* on an existing link, not a new link.

## Milestone 1: listed in the room, card readable

The DUO hosts (multiplayer id 0); the game, walking up and pressing A, connects as its child.

1. **Broadcast** (pret:pokeemerald/src/link_rfu_2.c:2066 SetHostRfuGameData,
   pret:pokeemerald/include/link_rfu.h:102 RfuGameData):
   - serial number `RFU_SERIAL_GAME` = `0x0002` (pret:pokeemerald/include/link_rfu.h:23), not the
     distributor's `0x7F7D`;
   - game name: `RfuGameData` - compatibility (language = the game's own, version, trainer ID),
     `activity = IN_UNION_ROOM | ACTIVITY_NONE` (`0x40`), `playerGender`, `startedActivity = 0`;
   - user name: "DUO".
2. **Who appears** (pret:pokeemerald/src/union_room.c:3465 Task_SearchForChildOrParent): a parent
   whose serial number is accepted (pret:pokeemerald/src/link_rfu_2.c:1563 IsRfuSerialNumberValid)
   and whose activity is in the Union Room's list (pret:pokeemerald/src/data/union_room.h:1029
   sAcceptedActivityIds_Resume). The English game drops Japanese partners
   (pret:pokeemerald/src/union_room.c:3478); the DUO broadcasts the game's own language, as the
   distributor does.
3. **Talking to the DUO** (pret:pokeemerald/src/union_room.c:2640 UR_STATE_INTERACT_WITH_PLAYER,
   2659 UR_STATE_TRY_COMMUNICATING): `TryConnectToUnionRoomParent`, then the same connect, NI name
   and join as Mystery Gift, then the link players.
4. **Cards** (pret:pokeemerald/src/union_room.c:1517 Task_ExchangeCards): player 0 - the DUO -
   asks for blocks of 100 bytes (`0xA100`, `BLOCK_REQ_SIZE_100`); both send their `struct
   TrainerCard` (pret:pokeemerald/include/trainer_card.h). The DUO's: name "DUO", the broadcast
   trainer ID, a gender, a few plausible counts.
5. **The game's choice** (pret:pokeemerald/src/union_room.c:2707
   UR_STATE_HANDLE_DO_SOMETHING_PROMPT_INPUT): the player picks from the menu; the game sends one
   packet, `0x2F00` + six words, the first `IN_UNION_ROOM | activity`
   (pret:pokeemerald/src/link_rfu_2.c:1280 Rfu_SendPacket, 1233 RfuPrepareSendBuffer).
6. **The DUO's answer** (pret:pokeemerald/src/union_room.c:4289 PollPartnerYesNoResponse): a packet
   from player 0 whose first word is `IN_UNION_ROOM | ACTIVITY_ACCEPT` (`0x51`) or `| ACTIVITY_DECLINE`
   (`0x52`). For "Greetings" (`ACTIVITY_CARD`) it accepts; the game then shows the DUO's card
   (pret:pokeemerald/src/union_room.c:4440 ViewURoomPartnerTrainerCard) and stands by
   (`0x6600`, already answered). Anything not yet built is declined politely.
7. **Leaving:** the game closes (`0x5F00`, already answered) or disconnects.

## Milestone 2: a trade

After accepting `IN_UNION_ROOM | ACTIVITY_TRADE` the game starts the trade
(pret:pokeemerald/src/union_room.c:3006 UR_STATE_PRINT_START_ACTIVITY_MSG onwards,
pret:pokeemerald/src/union_room.c:1477 Task_StartUnionRoomTrade). The trade screen's own protocol is
the cable trade's (`trade.c`), carried in link_rfu_2's commands instead of link.c's. The DUO's trade
logic is in `trade.c` today; how much of it can be shared with a wireless program, within a
program's 11.7 KB, is the design question for this milestone.

## Later

- The player contacting the game first (the DUO as child: the game's `UR_STATE_PLAYER_CONTACTED_YOU`).
- Battles (`union_room_battle.c`), chat (`union_room_chat.c`), the trade board.
- Mystery Gift with a friend (`Task_SendMysteryGift`, `Task_CardOrNewsWithFriend`).
- The wireless minigames and groups of more than two.

## Size

The distributor program is 11,656 of 11,760 bytes. The Union Room is a new program, `union`, from
the same parts with the Mystery Gift server left out.
