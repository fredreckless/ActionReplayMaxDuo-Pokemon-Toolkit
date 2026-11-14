"""profiles.py - what savegen.py needs to know about each game: addresses in RAM and code, and where
the Cable Club's attendants stand. Facts about the games (from pret's symbols where there are
some), not Nintendo's data. Picked by the ROM's header (game code and version byte)."""


class RubyEnglish11:
    TITLE = "English Ruby 1.1"
    SAVE_NAME = "ruby.sav"
    ORIGIN_GAME = 2                       # the party's game of origin (pk3: 2 Ruby)
    LANGUAGE = 2                          # the party's language (1 Japanese, 2 English, 3 French, ...)
    NAME_LENGTH = 7                       # the player's name (Japanese games: 5)
    # RAM (pret pokeruby, symbols/pokeruby_rev1.sym)
    gMain = 0x03001770
    gTasks = 0x03004B20
    gObjectEvents = 0x030048A0
    gPlayerPartyCount = 0x03004350
    gPlayerParty = 0x03004360
    sb1 = 0x02025734                      # gSaveBlock1 (Ruby's save blocks don't move)
    sb2 = 0x02024EA4                      # gSaveBlock2
    sStartMenuCursorPos = 0x0202E8FC
    sNumStartMenuActions = 0x0202E8FD
    sCurrentStartMenuActions = 0x0202E8FE
    gBattleMons, gMoveSelectionCursor, gBattlerControllerFuncs = 0x02024A80, 0x02024E64, 0x03004330
    BLENDER = (0x03004854, 0x54, 0xA2)    # gBerryBlenderData (a pointer), and in it arrowPos, playerIdToArrowId
    SB1_FLAGS, SB1_KEYITEMS, SB1_BERRIES = 0x1220, 0x5B0, 0x740
    # code
    sym = {
        "CB2_Overworld": 0x080543C4,
        "CB2_MainMenu": 0x080096C4,
        "CB2_NamingScreen": 0x080B5AC0,          # (sub_80B5AA0 in pokeruby)
        "CB2_MysteryEventMenu": 0x08146A04,
        "Task_StartMenu": 0x080712D4,          # (sub_80712B4: the START menu's task once open)
        "Task_HandleYesNoInput": 0x080B5504,
        "Task_HandleMultichoiceInput": 0x080B52D4,
        "CB2_PartyMenu": 0x0806AEFC,           # CB2_PartyMenuMain
        "HandleInputChooseMove": 0x0802C68C,   # (the rehearsals: a move with PP left)
    }
    NAMING_CB2 = "CB2_NamingScreen"
    MENU_ACTION_SAVE = 5
    CABLE_CLUB_MENU = None                # Ruby: an attendant for each room
    ITEM_POKEBLOCK_CASE, ITEM_CHERI_BERRY = 273, 133
    SYS = 0x800
    FLAGS = [
        SYS + 0x00,       # FLAG_SYS_POKEMON_GET
        SYS + 0x01,       # FLAG_SYS_POKEDEX_GET: the Colosseum and the Trade Center
        SYS + 0x0F, SYS + 0x10, SYS + 0x17,   # visited Littleroot, Oldale, Slateport
        SYS + 0x18,       # FLAG_VISITED_MAUVILLE_CITY: the Record Corner
        SYS + 0x1B, SYS + 0x1C,               # visited Lilycove, Mossdeep
        SYS + 0x35,       # FLAG_SYS_CLOCK_SET
        SYS + 0x4C,       # FLAG_SYS_EXDATA_ENABLE: MYSTERY EVENTS on the title menu
        SYS + 0x60,       # FLAG_SYS_B_DASH (Running Shoes)
        0x5F,             # FLAG_RECEIVED_POKEBLOCK_CASE
        0x60,             # FLAG_RECEIVED_SECRET_POWER: Record Mixing only takes in Secret Bases after it
    ]
    PARTY = ["SCEPTILE", "BLAZIKEN", "SWAMPERT", "MANECTRIC", "AGGRON", "JIRACHI"]
    PARTY_LEVEL = 50
    # maps (group, number): Mossdeep's Pokemon Center upper floor (14, 4), Lilycove's Contest Lobby
    # (13, 4). The attendants stand behind the counters at x = 4 (Colosseum), 7 (Trade Center) and
    # 10 (Record Corner), y = 2; the link Berry Blender is to the right of (17, 5).
    HOME = (14, 4, 7, 4)
    QUESTION = ("Task_HandleYesNoInput", "Task_HandleMultichoiceInput")
    STATES = [
        dict(name="at_trade_question", kind="talk", warp=(14, 4, 7, 4), face="UP", task=QUESTION),
        dict(name="at_colosseum_question", kind="talk", warp=(14, 4, 4, 4), face="UP", task=QUESTION),
        dict(name="at_record_question", kind="talk", warp=(14, 4, 10, 4), face="UP", task=QUESTION),
        dict(name="at_blender_question", kind="talk", warp=(13, 4, 17, 5), face="RIGHT", task=QUESTION),
        dict(name="at_link_standby", kind="title_menu", downs=2, until="CB2_MysteryEventMenu", press_first=True),
    ]


class EmeraldEnglish:
    TITLE = "English Emerald"
    SAVE_NAME = "emerald.sav"
    ORIGIN_GAME = 3
    LANGUAGE, NAME_LENGTH = 2, 7
    # RAM (pret pokeemerald, symbols/pokeemerald.sym). The save blocks move: through the pointers.
    gMain = 0x030022C0
    gTasks = 0x03005E00
    gObjectEvents = 0x02037350
    gPlayerPartyCount = 0x020244E9
    gPlayerParty = 0x020244EC
    sb1_ptr = 0x03005D8C                  # gSaveBlock1Ptr
    sb2_ptr = 0x03005D90                  # gSaveBlock2Ptr
    SB2_KEY = 0xAC                        # encryptionKey: bag quantities are XORed with its low half
    sStartMenuCursorPos = 0x0203760E
    sNumStartMenuActions = 0x0203760F
    sCurrentStartMenuActions = 0x02037610
    gSelectedOrderFromParty = 0x0203CEF8  # (the Battle Frontier's choice of Pokemon: the tower rehearsal)
    gPartyMenu = 0x0203CEC8               # (slotId at +9: the rehearsals' party screen after a faint)
    gBattleMons, gMoveSelectionCursor, gBattlerControllerFuncs = 0x02024084, 0x020244B0, 0x03005D60
    BLENDER = (0x020322A4, 0x4A, 0x96)    # sBerryBlender (a pointer), and in it arrowPos, playerIdToArrowId
    SB1_FLAGS, SB1_KEYITEMS, SB1_BERRIES = 0x1270, 0x5D8, 0x790
    sym = {
        "CB2_Overworld": 0x08085E5C,
        "CB2_MainMenu": 0x0802F6B0,
        "CB2_NamingScreen": 0x080E4F58,
        "Task_StartMenu": 0x0809FA34,          # Task_ShowStartMenu: the START menu's task once open
        "Task_HandleYesNoInput": 0x080E215C,
        "Task_HandleMultichoiceInput": 0x080E2058,
        "Task_MysteryGift": 0x080191F4,
        "CB2_PartyMenu": 0x081B01B0,           # CB2_UpdatePartyMenu
        "HandleInputChooseMove": 0x08057BFC,
    }
    NAMING_CB2 = "CB2_NamingScreen"
    MENU_ACTION_SAVE = 5
    ITEM_POKEBLOCK_CASE, ITEM_CHERI_BERRY = 273, 133
    SYS = 0x860
    FLAGS = [
        SYS + 0x00, SYS + 0x01,               # the Pokemon, the Pokedex (the Cable Club wants it)
        SYS + 0x0F, SYS + 0x10, SYS + 0x17,   # visited Littleroot, Oldale, Slateport
        SYS + 0x18,                           # FLAG_VISITED_MAUVILLE_CITY: RECORD CORNER on the menu
        SYS + 0x1B, SYS + 0x1C,               # visited Lilycove, Mossdeep
        SYS + 0x35,                           # FLAG_SYS_CLOCK_SET
        SYS + 0x60,                           # FLAG_SYS_B_DASH
        SYS + 0x7B,                           # FLAG_SYS_MYSTERY_GIFT_ENABLE: MYSTERY GIFT on the title menu
        0x5F,                                 # FLAG_RECEIVED_POKEBLOCK_CASE
        0x60,                                 # FLAG_RECEIVED_SECRET_POWER (Secret Bases in Record Mixing)
    ]
    PARTY = RubyEnglish11.PARTY
    PARTY_LEVEL = 50
    # Mossdeep's Pokemon Center upper floor (14, 4): Emerald's attendants stand at y = 2, the
    # Wireless Club's at x = 2, the Union Room's at 6 and the Direct Corner's at 10, which (with no
    # Wireless Adapter) is the Cable Club: TRADE CENTER, COLOSSEUM, RECORD CORNER. Lilycove's Contest
    # Lobby (13, 4): the link Berry Blender at (23, 5); the link contest receptionist at (15, 2).
    HOME = (14, 4, 10, 4)
    CABLE_CLUB_MENU = ["TRADE CENTER", "COLOSSEUM", "RECORD CORNER"]     # (the rehearsals choose from it)
    QUESTION = RubyEnglish11.QUESTION
    STATES = [
        dict(name="at_cable_club_menu", kind="talk", warp=(14, 4, 10, 4), face="UP", task=QUESTION),
        dict(name="at_blender_question", kind="talk", warp=(13, 4, 22, 5), face="RIGHT", task=QUESTION),
        dict(name="at_contest_question", kind="talk", warp=(13, 4, 15, 4), face="UP", task=QUESTION),
        # the Battle Tower lobby (26, 5): the link multi battle attendant at (18, 5)
        dict(name="at_tower_link_question", kind="talk", warp=(26, 5, 18, 7), face="UP", task=QUESTION),
        # English Emerald's MYSTERY GIFT wants the Wireless Adapter before it opens (the DUO's part):
        # so the state is the title menu with MYSTERY GIFT highlighted, for the rehearsal to press A
        dict(name="at_title_mystery_gift", kind="title_menu", downs=2, select_only=True),
    ]


class LeafGreenEnglish11:
    TITLE = "English LeafGreen 1.1"
    SAVE_NAME = "leafgreen.sav"
    ORIGIN_GAME = 5
    LANGUAGE, NAME_LENGTH = 2, 7
    # RAM (pret pokefirered, symbols/pokeleafgreen_rev1.sym)
    gMain = 0x030030F0
    gTasks = 0x03005090
    gObjectEvents = 0x02036E38
    gPlayerPartyCount = 0x02024029
    gPlayerParty = 0x02024284
    sb1_ptr = 0x03005008
    sb2_ptr = 0x0300500C
    SB2_KEY = 0xF20
    sStartMenuCursorPos = 0x020370F4
    sNumStartMenuActions = 0x020370F5     # sNumStartMenuItems
    sCurrentStartMenuActions = 0x020370F6 # sStartMenuOrder
    gPartyMenu = 0x0203B0A0
    gBattleMons, gMoveSelectionCursor, gBattlerControllerFuncs = 0x02023BE4, 0x02023FFC, 0x03004FE0
    SB1_FLAGS, SB1_KEYITEMS, SB1_BERRIES = 0x0EE0, 0x3B8, 0x54C
    sym = {
        "CB2_Overworld": 0x080565C8,
        "CB2_MainMenu": 0x0800C2E8,
        "CB2_NamingScreen": 0x0809FB58,
        "Task_StartMenu": 0x0806F204,          # Task_StartMenuHandleInput
        "Task_HandleYesNoInput": 0x0809CE3C,   # Task_YesNoMenu_HandleInput
        "Task_HandleMultichoiceInput": 0x0809CC80,   # Task_MultichoiceMenu_HandleInput
        "Task_MysteryGift": 0x08142EF0,
        "CB2_PartyMenu": 0x0811EBF0,           # CB2_UpdatePartyMenu
        "HandleInputChooseMove": 0x0802EA24,
    }
    NAMING_CB2 = "CB2_NamingScreen"
    MENU_ACTION_SAVE = 4                  # (FireRed/LeafGreen have no POKeNAV)
    ITEM_POKEBLOCK_CASE, ITEM_CHERI_BERRY = None, 133
    SYS = 0x800
    FLAGS = [
        SYS + 0x28, SYS + 0x29,               # FLAG_SYS_POKEMON_GET, FLAG_SYS_POKEDEX_GET
        SYS + 0x2F,                           # FLAG_SYS_B_DASH
        SYS + 0x39,                           # FLAG_SYS_MYSTERY_GIFT_ENABLED
        SYS + 0x91,                           # FLAG_WORLD_MAP_VIRIDIAN_CITY
    ]
    PARTY = ["VENUSAUR", "CHARIZARD", "BLASTOISE", "PIKACHU", "SNORLAX", "LAPRAS"]
    PARTY_LEVEL = 50
    # Viridian City's Pokemon Center upper floor (5, 5), laid out as Emerald's: the Direct Corner's
    # attendant at (10, 2) is the Cable Club with no Wireless Adapter (TRADE CENTER, COLOSSEUM).
    HOME = (5, 5, 10, 4)
    CABLE_CLUB_MENU = ["TRADE CENTER", "COLOSSEUM"]
    QUESTION = RubyEnglish11.QUESTION
    STATES = [
        dict(name="at_cable_club_menu", kind="talk", warp=(5, 5, 10, 4), face="UP", task=QUESTION),
        dict(name="at_title_mystery_gift", kind="title_menu", downs=2, select_only=True),
    ]


# Addresses for the other languages, found by findsyms.py from pret's English symbols (13 November
# 2026): code by its masked bytes, RAM by the literal pools of the functions that use it. None:
# not found (the Japanese naming screens differ; mashing A gets through them instead).
# sBerryBlender (BLENDER) is at English's address in the other European languages; Japanese's is set below.
DERIVED = {
    "BPED": dict(gBattleMons=0x02024084, gMoveSelectionCursor=0x020244B0, gBattlerControllerFuncs=0x03005D60, gPartyMenu=0x0203CEC8, gSelectedOrderFromParty=0x0203CEF8, gMain=0x030022C0, gTasks=0x03005E00, gObjectEvents=0x02037350, gPlayerPartyCount=0x020244E9, gPlayerParty=0x020244EC, sb1_ptr=0x03005D8C, sb2_ptr=0x03005D90, sStartMenuCursorPos=0x0203760E, sNumStartMenuActions=0x0203760F, sCurrentStartMenuActions=0x02037610,
                 sym=dict(HandleInputChooseMove=0x08057C00, CB2_Overworld=0x08085E78, CB2_MainMenu=0x0802F6B4, CB2_NamingScreen=0x080E4BC0, Task_StartMenu=0x0809FA50, Task_HandleYesNoInput=0x080E1DB4, Task_HandleMultichoiceInput=0x080E1CB0, Task_MysteryGift=0x080191F4, CB2_PartyMenu=0x081AFCD8)),
    "BPEF": dict(gBattleMons=0x02024084, gMoveSelectionCursor=0x020244B0, gBattlerControllerFuncs=0x03005D60, gPartyMenu=0x0203CEC8, gSelectedOrderFromParty=0x0203CEF8, gMain=0x030022C0, gTasks=0x03005E00, gObjectEvents=0x02037350, gPlayerPartyCount=0x020244E9, gPlayerParty=0x020244EC, sb1_ptr=0x03005D8C, sb2_ptr=0x03005D90, sStartMenuCursorPos=0x0203760E, sNumStartMenuActions=0x0203760F, sCurrentStartMenuActions=0x02037610,
                 sym=dict(HandleInputChooseMove=0x08057BFC, CB2_Overworld=0x08085E6C, CB2_MainMenu=0x0802F6B0, CB2_NamingScreen=0x080E4BE0, Task_StartMenu=0x0809FA48, Task_HandleYesNoInput=0x080E1DD4, Task_HandleMultichoiceInput=0x080E1CD0, Task_MysteryGift=0x080191F4, CB2_PartyMenu=0x081AFDEC)),
    "BPEI": dict(gBattleMons=0x02024084, gMoveSelectionCursor=0x020244B0, gBattlerControllerFuncs=0x03005D60, gPartyMenu=0x0203CEC8, gSelectedOrderFromParty=0x0203CEF8, gMain=0x030022C0, gTasks=0x03005E00, gObjectEvents=0x02037350, gPlayerPartyCount=0x020244E9, gPlayerParty=0x020244EC, sb1_ptr=0x03005D8C, sb2_ptr=0x03005D90, sStartMenuCursorPos=0x0203760E, sNumStartMenuActions=0x0203760F, sCurrentStartMenuActions=0x02037610,
                 sym=dict(HandleInputChooseMove=0x08057C00, CB2_Overworld=0x08085E70, CB2_MainMenu=0x0802F6B4, CB2_NamingScreen=0x080E4BAC, Task_StartMenu=0x0809FA48, Task_HandleYesNoInput=0x080E1DAC, Task_HandleMultichoiceInput=0x080E1CA8, Task_MysteryGift=0x080191F4, CB2_PartyMenu=0x081AFCB8)),
    "BPEJ": dict(BLENDER=(0x02031F44, 0x4A, 0x96), gBattleMons=0x02023D28, gMoveSelectionCursor=0x02024154, gBattlerControllerFuncs=0x03005AC0, gPartyMenu=0x0203CB94, gSelectedOrderFromParty=0x0203CBC4, gMain=0x03002360, gTasks=0x03005B60, gObjectEvents=0x02036FF0, gPlayerPartyCount=0x0202418D, gPlayerParty=0x02024190, sb1_ptr=0x03005AEC, sb2_ptr=0x03005AF0, sStartMenuCursorPos=0x020372AE, sNumStartMenuActions=0x020372AF, sCurrentStartMenuActions=0x020372B0,
                 sym=dict(HandleInputChooseMove=0x0805780C, CB2_Overworld=0x080857C4, CB2_MainMenu=0x0802F314, CB2_NamingScreen=None, Task_StartMenu=0x0809F30C, Task_HandleYesNoInput=0x080E166C, Task_HandleMultichoiceInput=0x080E1568, Task_MysteryGift=0x08018C5C, CB2_PartyMenu=0x081AFE88)),
    "BPES": dict(gBattleMons=0x02024084, gMoveSelectionCursor=0x020244B0, gBattlerControllerFuncs=0x03005D60, gPartyMenu=0x0203CEC8, gSelectedOrderFromParty=0x0203CEF8, gMain=0x030022C0, gTasks=0x03005E00, gObjectEvents=0x02037350, gPlayerPartyCount=0x020244E9, gPlayerParty=0x020244EC, sb1_ptr=0x03005D8C, sb2_ptr=0x03005D90, sStartMenuCursorPos=0x0203760E, sNumStartMenuActions=0x0203760F, sCurrentStartMenuActions=0x02037610,
                 sym=dict(HandleInputChooseMove=0x08057BFC, CB2_Overworld=0x08085E70, CB2_MainMenu=0x0802F6B0, CB2_NamingScreen=0x080E4BB4, Task_StartMenu=0x0809FA48, Task_HandleYesNoInput=0x080E1DB4, Task_HandleMultichoiceInput=0x080E1CB0, Task_MysteryGift=0x080191F4, CB2_PartyMenu=0x081AFDD0)),
    "BPGD": dict(gBattleMons=0x02023BE4, gMoveSelectionCursor=0x02023FFC, gBattlerControllerFuncs=0x03004F30, gPartyMenu=0x0203B0A0, gMain=0x03003040, gTasks=0x03004FE0, gObjectEvents=0x02036E38, gPlayerPartyCount=0x02024029, gPlayerParty=0x02024284, sb1_ptr=0x03004F58, sb2_ptr=0x03004F5C, sStartMenuCursorPos=0x020370F4, sNumStartMenuActions=0x020370F5, sCurrentStartMenuActions=0x020370F6,
                 sym=dict(HandleInputChooseMove=0x0802E9A8, CB2_Overworld=0x080565D4, CB2_MainMenu=0x0800C254, CB2_NamingScreen=0x0809FC38, Task_StartMenu=0x0806F154, Task_HandleYesNoInput=0x0809CF0C, Task_HandleMultichoiceInput=0x0809CD50, Task_MysteryGift=0x08142F28, CB2_PartyMenu=0x0811EBAC)),
    "BPGF": dict(gBattleMons=0x02023BE4, gMoveSelectionCursor=0x02023FFC, gBattlerControllerFuncs=0x03004F30, gPartyMenu=0x0203B0A0, gMain=0x03003040, gTasks=0x03004FE0, gObjectEvents=0x02036E38, gPlayerPartyCount=0x02024029, gPlayerParty=0x02024284, sb1_ptr=0x03004F58, sb2_ptr=0x03004F5C, sStartMenuCursorPos=0x020370F4, sNumStartMenuActions=0x020370F5, sCurrentStartMenuActions=0x020370F6,
                 sym=dict(HandleInputChooseMove=0x0802E980, CB2_Overworld=0x08056694, CB2_MainMenu=0x0800C240, CB2_NamingScreen=0x0809FCF8, Task_StartMenu=0x0806F214, Task_HandleYesNoInput=0x0809CFCC, Task_HandleMultichoiceInput=0x0809CE10, Task_MysteryGift=0x08142FE4, CB2_PartyMenu=0x0811EC6C)),
    "BPGI": dict(gBattleMons=0x02023BE4, gMoveSelectionCursor=0x02023FFC, gBattlerControllerFuncs=0x03004F30, gPartyMenu=0x0203B0A0, gMain=0x03003040, gTasks=0x03004FE0, gObjectEvents=0x02036E38, gPlayerPartyCount=0x02024029, gPlayerParty=0x02024284, sb1_ptr=0x03004F58, sb2_ptr=0x03004F5C, sStartMenuCursorPos=0x020370F4, sNumStartMenuActions=0x020370F5, sCurrentStartMenuActions=0x020370F6,
                 sym=dict(HandleInputChooseMove=0x0802E994, CB2_Overworld=0x080565C0, CB2_MainMenu=0x0800C254, CB2_NamingScreen=0x0809FC18, Task_StartMenu=0x0806F140, Task_HandleYesNoInput=0x0809CEF8, Task_HandleMultichoiceInput=0x0809CD3C, Task_MysteryGift=0x08142F68, CB2_PartyMenu=0x0811EBF0)),
    "BPGJ": dict(gBattleMons=0x02023B44, gMoveSelectionCursor=0x02023F5C, gBattlerControllerFuncs=0x03005020, gPartyMenu=0x0203B014, gMain=0x03003130, gTasks=0x030050D0, gObjectEvents=0x02036D6C, gPlayerPartyCount=0x02023F89, gPlayerParty=0x020241E4, sb1_ptr=0x03005048, sb2_ptr=0x0300504C, sStartMenuCursorPos=0x02037028, sNumStartMenuActions=0x02037029, sCurrentStartMenuActions=0x0203702A,
                 sym=dict(HandleInputChooseMove=0x0802E1EC, CB2_Overworld=0x08055E74, CB2_MainMenu=0x0800BCB4, CB2_NamingScreen=None, Task_StartMenu=0x0806E9E4, Task_HandleYesNoInput=0x0809C85C, Task_HandleMultichoiceInput=0x0809C6A0, Task_MysteryGift=0x08143580, CB2_PartyMenu=0x0811F380)),
    "BPGS": dict(gBattleMons=0x02023BE4, gMoveSelectionCursor=0x02023FFC, gBattlerControllerFuncs=0x03004F30, gPartyMenu=0x0203B0A0, gMain=0x03003040, gTasks=0x03004FE0, gObjectEvents=0x02036E38, gPlayerPartyCount=0x02024029, gPlayerParty=0x02024284, sb1_ptr=0x03004F58, sb2_ptr=0x03004F5C, sStartMenuCursorPos=0x020370F4, sNumStartMenuActions=0x020370F5, sCurrentStartMenuActions=0x020370F6,
                 sym=dict(HandleInputChooseMove=0x0802E994, CB2_Overworld=0x080566A8, CB2_MainMenu=0x0800C240, CB2_NamingScreen=0x0809FD00, Task_StartMenu=0x0806F228, Task_HandleYesNoInput=0x0809CFE0, Task_HandleMultichoiceInput=0x0809CE24, Task_MysteryGift=0x08143054, CB2_PartyMenu=0x0811ECD8)),
}

LANGUAGES = {"J": ("Japanese", 1), "E": ("English", 2), "F": ("French", 3), "I": ("Italian", 4),
             "D": ("German", 5), "S": ("Spanish", 7)}


def derived(code, version):
    """A profile for another language: the English one with the addresses findsyms.py found.
    Save layouts, flags, items and maps are the same in every language."""
    base = {"BPE": EmeraldEnglish, "BPG": LeafGreenEnglish11}.get(code[:3])
    if base is None or code not in DERIVED or version != 0:
        return None
    lang, lang_id = LANGUAGES[code[3]]
    d = dict(DERIVED[code])
    sym = dict(base.sym)
    sym.update(d.pop("sym"))
    attrs = dict(d, sym=sym, LANGUAGE=lang_id, NAME_LENGTH=5 if lang_id == 1 else 7,
                 TITLE=base.TITLE.replace("English", lang).replace(" 1.1", ""),
                 SAVE_NAME=base.SAVE_NAME.replace(".sav", f"_{code[3].lower()}.sav"))
    if sym.get("CB2_NamingScreen") is None:
        attrs["NAMING_CB2"] = None
    return type(f"{base.__name__}_{code}", (base,), attrs)


def for_rom(path):
    with open(path, "rb") as f:
        head = f.read(0xC0)
    code, version = head[0xAC:0xB0].decode("latin-1"), head[0xBC]
    if code == "AXVE" and version == 1:
        return RubyEnglish11
    if code == "BPEE" and version == 0:
        return EmeraldEnglish
    if code == "BPGE" and version == 1:
        return LeafGreenEnglish11
    prof = derived(code, version)
    if prof:
        return prof
    raise SystemExit(f"no profile yet for game code {code} version {version}")
