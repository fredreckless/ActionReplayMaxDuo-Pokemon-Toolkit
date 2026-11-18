# The Direct Corner: Cable Club rooms over wireless (plan, from the source)

**Why:** the Union Room's trade is a single swap from the trading board, and its battles are not
built. The Direct Corner (Emerald, FireRed/LeafGreen: the Pokemon Center's wireless counter) gives
the full Trade Center - the whole party on the trade screen, several trades in a sitting - and the
Colosseum, Record Corner, Berry Crush and the minigames, all as groups over the wireless link. The
DUO already does the cable versions of the Trade Center, Record Mixing and the Colosseum, and the
wireless plumbing as both host and child. This is the plan for joining them up. Nothing is built.

## What happens in the game (pret:pokeemerald, cited)

1. **The group.** One player becomes the leader (pret:pokeemerald/src/union_room.c:389
   Task_TryBecomeLinkLeader: hosting, `ACTIVITY_TRADE` etc. in its broadcast, not `IN_UNION_ROOM`);
   the other joins (pret:pokeemerald/src/union_room.c:984 Task_TryJoinLinkGroup: searching, the list
   of groups, connecting, the name, the leader's yes). The DUO can take either part now: as leader
   with the distributor's host code (`adapter.c`), as joiner with the `join` build's child code
   (stages H1 and H2b of docs/WIRELESS_HOST.md).
2. **The start** (pret:pokeemerald/src/union_room.c:1643 Task_StartActivity): for `ACTIVITY_TRADE`,
   a trainer card into the block buffer and a warp to the Trade Center (`USING_TRADE_CENTER`); the
   Colosseum and the Record Corner the same way, to their own rooms. On the way
   (pret:pokeemerald/src/union_room.c:1611 CB2_TransitionToCableClub) the cards are exchanged with
   `Task_ExchangeCards` - the Union Room's own exchange, which the `union` build already leads - and
   only then does the room load (`CB2_ReturnToFieldCableClub`).
3. **The room over wireless.** The overworld's link callback is the cable one
   (pret:pokeemerald/src/overworld.c:2239 CB1_OverworldLink), but its keys travel as
   `RFUCMD_SEND_HELD_KEYS` in link_rfu_2's command table (pret:pokeemerald/src/link_rfu_2.c:1029
   SendKeysToRfu: the key code with a counter in its top byte), and the game gives up if the link's
   state hasn't moved for 60 frames (pret:pokeemerald/src/overworld.c:2283 CheckRfuKeepAliveTimer).
   While its send queue is backed up it sends `LINK_KEY_CODE_NULL` in place of plain moves
   (pret:pokeemerald/src/overworld.c:2446 UpdateHeldKeyCode).
4. **The seat** (pret:pokeemerald/src/cable_club.c:1042 Task_EnterCableClubSeat, then 1127
   Task_StartWirelessTrade): a standby, then the trade menu - trade.c's own exchange of parties,
   choices and the trade itself, by blocks, as over the cable.

## What the DUO would need

- **A room walker on link_rfu_2.** `room_walk.h` already plans the DUO's walk to its seat and
  answers the game's moves on the cable. Over wireless the same key codes go out as
  `SEND_HELD_KEYS` rows, one each frame (also keeping the 60-frame watchdog happy).
- **The trade menu over blocks.** The cable `trade` program speaks trade.c's protocol through
  link.c's blocks; link_rfu_2's blocks carry the same bytes. The block layer differs (the parent's
  table, echoes, the child's four-frame grace) but the `union` and `join` builds have both sides.
- **Room.** The `union` build is 11.4 KB of 11.76; the `trade` program is near its limit too. A new
  build (`corner`) from adapter.c's wireless parts and trade.c's menu logic, with neither's extras -
  probably as two programs to begin with: the DUO as leader of a Trade Center first (the game joins,
  which is the path the distributor already walks on hardware).
- **Models.** `pret_link.Console` is the cable game; a wireless Console (link_rfu_2 underneath,
  `SendKeysToRfu` for keys) would let the existing Trade Center model run over the RFU model with
  little change.

## Order

1. The group as leader (DUO hosts "TRADE CENTER", the game joins and the activity starts): the smallest step, on code that already works on hardware.
2. The room: the DUO's keys over `SEND_HELD_KEYS`, walking to its seat; the game's watchdog quiet.
3. The trade menu over link_rfu_2: the cable trade program's logic, moved across.
4. Then the Colosseum (the battle partner) and the Record Corner the same way.

## Notes for the room (step 2), from the source

- **Arriving** (pret:pokeemerald/src/field_screen_effect.c:192 Task_ReturnToFieldWirelessLink): a
  standby first (the DUO, as leader, already answers it), then `StartSendingKeysToLink`, which over
  wireless is `StartSendingKeysToRfu` (pret:pokeemerald/src/link.c:714).
- **Keys out** (pret:pokeemerald/src/link_rfu_2.c:1029 SendKeysToRfu): once the link players are in,
  every frame the game has a key code to send, it sends `RFUCMD_SEND_HELD_KEYS` (0xBE00,
  pret:pokeemerald/include/link_rfu.h:19) with the code in the low byte of word 1 and a counter in its
  high byte.
- **Keys in**: link_rfu_2 puts each player's word 1 in `gLinkPartnersHeldKeys`; the overworld reads
  only its low byte (pret:pokeemerald/src/overworld.c:2429 UpdateAllLinkPlayers), and only on frames
  when a command came in or the game isn't sending keys (pret:pokeemerald/src/overworld.c:2239
  CB1_OverworldLink). So the DUO's key codes go out as 0xBE00 rows, one a frame, like the game's.
- **The watchdog**: while the game waits in certain key callbacks (`KeyInterCB_Idle`, `_Ready`
  before its own READY is back, `_ExitingSeat`, `_WaitForPlayersToExit`), each call counts towards
  60 (pret:pokeemerald/src/overworld.c:2283 CheckRfuKeepAliveTimer); a change of callback resets it.
  The change comes from the game's *own* key coming back through the link
  (pret:pokeemerald/src/overworld.c:2319 HandleLinkPlayerKeyInput: its IDLE, READY or EXIT_ROOM, read
  from its own row). As leader the DUO echoes every row in its table each frame, so the game's keys
  do come back; what the DUO must not do is let the table stall for a second.
- The cable room is modelled from pokeruby (`tests/pret_cable_club.py` LinkRoom); Emerald's
  overworld link (the functions above, and the key intercept callbacks around
  pret:pokeemerald/src/overworld.c:2516 KeyInterCB_SelfIdle) wants porting for the wireless room.
