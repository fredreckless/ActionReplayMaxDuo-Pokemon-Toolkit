"""check.py - the Virtual DUO's own checks (the toolkit's push rule, for this folder).

    python3 check.py            build the core, fuzz it, and compare hwsim.py old and new
    python3 check.py --toolkit  also run the toolkit's `tests/check.py full` with the core in place

The toolkit is expected beside this folder (../actionreplaymaxduo-pokemon-toolkit, or the folder
TOOLKIT names). The comparison needs the original hwsim.py: ORIGINAL_HWSIM names it, or it is
taken from the toolkit's git history (origin/main).
"""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "core")
TESTS = os.path.join(HERE, "tests")
TOOLKIT = os.environ.get("TOOLKIT") or next(
    (p for p in (os.path.join(os.path.dirname(HERE), n) for n in ("actionreplaymaxduo-pokemon-toolkit", "ActionReplay"))
     if os.path.isdir(p)), None)


def step(name, cmd, cwd=HERE):
    print(f"== {name}", flush=True)
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode:
        print(f"FAILED: {name}")
        sys.exit(1)


def main():
    sys.path.insert(0, CORE)
    import duocore
    duocore.build()
    print(f"== built {duocore.LIBNAME}: {duocore.version()}")
    with tempfile.TemporaryDirectory() as tmp:
        exe = os.path.join(tmp, "fuzz_core")
        cc = os.environ.get("CC", "cc")
        step("fuzz the core (AddressSanitizer, UBSan)",
             [cc, "-std=c99", "-g", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
              "-I", CORE, os.path.join(TESTS, "fuzz_core.c"), os.path.join(CORE, "duocore.c"), "-o", exe])
        step("fuzz run", [exe, "200"])
        if not TOOLKIT:
            print("(no toolkit beside this folder: skipping the hwsim.py comparison)")
            return 0
        old = os.environ.get("ORIGINAL_HWSIM")
        if not old:
            old = os.path.join(tmp, "hwsim_original.py")
            src = subprocess.run(["git", "show", "origin/main:tests/hwsim.py"], cwd=TOOLKIT, capture_output=True)
            if src.returncode:
                print("(can't read the original hwsim.py from git: set ORIGINAL_HWSIM)")
                return 1
            open(old, "wb").write(src.stdout)
        step("hwsim.py: the original against the core (random bus programs)",
             [sys.executable, os.path.join(TESTS, "diff_hwsim.py"), old, os.path.join(TOOLKIT, "tests", "hwsim.py"),
              "--programs", "200"])
    if "--toolkit" in sys.argv:
        step("the toolkit's check.py full", [sys.executable, os.path.join("tests", "check.py"), "full"], cwd=TOOLKIT)
    print("ALL GOOD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
