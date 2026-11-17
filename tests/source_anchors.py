"""Checks every citation of the games' source in the simulator against the pinned pret source.

A citation is `pret:<repo>/<path>:<line> <Name>` (in a comment or docstring, in tests/ or virtual/).
It holds when line <line> of that file, at the pinned commit, names <Name>: a function's or a
macro's definition, usually. A citation that doesn't hold means the model claims to port something
the source doesn't say there - a wrong line, or a recollection passed off as a port.

    python tests/source_anchors.py          check all; exit 1 if any fail
    python tests/source_anchors.py --list   also list each citation and the line it points at

Without the source cached (python tools/pret.py) it says so and exits 0: the check is skipped, not
passed.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pret  # noqa: E402

CITE = re.compile(r"pret:(pokeruby|pokeemerald|pokefirered)/([\w./-]+):(\d+) (\w+)")


def citations():
    for path in sorted(glob.glob(os.path.join(ROOT, "tests", "*.py")) + glob.glob(os.path.join(ROOT, "virtual", "*.py"))):
        if os.path.basename(path) == "source_anchors.py":
            continue
        for n, line in enumerate(open(path, encoding="utf-8"), 1):
            for m in CITE.finditer(line):
                yield os.path.relpath(path, ROOT), n, m.group(1), m.group(2), int(m.group(3)), m.group(4)


def check(verbose=False):
    missing = [r for r in pret.PINS if not pret.have(r)]
    if missing:
        print(f"source anchors: SKIPPED - the pinned source isn't cached ({', '.join(missing)}); "
              "run python tools/pret.py")
        return True
    cache, bad, n = pret.cache_dir(), [], 0
    lines = {}
    for where, at, repo, path, line, name in citations():
        n += 1
        key = (repo, path)
        if key not in lines:
            f = os.path.join(cache, repo, path)
            lines[key] = open(f, encoding="utf-8", errors="replace").read().split("\n") if os.path.exists(f) else None
        src = lines[key]
        text = src[line - 1] if src and 0 < line <= len(src) else None
        ok = text is not None and re.search(rf"\b{re.escape(name)}\b", text)
        if verbose:
            print(f"  {'ok ' if ok else 'BAD'} {where}:{at}  {repo}/{path}:{line} {name}  | {(text or '(no such line)').strip()[:70]}")
        if not ok:
            bad.append((where, at, repo, path, line, name, text))
    for where, at, repo, path, line, name, text in bad:
        print(f"source anchors: {where}:{at} cites {repo}/{path}:{line} {name}, but that line is: "
              f"{(text or '(no such line or file)').strip()[:90]}")
    print(f"source anchors: {n - len(bad)} of {n} citations hold (pret pinned: "
          + ", ".join(f"{r} {c[:7]}" for r, c in pret.PINS.items()) + ")")
    return not bad


if __name__ == "__main__":
    sys.exit(0 if check("--list" in sys.argv) else 1)
