"""Select SQLGlot tests and schedule them under the official worker cost."""

import argparse
import json
from pathlib import Path
import re
import sys

MAX_WORKERS = 8
WORKER_COST_MS = 2_000


def schedule(tests):
    ordered = sorted(tests, key=lambda test: (-round(test["seconds"] * 1000), test["number"]))
    best = []
    best_cost = None
    for count in range(1, min(MAX_WORKERS, len(ordered)) + 1):
        workers = [[] for _ in range(count)]
        loads = [0] * count
        for test in ordered:
            slot = min(range(count), key=lambda index: (loads[index], len(workers[index])))
            workers[slot].append(test["number"])
            loads[slot] += round(test["seconds"] * 1000)
        cost = max(loads) + WORKER_COST_MS * count
        if best_cost is None or cost < best_cost:
            best, best_cost = workers, cost
    return best


def select(patch, fixture_map, tests):
    """Use measured readers only for edits to existing, unchanged fixture paths."""
    blocks = re.split(r"(?m)(?=^diff --git )", patch)
    chosen = set()
    for block in blocks:
        if not block.strip():
            continue
        header, separator, _ = block.partition("\n@@ ")
        if not separator or not header.startswith("diff --git "):
            return tests
        lines = header.splitlines()
        if len(lines) != 4 or not lines[1].startswith("index "):
            return tests
        old, new = lines[2:]
        if not old.startswith("--- a/") or new != "+++ b/" + old[6:]:
            return tests
        readers = fixture_map.get(old[6:])
        if not readers:
            return tests
        chosen.update(readers)
    if not chosen:
        return tests
    selected = [test for test in tests if test["id"] in chosen]
    return selected if len(selected) == len(chosen) else tests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("/data"))
    parser.add_argument(
        "--fixture-map", type=Path, default=Path(__file__).with_name("fixtures-map.json")
    )
    args = parser.parse_args()
    tests = json.loads((args.data / "tests.json").read_text(encoding="utf-8"))["tests"]
    fixture_map = json.loads(args.fixture_map.read_text(encoding="utf-8"))
    full = schedule(tests)
    for patch in sorted((args.data / "commits").glob("*.patch")):
        selected = select(patch.read_text(encoding="utf-8"), fixture_map, tests)
        workers = full if selected is tests else schedule(selected)
        print(json.dumps({"commit": patch.stem, "workers": workers}, separators=(",", ":")))
    print("Scheduled fixture readers or the full suite for every patch", file=sys.stderr)


if __name__ == "__main__":
    main()
