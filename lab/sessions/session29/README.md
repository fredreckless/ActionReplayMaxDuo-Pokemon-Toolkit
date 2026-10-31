# Session 29: the first trade, and why Devin never arrived (31 October 2026, late evening)

**Set-up.** `duo_events.py` at commit 00dc344 (the Cable Club link type fixed), Reckless v4.2.
English Ruby (the cartridge reports AXVE, revision 1) on the GBA link cable.

**1. The Devin e-Card, twice.**
- Both runs: 212 bytes, link up as player 1, link type 0x5501, "sent the Mystery Event", the game
  closed the link; 1,593 and 879 transfers, **0 mismatches**.
- In the game: "the event was safely loaded", then in Mossdeep the door still locked.
- **A read-only save backup** (`maxduo_saves.py --gba-save`, 14/14 sections valid), taken after
  both runs: the e-Reader trainer slot (SaveBlock2 + 0x498, 188 bytes) is **all zeros**, and the
  trainer's name appears nowhere in the save.
- **Why** (pokeruby `link.c`): a received block goes to the shared buffer `gSharedMem` only if it
  is over 256 bytes (`BLOCK_BUFFER_SIZE`); smaller ones land in `gBlockRecvBuffer`. The MYSTERY
  EVENT menu runs `gSharedMem`, which it had cleared after the last event: the first byte isn't a
  command the script engine accepts as valid, so it stops with status 0 ("loaded OK") and saves,
  having done nothing. The Drash Berry (1,352 bytes) and the wrapped `.me3`/`.ecb` files were all
  big enough, which is why they worked.
- **Fixed:** every event now goes as the full 2,004-byte buffer, the script then zeros. The model
  of Ruby's link layer now applies the 256-byte rule, so the old behaviour fails the tests.

**2. The trade: it works.**
- `trade --pk3` with the WISHMKR Jirachi, twice. Every stage reported: linked at 27.9 s, "in the
  Trade Center (the DUO is player 1; English)", walking, seated, parties, the menu, "you said yes:
  trading", the scene, saving at 89.6 s, "traded and saved" at 98.0 s, leaving, done.
- Ruby received Jirachi and saved; the DUO kept what it was given (a WURMPLE, then a POOCHYENA)
  as `.pk3` files. Checksum mismatches: 2 in the first run, 0 in the second.
- **But leaving froze the game:** after CANCEL, Ruby goes back to the room over a new link
  (0x1111) and the DUO had already stopped, so the game hit its 300-frame link timeout. The user
  noted that the DUO's character should walk back and leave.
- **Fixed in the simulator:** the DUO now answers the room's new link, walks back to the door,
  presses DOWN there and sends the exit key (23); if the player leaves first, it follows at once.
  See docs/TRADE.md.
- The second run printed "no trade this time" while leaving (the game's 0xEECC after the DUO's
  CANCEL); after a trade it now says "leaving the trade screen".

**3. Requests from the user, done.**
- Received Pokémon are kept in a `received` folder beside the tools, not inside EventsGallery,
  named e.g. `2026-10-31 224603 WURMPLE (for JIRACHI).pk3`. (The two from this session are still in
  `EventsGallery\...\WSHMKR Jirachi\received\`; move them by hand if you like.)
- **Lines on the DUO's screen** for the trade and e-Reader programs, shown only between link
  sessions (a line costs over a frame).
