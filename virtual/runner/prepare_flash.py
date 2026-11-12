"""prepare_flash.py - make the Virtual DUO's flash image, once, from the built firmware.

    python3 virtual/runner/prepare_flash.py [firmware/build/fw_v42.bin] [OUT.bin]

Datel's start-up formats its codes database in flash when it is blank, and while it is blank it
skips the USB boot check: so a DUO straight from the firmware build never answers the PC. This boots
it once, lets it format (a few seconds of its time; the counts below stop changing), and keeps the
result. Pass that image as --duo-fw / --duo-flash from then on.

The image is Datel's firmware plus a formatted database: like the firmware, never commit it. The
default output, firmware/build/duo_flash.bin, sits in the git-ignored build folder for that reason.
"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from vduo import Runner  # noqa: E402


def main():
    fw = sys.argv[1] if len(sys.argv) > 1 else os.path.join(TOP, "firmware", "build", "fw_v42.bin")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(TOP, "firmware", "build", "duo_flash.bin")
    if not os.path.exists(fw):
        sys.exit(f"{fw} isn't there: build the firmware first (python3 firmware/build_firmware.py DATEL_FILE --all)")
    with Runner(duo_fw=fw) as v:
        last, steady = None, 0
        for _ in range(40):                              # up to 12,000 frames; it takes about 300
            v.run_frames("duo", 300)
            s = v.status()
            now = (s["flash_programs"], s["flash_erases"])
            steady = steady + 1 if now == last and int(now[1]) else 0
            last = now
            if steady >= 2:
                break
        else:
            sys.exit(f"the DUO never settled: {s}")
        if int(s["bad"]) or int(s["violations"]):
            sys.exit(f"the DUO misbehaved while formatting: {s}")
        v.save_flash(out)
    print(f"formatted: {last[0]} words programmed, {last[1]} erases; kept as {out}")


if __name__ == "__main__":
    main()
