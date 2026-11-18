# The Union Room (Emerald, FireRed/LeafGreen)

**Goal:** the DUO as a player in the game's Union Room: listed in the room, its trainer card
readable, then trades (and later battles and chat), all over the Mystery Gift cable (MGB-010, or any
Game Boy Color cable: a GBA link cable won't do, see WIRELESS.md). No Wireless Adapter: the DUO
plays the adapter *and* the player behind it, as it already does for Mystery Gift.

**Status (18 November):** milestones 1 and 2 and chat work in the simulator - `python duo_events.py
union`, the `union` program (adapter.c built with `-DUNION_ROOM`, 11.1 KB). Nothing on hardware yet -
it needs the cable swapped.

**Fixed 18 November, afternoon:** the trade request's activity was taken as 3; it is
`ACTIVITY_TRADE`, 4 (pret:pokeemerald/include/constants/union_room.h:24 - 3 is a multi battle). The
model had the same slip, so the simulator agreed with the program; on hardware the DUO would have
said no to every trade. Both now cite the header, and a planted bug brings back the old value.

**Try it (when the MGB-010 or another Game Boy Color cable is in):** `python duo_events.py union`,
then in Emerald, FireRed or LeafGreen go to the Union Room, walk up to the trainer called DUO, press
A and choose GREETINGS. The trace lists each step: the connection, the link players, the cards, the
game's request and the DUO's answer. With `--pk3 FILE --want TYPE` the DUO also puts that Pokemon on
the trading board: check the board, pick its offer and choose one of yours of that type.

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

## Milestone 1: listed in the room, card readable (simulator: done 18 November)

In the simulator (`tests/union_room_model.py`, the game's side, cited to pokeemerald) the game finds
the DUO, connects, exchanges link players and cards, asks for Greetings, reads the DUO's card and
leaves; asked for a trade, the DUO declines and the game closes the link. Three planted bugs (the
wrong serial, declining Greetings, accepting a trade) are each caught.

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

## Milestone 2: a trade from the trading board (simulator: done 18 November)

The Union Room's own trades go through its **trading board**, not the talk menu (whose choices are
Greetings, Battle, Chat and Exit: pret:pokeemerald/src/data/union_room.h:795
sInviteToActivityMenuItems). A player puts a Pokemon on the board and names the type they want;
another picks that offer, chooses one of their own of that type, and asks.

- **The DUO's offer** rides in its broadcast: `RfuGameData`'s `tradeSpecies`, `tradeType` (the type
  it wants) and `tradeLevel`. `python duo_events.py union --pk3 FILE --want TYPE` loads the Pokemon
  (its party form, 100 bytes) and sets the offer.
- **The request** (pret:pokeemerald/src/union_room.c:2766 UR_STATE_SEND_TRADE_REQUST): after the
  cards, the game sends `0x2F00`, `IN_UNION_ROOM | ACTIVITY_TRADE`, its species, its level. The DUO
  accepts if it has something on the board.
- **The swap** (pret:pokeemerald/src/union_room.c:1477 Task_StartUnionRoomTrade): a standby, then
  each sends its Pokemon (one 100-byte block), then its mail (220 bytes; the DUO's is empty).
- **The animation and the save** (pret:pokeemerald/src/trade.c:4627 CB2_UpdateLinkTrade,
  4650 CB2_WaitTradeComplete, 4676 CB2_SaveAndEndTrade): when its animation ends the game trades the
  Pokemon and says so (`0xABCD`, LINKCMD_READY_FINISH_TRADE); the leader - the DUO - then sends the
  go-ahead (`0xDCBA`). It must not come sooner: received during the animation it skips the trade
  itself (a planted bug checks this). Then three standbys around the save, and the close.
- **The PC** keeps the game's Pokemon as a `.pk3` in `received\`, as a cable trade does.

The full trade screen (choosing from the whole party) is the Direct Corner's wireless Trade Center:
a group link-up, then the Cable Club trade over wireless. That's a later milestone.

## Chat (simulator: done 18 November)

From the talk menu, CHAT (`IN_UNION_ROOM | ACTIVITY_CHAT`, 0x45): the DUO says yes, a standby, then
both are in pret:pokeemerald/src/union_room_chat.c. Every message there is a 40-byte block: its kind
(CHAT 1, JOIN 2, LEAVE 3, DROP 4), the sender's name (8 bytes), then the text - or, for the others,
the sender's player number (pret:pokeemerald/src/union_room_chat.c:1830 PrepareSendBuffer_Join and
the rest). The DUO is the leader, player 0:

- when the player's JOIN arrives, it joins too and says "HELLO! I'M THE DUO.";
- each message the player sends, it says back, and the PC prints it (`"NAME: text"`);
- when the player leaves (LEAVE), the DUO ends the chat with DROP, as a leader left on its own does
  (`Task_ReceiveChatMessage`, then `Chat_Exit`); the game then closes the link as usual.

The model is `URoomChild.chat_frame` in `tests/union_room_model.py`.

## Later

- The player contacting the game first (the DUO as child: the game's `UR_STATE_PLAYER_CONTACTED_YOU`).
- Battles (`union_room_battle.c`).
- Mystery Gift with a friend: done the other way round (the game sends, the DUO keeps it) in the
  `join` program - docs/WIRELESS_HOST.md.
- The wireless minigames and groups of more than two.

## Size

The distributor program is 11,656 of 11,760 bytes. The Union Room is a new program, `union`, from
the same parts with the Mystery Gift server left out: 11,384 bytes with chat.
