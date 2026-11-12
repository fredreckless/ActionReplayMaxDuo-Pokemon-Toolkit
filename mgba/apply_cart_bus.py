"""apply_cart_bus.py - add the cartridge-bus device hook to an mGBA 0.10.5 source tree.

    python3 apply_cart_bus.py path/to/mgba-0.10.5

The hook is one pointer in struct GBAMemory. While it's set, every data access to the
cartridge (the ROM space 0x08000000-0x0DFFFFFF and the save area 0x0E000000-0x0FFFFFFF, at any
width, including DMA and LDM/STM), every jump that starts executing from the ROM space, and
every WAITCNT change goes to the device instead of mGBA's own cartridge code. Instruction
fetches inside the ROM space keep coming from memory->rom, which the device keeps up to date.
With the pointer NULL (always, unless a frontend sets it) mGBA behaves exactly as before.

The edits are made by exact text replacement, so they fail loudly on any other mGBA version.
`git diff` in the tree afterwards gives the patch (cart-bus.patch beside this script).
"""
import os, sys

root = sys.argv[1]


def edit(rel, pairs):
    p = os.path.join(root, rel)
    s = open(p).read()
    for old, new in pairs:
        if s.count(old) != 1:
            sys.exit(f"{rel}: expected exactly one match for:\n{old}")
        s = s.replace(old, new)
    open(p, "w").write(s)


edit("include/mgba/internal/gba/memory.h", [
    ("""struct GBAMemory {
	uint32_t* bios;""", """/* A device that answers the whole cartridge bus (e.g. a pass-through cartridge whose contents
 * change). See src/gba/memory.c: while memory->cartBus is set, cartridge data accesses, jumps
 * into the ROM space and WAITCNT writes go to it; fetches still read memory->rom. */
struct GBACartBus {
	void* context;
	uint32_t (*load)(struct GBACartBus*, uint32_t address, int width);
	void (*store)(struct GBACartBus*, uint32_t address, int width, uint32_t value);
	void (*fetch)(struct GBACartBus*, uint32_t address);
	void (*waitcnt)(struct GBACartBus*, uint16_t value);
};

struct GBAMemory {
	struct GBACartBus* cartBus;
	uint32_t* bios;"""),
])

edit("src/gba/memory.c", [
    # instruction fetch entering the ROM space
    ("""	case REGION_CART2_EX:
		cpu->memory.activeRegion = memory->rom;
		cpu->memory.activeMask = memory->romMask;""", """	case REGION_CART2_EX:
		if (memory->cartBus && memory->cartBus->fetch) {
			memory->cartBus->fetch(memory->cartBus, address);
		}
		cpu->memory.activeRegion = memory->rom;
		cpu->memory.activeMask = memory->romMask;"""),
    # 32-bit loads (GBALoad32, GBALoadMultiple)
    ("""#define LOAD_CART \\
	wait += waitstatesRegion[address >> BASE_OFFSET]; \\
	if ((address & (SIZE_CART0 - 1)) < memory->romSize) { \\""", """#define LOAD_CART \\
	wait += waitstatesRegion[address >> BASE_OFFSET]; \\
	if (memory->cartBus) { \\
		value = memory->cartBus->load(memory->cartBus, address & ~3, 4); \\
	} else if ((address & (SIZE_CART0 - 1)) < memory->romSize) { \\"""),
    # 16-bit loads
    ("""	case REGION_CART2:
		wait = memory->waitstatesNonseq16[address >> BASE_OFFSET];
		if ((address & (SIZE_CART0 - 1)) < memory->romSize) {
			LOAD_16(value, address & (SIZE_CART0 - 2), memory->rom);
		} else if (memory->vfame.cartType) {
			value = GBAVFameGetPatternValue(address, 16);
		} else if ((address & (SIZE_CART0 - 1)) >= AGB_PRINT_BASE) {""", """	case REGION_CART2:
		wait = memory->waitstatesNonseq16[address >> BASE_OFFSET];
		if (memory->cartBus) {
			value = memory->cartBus->load(memory->cartBus, address & ~1, 2);
		} else if ((address & (SIZE_CART0 - 1)) < memory->romSize) {
			LOAD_16(value, address & (SIZE_CART0 - 2), memory->rom);
		} else if (memory->vfame.cartType) {
			value = GBAVFameGetPatternValue(address, 16);
		} else if ((address & (SIZE_CART0 - 1)) >= AGB_PRINT_BASE) {"""),
    ("""	case REGION_CART2_EX:
		wait = memory->waitstatesNonseq16[address >> BASE_OFFSET];
		if (memory->savedata.type == SAVEDATA_EEPROM || memory->savedata.type == SAVEDATA_EEPROM512) {""", """	case REGION_CART2_EX:
		wait = memory->waitstatesNonseq16[address >> BASE_OFFSET];
		if (memory->cartBus) {
			value = memory->cartBus->load(memory->cartBus, address & ~1, 2);
		} else if (memory->savedata.type == SAVEDATA_EEPROM || memory->savedata.type == SAVEDATA_EEPROM512) {"""),
    # 8-bit loads: the ROM space ...
    ("""		wait = memory->waitstatesNonseq16[address >> BASE_OFFSET];
		if ((address & (SIZE_CART0 - 1)) < memory->romSize) {
			value = ((uint8_t*) memory->rom)[address & (SIZE_CART0 - 1)];""", """		wait = memory->waitstatesNonseq16[address >> BASE_OFFSET];
		if (memory->cartBus) {
			value = memory->cartBus->load(memory->cartBus, address, 1);
		} else if ((address & (SIZE_CART0 - 1)) < memory->romSize) {
			value = ((uint8_t*) memory->rom)[address & (SIZE_CART0 - 1)];"""),
    # ... and the save area (16- and 32-bit save loads come through here as well)
    ("""		wait = memory->waitstatesNonseq16[address >> BASE_OFFSET];
		if (memory->savedata.type == SAVEDATA_AUTODETECT) {
			mLOG(GBA_MEM, INFO, "Detected SRAM savegame");""", """		wait = memory->waitstatesNonseq16[address >> BASE_OFFSET];
		if (memory->cartBus) {
			value = memory->cartBus->load(memory->cartBus, address, 1);
			break;
		}
		if (memory->savedata.type == SAVEDATA_AUTODETECT) {
			mLOG(GBA_MEM, INFO, "Detected SRAM savegame");"""),
    # 32-bit stores (GBAStore32, GBAStoreMultiple)
    ("""#define STORE_CART \\
	wait += waitstatesRegion[address >> BASE_OFFSET]; \\
	if (memory->matrix.size && (address & 0x01FFFF00) == 0x00800100) { \\
		GBAMatrixWrite(gba, address & 0x3C, value); \\
		break; \\
	} \\
	mLOG(GBA_MEM, STUB, "Unimplemented memory Store32: 0x%08X", address);""", """#define STORE_CART \\
	wait += waitstatesRegion[address >> BASE_OFFSET]; \\
	if (memory->cartBus) { \\
		memory->cartBus->store(memory->cartBus, address & ~3, 4, value); \\
	} else if (memory->matrix.size && (address & 0x01FFFF00) == 0x00800100) { \\
		GBAMatrixWrite(gba, address & 0x3C, value); \\
	} else { \\
		mLOG(GBA_MEM, STUB, "Unimplemented memory Store32: 0x%08X", address); \\
	}"""),
    # 16-bit stores
    ("""	case REGION_CART0:
		if (IS_GPIO_REGISTER(address & 0xFFFFFE)) {""", """	case REGION_CART0:
		if (memory->cartBus) {
			memory->cartBus->store(memory->cartBus, address & ~1, 2, (uint16_t) value);
			break;
		}
		if (IS_GPIO_REGISTER(address & 0xFFFFFE)) {"""),
    ("""	case REGION_CART0_EX:
		if ((address & 0x00FFFFFF) >= AGB_PRINT_BASE) {""", """	case REGION_CART0_EX:
		if (memory->cartBus) {
			memory->cartBus->store(memory->cartBus, address & ~1, 2, (uint16_t) value);
			break;
		}
		if ((address & 0x00FFFFFF) >= AGB_PRINT_BASE) {"""),
    # 8-bit stores: the ROM space (both halves) and the save area
    ("""	case REGION_CART0:
		mLOG(GBA_MEM, STUB, "Unimplemented memory Store8: 0x%08X", address);
		break;
	case REGION_CART_SRAM:
	case REGION_CART_SRAM_MIRROR:
		if (memory->savedata.type == SAVEDATA_AUTODETECT) {""", """	case REGION_CART0:
		if (memory->cartBus) {
			memory->cartBus->store(memory->cartBus, address, 1, (uint8_t) value);
			break;
		}
		mLOG(GBA_MEM, STUB, "Unimplemented memory Store8: 0x%08X", address);
		break;
	case REGION_CART0_EX:
		if (memory->cartBus) {
			memory->cartBus->store(memory->cartBus, address, 1, (uint8_t) value);
			break;
		}
		mLOG(GBA_MEM, GAME_ERROR, "Bad memory Store8: 0x%08X", address);
		break;
	case REGION_CART_SRAM:
	case REGION_CART_SRAM_MIRROR:
		if (memory->cartBus) {
			memory->cartBus->store(memory->cartBus, address, 1, (uint8_t) value);
			break;
		}
		if (memory->savedata.type == SAVEDATA_AUTODETECT) {"""),
    # WAITCNT
    ("""void GBAAdjustWaitstates(struct GBA* gba, uint16_t parameters) {
	struct GBAMemory* memory = &gba->memory;""", """void GBAAdjustWaitstates(struct GBA* gba, uint16_t parameters) {
	struct GBAMemory* memory = &gba->memory;
	if (memory->cartBus && memory->cartBus->waitcnt) {
		memory->cartBus->waitcnt(memory->cartBus, parameters);
	}"""),
])
print("cart bus hook applied")
