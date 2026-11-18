# Connectivity and the games' source

The rule (17 November, Fred): every connectivity routine starts from the games' own source, and that
source is built into the simulator. This page lists each routine, the source it rests on, the
simulator's model of the game, and how far that model is a port.

## How it works

- **The source:** pret's decompilations, pinned to one commit each (`tools/pret.py`; it fetches
  `src/` and `include/` into `~/.cache/pret`, or `$PRET_DIR`). Not committed here.

  | repo | commit |
  |---|---|
  | pokeruby | `5784633ce4ef7ade1a7f2d2d0c288e3d5e6cdd7f` |
  | pokeemerald | `9103e529c2fbdd7add4a1ff3350c6c1f92112c42` |
  | pokefirered | `ce6406d8c2eaf46d543c8a2606de0c3cb1951982` |

- **Citations:** a model cites what it ports as `pret:<repo>/<file>:<line> <Name>`.
  `tests/source_anchors.py` checks every one against the pinned source on every test tier
  (`check.py quick`, `changed`, `full`). It fails if the cited line doesn't name the function or
  macro it claims. Without the source cached it says it's skipped; it doesn't pass silently.
- **Shared, not copied:** a ported piece lives in one module, and every model uses it. Today that's
  `tests/pret_link.py` (link.c whole: the serial layer `GameLink`, and above it `Console` - the
  commands, blocks, link players, callbacks, error status and main.c's loop - plus `Cable`, which
  joins consoles frame by frame) and `tests/pret_cable_club.py` (the Cable Club's link-up and the
  link rooms).
- **The models on top:** `trade_game_model.Session` runs each routine's handlers on a `Console`
  (trade, Record Mixing, battles, the Battle Tower, the blender, contests all go through it). What
  a handler sends goes into `gSendCmd` as the game's task code would put it; the room's keys go
  through link.c's keys callback, with its lockstep; blocks, link players, the "ready" barrier and
  the close are link.c's own.
- **What the source can't say:** the link hardware itself, meaning bit timing, the error flag's
  conditions, when SIOMULTI latches, and how long a unit waits for the next. That comes from GBATEK
  and our own hardware runs (the scope, 16 November), and the code marks it with the run's date.

Status: **ported** means a line-by-line port with citations checked. **From source** means it was
written from the source when the routine was built, cites files but not lines, and hasn't been
re-checked. **Hardware** means not in any game source; GBATEK and our runs.

## The link layer (every cable routine)

| What | Source | Model | Status |
|---|---|---|---|
| Serial layer: handshake, checksums, queues, error status | pokeruby `link.c`: `LinkMain1`, `SerialCB`, `DoHandshake`, `DoRecv`, `DoSend`, `SendRecvDone`, `LinkVSync`, `EnqueueSendCmd`, `DequeueRecvCmds`, `CheckErrorStatus` (the same in Emerald and FireRed, checked by hand on 17 November) | `tests/pret_link.py`, used by `link_game_model.LinkLayer` (trade, mix, battle, tower, contest, blender, e-Reader) and `gp_link_model` (lab4p) | **ported** |
| Link commands: `0x2222` link players, `0xBBBB`/`0x8888` blocks, `0xCCCC` block requests, `0x5FFF` close, `0x2FFE` ready, `0xCAFE` keys; the link callbacks; `OpenLink`/`CloseLink`; main.c's loop (the lockstep, the double update) | pokeruby `link.c` `ProcessRecvCmds`, `BuildSendCmd`, `InitBlockSend` and the block callbacks, `HandleReceiveRemoteLinkPlayer`, `SetCloseLinkCallback`, `sub_80084A4` (ready), `sub_8007B14` (keys), `GetLinkPlayerDataExchangeStatusTimed`; `main.c` `UpdateLinkAndCallCallbacks` | `pret_link.Console`, under `trade_game_model.Session` (every Cable Club routine) | **ported** |
| Cable Club link-up, trainer cards | `cable_club.c` `sub_8082CD4` and its tasks, `sub_8082D9C` | `pret_cable_club.LinkUp` | **ported**; the routine models still do their own link-up steps on top of `Console` (next: use `LinkUp`) |
| Link rooms: entering (the ready barrier, the keys callback), the key codes, the queue throttle (27/28) | `overworld.c` `sub_8055354`, `sub_8055390`, `sub_8055408`, `sub_8055438`, `sub_8054FF8`; `field_fadetransition.c` `sub_8080A5C` | `pret_cable_club.LinkRoom` | **ported** (walking reduced to "busy for a step"); the routine models keep their own room maps on top |
| lab4p's game side (the Trade Center as a child, at the line level) | as above | `gp_link_model` | serial layer ported; its Trade Center flow is still its own copy (next) |
| Link hardware: start/stop bits, SO hand-over, error flag, SIOMULTI latching, the wait for the next unit | none (GBATEK; scope 16 November) | `gp_link_model` (lines), `SioHardwareMaster`, hwsim | hardware |

## Routines

| Routine (program) | Games | Source | Model | Status |
|---|---|---|---|---|
| Trade (`trade`) | R/S, E, FR/LG | `trade.c`, `cable_club.c`, `overworld.c` | `trade_game_model.py` | from source |
| Record Mixing (`mix`) | R/S, E | `record_mixing.c`, `secret_base.c`, `tv.c` | `mix_game_model.py` | from source |
| Colosseum battles (`colosseum`) | R/S, E, FR/LG | `battle_main.c`, `battle_controllers.c`, `battle_controller_link_*.c` | `battle_game_model.py` | from source |
| Battle Tower link multi (`tower`) | E | `battle_tower.c`, `cable_club.c` | `tower_game_model.py` | from source |
| Berry Blender (`blender`) | R/S, E | `berry_blender.c` | `blender_game_model.py` | from source |
| Link Contest (`contest`) | E | `contest_link.c`, `contest_link_util.c` | `contest_game_model.py` | from source |
| e-Reader route, Mystery Event (`ereader`) | R/S | `mystery_event_menu.c`, `mystery_event_script.c` | `link_game_model.py`, `mevent_model.py` | from source |
| e-Reader Trainer Hill/Tower | E, FR/LG (Japanese) | `ereader_helpers.c`, `cereader_tool.c` | `link_game_model.py` | from source |
| Wireless Adapter (`adapter*`) | E, FR/LG | `librfu_intr.c`, `librfu_stwi.c`, `librfu_sio32id.c`, `mystery_gift_*.c` | `rfu_game_model.py`, `sio32id_model.py` | from source (librfu: a port, file-level citations) |
| Four players on a two-player cable (`lab4p`) | R/S | `link.c` (above) | `gp_link_model.py` | **parked** (17 November: the game read the DUO's hand-sent slots as garbage on all 12 settings, 2353 tries); serial layer ported |
| Union Room, milestone 1: listed, Greetings, the card (`union`) | E, FR/LG | `union_room.c` (Task_ExchangeCards, the activity packets), `link_rfu_2.c` (Rfu_SendPacket, SetHostRfuGameData) | `union_room_model.py` on `rfu_game_model.py` | **from source**, cited; simulator done 18 November (milestone 2, the trading-board trade, too: `trade.c`), hardware needs the MGB-010 |
| Union Room trade (trading board) and chat (`union`) | E, FR/LG | `union_room.c` (Task_StartUnionRoomTrade, the trade request), `trade.c` (CB2_LinkTrade, the finish handshake), `union_room_chat.c` (the 40-byte messages, Task_ReceiveChatMessage, Chat_Exit), `constants/union_room.h` (activities, cited with values) | `union_room_model.py` | **from source**, cited; simulator, 18 November (the trade request's activity fixed: 4, not 3). Battles not yet |
| The game as wireless host, the DUO joining (`join`, `friend`): stages H1 to H3 | E, FR/LG | librfu (`rfu_REQ_pollSearchChild`, `rfu_STC_readChildList`, `rfu_STC_PARENT_analyzeRecvPacket`, `rfu_REQ_sendData`), `AgbRfu_LinkManager.c` (`rfu_LMAN_PARENT_checkRecvChildName`), `link_rfu_2.c` (the join status, `RfuMain1_Parent`, `RfuMain2_Parent`, `Task_PlayerExchange`, the parent's block send, standby and close), `mystery_gift_server.c`, `mystery_gift_scripts.c`, `mystery_gift.c` (game-data checks), `mystery_gift_client.c` (in C, on the DUO) | `host_game_model.py` | **from source**, cited; simulator, 18 November. Next: the Direct Corner, or the Union Room with the game as parent |

## Next, in order

Porting is frozen in breadth (17 November): a routine's protocol is ported, with citations, when
that routine is next worked on, not before.

1. (Parked with four players) Move `gp_link_model`'s game side onto `Console`, `LinkUp` and
   `LinkRoom`, replacing its own Trade Center flow.
2. Have the routine models use `LinkUp` for the Cable Club steps instead of their own.
3. Add line citations to each routine's own protocol (trade.c, record_mixing.c, ...) as it's next
   touched, so the anchors check them.
4. Check the ported functions are the same across Ruby, Emerald and FireRed mechanically, not by
   hand.

## What the port has already found (17 November)

- **DoHandshake:** a slot that reads as neither a handshake nor empty counts **no players**. The
  line-level model counted the slots before it instead. That's how the DUO's hand-sent slots seemed
  to link four players when the game counted none (16 November).
- **SerialCB copies the link hardware's error flag** (`SIO_MULTI_CNT->error`) into
  `gLink.hardwareError` on every transfer once linked. `CheckErrorStatus` makes that a link error,
  even with every checksum matching. Neither copy of the link layer knew this.
- **One command a frame:** `LinkVSync` starts each command at VBlank and the timer spaces its nine
  transfers. lab4p's pacing drifted later each frame; it now keeps to its schedule.
- **Correction (17 November, afternoon):** the morning's claim that the game's queue fills in the
  Trade Center room came from the old room model, which queued a key every frame without fail. The
  real room throttles itself: the key function sends 27 or 28 when either queue holds more than four
  commands and freezes the player until it's down to two (`overworld.c` `sub_8055390`,
  `sub_8055408`, `sub_8055438`), and the keys callback's lockstep skips the game's callbacks on a
  frame with nothing received. On the ported room, four consoles walking for 600 frames never had
  more than one command queued.
- **CloseLink turns the game's serial off** (`DisableSerial`), and `EnableSerial` loads 0 for the next
  link's first word. As slave, a closed game reads as nobody (0xFFFF) to the DUO. The DUO programs
  counted that as checksum mismatches at every change of link (25 in one DUO-as-master trade).
  Fixed in `trade`, `mix`, `tower`, `colosseum`: a 0xFFFF where the game's checksum is due means its
  link closed, and the DUO waits for the next one. (On hardware, session 29 saw 2 and 0, and session
  25 put "the mismatches after the close" down to the game opening its link again.)
- **A slave game counts VBlanks without a transfer** (`LinkVSync`: more than 10 is a link error).
  As master, the DUO planned its walk round the player without starting a transfer, for 6 frames and
  sometimes more than 10. Fixed in `room_walk.h`: as master it plans a row at a time, so its commands
  go out on time. (The cable as fitted makes the game master, so this is the less common way round.)
- **Order within a frame (`MASTER_ORDER` in `pret_link.py`):** a frame's LinkMain1 dequeues the
  commands finished before this VBlank, and a CloseLink there stops the command just begun after one
  transfer. With that order the DUO sees no mismatch when the game closes as master.
- **The close waits on a sample, not the queue** (17 November, evening): `sub_8008350` sends `0x5FFF`
  only when `gLastRecvQueueCount` is 0, and Ruby's `SerialCB` sets that only when its transfer count
  reaches 8 - each command's eighth transfer as master, once in 256 transfers as slave. Leaving a
  room, the game stops its own keys first (`sub_8081050`); the DUO didn't, so with the DUO as master
  the game could wait on a black screen for good (15 November). The DUO now stops its keys once both
  have left, and the ported link layer samples as the game does.
- **The blender writes `gSendCmd` itself** (`berry_blender.c` `sub_80500A8`), so its game isn't in
  lockstep with the DUO: the DUO's copy of the blend can end a frame or two off the game's own, as the
  game itself allows (it takes the leader's time and RPM). The test now allows it too.

## Still to check

- **The drift in the other programs:** `trade`, `mix`, `colosseum`, `ereader`, `tower` and
  `link_tail.h` set each command's start from when they noticed (`next_cycle = now() +
  LINES_PER_FRAME`), as lab4p did. With the room's own throttle ported, a DUO that falls behind
  makes the game send 27/28 and wait rather than overflow; whether that has anything to do with the
  black screen after the trade on 15 November (parked) is still open.
