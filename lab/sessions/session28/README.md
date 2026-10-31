# Session 28: berries, tickets, a trainer and the first trade (31 October 2026, evening)

**Set-up.**
- `duo_events.py` at commit e2ebe62, Reckless v4.2. The user's games are all European English,
  except Emerald, which is Japanese.
- Part 1 on the GBA link cable (Ruby); part 2 on the MGB-010 (LeafGreen, Japanese Emerald).

**Part 1: the GBA link cable, English Ruby.**

| Run | What the trace showed | In the game |
|---|---|---|
| `event` Cool Trainer Devin (USA) `.raw` | 212-byte script (checkcompat addtrainer end), link up as player 1, link type 0x5501, sent, closed; 1,354 transfers, 0 mismatches | **Mossdeep: the old man's default greeting and the door locked**, so `ValidateEReaderTrainer` found no valid trainer |
| `event` Drash Berry (USA) `.raw` | 1,352 bytes (checkcompat setenigmaberry end), 0 mismatches | "PUMKIN BERRY transformed into DRASH BERRY": **e-Card berries work** |
| `event` Cool Trainer Devin (JPN) `.raw` | the Japanese-card warning shown; sent, 0 mismatches | nothing in Mossdeep, as expected (an English game refuses a Japanese card) |
| `trade --pk3` WISHMKR Jirachi | "linked" at 42.6 s, then nothing more; stopped by hand | the room reached, the DUO's character **stood still at the door**; its trainer card showed WISHMKR, 00:00 and $0 |

**Part 2: the MGB-010, Mystery Gift.**
- English LeafGreen, the English MysticTicket (US) `.wc3`: received, as the trace and the game
  showed (the US card works on a European game).
- English LeafGreen, `gift --card` with the Eon Ticket `.me3`: refused ("not a .wc3"), but the tool
  went on, and the game found nothing to receive. Now `gift` turns a `.me3` away before anything
  starts and gives the `event` command instead.
- English LeafGreen, the Japanese Aurora Ticket 2004 `.wc3`: the language warning shown; the card
  was received, with garbled text, and the deliveryman on the Pokémon Center's top floor handed
  over the Aurora Ticket, again with garbled text. It appears to be a genuine key item.
- Japanese Emerald, the Japanese MysticTicket 2006-2007 `.wc3`: received; しんぴのチケット.
- **Confirmed by the user:** saying ふしぎ できごと ワクワク ドキドキ (fushigi dekigoto wakuwaku
  dokidoki) at the Poké Mart questionnaire in Japanese Emerald unlocks ふしぎなできごと (Mystery
  Event); both ふしぎなおくりもの and ふしぎなできごと are now in its menu.

**What it means, and what was changed.**
- **The trade:** the Cable Club's link type is **0x1133** (`cable_club.c` `sub_80834E4`), and the
  same link carries on into the Trade Center. `trade.c` waited for 0x1111 (only the link test
  screen's), so it never started walking. Fixed in `trade.c`, the model and docs/TRADE.md; the
  trainer-card exchange (`0xCCCC 2`, 100 bytes) is now modelled too, and `trade.c`'s blank card is
  a full 100 bytes (it read past a 40-byte buffer before).
- **The trainer:** not yet explained. The card's trainer record is intact (its checksum matches the
  game's sum of 46 words), the script is the card's own, and Ruby's `addtrainer` copies it and
  saves. To find out, the next step is a read-only backup of the Ruby save, to look at the stored
  trainer slot (SaveBlock2 + 0x498, 188 bytes).
