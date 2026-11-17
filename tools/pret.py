"""The games' decompiled source (pret's pokeruby, pokeemerald, pokefirered), pinned, fetched on
demand for the simulator's source checks (tests/source_anchors.py) - not kept in this repository.

    python tools/pret.py            fetch (or update to the pinned commits) into the cache
    python tools/pret.py --where    print the cache's path

The cache is $PRET_DIR, else ~/.cache/pret. Sparse, blobless clones of src/ and include/ only.
Moving a pin: change PINS, run the source checks, fix what moved.
"""
import os
import subprocess
import sys

PINS = {
    "pokeruby": "5784633ce4ef7ade1a7f2d2d0c288e3d5e6cdd7f",
    "pokeemerald": "9103e529c2fbdd7add4a1ff3350c6c1f92112c42",
    "pokefirered": "ce6406d8c2eaf46d543c8a2606de0c3cb1951982",
}


def cache_dir():
    return os.environ.get("PRET_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "pret")


def have(repo):
    d = os.path.join(cache_dir(), repo)
    if not os.path.isdir(os.path.join(d, "src")):
        return False
    head = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    return head == PINS[repo]


def fetch(repo):
    d = os.path.join(cache_dir(), repo)
    os.makedirs(cache_dir(), exist_ok=True)
    git = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
    if not os.path.isdir(d):
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--sparse", "--no-checkout",
                        f"https://github.com/pret/{repo}.git", d], check=True)
        git("sparse-checkout", "set", "src", "include")
    git("fetch", "-q", "--depth", "1", "origin", PINS[repo])
    git("checkout", "-q", PINS[repo])


if __name__ == "__main__":
    if "--where" in sys.argv:
        print(cache_dir())
        sys.exit(0)
    for repo in PINS:
        if have(repo):
            print(f"{repo}: at {PINS[repo][:7]}")
        else:
            print(f"{repo}: fetching {PINS[repo][:7]}...")
            fetch(repo)
