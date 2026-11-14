# Virtual DUO

An emulated Action Replay MAX DUO, so the toolkit
(`fredreckless/ActionReplayMaxDuo-Pokemon-Toolkit`) can be rehearsed against a real Pokémon game
running in mGBA instead of hand-written game models. The plan, the standing rules and the build
order are in the handover doc ("Virtual DUO - handover", 11 November 2026).

It lives in the toolkit's repository as `virtual/` (moved in, with its history, on 12 November
2026). Since 13 November the toolkit's own `tests/hwsim.py` is built on this folder's core, so the
toolkit's tests and the emulator share one model of the DUO; the old pure-Python one is kept,
frozen, as `tests/hwsim_python.py` for `check.py`'s comparison. The tests and the emulator need
Linux and a C compiler: on Windows, WSL2. The tool itself, talking to a real DUO, doesn't.

## What's here (build steps 1 to 5)

| Path | What it is |
|---|---|
| `core/duocore.h`, `core/duocore.c` | The shared C core: the DUO's chips as one behavioural model, answering cartridge-bus reads and writes. No knowledge of any emulator. |
| `core/duocore.py` | The core from Python through `ctypes`; builds the library on first use. |
| `tests/hwsim_python.py` | The toolkit's old, pure-Python `hwsim.py`, frozen as it was when the core went behind it, for the comparison. |
| `tests/diff_hwsim.py` | The original `hwsim.py` against the new one, with random bus programs; needs no firmware. |
| `tests/fuzz_core.c` | The core on its own under AddressSanitizer and UBSan, with invariants and link traffic. |
| `tests/test_link.py`, `tests/test_flash.py` | The USB link at register level (with Datel's own send and receive routines transcribed), the Action Replay switch, and the SST flash's command set. |
| `mgba/cart-bus.patch`, `mgba/apply_cart_bus.py` | A small hook in mGBA 0.10.5's cartridge bus (63 lines) so a device can answer it. |
| `mgba/lockstep.patch`, `mgba/apply_lockstep.py` | One correction to mGBA's link cable: a master's START while the others aren't ready still transfers, as on hardware (see below). |
| `runner/build.sh`, `runner/vduo.c`, `runner/vduo.py` | `vduo`: two GBAs in one process on a link cable, one with the DUO in its slot; the DUO's USB on a TCP port; a text control channel driven from Python. |
| `rehearsals/` | Rehearsals against a real game: `trade.py`, `colosseum.py` (single or double), `mix.py`, `event.py`, `blender.py`, `contest.py` and `tower.py`, with `ruby.py`'s helpers (any ROM savegen knows: Ruby, and Emerald and LeafGreen in every language, from the Cable Club menu); `all.sh` runs English Ruby's seven, `all_games.sh` Emerald's ten or LeafGreen's three. |
| `savegen/` | The save generator: a save and the rehearsals' states from a ROM alone, written by the game's own code (`savegen/README.md`). |
| `check.py` | This folder's own check (`--toolkit` adds the toolkit's `check.py full`). |

Nothing of Nintendo's or Datel's is here: the firmware, the game, its save, the DUO's flash image
and any save states are always passed in by path from outside the folder.

## Where the line is drawn

The **core** decides everything the DUO's hardware decides:

- the Actel: the mapping register at 0x0800009C (0x0120 the DUO; 0x0101, 0x0007, 0x0001 the
  game), the header overlay 0x08000020-0x0800009F (zeros, F0 0F at 0x9C, every mode and width),
  the control area 0x09FE0000-0x09FFFFFF (read while the game is mapped: a failure);
- the SST flash: 512 KB, twice below 1 MB, open bus above, its software-ID mode;
- the game in the slot: its ROM chip, open bus above it, and 2-cycle first-access timing
  corrupting its reads;
- the save chips (Sanyo and Macronix 128 KB Flash, 64 KB Flash, 32 KB SRAM, EEPROM, none): their
  command decoders, sleep after every swap-in, wake on any game ROM read, the 8-bit bus, and every
  write that could change a save, reported as a violation;
- the USB chip at register level: LINK_IN 0x09FE01C0 and LINK_OUT 0x09FE01E0 (low byte data, bit 8
  each side's strobe; the GBA acts when the strobes differ, the chip when they agree), eight bytes
  a packet in four rounds, strict alternation, PC packet then GBA packet; so Datel's own routines
  run unaltered;
- the Action Replay switch (LINK_IN bits 13 and 14; 0x09FE0160 reads 0, 0x09FFE140 reads 0xF0A0);
- the SST flash's command set (word program, 4 KB sector, 64 KB block and chip erase), reported
  as `FLASH_CHANGED` so `hwsim.py` can still treat any write to the DUO's own flash as a failure.

The **host** (`hwsim.py`) keeps the CPU (Unicorn), the checks only a simulator can make (which code
wrote the mapping register; IME and WAITCNT at a save read), fault injection (with its own Python
random streams, so a corrupted packet is corrupted identically), the USB queues and their threads,
the BIOS, and the link cable. It keeps Unicorn's copy of the cartridge up to date whenever the core
reports that it reads differently.

Two small differences, neither visible to a passing test: a 16- or 32-bit save read returns the
byte repeated from `duo_read` (as the real chip does), where Unicorn's memory shows the plain bytes;
either way it's recorded as a failure, as before. And `duo_result.cycles` is always 0: the core
doesn't model bus timing yet (build step 6).

## The proof (12 November 2026)

With Datel's 1.06 update built (v4.1 CRC A5303402, v4.2 DD59ED8A, both matching the releases) and
the core in place of the Python models, the toolkit's `python3 tests/check.py full` gave
**202 of 202 tests passed, 146 of 146 planted bugs caught, ALL GOOD**, with no simulator crashes,
both before and after the open-bus cache described below (the second run is the final code).
This folder's own `python3 check.py` passes on the final code as well.

Besides that:

- `tests/diff_hwsim.py` drove the original and new `hwsim.py` through about 1,600 random bus
  programs (some 190,000 operations: mapping swaps, every Flash command sequence and broken ones,
  save and ROM reads at every width, WAITCNT changes, flash ID mode, USB packets from both ends).
  Every byte of the cartridge as the CPU sees it, every value read, every violation, failure and
  its wording, and the USB link's state matched.
- `tests/fuzz_core.c` ran 1.2 million operations through the core under AddressSanitizer and UBSan:
  clean, with its invariants holding.

### A Unicorn fault the comparison found

Long comparison runs crashed now and then inside Unicorn's own memory code (`load_helper` in
`libunicorn.so`, a load from JIT-compiled code, with no core frame on the stack), or a CPU load
returned a wrong value while the memory itself was right. What we learned:

- **It's in Unicorn, and the original has it too.** Some bus programs make the untouched original
  `hwsim.py` crash, or disagree with itself about a value read, with one simulated DUO and no core
  loaded (seed 6, program 2 does it every time). Shrinking the program found no single DUO operation
  responsible: it depends on how much code has run, the mark of a fault in Unicorn's JIT and TLB
  bookkeeping. The toolkit's note that Unicorn crashes after very many DUOs in one process is
  probably the same fault.
- **The first version of the new glue made it much more likely.** It rendered two fresh 31 MB
  buffers for the open-bus space above the cartridge for every simulated DUO; the original built
  that image once and reused it. On one stretch of programs: the original against itself, no
  failures in 8 runs; the new glue, 11 in 28; the new glue rendering the space once per process and
  reusing it (what `hwsim.py` now does), none in 20. The space is identical for every DUO with the
  same span, and the core still renders it, so nothing a test can see changed.
- **The harness had two slips of its own**, both fixed: it built DUOs for programs it then skipped
  (leaving dead Unicorn instances for the collector to free at any moment, even mid-emulation), and
  `DIFF_DUMP` saved the previous program. A Unicorn instance is freed only by Python's cyclic
  collector (checked), so the comparison now collects between programs.
- `diff_hwsim.py --batch N` runs the programs in fresh processes and, when one crashes or the CPU
  misreads, runs the original against itself over the same programs: if the original misbehaves
  too, the program is counted as Unicorn's and skipped; if not, the comparison fails.

Worth remembering for step 2: the hooks that rewrite Unicorn's memory from inside other hooks are
where Unicorn is fragile, and they become thin glue there.

## Steps 3 to 5: Datel's own code, mGBA, and a real game (12 November 2026)

- **Step 3.** With the USB link modelled at register level, `hwsim.py` stopped replacing Datel's
  USB routines; the full tier again gave **202 of 202, 146 of 146, ALL GOOD**, and gave it
  again after the switch, flash and mirror changes of step 4.
- **Step 4.** `vduo` runs the firmware in mGBA. Datel's start-up formats its codes database in
  flash when it is blank, and while it is blank it skips the USB boot check; so the first run is
  kept with `save_flash` and that image is passed as `--duo-fw` from then on (it is Datel's
  firmware plus a formatted database: never commit it). `duo_events.py --virtual` then connects
  ("Datel protocol 1.04, Reckless v4.2"), uploads a program and polls it, and the DUO's screen
  shows USB SERVER MODE.
- **Step 5, the trade.** Against Fred's own Ruby, the DUO linked, both sat down, and the
  game traded its WISHMKR Jirachi for a synthetic test Pokémon and saved (in memory only). The
  .pk3 the toolkit kept is **byte for byte the one the real DUO received on 1 November**
  (PID 7A0DF4BC), and identical in game form to the gallery's WISHMKR file. 49,754 transfers, no
  checksum mismatches. `rehearsals/trade.py` repeats it and passes.
- **Step 5, the Colosseum.** A single battle against the same Ruby, the DUO with the MEW and
  JIRACHI of the 7 November hardware run, playing simply. The battle was played to the end (won
  by the game's side) and the record copied: 177 to 181 commands from the game, 8 choices by the
  DUO, no checksum mismatches. `rehearsals/colosseum.py` repeats it and passes.

Comparing with the hardware's records:

- The 7 November hardware run ended with a USB timeout while copying the record; the toolkit of
  11 November copies records reliably on hardware, and so does the virtual run. Nothing to fix.
- Against the hardware's single battle with Ruby of 11 November (its record of 22:58), the
  virtual record has **the same first 41 entries** in the same order: link player, link type
  0x2233, the 100-byte exchange, the "ready" barrier, the DUO sitting down, link closing 0x5FFF,
  link type 0x2211, both battle headers, three party blocks, GETMONDATA, INTROSLIDE,
  DRAWTRAINERPIC, the party summaries, and so on to the first CHOOSEACTION. From there the order
  depends on who answers first, which a person's thinking time decides; the length depends on
  the moves chosen. Every kind of battle command the virtual battle saw, the hardware saw, and
  the hardware's only extras (STATUSANIMATION, STATUSICONUPDATE) came from a status condition.
- The tool's progress lines skip some phases ("on a spot", "the battle's link is opening",
  "back in the Colosseum"), because the emulator runs several times faster than real time and
  a phase can begin and end between two of the tool's polls; the record shows they happened.
- In the trade, once the DUO has left, the game ends the session itself and puts the player back
  in front of the attendant: there is nothing to walk out of.

## More rehearsals: double battle, Record Mixing, Mystery Event, Berry Blender (12 November 2026)

Contest and the Battle Tower need Emerald, which isn't here yet; everything Ruby can do is.

- **Double battle.** Played to the end, record copied, no checksum mismatches. Against the
  hardware's double battle with Ruby (11 November, the run of 23:02) the first **74 entries** match; from
  the first choice they part, because there the PC chose for the DUO and here it played simply.
  The same kinds of battle command on both.
- **Record Mixing**, with the inputs of the 7 November hardware run (WILLOW's base, the Bard's
  song, the AWESOME BATTLE trend). The game mixed and saved, as on hardware, with no checksum
  mismatches; and since the emulator's save is ours to read, the save afterwards was checked:
  the toolkit's `bases` finds WILLOW's base in it, and the old man's song and the trend are in
  it **byte for byte**.
- **Mystery Event** (the UK Eon Ticket) from the title menu. The game took it, closed the link,
  ran it and saved; the whole .me3 is in the save byte for byte (a saved event is the game's own
  stored form). On hardware the same event reached Ruby in lab session 26.
- **Berry Blender**, both ways round. The game's player presses A as its own arrow passes the top
  (read from the blender's state in RAM, a frame ahead), so it scores mostly "best" hits like a
  practised player instead of mashing (14 November). It also found two toolkit bugs that **the hardware logs
  show too** (11 November, 23:26 and 23:30), so the emulator copies them faithfully:
  - with the DUO on the child's end, the live line says "Blend 3 done" after one blend: the
    program counts a blend for every copy of the leader's verdict, and the game sends three
    (`blender.c`, `blends++` on each LEADER_STOP/LEADER_GO);
  - with the DUO leading, the summary's "Best speed 498.53 RPM in 893801:51" (here, 524.15 RPM in
    907546:12) is the game's berry block read as the leader's block, since the leader's block is
    then the DUO's own and never arrives (`blender_blends`): bytes 0-3 and 4-5 of
    `87 00 ca bf bd c2` are exactly those numbers. The Pokeblock it predicts is wrong with them;
    what the game made is not affected.
  - (Small: the live hit counts are 8 bits, so a player who presses A hundreds of times sees
    them wrap; the summary afterwards is right.)

### The link correction

The DUO on the master's end didn't link at first: mGBA 0.10.5 ignores a multiplayer master's
START while SD ("all GBAs ready") is low but leaves the bit set, so the master looks busy for ever.
The DUO's programs start a transfer every frame until the game answers, and on the real DUO they
link from either end (the hardware blender run of 23:30 had the DUO as player 0). Real hardware
runs the transfer anyway, with FFFFh from every GBA not taking part (GBATEK). `apply_lockstep.py`
makes mGBA do that; Pokemon games check SD before starting, which is why mGBA's own links never
met the case.

### The comparison harness, brought up to date

This folder's `check.py` had stopped passing since steps 3 and 4, and nobody had noticed because
the toolkit's full tier was the check being run. The core was fine: the harness was out of date
in three places, all now fixed, and `check.py` again gives **IDENTICAL: 200 programs, ALL GOOD**.

- Its random firmware had nothing at Datel's SEND8 (0x0800C29C), which the new `hwsim.py` now
  runs instead of replacing it with Python: it carries a Thumb SEND8 now, as `test_link.py`
  transcribes it, reading a waiting PC packet first as Datel does.
- It wrote loose flash-ID commands (a lone 0x9090 to 0x5554) that only the original accepted;
  it now sends the SST chip's real AA/55/90 and F0, and as its deliberate mistakes, writes both
  reject.
- It read the control area for its own snapshot after taking the failures and the save chip's
  state: with the control area MMIO, that read reached the core like a CPU read. The state is
  taken first now.

## Using it

From the repository's top folder:

```
python3 virtual/check.py              # build, fuzz, compare (no firmware needed)
python3 virtual/check.py --toolkit    # and the full tier with the core behind hwsim.py (needs the firmware built)
virtual/runner/build.sh               # fetch mGBA 0.10.5, patch it, build it and vduo
python3 virtual/runner/prepare_flash.py   # once, after the firmware build: the DUO's formatted flash
```

`prepare_flash.py` boots the freshly built v4.2 once, lets Datel's start-up format its codes
database, and keeps the result as `firmware/build/duo_flash.bin` (git-ignored: it is Datel's
firmware). That image is what `--duo-fw` and the rehearsals' `--duo-flash` take.

A rehearsal needs a save state of the game standing at the attendant's question (made once with
`vduo.py`'s `state_save`), the game and its save, and the formatted flash image:

```
python3 virtual/rehearsals/colosseum.py --rom RUBY.gba --sav RUBY.sav --duo-flash duo_flash.bin \
    --state at_colosseum_question.state --pk3 A.pk3 B.pk3 --out /tmp/colo
```

With the patch applied, `hwsim.py` finds the core in `virtual/core`, or wherever
`VIRTUAL_DUO_CORE` points. On Windows the core needs a C compiler once (MSYS2's gcc, or clang), or
`DUOCORE_LIB` pointing at a built `duocore.dll`.

## Licence

The toolkit's MIT licence, except `mgba/`: those patches change mGBA's own files, so they (and the
scripts that make them) are under mGBA's licence, the Mozilla Public License 2.0. mGBA itself is
fetched by `runner/build.sh`, never copied in.
