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
   library sends to up to three GBAs at once (`client_bit` bits 1-3). Next: test that on hardware with
   one GBA, then write the helper itself (a partner program built for 0x02000000, which joins the link
   as player 2 or 3 and takes its team and role from its own data) and model three GBAs in hwsim.
4. (4) and (5) only if 2 and 3 leave a gap.
