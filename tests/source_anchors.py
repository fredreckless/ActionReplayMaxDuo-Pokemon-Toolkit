"""Checks every citation of the games' source in the simulator against the pinned pret source.

A citation is `pret:<repo>/<path>:<line> <Name>` (in a comment or docstring, in tests/ or virtual/).
It holds when line <line> of that file, at the pinned commit, names <Name>: a function's or a
macro's definition, usually. A citation that doesn't hold means the model claims to port something
the source doesn't say there - a wrong line, or a recollection passed off as a port.

Where the cited line defines a number (`#define NAME 4`) and the citing line gives that name a
number too (`NAME = 4`, or several names and numbers in a row), the numbers must agree as well: a
constant copied wrongly into both the model and the program is invisible to every other test
(the Union Room's trade activity, 18 November). Citations in firmware/programs/ count too.

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
    for path in sorted(glob.glob(os.path.join(ROOT, "tests", "*.py")) + glob.glob(os.path.join(ROOT, "virtual", "*.py"))
                       + glob.glob(os.path.join(ROOT, "firmware", "programs", "*.[ch]"))):
        if os.path.basename(path) == "source_anchors.py":
            continue
        for n, line in enumerate(open(path, encoding="utf-8"), 1):
            for m in CITE.finditer(line):
                yield os.path.relpath(path, ROOT), n, m.group(1), m.group(2), int(m.group(3)), m.group(4), line


DEFINE = re.compile(r"^\s*#define\s+(\w+)\s+\(?\s*(0x[0-9A-Fa-f]+|\d+)\s*\)?\s*(?:$|//|/\*)")
ENUM_ITEM = re.compile(r"^\s*(\w+)\s*(?:=\s*(0x[0-9A-Fa-f]+|\d+))?\s*,")


def defined_value(src, line, name):
    """The number the cited line gives `name`: a #define, or an item of an enum (counted from the
    enum's start, or from the last item given a number). None if it gives none."""
    m = DEFINE.match(src[line - 1])
    if m and m.group(1) == name:
        return int(m.group(2), 0)
    if not ENUM_ITEM.match(src[line - 1]) or ENUM_ITEM.match(src[line - 1]).group(1) != name:
        return None
    count = 0
    for k in range(line - 1, max(-1, line - 200), -1):
        text = src[k]
        if re.search(r"\benum\b", text) or text.strip() == "{" and k > 0 and re.search(r"\benum\b", src[k - 1]):
            return count - 1 if k != line - 1 else None
        item = ENUM_ITEM.match(text)
        if item and item.group(2) is not None:
            return int(item.group(2), 0) + count
        if item:
            count += 1
        elif text.strip() and not text.strip().startswith(("//", "/*", "*")) and text.strip() != "{":
            return None
    return None


def stated_value(citing_line, name):
    """The number the citing line gives `name` (Python `A, B = 1, 2` or `NAME = 4`), or None."""
    code = citing_line.split("#")[0] if not citing_line.lstrip().startswith("#define") else ""
    m = re.match(r"^\s*([A-Z][A-Z0-9_]*(?:\s*,\s*[A-Z][A-Z0-9_]*)*)\s*=\s*([^#]+)$", code.rstrip())
    if not m:
        return None
    names = [x.strip() for x in m.group(1).split(",")]
    values = [x.strip() for x in m.group(2).split(",")]
    if len(names) != len(values):
        return None
    for n, v in zip(names, values):
        if n == name or n.endswith("_" + name) or name.endswith(n):
            try:
                return int(v, 0)
            except ValueError:
                return None
    return None


def check(verbose=False):
    missing = [r for r in pret.PINS if not pret.have(r)]
    if missing:
        print(f"source anchors: SKIPPED - the pinned source isn't cached ({', '.join(missing)}); "
              "run python tools/pret.py")
        return True
    cache, bad, n = pret.cache_dir(), [], 0
    lines = {}
    for where, at, repo, path, line, name, citing in citations():
        n += 1
        key = (repo, path)
        if key not in lines:
            f = os.path.join(cache, repo, path)
            lines[key] = open(f, encoding="utf-8", errors="replace").read().split("\n") if os.path.exists(f) else None
        src = lines[key]
        text = src[line - 1] if src and 0 < line <= len(src) else None
        ok = text is not None and re.search(rf"\b{re.escape(name)}\b", text)
        if ok:
            want, said = defined_value(src, line, name), stated_value(citing, name)
            if want is not None and said is not None and want != said:
                ok = False
                text = f"{text.strip()}  (the source's value is {want}; the citing line says {said})"
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
