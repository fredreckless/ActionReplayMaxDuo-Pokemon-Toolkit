"""duocore.py - the shared C core (duocore.c), reached from Python through ctypes.

    import duocore
    core = duocore.Core(fw, game, "sanyo", save)
    value, r = core.read(0x0E000000, 1)
    r = core.write(0x0800009C, 2, 0x0101)

The library is built on first use, beside this file, when it's missing or older than the source
(a C compiler is needed: cc/gcc/clang on Linux and macOS, gcc from MSYS2 or clang on Windows).
DUOCORE_LIB names a ready-built library instead.
"""
import ctypes, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = [os.path.join(HERE, f) for f in ("duocore.c", "duocore.h")]
LIBNAME = "duocore.dll" if sys.platform == "win32" else "libduocore.dylib" if sys.platform == "darwin" else "libduocore.so"

SAVE_TYPES = {"sanyo": 0, "macronix": 1, "flash512": 2, "sram": 3, "eeprom": 4, "none": 5}

OK, FAIL = 0, 1
F_VIOLATION, F_BAD, F_ROM_CHANGED, F_SAVE_CHANGED, F_WOKE = 1, 2, 4, 8, 16


class Result(ctypes.Structure):
    _fields_ = [("status", ctypes.c_int32), ("flags", ctypes.c_int32), ("rom_lo", ctypes.c_uint32),
                ("rom_hi", ctypes.c_uint32), ("cycles", ctypes.c_uint32), ("_msg", ctypes.c_char * 200)]

    @property
    def msg(self):
        return self._msg.decode("latin-1")

    @property
    def failed(self):
        return self.status == FAIL


def build(out=None):
    """Compile the core into a shared library; returns its path."""
    out = out or os.path.join(HERE, LIBNAME)
    for cc in (os.environ.get("CC"), "cc", "gcc", "clang"):
        if not cc:
            continue
        cmd = [cc, "-O2", "-shared", "-std=c99", "-Wall", "-Wextra", "-o", out, SOURCES[0]]
        if sys.platform != "win32":
            cmd.insert(1, "-fPIC")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
        except OSError:
            continue
        if r.returncode == 0:
            return out
        raise RuntimeError(f"building duocore failed:\n{r.stderr}")
    raise RuntimeError("no C compiler found to build duocore (set CC, or DUOCORE_LIB to a built library)")


def _load():
    path = os.environ.get("DUOCORE_LIB")
    if not path:
        path = os.path.join(HERE, LIBNAME)
        newest = max(os.path.getmtime(s) for s in SOURCES)
        if not os.path.exists(path) or os.path.getmtime(path) < newest:
            # build to a private name first: tests run many processes at once
            tmp = f"{path}.{os.getpid()}.tmp"
            build(tmp)
            os.replace(tmp, path)
    lib = ctypes.CDLL(path)
    P, R = ctypes.c_void_p, ctypes.POINTER(Result)
    u8p, sz, u32, i32 = ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int
    sig = {
        "duo_new": (P, [u8p, sz, u8p, sz, i32, u8p, sz]),
        "duo_free": (None, [P]),
        "duo_read": (u32, [P, u32, i32, R]),
        "duo_write": (None, [P, u32, i32, u32, R]),
        "duo_render": (None, [P, u32, ctypes.c_void_p, sz]),
        "duo_rom_span": (u32, [P]),
        "duo_set_waitcnt": (None, [P, ctypes.c_uint16, R]),
        "duo_wants_rom_reads": (i32, [P]),
        "duo_usb_turn": (i32, [P]),
        "duo_usb_set_turn": (None, [P, i32]),
        "duo_usb_from_pc": (i32, [P, u8p, sz, R]),
        "duo_usb_from_gba": (i32, [P, u8p, sz, R]),
        "duo_mapped": (i32, [P]), "duo_awake": (i32, [P]), "duo_bank": (i32, [P]),
        "duo_id_mode": (i32, [P]), "duo_flash_id_mode": (i32, [P]), "duo_waitcnt": (ctypes.c_uint16, [P]),
        "duo_save_writes": (u32, [P]), "duo_ignored": (u32, [P]), "duo_save_size": (sz, [P]),
        "duo_save_copy": (None, [P, ctypes.c_void_p]), "duo_cmd_len": (i32, [P]),
        "duo_version": (ctypes.c_char_p, []),
    }
    for name, (res, args) in sig.items():
        f = getattr(lib, name)
        f.restype, f.argtypes = res, args
    return lib


_lib = None


def lib():
    global _lib
    if _lib is None:
        _lib = _load()
    return _lib


class Core:
    """One DUO: its flash, the game in its slot and the game's save chip, and its USB chip."""

    def __init__(self, fw, game, save_type="sanyo", save=b""):
        self.lib = L = lib()
        if save_type not in SAVE_TYPES:
            raise ValueError(f"unknown save type {save_type!r}")
        fw, game, save = bytes(fw), bytes(game), bytes(save or b"")
        self.h = L.duo_new(fw, len(fw), game, len(game), SAVE_TYPES[save_type], save, len(save))
        if not self.h:
            raise MemoryError("duo_new failed")
        self.r = Result()
        self._rp = ctypes.byref(self.r)

    def __del__(self):
        h, self.h = getattr(self, "h", None), None
        if h and _lib is not None:
            _lib.duo_free(h)

    # ---- the bus (each returns the core's Result, reused between calls)
    def read(self, addr, width):
        v = self.lib.duo_read(self.h, addr, width, self._rp)
        return v, self.r

    def write(self, addr, width, value):
        self.lib.duo_write(self.h, addr, width, value & 0xFFFFFFFF, self._rp)
        return self.r

    def render(self, addr, length):
        buf = ctypes.create_string_buffer(length)
        self.lib.duo_render(self.h, addr, buf, length)
        return buf.raw

    def set_waitcnt(self, v):
        self.lib.duo_set_waitcnt(self.h, v & 0xFFFF, self._rp)
        return self.r

    # ---- USB
    def usb_from_pc(self, pkt):
        pkt = bytes(pkt)
        return self.lib.duo_usb_from_pc(self.h, pkt, len(pkt), self._rp), self.r

    def usb_from_gba(self, pkt):
        pkt = bytes(pkt)
        return self.lib.duo_usb_from_gba(self.h, pkt, len(pkt), self._rp), self.r

    @property
    def turn(self):
        return "gba" if self.lib.duo_usb_turn(self.h) else "pc"

    @turn.setter
    def turn(self, who):
        self.lib.duo_usb_set_turn(self.h, 1 if who == "gba" else 0)

    # ---- state
    rom_span = property(lambda s: s.lib.duo_rom_span(s.h))
    wants_rom_reads = property(lambda s: bool(s.lib.duo_wants_rom_reads(s.h)))
    mapped = property(lambda s: s.lib.duo_mapped(s.h) or None)
    awake = property(lambda s: bool(s.lib.duo_awake(s.h)))
    bank = property(lambda s: s.lib.duo_bank(s.h))
    id_mode = property(lambda s: bool(s.lib.duo_id_mode(s.h)))
    flash_id_mode = property(lambda s: bool(s.lib.duo_flash_id_mode(s.h)))
    waitcnt = property(lambda s: s.lib.duo_waitcnt(s.h))
    save_writes = property(lambda s: s.lib.duo_save_writes(s.h))
    ignored = property(lambda s: s.lib.duo_ignored(s.h))
    cmd_len = property(lambda s: s.lib.duo_cmd_len(s.h))

    @property
    def save(self):
        n = self.lib.duo_save_size(self.h)
        buf = ctypes.create_string_buffer(max(1, n))
        self.lib.duo_save_copy(self.h, buf)
        return bytearray(buf.raw[:n])


def version():
    return lib().duo_version().decode()
