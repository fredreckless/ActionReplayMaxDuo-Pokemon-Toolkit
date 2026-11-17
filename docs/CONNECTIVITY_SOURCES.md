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
  `tests/pret_link.py` (link.c's serial layer).
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
| Link commands: `0x2222` link players, `0xBBBB`/`0x8888` blocks, `0xCCCC` block requests, `0x5FFF` close, `0x2FFE` ready | pokeruby `link.c` `ProcessRecvCmds`, `BuildSendCmd`, block send | written into each model separately | from source, **duplicated**: port next |
| Cable Club link-up, trainer cards, the room's lockstep keys (`0xCAFE`) | `cable_club.c`, `overworld.c`, `data/scripts/cable_club.inc` | trade, mix, battle, tower, blender, contest models, and `gp_link_model`, each its own copy | from source, **duplicated**: port next |
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
| Four players on a two-player cable (`lab4p`) | R/S | `link.c` (above) | `gp_link_model.py` | link layer **ported**; Trade Center flow duplicated; lines hardware |

## Next, in order

1. Port link.c's commands (`ProcessRecvCmds`, `BuildSendCmd`, blocks) into `pret_link.py`, and
   replace each model's copy.
2. Port the Cable Club flow (`cable_club.c` link-up tasks, `overworld.c` link-room keys) once into
   `tests/pret_cable_club.py`, and replace the six copies.
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
  transfers. With the game queueing a command every frame in the Trade Center room, lab4p's pacing,
  which drifted later each frame, let the game's queue fill: a link error after a while. lab4p now
  keeps to its schedule.

## To check once the Cable Club flow is ported

- **The same drift in the other programs:** `trade`, `mix`, `colosseum`, `ereader`, `tower` and
  `link_tail.h` set each command's start from when they noticed (`next_cycle = now() + LINES_PER_FRAME`),
  as lab4p did. In a room the game queues a key command every frame, so a DUO that falls behind lets
  its queue fill. Trades work on hardware, so nothing is changed on a hunch. The faithful room port
  (with DequeueRecvCmds one a frame, not at once) will show whether a long session fills it, and
  whether it has anything to do with the black screen after the trade on 15 November (parked).
