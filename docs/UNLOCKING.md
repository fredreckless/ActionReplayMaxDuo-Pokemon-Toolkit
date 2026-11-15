# Unlocking Mystery Gift and Mystery Event, in every language

A game won't offer MYSTERY GIFT or MYSTERY EVENT on its title menu until you've told someone in the game a secret phrase. The phrase is four words from the game's easy chat word lists, and **each language has its own**. The words aren't always a translation of the English ones, either: Spanish leaves the fourth box empty, and Italian ends with "!".

Every phrase below was **read from the game's own ROM**, from the words the game compares with what you enter. Each one was then **entered in that game by button presses** in the emulator: word by word, then a save and a restart. That was done for every ROM listed, 30 runs in all, and each time the game set the flag itself and the new item was on the title menu. Japanese Ruby and Sapphire are the only gap (see the end).

## Where to say it

| Game | Who to tell | When | What appears on the title menu |
|---|---|---|---|
| Emerald, FireRed, LeafGreen | The **questionnaire** on the counter of any Poké Mart. Read it and answer YES | Once you have the Pokédex | Mystery Gift (Japanese Emerald can also unlock Mystery Event there) |
| Ruby, Sapphire | The **man by the PC** in Petalburg City's Pokémon Center. Answer YES when he asks to see your profile | After beating Norman | Mystery Event |

Then **save, and switch the game off and on again**: the item appears on the title menu.

To enter a word, highlight its box and press A. The quickest way to find a word in Emerald, FireRed, LeafGreen and the European Ruby and Sapphire is A-Z mode: press SELECT, choose the word's first letter, then scroll down the list. Japanese games list the words by group instead. When all four boxes are right, choose OK, then YES.

## Mystery Gift: Emerald, FireRed and LeafGreen

The same phrase works in all three games in a given language.

| Language | Phrase | On the title menu |
|---|---|---|
| English | **LINK** · **TOGETHER** · **WITH** · **ALL** | MYSTERY GIFT |
| French | **CONNEXION** · **AVEC** · **LES** · **DRESSEUR** | CADEAU MYST. |
| German | **LINK** · **MIT** · **ALLE** · **ZUSAMMEN** | GEHEIMGESCHEHEN |
| Italian | **INSIEME** · **IN** · **LINK** · **!** | DONO SEGRETO |
| Spanish | **CONEXIÓN** · **CON** · **TODOS** · *(leave the fourth box empty)* | REGALO MIST. |
| Japanese | **ともだち** · **いっぱい** · **ふしぎ** · **つうしん** | ふしぎな もらいもの |

Japanese Emerald shows ふしぎな おくりもの instead when it finds a Wireless Adapter at start-up. That is what the DUO plays: see the main README.

## Mystery Event: Ruby and Sapphire (and Japanese Emerald)

| Language | Phrase | On the title menu |
|---|---|---|
| English | **MYSTERY** · **EVENT** · **IS** · **EXCITING** | MYSTERY EVENTS |
| French | **EVENEMENT** · **MYSTERE** · **EST** · **PASSIONNANT** | EVENEMENTS MYSTERE |
| German | **GEHEIM** · **GESCHEHEN** · **IST** · **JIPP! JIPP!** | GEHEIMGESCHEHEN |
| Italian | **EVENTO** · **SEGRETO** · **È** · **FANTASTICO** | EVENTI SEGRETI |
| Spanish | **EVENTO** · **MISTERIOSO** · **ES** · **DEMASIADO** | EVENTOS MISTERIOSOS |
| Japanese Emerald | **ふしぎ** · **できごと** · **わくわく** · **ドキドキ** (at the Poké Mart questionnaire) | ふしぎな できごと |

"JIPP! JIPP!" is a single word in the German lists. Ruby and Sapphire compare the words' text, so any word that reads the same will do.

The European versions of Emerald have no Mystery Event, and the questionnaire doesn't accept this phrase. FireRed and LeafGreen still have the phrase in their code in every language, but none of their scripts uses it (going by pret's FireRed).

Once Mystery Event is unlocked, the DUO can send events to Ruby and Sapphire in every language here ([EREADER.md](EREADER.md)). Each French, Italian and Spanish Eon Ticket from the EventsGallery was checked in its own Ruby and Sapphire in the emulator.

## The ROMs this was checked in

- **Emerald:** Japanese (both phrases), English, French, German, Italian and Spanish.
- **FireRed:** Japanese, English (USA), French, German, Italian and Spanish.
- **LeafGreen:** Japanese, English (Europe, Rev 1), French, German, Italian and Spanish.
- **Ruby:** English (1.1), French, German (the debug version), Italian and Spanish.
- **Sapphire:** English (Europe, Rev 1), French, German, Italian and Spanish.
- **Not checked:** Japanese Ruby and Sapphire. They're a different build, which the save generator doesn't know yet. Their phrase is believed to be ふしぎ できごと わくわく ドキドキ, as in Japanese Emerald, but that hasn't been checked.

## How it was done

`virtual/savegen/phrases.py` does all of it:

- **`find`** reads each ROM's phrase and the addresses it needs. In Emerald, FireRed and LeafGreen the phrase comes from the arrays the game's comparison function is given. Ruby and Sapphire's comparison reaches into a structure laid out differently in each language, so their phrase is found as English Ruby's four word numbers in some order: that pattern comes up exactly once in each European ROM.
- **`play ROM SAV`** plays the unlock in the game. It reads the easy chat screen's own word lists and cursors from RAM, so the presses don't depend on knowing the language, and it checks each word in its box before going on. Then it saves, restarts and looks at the title menu. It works on a copy of the save.
- **`table`** prints the phrases.

No ROM data is kept in this repository beyond the phrases themselves and a few addresses.
