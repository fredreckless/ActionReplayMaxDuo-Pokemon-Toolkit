"""diff_hwsim.py - the original hwsim.py against the one built on the shared core.

    python3 diff_hwsim.py OLD_HWSIM NEW_HWSIM [--programs N] [--seed S]

Runs the same random bus programs on both and compares everything a test could see: every byte
of the cartridge as the CPU reads it (the DUO/game span, a sample of open bus, the save window),
every value read, the mapping, the save chip's state and contents, the violations, the failures
and their wording, and the USB link's turn and errors. No firmware is needed: the programs are
run by a small Thumb interpreter in RAM, so the mapping register is written from RAM as Datel's
code does.
"""
import argparse, gc, importlib.util, os, random, struct, sys

from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_SP
from unicorn import UcError

CODE, TABLE, OUT, PKT = 0x02010000, 0x02020000, 0x02030000, 0x0203F000
ROM, SAVE = 0x08000000, 0x0E000000
F_USB_SEND8 = 0x0800C29C

W8, W16, W32, R8, R16, R32, SEND = range(7)

INTERP = """
loop:
  cmp r6, #0
  beq done
  ldr r0, [r4, #0]
  ldr r1, [r4, #4]
  ldr r2, [r4, #8]
  adds r4, #12
  subs r6, #1
  cmp r0, #0
  beq w8
  cmp r0, #1
  beq w16
  cmp r0, #2
  beq w32
  cmp r0, #3
  beq r8
  cmp r0, #4
  beq r16
  cmp r0, #5
  beq r32
  mov r0, r2
  blx r1
  b loop
w8:
  strb r2, [r1]
  b loop
w16:
  strh r2, [r1]
  b loop
w32:
  str r2, [r1]
  b loop
r8:
  ldrb r3, [r1]
  str r3, [r5]
  adds r5, #4
  b loop
r16:
  ldrh r3, [r1]
  str r3, [r5]
  adds r5, #4
  b loop
r32:
  ldr r3, [r1]
  str r3, [r5]
  adds r5, #4
  b loop
done:
  b done
"""

# Datel's SEND8 (0x0800C29C in firmware 1.06), as tests/test_link.py transcribes it, in Thumb: the
# random firmware needs it there, since the new hwsim.py runs Datel's own USB code (the original
# replaced it with Python, so the bytes there don't matter to it). The original let a program send
# while a PC packet was still waiting, taking it as read; Datel always reads it first (RECV8,
# 0x0800C1FC), so when one is waiting (the two strobes differ) this reads it first too.
SEND8 = """
  push {r4, r5, r6, r7, lr}
  ldr r4, link_in
  ldr r5, link_out
  ldr r6, shadow
  ldrh r1, [r4]
  ldrh r2, [r6]
  eors r1, r2
  lsrs r1, r1, #9
  bcc send
  movs r7, #4
recv:
rw1:
  ldrh r1, [r4]
  lsrs r1, r1, #9
  bcc rw1
  ldrh r2, [r6]
  movs r3, #1
  lsls r3, r3, #8
  orrs r2, r3
  strh r2, [r6]
  strh r2, [r5]
rw0:
  ldrh r1, [r4]
  lsrs r1, r1, #9
  bcs rw0
  ldrh r2, [r6]
  bics r2, r3
  strh r2, [r6]
  strh r2, [r5]
  subs r7, #1
  bne recv
send:
  movs r7, #4
next:
w1:
  ldrh r1, [r4]
  lsrs r1, r1, #9
  bcc w1
  ldrh r2, [r6]
  movs r3, #0xFF
  lsls r3, r3, #8
  ands r2, r3
  ldrb r1, [r0]
  orrs r2, r1
  movs r1, #1
  lsls r1, r1, #8
  orrs r2, r1
  strh r2, [r6]
  strh r2, [r5]
w0:
  ldrh r1, [r4]
  lsrs r1, r1, #9
  bcs w0
  ldrh r2, [r6]
  movs r3, #0xFE
  lsls r3, r3, #8
  ands r2, r3
  ldrb r1, [r0, #1]
  orrs r2, r1
  strh r2, [r6]
  strh r2, [r5]
  adds r0, #2
  subs r7, #1
  bne next
  pop {r4, r5, r6, r7, pc}
  .align 2
link_in: .word 0x09FE01C0
link_out: .word 0x09FE01E0
shadow: .word 0x0300212C
"""


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    spec.loader.exec_module(mod)
    return mod


def program(rng, n, duo=True):
    """Random bus traffic. It follows its own mapping writes, so accesses that only make sense
    with the DUO mapped (flash ID mode, calling Datel's USB routine) mostly come at the right
    time; now and then one comes at the wrong time, and both simulators must fail alike."""
    ops = [(W16, 0x04000208, 0), (W16, 0x04000204, 0x4317)]   # as Datel's code runs: IME off, safe timing
    sent = False                                           # one GBA packet per PC packet
    flash_cmds = [0x90, 0xF0, 0xB0, 0x80, 0xA0, 0x10, 0x30, 0x00]
    wrong = lambda: rng.random() < 0.02
    while len(ops) < n:
        k = rng.random()
        if k < 0.10:                                           # swap the game or the DUO in
            v = rng.choice([0x0120, 0x0101, 0x0007, 0x0001, 0x0120, 0x0101])
            if rng.random() < 0.005:
                v = rng.randrange(0x10000)
            ops.append((rng.choice([W16, W16, W16, W32]), 0x0800009C, v))
            duo = v == 0x0120 if v in (0x0120, 0x0101, 0x0007, 0x0001) else duo
        elif k < 0.30:                                         # a Flash command, mostly well formed
            cmd = rng.choice(flash_cmds)
            seq = [(0x5555, 0xAA), (0x2AAA, 0x55), (0x5555, cmd)]
            if cmd == 0xB0:
                seq.append((0, rng.randrange(4)))
            if rng.random() < 0.25:                           # broken sequences
                i = rng.randrange(len(seq))
                seq[i] = (rng.choice([0x5555, 0x2AAA, 0, rng.randrange(0x10000)]), rng.choice([0xAA, 0x55, 0xF0, rng.randrange(256)]))
            if rng.random() < 0.2:
                seq = seq[:rng.randrange(1, len(seq) + 1)]
            for off, v in seq:
                ops.append((W8 if rng.random() < 0.95 else W16, SAVE + (off & ~1 if rng.random() < 0.05 else off), v))
        elif k < 0.34:                                         # a reset at 0
            ops.append((W8, SAVE, 0xF0))
        elif k < 0.37:                                         # anything else to the save chip (SRAM writes)
            ops.append((W8, SAVE + rng.randrange(0x10000), rng.randrange(256)))
        elif k < 0.52:                                         # save reads, mostly byte-wide
            w = rng.choice([R8] * 12 + [R16, R32])
            ops.append((w, SAVE + (rng.randrange(0x10000) & ~({R8: 0, R16: 1, R32: 3}[w])), 0))
        elif k < 0.70:                                         # ROM reads: header, overlay, flash, game, open bus
            w = rng.choice([R8, R16, R32])
            a = rng.choice([0, 4, 0x20, 0x9C, 0x9E, 0xA0, 0x100, 0x1100, 0x7FFFC, 0x80000, 0xFFFFC, 0x100000,
                            0x17FFFC, 0x200000, rng.randrange(0x400000), rng.randrange(0x2000000)])
            ops.append((w, ROM + (a & ~({R8: 0, R16: 1, R32: 3}[w])), 0))
        elif k < 0.77:                                         # the DUO flash's ID mode
            # The SST chip's own sequences, as Datel sends them (since step 4 the core decodes
            # them as the chip does; the original took any write to these two addresses): ID
            # entry AA/55/90, exit F0. A wrong one is a write both reject.
            if wrong():
                ops.append((W16, ROM + rng.choice([0, 0x100]), rng.choice([0x9090, 0x1234])))
            elif duo:
                if rng.random() < 0.5:
                    ops += [(W16, 0x0800AAAA, 0xAAAA), (W16, 0x08005554, 0x5555), (W16, 0x0800AAAA, 0x9090)]
                else:
                    ops.append((W16, ROM, 0xF0F0))
        elif k < 0.85:                                         # WAITCNT: safe, and too fast for the ROM
            ops.append((rng.choice([W16, W16, W16, W8]), 0x04000204 + (1 if rng.random() < 0.05 else 0),
                        rng.choice([0x4317, 0x4317, 0x431B, 0x4314, 0x4318, 0x0003])))
        elif k < 0.89:                                         # IME
            ops.append((W16, 0x04000208, 0 if rng.random() < 0.9 else 1))
        elif k < 0.95:                                         # the GBA sends a USB packet
            if (duo and not sent) or wrong():
                ops.append((SEND, F_USB_SEND8 | 1, PKT))
                sent = True
        elif k < 0.952:                                        # a stray write to ROM (a failure)
            ops.append((rng.choice([W8, W16]), ROM + rng.randrange(0x200000) & ~1, rng.randrange(0x10000)))
        elif rng.random() < 0.1 or duo:                        # control-area reads
            ops.append((R16, 0x09FE0000 + (rng.randrange(0x20000) & ~1), 0))
    return ops


def make(mod, fw, game, save_type, save):
    hw = mod.Hw(fw, game, save_type, save)
    mu = hw.mu
    mu.mem_write(CODE, CODE_BYTES)
    mu.mem_write(PKT, bytes(range(0x40, 0x48)))
    return hw


def run(hw, ops):
    mu = hw.mu
    tbl = b"".join(struct.pack("<III", k, a & 0xFFFFFFFF, v & 0xFFFFFFFF) for k, a, v in ops)
    mu.mem_write(TABLE, tbl)
    mu.mem_write(OUT, bytes(4 * len(ops)))
    mu.reg_write(UC_ARM_REG_R4, TABLE)
    mu.reg_write(UC_ARM_REG_R5, OUT)
    mu.reg_write(UC_ARM_REG_R6, len(ops))
    mu.reg_write(UC_ARM_REG_SP, 0x03007E00)
    hw.pending_view = False
    try:
        mu.emu_start(CODE | 1, DONE)
        while hw.pending_view and not hw.bad:
            hw.pending_view = False
            hw.show_game()
            mu.emu_start(mu.reg_read(UC_ARM_REG_PC) | 1, DONE)
    except UcError as e:
        hw.bad.append(f"CPU fault: {e}")
    return bytes(mu.mem_read(OUT, 4 * len(ops)))


def pc_side(hw, mod, rng):
    """The PC writes packets, sometimes two in a row."""
    t = mod.Transport(hw)
    for _ in range(rng.choice([1, 1, 1, 1, 1, 1, 0, 2])):
        try:
            t.write(bytes([rng.randrange(256) for _ in range(8)]), timeout=1)
        except Exception as e:                                  # the USB timeout
            hw.link_errors.append(f"(raised {type(e).__name__})")


def snapshot(hw, rom_samples):
    """Everything a test could see. The state first, then memory: in the new hwsim.py the control
    area is MMIO, so an open-bus sample read there reaches the core as a CPU read would (a failure
    while the game is mapped, and a wake for a sleeping save chip)."""
    mu = hw.mu
    span = max(0x100000, len(hw.game))
    s = {
        "mapped": hw.mapped, "awake": hw.awake, "bank": hw.bank, "id_mode": hw.id_mode,
        "save": bytes(hw.save), "violations": list(hw.violations), "bad": list(hw.bad),
        "map_writes": list(hw.map_writes), "save_writes": hw.save_writes, "ignored": hw.ignored,
        "waitcnt": hw.waitcnt, "turn": hw.turn, "link_errors": list(hw.link_errors),
        "sent": hw.d2h.qsize(), "pc": hw.pc_packets, "save_reads": hw.save_reads,
    }
    s["save window"] = bytes(mu.mem_read(SAVE, 0x10000))
    s["rom"] = bytes(mu.mem_read(ROM, span))
    s["open bus"] = [bytes(mu.mem_read(ROM + a, 64)) for a in rom_samples]
    return s


def _one(a, old, new, extra, progress=False):
    import subprocess
    env = dict(os.environ, DIFF_PROGRESS="1") if progress else os.environ
    return subprocess.run([sys.executable, __file__, old, new, "--programs", str(a.programs), "--ops", str(a.ops),
                           "--seed", str(a.seed)] + extra, capture_output=True, text=True, env=env)


def original_crashes_too(a, i, lo=None):
    """Does the original hwsim.py misbehave against itself on program i (crash, or disagree with
    itself about a value read)? Then it's Unicorn's fault (seen with the original alone: a crash
    in libunicorn's own memory code, or a CPU load returning the wrong value), not the core's."""
    span = ["--only", str(i)] if lo is None else ["--range", f"{lo}:{i + 1}"]   # with the same history
    return any(_one(a, a.old, a.old, span).returncode != 0 for _ in range(3))


def batches(a):
    """Run the programs N at a time, each batch in its own process. A program that crashes is
    checked against the original on its own: if the original crashes there too, it's counted as
    Unicorn's and skipped; otherwise the comparison fails."""
    import re
    totals, unicorn = {}, []
    todo = [(lo, min(a.programs, lo + a.batch)) for lo in range(0, a.programs, a.batch)]
    while todo:
        lo, hi = todo.pop(0)
        if lo >= hi:
            continue
        r = _one(a, a.old, a.new, ["--range", f"{lo}:{hi}"], progress=True)
        if r.returncode < 0:                                    # crashed: in which program?
            got = [int(x) for x in re.findall(r"starting program (\d+)", r.stdout)]
            i = got[-1] if got and lo <= got[-1] < hi else lo
            if not original_crashes_too(a, i, lo):
                print(r.stderr[-1500:])
                print(f"FAILED: program {i} crashes with the new hwsim.py; the original against itself doesn't")
                return 1
            unicorn.append(i)
            todo[:0] = [(lo, i), (i + 1, hi)]                   # the rest of the batch, around it
            continue
        if r.returncode != 0 or "IDENTICAL" not in r.stdout:
            print(r.stdout[-3000:] + r.stderr[-1500:])
            print(f"FAILED in programs {lo}-{hi - 1} (exit code {r.returncode})")
            return 1
        _add(totals, r.stdout)
    if unicorn:
        totals["skipped: Unicorn misbehaves with the original too"] = len(unicorn)
    print("IDENTICAL: " + ", ".join(f"{v} {k}" for k, v in totals.items()))
    if unicorn:
        print("(Unicorn crashed or misread on programs " + ", ".join(map(str, sorted(unicorn)))
              + " with the original hwsim.py against itself as well)")
    return 0


def _add(totals, out):
    import re
    for n, k in re.findall(r"(\d+) ([a-z -]+?)(?:,|$)", out.split("IDENTICAL:", 1)[1].strip().splitlines()[0]):
        totals[k] = totals.get(k, 0) + int(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--programs", type=int, default=400)
    ap.add_argument("--ops", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--only", type=int, help="run just this program (the others are drawn, not run)")
    ap.add_argument("--trace", action="store_true", help="with --only: print each operation and what each side read")
    ap.add_argument("--range", help="START:STOP: run just these programs (the others are drawn, not run)")
    ap.add_argument("--batch", type=int, default=0,
                    help="run N programs per fresh process (Unicorn crashes after very many simulated DUOs in one)")
    a = ap.parse_args()
    if a.batch:
        return batches(a)
    lo, hi = (int(x) for x in a.range.split(":")) if a.range else (0, a.programs)
    if os.environ.get("DIFF_NOGC"):
        gc.disable()                     # experiments: no collection in the middle of emulation
    global CODE_BYTES, DONE
    enc, _ = Ks(KS_ARCH_ARM, KS_MODE_THUMB).asm(INTERP, CODE)
    CODE_BYTES = bytes(enc)
    DONE = CODE + len(CODE_BYTES) - 2
    old, new = load(a.old, "hwsim_old"), load(a.new, "hwsim_new")
    rng = random.Random(a.seed)
    fw = bytearray(random.Random(5).getrandbits(8) for _ in range(0x30000))
    send8, _ = Ks(KS_ARCH_ARM, KS_MODE_THUMB).asm(SEND8, F_USB_SEND8)
    fw[F_USB_SEND8 - ROM:F_USB_SEND8 - ROM + len(send8)] = bytes(send8)
    fw = bytes(fw)
    games = [old.make_game_rom(), old.make_game_rom(code=b"ZTST", size=0x1000, tag_at=0x800, seed=2),
             old.make_game_rom(code=b"AXVE", size=0x180000, rom_size=0x200000, seed=7),
             old.make_game_rom(code=b"BPGE", size=0x1000, tag_at=0x800, rom_size=0x200000, seed=3)]
    types = ["sanyo", "macronix", "flash512", "sram", "eeprom", "none"]
    samples = [0x100000, 0x180000, 0x1FFFFC0, 0x200000, 0xFFFFC0]
    counts = {"programs": 0, "ops": 0, "fails": 0, "violations": 0, "wakes": 0, "bank switches": 0, "id": 0,
              "corrupt views": 0, "link errors": 0, "re-run fresh": 0}
    for i in range(a.programs):
        game = games[i % len(games)]
        t = types[(i // len(games)) % len(types)]
        save = bytes(rng.getrandbits(8) for _ in range(rng.choice([0, 0x8000, 0x20000])))
        if os.environ.get("DIFF_PROGRESS"):
            print(f"starting program {i}", flush=True)
        chunks = [program(rng.__class__(rng.random()), a.ops) for _ in range(rng.randrange(1, 4))]
        pcs = [rng.random() for _ in chunks]
        if os.environ.get("DIFF_DUMP") and a.only == i:
            import json
            json.dump({"chunks": chunks, "pcs": pcs, "type": t, "game": i % len(games), "save": save.hex()},
                      open(os.environ["DIFF_DUMP"], "w"))
        if (a.only is not None and i != a.only) or not lo <= i < hi:
            continue
        hws = [make(m, fw, game, t, save) for m in (old, new)]
        outs = [[], []]
        for c, ops in enumerate(chunks):
            for j, hw in enumerate(hws):
                pc_side(hw, (old, new)[j], random.Random(pcs[c]))     # the PC speaks first
                outs[j].append(run(hw, ops))
            if hws[0].bad or hws[1].bad:
                break
        if a.trace:
            reads = [k for c in chunks for k in c if k[0] in (R8, R16, R32)]
            n = 0
            for c, ops in enumerate(chunks):
                for op in ops:
                    tag = "WRITE8 WRITE16 WRITE32 READ8 READ16 READ32 SEND".split()[op[0]]
                    line = f"chunk {c} {tag:7} {op[1]:#010x} {op[2]:#x}"
                    if op[0] in (R8, R16, R32):
                        vals = [struct.unpack_from("<I", outs[j][c], 4 * (n if c == 0 else 0))[0] for j in (0, 1)]
                        line += f"   old {vals[0]:#x}  new {vals[1]:#x}" + ("   <-- differs" if vals[0] != vals[1] else "")
                        n += 1
                    print(line)
            print("bad:", hws[0].bad, "|", hws[1].bad)
        s0, s1 = (snapshot(hw, samples) for hw in hws)
        if outs[0] != outs[1]:
            s0["reads"], s1["reads"] = outs
        differ = [k for k in s0 if s0[k] != s1[k]]
        if differ == ["reads"] and a.only is None:
            # Every byte of both simulators' memory agrees, but a CPU load disagreed: Unicorn's own
            # trouble late in a long process (the toolkit runs each test in its own process for
            # this). Run the program again in a fresh process before calling it a difference.
            import subprocess
            r = subprocess.run([sys.executable, __file__, a.old, a.new, "--programs", str(a.programs), "--ops", str(a.ops),
                                "--seed", str(a.seed), "--only", str(i)], capture_output=True, text=True)
            if r.returncode == 0 and "IDENTICAL" in r.stdout:
                counts["re-run fresh"] += 1
                differ = []
            elif original_crashes_too(a, i):
                counts["re-run fresh"] += 1          # Unicorn's trouble with the original too
                differ = []
        for k in differ:
            if True:
                print(f"DIFFERENT in program {i} ({t}, game {i % len(games)}): {k}")
                v0, v1 = s0[k], s1[k]
                if isinstance(v0, bytes):
                    d = next(x for x in range(min(len(v0), len(v1))) if v0[x] != v1[x]) if len(v0) == len(v1) else None
                    print(f"  first difference at {d:#x}" if d is not None else f"  lengths {len(v0)} / {len(v1)}")
                else:
                    print(f"  old: {v0!r}\n  new: {v1!r}")
                return 1
        if os.environ.get("DIFF_RSS") and i % 25 == 0:
            rss = int(open("/proc/self/statm").read().split()[1]) * os.sysconf("SC_PAGE_SIZE") >> 20
            print(f"program {i}: {rss} MB resident", flush=True)
        counts["programs"] += 1
        counts["ops"] += sum(len(c) for c in chunks)
        counts["fails"] += bool(s0["bad"])
        counts["violations"] += len(s0["violations"])
        counts["wakes"] += s0["awake"]
        counts["bank switches"] += s0["bank"]
        counts["id"] += s0["id_mode"]
        counts["corrupt views"] += (s0["mapped"] is not None and (s0["waitcnt"] >> 2) & 3 == 2)
        counts["link errors"] += len(s0["link_errors"])
        for hw in hws:
            hw.mu = None
        # A Unicorn instance is freed only by Python's cyclic collector, which can otherwise run in
        # the middle of another instance's emulation (inside a hook) and crash it. Free them here.
        del hws, s0, s1
        gc.collect()
    print("IDENTICAL: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
