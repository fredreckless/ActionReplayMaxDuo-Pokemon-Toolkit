# Virtual DUO

An emulated Action Replay MAX DUO, so the toolkit
(`fredreckless/ActionReplayMaxDuo-Pokemon-Toolkit`) can be rehearsed against a real Pokémon game
running in mGBA instead of hand-written game models. The plan, the standing rules and the build
order are in the handover doc ("Virtual DUO - handover", 11 November 2026).

This is a local folder, kept beside the toolkit's clone. It has no GitHub repository, and gets one
only when Fred asks.

## What's here (build step 1)

| Path | What it is |
|---|---|
| `core/duocore.h`, `core/duocore.c` | The shared C core: the DUO's three chips as one behavioural model, answering cartridge-bus reads and writes. No knowledge of any emulator. |
| `core/duocore.py` | The core from Python through `ctypes`; builds the library on first use. |
| `toolkit/hwsim.patch` | The change to the toolkit's `tests/hwsim.py` that puts the core behind it. Not applied to the toolkit's repository: that's still Fred's decision. |
| `tests/diff_hwsim.py` | The original `hwsim.py` against the new one, with random bus programs; needs no firmware. |
| `tests/fuzz_core.c` | The core on its own under AddressSanitizer and UBSan, with invariants. |
| `check.py` | This folder's own check (`--toolkit` adds the toolkit's `check.py full`). |

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
- the USB chip: strict alternation, PC packet then GBA packet.

The **host** (`hwsim.py`) keeps the CPU (Unicorn), the checks only a simulator can make (which code
wrote the mapping register; IME and WAITCNT at a save read), fault injection (with its own Python
random streams, so a corrupted packet is corrupted identically), the USB queues and their threads,
the BIOS, and the link cable. It keeps Unicorn's copy of the cartridge up to date whenever the core
reports that it reads differently.

Two small differences, neither visible to a passing test: a 16- or 32-bit save read returns the
byte repeated from `duo_read` (as the real chip does), where Unicorn's memory shows the plain bytes;
either way it's recorded as a failure, as before. And `duo_result.cycles` is always 0: the core
doesn't model bus timing yet (build step 6).

## Using it

```
python3 check.py                      # build, fuzz, compare (no firmware needed)
python3 check.py --toolkit            # and the toolkit's full tier (needs the firmware built)
```

`hwsim.py` finds the core in `../virtual-duo/core` beside the toolkit, or wherever
`VIRTUAL_DUO_CORE` points. On Windows the core needs a C compiler once (MSYS2's gcc, or clang), or
`DUOCORE_LIB` pointing at a built `duocore.dll`.
