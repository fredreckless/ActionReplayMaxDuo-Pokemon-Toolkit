"""
Test suite for Reckless v4 firmware + PC tool, run against hwsim (which
reproduces every behaviour observed on the real DUO).

    python tests/test_v4.py            run everything (about 15 minutes)
    python tests/test_v4.py stream     run tests whose name contains "stream"
    python tests/run_each.py           run each test in its own process (most reliable)

Needs the firmware built first: python firmware/build_firmware.py PATH_TO_DATEL_1.06_UPDATE --all
"""
import gc, io, contextlib, glob, json, os, random, re, shutil, struct, subprocess, sys, tempfile, threading, time, traceback, types, zlib
import paths
os.environ["ACTIONREPLAY_NO_LOG"] = "1"     # (the tools' run logs: tested on their own, not written by every test)
import hwsim, thumbcheck, maxduo_saves as M
import duo_events as W

MISSING_BUILD = None          # set when a firmware image isn't built here: tests that error are then skipped
try:
    FW = open(os.environ.get("V3_FW") or paths.build_file("fw_v4.bin"), "rb").read()
    OFFICIAL = paths.read_build("fw.bin")
    LABFW = paths.read_build("fw_lab.bin")
    OLD_V3 = paths.read_build("fw_v3_original.bin", required=False)   # the first v3, whose transfers stalled
    V31 = paths.read_build("fw_v3.bin")                                  # v3.1
    FW42 = open(os.environ.get("V42_FW") or paths.build_file("fw_v42.bin"), "rb").read()    # v4.2
except paths.MissingBuild as e:
    MISSING_BUILD = e
    FW = OFFICIAL = LABFW = OLD_V3 = V31 = FW42 = None
import fixtures
RUBY = fixtures.make_gen3_save("May", 12345, save_no=337)          # synthetic Ruby save
GAME = hwsim.make_game_rom()
SAVE = 0x0E000000
RESULTS = []


class Skip(Exception):
    """A test that needs an optional file which isn't present."""


def need_untouched_official():
    """Rebuild tests start from Datel's own 1.06 firmware, whose padding is empty (0xFF). The
    workspace's fw.bin isn't always that (the update file isn't in the repository)."""
    import build_patch as BP
    if not all(x == 0xFF for x in OFFICIAL[BP.PAD_START - BP.BASE:BP.PAD_END - BP.BASE]):
        raise Skip("fw.bin here isn't Datel's untouched 1.06 firmware (its padding isn't empty); "
                   "build from the update file first")
LIVE = []
M.SHORT_TIMEOUT = 800        # keep the real ratio: DUO waits ~15 s, PC ~5 s (scaled here)
M.BUSY_WAIT_S = 3            # the DUO's 15 s give-up time is 1.8 s in the simulator


def device(save_type="sanyo", save=None, game=None, faults=None, fw=FW):
    hw = hwsim.Hw(fw, game or GAME, save_type, save if save is not None else RUBY, faults).start()
    LIVE.append(hw)
    duo = M.MaxDuo(hwsim.Transport(hw))
    duo.hello()
    return hw, duo


def sent_as(script):
    """What Ruby's shared buffer holds after the DUO sends `script`: the whole 2,004-byte buffer."""
    return script.ljust(W.MEV_MAX, b"\0")


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def gba_save(duo, **kw):
    out = tempfile.mkdtemp()
    args = types.SimpleNamespace(out=out, map=kw.get("map"), save_type=kw.get("save_type"), slow=kw.get("slow", False))
    (path, data, info), text = quiet(M.gba_save_v3, duo, args)
    return path, data, info, text, out


def clean(hw):
    assert not hw.bad, f"simulator problems: {hw.bad}"
    assert not hw.violations, f"save-changing writes: {hw.violations}"
    assert hw.mapped is None, "left the game mapped"
    assert not hw.link_errors, f"link out of step: {hw.link_errors}"
    assert bytes(hw.save) == hw.original_save, "save contents changed"


def test(name):
    def deco(fn):
        RESULTS.append((name, fn))
        return fn
    return deco


def lab_read_ops(n, start=SAVE, wake=True, mapping=0x0101):
    ops = [("w16", M.MAP_REG, mapping), ("delay", 0, 0x100)]
    if wake:
        ops.append(("r16", 0x08000000, 2))
    return ops + [("r8", start, n), ("w16", M.MAP_REG, 0x0120)]


# ===================================================================== build
@test("build: v4 rebuilds byte-for-byte from source (reproducible)")
def _():
    need_untouched_official()
    work = tempfile.mkdtemp()
    open(os.path.join(work, "fw.bin"), "wb").write(OFFICIAL)
    out = subprocess.run([sys.executable, "-c", "import build_v4; build_v4.build()"], cwd=work, capture_output=True, text=True,
                         env=dict(os.environ, PYTHONPATH=paths.FIRMWARE))
    assert out.returncode == 0, out.stderr
    assert open(os.path.join(work, "fw_v4.bin"), "rb").read() == FW


@test("build: outside Datel's padding, only command slots and text pointers change")
def _():
    allowed = {0x080074A8, 0x080074BC, 0x080074C4, 0x08007518, 0x08007524,               # cmds 2,7,9,1E,21
               0x080074AC, 0x080074B0, 0x080074B4, 0x080074B8,                           # cmds 3,4,5,6 (lab/v2)
               0x080073A0, 0x080073A4,                                                   # redirected call
               0x0800B238}                                                                # version label
    allowed |= {t + 4 * 36 for t in (0x0802BB70, 0x0802BE94, 0x0802C0B8, 0x0802C2DC)}     # USB-mode line only
    bad = sorted({hex(0x08000000 + i & ~3) for i in range(len(OFFICIAL)) if FW[i] != OFFICIAL[i]
                  and not 0x1E7C2 <= i < 0x1FD90 and (0x08000000 + i & ~3) not in allowed})
    assert not bad, f"unexpected changes at {bad}"


@test("build: Datel's own command handlers are untouched")
def _():
    ours = {2, 3, 4, 5, 6, 7, 9, 0x1E, 0x21}
    for c in range(2, 0x28):
        o = 0x74A8 + 4 * (c - 2)
        if c not in ours:
            assert FW[o:o + 4] == OFFICIAL[o:o + 4], f"command {c:#x} changed"


@test("build: every patch routine (v1, v2, lab, v4) is ARM7TDMI Thumb-1 only")
def _():
    import build_patch as v1, build_patch2 as v2, build_lab as L, build_v4 as V
    pieces = [("v2 wrapper", v2.ASM_PREP2.replace("RAMFN_ADDR", "0").replace("RAMFN_LEN", "0"), v1.PREP_AT),
              ("stub", v1.ASM_STUB, v1.STUB_AT), ("lab tail", L.ASM_LAB_TAIL, L.TAIL_AT),
              ("lab setaddr", L.ASM_SETADDR, L.SETADDR_AT), ("lab poke", L.ASM_POKE, L.POKE_AT),
              ("lab exec", L.ASM_EXEC, L.EXEC_AT),
              ("lab wrapper", L.ASM_LAB_PREP.replace("TRAMP_ADDR", "0").replace("TRAMP_LEN", "0"), L.LAB_PREP_AT),
              ("lab trampoline", L.ASM_LAB_TRAMP.replace("PROBE_AT", "0").replace("PROBE", "0"), L.LAB_TRAMP_AT),
              ("interpreter", L.ASM_LAB_INTERP, L.STAGE_LO + 12)]
    _, S = V.strings_blob()
    pieces += [(n, src, V.AT[n]) for n, src in V.sources(S).items()]
    for name, src, at in pieces:
        thumbcheck.checked_assemble(v1.assemble, src, at, name)
    # and the tool's embedded interpreter is exactly the checked build
    assert M.LAB_INTERP == L.interp_code()


@test("build: update file is self-consistent and recognised by the tool")
def _():
    crc, payload = M.check_update_file(paths.build_file("duo_1.06_reckless_v4.1.bin"))
    assert payload == FW and "v4.1" in M.KNOWN_FIRMWARE.get(crc, "")
    for name, word in (("installed_v4.bin", "use v4.1"), ("duo_1.06_reckless_v3_original.bin", "use v3.1")):   # optional old builds
        if paths.build_file(name, required=False):
            crc, _ = M.check_update_file(paths.build_file(name))
            assert word in M.KNOWN_FIRMWARE.get(crc, "")


@test("update: installing v4.1 over the official, the lab edition, v3, v3.1 AND the first v4, flash simulated")
def _():
    saved, sys.argv = sys.argv, sys.argv[:1]
    try:
        import emu_update_test as U
    finally:
        sys.argv = saved
    for current in (OFFICIAL, LABFW, OLD_V3, V31, paths.read_build("installed_fw_v4.bin", required=False)):
        if current is None:
            continue
        U.OFFICIAL = current
        ok, text = quiet(U.main, paths.build_file("duo_1.06_reckless_v4.1.bin"))
        assert ok, text


# ============================================================ basic behaviour
@test("info: v4 identifies itself; v3.1, v3 and the lab edition are told apart")
def _():
    for fw, kind, fast in ((FW, "v4", True), (V31, "v3.1", True), (OLD_V3, "v3", False), (LABFW, None, False)):
        if fw is None:
            continue
        hw, duo = device(fw=fw)
        assert (duo.reckless(), duo.is_v3()) == (kind, fast), (kind, duo.reckless())
        hw.stop(); clean(hw)


@test("legacy --gba-save (cmd 0x03) now works too, with all three mappings")
def _():
    for m in (0x0101, 0x0007, 0x0001):
        hw, duo = device()
        data = duo.gba_save(2, m)
        hw.stop(); clean(hw)
        assert data == RUBY, f"mapping {m:#x}"
        assert hw.bank == 0


@test("legacy lab path (cmds 4/5/6) still works on v3")
def _():
    hw, duo = device()
    lab = M.Lab(duo); lab.v3 = False
    res = lab.run(lab_read_ops(64))
    hw.stop(); clean(hw)
    assert res[-1][1] == RUBY[:64]


@test("full --gba-save of a Ruby save: identical file, no writes beyond bank switches")
def _():
    hw, duo = device()
    t0 = hw.sent_packets
    path, data, info, text, _ = gba_save(duo)
    hw.stop(); clean(hw)
    assert data == RUBY and open(path, "rb").read() == RUBY
    assert info["title"] == "POKEMON RUBY" and info["code"] == "AXVE" and "known game" in info["tags"][0]
    assert hw.save_writes == 8, f"{hw.save_writes} chip writes (expected 2 bank switches = 8)"


@test("screen log: expected messages, in order, all short enough for the screen")
def _():
    hw, duo = device()
    gba_save(duo)
    hw.stop()
    log = hw.log
    want = ["PC connected: RECKLESS V4", "GBA save: reading game", "Sent 64 KB",
            "Reading bank 1 (64 KB)", "Save copied to PC", f"128 KB, CRC {zlib.crc32(RUBY):08X}"]
    pos = 0
    for w in want:
        assert w in log[pos:], f"missing or out of order: {w!r}\n{log}"
        pos = log.index(w, pos) + 1
    assert all(len(l) <= 27 for l in log), [l for l in log if len(l) > 27]


@test("speed: v4 needs a fifteenth of v2's USB transfers for the same save (both directions counted)")
def _():
    hw, duo = device()
    n0 = hw.sent_packets + hw.pc_packets
    gba_save(duo)
    v31 = hw.sent_packets + hw.pc_packets - n0
    hw.stop(); clean(hw)
    v2 = 2 * (0x20000 // 8) + 8                 # Datel-style: every 8 bytes = 1 packet + 1 ack
    print(f"      USB transfers: v2 {v2}, v4 {v31} -> about {v2 * 0.0092:.0f} s vs {v31 * 0.0092:.0f} s on the real DUO"
          " (9.2 ms per transfer, as measured in lab session 1)")
    assert v31 * 14 < v2, v31


# ================================================================== streaming
PATTERNS = {
    "random": bytes(random.Random(1).getrandbits(8) for _ in range(0x8000)),
    "all FF": b"\xFF" * 0x8000,
    "all zero": bytes(0x8000),
    "all escape byte": bytes([M.RLE_ESC]) * 0x8000,
    "escape alternating": bytes([M.RLE_ESC, 0]) * 0x4000,
    "runs 255/256/257": (b"\x11" * 255 + b"\x22" * 256 + b"\x33" * 257 + b"\x44") * 42 + b"\x55" * (0x8000 - 769 * 42),
    "ascending": bytes(i & 0xFF for i in range(0x8000)),
    "Ruby first 32 KB": RUBY[:0x8000],
    "short runs of 3": (b"\x01\x01\x01\x02\x02\x02") * 5461 + b"\x00\x00",
}


@test("stream: 9 data patterns round-trip exactly; GBA compression == reference encoder")
def _():
    for name, pat in PATTERNS.items():
        assert len(pat) == 0x8000, name
        hw, duo = device("sram", save=pat, game=hwsim.make_game_rom(code=b"ZTST", tag=b"SRAM_V113"))
        res = M.Lab(duo).run(lab_read_ops(0x8000))
        hw.stop(); clean(hw)
        assert res[-1][1] == pat, f"{name}: data differs"
        out = b"\x2e\x00" + pat + b"DONE"                  # what the GBA streamed
        for (b, raw, dlen), payload in zip(duo.stats["block_info"], duo.stats["payloads"]):
            ref = M.rle3_encode(out[b * 4096:(b + 1) * 4096])
            assert raw == (ref is None), f"{name} block {b}: raw={raw}, reference says {ref is None}"
            if not raw:
                assert payload == ref, f"{name} block {b}: GBA's compressed bytes differ from the reference"


@test("stream: odd output sizes (1, 4095, 4096, 4097, 5000, 65536 bytes)")
def _():
    for n in (1, 4095, 4096, 4097, 5000, 0x10000):
        hw, duo = device()
        res = M.Lab(duo).run(lab_read_ops(n))
        hw.stop(); clean(hw)
        assert res[-1][1] == RUBY[:n], n


@test("stream: random bit corruption is caught by block CRCs and re-sent")
def _():
    hw, duo = device(faults={"corrupt_p": 0.004, "seed": 11})
    res = M.Lab(duo).run(lab_read_ops(0x10000))
    hw.stop(); clean(hw)
    assert res[-1][1] == RUBY[:0x10000] and duo.stats["retries"] > 0, duo.stats["retries"]


@test("stream: a corrupted block header and a corrupted data packet are each NAKed and re-sent")
def _():
    hw, duo = device(faults={"corrupt_at": {1, 30, 200}})
    res = M.Lab(duo).run(lab_read_ops(0x10000))
    hw.stop(); clean(hw)
    assert res[-1][1] == RUBY[:0x10000] and duo.stats["retries"] >= 2, duo.stats["retries"]


@test("stream: one corrupted packet at EVERY position of a stream (header, data, last) always recovers")
def _():
    ops = lab_read_ops(0x3000)
    hw, duo = device()
    M.Lab(duo).run(ops)
    n = duo.stats["packets"]
    hw.stop(); clean(hw)
    harmless = []
    hw, duo = device()
    lab = M.Lab(duo)
    for pos in range(1, n + 1):                  # one DUO, a fresh fault position each run
        hw.faults["corrupt_at"] = {pos}
        hw.rng.seed(pos)
        res = lab.run(ops)
        assert res[-1][1] == RUBY[:0x3000], pos
        assert not hw.bad and not hw.link_errors, (pos, hw.bad, hw.link_errors)
        if not duo.stats["retries"]:
            harmless.append(pos)
    hw.faults.clear()
    hw.stop(); clean(hw)
    assert len(harmless) <= 4, harmless          # only flips in a block's discarded padding need no resend
    print(f"      all {n} positions gave exact data ({len(harmless)} flips landed in padding: {harmless})")


@test("stream: random corruption (1 packet in 2000) over 64 KB still gives exact data")
def _():
    hw, duo = device(faults={"corrupt_p": 0.0005, "seed": 5})
    res = M.Lab(duo).run(lab_read_ops(0x10000))
    hw.stop(); clean(hw)
    assert res[-1][1] == RUBY[:0x10000]
    print(f"      {duo.stats['retries']} blocks re-sent")


@test("stream: --slow uses the Datel-style lab transfers and still gets the identical save")
def _():
    hw, duo = device()
    path, data, info, text, _ = gba_save(duo, slow=True)
    hw.stop(); clean(hw)
    assert data == RUBY and any(l.startswith("SendFile") for l in hw.log)


@test("stream: if the PC vanishes mid-transfer the DUO times out and recovers")
def _():
    hw, duo = device()
    lab = M.Lab(duo)
    prog = M.lab_encode([("w16", M.WAITCNT, 3)] + lab_read_ops(0x10000))
    lab._upload_fast(M.LAB_STAGE, prog)
    duo.t.write(M.packet(M.CMD_EXEC_STREAM, 0))
    duo.t.read(5000)                           # start packet
    for _ in range(4):                         # answer a few packets, then stop answering
        duo.t.write(M.packet(M.ST_CONT, 0))
        duo.t.read(5000)
    time.sleep(hwsim.FRAME_S * 900 + 2.5)
    duo._drain()
    assert "PC stopped answering" in hw.log, hw.log[-5:]
    assert duo.hello() == 0x104               # back in the command loop
    hw.stop(); clean(hw)


@test("link: stray stream answers and retired v3 commands get Datel's 'unknown' reply - never silence")
def _():
    hw, duo = device()
    for cmd in (M.ST_ACK, 0x0F, M.ST_CONT, 0x08, 0x1D):
        duo.t.write(b"CBW" + bytes([cmd]) + bytes(4))           # raw: the tool itself won't send 0x0F/0x08/0x1D
        assert M.parse(duo.t.read(5000))[0] == 0x01, f"{cmd:#x}"
    assert duo.hello() == 0x104
    hw.stop(); clean(hw)


@test("reproduction: v3 firmware + v3 tool stall exactly as on the real DUO ('LAB: upload timed out')")
def _():
    import importlib.util
    old_tool = os.path.join(paths.HERE, "history", "maxduo_saves_v3_original.py")
    if OLD_V3 is None or not os.path.exists(old_tool):
        raise Skip("build with --all first: needs the original v3 firmware")
    spec = importlib.util.spec_from_file_location("old_tool", old_tool)
    OLD = importlib.util.module_from_spec(spec); spec.loader.exec_module(OLD)
    OLD.SHORT_TIMEOUT = 800
    hw = hwsim.Hw(OLD_V3, GAME, "sanyo", RUBY).start(); LIVE.append(hw)
    duo = OLD.MaxDuo(hwsim.Transport(hw)); duo.hello()
    args = types.SimpleNamespace(out=tempfile.mkdtemp(), map=None, save_type=None, slow=False)
    try:
        quiet(OLD.gba_save_v3, duo, args)
        raise AssertionError("the old pair worked in the simulator - it should not")
    except Exception as e:
        assert _is_timeout_like(e), e
    time.sleep(hwsim.FRAME_S * 900 + 3)
    assert "LAB: upload timed out" in hw.log, hw.log[-4:]
    assert any("PC sent two packets in a row" in x for x in hw.link_errors)
    hw.stop()
    assert not hw.violations and bytes(hw.save) == hw.original_save


def _is_timeout_like(e):
    return "timeout" in type(e).__name__.lower() or "timed out" in str(e).lower()


@test("fallback: the new tool reads a save through the INSTALLED v3 firmware (slow, proven path)")
def _():
    if OLD_V3 is None:
        raise Skip("build with --all first: needs the original v3 firmware")
    hw, duo = device(fw=OLD_V3)
    path, data, info, text, _ = gba_save(duo)
    hw.stop(); clean(hw)
    assert data == RUBY and "Reckless v3, whose fast transfers stall" in text
    assert hw.save_writes == 8


# ==================================================================== uploads
@test("upload: firmware refuses out-of-window, zero-length and overflowing uploads")
def _():
    hw, duo = device()
    assert duo.ask(M.LAB_SETADDR, 0x0203AFF8) == (4, 0x0203AFF8)
    assert duo.ask(M.CMD_UPLOAD, 16)[0] == 0x3F                    # would cross the window end
    assert duo.ask(M.CMD_UPLOAD, 0)[0] == 0x3F
    assert duo.ask(M.CMD_UPLOAD, 0xFFFFFFF8)[0] == 0x3F            # wrap-around attempt
    assert duo.ask(M.LAB_SETADDR, 0x02000000)[0] == 0x3F           # outside the window entirely
    assert "LAB: bad upload request" in hw.log
    hw.stop(); clean(hw)


@test("upload: a corrupted upload is detected by its CRC")
def _():
    hw, duo = device()
    lab = M.Lab(duo)
    duo.ask(M.LAB_SETADDR, M.LAB_STAGE)
    assert duo.ask(M.CMD_UPLOAD, 16) == (M.CMD_UPLOAD, 16)
    duo.t.write(b"ABCDEFGH")
    assert M.parse(duo.t.read(5000)) == (M.UP_ACK, 8)                # every packet answered
    duo.t.write(b"ABCDEFGX")
    code, crc = M.parse(duo.t.read(5000))
    assert code == M.CMD_UPLOAD and crc != zlib.crc32(b"ABCDEFGHABCDEFGH")
    hw.stop(); clean(hw)


@test("upload: an incomplete upload times out cleanly, without replying out of turn")
def _():
    hw, duo = device()
    duo.ask(M.LAB_SETADDR, M.LAB_STAGE)
    assert duo.ask(M.CMD_UPLOAD, 64) == (M.CMD_UPLOAD, 64)
    duo.t.write(b"12345678")
    assert M.parse(duo.t.read(5000)) == (M.UP_ACK, 8)
    time.sleep(hwsim.FRAME_S * 900 + 2.5)                       # PC goes quiet; the DUO gives up
    assert "LAB: upload timed out" in hw.log, hw.log[-3:]
    assert duo.hello() == 0x104
    hw.stop(); clean(hw)


@test("messages: sanitised, truncated, at most three, and never repeated")
def _():
    hw, duo = device()
    lab = M.Lab(duo)
    lab.run(lab_read_ops(4), messages=["ok line", "tab\there", "x" * 40, "fourth"])
    n = len(hw.log)
    lab.run(lab_read_ops(4))
    hw.stop(); clean(hw)
    assert "ok line" in hw.log and "tab?here" in hw.log and "x" * 26 in hw.log
    assert "x" * 27 not in hw.log and "fourth" not in hw.log
    assert hw.log[n:].count("ok line") == 0


# ============================================================ safety / types
def save_case(tag, chip, save=None, save_type=None, expect=None, writes=0):
    game = hwsim.make_game_rom(code=b"ZTST", tag=tag) if tag is not None else hwsim.make_game_rom(code=b"ZTST", tag=None)
    hw, duo = device(chip, save=save, game=game)
    try:
        path, data, info, text, out = gba_save(duo, save_type=save_type)
        err = None
    except M.DuoError as e:
        err, data, out = str(e), None, None
    hw.stop(); clean(hw)
    assert hw.save_writes == writes, f"{hw.save_writes} chip writes, expected {writes}"
    return err, data, hw


@test("types: FLASH1M on Sanyo and Macronix chips -> 128 KB with bank switch")
def _():
    for chip in ("sanyo", "macronix"):
        err, data, hw = save_case(b"FLASH1M_V103", chip, writes=8)
        assert err is None and data == RUBY, chip


@test("types: 64 KB Flash (FLASH512_V / FLASH_V) -> 64 KB, no chip commands at all")
def _():
    for tag in (b"FLASH512_V131", b"FLASH_V126"):
        err, data, hw = save_case(tag, "flash512", save=RUBY[:0x10000])
        assert err is None and data == RUBY[:0x10000], tag


@test("types: SRAM (SRAM_V / SRAM_F_V) -> 32 KB, no writes at all")
def _():
    for tag in (b"SRAM_V113", b"SRAM_F_V100"):
        err, data, hw = save_case(tag, "sram", save=RUBY[:0x8000])
        assert err is None and data == RUBY[:0x8000], tag


@test("types: EEPROM, no tag, and conflicting tags are refused without touching the chip")
def _():
    err, _, _ = save_case(b"EEPROM_V124", "eeprom")
    assert err and "EEPROM" in err
    err, _, _ = save_case(None, "sram", save=RUBY[:0x8000])
    assert err and "tag" in err
    game = hwsim.make_game_rom(code=b"ZTST", tag=b"FLASH1M_V103")
    game = game[:0x50000] + b"SRAM_V113" + game[0x50009:]
    hw, duo = device("sanyo", game=game)
    try:
        gba_save(duo); raise AssertionError("conflicting tags accepted")
    except M.DuoError as e:
        assert "several" in str(e)
    hw.stop(); clean(hw)
    assert hw.save_writes == 0


@test("types: a repro cart (FLASH1M tag, SRAM chip) gets NO bank switch and a warning")
def _():
    sram = RUBY[:0x8000]
    game = hwsim.make_game_rom(code=b"ZTST", tag=b"FLASH1M_V103")
    hw, duo = device("sram", save=sram, game=game)
    path, data, info, text, _ = gba_save(duo)
    hw.stop(); clean(hw)
    assert hw.save_writes == 0 and "looks like SRAM" in text and data == sram * 2


@test("types: --save-type override works when the tag is missing")
def _():
    err, data, hw = save_case(None, "sram", save=RUBY[:0x8000], save_type="sram32")
    assert err is None and data == RUBY[:0x8000]


@test("types: tag found anywhere in the ROM, and the DUO's registers are never read")
def _():
    for at in (0x100, 0x7FFF0, 0xFFFF0):
        game = hwsim.make_game_rom(code=b"ZTST", tag=b"FLASH1M_V103", tag_at=at, size=0x100000)
        hw, duo = device("sanyo", game=game)
        path, data, info, text, _ = gba_save(duo)
        hw.stop(); clean(hw)                       # clean() fails on any DUO-register read
        assert data == RUBY and info["tags"] == ["FLASH1M_V103"], at


@test("wake: without the wake-up read the chip stays silent (matches the real DUO)")
def _():
    hw, duo = device()
    res = M.Lab(duo).run(lab_read_ops(16, wake=False))
    hw.stop(); clean(hw)
    assert res[-1][1] == b"\xFF" * 16


@test("verify: one bad byte from the chip is caught by the GBA's checksum and re-read")
def _():
    # the first run checksums 2x32 KB, then reads bank 0 (from save-read 0x10000), then checksums it
    hw, duo = device(faults={"flip_save_read": {0x10000 + 0x1234}})
    path, data, info, text, _ = gba_save(duo)
    hw.stop(); clean(hw)
    assert data == RUBY and "reading again" in text


@test("verify: a chip that keeps giving different data is refused, no file written")
def _():
    flips = {0x10000 + 0x1234, 0x30000 + 0x1234, 0x50000 + 0x1234}   # first read and both re-reads
    hw, duo = device(faults={"flip_save_read": flips})
    try:
        gba_save(duo); raise AssertionError("inconsistent data accepted")
    except M.DuoError as e:
        assert "different data twice" in str(e)
    hw.stop(); clean(hw)


# ================================================================== lab ops
@test("lab: search finds aligned patterns, reports at most four, pads with FF")
def _():
    game = bytearray(hwsim.make_game_rom(code=b"ZTST", tag=None))
    for at in (0x1000, 0x2004, 0x3008, 0x400C, 0x5000):
        game[at:at + 12] = b"ABCDtail%04X" % at
    hw, duo = device(game=bytes(game))
    w = lambda b: struct.unpack("<I", b)[0]
    res = M.Lab(duo).run([("w16", M.MAP_REG, 0x0101), ("r16", 0x08000000, 2),
                          ("search", 0x08000000, 0x10000, (w(b"ABCD"), w(b"ZZZZ"), w(b"YYYY"))),
                          ("search", 0x08000000, 0x10000, (w(b"QQQQ"), w(b"RRRR"), w(b"SSSS"))),
                          ("w16", M.MAP_REG, 0x0120)])
    hw.stop(); clean(hw)
    found, none = res[1][1], res[2][1]
    addrs = [struct.unpack_from("<I", found, i)[0] for i in range(0, 64, 16)]
    assert addrs == [0x08001000, 0x08002004, 0x08003008, 0x0800400C], [hex(a) for a in addrs]
    assert found[4:16] == b"ABCDtail1000" and none == b"\xFF" * 64


@test("lab: CRC op matches zlib for lengths 0, 1, 3, 4096 and 64 KB")
def _():
    hw, duo = device()
    ns = (0, 1, 3, 4096, 0x10000)
    ops = [("w16", M.MAP_REG, 0x0101), ("r16", 0x08000000, 2)] + [("crc", SAVE, n) for n in ns] + [("w16", M.MAP_REG, 0x0120)]
    res = M.Lab(duo).run(ops)
    hw.stop(); clean(hw)
    for n, (_, d) in zip(ns, res[1:]):
        assert struct.unpack("<I", d)[0] == zlib.crc32(RUBY[:n]), n


@test("lab: the GBA itself refuses erase/program values and stray addresses")
def _():
    real = M.lab_validate
    M.lab_validate = lambda ops: None
    try:
        for bad in ([("w8", 0x0E005555, 0xAA), ("w8", 0x0E002AAA, 0x55), ("w8", 0x0E005555, 0x80)],
                    [("w8", 0x0E005555, 0xA0)], [("w16", 0x08005554, 0x5555)], [("w8", 0x0E001234, 0x00)],
                    [("w16", 0x04000000, 0)]):
            hw, duo = device()
            try:
                M.Lab(duo).run([("w16", M.MAP_REG, 0x0101), ("r16", 0x08000000, 2)] + bad)
                raise AssertionError(f"{bad} accepted")
            except M.DuoError as e:
                assert "ERR!" in str(e)
            hw.stop(); clean(hw)
    finally:
        M.lab_validate = real


@test("fuzz: 120 random allowed scripts - never a save-changing write, always tidy afterwards")
def _():
    rng = random.Random(42)
    hw, duo = device()
    lab = M.Lab(duo)
    for i in range(120):
        ops = []
        for _ in range(rng.randrange(1, 9)):
            k = rng.randrange(9)
            if k == 0:
                ops.append(("w16", M.MAP_REG, rng.choice(sorted(M.LAB_MAPS))))
            elif k == 1:
                ops.append(("r16", 0x08000000 + 2 * rng.randrange(0x1000), 2))
            elif k == 2:
                ops.append(("r8", SAVE + rng.randrange(0x10000 - 64), rng.randrange(65)))
            elif k == 3:
                ops.append(("w8", rng.choice(sorted(M.SAVE_CMD_ADDRS)), rng.choice([0xAA, 0x55, 0x90, 0xF0, 0x00, 0x01])))
            elif k == 4:
                ops.append(("crc", SAVE + rng.randrange(0x100), rng.randrange(0x400)))
            elif k == 5:
                ops.append(("delay", 0, rng.randrange(0x100)))
            elif k == 6:
                ops.append(("r32", 0x08000000 + 4 * rng.randrange(0x1000), 4 * rng.randrange(4)))
            elif k == 7:
                ops.append(("wait16", 0x04000006, rng.randrange(1, 50)))
            else:
                ops.append(("sample8", SAVE, rng.randrange(1, 20) | 1 << 16))
        try:
            lab.run(ops)
        except M.DuoError as e:
            raise AssertionError(f"script {i} {ops}: {e}")
        assert hw.mapped is None and not hw.bad, (i, ops, hw.bad)
        assert bytes(hw.mu.mem_read(0x03000000, 0x178)) == hw.boot_iwram, f"flash routines not restored after {i}"
    hw.stop()
    assert not hw.violations, hw.violations          # B0/90/F0/AA/55 never change data


@test("regression: the earlier lab and v2 suites still pass on v4")
def _():
    for script in ("emu_test_lab.py", "emu_test2.py"):
        out = subprocess.run([sys.executable, script, paths.build_file("fw_v4.bin")], cwd=paths.HERE,
                             capture_output=True, text=True, timeout=1500)
        assert "ALL PASSED" in out.stdout, f"{script}:\n{out.stdout[-1500:]}"


# ======================================================================= v4
OTHER = fixtures.make_gen3_save("Brendan", 54321, save_no=12, seed=2)  # a different trainer


@test("v4 look: Datel's colours, start-up and title text restored; only the USB line and version differ")
def _():
    assert FW[0xEADC:0xEADC + 14 * 12] == OFFICIAL[0xEADC:0xEADC + 14 * 12], "colour schemes"
    assert FW[0xFA0:0xFA8] == OFFICIAL[0xFA0:0xFA8], "start-up colours"
    rd = lambda fw, a: struct.unpack_from("<I", fw, a - 0x08000000)[0]
    cs = lambda fw, a: fw[a - 0x08000000:fw.index(b"\0", a - 0x08000000)].decode("latin-1")
    for t in (0x0802BB70, 0x0802BE94, 0x0802C0B8, 0x0802C2DC):
        assert rd(FW, t) == rd(OFFICIAL, t) and rd(FW, t + 240) == rd(OFFICIAL, t + 240), "start-up / title text"
        assert cs(FW, rd(FW, t + 144)) == "RECKLESS V4 - READY"
    assert cs(FW, rd(FW, 0x0800B238)) == "V1.06 RM4"


@test("restart: reply first, soft reset, Datel's start-up answers the waiting hello, link stays in step")
def _():
    hw, duo = device()
    took = duo.restart(wait_s=20)
    path, data, info, text, _ = gba_save(duo)                 # fully usable afterwards
    hw.stop(); clean(hw)
    assert data == RUBY
    assert hw.restarts == 1 and hw.boots == ["usb"] and "Restarting (PC request)" in hw.log, (hw.restarts, hw.boots)


@test("restart: ten in a row always come back to USB mode, with real USB latency (v4's race is gone)")
def _():
    hw, duo = device()
    hw.usb_latency = 0.010                       # PC packets take ~10 ms to reach the GBA, as with real USB polling
    for i in range(10):
        duo.restart(wait_s=10)
        assert duo.hello() == 0x104, i
    hw.stop(); clean(hw)
    assert hw.restarts == 10 and hw.boots == ["usb"] * 10, hw.boots


@test("8-bit save bus: a full save and a cartridge report never read the save area wider than 8 bits")
def _():
    hw, duo = device()
    gba_save(duo)
    out = tempfile.mkdtemp(); cwd = os.getcwd(); os.chdir(out)
    try:
        quiet(M.cart_report, duo, types.SimpleNamespace(map=None, slow=False))
    finally:
        os.chdir(cwd)
    hw.stop(); clean(hw)                      # clean() fails on any 16/32-bit save read


@test("restart: three in a row, each followed by a lab run; refused politely on v3.1")
def _():
    hw, duo = device()
    for i in range(3):
        duo.restart(wait_s=20)
        assert M.Lab(duo).run(lab_read_ops(64))[-1][1] == RUBY[:64]
    hw.stop(); clean(hw)
    assert hw.restarts == 3 and hw.boots == ["usb"] * 3
    hw, duo = device(fw=V31)
    try:
        duo.restart(); raise AssertionError("v3.1 accepted a restart")
    except M.DuoError as e:
        assert "v4" in str(e)
    assert duo.hello() == 0x104
    hw.stop(); clean(hw)


@test("power-on: a waiting hello -> USB SERVER MODE; no hello -> the menu, and USB isn't served")
def _():
    hw = hwsim.Hw(FW, GAME, "sanyo", RUBY, powered=False).start(); LIVE.append(hw)
    duo = M.MaxDuo(hwsim.Transport(hw))
    threading.Timer(2.0, hw.power_on).start()    # well after the tool's first wait (0.2 s clearing + 0.8 s)
    v, text = quiet(duo.connect, 20)
    assert v == 0x104 and "Switch the GBA on now" in text
    time.sleep(0.3)
    assert hw.boots == ["usb"]
    hw.stop(); clean(hw)
    hw = hwsim.Hw(FW, GAME, "sanyo", RUBY, powered=False).start(); LIVE.append(hw)
    hw.power_on(); time.sleep(0.5)
    assert hw.boots == ["menu"]
    duo = M.MaxDuo(hwsim.Transport(hw))
    try:
        quiet(duo.connect, 2); raise AssertionError("menu answered USB")
    except M.DuoError as e:
        assert "USB SERVER MODE" in str(e)
    hw.stop()


@test("connect: stale packets are cleared; a DUO still busy with an interrupted transfer is waited for")
def _():
    hw, duo = device()
    hw.inject_stale(b"SBW\x10" + bytes(4)); hw.inject_stale(b"garbage!")
    v, text = quiet(duo.connect)
    assert v == 0x104 and "cleared 2 old packet" in text
    lab = M.Lab(duo)
    prog = M.lab_encode([("w16", M.WAITCNT, 3)] + lab_read_ops(0x8000))
    lab._upload_fast(M.LAB_STAGE, prog)
    duo.t.write(M.packet(M.CMD_EXEC_STREAM, 0)); duo.t.read(5000)          # start a stream, then abandon it
    duo.t.write(M.packet(M.ST_CONT, 0)); duo.t.read(5000)
    duo2 = M.MaxDuo(duo.t)                                                  # 'the tool is run again'
    v, text = quiet(duo2.connect)
    assert v == 0x104
    assert M.Lab(duo2).run(lab_read_ops(64))[-1][1] == RUBY[:64]
    hw.stop(); clean(hw)


@test("resident interpreter: later runs send only header + operations; a damaged copy is rejected, never run")
def _():
    hw, duo = device()
    lab = M.Lab(duo)
    lab.run(lab_read_ops(64))
    p0 = hw.pc_packets
    assert lab.run(lab_read_ops(64))[-1][1] == RUBY[:64]
    partial = hw.pc_packets - p0
    assert getattr(lab, "partial_uploads", 0) == 1
    hw.mu.mem_write(M.LAB_STAGE + 0x100, b"\x00\xde\x00\xde")              # damage the resident interpreter
    p0 = hw.pc_packets
    assert lab.run(lab_read_ops(64))[-1][1] == RUBY[:64]                    # rejected, then sent in full
    full = hw.pc_packets - p0
    assert "LAB: script rejected" in hw.log and duo.lab_resident
    hw.stop(); clean(hw)
    print(f"      PC packets per small run: {partial} with the interpreter resident, {full} after a rejection")
    assert partial * 2 < full


@test("fast save: known games skip the search; unknown games search only their real ROM size")
def _():
    hw, duo = device()
    path, data, info, text, _ = gba_save(duo)
    hw.stop(); clean(hw)
    assert data == RUBY and "known game (Pokemon Ruby)" in text and "search" not in text
    for mb in (1, 2, 4):
        g = hwsim.make_game_rom(code=b"ZTST", tag=b"FLASH1M_V103", size=0x80000, tag_at=0x7FF00, rom_size=mb << 20)
        hw, duo = device(game=g)
        path, data, info, text, _ = gba_save(duo)
        hw.stop(); clean(hw)
        assert data == RUBY and f"({mb} MB ROM)" in text, (mb, text[-400:])


@test("cartridge report: corrected whole-ROM CRC equals the real ROM's, for 1, 2 and 4 MB chips")
def _():
    for mb in (1, 2, 4):
        g = hwsim.make_game_rom(code=b"ZTST", tag=b"FLASH1M_V103", size=min(0x100000, mb << 19), rom_size=mb << 20, seed=mb)
        hw, duo = device(game=g)
        out = tempfile.mkdtemp(); cwd = os.getcwd(); os.chdir(out)
        try:
            rep, text = quiet(M.cart_report, duo, types.SimpleNamespace(map=None, slow=False))
        finally:
            os.chdir(cwd)
        hw.stop(); clean(hw)
        assert rep["rom_size_mb"] == mb and rep["rom_crc32"] == f"{zlib.crc32(g):08X}", (mb, rep)
        assert rep["header_ok"] and rep["logo_start_ok"] and rep["stable"]
        assert rep["timing_game_ok"] and not rep["timing_2cycle_ok"]       # the simulated chip fails 2-cycle reads


@test("cartridge report: reference match -> genuine; mismatch -> flagged; SRAM-in-Flash repro flagged")
def _():
    g = hwsim.make_game_rom(code=b"ZTST", tag=b"FLASH1M_V103", size=0x80000, rom_size=0x100000)
    for ref, word in ((zlib.crc32(g), "genuine"), (0x12345678, "does NOT match")):
        hw, duo = device(game=g)
        out = tempfile.mkdtemp(); cwd = os.getcwd(); os.chdir(out)
        try:
            json.dump({"ZTST rev 0": f"{ref:08X}"}, open(M.REFERENCES_FILE, "w"))
            rep, text = quiet(M.cart_report, duo, types.SimpleNamespace(map=None, slow=False))
        finally:
            os.chdir(cwd)
        hw.stop(); clean(hw)
        assert rep["verdict"].startswith(word), rep["verdict"]
    hw, duo = device("sram", save=RUBY[:0x8000], game=g)
    out = tempfile.mkdtemp(); cwd = os.getcwd(); os.chdir(out)
    try:
        rep, text = quiet(M.cart_report, duo, types.SimpleNamespace(map=None, slow=False))
    finally:
        os.chdir(cwd)
    hw.stop(); clean(hw)
    assert rep["save_halves_mirror"] and "reproduction" in text and hw.save_writes == 0


@test("cartridge report: the logo constants match their derivation and correct a known example")
def _():
    import logo_correction as LC
    assert {k: v for k, v in LC.constants().items()} == M.LOGO_CRC_FIX
    assert M.LOGO_START == hwsim.LOGO[:0x1C]
    rom = bytearray(random.Random(9).getrandbits(8) for _ in range(0x100000)); rom[4:0xA0] = hwsim.LOGO
    seen = bytearray(rom); seen[0x20:0x9C] = bytes(0x7C); seen[0x9C:0xA0] = hwsim.MAPREG_READ
    assert zlib.crc32(seen) ^ M.LOGO_CRC_FIX[0x100000] == zlib.crc32(rom)


@test("backups: per-game folder, identical saves not stored twice, a new trainer is warned about")
def _():
    out = tempfile.mkdtemp()
    def run_save(save):
        hw, duo = device(save=save)
        args = types.SimpleNamespace(out=out, map=None, save_type=None, slow=False)
        (path, data, info), text = quiet(M.gba_save_v3, duo, args)
        hw.stop(); clean(hw)
        return path, text
    p1, t1 = run_save(RUBY)
    assert "May" in os.path.basename(p1) and "Trainer May (ID 12345)" in t1 and "save #337" in t1
    p2, t2 = run_save(RUBY)
    assert p2 == p1 and "not stored again" in t2
    p3, t3 = run_save(OTHER)
    assert "Brendan" in os.path.basename(p3) and "WARNING" in t3 and "May" in t3
    assert open(p1, "rb").read() == RUBY                                     # earlier backup untouched
    assert len(os.listdir(os.path.dirname(p1))) == 2


@test("refusals: DeleteFile and the file-writing commands can never be sent, and a full run never tries")
def _():
    for cmd, word in ((0x1C, "DeleteFile"), (0x0A, "writes"), (0x0B, "writes"), (0x25, "writes"), (0x27, "DS card")):
        try:
            M.packet(cmd); raise AssertionError(f"{cmd:#x} not refused")
        except M.DuoError as e:                      # refused WITH its explanation, not just unlisted
            assert "refusing" in str(e) and word in str(e), str(e)
    assert not (set(M.REFUSED) & M.SAFE_COMMANDS)
    sent = []
    hw, duo = device()
    orig = duo.t.write
    duo.t.write = lambda data, timeout=5000: (sent.append(bytes(data)), orig(data, timeout))[1]
    quiet(duo.connect); gba_save(duo); duo.restart(wait_s=20)
    hw.stop(); clean(hw)
    cmds = {p[3] for p in sent if p[:3] == b"CBW"}
    assert not (cmds & set(M.REFUSED)) and cmds <= M.SAFE_COMMANDS, sorted(map(hex, cmds))


@test("compatibility: the v4 tool saves fast through v3.1 firmware too")
def _():
    hw, duo = device(fw=V31)
    path, data, info, text, _ = gba_save(duo)
    hw.stop(); clean(hw)
    assert data == RUBY and duo.reckless() == "v3.1"


@test("lab: table CRC op (crct) matches zlib on ROM; refused for the 8-bit save area and when unaligned")
def _():
    hw, duo = device()
    lab = M.Lab(duo)
    for n in (0, 4, 8, 4096, 0x10000):
        ops = [("w16", M.MAP_REG, 0x0101), ("delay", 0, 0x400), ("r16", 0x08000000, 2),
               ("crct", 0x08000100, n), ("w16", M.MAP_REG, 0x0120)]
        assert struct.unpack("<I", lab.run(ops)[-1][1])[0] == zlib.crc32(GAME[0x100:0x100 + n]), n
    for bad in (("crct", 0x08000101, 4), ("crct", 0x08000100, 6), ("crct", 0x0E000000, 0x10000)):
        try:
            M.lab_validate([bad]); raise AssertionError(bad)
        except M.DuoError:
            pass
    hw.stop(); clean(hw)


@test("lab_runner: allows the new read-only commands, still refuses --update")
def _():
    src = open(os.path.join(paths.ROOT, "lab_runner.py")).read()
    assert '"--cart-report"' in src and '"--restart"' in src and 'FORBIDDEN = {"--update"}' in src


# ======================================================================= main
@test("fast save: garbled start of a run's output (seen on real hardware) is caught; header re-read")
def _():
    real = M.MaxDuo.receive_stream
    calls = []
    def garbling(self, *a, **k):
        data = bytearray(real(self, *a, **k))
        calls.append(1)
        if len(calls) == 1:
            data[2:9] = bytes([0x00, 0x13, 0x88, 0x01, 0x00, 0x00, 0x7F])     # 7 bytes after the wake read
        return bytes(data)
    for garble_header in (False, True):
        calls.clear()
        M.MaxDuo.receive_stream = garbling
        try:
            hw, duo = device()
            if garble_header:
                def garbling2(self, *a, **k):
                    data = bytearray(real(self, *a, **k)); calls.append(1)
                    if len(calls) == 1:
                        data[34:39] = b"\x00\x13\x88\x01\x00"   # first 5 header bytes
                    return bytes(data)
                M.MaxDuo.receive_stream = garbling2
            path, data, info, text, _ = gba_save(duo)
        finally:
            M.MaxDuo.receive_stream = real
        hw.stop(); clean(hw)
        assert data == RUBY and info["header_ok"] and info["title"] == "POKEMON RUBY", (info, text[-600:])
        assert "POKEMON RUBY" in path
        assert ("garbled" in text) != garble_header and ("reading it again" in text) == garble_header, text[-600:]



# ====================================================================== v4.2
import sio32id_model


def run42(**kw):
    hw = hwsim.Hw(FW42, kw.get("game") or GAME, "sanyo", RUBY).start(); LIVE.append(hw)
    duo = M.MaxDuo(hwsim.Transport(hw)); duo.hello()
    return hw, duo


@test("v4.2 build: only command slot 0x23, the INFO reply and Datel's padding differ from v4.1; reproducible")
def _():
    need_untouched_official()
    diff = [i for i in range(len(FW)) if FW42[i] != FW[i]]
    outside = sorted({0x08000000 + (i & ~3) for i in diff if not 0x1E7C2 <= i < 0x1FD90})
    assert outside == [0x080074A8 + 4 * (0x23 - 2)], [hex(x) for x in outside]
    assert struct.pack("<I", M.RK42) in FW42 and struct.pack("<I", M.RK40) not in FW42[0x1F400:0x1F500]
    work = tempfile.mkdtemp()
    open(os.path.join(work, "fw.bin"), "wb").write(OFFICIAL)
    out = subprocess.run([sys.executable, "-c", "import build_v42; build_v42.build()"], cwd=work, capture_output=True,
                         text=True, env=dict(os.environ, PYTHONPATH=paths.FIRMWARE))
    assert out.returncode == 0, out.stderr[-800:]
    assert open(os.path.join(work, "fw_v42.bin"), "rb").read() == FW42


@test("two tools: the save tool has no event options; duo_events.py has gift/news/event, needs the save tool beside it, and duo_wireless.py's old options still work")
def _():
    saves = subprocess.run([sys.executable, os.path.join(paths.ROOT, "maxduo_saves.py"), "--help"], capture_output=True, text=True)
    events = subprocess.run([sys.executable, os.path.join(paths.ROOT, "duo_events.py"), "--help"], capture_output=True, text=True)
    assert saves.returncode == 0 and "adapter" not in saves.stdout.lower() and "wonder" not in saves.stdout.lower(), saves.stdout
    assert events.returncode == 0 and all(c in events.stdout for c in ("gift", "news", "event", "find-serial")), events.stdout
    gift = subprocess.run([sys.executable, os.path.join(paths.ROOT, "duo_events.py"), "gift", "--help"], capture_output=True, text=True)
    assert all(f in gift.stdout for f in ("--card", "--serial", "--sweep-serial", "--keep-going")), gift.stdout
    old = subprocess.run([sys.executable, os.path.join(paths.ROOT, "duo_wireless.py"), "--trace", "--wonder-card", "x.wc3",
                          "--help"], capture_output=True, text=True)
    assert old.returncode == 0 and "duo_events.py gift --card x.wc3" in old.stdout and "--card" in old.stdout, old.stdout
    for legacy, new in ((["--trace", "--wonder-card", "c.wc3", "--serial", "7F7F"], ["gift", "--card", "c.wc3", "--serial", "7F7F"]),
                        (["--trace", "--wonder-news", "n.bin"], ["news", "--news", "n.bin"]),
                        (["--mystery-event", "e.me3"], ["event", "--event", "e.me3"]),
                        (["--ereader", "120"], ["event", "--seconds", "120"]),
                        (["--test"], ["adapter-test"]), (["--probe"], ["probe"]),
                        (["--find-serial", "--deep"], ["find-serial", "--deep"]),
                        (["--trace", "--sweep-serial"], ["gift", "--sweep-serial"])):
        assert W.translate_legacy(legacy) == new, (legacy, W.translate_legacy(legacy))
    assert W.SAFE_COMMANDS is M.SAFE_COMMANDS and W.PROG_PUT in M.SAFE_COMMANDS   # one shared allow-list


@test("v4.2 programs: the tool's embedded programs are exactly this repository's build, Thumb-1 only")
def _():
    out = subprocess.run([sys.executable, "-c", "import programs, sys; sys.stdout.write(programs.build('adapter_detect').hex())"],
                         cwd=paths.FIRMWARE, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=paths.FIRMWARE))
    assert out.returncode == 0, out.stderr[-800:]
    assert bytes.fromhex(out.stdout) == W.PROGRAMS["adapter_detect"]


@test("v4.2 run: a staged program with a bad magic, length, entry or CRC is refused and never runs")
def _():
    good = bytearray(W.PROGRAMS["adapter_detect"])
    bad_images = []
    b = bytearray(good); b[0] ^= 1; bad_images.append(b)                         # magic
    b = bytearray(good); struct.pack_into("<I", b, 4, 0x4000); bad_images.append(b)  # length too big
    b = bytearray(good); struct.pack_into("<I", b, 12, 0x1000); bad_images.append(b) # entry outside the code
    b = bytearray(good); b[8] ^= 1; bad_images.append(b)                            # the stored CRC wrong: the
    # code is intact, so a firmware that skipped the check would run it and this test fail cleanly,
    # before the next case runs damaged code (which can crash the emulator outright)
    b = bytearray(good); b[40] ^= 0x10; bad_images.append(b)                        # code damaged (CRC)
    for img in bad_images:
        hw, duo = run42()
        M.Lab(duo)._upload_fast(M.LAB_STAGE, bytes(img))
        code, val = duo.ask(W.CMD_RUN)
        assert code == 0x3F, hex(code)
        assert duo.hello() == 0x104
        hw.stop(); clean(hw)
        assert "Program rejected" in hw.log and "Running program" not in hw.log


@test("v4.2 adapter test: answers the game's NINTENDO / 0x8001 exchange; the game accepts the adapter; DUO back in USB mode")
def _():
    hw, duo = run42()
    game = sio32id_model.Side(1)                      # the game's half: librfu's own code, clock master
    hw.attach_link_partner(game)
    st = quiet(W.adapter_test, duo, types.SimpleNamespace(adapter_test=30), poll_s=0.1, after_s=0.5)[0]
    assert game.last == 0x8001 and st >> 21 & 1, (hex(game.last), hex(st))
    words = hw.link_words
    assert words[1] == (0x494EFFFF, 0xFFFF494E) and (0x8001B0BB, 0xB0BB8001) in words   # matches the real adapter
    assert duo.hello() == 0x104 and duo.reckless() == "v4"
    hw.stop(); clean(hw)
    assert "Adapter check answered" in hw.log and any(l.startswith("Program finished") for l in hw.log)


@test("v4.2 run: an upload answer held up straight after an earlier run (seen on hardware) -> the tool waits and re-sends")
def _():
    hw, duo = run42()
    quiet(W.adapter_test, duo, types.SimpleNamespace(adapter_test=1), poll_s=0.2, after_s=0.5)   # an earlier run
    real_read, reads, held = duo.t.read, [0], []

    def late_read(timeout=5000):
        reads[0] += 1
        if reads[0] == 4:                      # SETADDR, UPLOAD, packet 1 answered; packet 2's answer is held up
            held.append(real_read(timeout))
            threading.Timer(0.3, lambda: hw.d2h.put(held[0])).start()   # ... and turns up much later
            import usb.core
            raise usb.core.USBTimeoutError("timeout")
        return real_read(timeout)
    duo.t.read = late_read
    _, text = quiet(W.run_program, duo, "adapter_detect")
    duo.t.read = real_read
    assert "missed part of the program upload" in text and "cleared 1 old packet" in text, text
    assert duo.ask(W.PROG_STOP)[0] == W.PROG_STOP and duo.hello() == 0x104
    hw.stop(); clean(hw)
    assert "LAB: upload timed out" in hw.log and hw.log.count("Running program") == 2, hw.log


@test("connect: a first answer that's held up (seen on hardware) -> the tool waits and tries again")
def _():
    hw = hwsim.Hw(FW42, GAME, "sanyo", RUBY).start(); LIVE.append(hw)
    duo = M.MaxDuo(hwsim.Transport(hw))
    real_read, reads, held = duo.t.read, [0], []

    def late_read(timeout=5000):
        pkt = real_read(timeout)
        reads[0] += 1
        if reads[0] == 2:                      # hello answered; the firmware check's answer is held up
            held.append(pkt)
            threading.Timer(0.3, lambda: hw.d2h.put(held[0])).start()
            import usb.core
            raise usb.core.USBTimeoutError("timeout")
        return pkt
    duo.t.read = late_read
    (version, v42), text = quiet(W.connect, duo, 30)
    duo.t.read = real_read
    assert version == 0x104 and v42 and "trying again" in text, text
    assert duo.hello() == 0x104
    hw.stop(); clean(hw)


@test("v4.2 adapter test: with nothing on the cable it reports 'nothing from the game' and stops cleanly")
def _():
    hw, duo = run42()
    st, text = quiet(W.adapter_test, duo, types.SimpleNamespace(adapter_test=1), poll_s=0.2, after_s=0.5)
    assert st & 0xFFFF == 0 and "nothing from the game yet" in text and "not detected" in text
    assert duo.hello() == 0x104
    hw.stop(); clean(hw)


@test("v4.2 adapter test: the game starts mid-way (junk words first) and still accepts the adapter")
def _():
    hw, duo = run42()
    game = sio32id_model.Side(1); game.out = 0x12345678; game.count = 2; game.recv_id = 0xBEEF
    hw.attach_link_partner(game)
    st = quiet(W.adapter_test, duo, types.SimpleNamespace(adapter_test=30), poll_s=0.1, after_s=0.5)[0]
    hw.stop(); clean(hw)
    assert game.last == 0x8001 and st >> 21 & 1


# ---------------------------------------------------------------- the adapter program (C)
import rfu_game_model as RFU


_SYMS = {}


def adapter_symbol(name, program="adapter"):
    """Address of a global in an adapter build (needs clang; the embedded copies are checked
    against a fresh build by another test, so the layouts match)."""
    if program not in _SYMS:
        sys.path.insert(0, paths.FIRMWARE)
        import programs
        try:
            _SYMS[program] = programs.symbols(program)
        except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
            raise Skip(f"needs clang/llvm to locate program symbols: {e}")
    return _SYMS[program][name]


def adapter_session(script, seconds=20, attach=True, program="adapter", lag_bits=0, first_bit=False,
                    flick_window=None, wonder_card=None, check_search=False,
                    sweep_serial=False, serial=None, wonder_news=None, stop_on_game=True, keep_going=False):
    hw, duo = run42()
    game = RFU.Game()
    if attach:
        flick = (adapter_symbol("flick_w", program),) + tuple(flick_window) if flick_window else None
        hw.attach_link_game(script(game), lag_bits=lag_bits, first_bit=first_bit, flick=flick)
    r = quiet(W.adapter_trace, duo, types.SimpleNamespace(adapter_trace=seconds, adapter_probe=seconds,
                                                          wonder_card=wonder_card, check_search=check_search,
                                                          sweep_serial=sweep_serial, serial=serial,
                                                          wonder_news=wonder_news, keep_going=keep_going),
              poll_s=0.2,
              stop_when=(lambda: hw.lg_done) if attach and stop_on_game else None, program=program)
    entries, st, counters = r[0][:3]
    hw.probe = r[0][3] if len(r[0]) > 3 else None
    hw.text = r[1]
    assert duo.hello() == 0x104 and duo.reckless() == "v4"          # back in USB server mode
    hw.stop(); clean(hw)
    assert any(l.startswith("Program finished") for l in hw.log)
    trace = [W.describe_trace_entry(h, d) for _, h, d in entries]
    return hw, game, trace, st, counters


@test("adapter program: the tool's embedded copy is this repository's build (clang 18.1), Thumb-1 only")
def _():
    sys.path.insert(0, paths.FIRMWARE)
    import programs
    try:
        version = programs.clang_version()
    except RuntimeError as e:
        raise Skip(str(e))
    if version != programs.CLANG_VERSION:
        raise Skip(f"clang {version} here; the embedded copy was built with {programs.CLANG_VERSION}")
    assert programs.build("adapter") == W.PROGRAMS["adapter"]
    assert programs.build("adapter_probe") == W.PROGRAMS["adapter_probe"]


@test("wireless adapter: Emerald's Mystery Gift search, command by command, answered as a real adapter would")
def _():
    def script(game):
        acks = yield from RFU.mystery_gift_search(game, polls=12)
        yield ("delay", 40 * RFU.MS)
        acks["sleep"] = yield from RFU.go_to_sleep(game)
        return acks
    hw, game, trace, st, counters = adapter_session(script)
    assert hw.lg_error is None and hw.lg_done, repr(hw.lg_error)
    acks = hw.lg_result
    assert acks[0x10] == [0x99660090] and acks[0x17] == [0x99660097] and acks[0x16] == [0x99660096]
    assert acks[0x1C] == [0x9966009C] and acks[0x1D][:2] == [0x9966079D, 0x7DA5] and acks[0x1E][:2] == [0x9966079E, 0x7DA5]
    assert acks["wait"] == 0x99660027                                  # the adapter's turn: nothing happened
    assert acks[0x13] == [0x99660193, 0]                               # idle, no ID
    assert acks[0x99] == "rejected" and acks["sleep"] == [0x996600BD]
    assert not game.errors, game.errors
    assert game.retries == 0 and not hw.link_trouble, (game.retries, hw.link_trouble)
    names = [t for t, _ in trace]
    expect = ["ID exchange completed", "Hello", "setup (0x17) 003C0420", "broadcast data", "start searching",
              "search results?", "stop searching", "wait (0x27)", "the adapter's turn", "status (0x13)",
              "unknown command (0x99)", "ID exchange completed", "sleep (0x3D)"]
    assert len(names) == len(expect) and all(n.startswith(e) for n, e in zip(names, expect)), names
    assert trace[5][1] == 12                                          # 12 polls, one line
    assert counters & 0xFFFF == 2 and counters >> 16 == 0


@test("distributor: Emerald's search finds a Wonder Card distributor (serial 0x7F7F as in BPEJ, checksum good, hasCard) and connects")
def _():
    def script(game):
        found = yield from RFU.find_distributor(game)
        conn = yield from RFU.connect_to(game, found["id"])
        yield from game.command(0x24, [0x00000400, 0x12345678])      # a child's first data
        return found, conn
    hw, game, trace, st, counters = adapter_session(script, first_bit=True, program="adapter_lab")
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors)
    found, conn = hw.lg_result
    assert found["serial"] == 0x7F7F and found["checksum_ok"] and found["gname"]["hasCard"], found
    assert found["gname"]["language"] == 1 and found["gname"]["version"] == 3 and found["uname"][:3] == bytes([0xBE, 0xCF, 0xC9])
    assert conn["status"] == 0 and conn["child_id"] == 0x2C41 and conn["swap"] == 0x99660028, conn
    # lab session 16: each top-bit-1 word needs a flick, and flicks lose words - only the header may
    assert found["words"][0] >> 16 == 0x9966 and all(w < 0x80000000 for w in found["words"][1:]), found["words"]
    assert found["uname"][3:5] == bytes([0x00, 0xFF]) and found["gname"]["trainer"] == 0x5678, found
    names = [t for t, _ in trace]
    assert any(n.startswith("the game connected to the distributor") for n in names), names
    assert game.retries == 0, game.retries
    assert W.adapter_trace.last_capture == [(0x24, 2, 1, [0x00000400, 0x12345678])], W.adapter_trace.last_capture


@test("find serial: read-only ROM search reports 0x7F7D when the game has it, and says so when it doesn't")
def _():
    import struct as _s
    for planted, expect in ((True, "same distributor serial"), (False, "serial differs")):
        rom = bytearray(hwsim.make_game_rom(title=b"POKEMON EMER", code=b"BPEJ", tag=b"FLASH1M_V103"))
        for k in range(0, len(rom) - 3, 4):            # no accidental matches in the random data
            if _s.unpack_from("<I", rom, k)[0] in W.SERIAL_PATTERNS:
                rom[k] ^= 1
        _s.pack_into("<I", rom, 0x10000, 0x99660000)
        if planted:
            _s.pack_into("<I", rom, 0x20004, 0x00007F7D)
        hw, duo = run42(game=bytes(rom))
        hits, text = quiet(W.find_serial, duo)
        hw.stop(); clean(hw)                           # clean() fails on any save-chip write
        assert "POKEMON EMER (BPEJ)" in text and expect in text, text
        assert (0x08020004 in [h[0] for h in hits]) == planted and 0x08010000 in [h[0] for h in hits], hits


@test("serial sweep: a game that only takes serial 0x0151 is offered it, finds it again, and connects to it")
def _():
    JP = 0x0151
    def script(game):
        yield ("until_ready",)
        assert (yield from game.check_id()) == 0x8001
        for cmd, data in ((0x10, []), (0x17, [0x003C0420]), (0x16, [2, 0, 0, 0, 0, 0xFFFFFFFF]), (0x1C, [])):
            yield from game.command(cmd, data)
        seen = None
        for n in range(900):                        # Emerald: Task_CardOrNewsOverWireless
            hosts = RFU.parse_candidates((yield from game.command(0x1D)))
            assert len(hosts) == 3 and all(h["checksum_ok"] for h in hosts), hosts
            match = [h for h in hosts if h["serial"] == JP and h["gname"]["hasCard"]]
            if seen is None and match:
                seen = n                            # the chime; 120+ frames on, it looks for it again
            elif seen is not None and n - seen > 120 and match:
                yield from game.command(0x1E)
                yield from game.command(0x1F, [match[0]["id"]])
                return n - seen
        raise RFU.LinkError(f"serial {JP:#x} " + ("never offered" if seen is None else "not offered again"))
    hw, game, trace, st, counters = adapter_session(script, seconds=60, first_bit=True, sweep_serial=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors)
    assert hw.lg_result < 120 + 240, hw.lg_result     # within the 240 frames Emerald allows
    assert W.adapter_trace.last_sweep >> 16 == JP, hex(W.adapter_trace.last_sweep)
    assert "the game connected to serial 0x0151" in hw.text, hw.text


@test("find serial --deep: reads the ROM into memory, finds the accepted-serials list code points at, and writes nothing")
def _():
    import struct as _s
    rom = bytearray(hwsim.make_game_rom(title=b"POKEMON EMER", code=b"BPEJ", tag=b"FLASH1M_V103", size=0x60000))
    rom[0x40000:0x40010] = _s.pack("<4H", 0x0002, 0x1234, 0x0000, 0xFFFF) + bytes(8)   # the real list
    _s.pack_into("<I", rom, 0x20100, 0x08040000)                                       # code points at it
    _s.pack_into("<I", rom, 0x20200, 0x00001234)                                       # and compares with it
    rom[0x50002:0x50008] = _s.pack("<3H", 0x0002, 0x0777, 0xFFFF)                       # a decoy, unreferenced
    hw, duo = run42(game=bytes(rom))
    found, text = quiet(W.find_serial_deep, duo)
    hw.stop(); clean(hw)
    assert found and found[0][1:3] == (0x1234, 0x08040000) and found[0][0] == 2, found
    assert 0x0777 not in [f[1] for f in found], found
    assert "Most likely: 0x1234" in text and "BPEJ" in text, text


@test("every game: an English FireRed gets serial 0x7F7D and an English host, and receives a full-size (0x14C) card")
def _():
    path, card, script = test_wc3("English")
    hw, game, trace, st, counters = adapter_session(lambda g: gift_script(g, RFU.EN_FIRERED), first_bit=True,
                                                    seconds=120, wonder_card=path)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors, [t for t, _ in trace][-10:])
    child, client = hw.lg_result
    assert client.result == RFU.CLI_MSG_CARD_RECEIVED and client.saved_card == card and len(card) == 0x14C
    assert client.saved_ram_script == script
    assert W.adapter_trace.last_serial == 0x7F7D | RFU.EN_FIRERED << 16, hex(W.adapter_trace.last_serial)
    assert child.link_players[0][26] == 2, child.link_players[0]                  # host language: English
    names = [t for t, _ in trace]
    assert any(n.startswith("broadcast data (0x16)") and n.endswith("English FireRed") for n in names), names
    assert "Distributor serial used: 0x7f7d, for English FireRed" in hw.text and "Warning" not in hw.text


@test("every game: Japanese Emerald still gets 0x7F7F; --serial overrides the choice; a card in the wrong language is warned about")
def _():
    def script(game):
        return (yield from RFU.find_distributor(game, compat=RFU.JP_EMERALD))
    hw, game, trace, st, counters = adapter_session(script, first_bit=True)
    assert hw.lg_error is None and hw.lg_result["serial"] == 0x7F7F and hw.lg_result["gname"]["language"] == 1
    def forced(game):
        return (yield from RFU.find_distributor(game, compat=RFU.EN_EMERALD, serial=0x1234))
    hw, game, trace, st, counters = adapter_session(forced, first_bit=True, serial=0x1234)
    assert hw.lg_error is None and hw.lg_result["serial"] == 0x1234, (repr(hw.lg_error), game.errors)
    assert "fixed at 0x1234" in hw.text and hw.lg_result["gname"]["language"] == 2
    path, card, scr = test_wc3("Japanese")
    def english(game):
        return (yield from RFU.find_distributor(game, compat=RFU.EN_EMERALD))
    hw, game, trace, st, counters = adapter_session(english, first_bit=True, wonder_card=path)
    assert hw.lg_error is None and hw.lg_result["serial"] == 0x7F7D
    assert "the Wonder Card is Japanese, but the game is English Emerald" in hw.text, hw.text


def test_news(language="Japanese", with_crc=True, news_id=0x0042):
    """Made-up Wonder News in the layout the tool reads (test data only - not any real event)."""
    size = 202 if language == "Japanese" else 444
    news = bytearray((i * 11 + 3) & 0xFF for i in range(size))
    news[0:2] = news_id.to_bytes(2, "little")
    news[2], news[3] = 1, 2                                 # sendType, bgType
    data = (W.game_crc16(news).to_bytes(4, "little") if with_crc else b"") + bytes(news)
    path = os.path.join(tempfile.gettempdir(), f"test_news_{language[:2]}_{int(with_crc)}.bin")
    open(path, "wb").write(data)
    return path, bytes(news)


def news_script(compat=RFU.JP_EMERALD, saved_news=None, news_size=202):
    def script(game):
        found = yield from RFU.find_distributor(game, compat=compat, news=True)
        yield from RFU.connect_to(game, found["id"])
        yield from RFU.send_child_name(game, RFU.child_name_bytes())
        yield from RFU.wait_join_status(game)
        child = RFU.ChildLink()
        client = yield from RFU.receive_gift(game, child, client_kw=dict(saved_news=saved_news, news_size=news_size))
        return found, child, client
    return script


@test("Wonder News: Japanese Emerald finds a news distributor (hasNews), saves the news and is told 'news received'")
def _():
    path, news = test_news("Japanese")
    hw, game, trace, st, counters = adapter_session(news_script(), first_bit=True, seconds=120, wonder_card=None,
                                                    wonder_news=path)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors, [t for t, _ in trace][-10:])
    found, child, client = hw.lg_result
    assert found["gname"]["hasNews"] and not found["gname"]["hasCard"] and found["gname"]["activity"] == 22, found
    assert client.result == RFU.CLI_MSG_NEWS_RECEIVED and client.saved_news == news, (client.result, client.history)
    assert "Wonder News loaded" in hw.text and "the game saved the news" in hw.text, hw.text
    names = [t for t, _ in trace]
    assert any("next, Wonder News" in n for n in names) and any("next, the game's answer" in n for n in names), names


@test("Wonder News: a game that already has the same news keeps it and is told so; an English game takes 444-byte news")
def _():
    path, news = test_news("Japanese", with_crc=False)
    hw, game, trace, st, counters = adapter_session(news_script(saved_news=news), first_bit=True, seconds=120,
                                                    wonder_news=path)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors)
    found, child, client = hw.lg_result
    assert client.result == RFU.CLI_MSG_HAD_NEWS and client.saved_news == news, (client.result, client.history)
    assert "already had this news" in hw.text, hw.text
    path, news = test_news("English")
    hw, game, trace, st, counters = adapter_session(news_script(RFU.EN_FIRERED, news_size=444), first_bit=True,
                                                    seconds=120, wonder_news=path)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors)
    found, child, client = hw.lg_result
    assert client.result == RFU.CLI_MSG_NEWS_RECEIVED and client.saved_news == news and found["serial"] == 0x7F7D


@test("Wonder News files: bare or with the save's CRC, Japanese or English; bad sizes refused, damage and ID 0 reported")
def _():
    for language in ("Japanese", "English"):
        for with_crc in (True, False):
            path, news = test_news(language, with_crc)
            lang, got, problems = W.parse_wonder_news(open(path, "rb").read())
            assert got == news and problems == [] and lang.startswith(language[:2]), (lang, problems)
    data = bytearray(open(test_news("English")[0], "rb").read()); data[20] ^= 1
    assert "checksum" in " ".join(W.parse_wonder_news(bytes(data))[2])
    assert "ID is 0" in " ".join(W.parse_wonder_news(open(test_news("Japanese", news_id=0)[0], "rb").read())[2])
    try:
        W.parse_wonder_news(bytes(300)); raise AssertionError("300 bytes accepted")
    except ValueError as e:
        assert "202" in str(e) and "444" in str(e)


import link_game_model as LG


def ereader_run(game, event=None, seconds=60, stop_on_game=True, race_window=0, si_flicker=0, path=None):
    """The DUO's e-Reader program against a simulated Ruby on the GBA link cable. `path` sends an
    existing file (an e-Card's strips) instead of `event`."""
    hw, duo = run42()
    hw.attach_mp_game(game.run(), game_master=game.master, race_window=race_window, si_flicker=si_flicker)   # the cable
    if event is not None:
        path = event_file(event)
    r = quiet(W.ereader_session, duo, types.SimpleNamespace(ereader=seconds, mystery_event=path),
              poll_s=0.2, stop_when=(lambda: hw.lg_done) if stop_on_game else None)
    hw.text = r[1]
    assert duo.hello() == 0x104
    hw.stop(); clean(hw)                              # nothing written to any cartridge
    return hw, r[0]


import mevent_model as ME


def test_me3(script_len=640, gift=(1, 0x97, 0x113), place=(8, 1, 1)):
    """A made-up saved Mystery Event in the .me3 layout: RAM script block (byte-sum checksum, magic
    0x33, map group, map number, person, script) and Record Mixing gift (byte-sum, count, chance,
    item). The script bytes are nonsense - no Nintendo data."""
    script = bytes(((i * 29 + 7) & 0xFF) or 1 for i in range(script_len))
    block = (bytes([0x33, *place]) + script).ljust(1000, b"\0")
    g = bytes([gift[0], gift[1]]) + gift[2].to_bytes(2, "little") if gift else bytes(4)
    return sum(block).to_bytes(4, "little") + block + (sum(g).to_bytes(4, "little") if gift else bytes(4)) + g


def event_file(data, name="test_event (ENG).me3"):
    path = os.path.join(tempfile.mkdtemp(), name)
    open(path, "wb").write(data)
    return path


TEST_ME3 = test_me3()
TEST_EVENT = W.prepare_event(TEST_ME3, "x (ENG).me3")[0]       # the script the DUO actually sends


@test("Mystery Event files: a .me3 is wrapped so Ruby stores exactly it; raw scripts are checked; damage, wrong language and other files are refused")
def _():
    for gift in ((1, 0x97, 0x113), None):
        me3 = test_me3(gift=gift)
        script, text, problems = W.prepare_event(me3, "x (ENG) (UK).me3")
        assert not problems and "Petalburg City Gym" in text and ("Eon Ticket" in text) == bool(gift), (text, problems)
        assert script[0] == W.MEV_CHECKCOMPAT and len(script) <= W.MEV_MAX
        for version in ("Ruby", "Sapphire"):
            status, saved, store = ME.run(script, "English", version)
            assert (status, saved) == (ME.LOAD_OK, True), (status, store["trace"])
            assert store["ram_script"] == me3[:1004] and store["gift"][:8] == me3[1004:], version
        assert ME.run(script, "German", "Ruby")[:2] == (ME.FAILURE, False)        # the game refuses it
    # the session-25 trap: a .me3 sent as it is gives "loaded OK" and a save, but stores nothing
    status, saved, store = ME.run(TEST_ME3)
    assert (status, saved) == (ME.LOAD_OK, True) and not any(store["ram_script"]) and not any(store["gift"])
    # damage on the way: the script's checksum command gives "loading error" and no save
    bad = bytearray(TEST_EVENT); bad[-3] ^= 0x40
    assert ME.run(bytes(bad))[:2] == (ME.LOAD_ERROR, False)
    # the file's own checks
    damaged = bytearray(TEST_ME3); damaged[300] ^= 1
    assert "checksum" in " ".join(W.prepare_event(bytes(damaged), "x.me3")[2])
    damaged = bytearray(TEST_ME3); damaged[1009] ^= 1
    assert "Record Mixing" in " ".join(W.prepare_event(bytes(damaged), "x.me3")[2])
    for data, name, word in ((bytes(300), "x.bin", "not a saved Mystery Event"),
                             (bytes([0x10]) + bytes(1011), "x.me3", "not a saved Mystery Event"),
                             (TEST_ME3, "x (FRE).me3", "French")):
        try:
            W.prepare_event(data, name); raise AssertionError(f"{name} accepted")
        except ValueError as e:
            assert word in str(e), e
    assert W.prepare_event(TEST_ME3, "x (GER).me3")[0][5] == 4               # German mask (1 << 2)
    jp = W.prepare_event(TEST_ME3, "x (JPN).me3")[0]                           # Japanese: 0x0001, as on
    assert jp[5] == 1 and ME.run(jp, "Japanese")[:2] == (ME.LOAD_OK, True)      # Nintendo's own cards
    assert ME.run(jp, "English")[:2] == (ME.FAILURE, False)
    # a script that's already a Mystery Event script goes as it is, after its own checks
    assert W.prepare_event(TEST_EVENT, "x.bin")[0] == TEST_EVENT
    wrong = bytearray(TEST_EVENT); wrong[11] = 0
    assert "0x4" in " ".join(W.prepare_event(bytes(wrong), "x.bin")[2])
    # and load_event refuses a file that fails its checks, before anything is sent
    try:
        quiet(W.load_event, None, event_file(bytes(damaged))); raise AssertionError("damaged file sent")
    except ValueError:
        pass


def gen3(text):
    """English Gen 3 text (capitals, small letters, digits and spaces), with its 0xFF end mark."""
    out = bytearray()
    for c in text:
        out.append(0 if c == " " else 0xBB + ord(c) - 65 if c.isupper() else 0xD5 + ord(c) - 97 if c.islower() else 0xA1 + int(c))
    return bytes(out) + b"\xff"


def test_ecb(name="TESTER", flavours=(0, 20, 0, 0, 30), pointers=0x02028D50):
    """A made-up saved Enigma Berry in the .ecb layout (pokeruby's EnigmaBerry record). Like a real
    file, its description pointers hold the saving game's addresses, which the checksum leaves out.
    The picture and texts are nonsense - no Nintendo data."""
    rec = bytearray(W.ECB_SIZE)
    rec[0:7] = gen3(name)[:7].ljust(7, b"\xff")
    rec[7], rec[8:10], rec[0x0A], rec[0x0B] = 3, (52).to_bytes(2, "little"), 4, 2      # firmness, size, yields
    rec[0x0C:0x14] = struct.pack("<II", pointers, pointers + 45)
    rec[0x14], rec[0x15:0x1A], rec[0x1A] = 12, bytes(flavours), 50                      # growth, flavours, smoothness
    rec[0x1B:0x49C] = bytes((i * 37 + 11) & 0xFF for i in range(0x49C - 0x1B))           # picture
    rec[0x49C:0x4BC] = bytes(range(32))                                                  # palette
    rec[0x4BC:0x4BC + 16] = gen3("A test berry").ljust(16, b"\0")
    rec[0x4E9:0x4E9 + 16] = gen3("Made up here").ljust(16, b"\0")
    rec[0x528], rec[0x529] = 6, 0
    rec[0x52C:0x530] = W.ecb_checksum(rec).to_bytes(4, "little")
    assert len(rec) == W.ECB_SIZE
    return bytes(rec)


TEST_ECB = test_ecb()


@test("Enigma Berry files: a .ecb is wrapped so Ruby stores exactly the berry, Norman can give it, and a second berry replaces the first; damage and empty berries are refused; Japanese berries get the Japanese mask")
def _():
    script, text, problems = W.prepare_event(TEST_ECB, "x RS - Tester Berry (USA).ecb")
    assert not problems and "TESTER BERRY" in text and "dry 20, sour 30" in text, (text, problems)
    assert script[0] == W.MEV_CHECKCOMPAT and len(script) == 36 + W.ECB_SIZE <= W.MEV_MAX
    for version in ("Ruby", "Sapphire"):
        status, saved, store = ME.run(script, "English", version)
        assert (status, saved) == (ME.SUCCESS, True), (status, store["trace"])
        assert store["trace"] == [W.MEV_CHECKCOMPAT, W.MEV_CHECKSUM, W.MEV_SETENIGMABERRY, W.MEV_END], store["trace"]
        b = store["berry"]
        assert b[:0x0C] == TEST_ECB[:0x0C] and b[0x14:] == TEST_ECB[0x14:], version   # all but the pointers
        assert store["berry_valid"] and store["berry_available"] and store["message"] == "berry", store
    assert ME.run(script, "German", "Ruby")[:2] == (ME.FAILURE, False)               # the game refuses it
    # a second berry replaces the first ("transform"); the same one again is "obtained"
    first = ME.run(script)[2]["berry"]
    other = W.prepare_event(test_ecb("OTHER", (10, 10, 10, 10, 10)), "y (ENG).ecb")[0]
    assert ME.run(other, berry=first)[2]["message"] == "berry transform"
    assert ME.run(script, berry=first)[2]["message"] == "berry obtained"
    # damage on the way: the checksum command gives "loading error" and no save
    bad = bytearray(script); bad[200] ^= 0x10
    assert ME.run(bytes(bad))[:2] == (ME.LOAD_ERROR, False)
    # the pointers really don't count: another game's addresses still pass the file's checks
    assert not W.parse_ecb(test_ecb(pointers=0x02031000))[1]
    # the file's own checks
    damaged = bytearray(TEST_ECB); damaged[0x300] ^= 1
    assert "checksum" in " ".join(W.prepare_event(bytes(damaged), "x.ecb")[2])
    empty = bytearray(TEST_ECB); empty[0x14] = 0
    empty[0x52C:0x530] = W.ecb_checksum(empty).to_bytes(4, "little")
    assert "growth time" in " ".join(W.prepare_event(bytes(empty), "x.ecb")[2])
    jp, text, _ = W.prepare_event(TEST_ECB, "x (JPN).ecb")
    assert jp[5] == 1 and ME.run(jp, "Japanese")[2]["berry_valid"] and "Japanese-named" in text, text
    try:
        W.prepare_event(TEST_ECB, "x (ITA).ecb"); raise AssertionError("Italian berry accepted")
    except ValueError as e:
        assert "Italian" in str(e), e
    assert "Norman" in W.event_hint(TEST_ECB) and "TESTER BERRY" in W.event_hint(TEST_ECB)
    try:
        quiet(W.load_event, None, event_file(bytes(damaged), "x (ENG).ecb")); raise AssertionError("damaged berry sent")
    except ValueError:
        pass


@test("e-Reader: an Enigma Berry (.ecb) goes across the link cable and Ruby stores it; the tool says to see Norman")
def _():
    game = LG.RubyMysteryEvent(master=True)
    hw, report = ereader_run(game, TEST_ECB)
    expected = W.prepare_event(TEST_ECB, "x (ENG).ecb")[0]
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-600:])
    assert hw.lg_result == sent_as(expected), (len(hw.lg_result or b""), hw.text[-400:])
    status, saved, store = ME.run(hw.lg_result, "English", "Ruby")
    assert (status, saved) == (ME.SUCCESS, True) and store["berry_valid"] and store["berry_available"], store["trace"]
    assert report["bad_checksums"] == 0, report
    for line in ("TESTER BERRY", "Mystery Event loaded", "sent the Mystery Event", "the game closed the link", "Norman"):
        assert line in hw.text, (line, hw.text[-1500:])


import ecard_fixtures as EC


def card_files(strips, name="08-X001 RS - Test Trainer (USA)"):
    """Write a made-up card's strips as the gallery names them."""
    folder = tempfile.mkdtemp()
    paths = []
    for i, strip in enumerate(strips):
        n = f"{name} (Strip {i + 1}).raw" if len(strips) > 1 else f"{name}.raw"
        paths.append(os.path.join(folder, n))
        open(paths[-1], "wb").write(strip)
    return paths


TEST_TRAINER = EC.test_trainer()


@test("e-Card scans: strips decode (Reed-Solomon checked, vpk0 both ways, two strips joined after their titles) and the card's own Mystery Event goes as it is; damaged strips, e-Reader programs and clock cards are refused")
def _():
    # a trainer card, as the real English ones: checkcompat, addtrainer, end
    script = EC.trainer_script(TEST_TRAINER, "English")
    for method, before in ((0, 400), (1, 400), (1, 3500)):              # the last needs two strips
        paths = card_files(EC.make_card(script, method, before))
        assert (len(paths) > 1) == (before > 3000), len(paths)
        for p in paths:                                                  # any strip finds the others
            sent, text, problems, hint = W.prepare_card(p)
            assert sent == script and not problems, (text, problems)
            assert "English" in text and "addtrainer" in text and f"{len(paths)} strip" in text, text
            assert "Mossdeep" in hint, hint
        for version in ("Ruby", "Sapphire"):
            status, saved, store = ME.run(sent, "English", version)
            assert (status, saved) == (ME.SUCCESS, True) and store["trainer"] == TEST_TRAINER, store["trace"]
        assert ME.run(sent, "Japanese")[:2] == (ME.FAILURE, False)
    # a berry card: the berry follows the script, as on the real cards
    berry_script = bytes(W.build_berry_script(TEST_ECB))
    sent = W.prepare_card(card_files(EC.make_card(berry_script))[0])[0]
    assert sent == berry_script and ME.run(sent)[2]["berry_valid"]
    # a damaged strip: one byte changed -> its codeword fails, and nothing is sent
    strip = bytearray(EC.make_card(script)[0]); strip[104 * 5 + 40] ^= 0x10
    s, text, problems, hint = W.prepare_card(card_files([bytes(strip)])[0])
    assert s is None and "Reed-Solomon" in " ".join(problems), problems
    # a program for the e-Reader itself (no vpk0), a card with no Mystery Event, a wrong size
    for card, word in ((EC.make_strip(b"\x10\x00" + bytes(300)), "programs for the e-Reader"),
                       (EC.make_card(bytes(500))[0], "no Mystery Event"),
                       (bytes(2000), "not an e-Reader strip")):
        try:
            W.prepare_card(card_files([card])[0]); raise AssertionError(f"accepted ({word})")
        except ValueError as e:
            assert word in str(e), e
    # a card that would turn on the clock reset is refused (this tool leaves clocks alone)
    clock = script[:17] + bytes([14, W.MEV_END])                     # checkcompat, enableresetrtc, end
    assert "clock" in " ".join(W.prepare_card(card_files(EC.make_card(clock))[0])[2])
    # damage inside the compressed program is caught too
    bad = bytearray(EC.vpk0_encode(b"ABCABCABC" * 20)); bad[13] ^= 0xFF
    try:
        W.vpk0_decode(bytes(bad)); raise AssertionError("damaged vpk0 accepted")
    except ValueError:
        pass


@test("e-Card trainer on the link cable: a Japanese card (initramscript, addtrainer) goes to a Japanese Ruby, which stores the trainer; the tool points to Mossdeep")
def _():
    script = EC.trainer_script(TEST_TRAINER, "Japanese", ram_script=bytes(range(1, 60)))
    paths = card_files(EC.make_card(script, method=1), "08-A001 RS - Test Trainer (JPN)")
    game = LG.RubyMysteryEvent(master=True, language=LG.LANG_JAPANESE)
    hw, report = ereader_run(game, path=paths[0])
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-600:])
    assert hw.lg_result == sent_as(script), (len(hw.lg_result or b""), hw.text[-400:])
    status, saved, store = ME.run(hw.lg_result, "Japanese", "Ruby")
    assert (status, saved) == (ME.SUCCESS, True) and store["trainer_valid"], store["trace"]
    assert store["ram_script"][4:8] == bytes([0x33, 25, 4, 1]), store["ram_script"][:8].hex()
    assert report["bad_checksums"] == 0 and report["game_language"] == 1, report
    for line in ("an e-Card", "Japanese", "Japanese", "sent the Mystery Event", "Mossdeep"):
        assert line in hw.text, (line, hw.text[-1500:])
    assert "can't be used" not in hw.text
    # the same card with an English Ruby: the tool says at once that the game will refuse it
    game = LG.RubyMysteryEvent(master=True)
    hw, report = ereader_run(game, path=paths[0])
    assert "The event is for Japanese games, so this English game will say it can't be used" in hw.text, hw.text[-900:]
    assert ME.run(hw.lg_result, "English")[:2] == (ME.FAILURE, False)


def test_pk3(species=409, pid=0x12345678, otid=0x0000_4E44, game=2, met=0xFF, fateful=True, lang=2,
             nickname="TESTMON", ot="TESTER", encrypted=False, party=False, moves=None, exp=1000):
    """A made-up Gen 3 Pokemon. PKHeX's form (decrypted, blocks in G-A-E-M order) unless
    `encrypted`, which gives the game's own form. Nothing here is a real event's data. `moves`: up
    to four move IDs (default Pound and Karate Chop), each with its full PP."""
    g = struct.pack("<HHIBBH", species, 0, exp, 0, 70, 0)
    if moves is None:
        a = struct.pack("<4H4B", 1, 2, 0, 0, 35, 25, 0, 0)
    else:
        import duo_battle as B
        ms = list(moves)[:4] + [0] * (4 - len(list(moves)[:4]))
        a = struct.pack("<4H4B", *ms, *[B.MOVES[m][4] if m else 0 for m in ms])
    e = bytes(12)
    m = struct.pack("<BBHII", 0, met, 5 | game << 7 | 4 << 11, 0x3FFFFFFF & 0x1F7BDEF7, (1 << 31) if fateful else 0)
    blocks = {"G": g, "A": a, "E": e, "M": m}
    plain_gaem = g + a + e + m
    checksum = sum(struct.unpack("<24H", plain_gaem)) & 0xFFFF
    if encrypted:
        shuffled = b"".join(blocks[c] for c in W.PK3_ORDERS[pid % 24])
        data = struct.pack("<12I", *[w ^ pid ^ otid for w in struct.unpack("<12I", shuffled)])
    else:
        data = plain_gaem
    head = struct.pack("<II", pid, otid) + gen3(nickname)[:10].ljust(10, b"\xff") + struct.pack("<H", lang)
    head += gen3(ot)[:7].ljust(7, b"\xff") + b"\0" + struct.pack("<HH", checksum, 0)
    return head + data + (bytes(20) if party else b"")


@test("Pokemon files (.pk3): PKHeX's decrypted form and the game's encrypted form are both read and checked; species, Pokedex number, trainer, origin and the event mark; damage reported; pk3-info needs no DUO")
def _():
    for encrypted in (False, True):
        for pid in (0x12345678, 0x9ABCDEF1, 23, 24 * 7 + 5):             # different block orders
            data = test_pk3(pid=pid, encrypted=encrypted)
            f, problems = W.parse_pk3(data)
            assert not problems, problems
            assert (f["dex"], f["name"], f["species"]) == (385, "JIRACHI", 409), f
            assert f["ot"] == "TESTER" and f["nickname"] == "TESTMON" and f["tid"] == 0x4E44 and f["sid"] == 0
            assert f["game"] == "Ruby" and f["met_location"] == 0xFF and f["fateful"] and f["met_level"] == 5
            assert f["ball"] == "Poke" and f["language"] == "English" and f["moves"] == [1, 2]
            assert ("encrypted" in f["form"]) == encrypted, f["form"]
            g = W.pk3_game_form(data)                                    # always the game's form
            assert W.parse_pk3(g)[0]["form"].startswith("the game's") and W.parse_pk3(g)[0]["blocks"] == f["blocks"]
            assert g == test_pk3(pid=pid, encrypted=True)
    # Pokedex numbers: Kanto/Johto as they are, Hoenn reordered, eggs
    assert W.pk3_species(151) == (151, "MEW") and W.pk3_species(277) == (252, "TREECKO")
    assert W.pk3_species(411) == (358, "CHIMECHO") and W.pk3_species(122) == (122, "MR. MIME")
    assert W.pk3_species(410) == (386, "DEOXYS") and W.pk3_species(412)[1] == "EGG"
    # a party Pokemon (100 bytes), a Japanese one, a shiny one
    assert W.parse_pk3(test_pk3(party=True))[0]["party"]
    jp = bytearray(test_pk3(lang=1)); jp[0x14:0x17] = bytes([0x01, 0x02, 0xFF])           # "あい"
    assert W.parse_pk3(bytes(jp))[0]["ot"] == "あい" and W.parse_pk3(bytes(jp))[0]["language"] == "Japanese"
    assert W.parse_pk3(test_pk3(pid=0x4E440000 | 0x0001, otid=0x00004E44))[0]["shiny"]
    # damage: one byte of the data, in either form
    for encrypted in (False, True):
        bad = bytearray(test_pk3(encrypted=encrypted)); bad[0x30] ^= 4
        assert "checksum" in " ".join(W.parse_pk3(bytes(bad))[1])
    for data in (bytes(79), bytes(101)):
        try:
            W.parse_pk3(data); raise AssertionError("accepted")
        except ValueError as e:
            assert "not a Gen 3 Pokemon" in str(e)
    # the command: no DUO, no USB
    path = event_file(test_pk3(), "385 - JIRACHI - TEST.pk3")
    old = W.UsbTransport
    W.UsbTransport = None                                               # it must not even try
    try:
        _, text = quiet(W.main, ["pk3-info", path])
    finally:
        W.UsbTransport = old
    assert "#385 JIRACHI" in text and "fateful encounter" in text and "PKHeX's (decrypted)" in text, text


@test("A file given to the wrong command is turned away before USB, with the command that sends it")
def _():
    old = W.UsbTransport
    W.UsbTransport = None                                               # it must not even try
    try:
        for argv, want in ((["gift", "--card", "RS - Item Eon Ticket (ENG) (UK).me3"], "event --event"),
                           (["event", "--event", "FL - Item MysticTicket (ENG) (US).wc3"], "gift --card"),
                           (["gift", "--card", "x.pk3"], "trade --pk3"),
                           (["trade", "--pk3", "08-A001 RS - Cool Trainer Devin (USA).raw"], "event --event")):
            try:
                quiet(W.main, argv); raise AssertionError(f"accepted {argv}")
            except SystemExit as e:
                assert want in str(e.code) and argv[2] in str(e.code), e.code
    finally:
        W.UsbTransport = old
    assert W.wrong_route("event", "x.me3") is None and W.wrong_route("gift", "x.wc3") is None
    assert W.wrong_route("event", "script.bin") is None                  # bare scripts are fine


@test("Japanese Emerald Trainer Hill e-Cards: the trainer record is found in the card's program (Japanese layout, byte-sum checked), several cards make one set, damage and other cards refused")
def _():
    cards = [card_files(EC.make_card(EC.hill_trainer(number=k, seed=k), before=256, after=2800),
                        f"19-A00{k} E - Test Trainer (JPN)")[0] for k in (1, 2, 3)]
    data, text, problems, hint = W.prepare_card(cards[0])
    assert not problems and "Trainer Hill" in text and "#1" in text and "Japanese Emerald" in text, (text, problems)
    assert len(data) == W.HILL_SET_SIZE and LG.validate_trainer_hill(data) == [1] and "Trainer Hill" in hint
    data3 = W.prepare_card(cards)[0]
    assert LG.validate_trainer_hill(data3) == [1, 2, 3]
    try:
        W.build_hill_set([EC.hill_trainer()] * 5); raise AssertionError("5 trainers accepted")
    except ValueError as e:
        assert "1 to 4" in str(e)
    damaged = bytearray(EC.hill_trainer()); damaged[300] ^= 1                    # one byte off: no record
    try:
        W.prepare_card(card_files(EC.make_card(bytes(damaged), before=256, after=2800), "19-A099 E - X (JPN)")[0])
        raise AssertionError("a damaged record accepted")
    except ValueError as e:
        assert "Trainer Hill" in str(e)


@test("Japanese Emerald's e-Reader screen on the link cable: the DUO answers within its 10 frames, link type 0x5503, sends the Trainer Hill set; the game checks it and closes; the tool points to the Trainer Hill")
def _():
    cards = [card_files(EC.make_card(EC.hill_trainer(number=k, seed=k), before=256, after=2800),
                        f"19-A00{k} E - Test Trainer (JPN)")[0] for k in (4, 7)]
    game = LG.RubyMysteryEvent(master=True, language=LG.LANG_JAPANESE, link_type=LG.LINKTYPE_EREADER_EM,
                               connect_within=10, press_a_after=16, check_language=False)
    hw, report = ereader_run(game, path=cards)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-600:])
    assert LG.validate_trainer_hill(hw.lg_result) == [4, 7], hw.text[-600:]
    assert report["game_link_type"] == 0x5503 and report["bad_checksums"] == 0, report
    for line in ("2 Trainer Hill e-Cards", "Trainer Hill set loaded", "link type 0x5503", "Trainer Hill on Route 111"):
        assert line in hw.text, (line, hw.text[-1500:])
    assert "can't be used" not in hw.text


@test("Japanese FireRed/LeafGreen Trainer Tower e-Cards: each card's floor record is found (Japanese layout), up to four go as one set, which the game's checks accept; Emerald and FireRed cards don't mix")
def _():
    cards = [card_files(EC.make_card(EC.tower_floor(number=k, seed=k, challenge=k % 4), before=256, after=2700),
                        f"15-A00{k} FRLG - Test Trainer (JPN)")[0] for k in (1, 2, 3, 4)]
    data, text, problems, hint = W.prepare_card(cards[:1])
    assert not problems and "Trainer Tower" in text and "#1" in text and "Seven Island" in hint, (text, problems)
    assert len(data) == 8 + W.TOWER_RECORD and LG.validate_trainer_tower(data) == [1]
    assert LG.validate_trainer_tower(W.prepare_card(cards)[0]) == [1, 2, 3, 4]
    hill = card_files(EC.make_card(EC.hill_trainer(number=9), before=256, after=2800), "19-A009 E - X (JPN)")[0]
    try:
        W.prepare_card([cards[0], hill]); raise AssertionError("mixed cards accepted")
    except ValueError as e:
        assert "different games" in str(e)


@test("Japanese FireRed's e-Reader screen on the link cable: link type 0x5502, two Trainer Tower floors arrive and pass the game's checks; the tool points to Seven Island")
def _():
    cards = [card_files(EC.make_card(EC.tower_floor(number=k, seed=k), before=256, after=2700),
                        f"15-A00{k} FRLG - Test Trainer (JPN)")[0] for k in (5, 6)]
    game = LG.RubyMysteryEvent(master=True, language=LG.LANG_JAPANESE, link_type=LG.LINKTYPE_EREADER_FRLG,
                               connect_within=10, press_a_after=16, check_language=False)
    hw, report = ereader_run(game, path=cards)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-600:])
    assert LG.validate_trainer_tower(hw.lg_result) == [5, 6], hw.text[-600:]
    assert report["game_link_type"] == 0x5502 and report["bad_checksums"] == 0, report
    for line in ("2 Trainer Tower e-Cards", "Trainer Tower set loaded", "Seven Island"):
        assert line in hw.text, (line, hw.text[-1500:])


@test("Pokemon files: the tool says how each event was originally given out - the Mystery Mew by trade, the Aura Mew by a multiboot program, unreleased ones never - and that a trade is the nearest route when it isn't the original")
def _():
    def route(ot, folder):
        d = os.path.join(tempfile.mkdtemp(), *folder)
        os.makedirs(d)
        path = os.path.join(d, "x.pk3")
        open(path, "wb").write(test_pk3(ot=ot))
        f = W.parse_pk3(open(path, "rb").read())[0]
        return W.pk3_route(path, f), W.describe_route(path, f)
    r, text = route("MYSTRY", ("Released", "Gen 3", "ENG", "Toys R Us"))
    assert r[1] == "trade" and "This trade is the original route" in text, text
    r, text = route("Aura", ("Released", "Gen 3", "ENG", "Aura Mew"))
    assert r[1] == "multiboot" and "multiboot program" in text and "nearest route" in text, text
    r, text = route("MYSTRY", ("Unreleased", "Gen 3", "ENG", "MYSTRY Mew"))
    assert r[1] == "never" and "Never distributed" in text, text
    r, text = route("PCNYd", ("somewhere else",))                      # moved out of the gallery: the name still tells
    assert r[1] == "machine" and "event machine" in text, text
    r, text = route("ROCKS", ("x",))
    assert r[1] == "unknown" and "isn't known" in text, text
    r, text = route("NOBODY", ("x",))
    assert r is None and "not in this tool's catalogue" in text, text
    # and the trade and pk3-info both say it
    path = event_file(test_pk3(ot="WISHMKR"), "385 - JIRACHI - TEST.pk3")
    _, out = quiet(W.pk3_info, [path])
    assert "Colosseum bonus disc" in out and "nearest route" in out, out


@test("e-Reader trainer files (.ect): wrapped so Ruby stores exactly the trainer, the tool points to Mossdeep; damaged and empty records refused; Japanese ones get the Japanese mask")
def _():
    script, text, problems = W.prepare_event(TEST_TRAINER, "08-A001 RS - Test (USA).ect")
    assert not problems and "e-Reader trainer" in text, (text, problems)
    status, saved, store = ME.run(script, "English", "Sapphire")
    assert (status, saved) == (ME.SUCCESS, True) and store["trainer"] == TEST_TRAINER, store["trace"]
    assert store["trace"] == [W.MEV_CHECKCOMPAT, W.MEV_CHECKSUM, W.MEV_ADDTRAINER, W.MEV_END]
    assert "Mossdeep" in W.event_hint(TEST_TRAINER)
    jp = W.prepare_event(TEST_TRAINER, "x (JPN).ect")[0]
    assert jp[5] == 1 and ME.run(jp, "Japanese")[2]["trainer_valid"]
    bad = bytearray(TEST_TRAINER); bad[50] ^= 1
    assert "checksum" in " ".join(W.prepare_event(bytes(bad), "x.ect")[2])
    assert "empty" in " ".join(W.prepare_event(bytes(188), "x.ect")[2])
    damaged = bytearray(W.prepare_event(TEST_TRAINER, "x.ect")[0]); damaged[100] ^= 8      # on the way
    assert ME.run(bytes(damaged))[:2] == (ME.LOAD_ERROR, False)


import trade_game_model as TG

TRADE_EVENT = None


def trade_run(master=True, accept=True, event=None, game_species=(25, 151, 280), pick=1, seconds=240, leaves_first=False,
              game_kind="ruby", national_dex=True, events=None, picks=None, in_the_way=None):
    """The DUO's trade program against a simulated Ruby in the Trade Center (docs/TRADE.md)."""
    event = event or test_pk3(species=409, pid=0x0BADCAFE, otid=0x00004E44)
    party = [W.pk3_party_form(test_pk3(species=sp, pid=0x1000 + sp, otid=0x2222)) for sp in game_species]
    game = TG.RubyTrade(master=master, party=party, pick=pick, accept=accept, leaves_first=leaves_first,
                        game=game_kind, national_dex=national_dex, trades=len(events) if events else 1, picks=picks,
                        in_the_way=in_the_way)
    hw, duo = run42()
    hw.attach_mp_game(game.run(), game_master=game.master)
    path = event_file(event, "385 - JIRACHI - TEST.pk3")
    if events:
        path = [event_file(e, f"{k} - TEST.pk3") for k, e in enumerate(events)]
    W.RECEIVED_DIR = os.path.join(tempfile.mkdtemp(), "received")      # (never the repo's own folder)
    r = quiet(W.trade_session, duo, types.SimpleNamespace(pk3=path, seconds=seconds), poll_s=0.2,
              stop_when=lambda: hw.lg_done)
    hw.text = r[1]
    assert duo.hello() == 0x104
    hw.stop(); clean(hw)                              # nothing written to any cartridge
    return hw, game, r[0], event, path


def kept_files(path):
    folder = W.RECEIVED_DIR
    return [open(os.path.join(folder, f), "rb").read() for f in sorted(os.listdir(folder))] if os.path.isdir(folder) else []


@test("trade, the game as master (the cable as fitted): the DUO walks to its seat, the parties swap, the game receives the event Pokemon exactly and saves; the DUO keeps what it was given as a .pk3; no National Dex")
def _():
    hw, game, report, event, path = trade_run(master=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    res = game.result
    assert res["received"] == W.pk3_party_form(event), "the game didn't receive the event Pokemon exactly"
    assert res["saved"] and not res["national_dex_enabled"] and res["partner_seat"] == (7, 5), res
    assert len(res["partner_party"]) == 1 and res["partner_pick"] == 0
    assert report["traded"] and report["bad_checksums"] == 0 and report["barriers"] == 4, report   # the room's fade-in, then the save's three
    assert kept_files(path) == [res["gave"]], "the .pk3 kept isn't what the game gave"
    assert W.parse_pk3(res["gave"])[0]["name"] == "MEW"
    for line in ("the DUO is player 1", "walking to the table", "swapping parties", "traded and saved", "You gave: #151 MEW", "Kept on this PC",
                 "back in the room", "walking back to the door", "leaving the room", "done"):
        assert line in hw.text, (line, hw.text[-1500:])
    # its trainer card and link player: the event's own trainer (TESTER, ID 19524, male), not blank
    card = res["partner_card"]
    assert card[0x30:0x38] == gen3("TESTER").ljust(8, b"\xff")[:8] and card[0x0E:0x10] == (0x4E44).to_bytes(2, "little"), card.hex()
    # ... as realistic as the event allows: a Pokedex, a new save's money and profile phrase, the
    # event Pokemon's own game (the test file's: Ruby), the party for FireRed/LeafGreen's card back
    assert card[0x02] == 1 and struct.unpack_from("<H", card, 0x0C)[0] == 1, card.hex()
    assert struct.unpack_from("<I", card, 0x24)[0] == 3000, card.hex()
    assert struct.unpack_from("<4H", card, 0x28) == (W.EC_I_AM, W.EC_A, W.EC_POKEMON, W.EC_GREAT), card.hex()
    assert card[0x38] == 2, card.hex()                               # Ruby: the test file's own game
    assert struct.unpack_from("<H", card, 0x54)[0] == W.parse_pk3(event)[0]["species"], card.hex()
    assert card[0] == 0 and card[0x38] == 2 and game.link_players[1]["name"][:7] == gen3("TESTER"), game.link_players[1]
    # the DUO's own screen: what it plays and where it has got to, shown only between link sessions
    for line in ("Playing: trade partner", "Offering JIRACHI", "Seated", "Traded, saved", "Done: link closed"):
        assert line in hw.log, (line, hw.log)
    # back in the room (lab session 29: the game froze here), the DUO walks to the door and leaves
    assert res["left_room"] and res["partner_left_by_door"], (res, game.log)
    assert "no trade this time" not in hw.text and "(for JIRACHI)" in os.listdir(W.RECEIVED_DIR)[0]


# ---------------------------------------------------------------- Record Mixing: Secret Bases
import mix_game_model as MG
import secret_bases as SB

BASE_CARD = """owner = {owner}
gender = {gender}
language = English
id = {tid}
location = {location}
decoration = Heavy Desk at 3, 5
decoration = Pikachu Doll at 4, 4
decoration = Red Plant at 8, 3
pokemon = Swampert Lv 45 @ Leftovers : Surf, Earthquake, Protect, Rest  EV 85  nature Brave
pokemon = Manectric Lv 43 @ Magnet : Thunderbolt, Roar, Quick Attack  EV 60
"""


def test_base(owner="WILLOW", gender="girl", tid=1234, location=162):
    card = BASE_CARD.format(owner=owner, gender=gender, tid=tid, location=location)
    if location // 10 != 16:                          # (the decorations fit a tree's first room only)
        card = "\n".join(l for l in card.splitlines() if not l.startswith("decoration"))
    return SB.card_to_sb3(card)


GAME_PLAYER = (0, b"\x39\x30\x12\x34", (gen3("MAY") + b"\xff" * 7)[:7])


def game_bases(own_location=222, others=()):
    """The game's 20 bases: its own (slot 0) at own_location, then `others` (.sb3 bytes)."""
    own = bytearray(SB.SB3_SIZE)
    if own_location:
        own[0] = own_location
        own[1] = GAME_PLAYER[0] << 4
        own[2:9] = GAME_PLAYER[2]
        own[9:13] = GAME_PLAYER[1]
    out = [bytes(own)] + list(others)
    assert all(len(b) == SB.SB3_SIZE for b in out)
    return [bytes(b) for b in out] + [bytes(SB.SB3_SIZE)] * (20 - len(out))


def game_tail(seed=5):
    r = random.Random(seed)
    tail = bytearray(r.getrandbits(8) for _ in range(MG.RECORD_SIZE - MG.TV_AT))
    tail[MG.GIFT_AT - MG.TV_AT:MG.GIFT_AT - MG.TV_AT + 2] = b"\0\0"
    return bytes(tail)


def mix_run(master=True, bases=(), game=None, gift=None, seconds=240, leaves_first=False, strict=False, extra=None,
            off_at=None, **game_kw):
    if isinstance(game, str):                         # (8 November: "emerald", the same Record Corner)
        game_kw["game"], game = game, None
    game = game or MG.RubyRecordCorner(master=master, bases=game_kw.pop("own", None) or game_bases(), player=GAME_PLAYER,
                                       tail=game_tail(), leaves_first=leaves_first, **game_kw)
    hw, duo = run42()
    hw.attach_mp_game(game.run(), game_master=game.master)
    paths = [event_file(b, f"{k} - TEST.sb3") for k, b in enumerate(bases)]
    W.BASES_DIR = os.path.join(tempfile.mkdtemp(), "bases")
    W.RECORDS_DIR = os.path.join(os.path.dirname(W.BASES_DIR), "records")
    back_on = switch_off_at(duo, off_at) if off_at is not None else None
    r = quiet(W.mix_session, duo, types.SimpleNamespace(base=paths, gift=gift, seconds=seconds, strict=strict, **(extra or {})),
              poll_s=0.2, stop_when=lambda: hw.lg_done)
    hw.text = r[1]
    if back_on:
        back_on()
    assert duo.hello() == 0x104
    hw.stop(); clean(hw)                              # nothing written to any cartridge
    return hw, game, r[0]


@test("Record Mixing with Emerald (8 November): the DUO is a Ruby player, so Emerald mixes in Ruby's layout - the 24 rounds go across both ways, the game files the bases and saves as with Ruby, and the tool says what Emerald's layout leaves out")
def _():
    ours = [test_base(), test_base(owner="ODA", gender="boy", tid=4321, location=1)]
    hw, game, report = mix_run(master=True, bases=ours, game="emerald")
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    res = game.result
    assert res["mixed"] and res["saved"] and res["left_room"], res
    assert game.link_players[game.other]["version"] & 0xFF == 2, game.link_players[game.other]
    assert res["partner_record"][:320] == b"".join(ours), "Emerald didn't receive our bases exactly"
    assert "To Emerald the DUO is a Ruby player" in hw.text, hw.text[-1500:]


@test("Record Mixing, the game as master (the cable as fitted): the DUO sits down, the 24 rounds go across, the game files the two bases by its own rules and saves; its other sections come back unchanged, the Battle Tower empty; the DUO walks out")
def _():
    ours = [test_base(), test_base(owner="ODA", gender="boy", tid=4321, location=1)]
    hw, game, report = mix_run(master=True, bases=ours)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    res = game.result
    assert res["mixed"] and res["saved"] and res["left_room"] and res["partner_left_by_door"], res
    assert res["partner_seat"] == (13, 6), res["partner_seat"]
    assert res["keys_while_mixing"] < 10, res["keys_while_mixing"]          # its room keys stop with the game's
    rec = res["partner_record"]
    assert rec[:320] == b"".join(ours), "the game didn't receive our bases exactly"
    assert rec[320:MG.TV_AT] == bytes(MG.TV_AT - 320)
    own = game.own_record()
    assert rec[MG.TV_AT:MG.BT_AT] == own[MG.TV_AT:MG.BT_AT], "the TV shows to the mail weren't handed back unchanged"
    assert rec[MG.BT_AT:MG.GIFT_AT] == bytes(MG.GIFT_AT - MG.BT_AT) and rec[MG.GIFT_AT:MG.GIFT_AT + 2] == b"\0\0"
    after = res["bases_after"]
    assert sorted(b[0] for b in after if b[0]) == sorted([222, 162, 1]), [b[0] for b in after]
    assert after == W.SB.predict_mix(res["bases_before"], ours + [bytes(160)] * 18, GAME_PLAYER), "the tool's prediction differs"
    assert report["mixed"] and report["bad_checksums"] == 0 and report["kept"] == [True, True], report
    for line in ("the DUO is player 1", "walking to the table", "mixing records", "Kept: WILLOW", "Kept: ODA",
                 "it now has 2 of the 2 bases", "back in the room", "leaving the room", "done"):
        assert line in hw.text, (line, hw.text[-2000:])
    assert len(report["files"]) == 1 and "the player's own" in report["files"][0]
    assert open(report["files"][0], "rb").read()[0] == 222
    for line in ("Playing: Record Corner", "Bringing 2 Secret Bases", "Mixed and saved", "Done: the link is closed"):
        assert line in hw.log, (line, hw.log)


@test("Record Mixing with a whole record (6 November): the DUO brings its old man, a trend, a TV show and a Battle Tower trainer; the game merges them by Ruby's rules exactly as the tool predicts, keeps its other parts, and the DUO brings the game's whole record back")
def _():
    import records as R
    sc = record_scenario(7)
    ours = R.split(sc["ours"])
    bard = bytearray(64); struct.pack_into("<6H", bard, 2, 11, 12, 13, 14, 15, 16); bard[0x1A:0x22] = SB.encode_name("WILLOW", 2).ljust(8, b"\xff")
    trend = struct.pack("<HHHH", 125 | 127 << 7, 5, 0x0101, 0x0202)
    show = bytearray(36); show[0], show[1] = 21, 0; struct.pack_into("<H", show, 0x10, 25); show[0x22:0x24] = b"\x44\x44"
    tower = bytearray(164); struct.pack_into("<H", tower, 2, 14); tower[4:12] = SB.encode_name("ODA", 2).ljust(8, b"\xff")
    tmp = tempfile.mkdtemp()
    files = {}
    for name, data, ext in (("old_man", bard, ".om3"), ("trend", trend, ".dt3"), ("tv", show, ".tv3"), ("tower", tower, ".bt3")):
        files[name] = os.path.join(tmp, "x" + ext); open(files[name], "wb").write(data)
    base = test_base()
    game = MG.RubyRecordCorner(master=True, bases=game_bases(), player=GAME_PLAYER, tail=sc["game_rec"][MG.TV_AT:],
                               tower_records=sc["tower"], seen=lambda sp: True, game_clear=True)
    sent_before = game.own_record()
    hw, game, report = mix_run(game=game, bases=[base], extra=dict(old_man=[files["old_man"]], trend=[files["trend"]],
                                                                   tv=[files["tv"]], tower=[files["tower"]]))
    assert hw.lg_error is None and game.result["mixed"], (repr(hw.lg_error), hw.text[-1500:])
    partner = game.result["partner_record"]
    got = R.split(partner)
    assert got["old_man"][0] == bytes(bard) and got["trends"][0] == trend and got["tv"][0] == bytes(show)
    assert got["tower"][0] == R.with_tower_checksum(tower), "the tool writes the Battle Tower checksum"
    assert got["news"][0] == sent_before[MG.NEWS_AT:MG.NEWS_AT + 64] and got["mail"][0] == sent_before[MG.MAIL_AT:MG.MAIL_AT + 120], \
        "the parts we didn't bring are the game's own, handed back"
    after = game.result["after"]
    our_tid = int.from_bytes(base[9:13], "little")
    state = dict(record=sent_before, tid=int.from_bytes(GAME_PLAYER[1], "little"), tower=sc["tower"], seen=lambda sp: True, game_clear=True)
    mine = R.predict(state, partner, our_tid, game_is_player0=True)
    assert mine["old_man"] == after["old_man"] and mine["trends"] == after["trends"] and mine["tv"][:24] == after["tv"][:24]
    assert after["trends"][0] == trend and after["old_man"][2:14] == bytes(bard[2:14])
    assert any(t[0] == 21 and t[1] == 1 and t[0x10] == 25 for t in after["tv"]), "our show is on the game's TV"
    assert after["tower_slot"] in mine["tower_slots"]
    assert report["game_record"] == sent_before, "the DUO didn't bring the game's whole record back exactly"
    assert open(report["record_file"], "rb").read() == sent_before
    shutil.rmtree(tmp)


@test("Record Mixing: the DUO's GBA is switched off as it walks out (7 November, hardware) - the game's whole record, copied while the DUO walked, is still kept, and the tool says when it's safe to switch off")
def _():
    hw, game, report = mix_run(master=True, bases=[test_base()], off_at=W.MIX_ST["EXITING"])
    text = hw.text
    r = game.result
    assert r["mixed"] and r["saved"], r
    assert "Keep the DUO's GBA switched on" in text, text[-1200:]
    assert report.get("record_file"), text[-1200:]
    assert open(report["record_file"], "rb").read() == game.own_record(), "the kept record isn't the game's"
    assert "safe to switch the DUO's GBA off now" in text


@test("Record Mixing, the DUO as master (player 0): it paces the 24 rounds itself, gives the Eon Ticket, reads the game's bases exactly; the player leaves first and the DUO follows")
def _():
    friend = test_base(owner="ZED", gender="boy", tid=777, location=131)
    own = game_bases(own_location=222, others=[friend])
    ours = [test_base(), test_base(owner="ODA", gender="boy", tid=4321, location=1)]
    hw, game, report = mix_run(master=False, bases=ours, own=own, gift="eon ticket", leaves_first=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    res = game.result
    assert res["mixed"] and res["saved"] and res["left_room"] and res["partner_seat"] == (6, 6), res
    assert res["gift_received"] == MG.ITEM_EON_TICKET, res["gift_received"]
    assert res["partner_record"][:320] == b"".join(ours)
    diff = [(i, k) for i, (a, b) in enumerate(zip(report["game_bases"], res["bases_before"])) for k in range(160) if a[k] != b[k]]
    assert not diff, ("the game's bases weren't read back exactly", diff[:10])
    assert report["kept"] == [True, True] and report["bad_checksums"] == 0, report
    assert len(report["files"]) == 2 and "ZED" in " ".join(report["files"])
    assert "the DUO is player 0" in hw.text and "Gift item: Eon Ticket" in hw.text and "***" not in hw.text, hw.text[-1500:]


@test("Record Mixing, the gift as player 1: the tool says the game won't take it, and it doesn't; with no bases at all the DUO only reads the game's, and the game keeps its own; the player leaves first and the DUO follows at once")
def _():
    hw, game, report = mix_run(master=True, bases=[], gift="Eon Ticket", leaves_first=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    res = game.result
    assert res["mixed"] and res["gift_received"] is None, res
    assert [b[0] for b in res["bases_after"]][:2] == [222, 0], [b[0] for b in res["bases_after"]]
    assert "won't take the gift item" in hw.text and "only reads the game's" in hw.text, hw.text[-1500:]
    diff = [(i, k) for i, (a, b) in enumerate(zip(report["game_bases"], res["bases_before"])) for k in range(160) if a[k] != b[k]]
    assert not diff and len(report["files"]) == 1, (diff[:10], report["files"])
    assert res["left_room"] and 0 <= res["partner_left_after"] <= 10, res.get("partner_left_after")


@test("Record Mixing, the game's own filing rules: a base at the player's own spot, one where the player has registered a base, and one with the player's own name and IDs are not kept, and the tool says so; the rest are")
def _():
    registered = bytearray(test_base(owner="REG", gender="boy", tid=55, location=1))
    registered[1] |= 0x40                             # registered at the player's PC
    own = game_bases(own_location=222, others=[bytes(registered)])
    me = bytearray(test_base(owner="MAY", gender="boy", tid=12345, location=141))
    me[9:13] = GAME_PLAYER[1]; me[2:9] = GAME_PLAYER[2]; me[1] = GAME_PLAYER[0] << 4
    ours = [test_base(location=222), test_base(owner="ODA", gender="boy", tid=4321, location=1), bytes(me),
            test_base(owner="KEPT", gender="boy", tid=99, location=162)]
    hw, game, report = mix_run(master=True, bases=ours, own=own)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    after = {b[0]: b for b in game.result["bases_after"] if b[0]}
    assert sorted(after) == [1, 162, 222] and after[1][2:5] == gen3("REG")[:3] and after[222][2:5] == gen3("MAY")[:3], sorted(after)
    assert report["kept"] == [False, False, False, True], report["kept"]
    for line in ("Not kept: WILLOW (Shrub 3, Route 120) - the player's own base is there", "Not kept: ODA", "Kept: KEPT",
                 "has the player's own name and IDs", "it now has 1 of the 4 bases"):
        assert line in hw.text, (line, hw.text[-2500:])


@test("Secret Base filing: the tool's copy of secret_base.c (secret_bases.predict_mix) agrees with the simulator's own port on 300 random sittings")
def _():
    r = random.Random(11)
    places = [i for i in SB.tables().locations]
    owners = [(g, bytes([t, 0, 0, 0]), (gen3(n) + b"\xff" * 7)[:7]) for g, t, n in
              ((0, 1, "AA"), (1, 2, "BB"), (0, 3, "CC"), (1, 4, "DD"), (0, 5, "EE"), (1, 6, "FF"))]
    def base(owner, place, registry=0, received=0):
        b = bytearray(160)
        b[0], b[1] = place, owner[0] << 4 | registry << 6
        b[2:9], b[9:13] = owner[2], owner[1]
        struct.pack_into("<H", b, 0x0E, received)
        return bytes(b)
    for case in range(300):
        player = owners[0]
        mine = [base(player, r.choice(places))] + [base(r.choice(owners[1:]), r.choice(places), r.choice((0, 0, 1)), r.randrange(4))
                                                  if r.random() < 0.6 else bytes(160) for _ in range(19)]
        theirs = [base(r.choice(owners), r.choice(places), 0, r.randrange(4)) if r.random() < 0.5 else bytes(160) for _ in range(20)]
        own = [bytearray(b) for b in mine]
        MG.mix_bases(own, [theirs, [bytes(160)] * 20] if False else [mine, theirs], 0, 2, player)
        assert [bytes(b) for b in own] == SB.predict_mix(mine, theirs, player), f"case {case} differs"


def party_mon(species, level, pid, moves, evs=(0,) * 6, item=0, egg=False, otid=0x00112233):
    """A made-up 100-byte party Pokemon in the game's own (encrypted) form."""
    g = struct.pack("<HHIBBH", species, item, 1000, 0, 70, 0)
    a = struct.pack("<4H4B", *moves, 35, 25, 10, 5)
    e = bytes(evs) + bytes(6)
    m = struct.pack("<BBHII", 0, 0, 5 | 2 << 7 | 4 << 11, (1 << 30) if egg else 0x1F7BDEF7 & 0x3FFFFFFF, 0)
    blocks = {"G": g, "A": a, "E": e, "M": m}
    shuffled = b"".join(blocks[c] for c in W.PK3_ORDERS[pid % 24])
    data = struct.pack("<12I", *[w ^ pid ^ otid for w in struct.unpack("<12I", shuffled)])
    head = struct.pack("<II", pid, otid) + bytes(24)
    return head + data + bytes([0, 0, 0, 0, level]) + bytes(15)


def save_with_bases(game, bases, party=(), seed=3):
    """A 128 KB save whose newest copy holds these Secret Bases and party (SaveBlock 1 is sections
    1-4); an older copy holds nothing, so reading the wrong copy shows."""
    data = bytearray(fixtures.make_gen3_save(seed=seed))
    for slot, newest in ((0, True), (1, False)):
        sb1 = bytearray(4 * 3968)
        if newest:
            at = SB.BASES_AT[game]
            for i, b in enumerate(bases):
                sb1[at + 160 * i:at + 160 * (i + 1)] = b
            sb1[SB.PARTY_COUNT_AT] = len(party)
            for i, mon in enumerate(party):
                sb1[SB.PARTY_AT + 100 * i:SB.PARTY_AT + 100 * (i + 1)] = mon
        for k in range(14):
            o = slot * 0xE000 + k * 0x1000
            sec = struct.unpack_from("<H", data, o + 0xFF4)[0]
            if 1 <= sec <= 4:
                body = bytearray(data[o:o + 0xFF4])
                body[:3968] = sb1[3968 * (sec - 1):3968 * sec]
                c = sum(struct.unpack_from("<992I", body, 0)) & 0xFFFFFFFF
                data[o:o + 0xFF4] = body
                struct.pack_into("<H", data, o + 0xFF6, ((c >> 16) + c) & 0xFFFF)
    return bytes(data)


@test("Secret Base files (.sb3): a card makes one and comes back from it unchanged; the game's structural rules refuse (location, name, team, items, gaps); fair play warns (dolls on the floor, posters off the wall, overlaps, moves, EVs)")
def _():
    card = BASE_CARD.format(owner="WILLOW", gender="girl", tid=1234, location="Tree, room 1, Route 121")
    data = SB.card_to_sb3(card)
    f, problems, warnings = SB.check_sb3(data)
    assert len(data) == 160 and not problems and not warnings, (problems, warnings)
    assert f["location"] == 162 and SB.owner_name(f) == "WILLOW" and f["gender"] == 1 and f["tid"] == 1234
    assert SB.NATURES[f["team"][0]["personality"] % 25] == "Brave" and f["team"][1]["moves"][3] == 0
    assert SB.card_to_sb3(SB.sb3_to_card(data)) == data, "a card written from an .sb3 doesn't make the same bytes"
    assert SB.file_name(f) == "WILLOW - Tree 1, Route 121 (ENG).sb3"
    try:
        SB.card_to_sb3(card.replace("Tree, room 1, Route 121", "Tree, Route 121")); raise AssertionError("ambiguous place taken")
    except ValueError as e:
        assert "2 tree spots" in str(e) and "(ID 162)" in str(e) and "(ID 172)" in str(e)
    for text, wanted in (("Leftovers", "Leftover"), ("Swampert", "Swampret")):
        try:
            SB.card_to_sb3(card.replace(text, wanted)); raise AssertionError("misspelling taken")
        except ValueError as e:
            assert f"did you mean {text.upper()}" in str(e), e
    def broken(fn):
        b = bytearray(data); fn(b)
        return SB.check_sb3(bytes(b))[1]
    assert any("75 Secret Base spots" in p for p in broken(lambda b: b.__setitem__(0, 7)))
    assert any("name" in p for p in broken(lambda b: b.__setitem__(slice(2, 9), b"\xff" * 7)))
    assert any("no Pokemon" in p for p in broken(lambda b: b.__setitem__(slice(0x7C, 0x88), bytes(12))))
    assert any("after the team" in p for p in broken(lambda b: b.__setitem__(0x96, 9)))
    assert any("can't be held" in p for p in broken(lambda b: struct.pack_into("<H", b, 0x88, 0x113)))
    assert any("isn't a Pokemon" in p for p in broken(lambda b: struct.pack_into("<H", b, 0x7C, 260)))
    assert any("first slots" in p for p in broken(lambda b: b.__setitem__(0x12, 0)))
    odd = SB.card_to_sb3(card.replace("Pikachu Doll at 4, 4", "Pikachu Doll at 6, 6").replace("Red Plant at 8, 3", "Ball Poster at 8, 3")
                         .replace("Thunderbolt, Roar", "Fly, Roar").replace("EV 60", "EV 90")
                         + "decoration = Small Chair at 4, 5\n")
    f, problems, warnings = SB.check_sb3(odd)
    assert not problems, problems
    for w in ("dolls and cushions sit on a mat or a desk", "a poster goes on the back wall", "overlaps Heavy Desk",
              "can't learn Fly", "EV number 90"):
        assert any(w in x for x in warnings), (w, warnings)
    paths = [event_file(odd, "odd.sb3")]
    assert quiet(W.load_bases, paths)[0] == [SB.normalise(odd)]
    try:
        quiet(W.load_bases, paths, strict=True); raise AssertionError("--strict let it through")
    except ValueError as e:
        assert "--strict" in str(e)
    twice = [event_file(data, "a.sb3"), event_file(SB.card_to_sb3(card.replace("WILLOW", "OTHER")), "b.sb3")]
    try:
        quiet(W.load_bases, twice); raise AssertionError("two bases in one spot taken")
    except ValueError as e:
        assert "keeps only the first" in str(e)
    try:
        quiet(W.load_bases, [event_file(data, f"{k}.sb3") for k in range(21)]); raise AssertionError("21 bases taken")
    except ValueError as e:
        assert "at most 20" in str(e)


@test("Secret Bases from a save backup (bases, base make/show): the newest copy's bases become .sb3 files, the player's own with its team from the party (Eggs left out, EVs averaged), the language from the cartridge code; FireRed and unknown games refused; no DUO needed")
def _():
    friend = test_base(owner="ZED", gender="boy", tid=777, location=131)
    own = bytearray(160); own[0] = 222; own[1] = 0x10; own[2:9] = (gen3("KIM") + b"\xff" * 7)[:7]; own[9:13] = b"\x01\x02\x03\x04"
    own[0x10] = 5                                     # (times entered: the player's own business)
    party = [party_mon(280, 20, 0x11111111, (1, 2, 3, 4), evs=(60, 0, 0, 0, 0, 0), item=3),
             party_mon(283, 5, 0x22222222, (5, 0, 0, 0), egg=True), party_mon(25, 30, 0x33333333, (85, 0, 0, 0))]
    for game, code in (("Ruby", "AXVD"), ("Emerald", "BPEE")):
        folder = os.path.join(tempfile.mkdtemp(), f"{code} POKEMON GAME")
        os.makedirs(folder)
        path = os.path.join(folder, "2026-11-04 120000 KIM #12.sav")
        open(path, "wb").write(save_with_bases(game, [bytes(own), friend], party))
        out = os.path.join(tempfile.mkdtemp(), "out")
        text = quiet(W.main, ["bases", path, "--out", out])[1]
        files = sorted(os.listdir(out))
        assert len(files) == 2 and "the player's own" in text and "ZED" in text, (files, text)
        mine = open(os.path.join(out, next(n for n in files if n.startswith("KIM"))), "rb").read()
        f, problems, warnings = SB.check_sb3(mine)
        team = [m for m in f["team"] if m["species"]]
        assert [m["species"] for m in team] == [280, 25] and team[0]["ev"] == 10 and team[0]["item"] == 3, team
        assert team[0]["level"] == 20 and team[0]["moves"] == [1, 2, 3, 4] and team[0]["personality"] == 0x11111111
        assert f["entered"] == 0 and f["language"] == (5 if game == "Ruby" else 2) and not problems, (f["language"], problems)
        assert open(os.path.join(out, next(n for n in files if n.startswith("ZED"))), "rb").read() == friend
    shown = quiet(W.main, ["base", "show", os.path.join(out, files[0])])[1]
    assert "pokemon = " in shown and "location   = " in shown
    card = os.path.join(tempfile.mkdtemp(), "Willow.txt")
    open(card, "w").write(BASE_CARD.format(owner="WILLOW", gender="girl", tid=1234, location=162))
    made = quiet(W.main, ["base", "make", card])[1]
    assert "Written:" in made and os.path.exists(os.path.join(os.path.dirname(card), "WILLOW - Tree 1, Route 121 (ENG).sb3"))
    frlg = os.path.join(tempfile.mkdtemp(), "BPRE POKEMON FIRE"); os.makedirs(frlg)
    open(os.path.join(frlg, "x.sav"), "wb").write(fixtures.make_gen3_save())
    for p, why in ((os.path.join(frlg, "x.sav"), "FireRed has no Secret Bases"), (event_file(fixtures.make_gen3_save(), "x.sav"), "which game")):
        try:
            quiet(W.main, ["bases", p]); raise AssertionError("taken")
        except SystemExit as e:
            assert why in str(e), e
    assert "mix --base" in W.wrong_route("trade", "base.sb3")


def secret_base_rom(code=b"AXVE", revision=1, seed=5):
    """A made-up 16 MB cartridge with everything the Secret Base Workshop looks for, at the addresses
    pret's notes give for English Ruby (duo_rom.WORKSHOP_PARTS): the 24 room layouts in the layout
    table, their maps and tilesets (one compressed), the decoration table, the object pictures and
    palettes. Random tiles and pictures: nothing here is a real game's data."""
    import duo_rom
    rng = random.Random(seed)
    where = duo_rom.WORKSHOP_PARTS[f"{code.decode()}{revision}"]
    g = bytearray(hwsim.make_game_rom(code=code, size=0x1000, tag_at=0x800, seed=seed, revision=revision))
    g += bytes(duo_rom.GAME_ROM_SIZE - len(g))
    free = [0x08600000]
    def put(addr, data):
        g[addr - 0x08000000:addr - 0x08000000 + len(data)] = data
        return addr
    def new(data):
        a = free[0]; free[0] = (a + len(data) + 3) & ~3
        return put(a, data)
    def stored_lz(raw):                                 # LZ77 with literals only: a real, valid stream
        out = bytearray([0x10]) + len(raw).to_bytes(3, "little")
        for i in range(0, len(raw), 8):
            out += b"\0" + raw[i:i + 8]
        return bytes(out)
    def tileset(compressed, first_pal):
        tiles = bytes(rng.getrandbits(8) for _ in range(512 * 32))
        pals = bytes(rng.getrandbits(8) for _ in range(16 * 32))
        metas = b"".join(struct.pack("<H", rng.randrange(1024) | rng.randrange(first_pal, first_pal + 6) << 12)
                         for _ in range(512 * 8))
        t = new(stored_lz(tiles) if compressed else tiles)
        return new(struct.pack("<BBHIIIII", compressed, 0, 0, t, new(pals), new(metas), 0, 0))
    primary, seconds = tileset(1, 0), [tileset(0, 6) for _ in range(6)]
    for k, (w, h) in enumerate(duo_rom.ROOM_SIZES):
        blocks = b"".join(struct.pack("<H", rng.choice([rng.randrange(512), 512 + rng.randrange(512)])) for _ in range(w * h))
        put(where["rooms"][k], struct.pack("<IIIIII", w, h, new(bytes(8)), new(blocks), primary, seconds[k % 6]))
    put(where["layouts"], struct.pack("<6I", *[0] * 6) + struct.pack("<24I", *where["rooms"]))
    gfx_at, gfx_size = where["gfx"]
    pal_at, pal_size = where["pals"]
    for i in range(pal_size // 8):
        put(pal_at + 8 * i, struct.pack("<IHH", new(bytes(rng.getrandbits(8) for _ in range(32))), 0x1100 + i, 0))
    for i in range(gfx_size // 4):
        side = rng.choice((16, 32))
        frame = new(struct.pack("<II", new(bytes(rng.getrandbits(8) for _ in range(side * side // 2))), side * side // 2))
        info = struct.pack("<HHHHHH", 0xFFFF, 0x1100 + i % (pal_size // 8), 0x1100, 0, side, side) + bytes(16) + struct.pack("<II", frame, 0)
        put(gfx_at + 4 * i, struct.pack("<I", new(info)))
    for k in range(121):
        first = rng.randrange(gfx_size // 4) if k >= 76 else rng.randrange(512)
        tiles = new(struct.pack("<9H", first, *[rng.randrange(512) for _ in range(8)]))
        rec = bytes([k]) + bytes(16) + bytes([rng.randrange(5), rng.randrange(10), rng.randrange(8)]) + bytes(8) + struct.pack("<I", tiles)
        put(where["decorations"] + 32 * k, rec)
    if "easy_chat" in where:                            # made-up Easy Chat words: "W2X0", "W2X1"... (text groups)
        words_at, table_at = where["easy_chat"]
        ptrs, at = [], words_at
        for k in range(22):
            ptrs.append(at)
            if k in (0, 18, 19):
                data = b"".join(struct.pack("<H", 1 + (k * 7 + i) % 350) for i in range(12))
            elif k == 21:
                data = b"".join(struct.pack("<H", 1 + i % 386) for i in range((table_at - at) // 2))
            else:
                data = b"".join(gen3(f"W{k}X{i}").rstrip(b"\xff") + b"\xff" for i in range(9))
            put(at, data)
            at += len(data)
            if k in (17, 18, 20):
                at += at & 1                            # (the id groups start on an even address)
        put(table_at, struct.pack("<22I", *ptrs))
    for t, (addr, size, kind) in enumerate(where.get("text", [])):     # made-up lines: "T3X1 {STR_VAR_1} END"
        text = lambda words: new(gen3(words).rstrip(b"\xff") + b"\xfd\x02\xfe" + gen3("END").rstrip(b"\xff") + b"\xff")
        if kind == "ptrs":
            put(addr, struct.pack(f"<{size // 4}I", *[text(f"T{t}X{i}") for i in range(size // 4)]))
        elif kind == "places":
            put(addr, b"".join(struct.pack("<BBBBI", 0, 0, 1, 1, new(gen3(f"PLACE {i}"))) for i in range(size // 8)))
        elif kind == "stories":
            put(addr, b"".join(struct.pack("<BBHIII", i + 1, 1, 0, new(gen3(f"STORY {i}")), new(gen3(f"DID {i}")),
                                           new(b"\xfd\x04" + gen3(" ").rstrip(b"\xff") + b"\xfd\x03\xfd\x02\xff")) for i in range(size // 16)))
        elif kind == "block" and size == 754:             # trainer class names, 13 bytes each
            put(addr, b"".join(gen3(f"CLASS {i}").ljust(13, b"\xff") for i in range(size // 13)))
        elif kind == "block" and size < 100:              # facility class -> name index
            put(addr, bytes(i % 58 for i in range(size)))
        elif kind == "block":                             # items: 44 bytes each, the price at +16
            put(addr, b"".join(bytes(16) + struct.pack("<H", 10 * i) + bytes(26) for i in range(size // 44)))
        elif kind == "string":
            put(addr, gen3("LINE").rstrip(b"\xff") + b"\xfd\x02\xff")
    return bytes(g)


@test("ROM copy for the workshop (duo_rom.py): only the parts the Secret Base Workshop draws with, found by pret's addresses and checked; the workshop draws every room, decoration and doll, and reads every Easy Chat word and the games' own lines, from them exactly as from the whole ROM")
def _():
    import duo_rom
    g = secret_base_rom()
    hw, duo = device(game=g)
    out = tempfile.mkdtemp()
    (path, data, info), text = quiet(duo_rom.dump, duo, types.SimpleNamespace(out=out, map=None, whole=False))
    hw.stop(); clean(hw)
    assert path.endswith("rev 1 - workshop parts.gba") and len(data) == len(g) and hw.save_writes == 0, path
    got = sum(1 for i in range(0, len(data), 4096) if any(data[i:i + 4096]))
    assert got < 400, f"read {got} 4 KB blocks: more than the workshop needs"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Skip("needs Python's playwright to compare the workshop's pictures")
    full = os.path.join(out, "whole.gba")
    open(full, "wb").write(g)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pg = browser.new_page()
            pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
            pg.goto("file://" + os.path.join(paths.ROOT, "secret_base_workshop.html"))
            pg.wait_for_function("typeof T !== 'undefined' && T && typeof S !== 'undefined' && S")
            draw = """async (b64) => {
                const bin = atob(b64), rom = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) rom[i] = bin.charCodeAt(i);
                const r = readRom(rom), out = [];
                for (const id of [1, 61, 103, 162, 183, 233]) out.push(r.picture(id, [{d: 3, x: 1, y: 3}, {d: 77, x: 2, y: 2}, {d: 66, x: 2, y: 0}]));
                for (let d = 1; d <= 120; d++) out.push(r.preview(d));
                out.push(JSON.stringify(readEasyChat(rom).groups));
                const t = readRomText(rom);
                out.push(JSON.stringify({tv: t.tv, std: t.std, places: t.places, stories: t.stories, d: t.dewford, b: t.bard, c: t.classOf(4), p: t.price(13)}));
                return out; }"""
            import base64
            a = pg.evaluate(draw, base64.b64encode(g).decode())
            b = pg.evaluate(draw, base64.b64encode(data).decode())
        finally:
            browser.close()
    assert a == b, [k for k, (x, y) in enumerate(zip(a, b)) if x != y][:10]


@test("ROM copy (duo_rom.py): a game without Secret Bases (LeafGreen) is turned away before anything is read, unless --whole")
def _():
    import duo_rom
    g = hwsim.make_game_rom(code=b"BPGE", title=b"POKEMON LEAF", size=0x1000, tag_at=0x800, rom_size=0x200000, seed=3)
    hw, duo = device(game=g)
    try:
        quiet(duo_rom.dump, duo, types.SimpleNamespace(out=tempfile.mkdtemp(), map=None, whole=False))
    except M.DuoError as e:
        assert "no Secret Bases" in str(e) and "--whole" in str(e), e
    else:
        raise AssertionError("LeafGreen wasn't turned away")
    finally:
        hw.stop(); clean(hw)


@test("ROM copy (duo_rom.py): the whole cartridge ROM, 64 KB at a time, each checked against the GBA's own CRC; only the DUO-covered header bytes differ; the save is never touched")
def _():
    import duo_rom
    g = hwsim.make_game_rom(code=b"AXVE", tag=b"FLASH1M_V103", size=0x180000, rom_size=0x200000, seed=7)
    hw, duo = device(game=g)
    out = tempfile.mkdtemp()
    (path, data, info), text = quiet(duo_rom.dump, duo, types.SimpleNamespace(out=out, map=None, whole=True))
    hw.stop(); clean(hw)
    assert len(data) == len(g) and open(path, "rb").read() == data and path.endswith("(AXVE) rev 0.gba"), (path, len(data))
    assert data[:0x20] == g[:0x20] and data[0xA0:] == g[0xA0:], "the ROM copy differs outside the DUO-covered header"
    assert data[0x20:0x9C] == bytes(0x7C) and "Saved:" in text and hw.save_writes == 0


@test("Secret Base Workshop (secret_base_workshop.html): its game tables and locations are exactly secret_bases.py's")
def _():
    page = open(os.path.join(paths.ROOT, "secret_base_workshop.html"), encoding="utf-8").read()
    src = open(os.path.join(paths.ROOT, "secret_bases.py"), encoding="utf-8").read()
    tables = re.search(r'_TABLES = """(.*?)"""', src, re.S).group(1).replace("\n", "")
    places = " ".join(re.search(r'_LOCATIONS = """(.*?)"""', src, re.S).group(1).split())
    assert f'const TABLES_B64 = "{tables}";' in page, "the workshop's tables differ from secret_bases.py's"
    assert f'const LOCATIONS_TXT = "{places}";' in page, "the workshop's locations differ from secret_bases.py's"


@test("Secret Base Workshop: Generate makes a valid base in every one of the 75 spots (no rule broken, the door reaches the owner and the PC, at most 16, positions 0-15), and changing spot asks first and starts the room empty")
def _():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Skip("needs Python's playwright to run the page")
    page_path = os.path.join(paths.ROOT, "secret_base_workshop.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pg = browser.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
            pg.goto("file://" + page_path)
            pg.wait_for_function("typeof T !== 'undefined' && T && typeof S !== 'undefined' && S")
            bad = pg.evaluate("""() => {
                const out = [];
                for (const id of T.locations.keys()) for (let s = 1; s <= 2; s++) {
                    const g = generateBase(id, id * 977 + s * 31337), res = checkDecorations(id, g.list);
                    if (res.why.some(Boolean) || res.bag.length || g.list.length > 16 || g.list.length < 4
                        || !walkable(id, g.list) || g.list.some(q => q.x > 15 || q.y > 15)) out.push([id, s, res.why, g.list.length]);
                }
                return out; }""")
            assert not bad, bad[:5]
            pg.click("#newBtn"); pg.click("#genBtn")
            assert pg.evaluate("checkAll().bad.length === 0 && checkAll().warn.length === 0"), pg.evaluate("checkAll()")
            before = pg.evaluate("S.location")
            pg.select_option("#spot", index=2)
            assert pg.evaluate("$('switchDlg').open") and pg.evaluate("S.location") == before, "changing spot didn't ask first"
            pg.click("#switchGo")
            assert pg.evaluate("S.location") != before and pg.evaluate("S.decorations.length") == 0
            pg.click("#cats button[data-cat='CHAIR']"); pg.click("#palette button >> nth=0")
            pg.click("#board .cell[data-x='3'][data-y='3']"); pg.click("#board .cell[data-x='5'][data-y='3']")
            assert pg.evaluate("S.decorations.length") == 1 and pg.evaluate("pick") is None, "a pick placed more than once"
            assert not errors, errors
        finally:
            browser.close()


@test("Record Workshop (secret_base_workshop.html): the old man, trends and whole-record tabs make the same bytes as records.py - the Easy Chat words read from the ROM, a Bard's .om3, .dt3 trends in the game's order, a Ruby save's record, an .rm3 with parts added")
def _():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Skip("needs Python's playwright to run the page")
    import records as R
    rom = secret_base_rom()
    tmp = tempfile.mkdtemp()
    rom_path = os.path.join(tmp, "rom.gba"); open(rom_path, "wb").write(rom)
    bard = bytearray(64); struct.pack_into("<6H", bard, 2, 3 << 9 | 1, 3 << 9 | 2, 5 << 9 | 0, 0 << 9 | 1, 18 << 9 | 127, 7 << 9 | 8)
    trend = struct.pack("<HHHH", 30 | 80 << 7, 7, 3 << 9 | 4, 4 << 9 | 5)
    save = save_with_sb([(R.SB1_AT["old_man"], bytes(bard)), (R.SB1_AT["trends"], trend + bytes(32))])
    save_path = os.path.join(tmp, "AXVE.sav"); open(save_path, "wb").write(save)
    page_path = os.path.join(paths.ROOT, "secret_base_workshop.html")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pg = browser.new_page(accept_downloads=True)
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
            pg.goto("file://" + page_path)
            pg.wait_for_function("typeof T !== 'undefined' && T && typeof S !== 'undefined' && S")
            pg.set_input_files("#romFile", rom_path)
            pg.wait_for_function("EC !== null", timeout=60000)
            assert pg.evaluate("EC.groups[3][1]") == "W3X1" and pg.evaluate("wordText(3 << 9 | 2)") == "W3X2"
            mon, move = pg.evaluate("wordText(0 << 9 | 1)"), pg.evaluate("wordText(18 << 9 | 127)")
            assert mon == "Bulbasaur" and move == SB.move_name(127).title(), (mon, move)
            # the Bard
            pg.click("#tab-oldman"); pg.select_option("#omKind", "0")
            for i, w in enumerate(["W3X1", "W3X2", "W5X0", mon, move, "7:8"]):
                pg.fill(f"[data-word='song{i}']", w); pg.press(f"[data-word='song{i}']", "Tab")
            pg.fill("#omAuthor", "WILLOW"); pg.press("#omAuthor", "Tab")
            pg.fill("#omAuthorId", "1234"); pg.press("#omAuthorId", "Tab")
            with pg.expect_download() as dl:
                pg.click("#omSave")
            om = open(dl.value.path(), "rb").read()
            assert dl.value.suggested_filename == "BARD - song by WILLOW (ENG).om3", dl.value.suggested_filename
            f = R.parse_old_man(om)
            assert f["song"] == list(struct.unpack_from("<6H", bard, 2)) and f["new_song"] == f["song"], f
            assert R.text(f["player"]) == "WILLOW" and struct.unpack("<I", f["player_id"])[0] == 1234 and R.check_part("old_man", om) == ([], [])
            said = pg.inner_text("#omPreview")                           # (the game's layout: two verses of word word / word)
            assert "W3X1 W3X2\nW5X0" in said and "LINE" in said, said
            # trends: two, saved together (a zip), in Ruby's order
            pg.click("#tab-trends"); pg.click("#trAdd"); pg.click("#trAdd")
            pg.fill("[data-word='t0w0']", "W3X4"); pg.press("[data-word='t0w0']", "Tab")
            pg.fill("[data-word='t0w1']", "W4X5"); pg.press("[data-word='t0w1']", "Tab")
            pg.fill("[data-word='t1w0']", "W9X1"); pg.press("[data-word='t1w0']", "Tab")
            pg.fill("[data-word='t1w1']", "W9X2"); pg.press("[data-word='t1w1']", "Tab")
            pg.fill(".trend[data-t='1'] [data-tf='trend']", "88"); pg.press(".trend[data-t='1'] [data-tf='trend']", "Tab")
            pg.fill(".trend[data-t='1'] [data-tf='max']", "99"); pg.press(".trend[data-t='1'] [data-tf='max']", "Tab")
            assert pg.inner_text("#trOrder").startswith("W9X1 W9X2"), pg.inner_text("#trOrder")
            with pg.expect_download() as dl:
                pg.click("#trSave")
            import zipfile
            z = zipfile.ZipFile(dl.value.path())
            dts = [z.read(n) for n in sorted(z.namelist())]
            parsed = [R.parse_trend(d) for d in dts]
            assert parsed[0]["words"] == [3 << 9 | 4, 4 << 9 | 5] and (parsed[0]["trendiness"], parsed[0]["max_trendiness"]) == (60, 90)
            assert parsed[1]["words"] == [9 << 9 | 1, 9 << 9 | 2] and (parsed[1]["trendiness"], parsed[1]["max_trendiness"]) == (88, 99)
            # the whole record: a Ruby save's own, then our old man and trends in it
            pg.click("#tab-record")
            pg.set_input_files("#recFile", save_path)
            pg.wait_for_function("REC.from === 'AXVE'")
            got = bytes(pg.evaluate("Array.from(joinRecord())"))
            assert got == R.record_from_save(save), [i for i in range(len(got)) if got[i] != R.record_from_save(save)[i]][:10]
            pg.click("#tab-oldman"); pg.click("#omToRecord")
            pg.click("#tab-trends"); pg.click("#trToRecord")
            pg.click("#tab-record"); pg.select_option("#recGift", str(0x113))
            with pg.expect_download() as dl:
                pg.click("#recSave")
            rm3 = open(dl.value.path(), "rb").read()
            want = R.split(R.record_from_save(save))
            want["old_man"], want["trends"], want["gift"] = [om], dts + [bytes(8)] * 3, 0x113
            assert rm3 == R.join(want), "the workshop's .rm3 isn't records.py's"
            assert "mix --record" in pg.inner_text("#recCmd")
            assert not errors, errors
        finally:
            browser.close()
            shutil.rmtree(tmp)


@test("Record Workshop: a designed Secret Base goes straight into the whole record with its Put it in the record button (no .sb3 download), byte for byte the .sb3 it would save; the same owner's base at the same spot is replaced, not doubled; an unfinished base isn't put in")
def _():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Skip("needs Python's playwright to run the page")
    import records as R
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pg = browser.new_page(accept_downloads=True)
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
            pg.goto("file://" + os.path.join(paths.ROOT, "secret_base_workshop.html"))
            pg.wait_for_function("typeof T !== 'undefined' && T && typeof S !== 'undefined' && S")
            pg.click("#tab-bases"); pg.click("#newBtn"); pg.click("#genBtn")
            assert pg.evaluate("checkAll().bad.length") == 0, pg.evaluate("checkAll()")
            with pg.expect_download() as dl:
                pg.click("#saveSb3")
            sb3 = open(dl.value.path(), "rb").read()
            pg.click("#baseToRecord")
            note = pg.inner_text("#saveNote")
            assert "Put in the record" in note and "1 of 20" in note, note
            pg.click("#tab-record")
            with pg.expect_download() as dl:
                pg.click("#recSave")
            bases = R.split(open(dl.value.path(), "rb").read())["bases"]
            assert bases[0] == sb3 and not any(any(b) for b in bases[1:]), "the record's base isn't the .sb3's bytes"
            pg.click("#tab-bases"); pg.click("#genBtn"); pg.click("#baseToRecord")   # a new design: same owner and spot
            second = bytes(pg.evaluate("Array.from(checkAll().bytes)"))
            note = pg.inner_text("#saveNote")
            assert "Updated in the record" in note and "1 of 20" in note, note
            assert pg.evaluate("REC.parts.bases.filter(any).length") == 1
            assert bytes(pg.evaluate("Array.from(REC.parts.bases[0])")) == second
            pg.evaluate("S.decorations = []; S.team = []; render()")             # unfinished: no team
            if pg.evaluate("checkAll().bad.length"):
                pg.click("#baseToRecord")
                assert "Not put in the record yet" in pg.inner_text("#saveNote"), pg.inner_text("#saveNote")
                assert pg.evaluate("REC.parts.bases.filter(any).length") == 1
            assert not errors, errors
        finally:
            browser.close()


@test("Record Workshop: the TV, PokéNews, day-care letter and Battle Tower tabs make the bytes records.py reads back (a show off the air so it travels, news, a letter, a Tower trainer with its checksum), play the game's own lines from the ROM, and all of it goes into one .rm3")
def _():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Skip("needs Python's playwright to run the page")
    import records as R, zipfile
    tmp = tempfile.mkdtemp()
    rom_path = os.path.join(tmp, "rom.gba"); open(rom_path, "wb").write(secret_base_rom())
    def typed(pg, sel, value):
        pg.fill(sel, value); pg.press(sel, "Tab")
    def saved(pg, button):
        with pg.expect_download() as dl:
            pg.click(button)
        return dl.value.suggested_filename, open(dl.value.path(), "rb").read()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pg = browser.new_page(accept_downloads=True)
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
            pg.goto("file://" + os.path.join(paths.ROOT, "secret_base_workshop.html"))
            pg.wait_for_function("typeof T !== 'undefined' && T && typeof S !== 'undefined' && S")
            pg.set_input_files("#romFile", rom_path)
            pg.wait_for_function("EC !== null && ROMTEXT !== null", timeout=60000)
            # a TV show: Pokémon Today, caught
            pg.click("#tab-tv"); pg.select_option("#tvKind", "21")
            typed(pg, "#tvBody [data-fk='0']", "Pikachu"); typed(pg, "#tvBody [data-fk='1']", "SPARKY")
            typed(pg, "#tvBody [data-fk='2']", "Great Ball"); typed(pg, "#tvBody [data-fk='3']", "3")
            typed(pg, "#tvBody [data-fk='4']", "WILLOW"); typed(pg, "#tvMadeBy", "4321")
            name, tv = saved(pg, "#tvSave")
            assert name == "TV - Pokémon Today caught - WILLOW (ENG).tv3", name
            assert tv[0] == 21 and tv[1] == 0 and struct.unpack_from("<H", tv, 0x10)[0] == 25 and tv[0x0F] == 3 and tv[0x12] == 3, tv.hex()
            assert R.text(tv[4:15]) == "SPARKY" and R.text(tv[0x13:0x1B]) == "WILLOW" and struct.unpack_from("<H", tv, 0x22)[0] == 4321, tv.hex()
            assert R.check_part("tv", tv)[0] == []
            screen = pg.inner_text("#tvScreen")
            assert "WILLOW" in screen and "END" in screen, screen        # (the made-up lines, with the show's names in)
            # PokéNews
            pg.click("#tab-news"); pg.select_option("[data-ni='0'] [data-nf='kind']", "1")
            name, news = saved(pg, "#newsSave")
            assert news[:4] == bytes([1, 1, 3, 0]) and not any(news[4:]) and "END" in pg.inner_text("#newsSay")
            # a day-care letter
            pg.click("#tab-mail")
            typed(pg, "[data-lj='0'] [data-fk='0']", "Orange Mail")
            typed(pg, "[data-word='ml0-1']", "W3X1"); typed(pg, "[data-word='ml0-2']", "W4X2")
            typed(pg, "[data-lj='0'] [data-fk='10']", "MAY"); typed(pg, "[data-lj='0'] [data-fk='11']", "12345")
            pg.select_option("#mailCount", "1")
            name, mail = saved(pg, "#mailSave")
            m = R.parse_mail(mail)
            assert m["letters"][0]["mail_item"] == 121 and m["letters"][0]["words"][:2] == [3 << 9 | 1, 4 << 9 | 2]
            assert R.text(m["letters"][0]["writer"]) == "MAY" and m["letters"][0]["writer_id"] == 12345 and m["count"] == 1 and m["no_item"][0]
            # a Battle Tower trainer
            pg.click("#tab-tower")
            typed(pg, "#towerHead [data-fk='1']", "ODA"); typed(pg, "#towerHead [data-fk='2']", "1234"); typed(pg, "#towerHead [data-fk='4']", "21")
            pg.select_option("#towerClass", "4")
            for k, (mon, move) in enumerate((("Swampert", "Earthquake"), ("Manectric", "Thunderbolt"), ("Gardevoir", "Psychic"))):
                typed(pg, f"[data-mk='{k}'] [data-fk='0']", mon); typed(pg, f"[data-mk='{k}'] [data-fk='2']", move)
            name, bt = saved(pg, "#towerSave")
            f = R.parse_tower(bt)
            assert R.check_part("tower", bt)[0] == [], R.check_part("tower", bt)
            assert R.text(f["name"]) == "ODA" and f["tid"] == 1234 and f["streak"] == 21 and f["trainer_class"] == 4 and len(f["party"]) == 3
            assert [x["level"] for x in f["party"]] == [50, 50, 50] and f["party"][0]["moves"][0] == SB._lookup("EARTHQUAKE", SB.tables().moves, "m")
            assert all(x["ot_id"] == 1234 for x in f["party"])
            assert "Class 4" in pg.inner_text("#towerPreview"), pg.inner_text("#towerPreview")   # (the class name from the ROM)
            # all of it in one record
            for t, b in (("tv", "#tvToRecord"), ("news", "#newsToRecord"), ("mail", "#mailToRecord"), ("tower", "#towerToRecord")):
                pg.click(f"#tab-{t}"); pg.click(b)
            pg.click("#tab-record")
            name, rm3 = saved(pg, "#recSave")
            want = R.split(R.join({}))
            want["tv"][0], want["news"], want["mail"], want["tower"] = tv, [news], [mail], [bt]
            assert rm3 == R.join(want), [i for i in range(len(rm3)) if rm3[i] != R.join(want)[i]][:12]
            assert not errors, errors
        finally:
            browser.close()
            shutil.rmtree(tmp)


@test("Record Mixing: a session stopped early (Ctrl+C) leaves the DUO's program running; the next run ends it and connects at once (6 November, hardware), and the copy of the game's bases shows its progress")
def _():
    game = MG.RubyRecordCorner(master=True, bases=game_bases(), player=GAME_PLAYER, tail=game_tail())
    hw, duo = run42()
    hw.attach_mp_game(game.run(), game_master=game.master)
    W.run_program(duo, "mix")
    said = []
    assert duo.connect(wait_s=20, say=said.append) == 0x104, said
    assert any("still running the last session's program" in m for m in said), said
    assert not any("unexpected answer" in m for m in said), said
    W.run_program(duo, "mix")                                     # and it runs a program again after that
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        data = W.Copier(duo, 4, "the game's bases", total=W.SB.SB3_SIZE * W.SB.BASES_IN_SAVE // 4).finish()
    assert len(data) == 3200 and "Copying the game's bases [########################] 100%" in out.getvalue()
    assert W.stop_program_quietly(duo) is not None and duo.hello() == 0x104
    hw.stop(); clean(hw)


@test("Run logs (runlog.py): every tool run writes its command, everything it printed and any error to logs/, with latest.log the newest")
def _():
    tmp = tempfile.mkdtemp()
    try:
        env = dict(os.environ, ACTIONREPLAY_LOG_DIR=tmp)
        env.pop("ACTIONREPLAY_NO_LOG", None)
        r = subprocess.run([sys.executable, os.path.join(paths.ROOT, "records.py"), "show", "nothing.om3"], env=env,
                           capture_output=True, text=True, cwd=tmp)
        assert r.returncode == 2 and "nothing.om3" in r.stderr, r
        logs = [f for f in os.listdir(tmp) if f != "latest.log"]
        assert len(logs) == 1 and " records show.log" in logs[0], logs
        text = open(os.path.join(tmp, logs[0]), encoding="utf-8").read()
        assert text.startswith("records show nothing.om3") and "nothing.om3" in text.split("\n", 3)[3] and "ended" in text, text
        assert open(os.path.join(tmp, "latest.log"), encoding="utf-8").read() == text
        r = subprocess.run([sys.executable, os.path.join(paths.ROOT, "duo_battle.py"), "--tournament", "2", "--level", "easy",
                            "--opponent", "random"], env=env, capture_output=True, text=True, cwd=tmp)
        assert r.returncode == 0, r.stderr
        newest = open(os.path.join(tmp, "latest.log"), encoding="utf-8").read()
        assert newest.startswith("duo_battle --tournament 2") and "easy against random:" in newest, newest
    finally:
        shutil.rmtree(tmp)


@test("Record Mixing: back in the room, the player stands in the DUO's way to the door (lab session 31) - the DUO goes round, asks to leave from a door tile, and both games warp out")
def _():
    # the game is player 0 (master), seated at (6,6): down, right x3, down to (9,8), in the middle of
    # the DUO's way from (13,6) to the door (8-11,9)
    hw, game, report = mix_run(master=True, bases=[test_base()], in_the_way=[18, 21, 21, 21, 18])
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    r = game.result
    assert report["mixed"] and r["left_room"] and r["partner_left_by_door"] and 1 in game.room.asked_to_leave, r
    assert r["positions_at_exit"][0] == (9, 8) and r["positions_at_exit"][1][1] == 9, r["positions_at_exit"]


def _reversals(trail):
    """How many times a walker turned straight back on itself (a step undoing the one before)."""
    steps = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(trail, trail[1:])]
    return sum(1 for a, b in zip(steps, steps[1:]) if a[0] == -b[0] and a[1] == -b[1])


def _pacer(until):
    """The game's player (0) walks to (11,8), in the DUO's way to its seat (13,6), and steps up and
    down between (11,7) and (11,8) until frame `until`, then goes to its own seat (6,6)."""
    def key(frame, room, me):
        if frame >= until:
            return MG.step_towards(room, me, (6, 6))
        if room.pos[me] not in ((11, 7), (11, 8)):
            return MG.step_towards(room, me, (11, 8))
        return MG.KEY_UP if room.pos[me] == (11, 8) else MG.KEY_DOWN
    return key


def _shadow(until):
    """The game's player (0) keeps stepping into the DUO's way: onto the tile next to the DUO on
    its shortest way to (13,6), until frame `until`; then to its own seat (6,6)."""
    def key(frame, room, me):
        if frame >= until:
            return MG.step_towards(room, me, (6, 6))
        duo = 1 - me
        k = MG.step_towards(room, duo, (13, 6))
        if k is None:
            return None
        dx, dy = MG.DIRS[k]
        target = (room.pos[duo][0] + dx, room.pos[duo][1] + dy)
        return MG.step_towards(room, me, target)
    return key


@test("Record Mixing: the player steps up and down in the DUO's way to the table (7 November, hardware: it paced along the left wall) - the DUO waits a moment, then goes round the other way without turning back or crossing another seat, and sits")
def _():
    hw, game, report = mix_run(master=True, bases=[test_base()], to_seat=_pacer(1500))
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    r = game.result
    trail = r["partner_trail"]
    assert r["mixed"] and r["partner_seat"] == (13, 6), r
    assert not set(trail[:-1]) & set(MG.SEATS), f"walked onto another seat: {trail}"
    assert _reversals(trail) == 0, f"back and forth: {trail}"
    assert "blocked by your character" in hw.text, "the PC wasn't told the DUO was waiting"


@test("Record Mixing: the player sits in the DUO's seat - the DUO takes the seat behind it on its side")
def _():
    def key(frame, room, me):
        return MG.step_towards(room, me, (13, 6))
    hw, game, report = mix_run(master=True, bases=[test_base()], to_seat=key)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    r = game.result
    assert r["mixed"] and r["partner_seat"] == (13, 4), r


@test("Record Mixing: the player keeps stepping in front of the DUO for a while - the DUO never gives up, and sits once it can")
def _():
    hw, game, report = mix_run(master=True, bases=[test_base()], to_seat=_shadow(1800))
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    r = game.result
    assert r["mixed"] and r["partner_seat"] == (13, 6), (r, r.get("partner_trail"))


@test("trade into Emerald without the National Pokedex: the DUO's link player says it has one, so the player may offer a non-Hoenn Pokemon; the tool names the game; Jirachi (in the Hoenn Pokedex) is received")
def _():
    hw, game, report, event, path = trade_run(master=True, game_kind="emerald", national_dex=False,
                                              game_species=(25, 1), pick=1)       # offers Bulbasaur
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    assert report["traded"] and game.result["received"] == W.pk3_party_form(event) and game.result["left_room"], game.result
    assert "English Emerald, no National Pokedex" in hw.text and "***" not in hw.text, hw.text[-1200:]


@test("trade into FireRed: the player offers a non-Kanto Pokemon, which FireRed only allows to a partner with the National Dex - the DUO's progress flags say it has one")
def _():
    hw, game, report, event, path = trade_run(master=False, game_kind="firered", game_species=(25, 280), pick=1)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    assert report["traded"] and game.result["received"] == W.pk3_party_form(event), game.result
    assert "English FireRed, National Pokedex" in hw.text and "the DUO is player 0" in hw.text, hw.text[-800:]


@test("trade: Emerald refuses a Mew without the fateful-encounter mark - the tool warns at link-up, the game says no, and the DUO still leaves the room cleanly")
def _():
    mew = test_pk3(species=151, pid=0x0BADCAFE, otid=0x00004E44, fateful=False)
    assert W.trade_refusal(3, 0x11, W.parse_pk3(mew)[0]) and not W.trade_refusal(2, 0, W.parse_pk3(mew)[0])
    hw, game, report, event, path = trade_run(master=True, game_kind="emerald", event=mew)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    assert game.result["refused"] and not report["traded"] and game.result["left_room"], game.result
    assert "*** Emerald only takes a Mew marked as a fateful encounter" in hw.text, hw.text[-1200:]
    # and Emerald without the National Pokedex won't take a Pokemon from outside the Hoenn Pokedex
    bulbasaur = W.parse_pk3(test_pk3(species=1))[0]
    assert "until it has the National Pokedex" in W.trade_refusal(3, 0x10, bulbasaur)
    assert W.trade_refusal(3, 0x11, bulbasaur) is None and W.trade_refusal(4, 0x10, bulbasaur) is None


@test("trade: three Pokemon in one sitting - after each trade the DUO offers the next, the player gives a different Pokemon each time, every one is kept, and the DUO leaves the room after the last")
def _():
    events = [test_pk3(species=sp, pid=0x0BAD0000 + sp, otid=0x00004E44) for sp in (409, 410, 25)]
    hw, game, report, event, paths = trade_run(master=True, events=events, picks=[0, 1, 2], seconds=400)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1200:])
    res = game.result
    assert res["received_all"] == [W.pk3_party_form(e) for e in events], "the game didn't receive them in order"
    assert res["partner_picks"] == [0, 1, 2] and res["left_room"], res["partner_picks"]
    assert report["trades"] == 3 and report["bad_checksums"] == 0, report
    kept = sorted(os.listdir(W.RECEIVED_DIR))
    assert [open(os.path.join(W.RECEIVED_DIR, k), "rb").read() for k in kept] != [] and len(kept) == 3, kept
    assert sorted(open(os.path.join(W.RECEIVED_DIR, k), "rb").read() for k in kept) == sorted(res["gave_all"])
    for line in ("3 Pokemon, one trade each", "traded and saved (1 of 3)", "traded and saved (3 of 3)",
                 "the game has 3 of the 3 event Pokemon", "(for JIRACHI)", "(for DEOXYS)", "(for PIKACHU)"):
        assert line in hw.text or any(line in k for k in kept), (line, hw.text[-1500:], kept)
    assert "Offering 3 Pokemon" in hw.log, hw.log


@test("trade: two Pokemon in one sitting with the DUO as master - it asks for the parties again before the second trade")
def _():
    events = [test_pk3(species=sp, pid=0x0BAD0000 + sp, otid=0x00004E44) for sp in (409, 410)]
    hw, game, report, event, paths = trade_run(master=False, events=events, picks=[2, 0], seconds=400)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1200:])
    assert game.result["received_all"] == [W.pk3_party_form(e) for e in events] and report["trades"] == 2, report


@test("trade: back in the room, the player leaves first - the DUO follows at once and both games warp out")
def _():
    hw, game, report, event, path = trade_run(master=True, leaves_first=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    assert report["traded"] and game.result["left_room"], game.result
    assert 0 <= game.result["partner_left_after"] <= 5, game.result     # it followed at once


@test("trade: back in the room, the player stands on the DUO's nearest door tile (lab session 31) - the DUO goes round to the other door tile, asks to leave there, and both games warp out")
def _():
    # the game is player 0 (master), seated at (4,5): down, down, right, right, down to (6,8),
    # the door tile player 1 would use; the DUO (player 1, at (7,5)) must take (5,8)
    hw, game, report, event, path = trade_run(master=True, in_the_way=[18, 18, 21, 21, 18])
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    r = game.result
    assert report["traded"] and r["left_room"] and r["partner_left_by_door"], r
    assert r["positions_at_exit"] == {0: (6, 8), 1: (5, 8)}, r["positions_at_exit"]
    assert 1 in game.room.asked_to_leave, "the DUO left without the exit prompt on the door"


@test("trade: back in the room, the player stands right below the DUO's seat - the DUO walks round the other way and still leaves by the door")
def _():
    # game player 0 from (4,5): down, down, right x3, up to (7,6), just below the DUO's seat (7,5)
    hw, game, report, event, path = trade_run(master=True, in_the_way=[18, 18, 21, 21, 21, 19])
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    r = game.result
    assert report["traded"] and r["left_room"] and r["partner_left_by_door"] and 1 in game.room.asked_to_leave, r


@test("trade, the DUO as master: it asks for the blocks itself (spaced so the game has filled each), and the game still receives the event Pokemon and saves")
def _():
    hw, game, report, event, path = trade_run(master=False)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-800:])
    res = game.result
    assert res["received"] == W.pk3_party_form(event) and res["saved"] and res["partner_seat"] == (4, 5), res
    assert report["traded"] and report["bad_checksums"] == 0, report
    assert kept_files(path) == [res["gave"]], "the DUO's copy of the game's party was stale"
    assert "the DUO is player 0" in hw.text


@test("trade: the player says no - no trade, the DUO chooses CANCEL with the player and the link closes; nothing is kept")
def _():
    for master in (True, False):
        hw, game, report, event, path = trade_run(master=master, accept=False)
        assert hw.lg_error is None and hw.lg_done, (master, repr(hw.lg_error), game.log, hw.text[-800:])
        assert "declined" in game.log and game.result["received"] is None and not game.result["saved"]
        assert not report["traded"] and kept_files(path) == [] and "without a trade" in hw.text, hw.text[-400:]
        assert game.result["left_room"], game.log                        # and out of the room cleanly


@test("party form: level, HP and stats worked out as the games do (base stats, growth rate, IVs, EVs, nature; Shedinja's 1 HP); a party file's own stats are kept; a damaged Pokemon isn't sent")
def _():
    def fields(**kw):
        return struct.unpack("<IBBHHHHHHH", W.pk3_party_fields(W.parse_pk3(test_pk3(**kw))[0]))
    # Pikachu (internal 25: 35/55/30/90/50/40, medium fast), level 50 (125,000 exp), IVs 31, EVs 0
    def pikachu(pid):
        d = bytearray(test_pk3(species=25, pid=pid))
        f = W.parse_pk3(bytes(d))[0]
        f["exp"], f["ivs"], f["evs"] = 125000, [31] * 6, [0] * 6
        return struct.unpack("<IBBHHHHHHH", W.pk3_party_fields(f))
    assert pikachu(25 * 4)[1:] == (50, 0xFF, 110, 110, 75, 50, 110, 70, 60), pikachu(100)   # Hardy: neutral
    assert pikachu(25 * 4 + 1)[5:7] == (82, 45), pikachu(101)                              # Lonely: +Atk, -Def
    assert W.pk3_exp_for_level(0, 1) == 1 and W.pk3_exp_for_level(3, 2) == 9 and W.pk3_exp_for_level(5, 100) == 1250000
    sh = W.parse_pk3(test_pk3(species=303))[0]; sh["exp"] = 1000
    assert struct.unpack("<IBBHHHHHHH", W.pk3_party_fields(sh))[3:5] == (1, 1)            # Shedinja
    assert fields(species=409)[1] >= 1
    # a 100-byte file with its own party fields keeps them
    own = bytearray(test_pk3(party=True)); own[84:100] = bytes(range(1, 17))
    assert W.pk3_party_form(bytes(own))[80:] == bytes(own[80:])
    # the game's form: decrypts back to the same Pokemon, with the worked-out party fields after it
    form = W.pk3_party_form(test_pk3())
    assert W.parse_pk3(form[:80])[0]["species"] == 409
    assert form[80:] == W.pk3_party_fields(W.parse_pk3(test_pk3())[0]) and form[84] >= 1 and form[88] > 0
    # a damaged Pokemon: refused before anything is sent
    bad = bytearray(test_pk3()); bad[0x30] ^= 2
    try:
        quiet(W.trade_session, None, types.SimpleNamespace(pk3=event_file(bytes(bad), "x.pk3"), seconds=1))
        raise AssertionError("a damaged Pokemon was sent")
    except ValueError:
        pass


@test("e-Reader: Ruby as master (purple plug) - handshake, link players, the event arrives intact, the link closes")
def _():
    game = LG.RubyMysteryEvent(master=True)
    hw, report = ereader_run(game, TEST_ME3)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-600:])
    assert hw.lg_result == sent_as(TEST_EVENT), (len(hw.lg_result or b""), hw.text[-400:])
    status, saved, store = ME.run(hw.lg_result, "English", "Ruby")    # what Ruby then does with it
    assert (status, saved) == (ME.LOAD_OK, True) and store["ram_script"] == TEST_ME3[:1004] \
        and store["gift"][:8] == TEST_ME3[1004:], (status, store["trace"])
    duo_lp = game.link_players[1]
    assert duo_lp["link_type"] == 0x5501 and duo_lp["language"] == LG.LANG_ENGLISH, duo_lp
    assert report["bad_checksums"] == 0 and report["game_language"] == 2, report
    assert "Playing: Card e-Reader+" in hw.log, hw.log                     # the DUO's screen (between sessions only)
    assert report["max_gap_lines"] < 20, report                            # (the line after the close isn't counted)
    for line in ("Mystery Event loaded", "link up (the DUO is player 1)", "got the game's link player: link type 0x5501, English",
                 "sent the Mystery Event", "the game closed the link"):
        assert line in hw.text, (line, hw.text)


@test("e-Reader: Ruby as master while SI flickers (lab session 27) - the DUO still knows it's player 1, says so, and the event arrives")
def _():
    game = LG.RubyMysteryEvent(master=True)
    hw, report = ereader_run(game, TEST_ME3, si_flicker=3)
    assert hw.mp_si_reads > 100, hw.mp_si_reads
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-600:])
    assert hw.lg_result == sent_as(TEST_EVENT) and report["bad_checksums"] == 0, report
    assert "the DUO is player 1" in hw.text and "swap the cable" not in hw.text, hw.text


@test("e-Reader: the DUO as master (pacing check against a game's link layer, with transfers finishing at the worst moment) - it starts the transfers and the handshake; a Japanese game gets a Japanese partner")
def _():
    game = LG.RubyMysteryEvent(master=False, language=LG.LANG_JAPANESE, menu_rules=False)
    small = test_me3(script_len=250)
    # with adversarial timing: transfers finish just as the DUO looks at the busy bit (the start race)
    # (the correct program doesn't look at SIOCNT while a transfer is in flight, so it meets few
    # of these; the planted start race does, every cycle)
    hw, report = ereader_run(game, small, race_window=12)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-600:])
    assert hw.lg_result == sent_as(W.prepare_event(small, "x (ENG).me3")[0])
    assert game.link_players[0]["language"] == LG.LANG_JAPANESE and "the DUO is player 0" in hw.text, hw.text
    # paced like Ruby's own master: a transfer and the one nine later are a whole frame apart
    # (one handshake transfer, or one 9-transfer command cycle, per frame; a few lines of jitter
    # within a cycle are fine - back to back is ~4,000 blocks), and the game was
    # always ready for each transfer (lab session 24)
    st, frame = hw.mp_start_blocks, hw.mp_frame_blocks
    assert len(st) > 100 and all(st[i + 9] - st[i] >= frame - 300 for i in range(len(st) - 9)), \
        min(st[i + 9] - st[i] for i in range(len(st) - 9))
    assert hw.mp_missed == 0, hw.mp_missed


@test("e-Reader: with the DUO on the master end, Ruby's menu gives up - the tool says to swap the cable's ends")
def _():
    game = LG.RubyMysteryEvent(master=False)                 # Ruby's real menu rules
    hw, duo = run42()
    hw.attach_mp_game(game.run(), game_master=False)
    r = quiet(W.ereader_session, duo, types.SimpleNamespace(ereader=30, mystery_event=None), poll_s=0.2,
              stop_when=lambda: hw.lg_done)
    hw.stop(); clean(hw)
    assert isinstance(hw.lg_error, LG.LinkError) and "isn't the link master" in str(hw.lg_error), repr(hw.lg_error)
    assert "swap the cable's ends" in r[1], r[1]


@test("e-Reader: two events in one session - after the game closes the link and opens it again, the DUO starts over")
def _():
    g1, g2 = LG.RubyMysteryEvent(master=True), LG.RubyMysteryEvent(master=True)

    def twice():
        a = yield from g1.run()
        yield ("delay", 25 * 228 * 20)                      # the game shows its message, the player goes back in
        b = yield from g2.run()
        return a, b
    hw, duo = run42()
    hw.attach_mp_game(twice())
    r = quiet(W.ereader_session, duo, types.SimpleNamespace(ereader=90, mystery_event=event_file(TEST_ME3), keep_going=True),
              poll_s=0.2, stop_when=lambda: hw.lg_done)
    hw.stop(); clean(hw)
    assert hw.lg_error is None and hw.lg_result == (sent_as(TEST_EVENT), sent_as(TEST_EVENT)), (repr(hw.lg_error), r[1][-600:])
    assert "opened the link again" in r[1] and "Mystery Events sent: 2" in r[1], r[1]
    assert r[0]["bad_checksums"] == 0, r[1]


@test("e-Reader: the tool stops by itself only once the game has closed the link and gone quiet")
def _():
    game = LG.RubyMysteryEvent(master=True)
    hw, report = ereader_run(game, TEST_ME3, stop_on_game=False)
    assert hw.lg_error is None and hw.lg_done and hw.lg_result == sent_as(TEST_EVENT), (repr(hw.lg_error), hw.text[-500:])
    assert "Finished: the game has received the event" in hw.text and "your Dad (Norman) in Petalburg City Gym" in hw.text, hw.text


@test("e-Reader: with no event loaded only link players are exchanged (a dry run); oversize files are refused")
def _():
    game = LG.RubyMysteryEvent(master=True)
    game_gen = game.run(max_transfers=6000)
    hw, duo = run42()
    hw.attach_mp_game(game_gen)
    r = quiet(W.ereader_session, duo, types.SimpleNamespace(ereader=60, mystery_event=None), poll_s=0.2,
              stop_when=lambda: hw.lg_done)
    hw.stop(); clean(hw)
    assert isinstance(hw.lg_error, LG.LinkError) and "no Mystery Event" in str(hw.lg_error), repr(hw.lg_error)
    assert len(game.link_players) == 2 and "sent our link player" in r[1], r[1]
    big = event_file(bytes([1]) + bytes(2004), "big.bin")             # a script over the game's buffer
    try:
        W.load_event(None, big); raise AssertionError("2005 bytes accepted")
    except ValueError as e:
        assert "2004" in str(e)


@test("search check: four entries per answer, all with good checksums, so librfu restarts its search (0x1E, 0x1C)")
def _():
    def script(game):
        yield ("until_ready",)
        assert (yield from game.check_id()) == 0x8001
        for cmd, data in ((0x10, []), (0x17, [0x003C0420]), (0x16, [2, 0, 0, 0, 0, 0xFFFFFFFF]), (0x1C, [])):
            yield from game.command(cmd, data)
        for _ in range(30):
            hosts = RFU.parse_candidates((yield from game.command(0x1D)))
            if len(hosts) == 4:                     # librfu: findParentCount == RFU_CHILD_MAX
                yield from game.command(0x1E)       # rfu_REQ_endSearchParent, then start again
                yield from game.command(0x1C)
                return hosts
            yield ("delay", 16 * RFU.MS)
        raise RFU.LinkError(f"never four entries (last answer had {len(hosts)})")
    hw, game, trace, st, counters = adapter_session(script, first_bit=True, check_search=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors)
    hosts = hw.lg_result
    assert [h["id"] for h in hosts] == [0x7DA5, 0x7DA6, 0x7DA7, 0x7DA8] and all(h["checksum_ok"] for h in hosts), hosts
    names = [t for t, _ in trace]
    assert "stop searching (0x1E)" in names and names.count("start searching (0x1C)") == 2, names
    assert "Search check" in hw.text, hw.text


@test("distributor: after connecting, the game's name arrives over librfu's NI channel, every chunk acknowledged")
def _():
    name = RFU.child_name_bytes()
    def script(game):
        found = yield from RFU.find_distributor(game)
        conn = yield from RFU.connect_to(game, found["id"])
        sender = yield from RFU.send_child_name(game, name)
        return conn, sender
    hw, game, trace, st, counters = adapter_session(script, first_bit=True, seconds=40)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors, [t for t, _ in trace][-8:])
    conn, sender = hw.lg_result
    assert sender.state == RFU.SEND_SUCCESS and sender.frames_sent <= 12, (hex(sender.state), sender.frames_sent)
    child = W.adapter_trace.last_child
    assert child["received"] and child["raw"] == name, (child, name.hex())
    names = [t for t, _ in trace]
    assert any(n.startswith("the distributor received the game's name") for n in names), names[-6:]
    assert game.retries == 0, game.retries


@test("distributor: then the host tells the game it may join (RFU_STATUS_JOIN_GROUP_OK over NI) and the game receives it")
def _():
    def script(game):
        found = yield from RFU.find_distributor(game)
        conn = yield from RFU.connect_to(game, found["id"])
        yield from RFU.send_child_name(game, RFU.child_name_bytes())
        r = yield from RFU.wait_join_status(game)
        return r
    hw, game, trace, st, counters = adapter_session(script, first_bit=True, seconds=40)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors, [t for t, _ in trace][-8:])
    r = hw.lg_result
    assert r.state == RFU.RECV_SUCCESS and bytes(r.buf) == b"\x05" and r.type == 0 and r.payload == 5, (hex(r.state), r.buf)
    names = [t for t, _ in trace]
    assert any(n.startswith("the distributor told the game it may join") for n in names), names[-6:]
    assert game.retries == 0, game.retries


def test_wc3(language="Japanese"):
    """A made-up Wonder Card in .wc3 layout (test data only - not any real event)."""
    size = 0xA4 if language == "Japanese" else 0x14C
    card = bytearray(size)
    card[0:2] = (0x0123).to_bytes(2, "little")             # flagId
    card[2:4] = (0x0019).to_bytes(2, "little")             # iconSpecies
    card[4:8] = (0x00C0FFEE).to_bytes(4, "little")         # idNumber
    card[8] = 0 | 1 << 2 | 1 << 6                          # type 0, bgType 1, sendType 1
    for i in range(10, size):
        card[i] = (i * 7) & 0xFF
    script = bytes([0x33, 0x05, 0x0A, 0x01]) + bytes((i * 13 + 5) & 0xFF for i in range(996))
    wc3 = (W.game_crc16(card).to_bytes(4, "little") + bytes(card) + bytes(0x50)
           + W.game_crc16(script).to_bytes(4, "little") + script)           # valid, as the game checks
    path = os.path.join(tempfile.gettempdir(), f"test_card_{language[:2]}.wc3")
    open(path, "wb").write(wc3)
    return path, bytes(card), script


def gift_script(game, compat=RFU.JP_EMERALD):
    found = yield from RFU.find_distributor(game, compat=compat)
    conn = yield from RFU.connect_to(game, found["id"])
    yield from RFU.send_child_name(game, RFU.child_name_bytes())
    yield from RFU.wait_join_status(game)
    child = RFU.ChildLink()
    client = yield from RFU.receive_gift(game, child)
    return child, client


@test("distributor: link players exchanged, then Mystery Gift delivers the Wonder Card and RAM script; the link closes")
def _():
    path, card, script = test_wc3()
    hw, game, trace, st, counters = adapter_session(gift_script, first_bit=True, seconds=120, wonder_card=path)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors, [t for t, _ in trace][-10:])
    child, client = hw.lg_result
    assert child.player_count == 2 and child.multiplayer_id == 1, (child.player_count, child.multiplayer_id)
    assert child.link_players[0][8:11] == bytes([0xBE, 0xCF, 0xC9]), child.link_players[0]
    assert client.result == RFU.CLI_MSG_CARD_RECEIVED, (client.result, client.history)
    assert client.saved_card == card and client.saved_ram_script == script
    link = W.adapter_trace.last_link
    assert link["player_ok"] and link["trainer_id"] == 0x0003D4C1 and link["mg_step"] == 6 and not link["mg_errors"], link
    assert link["game_data"] == bytes(range(0x40)), link["game_data"].hex()
    names = [t for t, _ in trace]
    assert any(n.startswith("link players exchanged") for n in names), names
    assert any(n.startswith("the game is ready to close the link") for n in names), names
    assert "Wonder Card loaded" in hw.text and game.retries == 0, (hw.text[:400], game.retries)
    # the DUO's screen: only where the wireless link can't be waiting (the simulator stalls the GBA
    # for over a frame on every line, so a line mid-link would cost retries or the gift)
    assert "Playing: Wireless Adapter" in hw.log and "Card sent: the game saves" in hw.log, hw.log
    assert hw.log.index("Card sent: the game saves") > hw.log.index("Playing: Wireless Adapter")
    talking = [s for s in hw.log_stalls if hw.lg_first_at <= s < hw.lg_done_at]
    assert not talking, (talking, hw.lg_first_at, hw.lg_done_at, hw.log)   # never while the game was on the link


@test("distributor: packets lost on the way (every 7th) are sent again until the game shows it got them; the card still arrives intact")
def _():
    path, card, script = test_wc3()
    def script_(game):
        found = yield from RFU.find_distributor(game)
        yield from RFU.connect_to(game, found["id"])
        yield from RFU.send_child_name(game, RFU.child_name_bytes())
        yield from RFU.wait_join_status(game)
        child = RFU.ChildLink()
        client = yield from RFU.receive_gift(game, child, drop_every=7)
        return child, client
    hw, game, trace, st, counters = adapter_session(script_, first_bit=True, seconds=150, wonder_card=path)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors, [t for t, _ in trace][-10:])
    child, client = hw.lg_result
    assert child.dropped > 20 and client.result == RFU.CLI_MSG_CARD_RECEIVED, (child.dropped, client.result)
    assert client.saved_card == card and client.saved_ram_script == script
    assert W.adapter_trace.last_link["resent"] >= child.dropped - 1, (W.adapter_trace.last_link, child.dropped)


@test("finishing: the tool stops by itself once the game has the card and has closed the link; --keep-going carries on")
def _():
    path, card, script = test_wc3()
    hw, game, trace, st, counters = adapter_session(gift_script, first_bit=True, seconds=120, wonder_card=path,
                                                    stop_on_game=False)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors)
    child, client = hw.lg_result
    assert client.result == RFU.CLI_MSG_CARD_RECEIVED and client.saved_card == card
    assert "Finished: the game has received the Wonder Card and closed the link." in hw.text, hw.text[-600:]
    # --keep-going: the game is done within a few seconds, and the tool must still be running at the
    # end of its 45 (a tool that stopped would stop soon after the game; 45 s leaves room for a
    # loaded machine, where 12 s once let a planted bug through)
    t0 = time.time()
    hw, game, trace, st, counters = adapter_session(gift_script, first_bit=True, seconds=45, wonder_card=path,
                                                    stop_on_game=False, keep_going=True)
    assert hw.lg_done and "Finished" not in hw.text and time.time() - t0 >= 45, hw.text[-300:]


@test("guided start-up: both GBAs off, the DUO's on, progress bars, then 'Ready' with each game's menu; a card named for another game is flagged")
def _():
    path, card, script = test_wc3()
    named = os.path.join(tempfile.mkdtemp(), "FL - Item Test (JPN).wc3")      # FireRed/LeafGreen, says its name
    shutil.copy(path, named)
    hw, duo = run42()
    game = RFU.Game()
    hw.attach_link_game(gift_script(game), first_bit=True)
    args = types.SimpleNamespace(command="gift", wait=5, seconds=120, card=named, serial=None, keep_going=False,
                                 sweep_serial=False, check_search=False, lab=False)
    _, text = quiet(W.run, duo, args)
    hw.stop(); clean(hw)
    assert hw.lg_done and hw.lg_error is None, repr(hw.lg_error)
    order = ["Before you start: both GBAs should be switched off.", "MGB-010",
             "leave the game's GBA off", "already on", "Setting up the DUO's GBA", "100%",
             "Loading the Wonder Card", "Ready. Now switch on the game's GBA",
             "ふしぎな おくりもの (fushigi na okurimono)", "ふしぎな もらいもの", "LINK TOGETHER WITH ALL",
             "the file's name says it's for FireRed/LeafGreen, but the game is Japanese Emerald", "Finished"]
    at = 0
    for item in order:
        k = text.find(item, at)
        assert k >= 0, (item, text[at:at + 400])
        at = k
    assert W.file_games("E - Item Old Sea Map (JPN).wc3") == ("Emerald",) and W.file_games("my card.wc3") is None
    assert W.file_games("FL - Item AuroraTicket (ENG) (UK).wc3") == ("FireRed", "LeafGreen")


@test("distributor: without a Wonder Card the game is told there is nothing to send, and the link closes tidily")
def _():
    hw, game, trace, st, counters = adapter_session(gift_script, first_bit=True, seconds=120)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors, [t for t, _ in trace][-10:])
    child, client = hw.lg_result
    assert client.result == RFU.CLI_MSG_NOTHING_SENT and client.saved_card is None, (client.result, client.history)
    assert W.adapter_trace.last_link["mg_step"] == 4, W.adapter_trace.last_link


@test("wireless adapter: the game gives up half-way through a command and starts it again; the adapter follows")
def _():
    def script(game):
        yield ("until_ready",)
        assert (yield from game.check_id()) == 0x8001
        yield from game.command(0x10)
        # 0x16 with six data words, abandoned after two, once the adapter is ready for the third;
        # librfu then starts the whole command again 130 ms later (STWI_restart_Command)
        got = yield ("xfer", 0x99660616)
        for w in (1, 2):
            yield ("wait_si", 1, 80 * RFU.MS); yield ("so", 1); yield ("wait_si", 0, 80 * RFU.MS); yield ("so", 0)
            got = yield ("xfer", w)
        yield ("wait_si", 1, 80 * RFU.MS); yield ("so", 1); yield ("wait_si", 0, 80 * RFU.MS); yield ("so", 0)
        yield ("delay", 130 * RFU.MS)
        again = yield from game.command(0x16, [1, 2, 3, 4, 5, 6])
        return again, (yield from game.command(0x13))
    hw, game, trace, st, counters = adapter_session(script)
    assert hw.lg_error is None, repr(hw.lg_error)
    assert hw.lg_result == ([0x99660096], [0x99660193, 0]), hw.lg_result
    names = [t for t, _ in trace]
    assert any(n.startswith("the game stopped answering") for n in names[2:4]), names
    assert names[-2].startswith("broadcast data (0x16) 00000001") and names[-1].startswith("status (0x13)"), names
    assert counters >> 16 == 1 and game.retries == 0, (counters, game.retries)


@test("wireless adapter: with the first-bit behaviour measured on real hardware, Emerald's search completes cleanly")
def _():
    def script(game):
        acks = yield from RFU.mystery_gift_search(game, polls=6)
        yield ("delay", 40 * RFU.MS)
        acks["sleep"] = yield from RFU.go_to_sleep(game)
        return acks
    hw, game, trace, st, counters = adapter_session(script, first_bit=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors, [t for t, _ in trace][-6:])
    acks = hw.lg_result
    assert acks[0x10] == [0x99660090] and acks[0x1D][:2] == [0x9966079D, 0x7DA5] and acks["wait"] == 0x99660027
    assert acks[0x13] == [0x99660193, 0] and acks["sleep"] == [0x996600BD]
    assert game.retries == 0 and not game.errors, (game.retries, game.errors)
    assert counters >> 16 == 0 and "Over-long answers" not in hw.text


@test("wireless adapter: the 'ready' flick tunes its own width into the window the game needs (too narrow: unseen, too wide: first bit wrong)")
def _():
    def script(game):
        acks = yield from RFU.mystery_gift_search(game, polls=4)
        acks["sleep"] = yield from RFU.go_to_sleep(game)
        return acks
    for window in ((6, 9), (11, 12), (0, 0)):       # climb, climb to a narrow window, back off
        hw, game, trace, st, counters = adapter_session(script, first_bit=True, flick_window=window, seconds=60,
                                                        program="adapter_lab")
        assert hw.lg_error is None and hw.lg_done, (window, repr(hw.lg_error), game.errors)
        tuning = W.adapter_trace.last_tuning
        lo, hi = window
        assert lo <= tuning["width"] <= hi, (window, tuning["width"], tuning["rows"])
        assert any(r[2] for r in tuning["rows"]) and tuning["scope"], tuning


@test("wireless adapter: with a one-bit lag the simulator reproduces lab session 11 - each command fails three times")
def _():
    def script(game):
        yield ("until_ready",)
        assert (yield from game.check_id()) == 0x8001
        try:
            yield from game.command(0x3D)
            return "accepted"
        except RFU.LinkError:
            return "failed"
    hw, game, trace, st, counters = adapter_session(script, lag_bits=1)
    names = [t for t, _ in trace]
    assert hw.lg_result == "failed" and game.retries == 2, (hw.lg_result, game.retries)
    assert names[0].startswith("ID exchange") and names.count("the game stopped answering in the middle of a command (0x3d: no handshake after its command word)") == 3, names


@test("2 MHz probe: on perfect wires the lagged answer is refused and the unshifted ones are accepted")
def _():
    def script(game):
        yield ("until_ready",)
        assert (yield from game.check_id()) == 0x8001
        for cmd in (0x10, 0x13):
            try:
                yield from game.command(cmd)
            except RFU.LinkError:
                pass
        return "done"
    hw, game, trace, st, counters = adapter_session(script, program="adapter_probe")
    (lag, first, plain) = hw.probe
    assert lag[1] >= 1 and lag[2] == 0 and first[2] >= 1, hw.probe     # the same word, just SO high


@test("2 MHz probe: with a one-bit lag (as lab session 11 suggests) only the lagged answer is accepted")
def _():
    def script(game):
        yield ("until_ready",)
        assert (yield from game.check_id()) == 0x8001
        try:
            yield from game.command(0x10)
        except RFU.LinkError:
            pass
        return "done"
    hw, game, trace, st, counters = adapter_session(script, program="adapter_probe", lag_bits=1)
    (lag, first, plain) = hw.probe
    assert lag[1] >= 1 and lag[2] >= 1 and first[2] == 0 and plain[2] == 0, hw.probe
    assert "consistent one-bit lag" in hw.text, hw.text[-600:]


@test("wireless adapter: an echo of our own acknowledgement after sleep (session 16) is ignored, not answered")
def _():
    def script(game):
        yield ("until_ready",)
        yield from RFU.go_to_sleep(game)
        yield ("delay", 30 * RFU.MS)
        yield ("xfer", 0x996600BD, 2)                # the game clocks once with its stale data
        yield ("delay", 30 * RFU.MS)
        return (yield from RFU.mystery_gift_search(game, polls=4))
    hw, game, trace, st, counters = adapter_session(script, first_bit=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.errors)
    names = [t for t, _ in trace]
    assert "unknown command (0xBD)" not in names, names           # the echo isn't treated as a command
    assert "unknown command (0x99)" in names, names               # a real unknown command still is
    assert "start searching (0x1C)" in names and counters >> 16 == 0, names


@test("card checks: a synthetic .wc3 with good CRC-16s passes; damage to the card or script, or a missing marker, is reported")
def _():
    for size, total in ((0xA4, 1252), (0x14C, 1420)):
        card = bytearray(size); card[0:2] = (1002).to_bytes(2, "little")
        script = bytearray(1000); script[0:4] = b"\x33\xff\xff\xff"; script[4:8] = b"\x02\x00\x00\x00"
        def build(card, script):
            return (W.game_crc16(card).to_bytes(4, "little") + bytes(card) + bytes(0x50)
                    + W.game_crc16(script).to_bytes(4, "little") + bytes(script))
        good = build(card, script)
        assert len(good) == total and W.check_wc3(good) == [], W.check_wc3(good)
        bad_card = bytearray(good); bad_card[10] ^= 1
        assert "card's checksum" in " ".join(W.check_wc3(bytes(bad_card)))
        bad_script = bytearray(good); bad_script[-1] ^= 1
        assert "RAM script's checksum" in " ".join(W.check_wc3(bytes(bad_script)))
        no_magic = bytearray(script); no_magic[0] = 0
        assert "marker" in " ".join(W.check_wc3(build(card, no_magic)))
    assert W.game_crc16(b"") == (~0x1121 & 0xFFFF)                 # the game's starting value


@test("wireless adapter: with nothing on the cable the trace stays empty and the program stops cleanly")
def _():
    hw, game, trace, st, counters = adapter_session(None, seconds=2, attach=False)
    assert trace == [] and st >> 16 == 0


@test("v4.2: everything else still works - fast save, cartridge report, restart; older firmware refuses programs")
def _():
    hw, duo = run42()
    path, data, info, text, _ = gba_save(duo)
    duo.restart(wait_s=20)
    hw.stop(); clean(hw)
    assert data == RUBY and hw.restarts == 1
    hw, duo = device()                                 # v4.1
    try:
        W.run_program(duo, "adapter_detect"); raise AssertionError("v4.1 ran a program")
    except M.DuoError as e:
        assert "v4.2" in str(e)
    hw.stop(); clean(hw)


@test("v4.2 update: installing v4.2 over the official firmware and over v4.1, flash simulated")
def _():
    saved, sys.argv = sys.argv, sys.argv[:1]
    try:
        import emu_update_test as U
    finally:
        sys.argv = saved
    for current in (OFFICIAL, FW):
        U.OFFICIAL = current
        ok, text = quiet(U.main, paths.build_file("duo_1.06_reckless_v4.2.bin"))
        assert ok, text
    crc, payload = M.check_update_file(paths.build_file("duo_1.06_reckless_v4.2.bin"))
    assert payload == FW42 and "v4.2" in M.KNOWN_FIRMWARE.get(crc, "")

# ===================================================================== record files (records.py)
def save_with_sb(edits, seed=3):
    """A synthetic save with bytes written into the newest copy's SaveBlock 1 (offset >= 0) or
    SaveBlock 2 (('sb2', offset)), checksums kept right."""
    d = bytearray(fixtures.make_gen3_save(seed=seed))
    newest = max(struct.unpack_from("<I", d, slot * 0xE000 + 0xFF8 + 4)[0] for slot in range(2))
    for where, data in edits:
        sec, off = (0, where[1]) if isinstance(where, tuple) else (1 + where // 3968, where % 3968)
        assert off + len(data) <= 3968, "keep an edit inside one section"
        for slot in range(2):
            for k in range(14):
                o = slot * 0xE000 + k * 0x1000
                s_, _, _, idx = struct.unpack_from("<HHII", d, o + 0xFF4)
                if s_ != sec or idx != newest:
                    continue
                body = bytearray(d[o:o + 0xFF4]); body[off:off + len(data)] = data
                n = {0: 3884, 13: 2000}.get(sec, 3968)
                c = sum(struct.unpack_from(f"<{n // 4}I", body, 0)) & 0xFFFFFFFF
                d[o:o + 0xFF4] = body
                struct.pack_into("<H", d, o + 0xFF6, ((c >> 16) + c) & 0xFFFF)
    return bytes(d)


@test("Record files (records.py): a Ruby save's own record as the game would send it (bases, TV shows with its own interviews taken off, news, old man, trends, day-care letters, Battle Tower trainer); split into part files and joined back byte for byte; the checks")
def _():
    import records as R
    bard = bytearray(64); struct.pack_into("<6H", bard, 2, 1, 2, 3, 4, 5, 6); bard[0x1A:0x22] = SB.encode_name("WILLOW", 2).ljust(8, b"\xff")
    trend = struct.pack("<HHHH", 30 | 80 << 7, 7, 0x0201, 0x0402)
    tv = bytearray(36 * 3)
    tv[0], tv[1] = 1, 1                                       # a local interview, on the air: sent off the air
    tv[36], tv[37] = 21, 1                                    # a "records" show: sent as it is
    struct.pack_into("<HHII", tv, 72 + 2, 0, 0, 0, 0)
    tower = bytearray(164); tower[0], tower[1] = 0, 5; struct.pack_into("<H", tower, 2, 21); tower[4:12] = SB.encode_name("ODA", 2).ljust(8, b"\xff")
    struct.pack_into("<HH4H", tower, 0x1C, SB._lookup("SWAMPERT", SB.tables().species, "x"), 0, 89, 0, 0, 0); tower[0x1C + 12] = 50
    tower = R.with_tower_checksum(tower)
    save = save_with_sb([(R.SB1_AT["old_man"], bytes(bard)), (R.SB1_AT["trends"], trend + bytes(32)),
                         (R.SB1_AT["tv"], bytes(tv)), (("sb2", R.SB2_TOWER_AT), tower)])
    rec = R.record_from_save(save)
    parts = R.split(rec)
    assert len(rec) == R.RS_SIZE and R.join(parts) == rec
    assert parts["old_man"][0] == bytes(bard), parts["old_man"][0].hex()
    assert parts["trends"][0] == trend, parts["trends"][0].hex()
    assert parts["tower"][0] == tower, (parts["tower"][0].hex(), tower.hex())
    assert parts["tv"][0][:2] == bytes([1, 0]) and parts["tv"][1][:2] == bytes([21, 1]), "sub_80C045C: own interviews go off the air"
    assert "WILLOW" in R.describe("old_man", parts["old_man"][0]) and "trendiness 30 of 80" in R.describe("trends", trend)
    assert "ODA" in R.describe("tower", tower) and "SWAMPERT" in R.describe("tower", tower).upper()
    assert R.check_part("tower", tower) == ([], [])
    bad = bytearray(tower); bad[2] ^= 1
    assert "checksum" in R.check_part("tower", bytes(bad))[0][0]
    assert "kind 9" in R.check_part("tv", bytes([9, 1]) + bytes(34))[0][0]
    assert R.check_part("old_man", bytes([7]) + bytes(63))[0]
    # the command line: split a save into files, join them back, show them
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "AXVE POKEMON RUBY", "test.sav"); os.makedirs(os.path.dirname(path)); open(path, "wb").write(save)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert R.main(["split", path, "--out", os.path.join(tmp, "parts")]) == 0
        files = out.getvalue().split("\n")[:-1]
        assert files[0].endswith("test.rm3") and open(files[0], "rb").read() == rec
        exts = sorted({os.path.splitext(f)[1] for f in files})
        assert {".om3", ".dt3", ".bt3", ".tv3"} <= set(exts), exts
        with contextlib.redirect_stdout(io.StringIO()):
            assert R.main(["join", *[f for f in files[1:]], "--out", os.path.join(tmp, "back.rm3")]) == 0
            assert R.main(["show", os.path.join(tmp, "back.rm3")]) == 0
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert R.main(["predict", path, os.path.join(tmp, "back.rm3"), "--partner-id", "4321"]) == 0
        assert "What the game keeps" in out.getvalue() and "Battle Tower:" in out.getvalue(), out.getvalue()
        back = R.split(open(os.path.join(tmp, "back.rm3"), "rb").read())
        for name in ("old_man", "trends", "tower", "news"):
            assert back[name][0] == parts[name][0], name
    finally:
        shutil.rmtree(tmp)


def record_scenario(seed):
    """A Ruby save and a partner's record with something in every part that the merge decides on:
    shows that travel and shows that don't, news, trends that tie and beat, an old man, letters,
    Battle Tower trainers. Random but repeatable."""
    import records as R
    r = random.Random(seed)
    game_tid, our_tid = 0x1234 + seed, 0x9876 - seed
    def show(kind, made_by, active, species=0):
        b = bytearray(r.getrandbits(8) for _ in range(36))
        b[0], b[1] = kind, active
        b[0x22], b[0x23] = made_by & 0xFF, made_by >> 8
        for at in R.SPECIES_FIELDS.get(kind, ()):
            struct.pack_into("<H", b, at, species or r.choice([1, 25, 280, 300, 400]))
        return bytes(b)
    kinds = list(R.TV_KINDS) + [9]
    def shows(owner, other):
        out = [show(r.choice(kinds), r.choice([owner, other, 0x4444]), r.randrange(2)) for _ in range(r.randrange(3, 24))]
        return out + [bytes(36)] * (25 - len(out))
    def news():
        out = b""
        for kind in r.sample([1, 2, 3, 4], r.randrange(4)):
            out += struct.pack("<BBH", kind, r.randrange(3), r.randrange(1, 5))
        return out.ljust(64, b"\0")
    def trends(pool):
        return [struct.pack("<HHHH", (lambda t, m: t | m << 7 | r.randrange(2) << 14)(*sorted([r.randrange(30, 128), r.randrange(30, 128)])),
                            r.getrandbits(16), *r.choice(pool)) for _ in range(5)]
    phrases = [(r.getrandbits(12), r.getrandbits(12)) for _ in range(6)]
    def mail():
        m = bytearray(r.getrandbits(8) for _ in range(112)) + bytes(8)
        for j in range(2):
            if r.random() < 0.3:
                struct.pack_into("<H", m, 56 * j + 0x20, 0)
        struct.pack_into("<I", m, 112, r.randrange(3))
        m[116], m[118] = r.randrange(2), r.randrange(2)
        return bytes(m)
    def tower(streak):
        t = bytearray(r.getrandbits(8) for _ in range(164))
        struct.pack_into("<H", t, 2, streak)
        return R.with_tower_checksum(t)
    old = bytearray(r.getrandbits(8) for _ in range(64)); old[0] = r.randrange(5)
    game_old = bytearray(64)
    tower_records = [tower(r.choice([0, 7, 7, 14, 21])) for _ in range(5)]
    seen_species = {s_ for s_ in range(1, 412) if r.random() < 0.7}
    game_rec = R.join({"tv": [bytes(x) for x in shows(game_tid, our_tid)], "news": [news()], "old_man": [bytes(game_old)],
                       "trends": trends(phrases), "mail": [mail()], "tower": [tower(9)]})
    ours = R.join({"tv": [bytes(x) for x in shows(our_tid, game_tid)], "news": [news()], "old_man": [bytes(old)],
                   "trends": trends(phrases), "mail": [mail()], "tower": [tower(r.choice([0, 7, 30]))]})
    return dict(game_rec=game_rec, ours=ours, game_tid=game_tid, our_tid=our_tid, tower=tower_records,
                seen=lambda sp: sp in seen_species, game_clear=r.random() < 0.5)


@test("Record files: what Ruby keeps from a partner's whole record - TV shows, news, old man, trends, day-care letters, Battle Tower - the tool's prediction (records.py) agrees with the game model's own port, in 60 random cases each way round, and in hand-made ones")
def _():
    import records as R
    for seed in range(60):
        sc = record_scenario(seed)
        for game_first in (True, False):
            game = MG.RubyRecordCorner(master=game_first, tail=sc["game_rec"][MG.TV_AT:], player=(0, sc["game_tid"].to_bytes(4, "little"), b"\xff" * 7),
                                       tower_records=sc["tower"], seen=sc["seen"], game_clear=sc["game_clear"])
            game.link_players = {game.other: dict(trainer_id=sc["our_tid"])}
            game.sent = game.own_record()
            game.merge_rest(sc["ours"])
            model = game.result["after"]
            state = dict(record=game.sent, tid=sc["game_tid"], tower=sc["tower"], seen=sc["seen"], game_clear=sc["game_clear"])
            mine = R.predict(state, sc["ours"], sc["our_tid"], game_is_player0=game_first)
            where = f"seed {seed}, game {'first' if game_first else 'second'}"
            assert mine["tv"][:24] == model["tv"][:24], (where, [(k, a.hex(), b.hex()) for k, (a, b) in enumerate(zip(mine["tv"], model["tv"])) if a != b][:2])
            assert mine["news"] == model["news"], (where, mine["news"], model["news"])
            assert mine["old_man"] == model["old_man"] and mine["trends"] == model["trends"], where
            assert mine["daycare_mail"] == model["daycare_mail"], where
            assert model["tower_slot"] in mine["tower_slots"], where
            if len(mine["tower_slots"]) == 1:
                assert mine["tower"] == model["tower"], where
    # by hand: our off-air show that someone else made arrives on the air; one the player made doesn't
    rec = R.join({})
    ours = R.split(R.join({}))
    show = bytearray(36); show[0], show[1] = 21, 0; struct.pack_into("<H", show, 0x10, 25); show[0x22:0x24] = b"\x44\x44"
    mine_made = bytearray(show); mine_made[0x22:0x24] = (0x1234).to_bytes(2, "little"); mine_made[0x20:0x22] = b"\x55\x55"
    ours["tv"][0], ours["tv"][1] = bytes(show), bytes(mine_made)
    trend = struct.pack("<HHHH", 120 | 125 << 7, 0, 7, 8)
    ours["trends"][0] = trend
    bard = bytearray(64); bard[0x29] = 1
    ours["old_man"][0] = bytes(bard)
    state = dict(record=rec, tid=0x1234, tower=[bytes(164)] * 5, seen=lambda sp: True, game_clear=True)
    after = R.predict(state, R.join(ours), 0x9999)
    assert after["tv"][5][:2] == bytes([21, 1]) and after["tv"][6][0] == 0, "show made by the player came back to them"
    assert after["trends"][0] == trend and after["old_man"][0x29] == 0
    assert R.predict(dict(state, seen=lambda sp: sp != 25), R.join(ours), 0x9999)["tv"][5][1] == 0, "an unseen Pokémon's show stays off"
    assert after["tower_slots"] == [0]


# ===================================================================== battle partner (PC side)
def battle_mon(name, level=50, moves=(), item="", **kw):
    import duo_battle as B
    return B.Mon(B.species_id(name), level, [B.move_id(m) for m in moves], B.item_id(item), **kw)


@test("battle: damage is the game's, step by step (pokemon.c CalculateBaseDamage, then critical hit, STAB, types, the 85-100 roll), worked by hand")
def _():
    import duo_battle as B
    swampert = battle_mon("SWAMPERT", moves=["EARTHQUAKE", "SURF"])      # Hardy, IVs 31, no EVs
    blaziken = battle_mon("BLAZIKEN", moves=["BLAZE KICK"])
    assert swampert.stats == [175, 130, 110, 80, 105, 110] and blaziken.stats == [155, 140, 90, 100, 130, 90]
    b = B.Battle([swampert], [blaziken], seed=1)
    eq, surf = swampert.moves
    # Earthquake: 130 * 100 * (2*50/5 + 2) // 90 // 50 + 2 = 65; STAB 65*15//10 = 97; Ground on Fire 97*20//10 = 194
    assert b.damage(swampert, blaziken, eq, b.sides[1], roll=100)[0] == 194
    assert b.damage(swampert, blaziken, eq, b.sides[1], roll=85)[0] == 194 * 85 // 100 == 164
    assert b.damage(swampert, blaziken, eq, b.sides[1], crit=True, roll=100)[0] == 130 * 15 // 10 * 2 == 390
    # Surf (special in Gen 3, as Water): 105 * 95 * 22 // 90 // 50 + 2 = 50; STAB 75; Water on Fire 150
    assert b.damage(swampert, blaziken, surf, b.sides[1], roll=100)[0] == 150
    b.sides[1].light_screen = 5                                       # halves it before the +2
    assert b.damage(swampert, blaziken, surf, b.sides[1], roll=100)[0] == (105 * 95 * 22 // 90 // 50 // 2 + 2) * 15 // 10 * 2
    b.weather = "RAIN"                                                 # and rain x1.5 (still before the +2)
    assert b.damage(swampert, blaziken, surf, b.sides[1], roll=100)[0] == (105 * 95 * 22 // 90 // 50 // 2 * 15 // 10 + 2) * 15 // 10 * 2
    # immunities: Ground on a Flying type or Levitate; Normal on a Ghost; Wonder Guard
    for name in ("SKARMORY", "GENGAR", "SHEDINJA"):
        assert b.immune(swampert, battle_mon(name), eq), name
    assert b.immune(battle_mon("SNORLAX"), battle_mon("GENGAR"), B.move_id("BODY SLAM")) == "types"
    assert b.immune(blaziken, battle_mon("SHEDINJA"), B.move_id("BLAZE KICK")) == ""      # Fire is super effective on Bug
    # stat stages, accuracy, critical hits
    swampert.stages[B.ATK] = 8                                        # +2: x2
    assert b.damage(swampert, blaziken, eq, b.sides[1], roll=100)[0] == (260 * 100 * 22 // 90 // 50 + 2) * 15 // 10 * 2
    assert b.accuracy(swampert, blaziken, B.move_id("HYDRO PUMP")) == 0.8
    assert b.crit_chance(swampert, blaziken, eq) == 1 / 16 and b.crit_chance(blaziken, swampert, B.move_id("BLAZE KICK")) == 1 / 8
    assert b.crit_chance(swampert, battle_mon("AGGRON"), eq) == 1 / 16 and b.crit_chance(swampert, battle_mon("ARMALDO"), eq) == 0     # Battle Armor


@test("battle: a Pokemon from a .pk3 has the stats the game gives it (duo_events' party fields), its moves, item, nature and ability")
def _():
    import duo_battle as B
    for pid in (0x12345678, 24, 0x9ABCDEF1):
        data = test_pk3(pid=pid, encrypted=pid & 1 == 0)
        f, _ = W.parse_pk3(data)
        mon = B.mon_from_pk3(data)
        party = W.pk3_party_fields(f)
        assert mon.level == party[4] and mon.stats == list(struct.unpack_from("<6H", party, 8)), (mon.stats, party)
        assert mon.moves == [1, 2] and mon.nature == pid % 25 and mon.species == 409 and mon.hp == mon.maxhp
        assert mon.ability == B.ABILITY[B.SPECIES[409][8]]                           # Serene Grace


@test("battle: whole battles with every species, move and held item play to the end without a fault (random, easy and medium players)")
def _():
    import duo_battle as B
    rng = random.Random(41)
    valid = [s for s in range(1, len(B.SPECIES)) if B.SPECIES[s][0] and s in B.tables().learn]
    items = [int(k) for k in B.HELD] + [0]
    def mon():
        sp, lv = rng.choice(valid), rng.randrange(5, 101)
        pool = sorted(B.learnable(sp, lv)) or [33]
        return B.Mon(sp, lv, rng.sample(pool, min(4, len(pool))), rng.choice(items), rng.randrange(2),
                     [rng.randrange(32) for _ in range(6)], [rng.randrange(256) for _ in range(6)], rng.randrange(25))
    ended = 0
    for n in range(150):
        b = B.Battle([mon() for _ in range(3)], [mon() for _ in range(3)], seed=n)
        kinds = [rng.choice(["random", "easy", "medium"]) for _ in (0, 1)]
        b.run([B.PLAYERS[kinds[0]](n), B.PLAYERS[kinds[1]](n + 1)])
        ended += b.sides[0].lost or b.sides[1].lost
        assert all(0 <= m.hp <= m.maxhp for side in b.sides for m in side.team)
        assert all(0 <= x <= 12 for side in b.sides for m in side.team for x in m.stages)
    assert ended >= 140, ended                                          # (the rest ran to 200 turns)
    log = lambda: B.Battle(B.random_team(random.Random(5)), B.random_team(random.Random(6)), seed=7, log=True)
    one, two = log(), log()
    one.run([B.Medium(1), B.Easy(2)]); two.run([B.Medium(1), B.Easy(2)])
    assert one.log == two.log, "the same seeds gave a different battle"


@test("battle: positions - every level avoids moves that can't work (Normal on a Ghost, Toxic on a Poison type, Thunder Wave on a Ground type, Earthquake on Levitate), and medium and elite always take a sure knock-out")
def _():
    import duo_battle as B
    cases = [("SNORLAX", ["BODY SLAM", "TOXIC", "EARTHQUAKE", "SHADOW BALL"], "GENGAR", {"BODY SLAM", "TOXIC", "EARTHQUAKE"}),
             ("MANECTRIC", ["THUNDER WAVE", "THUNDERBOLT", "CRUNCH"], "SWAMPERT", {"THUNDER WAVE", "THUNDERBOLT"}),
             ("SWAMPERT", ["EARTHQUAKE", "SURF"], "CLAYDOL", {"EARTHQUAKE"})]
    for me, moves, foe, bad in cases:
        for level in ("easy", "medium", "elite"):
            for k in range(6 if level == "elite" else 25):
                b = B.Battle([battle_mon(me, moves=moves)], [battle_mon(foe, moves=["TACKLE"])], seed=k)
                kw = dict(samples=3, playout=10) if level == "elite" else {}
                kind, i = B.PLAYERS[level](k, **kw).choose(b, 0)
                assert B.move_name(b.sides[0].mon.moves[i]) not in bad, (level, me, foe, B.move_name(b.sides[0].mon.moves[i]))
    # a sure knock-out: the foe on its last few HP, with a set-up move and a weak attack to choose from
    for level in ("medium", "elite"):
        for k in range(6):
            foe = battle_mon("SALAMENCE", moves=["DRAGON CLAW", "EARTHQUAKE"])
            foe.hp = 20
            b = B.Battle([battle_mon("GARDEVOIR", moves=["CALM MIND", "PSYCHIC", "THUNDERBOLT", "HYPNOSIS"]), battle_mon("SNORLAX", moves=["BODY SLAM"])],
                         [foe], seed=k)                                     # (its last Pokemon: the knock-out wins)
            kw = dict(samples=4, playout=12) if level == "elite" else {}
            kind, i = B.PLAYERS[level](k, **kw).choose(b, 0)
            assert kind == "move" and B.move_name(b.sides[0].mon.moves[i]) in ("PSYCHIC", "THUNDERBOLT"), (level, kind, i)


@test("battle: the impossible level sees the other side's choice before its own (as the DUO can in a link battle) and answers it - Swampert's Earthquake: switch to Skarmory (immune); its Ice Beam: switch to Walrein (resists) - and only ever picks what the game allows")
def _():
    import duo_battle as B
    for foe_move, want in (("EARTHQUAKE", 1), ("ICE BEAM", 2)):
        picks = []
        for k in range(4):
            b = B.Battle([battle_mon("MANECTRIC", moves=["THUNDERBOLT", "CRUNCH"]), battle_mon("SKARMORY", moves=["DRILL PECK", "STEEL WING"]),
                          battle_mon("WALREIN", moves=["SURF", "ICE BEAM"])], [battle_mon("SWAMPERT", moves=["EARTHQUAKE", "ICE BEAM"])], seed=k)
            foe = ("move", b.sides[1].mon.moves.index(B.move_id(foe_move)))
            pick = B.Impossible(k, samples=6, playout=30).choose(b, 0, foe_action=foe)
            assert pick in b.legal_actions(0), pick
            picks.append(pick)
        assert picks.count(("switch", want)) >= 3, (foe_move, picks)
    # in a whole battle it chooses last, knowing the other side's choice
    seen = []
    class Spy(B.Impossible):
        def choose(self, battle, s, foe_action=None):
            seen.append(foe_action)
            return super().choose(battle, s, foe_action)
    b = B.Battle(B.random_team(random.Random(1)), B.random_team(random.Random(2)), seed=3)
    b.run([Spy(1, samples=2, playout=8), B.Medium(2)], max_turns=4)
    assert seen and all(a is not None for a in seen), seen


@test("battle partner: a double battle's teamwork - the first of the DUO's Pokemon finishes off the foe on 10 HP, and its partner, choosing next, hits the other foe rather than the same one")
def _():
    import duo_battle as B
    lb = B.LinkBattle([test_pk3(species=409, pid=0x2000, otid=0x4E44)], level="medium", double=True, seed=1)
    lb.ours = [battle_mon("MACHAMP", moves=["CROSS CHOP"]), battle_mon("HITMONLEE", moves=["HI JUMP KICK"])]
    weak = battle_mon("SNORLAX", moves=["BODY SLAM"]); weak.hp = 10
    lb.theirs = [weak, battle_mon("SNORLAX", moves=["BODY SLAM"])]
    lb.pending = {1: (B.C_CHOOSEMOVE, bytes(24)), 3: (B.C_CHOOSEMOVE, bytes(24))}
    first = lb._double_move(1)
    lb.chosen[1] = first
    assert first[2] == 0, first                         # (battler 0: the Snorlax on 10 HP)
    assert lb._double_move(3)[2] == 2, lb._double_move(3)
    # through choose(), as the DUO asks: battler 1's move, then battler 3's
    d = bytes([B.C_CHOOSEMOVE, 0, 0, 0]) + struct.pack("<4H", B.move_id("CROSS CHOP"), 0, 0, 0) + bytes([5, 0, 0, 0]) + bytes(8)
    lb.chosen, lb.plan = {}, {}
    lb.ours[0].pp = [5]; lb.ours[1].pp = [5]
    lb.pending = {1: (B.C_CHOOSEMOVE, d), 3: (B.C_CHOOSEMOVE, d)}
    assert lb.choose(1) == (0, 0) and lb.choose(3) == (0, 2), (lb.chosen,)


def _double_view(level, ours, theirs, known=None):
    import duo_battle as B
    lb = B.LinkBattle([test_pk3(species=409, pid=0x2000, otid=0x4E44)], level=level, double=True, seed=1)
    lb.ours, lb.theirs = ours, theirs
    for m in theirs:
        m.known_moves = set(m.moves)
    if known:                                              # (the player has chosen this turn)
        lb.last_choose, lb.turn_mark, lb.player_choice = {0: 5, 2: 5, 1: 6, 3: 6}, {1: 0, 3: 0}, known
    return lb


def _ask(lb, battler):
    """CHOOSEACTION then CHOOSEMOVE for our battler, as the DUO asks: the move's name and target."""
    import duo_battle as B
    m = lb.mon(battler)
    lb.pending[battler] = (B.C_CHOOSEACTION, bytes(4))
    assert lb.choose(battler) == (0, 0)
    d = bytes([B.C_CHOOSEMOVE, 0, 0, 0]) + struct.pack("<4H", *(m.moves + [0] * 4)[:4]) + bytes((m.pp + [0] * 4)[:4]) + bytes(8)
    lb.pending[battler] = (B.C_CHOOSEMOVE, d)
    slot, target = lb.choose(battler)
    return B.move_name(m.moves[slot]), target


@test("battle partner: elite and impossible in a double battle play each pairing of moves out - Golem uses Rock Slide, not Earthquake, beside a Machamp (Earthquake would hit it) but Earthquake beside a Skarmory; impossible never aims at a foe protecting this turn (it hits the Weezing, though Fighting moves do little to it), which medium can't know")
def _():
    for partner, want in (("MACHAMP", "ROCK SLIDE"), ("SKARMORY", "EARTHQUAKE")):
        lb = _double_view("elite", [battle_mon("GOLEM", moves=["EARTHQUAKE", "ROCK SLIDE"]), battle_mon(partner, moves=["TACKLE"])],
                          [battle_mon("SNORLAX", moves=["BODY SLAM"]), battle_mon("SNORLAX", moves=["BODY SLAM"])])
        assert _ask(lb, 1)[0] == want, (partner, _ask(lb, 1))
    def protecting(level):
        weak = battle_mon("SNORLAX", moves=["PROTECT", "BODY SLAM"]); weak.hp = weak.maxhp * 3 // 10
        return _double_view(level, [battle_mon("MACHAMP", moves=["CROSS CHOP"]), battle_mon("HITMONLEE", moves=["HI JUMP KICK"])],
                            [weak, battle_mon("WEEZING", moves=["SLUDGE BOMB"])], known={0: ("move", 0, 1), 2: ("move", 0, 1)})
    lb = protecting("impossible")
    assert _ask(lb, 1)[1] == 2 and _ask(lb, 3)[1] == 2, "impossible aimed at the protecting Snorlax"
    lb = protecting("medium")
    assert _ask(lb, 1)[1] == 0                             # (medium goes for the weakened one)


@test("battle partner: a double battle at the impossible level through the DUO - both Pokemon's choices wait for the player's, follow the rules, and the battle plays to the end")
def _():
    hw, game, report, pk3s = colosseum_run(master=True, double=True, level="impossible", answer_delay=120, fallback=4,
                                           team=(409, 280, 151), duo_wins=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    assert game.result["partner_choices"] and report["fallbacks"] == 0, report
    assert all(t in (0, 2) for _, _, _, t in game.result["partner_choices"])


@test("battle: a team's .pk3 files are checked before a battle - effort values over 510, a move twice, too many PP, stats or a level that don't match its species and experience are refused (even the impossible level plays by the game's rules); an event's special move is only noted")
def _():
    import duo_battle as B
    good = test_pk3(species=409, pid=0x2000, otid=0x4E44, nickname="DUO0")
    problems, notes = B.check_legal(good)
    assert problems == [] and notes and "event" in notes[0], (problems, notes)
    assert B.check_legal(W.pk3_party_form(good))[0] == []
    def edit(data, fn):
        f, _ = W.parse_pk3(data)
        blocks = bytearray(f["blocks"])
        fn(blocks)
        plain = bytes(data[:0x20]) + bytes(blocks)              # (PKHeX's decrypted form, G-A-E-M)
        return plain[:0x1C] + struct.pack("<H", sum(struct.unpack("<24H", bytes(blocks))) & 0xFFFF) + plain[0x1E:]
    many = edit(good, lambda b: b.__setitem__(slice(24, 30), bytes([255, 255, 100, 0, 0, 0])))
    assert any("510" in p for p in B.check_legal(many)[0]), B.check_legal(many)
    twice = edit(good, lambda b: struct.pack_into("<2H", b, 12, 1, 1))
    assert any("same move twice" in p for p in B.check_legal(twice)[0]), B.check_legal(twice)
    pp = edit(good, lambda b: b.__setitem__(20, 99))
    assert any("PP" in p for p in B.check_legal(pp)[0]), B.check_legal(pp)
    boosted = bytearray(good.ljust(80, b"\0")) + bytearray(W.pk3_party_fields(W.parse_pk3(good)[0]))
    struct.pack_into("<H", boosted, 0x5A, 999)                    # Attack 999
    assert any("stats" in p for p in B.check_legal(bytes(boosted))[0]), B.check_legal(bytes(boosted))
    boosted = bytearray(good.ljust(80, b"\0")) + bytearray(W.pk3_party_fields(W.parse_pk3(good)[0]))
    boosted[0x54] = 100
    assert any("level" in p for p in B.check_legal(bytes(boosted))[0])


@test("battle: easy, medium and elite in order of strength - easy wins most battles against random choices (it isn't stupid), medium beats easy, elite beats easy (played both ways round on the same teams)")
def _():
    import duo_battle as B
    w, l, d = B.tournament("easy", "random", 40, seed=3)
    assert w >= 30, (w, l, d)
    w, l, d = B.tournament("medium", "easy", 60, seed=3)
    assert w >= 36, (w, l, d)
    rng, wins = random.Random(8), 0
    for n in range(5):
        teams = B.random_team(rng), B.random_team(rng)
        for swap in (0, 1):
            ta, tb = teams if not swap else teams[::-1]
            b = B.Battle([m.clone() for m in ta], [m.clone() for m in tb], seed=rng.random())
            wins += b.run([B.Elite(rng.random(), samples=4, playout=20), B.Easy(rng.random())]) == 0
    assert wins >= 7, wins


import battle_game_model as BG
import tower_game_model as TWG


def tower_run(team=(409, 280), player_species=(25, 151), enemy_species=(19, 20, 21, 22), level="medium",
              retire_after=0, seconds=600, **game_kw):
    """The DUO's tower program as the player's partner against a simulated Emerald in the Battle Tower."""
    pk3s = [test_pk3(species=sp, pid=0x2000 + 7 * sp, otid=0x00004E44, nickname=f"DUO{k}") for k, sp in enumerate(team)]
    party = [W.pk3_party_form(test_pk3(species=sp, pid=0x1000 + sp, otid=0x2222)) for sp in player_species]
    enemy = [W.pk3_party_form(test_pk3(species=sp, pid=0x3000 + sp, otid=0x3333)) for sp in enemy_species]
    game = TWG.EmeraldTowerMulti(party=party, enemy=enemy, **game_kw)
    hw, duo = run42()
    hw.attach_mp_game(game.run(), game_master=game.master)
    paths = [event_file(d, f"{k} - TEST.pk3") for k, d in enumerate(pk3s)]
    W.BATTLES_DIR = os.path.join(tempfile.mkdtemp(), "battles")
    r = quiet(W.tower_session, duo, types.SimpleNamespace(pk3=paths, seconds=seconds, level=level, fallback=15,
                                                          retire_after=retire_after),
              poll_s=0.2, stop_when=lambda: hw.lg_done)
    hw.text = r[1]
    assert duo.hello() == 0x104
    return hw, game, r[0]


@test("Battle Tower link multi battle (8 November): a three-battle challenge - the lobby's link-up (cards, the link save, the win streaks, the trainers), each battle with the DUO as partner (battler 2, the PC choosing, always at the Tower's trainers), and the carry-on exchange between battles")
def _():
    hw, game, report = tower_run(battles=3, duo_wins=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    r = game.result
    assert r["battles_played"] == 3 and r["battles_won"] == 3 and r["retire_sessions"] == 2, r
    assert r["partner_status"] == [TWG.LINK_CONTINUE] * 2, r["partner_status"]
    assert r["partner_choices"] and all(t in (1, 3) for _, b, _, t in r["partner_choices"] if b == 2), r["partner_choices"]
    assert report["battles"] == 3 and report["won"] == 3 and report["pc_answers"] > 0 and report["fallbacks"] == 0, report
    assert "3 battles, 3 won" in hw.text and report.get("file")


@test("Battle Tower link multi battle: the DUO retires after the first battle (--retire-after 1) - the game hears it, says the partner has retired, and the challenge ends")
def _():
    hw, game, report = tower_run(battles=7, duo_wins=True, retire_after=1)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    r = game.result
    assert r["battles_played"] == 1 and r["partner_status"] == [TWG.LINK_RETIRE], r
    assert r["challenge_status"] == TWG.LINKSTAT_MEMBER_RETIRE and report["verdict"] == TWG.LINKSTAT_MEMBER_RETIRE


@test("Battle Tower link multi battle: the first battle is lost - no carry-on exchange, the challenge is over, and the DUO is done")
def _():
    hw, game, report = tower_run(battles=7, hit_share=0.05, partner_hit_share=0.9)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    r = game.result
    assert r["battles_played"] == 1 and r["battles_won"] == 0 and r["retire_sessions"] == 0, r
    assert report["battles"] == 1 and report["won"] == 0 and report["state"] == W.TOWER_ST["DONE"], report


@test("Battle Tower link multi battle: one battle at the impossible level - the DUO waits for the player's (and the Tower trainers') choices, then answers within the rules")
def _():
    hw, game, report = tower_run(battles=1, duo_wins=True, level="impossible", answer_delay=120)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    assert game.result["partner_choices"] and report["pc_answers"] > 0, report


@test("Battle Tower link multi battle: the player chose a Pokemon of the same species as one of the DUO's - the game ends the link-up, and the tool says why")
def _():
    hw, game, report = tower_run(player_species=(409, 151), seconds=120)
    assert "same species" in repr(hw.lg_error), repr(hw.lg_error)
    assert "didn't get as far as the Tower's trainers" in hw.text, hw.text[-800:]


# ---------------------------------------------------------------- the Berry Blender (8 November)
import blender_game_model as BBG


def blender_run(berries=(133,), seconds=900, duo_berries=None, skill="expert", blends=1, **game_kw):
    """The DUO's blender program at a simulated Berry Blender, the game the leader."""
    game = BBG.BerryBlenderLink(berries=berries, **game_kw)
    hw, duo = run42()
    hw.attach_mp_game(game.run(), game_master=game.master)
    W.BATTLES_DIR = os.path.join(tempfile.mkdtemp(), "battles")
    r = quiet(W.blender_session, duo, types.SimpleNamespace(berry=duo_berries, skill=skill, blends=blends, seconds=seconds,
                                                            name="DUO", gender="boy"),
              poll_s=0.2, stop_when=lambda: hw.lg_done)
    hw.text = r[1]
    assert duo.hello() == 0x104
    return hw, game, r[0]


@test("Berry Blender (8 November): one blend with the player's Cheri - the link-up, the DUO's Oran (its berry block as the game's own), every hit the DUO claims matching the game's own arrow, the leader's time and RPM, the DUO's 'no more', the link save and the close; the PC names the Pokeblock")
def _():
    hw, game, report = blender_run()
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    r = game.result
    assert r["partner_berries"] == [139] and r["partner_answers"] == [BBG.SAY_NO] and r["verdicts"] == ["stop"], r
    b = r["blends"][0]
    # (an expert presses on the best spot each pass; once the arrow outruns it - over 2048 a frame - the
    # good spot is the nearest it lands, as for a player)
    assert b["partner_hits"] and all(h != BBG.HIT_MISS for _, h in b["partner_hits"]), b["partner_hits"]
    assert sum(h == BBG.HIT_BEST for _, h in b["partner_hits"]) >= 10 and b["passes"] <= len(b["partner_hits"]) + 1, b
    assert r["closed"] and report["state"] == W.BLENDER_ST["DONE"] and report["blends"] == 1, report
    d = report["details"][0]
    assert sum(d["hits"][1]) == len(b["partner_hits"]) and d["max_rpm"] == b["max_rpm"] and d["frames"] == b["frames"], (d, b)
    assert "a red Pokeblock (spicy 16; feel 20)" in hw.text and "Blend 1: your Cheri, the DUO's Oran" in hw.text, hw.text[-1200:]


@test("Berry Blender: two blends (--blends 2) - the DUO says yes after the first and no after the second, the game blends again in between")
def _():
    hw, game, report = blender_run(berries=(133, 135), blends=2, answers=[True, True])
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    r = game.result
    assert r["partner_answers"] == [BBG.PLAY_AGAIN, BBG.SAY_NO] and r["verdicts"] == ["again", "stop"], r
    assert len(r["blends"]) == 2 and report["blends"] == 2 and len(report["details"]) == 2, report
    assert "Blend 2: your Pecha, the DUO's Oran" in hw.text, hw.text[-1200:]


@test("Berry Blender: the player brings an Oran too - the DUO puts in its next berry (Sitrus), not a second Oran (a black Pokeblock)")
def _():
    hw, game, report = blender_run(berries=(139,))
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    assert game.result["partner_berries"] == [142], game.result


@test("Berry Blender: a casual DUO (--skill casual) and a player who sometimes misses - good and missed presses too, every one scored by the arrow as the game scores it")
def _():
    plan = lambda n: (BBG.HIT_BEST, BBG.HIT_MISS, BBG.HIT_GOOD)[n % 3]
    hw, game, report = blender_run(skill="casual", player_plan=plan, duo_berries=["Pecha", "Oran"])
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    hits = {h for _, h in game.result["blends"][0]["partner_hits"]}
    assert hits == {BBG.HIT_BEST, BBG.HIT_GOOD, BBG.HIT_MISS}, hits
    assert game.result["partner_berries"] == [135], game.result


@test("Berry Blender: the player wants another blend but the DUO stays for one - the leader's verdict is 'stop' (the DUO's answer), and the link closes")
def _():
    hw, game, report = blender_run(berries=(133, 135), blends=1, answers=[True, True])
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    r = game.result
    assert r["partner_answers"] == [BBG.SAY_NO] and r["verdicts"] == ["stop"] and len(r["blends"]) == 1, r


# ---------------------------------------------------------------- the four-player cable experiment (8 November)
import gp_link_model as GPL


def lab4p_run(players=3, link="trade", seconds=60, **game_kw):
    """The lab4p program driving the link port bit by bit against a line-level model of a game's
    serial hardware (child 1) and its link layer."""
    hw, duo = run42()
    game = GPL.GpLinkGame(hw, **game_kw)
    W.BATTLES_DIR = os.path.join(tempfile.mkdtemp(), "battles")
    r = quiet(W.lab4p_session, duo, types.SimpleNamespace(players=players, link=link, seconds=seconds, gap=4, bit_adjust=0),
              poll_s=0.2, stop_when=lambda: game.result["closed"])
    hw.text = r[1]
    assert duo.hello() == 0x104
    return hw, game, r[0]


@test("lab4p (8 November): the four-player experiment against a line-level model of the game's serial hardware - the DUO's bits read back as words in slots 0, 2 and 3 around the game's slot 1, the handshake counts four players, the game's checksums take in all four slots, and a Trade Center link-up (two players only) is refused and closed")
def _():
    hw, game, report = lab4p_run(players=3, link="trade", max_players=2)
    assert not game.errors, game.errors[:5]
    r = game.result
    assert r["handshake_players"] == 4 and r["checksum_errors"] == 0, r
    assert sorted(r["link_players"]) == [0, 2, 3] and r["refused"] is True and r["closed"], r
    assert report["players_seen"] == 4 and report["ck_four"] > 0 and report["timeouts"] == 0, report
    assert "it counted four players" in hw.text, hw.text[-1200:]


@test("lab4p: the control - the DUO as one player (slot 0 only) on the bit-by-bit link: the game hears two players, its checksums match, its link player arrives, and the Trade Center link-up carries on")
def _():
    hw, game, report = lab4p_run(players=1, link="trade", seconds=25, max_players=2)
    assert not game.errors, game.errors[:5]
    r = game.result
    assert r["handshake_players"] == 2 and r["checksum_errors"] == 0 and r["refused"] is False, r
    assert report["game_version"] == 2 and report["ck_two"] + report["ck_four"] > 0, report


@test("lab4p: a game whose hardware waits less for the next child than the DUO's gap (0.8 bits, the gap one bit) - slots 2 and 3 arrive too late and stay 0xFFFF, so the game counts two players: what --gap is there to try")
def _():
    hw, game, report = lab4p_run(players=3, link="none", seconds=20, window=0.8)
    r = game.result
    assert r["handshake_players"] == 2, r
    assert all(t[2] == 0xFFFF for t in game.transfers[-5:]), game.transfers[-5:]


# ---------------------------------------------------------------- Emerald's link Contest (8 November)
import contest_game_model as CTG


def contest_run(species=300, moves=(45, 39, 33, 98), seconds=900, category="cool", order=None, duo_category="cool",
                **game_kw):
    """The DUO's contest program as a contestant against a simulated Emerald (E mode), the game leading."""
    raw = test_pk3(species=species, pid=0x5000 + species, otid=0x00004E44, nickname="SKITTY", moves=moves, lang=2)
    game = CTG.EmeraldLinkContest(category=category, partner_species=species, partner_moves=list(moves), **game_kw)
    hw, duo = run42()
    hw.attach_mp_game(game.run(), game_master=game.master)
    W.BATTLES_DIR = os.path.join(tempfile.mkdtemp(), "battles")
    r = quiet(W.contest_session, duo, types.SimpleNamespace(pk3=[event_file(raw, "0 - SKITTY.pk3")], category=duo_category,
                                                            order=order, seconds=seconds, allow_unchecked=True),
              poll_s=0.2, stop_when=lambda: hw.lg_done)
    hw.text = r[1]
    assert duo.hello() == 0x104
    return hw, game, r[0]


@test("Contest (8 November): Emerald's link Contest in E mode - the link-up as an Emerald player, the set-up (the DUO's contestant in the link's form, nothing back where only the leader sends, the category and the leader's figures sent back), five rounds of the DUO's own moves in turn, every block of the appeals answered at its size, the final standings, the close")
def _():
    hw, game, report = contest_run(duo_place=1)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    r = game.result
    assert r["partner_moves"] == [45, 39, 33, 98, 45] and r["partner_index"] == [1, 1] and r["closed"], r
    assert report["standings"] == [0, 1, 2, 3] and report["rounds"] == 5 and report["state"] == W.CONTEST_ST["DONE"], report
    assert "your Pokemon came 1st, the DUO's" in hw.text and "2nd" in hw.text, hw.text[-800:]


@test("Contest: the DUO's moves in the order given (--order 2 1) and a beauty contest - the category matches the player's, and the DUO wins")
def _():
    hw, game, report = contest_run(category="beauty", duo_category="beauty", order=["2", "1"], duo_place=0)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    assert game.result["partner_moves"] == [39, 45, 39, 45, 39], game.result["partner_moves"]
    assert report["standings"][1] == 0 and "the DUO's" in hw.text and "1st." in hw.text, hw.text[-600:]





def switch_off_at(duo, state):
    """From the first status poll that shows `state` (or later), the DUO answers nothing more: its
    GBA switched off (7 November, hardware). Returns a function that switches it back on."""
    import usb.core
    orig, off = duo.ask, []

    def ask(cmd, *a, **k):
        if off:
            raise usb.core.USBTimeoutError("timeout")
        r = orig(cmd, *a, **k)
        if cmd == W.PROG_POLL and (a[:1] or [0])[0] == 0 and (r[1] & 0x1F) >= state:
            off.append(True)
        return r
    duo.ask = ask

    def back_on():
        duo.ask = orig
        W.stop_program_quietly(duo)
    return back_on


def colosseum_run(master=True, team=(409, 280), game_species=(25, 151), seconds=300, off_at=None, level="simple",
                  moves=None, game_moves=None, fallback=15, pc_wait=None, **game_kw):
    """The DUO's colosseum program against a simulated Ruby in the Colosseum; `level` is how the PC
    chooses for it ("simple": the DUO plays by itself, the probe). moves / game_moves: each side's
    moves (lists of move IDs, one list per Pokemon)."""
    pk3s = [test_pk3(species=sp, pid=0x2000 + 7 * sp, otid=0x00004E44, nickname=f"DUO{k}",
                     **({"moves": moves[k]} if moves else {})) for k, sp in enumerate(team)]
    party = [W.pk3_party_form(test_pk3(species=sp, pid=0x1000 + sp, otid=0x2222,
                                       **({"moves": game_moves[k]} if game_moves else {}))) for k, sp in enumerate(game_species)]
    game = BG.RubyColosseum(master=master, party=party, **game_kw)
    hw, duo = run42()
    hw.attach_mp_game(game.run(), game_master=game.master)
    paths = [event_file(d, f"{k} - TEST.pk3") for k, d in enumerate(pk3s)]
    W.BATTLES_DIR = os.path.join(tempfile.mkdtemp(), "battles")
    back_on = switch_off_at(duo, off_at) if off_at is not None else None
    r = quiet(W.colosseum_session, duo, types.SimpleNamespace(pk3=paths, seconds=seconds, level=level, fallback=fallback),
              poll_s=0.2, stop_when=lambda: hw.lg_done)
    hw.text = r[1]
    if back_on:
        back_on()
    assert duo.hello() == 0x104
    hw.stop(); clean(hw)                              # nothing written to any cartridge
    return hw, game, r[0], pk3s


@test("battle probe, the game as master (the cable as fitted): the DUO walks to its spot, the battle's link opens, the headers and parties swap (the game runs the battle), every command gets its done and the DUO's choices; the DUO's last Pokemon faints, the battle ends, the DUO walks out; the record is kept and reads back")
def _():
    hw, game, report, pk3s = colosseum_run(master=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    res = game.result
    assert res["battle_master"] == 0 and res["battled"] and res["left_room"] and res["partner_left_by_door"], res
    assert res["partner_spot"] == (10, 5) and res["same_partner"], res
    assert res["partner_party"] == b"".join(W.pk3_party_form(d) for d in pk3s).ljust(600, b"\0")
    assert res["partner_header"][:4] == bytes([1, 1, 0b0101, 0]), res["partner_header"].hex()
    assert res["outcome"] == BG.B_OUTCOME_WON and res["partner_switches"] == [(2, 1, 1)], (res["outcome"], res["partner_switches"])
    assert all(slot == 0 for _, _, slot, _ in res["partner_choices"]) and res["partner_dones"] == res["commands"], res
    assert report["bad_checksums"] == 0 and report["dropped"] == 0 and report["commands"] == res["commands"], report
    text = open(report["file"] + ".txt", encoding="utf-8").read()
    for line in ("link opened, type 0x2233", "link opened, type 0x2211", "battle header: signature 0x0101",
                 "party block 1: PIKACHU, MEW", "command CHOOSEMOVE", "the DUO chose Pokemon 1 to send in",
                 "command ENDLINKBATTLE", "won for the game's side", "link opened, type 0x2233"):
        assert line in text, (line, text[-3000:])
    for line in ("the DUO is player 1", "single battle", "swapping teams", "battling", "the battle is over (won for the game's side)",
                 "leaving the room", "done", "Kept on this PC: the battle's record"):
        assert line in hw.text, (line, hw.text[-2000:])


@test("battle probe: the DUO's GBA is switched off as soon as the DUO walks out (7 November, hardware: the record was lost) - the record copied during the battle is kept, the battle counts as played to the end, and the tool says it was switched off too soon")
def _():
    hw, game, report, pk3s = colosseum_run(master=True, off_at=W.COLOSSEUM_ST["WALKING_OUT"])
    text = hw.text
    assert report["cut_short"] and report.get("file"), (report.get("file"), text[-1500:])
    assert "switched off too soon" in text and "The battle was played to the end" in text, text[-1500:]
    assert "safe to switch off" in text                                # (said at the battle's end)
    lines = open(report["file"] + ".txt", encoding="utf-8").read()
    assert "cut short" in lines, lines[:400]
    assert sum(1 for k, _, _ in report["entries"] if k == 0) >= 10, "the battle's blocks weren't kept"


@test("battle probe: at the end the tool says it's safe to switch off only once the record is kept on this PC")
def _():
    hw, game, report, pk3s = colosseum_run(master=True)
    text = hw.text
    assert text.index("Keep the DUO's GBA switched on") < text.index("Kept on this PC") < text.index("safe to switch the DUO's GBA off now"), text[-1200:]
    assert not report["cut_short"]


def _ids(*names, kind="move"):
    import duo_battle as B
    return [B.move_id(n) if kind == "move" else B.species_id(n) for n in names]


@test("battle partner (8 November): the PC chooses the DUO's moves at the medium level - against a Gengar it uses Shadow Ball, never Tackle (slot 0, which the probe would use and which can't touch a Ghost)")
def _():
    gengar, = _ids("GENGAR", kind="species")
    hw, game, report, pk3s = colosseum_run(master=True, team=_ids("ALAKAZAM", kind="species"), game_species=(gengar,),
                                           moves=[_ids("TACKLE", "SHADOW BALL")], game_moves=[_ids("LICK")], level="medium",
                                           duo_wins=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    choices = game.result["partner_choices"]
    assert choices and all(slot == 1 for _, _, slot, _ in choices), choices
    assert report["pc_answers"] >= 2 * len(choices) - 1 and report["fallbacks"] == 0, report
    assert "made by the PC at the medium level" in hw.text


@test("battle partner: the impossible level waits for the player's choice each turn (it reaches the DUO over the link) and only then answers, within the game's rules")
def _():
    hw, game, report, pk3s = colosseum_run(master=True, level="impossible", answer_delay=300, duo_wins=True, fallback=3)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    seq = game.result["answer_frames"]
    turns = 0
    for i, (who, b, cmd, n, k) in enumerate(seq):
        if who == "partner" and cmd == BG.CHOOSEACTION:
            turns += 1
            before = [e for e in seq[:i] if e[0] == "game" and e[2] == BG.CHOOSEMOVE]
            last_partner = max([j for j in range(i) if seq[j][0] == "partner" and seq[j][2] == BG.CHOOSEACTION], default=-1)
            assert before and seq.index(before[-1]) > last_partner, f"turn {turns}: answered before the player chose ({seq[:i + 1]})"
    assert turns >= 2 and report["fallbacks"] == 0, (turns, report)


@test("battle partner: when the PC stops choosing (an error here), the DUO waits its fallback time and then chooses by itself; the battle still plays to the end")
def _():
    import duo_battle as B
    real = B.LinkBattle.choose
    B.LinkBattle.choose = lambda self, battler: (_ for _ in ()).throw(RuntimeError("made-up failure"))
    try:
        hw, game, report, pk3s = colosseum_run(master=True, level="medium", fallback=2, seconds=150)
    finally:
        B.LinkBattle.choose = real
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    assert "The PC couldn't choose" in hw.text and report["fallbacks"] >= 1, (report, hw.text[-800:])
    assert game.result["battled"] or game.result["outcome"], game.result


@test("battle partner: Emerald - the DUO introduces itself as a Ruby player (two Emerald players would add a recorded battle's seed and, with a Frontier Pass, the offer to record it), and the battle plays to the end, single and double")
def _():
    for double in (False, True):
        hw, game, report, pk3s = colosseum_run(master=True, level="medium", game="emerald", double=double,
                                               team=(409, 280, 151) if double else (409, 280), duo_wins=True)
        assert hw.lg_error is None and hw.lg_done, (double, repr(hw.lg_error), game.log, hw.text[-1500:])
        assert game.link_players[game.other]["version"] & 0xFF == 2 and not game.result["seed_exchanged"], game.link_players
        assert "to Emerald the DUO is a Ruby player" in hw.text and report["fallbacks"] == 0


@test("battle partner: FireRed and LeafGreen - the DUO is a player of the same game, with the progress flags the games look for (National Dex, game cleared), and the battle plays to the end; the DUO as player 0 too")
def _():
    for g, master in (("firered", True), ("leafgreen", False)):
        hw, game, report, pk3s = colosseum_run(master=master, level="medium", game=g, duo_wins=True)
        assert hw.lg_error is None and hw.lg_done, (g, repr(hw.lg_error), game.log, hw.text[-1500:])
        lp = game.link_players[game.other]
        assert lp["version"] & 0xFF == game.version and lp["progress"] & 0x11 == 0x11, lp
        assert game.result["battle_master"] == game.my_id


@test("battle partner: the PC's answer breaks the rules (a move slot with no move) - the DUO doesn't send it, chooses by itself instead, and the battle goes on")
def _():
    import duo_battle as B
    real = B.LinkBattle.choose
    def bad(self, battler):
        cmd = self.pending[battler][0]
        return (3, battler ^ 1) if cmd == B.C_CHOOSEMOVE else real(self, battler)
    B.LinkBattle.choose = bad
    try:
        hw, game, report, pk3s = colosseum_run(master=True, level="medium")
    finally:
        B.LinkBattle.choose = real
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    assert report["fallbacks"] >= 1 and all(slot != 3 for _, _, slot, _ in game.result["partner_choices"]), \
        (report, game.result["partner_choices"])


@test("battle partner: a double battle chosen by the PC - each of the DUO's two Pokemon aims at a foe it can hurt (Tackle never at the Gengar), the replacement after a faint is one that can battle, and it plays to the end")
def _():
    gengar, rattata = _ids("GENGAR", "RATTATA", kind="species")
    hw, game, report, pk3s = colosseum_run(master=True, double=True, level="medium",
                                           team=_ids("MACHAMP", "HITMONLEE", "PRIMEAPE", kind="species"),
                                           moves=[_ids("TACKLE")] * 3, game_species=(gengar, rattata),
                                           game_moves=[_ids("LICK"), _ids("TACKLE")], duo_wins=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    choices = game.result["partner_choices"]
    assert choices, game.result
    assert all(t == 2 for _, _, _, t in choices), f"Tackle aimed at the Gengar (battler 0): {choices}"
    for turn, b, pick in game.result["partner_switches"]:                # (after a faint: one fit and not out)
        assert pick == 2, game.result["partner_switches"]
    assert report["pc_answers"] > 0 and report["fallbacks"] == 0, report


@test("battle partner: a Pokemon that couldn't exist (effort values over 510) is refused before anything is sent, unless --allow-unchecked")
def _():
    good = test_pk3(species=409, pid=0x2000, otid=0x4E44)
    f, _ = W.parse_pk3(good)
    blocks = bytearray(f["blocks"]); blocks[24:30] = bytes([255, 255, 255, 0, 0, 0])
    bad = good[:0x1C] + struct.pack("<H", sum(struct.unpack("<24H", bytes(blocks))) & 0xFFFF) + good[0x1E:0x20] + bytes(blocks)
    path = event_file(bad, "0 - TEST.pk3")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            W.colosseum_session(None, types.SimpleNamespace(pk3=[path], level="impossible"))
            raise AssertionError("an impossible Pokemon was accepted")
        except ValueError as e:
            assert "couldn't exist" in str(e) and "--allow-unchecked" in str(e), e
    assert "510" in out.getvalue(), out.getvalue()


@test("battle probe, the DUO as master: as player 0 it sends the signature 0x0001, lower than any game's, so the game still runs the battle; the battle's link opens with its own link type; the DUO takes the left spot and walks out")
def _():
    hw, game, report, pk3s = colosseum_run(master=False)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    res = game.result
    assert res["battle_master"] == game.my_id == 1 and res["battled"] and res["left_room"] and res["partner_left_by_door"], res
    assert res["partner_spot"] == (3, 5) and res["partner_header"][:2] == b"\x01\x00", res
    assert res["partner_dones"] == res["commands"] and report["master"] == 1 and report["bad_checksums"] == 0, report
    assert "the DUO is player 0" in hw.text and "battle header: signature 0x0001" in open(report["file"] + ".txt").read()


@test("battle probe: the player stands on the DUO's usual spot, so the DUO takes the other one")
def _():
    hw, game, report, pk3s = colosseum_run(master=True, spot=(10, 5), team=(409,))
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    res = game.result
    assert res["game_spot"] == (10, 5) and res["partner_spot"] == (3, 5) and res["battled"], res
    assert res["partner_header"][2:4] == b"\x01\x00" and res["partner_switches"] == [], res      # one Pokemon: no switch


@test("battle probe: a double battle (the same room and link): the DUO answers for battlers 1 and 3, aims at the foe opposite, sends in its third Pokemon (not the one still on the field) and plays to the end")
def _():
    # (its first Pokemon a Shedinja, 1 HP: it faints while the second is still on the field)
    hw, game, report, pk3s = colosseum_run(master=True, double=True, team=(303, 280, 25), game_species=(25, 151, 280))
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    res = game.result
    assert res["battled"] and res["left_room"] and res["partner_dones"] == res["commands"], res
    assert {b for _, b, _, _ in res["partner_choices"]} == {1, 3}, res["partner_choices"]
    assert all(t == b ^ 1 for _, b, _, t in res["partner_choices"]), res["partner_choices"]
    assert res["partner_switches"] == [(1, 1, 2)], res["partner_switches"]
    assert "double battle" in hw.text, hw.text[-1500:]


@test("battle probe: the DUO's side wins (the game's Pokemon faint, it sends in its next itself); the player walks out first and the DUO follows")
def _():
    hw, game, report, pk3s = colosseum_run(master=False, hit_share=0.2, partner_hit_share=0.7, leaves_first=True)
    assert hw.lg_error is None and hw.lg_done, (repr(hw.lg_error), game.log, hw.text[-1500:])
    res = game.result
    assert res["outcome"] == BG.B_OUTCOME_LOST and res["left_room"] and res["partner_switches"] == [], res
    assert "lost for the game's side" in hw.text, hw.text[-1500:]


if __name__ == "__main__":
    pick = sys.argv[1] if len(sys.argv) > 1 else ""
    passed = failed = skipped = 0
    t_all = time.time()
    for name, fn in RESULTS:
        if pick and pick not in name:
            continue
        t = time.time()
        try:
            fn()
            for hw in LIVE:
                if hw.thread.is_alive():
                    hw.stop()
            LIVE.clear()
            passed += 1
            print(f"[PASS] {name}  ({time.time() - t:.0f}s)", flush=True)
        except (Skip, paths.MissingBuild) as e:
            skipped += 1
            for hw in LIVE:
                if hw.thread.is_alive():
                    hw.stop()
            LIVE.clear()
            print(f"[SKIP] {name}  ({e})", flush=True)
        except Exception as e:
            for hw in LIVE:
                if hw.thread.is_alive():
                    hw.stop()
            if MISSING_BUILD:      # without the firmware a test can't tell a real failure from a missing image
                skipped += 1
                LIVE.clear()
                print(f"[SKIP] {name}  ({MISSING_BUILD})", flush=True)
                continue
            failed += 1
            print(f"[FAIL] {name}\n       {type(e).__name__}: {str(e)[:600]}", flush=True)
            if not isinstance(e, AssertionError):
                traceback.print_exc(limit=3)
    print(f"\n{passed} passed, {failed} failed" + (f", {skipped} skipped" if skipped else "") + f" in {time.time() - t_all:.0f}s")
    sys.exit(1 if failed else 0)
