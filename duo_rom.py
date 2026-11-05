"""Copy the GBA cartridge in the Action Replay MAX DUO to a ROM file on this PC (read-only).

    python duo_rom.py                  the cartridge's whole ROM, into a 'roms' folder beside the tools
    python duo_rom.py --out FOLDER     somewhere else

Made for the Secret Base Workshop (secret_base_workshop.html), which reads the game's own room
tiles and decorations from your ROM in your browser, so the toolkit itself never carries any of the
game's art. Like maxduo_saves.py it only reads: the cartridge is mapped in, 64 KB at a time is read
and checked against the GBA's own CRC of the same bytes, and the DUO is put back as it was.

One difference from a dump made with a cartridge reader: the DUO's own chip covers 0x20-0x9F of the
cartridge header (part of the start-up logo), so those bytes read as zeros here. Nothing the
workshop uses is there, and maxduo_saves.py --cart-report still gives the real whole-ROM checksum.
Needs the Reckless firmware (v3.1 or later) and the GBA in USB SERVER MODE. Keep the ROM to
yourself: it's your cartridge's, and not for sharing."""
import argparse, os, sys, time, zlib

import maxduo_saves as M
from maxduo_saves import DuoError, Lab, MaxDuo, UsbTransport, MAP_REG

CHUNK = 0x10000
DUO_MAP = 0x0120                         # the DUO's own mapping, put back after every read


def wake(mapping):
    return [("w16", MAP_REG, mapping), ("delay", 0, 0x400), ("r16", 0x08000000, 2)]


def read_header(lab, mapping):
    """(header info, ROM size) of the cartridge, as maxduo_saves.py reads them."""
    for attempt in range(3):
        res = lab.run(wake(mapping) + [("r8", 0x08000000, 32), ("r8", 0x080000A0, 32)] + M.rom_size_ops()
                      + [("w16", MAP_REG, DUO_MAP)], messages=["ROM copy: reading header"])
        d = [x for _, x in res]
        info = M.describe_header(d[2])
        if info["header_ok"]:
            return info, M.rom_size_from(d[3:-1])
        print(f"  The header's checksum doesn't match ({d[2].hex(' ')}); reading it again...")
    raise DuoError("the cartridge's header never read cleanly: check it's seated in the DUO")


def read_chunk(lab, mapping, addr):
    ops = wake(mapping) + [("r8", addr, CHUNK), ("crct", addr, CHUNK), ("w16", MAP_REG, DUO_MAP)]
    for attempt in range(3):
        res = lab.run(ops)
        data, gba_crc = res[-2][1], M._w(res[-1][1])
        if zlib.crc32(data) == gba_crc:
            return data
        print(f"\n  The GBA's own checksum of {addr:#010x} disagreed; reading it again...")
    raise DuoError(f"the ROM at {addr:#010x} read differently three times: check the cartridge's contacts")


def dump(duo, args):
    lab = Lab(duo)
    mapping = getattr(args, "map", None) or 0x0101
    info, size = read_header(lab, mapping)
    size = min(size, M.MAX_ROM_READ)
    print(f"  Game: {info['title']} ({info['code']}, revision {info['revision']}), {size >> 20} MB")
    out = getattr(args, "out", None) or os.path.join(os.path.dirname(os.path.abspath(__file__)), "roms")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, M.safe_filename(f"{info['title']} ({info['code']}) rev {info['revision']}") + ".gba")
    t0, parts = time.time(), []
    for k, addr in enumerate(range(0x08000000, 0x08000000 + size, CHUNK)):
        parts.append(read_chunk(lab, mapping, addr))
        done = (k + 1) * CHUNK
        rate = done / max(time.time() - t0, 0.01)
        filled = 30 * done // size
        sys.stdout.write(f"\r    [{'#' * filled}{'.' * (30 - filled)}] {done >> 10:,} of {size >> 10:,} KB"
                         f"  (about {max(0, (size - done) / rate):.0f} s left)   ")
        sys.stdout.flush()
    print()
    data = b"".join(parts)
    with open(path, "wb") as f:
        f.write(data)
    if lab.v3:
        lab.run([], messages=["ROM copied to PC", f"{size >> 20} MB, CRC {zlib.crc32(data):08X}"])
    print(f"Saved: {path}\n  ({len(data):,} bytes in {time.time() - t0:.0f} s; header bytes 0x20-0x9F read as zeros "
          "through the DUO)")
    print("  Open secret_base_workshop.html and choose 'Use my ROM's graphics' to load it.")
    return path, data, info


def main(argv=None):
    ap = argparse.ArgumentParser(prog="duo_rom.py", description="Copy the GBA cartridge in the DUO to a ROM file (read-only).")
    ap.add_argument("--out", metavar="FOLDER", help="where to save it (default: a 'roms' folder beside this tool)")
    ap.add_argument("--map", type=lambda v: int(v, 0), default=None, help="cartridge mapping (default 0x101, as for saves)")
    ap.add_argument("--wait", type=int, default=120, help="seconds to wait for the GBA to be switched on (default 120)")
    args = ap.parse_args(argv)
    t = UsbTransport()
    try:
        duo = MaxDuo(t)
        version = duo.connect(wait_s=args.wait)
        print(f"Connected to Action Replay MAX DUO (Datel protocol {version >> 8}.{version & 0xFF:02d})")
        if not duo.is_v3():
            raise DuoError("copying a ROM needs the Reckless firmware (v3.1 or later)")
        print("Copying the cartridge's ROM (reads only)...")
        dump(duo, args)
    except DuoError as err:
        sys.exit(f"\nStopped: {err}")
    except Exception as err:
        if type(err).__name__ in ("USBTimeoutError", "USBError"):
            sys.exit(f"\nThe Action Replay stopped answering ({err}).\n"
                     "Check the console batteries and that USB SERVER MODE is still showing.")
        raise
    finally:
        t.close()


if __name__ == "__main__":
    main()
