# The game as host: the DUO joins the game's group

**Why:** everything wireless so far has the DUO host and the game join (Mystery Gift from a
distributor, the Union Room's DUO trainer). Several features need it the other way round: the game
leads and the DUO joins as its child.

- **Mystery Gift with a friend, "Send"** (pret:pokeemerald/src/union_room.c:1880
  Task_SendMysteryGift): the game shares its Wonder Card or News with the DUO, so the PC can keep a
  copy - the one wireless way to back up a card the game already has.
- **The Direct Corner** when the game "becomes the leader" of a Trade Center, Colosseum, Berry Crush,
  and so on.
- **The Union Room** when the DUO talks to the game first (the game is then the parent).

Plan: docs/WIRELESS_HOST.md.

**Status (18 November):** stage H1 works in the simulator: the `join` build of `adapter.c`
(`-DGAME_HOSTS`, 8.4 KB) is listed as the game's child after a few polls and sends its name over NI
in a child's 2-byte-headed frames; `tests/host_game_model.py`, the game as leader (cited), reads it
and accepts its serial. H2 (the join answer, then link_rfu_2 with the DUO as player 1) is next.
No command-line use yet: nothing useful happens on hardware until H3.

## What the game does as host (librfu 1026, Emerald and FireRed/LeafGreen)

The leader's link manager (pret:pokeemerald/src/AgbRfu_LinkManager.c:432 rfu_LMAN_manager_entity's
states) runs, in order:

1. **reset, config system, config game data** - `0x10`, `0x17`, `0x16`, as today; the broadcast now
   carries the *game's* activity (for a friend's gift, `ACTIVITY_WONDER_CARD2` or `_NEWS2`).
2. **start searching for children** - `0x19` (pret:pokeemerald/src/librfu_rfu.c:505
   rfu_REQ_startSearchChild), after a system-status request (`0x13`) for the adapter's own ID.
3. **poll** - `0x1A`, again and again (pret:pokeemerald/src/librfu_rfu.c:557
   rfu_REQ_pollSearchChild). Each answer lists the children connected so far, four bytes each: the
   child's ID (2), its slot (1), one spare (pret:pokeemerald/src/librfu_rfu.c:592
   rfu_STC_readChildList). With librfu 1026 one listing is enough: the slot is connected at once
   (no four polls of signal strength, which older versions wanted).
4. **the child's name** - the newly connected child must send its serial number, game name and user
   name over the NI channel, data type 1, before a timer runs out
   (pret:pokeemerald/src/AgbRfu_LinkManager.c:1001 rfu_LMAN_PARENT_checkRecvChildName). A serial
   outside the game's accepted list (`0x0002` game, `0x7F7D` distributor:
   pret:pokeemerald/src/link_rfu_2.c:227 sAcceptedSerialNos) is disconnected.
5. **the answer** - the leader asks its player, then sends `RFU_STATUS_JOIN_GROUP_OK` (or `_NO`) to
   that child over NI (pret:pokeemerald/src/link_rfu_2.c:1691 (SendRfuStatusToPartner's
   rfu_NI_setSendData)).
6. **the link** - link_rfu_2 as parent: each frame the game sends its command table to the children
   (pret:pokeemerald/src/link_rfu_2.c:892 rfu_UNI_setSendData(gRfu.parentSlots, gRfu.recvCmds ...))
   and reads each child's commands; link players, blocks, standby and close as before, only now the
   DUO is player 1.

## What the DUO answers (the adapter emulation, reversed)

| The game sends | The DUO answers |
|---|---|
| `0x13` system status | its own adapter ID (as today) |
| `0x19` start host | OK |
| `0x1A` poll host | no children for a moment, then one: ID `0x2468` (any), slot 0 |
| `0x1B` end host | the same list |
| `0x26` receive data | the DUO-child's frames: first the NI name (data type 1: serial `0x0002`, a game name, "DUO"), then link_rfu_2's child UNI frames |
| `0x24`/`0x25` send data | the game's frames: its NI join answer, then its command table |

**The receive format, as parent** (pret:pokeemerald/src/librfu_rfu.c:1924
rfu_STC_PARENT_analyzeRecvPacket): the `0x26` answer's first data word, shifted right 8, holds four
5-bit byte counts, one per child slot; the frames follow from byte 8, slot 0's first. Each frame
starts with the *child's* 2-byte header (pret:pokeemerald/src/librfu_rfu.c:85 llsf_struct, the
MODE_CHILD entry: slot state at bit 10, ack bit 9, n at 7, phase at 5, length in the low bits) -
the same header the game writes today as the distributor's child, which `adapter.c` already parses.

Every piece of that already exists in `adapter.c`, facing the other way: the NI sender (`nis_*`,
used for "you may join"), the NI receiver (`ni_*`, used for the game's name), the parent's and
child's UNI frame formats. The work is the parent-search answers and the turned-round link_rfu_2
roles.

## Stages

1. **H1, the DUO appears and is named:** the game's list of joiners shows "DUO". Simulator first: a
   game-side model of the leader (link manager states above) beside `rfu_game_model.py`'s child.
2. **H2, accepted and linked:** the join answer, then link players with the DUO as player 1.
3. **H3, Mystery Gift with a friend:** the game's Mystery Gift server sends its card
   (pret:pokeemerald/src/mystery_gift_server.c), the DUO runs the client side
   (pret:pokeemerald/src/mystery_gift_client.c), the PC keeps the card as a `.wc3`.

A separate build of `adapter.c` (as `union` is), so the distributor and Union Room programs keep
their room.
