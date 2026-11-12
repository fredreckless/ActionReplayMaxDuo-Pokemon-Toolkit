"""check.py - the Virtual DUO's own checks.

    python3 virtual/check.py            build the core, fuzz it, and compare hwsim.py old and new
    python3 virtual/check.py --toolkit  also run the toolkit's `tests/check.py full` with the core
                                        behind hwsim.py (in a scratch copy of the repository)

This folder lives in the toolkit's repository as virtual/. The toolkit's own tests/hwsim.py is the
original; the one built on the core is that file with toolkit/hwsim.patch applied, made in a
scratch folder: the toolkit itself isn't changed until that decision is taken.
"""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "core")
TESTS = os.path.join(HERE, "tests")
TOOLKIT = os.environ.get("TOOLKIT") or os.path.dirname(HERE)


def patched_hwsim(tmp):
    """The toolkit's hwsim.py with the core behind it, in a scratch folder."""
    d = os.path.join(tmp, "tests")
    os.makedirs(d, exist_ok=True)
    shutil.copy(os.path.join(TOOLKIT, "tests", "hwsim.py"), d)
    r = subprocess.run(["git", "apply", os.path.join(HERE, "toolkit", "hwsim.patch")],
                       cwd=tmp, capture_output=True, text=True)
    if r.returncode:
        print("toolkit/hwsim.patch no longer applies to tests/hwsim.py:\n" + r.stderr)
        sys.exit(1)
    return os.path.join(d, "hwsim.py")


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
        old = os.environ.get("ORIGINAL_HWSIM") or os.path.join(TOOLKIT, "tests", "hwsim.py")
        new = patched_hwsim(tmp)
        os.environ["VIRTUAL_DUO_CORE"] = CORE
        step("hwsim.py: the original against the core (random bus programs)",
             [sys.executable, os.path.join(TESTS, "diff_hwsim.py"), old, new, "--programs", "200", "--batch", "50"])
    if "--toolkit" in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "toolkit")
            shutil.copytree(TOOLKIT, copy, ignore=shutil.ignore_patterns(".git", "third_party", "build", "received",
                                                                         "battles", "records", "logs"))
            shutil.copytree(os.path.join(TOOLKIT, "firmware", "build"), os.path.join(copy, "firmware", "build"),
                            dirs_exist_ok=True)
            shutil.copy(patched_hwsim(tmp), os.path.join(copy, "tests", "hwsim.py"))
            os.environ["VIRTUAL_DUO_CORE"] = CORE
            step("the toolkit's check.py full, the core behind hwsim.py",
                 [sys.executable, os.path.join("tests", "check.py"), "full"], cwd=copy)
    print("ALL GOOD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
