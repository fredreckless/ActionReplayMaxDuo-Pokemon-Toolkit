"""Planted bugs: each must make at least one test fail (a check on the tests themselves).
    python mutate4.py [KIND ...]      run them all, or the kinds named (fw, fw42, prog, ereader, pc)
    python mutate4.py fw  "<name>"    one firmware mutant, rebuilt from build_v4.py
    python mutate4.py pc  "<name>"    one tool mutant"""
import glob, os, re, shutil, subprocess, sys
FW_MUTANTS = {
    "restart doesn't wait for the hello (v4's race)": ("    ldr  r7, lit_wait\nrs_wait:\n    bl   {AVAIL:#x}\n    cmp  r0, #0\n    bne  rs_go\n    bl   {IDLE:#x}\n    subs r7, #1\n    bne  rs_wait\nrs_go:\n", "", "ten in a row"),
    "restart uses hard reset": ("    svc  #0\n", "    svc  #0x26\n", "restart"),
    "restart resets before replying": ("    movs r0, #{CMD_RESTART:#x}\n    ldr  r1, lit_ack\n    bl   {a['send_sbw']:#x}\n", "", "restart"),
    "restart with interrupts on": ("    ldr  r0, lit_ime\n    movs r1, #0\n    strh r1, [r0]\n", "    movs r1, #0\n", "restart"),
}
FW42_MUTANTS = {
    "run skips the program's CRC check": ("    ldr  r1, [r6, #8]\n    cmp  r0, r1\n    bne  run_bad\n", "    ldr  r1, [r6, #8]\n", "v4.2 run: a staged program"),
    "run never replies before starting the program": ("    movs r0, #{CMD_RUN:#x}\n    ldr  r1, lit_ack\n    bl   {v4.AT['send_sbw']:#x}\n", "", "adapter test: answers"),
    "run accepts an entry point outside the code": ("    cmp  r1, r4\n    bhs  run_bad\n", "", "refused"),
}
PROG_MUTANTS = {      # firmware/programs/adapter.c: rebuilt and embedded in a copy of the tool
    "adapter skips the ready handshake": ("    if (!wait_si(1, HANDSHAKE_LINES)) {\n#ifndef PROBE\n        judge_flick(0);", "    if (0) {\n#ifndef PROBE\n        judge_flick(0);", "wireless adapter"),
    "adapter acknowledges without the 0x80": ("((cmd + 0x80) & 0xFF)", "(cmd & 0xFF)", "wireless adapter: Emerald"),
    "adapter never takes its turn after a wait": ("frames * LINES_PER_FRAME)\n            break;", "frames * LINES_PER_FRAME * 100000)\n            break;", "wireless adapter: Emerald"),
    "adapter rests SO low before a command (no first-bit fix)": ("    SIODATA32 = IDLE_WORD;\n    SIOCNT = CNT_32BIT | CNT_START | CNT_SO_HIGH;\n}", "    SIODATA32 = IDLE_WORD;\n    SIOCNT = CNT_32BIT | CNT_START;\n}", "first-bit behaviour"),
    "adapter's flick never gets wider": ("            flick_w++;                                        /* not noticed: wider */", "            ;", "tunes its own width"),
    "adapter's flick never gets narrower": ("            flick_w = last_flick ? last_flick - 1 : 0;       /* clocked but refused: narrower */", "            ;", "tunes its own width"),
    "distributor's broadcast checksum is wrong": ("    b[15] = ~sum;", "    b[15] = sum;", "distributor"),
    "distributor's name puts 0xFF in a word's top byte (needs flicks)": ("{ 0xBE, 0xCF, 0xC9, 0x00, 0xFF, 0, 0, 0 }", "{ 0xBE, 0xCF, 0xC9, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF }", "distributor: Emerald's search"),
    "adapter arms a top-bit-0 word straight from high (lab session 17)": ("        SIOCNT = CNT_32BIT;\n        SIOCNT = CNT_32BIT | CNT_START;\n        return;", "        SIOCNT = CNT_32BIT | CNT_START;\n        return;", "distributor: Emerald's search"),
    "serial sweep offers each block only once (the game can't find its host again)": ("id = ((n >> 10) << 9 | (n & 511))", "id = ((n >> 9) << 9 | (n & 511))", "serial sweep"),
    "serial sweep doesn't record the serial the game connects to": ("        if (sweep) found_serial = req[0] & 0xFFFF;", "", "serial sweep"),
    "distributor uses the English serial 0x7F7D (BPEJ ignores it, lab session 18)": ("#define SERIAL_JP_EMERALD 0x7F7F", "#define SERIAL_JP_EMERALD 0x7F7D", "distributor: Emerald's search"),
    "adapter answers its own echoed acknowledgement as a command": ("        if (in == ack[31] && (in & 0x80)) {", "        if (0) {", "echo of our own"),
    "distributor always uses the Japanese serial (ignores the game)": ("                    : lang == 1 && (compat >> 10 & 0xF) == 3 ? SERIAL_JP_EMERALD : SERIAL_DECOMP;", "                    : SERIAL_JP_EMERALD;", "every game: an English FireRed"),
    "distributor keeps a Japanese host for every game": ("        if (lang) host_lang = lang;", "", "every game: an English FireRed"),
    "--serial is ignored by the adapter": ("        if (idx) pc_serial = idx & 0x7FFF;", "", "every game: Japanese Emerald still"),
    "news: the distributor ignores the game's answer (always 'received')": ("        const u32 *script = mg_resp ? script_had_news : script_news_received;", "        const u32 *script = mg_resp && 0 ? script_had_news : script_news_received;", "Wonder News: a game that already has"),
    "news: the distributor still advertises a card": ("               | (GIFT_IS_NEWS ? 1 << 4 : 1 << 5)   /* hasNews or hasCard: what we offer */", "               | 1 << 5", "Wonder News: Japanese Emerald finds"),
    "news: sent under the Wonder Card's link ID": ("        case 3: *op = MG_SEND; *ident = ID_NEWS;", "        case 3: *op = MG_SEND; *ident = ID_CARD;", "Wonder News: Japanese Emerald finds"),
    "distributor doesn't say it has a card": ("(GIFT_IS_NEWS ? 1 << 4 : 1 << 5)", "(GIFT_IS_NEWS ? 1 << 4 : 0 << 5)", "distributor"),
    "host never acknowledges the game's chunks": ("    if (ni.state & NI_BUSY) {\n        u32 f", "    if (0) {\n        u32 f", "NI channel"),
    "host acknowledges with the wrong window number": ("ni.n[ni.phase] << 11 | 1u << 18", "((ni.n[ni.phase] + 1) & 3) << 11 | 1u << 18", "NI channel"),
    "host never moves on after the game acknowledges": ("        nis.acked[phase] = 1;", "        ;", "may join"),
    "host sends the wrong join status": ("static const u8 join_group_ok = 5;", "static const u8 join_group_ok = 6;", "may join"),
    "parent doesn't echo the game's commands": ("        memcpy(out + bytes + 3 + 14, rx_cmd, 14);                    /* row 1: the game's, echoed */\n", "", "Mystery Gift delivers"),
    "parent gives the game the wrong player number": ("tx_cmd[2] = 0x0001;", "tx_cmd[2] = 0x0002;", "Mystery Gift delivers"),
    "parent ignores the game's standby": ("    case CMD_READY_EXIT: standby_reply = 1;", "    case CMD_READY_EXIT: standby_reply = 0;", "Mystery Gift delivers"),
    "parent never agrees to close the link": ("    case CMD_READY_CLOSE: close_reply = 1;", "    case CMD_READY_CLOSE: close_reply = 0;", "nothing to send"),
    "parent keeps the game's sequence number": ("            child_uni[0] &= 0x1F;", "            ;", "Mystery Gift delivers"),
    "parent swaps the bytes in block chunks": ("tx_cmd[1 + j] = lo | hi << 8;", "tx_cmd[1 + j] = hi | lo << 8;", "Mystery Gift delivers"),
    "server's header CRC is off by one bit": ("            crc = ~crc;", "            crc = ~crc ^ 1;", "Mystery Gift delivers"),
    "server tells the game to save the card as Wonder News": ("CLI_SAVE_CARD = 10,", "CLI_SAVE_CARD = 9,", "Mystery Gift delivers"),
    "host moves on even when the game missed a packet": ("        if (hf_uni && !uni_acked && n_resent < 0xFFFF)", "        if (0)", "packets lost"),
    "adapter flicks while still armed (lab session 15: never seen)": ("        SIOCNT = CNT_32BIT;                                   /* disarmed for a moment: SO really low */", "        SIOCNT = CNT_32BIT | CNT_START;", "first-bit behaviour"),
    "adapter's flick never narrows after a lost word": ("            judge_flick(0);                                   /* narrower; the game will retry */", "            ;", "tunes its own width"),
    "adapter has no watchdog mid-command": ("        if (phase != PH_COMMAND && phase != PH_ID && now() - last_word_at > WATCHDOG_LINES) {", "        if (0) {", "wireless adapter: the game gives up"),
    "adapter: a screen line shown after the game has started talking": ("    if (game_seen || !say_loaded) return;", "    if (!say_loaded) return;", "distributor: link players exchanged"),
}

EREADER_MUTANTS = {  # firmware/programs/ereader.c: the e-Reader on the GBA link cable
    "e-Reader: the checksum slot carries 0": ("        loaded = checksum;\n", "        loaded = 0;\n", "e-Reader: Ruby as master"),
    "e-Reader: our link player keeps language 0": ("    memcpy(lp + 0x1A, game_player + 16 + 0x1A, 2);          /* language */", "", "e-Reader: Ruby as master"),
    "e-Reader: never answers the game's 0x5FFF": ("        queue(0x5FFF, 0);                                       /* close: everyone says so */", "        ;", "e-Reader: Ruby as master"),
    "e-Reader: as master, never says 0x8FFF": ("        loaded = is_master && seen_two >= 20 ? MASTER_HS : SLAVE_HS;", "        loaded = seen_two > 1000000 ? MASTER_HS : SLAVE_HS;", "e-Reader: the DUO as master"),
    "e-Reader: as master, never asks for link players": ("            if (is_master) queue(0x2222, 0x5501);                /* ask for link players */", "            ;", "e-Reader: the DUO as master"),
    "e-Reader: as master, the session-24 gap (12 lines from the start)": ("#define GAP_AFTER_DONE 13 ", "#define GAP_AFTER_DONE 7 ", "e-Reader: the DUO as master"),
    "e-Reader: as master, command cycles back to back": ("                    next_cycle = now() + LINES_PER_FRAME;", "                    next_cycle = now();", "e-Reader: the DUO as master"),
    "e-Reader: as master, starts before handling the last transfer": ("        } else if (is_master && !in_flight && !(SIOCNT & CNT_START)", "        } else if (is_master && !(SIOCNT & CNT_START)", "e-Reader: the DUO as master"),
    "e-Reader: takes its role from one look at SI (lab session 27)": ("    is_master = (SIOCNT >> CNT_ID_SHIFT & 3) == 0;            /* our player number, from the GBA */\n    role_known = 1;", "    is_master = !(SIOCNT & CNT_SI);", "while SI flickers"),
    "e-Reader: never notices the game starting over": ("    if (hs_run >= 3) {", "    if (hs_run >= 300000) {", "two events in one session"),
    "e-Reader: the event's last chunk is cut short": ("        u32 lo = at < tx_len ? tx_src[at] : 0, hi = at + 1 < tx_len ? tx_src[at + 1] : 0;", "        u32 lo = at + 14 < tx_len ? tx_src[at] : 0, hi = at + 1 < tx_len ? tx_src[at + 1] : 0;", "e-Reader: Ruby as master"),
    "ereader: a screen line shown while the game is linked": ("if (event_ready && !said_ready && state == ST_WAITING) {", "if (event_ready && !said_ready && state == ST_GOT_PLAYER) {", "Ruby as master (purple plug)"),
}

PC_MUTANTS = {
    "contest: the names not in the link's form": ("        name[length - 1], name[5] = name[5], 0xFF\n", "        name[length - 1] = name[5]\n", "Contest (8 November)"),
    "contest: the moves always in slot order": ("    order = [k for k in (order or slots) if 0 <= k < 4 and moves[k]] or slots\n", "    order = slots\n", "Contest: the DUO's moves"),
    "blender: the Pokeblock's strength without the best RPM": ("    factor = max_rpm // 333 + 100\n", "    factor = 100\n", "Berry Blender (8 November)"),
    "blender: the DUO's berry block with the flavours shifted": ("    return struct.pack(\"<H\", item) + SB.encode_name(row[0], 2) + bytes(row[1:7]) + b\"\\0\"", "    return struct.pack(\"<H\", item) + SB.encode_name(row[0], 2) + bytes(row[2:7]) + b\"\\0\\0\"", "Berry Blender (8 November)"),
    "mix: the gift item left out of our record": ("    parts[\"gift\"] = gift\n", "    parts[\"gift\"] = 0\n", "Record Mixing, the DUO as master"),
    "mix: a part we bring is handed back from the game instead": ("    mirror = sum(1 << k for k, name in enumerate(MIX_PARTS) if not parts.get(name))", "    mirror = 0x1F", "Record Mixing with a whole record"),
    "records: the prediction keeps the lower trendiness": ("            elif pool[key][0] & 0x7F < w[0] & 0x7F:", "            elif pool[key][0] & 0x7F > w[0] & 0x7F:", "Record files: what Ruby keeps"),
    "trade: the trainer card without the trainer's name": ("    card[0x30:0x38] = name[:8]\n", "", "trade, the game as master"),
    "trade: the trainer card without a Pokedex or a new save's profile": ("    card[0x02] = 1                                                     # has a Pokedex\n", "", "trade, the game as master"),
    "battle partner: the impossible level answers without waiting for the player's choice": ("                            continue                          # (waiting for the player's own choice)", "                            pass", "the impossible level waits"),
    "battle partner: the team isn't checked against the game's rules": ("            unruly = unruly or bool(rules)", "            unruly = False", "a Pokemon that couldn't exist"),
    "battle partner: the PC's move choice ignored (the first move used)": ("                slot, target = (plan[1] if plan[0] == \"move\" else -1), battler ^ 1", "                slot, target = 0, battler ^ 1", "the PC chooses the DUO's moves at the medium level"),
    "battle partner: a double battle's target is simply the first foe": ("                if v > best_v:\n                    best_v, best = v,", "                if best is None:\n                    best_v, best = v,", "a double battle chosen by the PC"),
    "battle partner: a double battle's partners don't work together": ("                self.chosen[battler] = plan          # (the partner, choosing next, works with it)", "", "a double battle's teamwork"),
    "battle partner: elite's double battle uses the quick chooser": ("                self.plan[battler] = (self._double_plan(battler) if self.level in (\"elite\", \"impossible\")", "                self.plan[battler] = (self._double_plan(battler) if False", "elite and impossible in a double battle"),
    "battle partner: a double battle's Earthquake never hurts the partner": ("                    targets = list(side) + ([a ^ 2] if MOVES[move][6] == 0x20 and (a ^ 2) in alive else [])", "                    targets = list(side)", "elite and impossible in a double battle"),
    "battle partner: a double battle's Protect ignored": ("                    if x in protect or alive[x] < 0.05:", "                    if alive[x] < 0.05:", "elite and impossible in a double battle"),
    "Battle Tower: the PC's partner aims at the player": ("            return slot, target if target in self.FOES else self.FOES[0]", "            return slot, 0", "Battle Tower link multi battle (8 November)"),
    "battle partner: a double battle taken for a single": ("                    double = v & 0xFFFF == 0x2244", "                    double = False", "a double battle chosen by the PC"),
    "battle: the impossible level doesn't use the other side's choice": ("            v = self.values(battle, s, acts, first=first)", "            v = self.values(battle, s, acts)", "the impossible level sees the other side's choice"),
    "battle: a team's effort values aren't checked": ("    if sum(evs) > 510:", "    if False:", "a team's .pk3 files are checked"),
    "colosseum: the battle's record read without each entry's padding": ("        at += 4 + (n + 3 & ~3)", "        at += 4 + n", "battle probe, the game as master"),
    "event files: any size accepted": ("        if len(data) > MEV_MAX:", "        if False:", "e-Reader: with no event"),
    "a .me3 is sent as it is, unwrapped": ("    script = build_event_script(me3, language)\n", "    script = data\n", "Mystery Event files"),
    "a .me3's RAM script checksum is never checked": ("    if stored != sum(block):", "    if False:", "Mystery Event files"),
    "the wrapped script has no checksum command": ("    out += bytes([MEV_CHECKSUM]) + struct.pack(\"<iII\", sum(me3[\"script\"]), start, end)", "    out += bytes([MEV_CHECKSUM]) + struct.pack(\"<iII\", 0, start, start)", "Mystery Event files"),
    "no advice to swap the cable when the DUO is master": ("                        if master and not warned:", "                        if False:", "Ruby's menu gives up"),
    "news files: the CRC is never checked": ("        if game_crc16(data) != crc:", "        if False:", "Wonder News files"),
    "card checks never compare the card's CRC": ("    if game_crc16(card) != int.from_bytes(data[0:2], \"little\"):", "    if False:", "card checks"),
    "no warning when the card's language differs from the game's": ("((data >> 16 & 0xF) == 1) != (card_language == \"Japanese\")", "False", "every game: Japanese Emerald still"),
    "fast 32-bit checksum on the save": ('("r8", SAVE_BASE, 0x10000), ("crc", SAVE_BASE, 0x10000), ("w16", MAP_REG, 0x0120)]', '("r8", SAVE_BASE, 0x10000), ("crct", SAVE_BASE, 0x10000), ("w16", MAP_REG, 0x0120)]', "8-bit"),
    "a stalled program upload is never sent again": ("            if attempt or not stalled:", "            if True:", "held up"),
    "a first connect that times out is never tried again": ("            if attempt or not maxduo_saves._is_timeout(err):\n                raise\n            print(f\"The DUO didn't finish", "            if True:\n                raise\n            print(f\"The DUO didn't finish", "connect: a first answer"),
    "Mystery Gift never finishes by itself": ("        finished_at = time.time()             # the game has it and has closed the link", "        finished_at = None", "finishing: the tool stops"),
    "the keep-going option is ignored": ("    finish = loaded and not getattr(args, \"keep_going\", False) and not sweeping \\", "    finish = loaded and not sweeping \\", "finishing: the tool stops"),
    "no warning for a card named for another game": ("                        if game and game not in card_games:", "                        if False:", "guided start-up"),
    "the start-up never says to leave the game's GBA off": ("    print(\"  Then switch on the DUO's GBA (the one with the Action Replay); leave the game's GBA off.\")", "    print(\"  Then switch on the DUO's GBA (the one with the Action Replay).\")", "guided start-up"),
    "old --mystery-event isn't translated": ("    elif event or ereader:", "    elif ereader:", "two tools"),
    "no stale-packet clearing": ("        cleared = self.drain()\n", "        cleared = 0\n", "connect"),
    "partial upload drops interpreter bytes": ("            self._upload_fast(LAB_STAGE, prog[:16])\n", "            self._upload_fast(LAB_STAGE, prog[:12])\n", "resident"),
    "wrong logo constant": ("0x01000000: 0x62B5CBC1", "0x01000000: 0x62B5CBC0", "logo constants"),
    "duplicate backups stored": ("            return p, \"identical to an earlier backup - not stored again\", summary, previous\n", "            pass\n", "backups"),
    "trainer change not warned": ("    if previous and (previous[\"trainer\"], previous[\"id\"]) != (summary[\"trainer\"], summary[\"id\"]):", "    if False:", "backups"),
    "DeleteFile allowed": ("    0x1C: \"DeleteFile", "    0x1D: \"DeleteFile", "refusals"),
    "adapter test never stops the program": ("    finally:\n        word = program_poll(duo, 1)\n        st = program_stop(duo)\n", "    finally:\n        word = st = 0\n", "adapter test"),
    "adapter program answers with the wrong ID": ("ADAPTER_IMAGE", "ADAPTER_IMAGE_WRONG_ID", "adapter test: answers"),
    "Wonder Card's RAM script read from the wrong place": ("    script = data[4 + size + 0x50 + 4:4 + size + 0x50 + 4 + 1000]", "    script = data[4 + size + 0x50:4 + size + 0x50 + 1000]", "Mystery Gift delivers"),
    "berry sent with initramscript's command number": ("MEV_SETENIGMABERRY = 7", "MEV_SETENIGMABERRY = 6", "Enigma Berry"),
    "berry's checksum taken before the pointers are cleared": ("struct.pack(\"<iII\", sum(rec), start, start + len(rec))\n    out += bytes([MEV_SETENIGMABERRY])", "struct.pack(\"<iII\", sum(berry), start, start + len(rec))\n    out += bytes([MEV_SETENIGMABERRY])", "Enigma Berry"),
    "berry file check counts the description pointers": ("    rec = bytearray(data[:ECB_CHECKSUM_AT])\n    rec[ECB_POINTERS] = bytes(8)\n", "    rec = bytearray(data[:ECB_CHECKSUM_AT])\n", "Enigma Berry files"),
    "card strips joined without skipping the later strips' titles": ("        card += data[CARD_TITLE:]\n", "        card += data[CARD_TITLE:] if not card else data\n", "e-Card scans"),
    "card strips' Reed-Solomon parity never checked": ("    damaged = [i for i, c in enumerate(cw) if rs_parity(c[:48]) != bytes(c[48:])]", "    damaged = []", "e-Card scans"),
    "vpk0 one-sample distances (method 1) off by four": ("else (m << 2) - 8", "else (m << 2) - 4", "e-Card"),
    "Japanese Mystery Events get the English mask": ('MEV_LANGUAGE_MASKS = {"Japanese": 1 << 0,', 'MEV_LANGUAGE_MASKS = {"Japanese": 1 << 1,', "Mystery Event files"),
    "a card's trainer record cut four bytes short": ("EREADER_TRAINER_SIZE = 0xBC", "EREADER_TRAINER_SIZE = 0xB8", "e-Card scans"),
    "pk3 blocks unshuffled with personality mod 23": ('form, plain, order = "the game\'s (encrypted)", decrypted, PK3_ORDERS[pid % 24]', 'form, plain, order = "the game\'s (encrypted)", decrypted, PK3_ORDERS[pid % 23]', "Pokemon files"),
    "Hoenn species not reordered to the National Dex": ("        n = PK3_HOENN_TO_NATIONAL[internal - 277]", "        n = internal - 25", "Pokemon files"),
    "PKHeX's decrypted .pk3 form never recognised": ('    if sum(struct.unpack("<24H", as_is)) & 0xFFFF == stored:', "    if False:", "Pokemon files"),
    ".ect trainer pointer four bytes late": ('    out += bytes([MEV_ADDTRAINER]) + struct.pack("<I", start)', '    out += bytes([MEV_ADDTRAINER]) + struct.pack("<I", start + 4)', "e-Reader trainer files"),
    "short events sent unpadded (Ruby runs an empty buffer)": ('    sent = data.ljust(MEV_MAX, b"\\0")', "    sent = data", "e-Card trainer on the link"),
    "Mew and Deoxys accepted by Emerald without the fateful mark": ('    if version in (3, 4, 5) and f["dex"] in (151, 386) and not f["fateful"]:', "    if False:", "Emerald refuses a Mew"),
    "Trainer Hill records read in pokeemerald's English layout": ("HILL_RECORD = 0x270", "HILL_RECORD = 0x274", "Trainer Hill e-Cards"),
    "Trainer Hill set's checksum left out": ('    return (bytes([len(records), 0, 0, 0]) + struct.pack("<I", sum(body) & 0xFFFFFFFF)', '    return (bytes([len(records), 0, 0, 0]) + struct.pack("<I", 0)', "Trainer Hill e-Cards"),
    "Trainer Tower floors read in pokefirered's English layout": ("TOWER_RECORD = 0x3D4", "TOWER_RECORD = 0x3E0", "Trainer Tower e-Cards"),
    "Secret Bases: a base filed at the player's own spot (predicted)": ("        if at == 0:\n            return\n        if at is not None:", "        if at is not None:", "Secret Base filing"),
    "Secret Bases: a card's nature ignored": ("        if nature is not None and pid % 25 != nature:\n            continue\n", "", "Secret Base files"),
    "Secret Bases: the player's own base keeps its out-of-date team": ("        if i == 0:                                     # SetPlayerSecretBaseParty", "        if False:", "Secret Bases from a save backup"),
    "Secret Bases: dolls allowed on the floor": ("        if (big and tile != \"L\") or (not big and tile not in (\"s\", \"L\")):", "        if big and tile != \"L\":", "Secret Base files"),
    "Secret Bases: two bases in one spot allowed": ("        if f[\"location\"] in places:", "        if False:", "Secret Base files"),
    "Secret Bases: the game's bases read back one word out": ("        self.words.append(program_poll(self.duo, self.sel | len(self.words) << 8))", "        self.words.append(program_poll(self.duo, self.sel | (len(self.words) + 1) << 8))", "Record Mixing, the DUO as master"),
    "every Pokemon's original route called a trade": ('    if route == "trade":\n        return f"Originally: {event}, {PK3_ROUTE_TEXT[\'trade\']}. This trade is the original route."', '    if True:\n        return f"Originally: {event}, {PK3_ROUTE_TEXT[\'trade\']}. This trade is the original route."', "how each event was originally given out"),
    "party stats left empty in a traded Pokemon": ("    return box + pk3_party_fields(f)", "    return box + bytes(20)", "party form"),
    "known game table ignored": ("    known = KNOWN_SAVE_GAMES.get(info[\"code\"][:3])\n    if forced:", "    known = None\n    if forced:", "known games"),
}


import threading
BUILD_LOCK = threading.Lock()


def run(kind, name):
    import paths, tempfile
    work = tempfile.mkdtemp()
    if kind == "fw42":
        old, new, pick = FW42_MUTANTS[name]
        src = open(os.path.join(paths.FIRMWARE, "build_v42.py")).read()
        assert src.count(old) == 1, name
        open(os.path.join(work, "build_v42_mut.py"), "w").write(src.replace(old, new))
        shutil.copy(paths.build_file("fw.bin"), work)
        r = subprocess.run([sys.executable, "-c", "import build_v42_mut as B; B.build('fw_mut.bin')"], cwd=work,
                           capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=paths.FIRMWARE))
        assert r.returncode == 0, r.stderr[-800:]
        env = dict(os.environ, V42_FW=os.path.join(work, "fw_mut.bin"))
    elif kind == "fw":
        old, new, pick = FW_MUTANTS[name]
        src = open(os.path.join(paths.FIRMWARE, "build_v4.py")).read()
        assert src.count(old) == 1, name
        open(os.path.join(work, "build_v4_mut.py"), "w").write(src.replace(old, new))
        shutil.copy(paths.build_file("fw.bin"), work)
        r = subprocess.run([sys.executable, "-c", "import build_v4_mut as B; B.build('fw_mut.bin')"], cwd=work,
                           capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=paths.FIRMWARE))
        assert r.returncode == 0, r.stderr[-800:]
        env = dict(os.environ, V3_FW=os.path.join(work, "fw_mut.bin"))
    elif kind in ("prog", "ereader", "trade", "mix", "colosseum", "tower", "blender", "contest", "lab4p"):
        old, new, pick = KINDS[kind][name]
        sys.path.insert(0, paths.FIRMWARE)
        import programs
        src_name = {"prog": "adapter.c", "ereader": "ereader.c", "trade": "trade.c", "mix": "mix.c", "colosseum": "colosseum.c",
                    "tower": "tower.c", "blender": "blender.c", "contest": "contest.c",
                    "lab4p": "lab4p.c"}[kind]
        src_path = os.path.join(paths.FIRMWARE, "programs", src_name)
        good_src = open(src_path).read()
        walk_path = os.path.join(paths.FIRMWARE, "programs", "room_walk.h")
        in_walk = good_src.count(old) == 0 and open(walk_path).read().count(old) == 1   # (the shared walk)
        assert in_walk or good_src.count(old) == 1, name
        # the everyday and the lab build share adapter.c
        builds = {"prog": ("adapter", "adapter_lab"), "ereader": ("ereader",), "trade": ("trade",), "mix": ("mix",),
                  "colosseum": ("colosseum",), "tower": ("tower",), "blender": ("blender",),
                  "contest": ("contest",), "lab4p": ("lab4p",)}[kind]
        with BUILD_LOCK:
            good = {b: programs.build(b).hex() for b in builds}
        os.makedirs(os.path.join(work, "programs"))
        open(os.path.join(work, "programs", src_name), "w").write(good_src if in_walk else good_src.replace(old, new))
        shutil.copy(os.path.join(paths.FIRMWARE, "programs", "link.ld"), os.path.join(work, "programs"))
        for h in glob.glob(os.path.join(paths.FIRMWARE, "programs", "*.h")):   # (room_walk.h, shared)
            shutil.copy(h, os.path.join(work, "programs"))
        if in_walk:
            open(os.path.join(work, "programs", "room_walk.h"), "w").write(open(walk_path).read().replace(old, new))
        with BUILD_LOCK:
            saved = programs._HERE
            programs._HERE = work
            try:
                bad = {}
                for b in builds:
                    try:
                        bad[b] = programs.build(b).hex()
                    except AssertionError:          # the planted bug doesn't fit this build: test the other
                        if b == "adapter":
                            raise
                        bad[b] = good[b]
            finally:
                programs._HERE = saved
        assert any(good[b] != bad[b] for b in builds), name
        tool = open(os.path.join(paths.ROOT, "duo_events.py")).read()
        for b in builds:
            assert tool.count(good[b]) == 1, b
            tool = tool.replace(good[b], bad[b])
        open(os.path.join(work, "duo_events.py"), "w").write(tool)
        shutil.copy(os.path.join(paths.ROOT, "maxduo_saves.py"), work)
        for f in ("secret_bases.py", "records.py", "runlog.py"):
            shutil.copy(os.path.join(paths.ROOT, f), work)
        env = dict(os.environ, MAXDUO_TOOL_DIR=work)
    else:
        old, new, pick = PC_MUTANTS[name]
        tools = {f: open(os.path.join(paths.ROOT, f), encoding="utf-8").read()
                 for f in ("maxduo_saves.py", "duo_events.py", "secret_bases.py", "records.py", "runlog.py", "duo_battle.py")}
        shutil.copy(os.path.join(paths.ROOT, "battle_data.py"), work)
        if old == "ADAPTER_IMAGE":                     # rebuild the embedded program with a wrong ID (valid CRC)
            sys.path.insert(0, paths.FIRMWARE)
            import programs
            with BUILD_LOCK:
                good = programs.build("adapter_detect").hex()
                programs.PROGRAMS["adapter_detect"] = programs.ADAPTER_DETECT.replace(f"{programs.RFU_ID:#x}", "0x8002")
                try:
                    bad = programs.build("adapter_detect").hex()
                finally:
                    programs.PROGRAMS["adapter_detect"] = programs.ADAPTER_DETECT
            assert good != bad
            old, new = good, bad
        target = next(f for f, t in tools.items() if old in t)       # the save tool, or the wireless one
        src = tools[target]
        assert src.count(old) == 1, name
        mutated = src.replace(old, new)
        if "crct" in new:   # let the bug through the tool's own guard too, so only the tests can catch it
            mutated = mutated.replace('if name == "crct" and 0x0E000000 <= addr < 0x0F000000:', 'if False:')
        for f, t in tools.items():
            open(os.path.join(work, f), "w", encoding="utf-8").write(mutated if f == target else t)
        env = dict(os.environ, MAXDUO_TOOL_DIR=work)
    for attempt in range(3):               # the emulator itself can segfault under load: run again
        r = subprocess.run([sys.executable, "test_v4.py", pick], cwd=paths.HERE, capture_output=True, text=True, env=env, timeout=1800)
        finished = any(" passed, " in l and " failed" in l for l in r.stdout.splitlines())
        if r.returncode >= 0 and finished:
            break                          # (no summary line means the run died part-way: try again)
    summary = [l for l in r.stdout.splitlines() if l.startswith("[") or "passed" in l]
    caught = any(l.startswith("[FAIL]") for l in summary)
    print(f"{'CAUGHT' if caught else 'MISSED'}  {kind}: {name}  ->  {summary[-1] if summary else r.stderr[-200:]}", flush=True)
    shutil.rmtree(work, ignore_errors=True)
    return caught


TRADE_MUTANTS = {    # firmware/programs/trade.c: the Cable Club trade partner
    "trade: player 1 heads for player 0's seat": ("seat_x = is_master ? 4 : 7;", "seat_x = is_master ? 4 : 4;", "trade, the game as master"),
    "trade: asks to leave wherever it stands, not on the door (lab session 31)": ("    if (rw_on_door(me)) {", "    if (rw_on_door(me) || 1) {", "the player stands on the DUO's nearest door tile"),
    "trade: never waits for a step to finish before the next": ("    if (!rw_free(me)) return 17;\n    state = ST_WALKING_OUT;", "    state = ST_WALKING_OUT;", "the player stands right below the DUO's seat"),
    "trade: our link player turns the game's National Dex on": ("lp[0] = game_player[16]; lp[1] = game_player[17];", "lp[0] = game_player[16]; lp[1] = game_player[17]; lp[3] = 0x80;", "trade, the game as master"),
    "trade: every block request answered with the first two Pokemon": ("u32 k = requests_answered < 3 ? requests_answered : 2;", "u32 k = 0;", "trade, the game as master"),
    "trade: the save's ready barriers never answered": ('queue(0x2FFE, 0, 0);                                     /* "ready": we are */', ";", "trade, the game as master"),
    "trade: as slave, says no instead of yes": ("send_msg(0xBBBB, 0);", "send_msg(0xBBCC, 0);", "trade, the game as master"),
    "trade: as master, asks for the next block at once": ("++req_timer > (req_sent ? 12 : 40)", "++req_timer > 0", "trade, the DUO as master"),
    "trade: stops after the trade screen (the game freezes back in the room)": ("else if (leave_agreed && state < ST_RETURNING) state = ST_RETURNING;", "else if (leave_agreed) state = ST_DONE;", "trade, the game as master"),
    "trade: never follows the player out of the room": ("if (game_exiting) { sent_exit = 1;", "if (0) { sent_exit = 1;", "back in the room, the player leaves first"),
    "trade: as master, opens the room again with the Cable Club's link type": ("if (state == ST_RETURNING) return LT_BACK;", "if (state == ST_RETURNING) return LT_ROOM;", "trade, the DUO as master"),
    "trade: offers the same slot again after a trade": ("            cur_pick++;                                          /* next time, the next event Pokemon */", "            ;", "three Pokemon in one sitting"),
    "trade: as master, opens a second trade screen where the scene should be": ("    if (state == ST_AGREED) return LT_SCENE;", "    if (state == ST_AGREED) return LT_TRADE;", "trade, the DUO as master"),
    "trade: screen lines shown in the middle of a link session": ("if (shown == state || (linked && state != ST_DONE)) return;", "if (shown == state) return;", "trade, the game as master"),
    "trade: no progress flags for Emerald and FireRed/LeafGreen": ("        lp[0x10] = 0x11;", "        lp[0x10] = 0;", "trade into FireRed"),
    "trade: as master, never says the trade can go ahead": ("send_msg(0xCCDD, 0); state = ST_AGREED;", "send_msg(0xDDEE, 0); state = ST_AGREED;", "trade, the DUO as master"),
}

MIX_MUTANTS = {      # firmware/programs/mix.c: the Record Corner partner
    "mix: tells Emerald it's an Emerald player (Emerald's own layout follows)": ("    return v == 3 ? 2 : v;                                   /* (Emerald: Ruby, below) */", "    return v;", "Record Mixing with Emerald"),
    "mix: player 1 heads for player 0's seat": ("seat_x = is_master ? 6 : 13, seat_y", "seat_x = is_master ? 6 : 6, seat_y", "Record Mixing, the game as master"),
    "mix: asks to leave wherever it stands, not on the door (lab session 31)": ("    if (rw_on_door(me)) {", "    if (rw_on_door(me) || 1) {", "Record Mixing: back in the room, the player stands in the DUO's way"),
    "mix: never stands up (26) before walking out": ("    if (f == 90) return 26;", "    if (f == 90) return 17;", "Record Mixing, the game as master"),
    "walk: the first plan clears only the walkable columns (7 November, hardware: paced on the left wall)": ("        rw_cx = rw_phase ? rw_x0 : 0;", "        rw_cx = rw_x0;", "the player steps up and down in the DUO's way"),
    "walk: plans only around where the player is this instant (back and forth)": ("    if (rw_clock - rw_moved_at > RW_FORGET) return 0;", "    return 0;", "the player steps up and down in the DUO's way"),
    "walk: no patience - goes round the moment the player is in the way": ("        if (rw_clock - rw_wait_since < RW_PATIENCE) *k = 0;", "        if (0) *k = 0;", "the player steps up and down in the DUO's way"),
    "walk: crosses other seats (their scripts stop it there)": ("&& (x != rw_goal_x || y != rw_goal_y)) return 1;", "&& 0) return 1;", "the player steps up and down in the DUO's way"),
    "mix: makes for its usual seat even with the player on it": ("    if (rw[1 - me].x == seat_x && rw[1 - me].y == 6) seat_y = 4;", "", "the player sits in the DUO's seat"),
    "mix: the game's own sections not handed back": ("        if (a < b) memcpy(chunk + (a - lo), rx_buf + (a - lo), b - a);", "        if (0) memcpy(chunk + (a - lo), rx_buf + (a - lo), b - a);", "Record Mixing, the game as master"),
    "mix: the game's Battle Tower record handed back too": ("part_end[5] = { 0x1004, 0x1044, 0x1084, 0x10AC, 0x1124 };", "part_end[5] = { 0x1004, 0x1044, 0x1084, 0x10AC, 0x11C8 };", "Record Mixing, the game as master"),
    "mix: the game's chunk kept before ours is made from that round - our parts in it lost": ("        copy_pending = 1;                                      /* into RECORD once ours has gone */\n        if (mirror_wait", "        copy_pending = 1;                                      /* into RECORD once ours has gone */\n        memcpy(RECORD + CHUNK * r, rx_buf, CHUNK);\n        if (mirror_wait", "Record Mixing with a whole record"),
    "mix: the PC's record from the wrong place in the file": ("#define RECORD      (BLOB + 48)", "#define RECORD      (BLOB + 16)", "Record Mixing with a whole record"),
    "mix: as master, asks for the next round at once": ("if (++round_timer > ROUND_GAP)", "if (++round_timer > 0)", "Record Mixing, the DUO as master"),
    "mix: as master, starts before the game has its first chunk ready": ("#define START_WAIT  150", "#define START_WAIT  10", "Record Mixing, the DUO as master"),
    "mix: room keys sent all through the mixing": ("    if (game_lp_type == LT_MIX && room_keys_seen && !cafe_stopped) {", "    if (game_lp_type == LT_MIX && room_keys_seen) {", "Record Mixing, the game as master"),
    "mix: as master, opens the room again with the Cable Club's link type": ("    return state >= ST_MIXED ? LT_AFTER : LT_MIX;", "    return LT_MIX;", "Record Mixing, the DUO as master"),
    "mix: never follows the player out of the room": ("    if (game_exiting) { sent_exit = 1;", "    if (0) { sent_exit = 1;", "Record Mixing, the gift as player 1"),
    "mix: screen lines shown in the middle of a link session": ("if (shown == state || (linked && state != ST_DONE)) return;", "if (shown == state) return;", "Record Mixing, the game as master"),
    "mix: later rounds sent without waiting for the game's chunk": ("        else mirror_wait = 1;                                      /* wait", "        else send_round(r);                                      /* wait", "Record Mixing, the game as master"),
    "mix: the room's \"ready\" (0x2FFE) never answered - the game stays black (lab session 31)": ("        queue(0x2FFE, 0, 0);\n        barriers++;", "        barriers++;", "Record Mixing, the game as master"),
}

COLOSSEUM_MUTANTS = {      # firmware/programs/colosseum.c: the battle probe
    "colosseum: as player 0, sends the game's own signature - the DUO would have to run the battle": ("    if (is_master) { our_header[0] = 1; our_header[1] = 0; }", "    if (0) { our_header[0] = 1; our_header[1] = 0; }", "battle probe, the DUO as master"),
    "colosseum: its done carries the game's player ID": ("    u8 done[4] = { is_master ? 0 : 1, 0, 0, 0 };", "    u8 done[4] = { is_master ? 1 : 0, 0, 0, 0 };", "battle probe, the game as master"),
    "colosseum: to Emerald, an Emerald player (the recorded battle's steps follow)": ("    return v == 3 ? 2 : v;", "    return v;", "battle partner: Emerald"),
    "colosseum: no progress flags for FireRed/LeafGreen": ("        lp[0x10] = 0x11;                                     /* (as trade.c", "        lp[0x10] = 0;                                        /* (as trade.c", "battle partner: FireRed and LeafGreen"),
    "colosseum: done to a choice without its answer": ("    battle_block(hdr, 1, r, kind == 2 ? 5 : 4);", "", "battle probe, the game as master"),
    "colosseum: never chooses by itself when the PC is silent": ("        if (t - since < wait) continue;", "        if (t - since < wait || 1) continue;", "when the PC stops choosing"),
    "colosseum: the PC's polls don't hold off its own choice": ("        u32 since = pc_alive_at - pend_since[side] < 0x80000000u ? pc_alive_at : pend_since[side];", "        u32 since = pend_since[side];", "the impossible level waits"),
    "colosseum: the PC's move answer not checked for PP": ("        if (value > 3 || !(pend_moves[side] >> value & 1) ||", "        if (value > 3 ||", "the PC's answer breaks the rules"),
    "colosseum: an answer against the rules is sent anyway": ("    answer_choice(pend_hdr[side], kind, ok ? r : pend_fb[side]);", "    answer_choice(pend_hdr[side], kind, r);", "the PC's answer breaks the rules"),
    "colosseum: answers for the game's battlers too": ("ours = battler & 1,", "ours = 1,", "battle probe, the game as master"),
    "colosseum: sends in a Pokemon still on the field (a double)": ("fainted >> i & 1 || i == on_field[0] || i == on_field[1]", "fainted >> i & 1", "battle probe: a double battle"),
    "colosseum: never takes the other spot when the player is on ours": ("    if (rw[other].x == spot_x && rw[other].y == 5) spot_x = 13 - spot_x;", "    (void)other;", "battle probe: the player stands on the DUO's usual spot"),
    "colosseum: the battle's close (0x5FFF) not answered": ("        queue(0x5FFF, 0, 0);\n        log_event(E_CLOSE, state);", "        log_event(E_CLOSE, state);", "battle probe, the game as master"),
    "colosseum: as master, opens the battle's link with the room's link type": ("    return state == ST_SEATED ? LT_BATTLE : doubles ? LT_DOUBLE : LT_SINGLE;", "    return doubles ? LT_DOUBLE : LT_SINGLE;", "battle probe, the DUO as master"),
    "colosseum: aims at its own side in a double": ("r[3] = battler ^ 1;", "r[3] = battler ^ 2;", "battle probe: a double battle"),
}

TOWER_MUTANTS = {          # firmware/programs/tower.c: the Battle Tower's link multi battle (8 November)
    "tower: our choice sent before our link player has gone": ("    if (state == ST_RETIRE && !choice_sent && !tx_on && !player_pending) {", "    if (state == ST_RETIRE && !choice_sent) {", "Battle Tower link multi battle (8 November)"),
    "tower: never retires": ("        small[0] = RETIRE_AFTER && battles >= RETIRE_AFTER;", "        small[0] = 0;", "the DUO retires after the first battle"),
    "tower: the trainers' list never answered": ("        else if (size == 40 && lobby_blocks == 1) { memcpy(small, b, 40); send_block(small, 40); lobby_blocks = 2; }", "", "Battle Tower link multi battle (8 November)"),
    "tower: answers the Tower trainers' battlers too": ("    u32 battler = b[1], cmd = b[8], ours = battler == OUR_BATTLER, side = 0;", "    u32 battler = b[1], cmd = b[8], ours = battler & 1, side = 0;", "Battle Tower link multi battle (8 November)"),
    "tower: the opening's third party block left out": ("    else if (start_out == 2) send_block(PARTY + 200, 100);       /* a third (none) */", "    else if (start_out == 2) send_block(zeros, 200);", "Battle Tower link multi battle (8 November)"),
    "tower: a carry-on after a loss": ("        retire_next = outcome == 1 && battles < 7;", "        retire_next = battles < 7;", "the first battle is lost"),
}

BLENDER_MUTANTS = {        # firmware/programs/blender.c: the Berry Blender partner (8 November)
    "blender: the arrow drifts from the game's": ("    arrow = (arrow + speed) & 0xFFFF;                        /* UpdateBlenderCenter */", "    arrow = (arrow + speed + 0x300) & 0xFFFF;", "Berry Blender (8 November)"),
    "blender: claims the best spot whatever the arrow": ("code = prox == 2 ? HIT_BEST : HIT_GOOD;", "code = HIT_BEST;", "Berry Blender (8 November)"),
    "blender: a good hit speeds the arrow above 1500 too": ("    else if (code == HIT_GOOD) { if (speed < 1500) speed += 256;", "    else if (code == HIT_GOOD) { speed += 256;", "Berry Blender (8 November)"),
    "blender: the same berry as the player's": ("    while (k + 1 < n && (BERRIES[16 * k] | BERRIES[16 * k + 1] << 8) == game_item) k++;", "    (void)n; (void)game_item;", "the player brings an Oran too"),
    "blender: always says yes to another blend": ("        u32 again = blends + 1 < (BLENDS ? BLENDS : 1);", "        u32 again = 1;", "Berry Blender (8 November)"),
    "blender: the answer to 'another berry?' never sent": ("        queue(SEND_PACKET, answered, 0);                     /* \"blend another berry?\" */", "", "Berry Blender (8 November)"),
    "blender: a \"ready\" barrier not answered": ("        queue(0x2FFE, 0, 0);\n        barriers++;", "        barriers++;", "Berry Blender (8 November)"),
    "blender: the link's close not answered": ("        queue(0x5FFF, 0, 0);\n        log_event(E_CLOSE, state);", "        log_event(E_CLOSE, state);", "Berry Blender (8 November)"),
}

CONTEST_MUTANTS = {        # firmware/programs/contest.c: Emerald's link Contest (8 November)
    "contest: says it's a Ruby player": ("    lp[0] = 3; lp[1] = game_player[17];", "    lp[0] = 2; lp[1] = game_player[17];", "Contest (8 November)"),
    "contest: answers the leader's random seed": ("((size == 4 && !seed_seen) || size == 2 * MON_SIZE)", "(size == 2 * MON_SIZE)", "Contest (8 November)"),
    "contest: answers the leader's AI contestants": ("((size == 4 && !seed_seen) || size == 2 * MON_SIZE)", "(size == 4 && !seed_seen)", "Contest (8 November)"),
    "contest: sends the game's move back, not its own": ("    if (state >= ST_CONTEST && size == 2) {", "    if (0) {", "Contest (8 November)"),
    "contest: its contestant number is the game's": ("        ours[0] = is_master ? 0 : 1;", "        ours[0] = 0;", "Contest (8 November)"),
    "contest: a block sent back a byte short": ("        send_block(blk, size);", "        send_block(blk, size - 1);", "Contest (8 November)"),
    "contest: a \"ready\" barrier not answered": ("        queue(0x2FFE, 0, 0);\n        barriers++;", "        barriers++;", "Contest (8 November)"),
}

LAB4P_MUTANTS = {          # firmware/programs/lab4p.c: the four-player cable experiment (8 November)
    "lab4p: bits sent from the highest": ("        set_pins(w >> i & 1 ? rc | P_SD : rc & ~P_SD);", "        set_pins(w >> (15 - i) & 1 ? rc | P_SD : rc & ~P_SD);", "lab4p (8 November)"),
    "lab4p: no stop bit": ("    set_pins(rc | P_SD);                                     /* the stop bit: high */", "    set_pins(rc & ~P_SD);", "lab4p (8 November)"),
    "lab4p: the game never given its turn (SO)": ("    set_pins(rc & ~P_SO);                                    /* SO low: the game's turn */", "    set_pins(rc);", "lab4p (8 November)"),
    "lab4p: SD still driven after our word": ("    set_pins(rc & ~OUT(P_SD));                               /* SD back to an input (the game's turn) */", "", "lab4p (8 November)"),
    "lab4p: checksums over two slots with three players": ("        u16 ck = PLAYERS >= 3 ? sum_four : sum_two;", "        u16 ck = sum_two;", "lab4p (8 November)"),
    "lab4p: the first transfer after the handshake taken as data": ("            send_idx = CMD_LEN; recv_idx = 0; cycles = 0;", "            send_idx = 0; recv_idx = 0; cycles = 0;", "lab4p (8 November)"),
}

KINDS = {"fw": FW_MUTANTS, "fw42": FW42_MUTANTS, "prog": PROG_MUTANTS, "ereader": EREADER_MUTANTS, "trade": TRADE_MUTANTS,
         "mix": MIX_MUTANTS, "colosseum": COLOSSEUM_MUTANTS, "tower": TOWER_MUTANTS, "blender": BLENDER_MUTANTS, "contest": CONTEST_MUTANTS,
         "lab4p": LAB4P_MUTANTS,
         "pc": PC_MUTANTS}


def runnable_kinds():
    """The fw and fw42 kinds rebuild from Datel's untouched firmware; leave them out without it."""
    import paths
    if paths.build_file("fw.bin", required=False):
        return list(KINDS)
    return [k for k in KINDS if k not in ("fw", "fw42")]


def run_many(kinds=None, jobs=None):
    """Run every planted bug of the given kinds (default: all that can run here). True if all were caught."""
    import concurrent.futures as cf
    kinds = [k for k in (kinds or runnable_kinds()) if k in runnable_kinds()]
    todo = [(k, n) for k in kinds for n in KINDS[k]]
    jobs = jobs or max(1, os.cpu_count() or 2)
    print(f"{len(todo)} planted bugs ({', '.join(kinds)}), {jobs} at a time", flush=True)
    def one(kn):
        try:
            return run(*kn)
        except Exception as e:                 # a planted bug that no longer fits the code: a failure,
            print(f"BROKEN  {kn[0]}: {kn[1]}  ->  {type(e).__name__}: {e}", flush=True)   # not a crash
            return False
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        ok = all(list(pool.map(one, todo)))
    print("every planted bug was caught" if ok else "SOME PLANTED BUGS WERE MISSED", flush=True)
    return ok


if __name__ == "__main__":
    if len(sys.argv) == 3 and not sys.argv[2].startswith("--"):
        ok = run(sys.argv[1], sys.argv[2])
    else:
        jobs = next((int(a.split("=", 1)[1]) for a in sys.argv[1:] if a.startswith("--jobs=")), None)
        kinds = [a for a in sys.argv[1:] if not a.startswith("--")] or None
        ok = run_many(kinds, jobs)
    sys.exit(0 if ok else 1)
