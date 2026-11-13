"""profiles.py - what savegen.py needs to know about each game: addresses in RAM and code, and where
the Cable Club's attendants stand. Facts about the games (from pret's symbols where there are
some), not Nintendo's data. Picked by the ROM's header (game code and version byte)."""


class RubyEnglish11:
    TITLE = "English Ruby 1.1"
    SAVE_NAME = "ruby.sav"
    ORIGIN_GAME = 2                       # the party's game of origin (pk3: 2 Ruby)
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
    }
    NAMING_CB2 = "CB2_NamingScreen"
    MENU_ACTION_SAVE = 5
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
    SB1_FLAGS, SB1_KEYITEMS, SB1_BERRIES = 0x1270, 0x5D8, 0x790
    sym = {
        "CB2_Overworld": 0x08085E5C,
        "CB2_MainMenu": 0x0802F6B0,
        "CB2_NamingScreen": 0x080E4F58,
        "Task_StartMenu": 0x0809FA34,          # Task_ShowStartMenu: the START menu's task once open
        "Task_HandleYesNoInput": 0x080E215C,
        "Task_HandleMultichoiceInput": 0x080E2058,
        "Task_MysteryGift": 0x080191F4,
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
    ]
    PARTY = RubyEnglish11.PARTY
    PARTY_LEVEL = 50
    # Mossdeep's Pokemon Center upper floor (14, 4): Emerald's attendants stand at y = 2, the
    # Wireless Club's at x = 2, the Union Room's at 6 and the Direct Corner's at 10, which (with no
    # Wireless Adapter) is the Cable Club: TRADE CENTER, COLOSSEUM, RECORD CORNER. Lilycove's Contest
    # Lobby (13, 4): the link Berry Blender at (23, 5); the link contest receptionist at (15, 2).
    HOME = (14, 4, 10, 4)
    QUESTION = RubyEnglish11.QUESTION
    STATES = [
        dict(name="at_cable_club_menu", kind="talk", warp=(14, 4, 10, 4), face="UP", task=QUESTION),
        dict(name="at_blender_question", kind="talk", warp=(13, 4, 22, 5), face="RIGHT", task=QUESTION),
        dict(name="at_contest_question", kind="talk", warp=(13, 4, 15, 4), face="UP", task=QUESTION),
        # English Emerald's MYSTERY GIFT wants the Wireless Adapter before it opens (the DUO's part):
        # so the state is the title menu with MYSTERY GIFT highlighted, for the rehearsal to press A
        dict(name="at_title_mystery_gift", kind="title_menu", downs=2, select_only=True),
    ]


class LeafGreenEnglish11:
    TITLE = "English LeafGreen 1.1"
    SAVE_NAME = "leafgreen.sav"
    ORIGIN_GAME = 5
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
    SB1_FLAGS, SB1_KEYITEMS, SB1_BERRIES = 0x0EE0, 0x3B8, 0x54C
    sym = {
        "CB2_Overworld": 0x080565C8,
        "CB2_MainMenu": 0x0800C2E8,
        "CB2_NamingScreen": 0x0809FB58,
        "Task_StartMenu": 0x0806F204,          # Task_StartMenuHandleInput
        "Task_HandleYesNoInput": 0x0809CE3C,   # Task_YesNoMenu_HandleInput
        "Task_HandleMultichoiceInput": 0x0809CC80,   # Task_MultichoiceMenu_HandleInput
        "Task_MysteryGift": 0x08142EF0,
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
    QUESTION = RubyEnglish11.QUESTION
    STATES = [
        dict(name="at_cable_club_menu", kind="talk", warp=(5, 5, 10, 4), face="UP", task=QUESTION),
        dict(name="at_title_mystery_gift", kind="title_menu", downs=2, select_only=True),
    ]


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
    raise SystemExit(f"no profile yet for game code {code} version {version}")
