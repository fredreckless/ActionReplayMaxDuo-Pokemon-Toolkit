# Four players: a wide look at the ways in, and which to take (19 November)

**Where we are.** On the GBA link cable each unit's serial hardware sends exactly one 16-bit slot per
transfer. With the game and the DUO alone, slots 2 and 3 are empty, so the game counts two players.
The lab program tried to fill them by driving the data line (SD) by hand, bit by bit in
general-purpose mode: over 2,353 tries and twelve timings (17 November) the game's link chip read
every hand-sent word as **garbage** - never as empty, never as read - while reading the DUO's own
link hardware every time. Earlier, as player 0, the hand-sent handshake was never taken either
(docs/HARDWARE_QUEUE.md, 12a-12h). So hand-sent words fail in general, not only in slots 2 and 3.

Fred asked for a wide look. Here are the approaches, each judged on what it needs, what we know, and
how likely it is to work.

## The approaches

| # | Approach | Needs | What we know | Verdict |
|---|---|---|---|---|
| 1 | **Virtual players over wireless.** In Emerald and FireRed/LeafGreen the groups are wireless: the DUO already *is* the Wireless Adapter, so it can be the adapter *and* every other player in software. No physical slots: the game's adapter talks to "children" that exist only in the DUO's program | Nothing new: the MGB-010 cable and the work already done (hosting, link_rfu_2's command table for up to 5 players, blocks, the Union Room and Direct Corner plumbing) | The groups' capacities (pret:pokeemerald/src/data/union_room.h:640 sLinkGroupToActivityAndCapacity): the multi battle 4, Record Corner 2-4, Berry Blender 2-4, the four Contest groups 2-4 (Emerald), Berry Crush and Pokemon Jump 2-5, Dodrio Berry Picking 3-5. link_rfu_2's table has a row per player; the DUO fills the extra rows | **The most promising, by far** - for Emerald and FireRed/LeafGreen. It sidesteps the cable's physics altogether |
| 2 | **Helper GBAs, multibooted from the DUO.** Every slot sent by real link hardware: a third and fourth GBA, with no cartridge, boot a small program from the DUO over the cable (Nintendo's multiboot, docs/MULTIBOOT.md path A) and each plays one more player - our own partner program, running from RAM as the DUO's do | Two more GBAs and a four-player cable chain (AGB-005 cables plug into each other's hub socket) | All the game ever accepted was link hardware; each helper's word would be. The helper follows the link like any player (it hears every slot); its role and team go in its program before sending | **Very likely to work** - the route for **Ruby/Sapphire**, which have no wireless (their link Contest needs four) |
| 3 | **A checksum oracle: what does the game actually read?** In link.c each player's checksum covers every slot it received. Sending known test words by hand (0x0000, 0xFFFF, 0x5555, 0x0001, ...) and reading the game's checksum back tells exactly what its chip decoded - a shifted bit, an inverted one, a lost stop bit | One GBA and the cable as fitted; a lab program | The 16 November hybrid already saw checksums part by xor 0x0002 and 0x22E9; a designed set of words would turn "garbage" into a rule | **Cheap, and the right next experiment** for the cable: it says whether hand-sent words can ever be fixed |
| 4 | **Re-arm the DUO's own link hardware for slots 2 and 3.** As player 0, after the game's slot, restart the DUO's multi-player transfer with the next word, so its hardware - not the CPU - drives the start bit and data | The cable as fitted | Unknown whether re-arming lifts SC (ending the transfer for the game) - GBATEK says the master holds SC low during a transfer | **Worth one lab run** after 3: the waveform would be the hardware's own |
| 5 | **A small external microcontroller** (e.g. an RP2040's programmable I/O) on the cable as players 2 and 3, the PC telling it what to send | About £5 of hardware and a cable breakout | Its timing is exact to the cycle and it can copy the real hardware's waveform measured first | **Would work**, but it isn't the DUO alone |
| 6 | UART mode to make the frames | - | A UART frame is start + 7 or 8 bits + stop; a multi-player word is start + 16 + stop. Two UART bytes put a stop and start bit in the middle | Ruled out |
| 7 | Normal (SPI) mode | - | Its data leaves on SO, not SD, the multi-player data line | Ruled out with a standard cable |
| 8 | The DUO on the slave end | - | Its hardware sends slot 1; slots 2 and 3 would still be by hand | No better than today |
| 9 | Fewer than four where the game allows | - | Record Mixing and the Blender already work with two; Ruby/Sapphire's link Contest needs exactly four (link type 0x6601) | Not a solution for four-only features |

## What I'd do, in order

1. **Wireless virtual players (1)** as part of the Direct Corner work: once the Trade Center works with
   the DUO as leader, a group of three or four with the extra players virtual - starting with the
   Record Corner (records from the PC for each virtual player), then Emerald's four-player Contest and
   Blender, the multi battle, Berry Crush and the minigames. In the simulator first, from the source.
2. **The checksum oracle (3)** on the cable, one short lab run: a definite answer on hand-sent words.
3. **Helper GBAs (2)** for Ruby/Sapphire's four-player link Contest, once multiboot (docs/MULTIBOOT.md
   path A) works - if Fred has two spare GBAs and cables. **Step one done (19 November, simulator):**
   the DUO now sends a multiboot program exactly as Emerald's Berry Fix screen does, and Nintendo's
   library sends to up to three GBAs at once (`client_bit` bits 1-3) - shown in the simulator too
   (check-in 2: three receiving GBAs behind the DUO, each booted from one transfer; the tool says how
   many answered). Next: test that on hardware, then write the helper itself (a partner program built for 0x02000000, which joins the link
   as player 2 or 3 and takes its team and role from its own data) and model three GBAs in hwsim.
4. (4) and (5) only if 2 and 3 leave a gap.

## The helper program, as designed (19 November, check-in 2)

What a helper GBA would run, so the work can be judged before it's started:

- **Built like the DUO's programs, linked for 0x02000000** with a multiboot header of our own (our own
  title and game code, no Nintendo bytes in the repository: the logo is copied from the sending
  file's header at send time, which comes from the user's ROM). Entry at 0x020000C0.
- **No PC behind it:** its part (link player, team, record, choices) travels in the program image,
  filled in by the PC just before sending, so each of the three helpers can carry a different player.
- **The link layer from `link_core.h`/`link_tail.h`** (the same code the DUO's routines use, checked
  against pret's link.c), as a child: its own link hardware sends its slot, so the game sees a real
  GBA in slots 2 and 3 - the one thing the hand-sent words never achieved.
- **First routine: the Record Corner with four players**, because mixing is passive (records in,
  records out) and the DUO already plays it; then Ruby/Sapphire's four-player link Contest.
- **Simulator first:** hwsim now carries three children behind the DUO, so a game model with four
  players (pret's link.c already counts them in DoHandshake) can test the helpers before any hardware.

## What a four-player link asks of each GBA (19 November, check-in 4: notes for the game model)

From `pret:pokeemerald/src/link.c:2181 DoHandshake`, the rule a four-player model has to follow:

- Every handshake frame the game reads all four slots. Counting from slot 0, each slot must hold
  MASTER_HANDSHAKE (slot 0) or SLAVE_HANDSHAKE (0xB9A0, low two bits free); the first 0xFFFF ends the
  count, and **anything else sets the count to 0** - which is exactly what hand-sent words did on
  hardware. The link opens only when the master is in slot 0 and the count is the same as the frame
  before (`sHandshakePlayerCount`). So each helper must be a real link chip answering 0xB9A0 in its
  own slot from the very first handshake: a multibooted GBA running link_core.h's slave code.
- After that the game exchanges its normal command/data words in every slot each frame; a helper
  that falls silent for a frame shows up as 0xFFFF and the game drops the link (`CheckErrorStatus`).
- The model's plan: first Python stand-ins for the helpers in hwsim's three child slots (cheap,
  tests the DUO side and a four-player game model built from link.c); only then a real helper image
  run in a second emulated CPU.
