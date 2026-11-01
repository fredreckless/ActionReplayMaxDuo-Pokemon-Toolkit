# Session 30: Devin arrives, a clean trade, the first Trainer Hill card (1 November 2026)

**Set-up.** `duo_events.py` at commit afe48e4 (copied to the PC and checked by SHA-1), Reckless
v4.2. GBA link cable as fitted (the game on the master end). English Ruby (AXVE, revision 1) and
Japanese Emerald.

**1. The Devin e-Card (USA) on Ruby: works.**
- Sent as the full 2,004-byte buffer; link up as player 1, link type 0x5501; "sent the Mystery
  Event", the game closed the link; 2,159 transfers, 0 mismatches.
- Ruby: "a new trainer has arrived in Hoenn"; Devin was in Mossdeep.
- **The two save backups compared** (read-only, before and after): the e-Reader trainer slot
  (SaveBlock2 + 0x498) went from all zeros to **exactly the card's 188-byte trainer**, checksum
  valid. Session 29's diagnosis confirmed: short events never reached Ruby's shared buffer.
- The "longest look away" read 145 scanlines: the new screen line, drawn after the game had
  closed the link. Now left out of the figure.

**2. A trade on Ruby, through to leaving: perfect.**
- Every stage reported, including the new ones: "back to the Trade Center", "back in the room",
  "walking back to the door", "leaving the room", "done". No freeze. 45,355 transfers, 0
  mismatches.
- What Ruby gave was kept in `received\` beside the tools, named "(for JIRACHI)".
- (A first attempt was stopped by hand while waiting for the game.)

**3. A Trainer Hill e-Card on Japanese Emerald: received.**
- `19-A001 E - Black Belt Kousei (JPN).raw`, sent as a one-trainer set (3,792 bytes); link up as
  player 1, **link type 0x5503**, Japanese; the set sent, then **the game closed the link**
  (it closes after checking the set); 3,863 transfers, 0 mismatches.
- The Trainer Hill itself is still to visit.
