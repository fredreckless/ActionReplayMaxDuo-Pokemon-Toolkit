# Multiboot: what the Gen 3 games use it for, and what the DUO could do (plan, 19 November)

**The rule for this one (Fred, 18 November):** only if the DUO does it exactly the way the original
hardware did - no guessing. So every step below names its primary source (pret's decompilation of the
games, which includes Nintendo's own multiboot library, and GBATEK), and anything those don't settle
is marked as needing a measurement before it's built.

**Status (19 November, night): path A is built and passes in the simulator; hardware next.**
`python duo_events.py multiboot FILE --send` (or `--from-rom EMERALD.gba --send` for the Berry Fix,
taken from the user's own ROM) sends a program the way Emerald's Berry Fix screen does:
`firmware/programs/mbsend.c` is pret's multiboot.c function for function (each cited and checked by
tests/source_anchors.py), driven as berry_fix_program.c drives it (once a frame; started after one GBA
has answered steadily for 180 frames; palette colour 4, speed 1), and the transfer is the DUO's own BIOS
(SWI 25h with r1 = 1, as pokefirered's libagbsyscall.s calls it). In the simulator the receiving GBA
(`tests/multiboot_model.py`) answers as GBATEK's table says, and hwsim stands in for SWI 25h; on hardware
both are the real BIOS. Two details GBATEK leaves open (the byte order inside its `dword(pp,cc,cc,cc)`,
and which 16-bit half goes first) are only in the simulator's stand-in, never in our code on the cable.
The last handshake after the transfer is answered by the received program itself; the model gives the
only answers the library accepts (each word echoed, then the program's game code).

## Where multiboot appears in the five games and their events

1. **Link-cable multiboot, GBA to GBA (Normal or Multi-Player mode).** The sending GBA runs Nintendo's
   multiboot library: a handshake written in C, then the BIOS's own transfer, SWI 25h
   (pret:pokeemerald/src/multiboot.c: `MultiBootInit`, `MultiBootMain` - which calls the BIOS `MultiBoot`
   at line 228 - `MultiBootStartMaster`; the same file in pokefirered). The receiving GBA needs no
   cartridge, or one held with START and SELECT at power-on (GBATEK, "BIOS Multi Boot"):
   - **The Berry Fix sender in Emerald and FireRed/LeafGreen.** Emerald's title screen with B and SELECT
     held (pret:pokeemerald/src/title_screen.c:799) opens `CB2_InitBerryFixProgram`, which sends
     `gMultiBootProgram_BerryGlitchFix` (0x3BF4 bytes) to a Ruby or Sapphire GBA
     (pret:pokeemerald/src/berry_fix_program.c:231). That program repairs Ruby/Sapphire's berry-growth
     clock bug in the cartridge's save. Nintendo also gave out a shiny Zigzagoon with it
     (docs/PK3_EVENTS.md).
   - **Event distribution cartridges** - the Aura Mew family, 10th Anniversary, Top 10 - about 500 of
     the gallery's event Pokemon (docs/PK3_EVENTS.md): the player's GBA boots holding START and SELECT,
     receives a program, and the program puts the Pokemon in the party and saves. Their programs aren't
     in pret; the route is documented by the cartridges' dumpers (sources in PK3_EVENTS.md).
2. **GameCube to GBA over the JOY bus.** Every main game carries the receiving end: when a GameCube
   resets the link during the intro, the game hands over to `libgcnmultiboot`
   (pret:pokeemerald/src/libgcnmultiboot.s; also pokeruby and pokefirered), which takes a program from
   the GameCube and runs it. Colosseum, XD, Pokemon Box and Pokemon Channel use this (for example the
   Colosseum bonus disc's Jirachi, written into the save by the program it sends). GBATEK: in JOY bus
   mode **the GBA is always the slave**; it can't send commands, and **the bit timing is not known**.
   Emerald's side in detail (19 November): at the copyright screen it runs `GameCubeMultiBoot_Main`
   each frame; if a GameCube boots it and the loaded header's game code is Colosseum's, it copies its
   *own* 0x28000-byte copy of Colosseum's GBA program into EWRAM and runs that
   (pret:pokeemerald/src/intro.c:1127 if (*(u32 *)(EWRAM_START + 0xAC) == COLOSSEUM_GAME_CODE)). So the
   GBA side of "Colosseum's multiboot" is entirely in the game; what's missing is a JOY bus host, which
   the DUO's GBA can't be with its link hardware (path C).
3. **Not multiboot:** Japanese Emerald and FireRed/LeafGreen send the e-Reader a program of their own
   over an ordinary 32-bit link (`EReader_Load`); the DUO already answers that route (docs/EREADER.md).

## What the DUO could do, and how sure each is

| Path | What | Source for every step | Status |
|---|---|---|---|
| **A. The DUO sends a link-cable multiboot** | The DUO's GBA plays Emerald's Berry Fix sender (or a distribution cartridge): Nintendo's handshake, then the DUO's own BIOS SWI 25h - the very routine the original cartridges called | pret multiboot.c (Nintendo's library, line by line) and the DUO GBA's own BIOS; GBATEK for the parameter block (4Ch bytes, transfer modes 0/1/2) | **Built (simulator), 19 November.** Can be done with no guessing. The program sent must come from the user's own dump (Emerald/FireRed/LeafGreen ROM for the Berry Fix; a distribution cartridge's dump for an event) - nothing Nintendo-made goes in the repository |
| **B. The DUO receives a link-cable multiboot** | The DUO's GBA plays the receiving GBA, keeping what Emerald's Berry Fix screen sends (so the PC has the program without a ROM dump) | The receiving side is the BIOS of the *other* GBA, not in pret; GBATEK documents its handshake (6200/720x, 610y, 60xx header, 62/63/64 info, llll 73rr, 0065/0074/0075) and the encryption (Normal: c=C387h, x=C37Bh, k=43202F2Fh; Multi-Player: c=FFF8h, x=A517h, k=6465646Fh; m = 6F646573h*m + 1) | Possible from GBATEK, checked against pret's sending side in the simulator first |
| **C. The DUO plays a GameCube** | Sending a GameCube program (Colosseum bonus disc, Channel) to a game at its intro | The game's receiver is in pret (libgcnmultiboot); the GameCube's *wire timing* is not in GBATEK ("unknown"), and the GBA's hardware can't be the JOY bus master, so the DUO would have to drive the line by hand (general-purpose mode) | **Blocked by the rule:** it would be a guess until measured. The safe first step: the DUO's GBA in JOY bus mode is a genuine slave, so with a real GameCube it could *receive* and record a GameCube's program and timing - read-only - and only then could anything be sent |

## Safety

The programs in A and C write the receiving cartridge's save: that's what they were for (the Berry Fix
repairs it; the event programs add a Pokemon). That's the original route, but it's still a save written
outside the game's own menus, so the tool refuses without an explicit option (`--send`), says first
which program it will send, and tells the user to back up that cartridge's save beforehand
(`maxduo_saves.py`). The DUO's own code never writes a save: it only passes on the original program.
Until the user asks to go ahead, docs/PK3_EVENTS.md's decision stands (event Pokemon by trade, the
nearest route).

## A fourth player? (19 November)

The library sends to up to three GBAs at once (`MULTIBOOT_NCHILD` 3: `client_bit` bits 1-3), as the
Berry Fix could. That is the way four GBAs on a four-player cable could all run something of the DUO's
choosing - see docs/FOUR_PLAYERS.md, approach 2.

## Plan, in order

1. **Simulator first.** Port `multiboot.c`'s handshake (with citations) as the sending game's model,
   and write the receiving BIOS's side from GBATEK as a second model; make them agree on a test
   program (made up, not Nintendo's). This gives both ends to test the DUO against.
2. **Path A on the DUO:** a `multiboot` program: the handshake as multiboot.c, then SWI 25h with the
   parameter block as the library fills it. The PC side takes the program from the user's ROM dump
   (the Berry Fix: found by its multiboot header in an Emerald, FireRed or LeafGreen ROM) and checks
   it before sending. Hardware test: a Ruby/Sapphire GBA held with START+SELECT at power-on.
3. **Path B** (receiving), if wanted: capture what a real Emerald sends, to compare with the dump.
4. **Path C:** only after a GameCube capture shows the timing; the DUO's GBA would record a GameCube in
   JOY bus mode first (a real GameCube and its GBA cable needed).
