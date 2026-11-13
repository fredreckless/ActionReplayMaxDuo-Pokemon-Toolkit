"""profiles.py - what savegen.py needs to know about each game: addresses in RAM and code, and where
the Cable Club's attendants stand. Facts about the games (from pret's symbols where there are
some), not Nintendo's data. Picked by the ROM's header (game code and version byte)."""


class RubyEnglish11:
    TITLE = "English Ruby 1.1"
    SAVE_NAME = "ruby.sav"
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
        dict(name="at_link_standby", kind="mystery_event"),
    ]

    @staticmethod
    def mystery_standby(g):
        return True


def for_rom(path):
    with open(path, "rb") as f:
        head = f.read(0xC0)
    code, version = head[0xAC:0xB0].decode("latin-1"), head[0xBC]
    if code == "AXVE" and version == 1:
        return RubyEnglish11
    raise SystemExit(f"no profile yet for game code {code} version {version}")
