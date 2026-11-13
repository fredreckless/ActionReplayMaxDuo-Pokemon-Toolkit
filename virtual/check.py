"""check.py - the Virtual DUO's own checks.

    python3 virtual/check.py            build the core, fuzz it, and compare the toolkit's hwsim.py
                                        (built on the core since 13 November) with the old Python one
    python3 virtual/check.py --toolkit  also run the toolkit's `tests/check.py full`

The old, pure-Python hwsim.py is kept as tests/hwsim_python.py, frozen as it was when the core
went behind the toolkit's: the comparison shows the two still agree, except where the core is
deliberately more faithful (see the README).
"""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "core")
TESTS = os.path.join(HERE, "tests")
TOOLKIT = os.environ.get("TOOLKIT") or os.path.dirname(HERE)


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
        old = os.path.join(TESTS, "hwsim_python.py")
        new = os.path.join(TOOLKIT, "tests", "hwsim.py")
        step("hwsim.py: the old Python one against the core (random bus programs)",
             [sys.executable, os.path.join(TESTS, "diff_hwsim.py"), old, new, "--programs", "200", "--batch", "50"])
    if "--toolkit" in sys.argv:
        step("the toolkit's check.py full", [sys.executable, os.path.join("tests", "check.py"), "full"], cwd=TOOLKIT)
    print("ALL GOOD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
