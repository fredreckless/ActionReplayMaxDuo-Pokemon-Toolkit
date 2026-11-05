# Session 31: trades into Emerald and LeafGreen, four at a sitting; the Record Corner stops at the door (5 November 2026)

**Set-up.** Reckless v4.2; `duo_events.py` as on `main` on 5 November (the PC's copy). GBA link
cable as fitted (the game on the master end; the DUO came up as player 1 for the trades and as
either player for Record Mixing, see below). English Ruby (AXVE, revision 1), Japanese Emerald,
English LeafGreen (BPGE, revision 1).

**1. Trainer Hill (Japanese Emerald): Black Belt Kousei appeared.** The one-card set from session 30
was used by the game. Devin (session 30's e-Card) was also confirmed in Mossdeep on Ruby.

**2. Trade into Japanese Emerald: works.**
- `trade --pk3` with a Japanese ネガイボシ (Wishing Star) Jirachi.
- The tool named the game correctly ("Japanese Emerald, National Pokedex"); walk, seat, parties,
  trade, save, back to the room and out of the door all clean. 48,515 transfers, 0 mismatches.
- Emerald's Cable Club is the right-hand attendant upstairs (the Direct Corner; with the cable, it
  offers Trade Center, Colosseum and, after Mauville, Record Corner).

**3. Trade into English LeafGreen: works.**
- The Aura Mew (fateful-encounter mark); the tool said "English LeafGreen, no National Pokedex".
  Traded and saved.
- **On the way out the player stood in the DUO's path.** The DUO's character couldn't reach the
  door; the game said the link was closing and the screen went black. The tool waited at
  "leaving the room" until stopped. To do: the DUO should follow where the player is (it sees
  every player's keys) and only ask to leave from the door.

**4. Several in one sitting (LeafGreen): works.**
- Four files offered (Aura Mew, then the 10th Anniversary Pikachu, Charizard and Articuno).
  Trade 1 and trade 2 went through and saved; at the third the player chose CANCEL, and the DUO
  left the room cleanly. "2 of the 4 event Pokemon", 75,966 transfers, 0 mismatches.
- Both received Pokémon were kept in `received\`, each named after the event Pokémon it was
  traded for.

**5. Record Mixing with English Ruby: the game's screen goes black entering the Record Corner.**
- Three runs: a base (`--base`) with the DUO as player 1, the same with the DUO as player 0, and
  `--gift "Eon Ticket"` with no bases (player 0).
- Each time the link came up as English Ruby and the tool printed "in the Record Corner", which
  only means the attendant's link (0x3311) is up. Then, as the game warped into the room, the
  screen stayed black with the music playing: the game was waiting for something. The tool showed
  nothing more until stopped.
- So nothing was mixed and the save is unchanged after the attendant's own save. A read-only save
  backup was taken beforehand.
- To do: find what the room's loading waits for (compare `mix.c` with `trade.c`, which gets past
  the same warp, and with pokeruby's Record Corner entry), make the model fail in the same way
  first, then fix. The tool should also report the program's state when nothing changes for a
  while, rather than wait silently.

**6. Other things seen.**
- `duo_rom.py` on LeafGreen: it went ahead although FireRed/LeafGreen have no Secret Bases, read
  the size as 31.9 MB (the cartridge is 16 MB), and estimated about 20 hours (the first 64 KB took
  over two minutes). Stopped. To do: refuse games the workshop can't use, before reading; fix the
  size; and make it practical (see the plan in the handover).
- `duo_events.py base make bases\Willow.txt` made `WILLOW - Tree 1, Route 121 (ENG).sb3`.
- The DUO's trainer card (name, ID and gender only) was looked at in LeafGreen; the user asked
  whether it should carry more.
