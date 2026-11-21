"""Select SQLGlot tests and schedule them under the official worker cost."""

import argparse
import json
from pathlib import Path
import re
import sys

MAX_WORKERS = 8
WORKER_COST_MS = 2_000
HEAD = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")


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


def changes(patch):
    """Yield original source paths and line numbers touched by a unified diff."""
    current = None
    old_line = None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            current = None
            old_line = None
        elif old_line is not None:
            prefix = line[:1]
            if prefix == "-":
                yield current, old_line
                old_line += 1
            elif prefix == "+":
                yield current, old_line
                if old_line > 1:
                    yield current, old_line - 1
            elif prefix == " ":
                old_line += 1
            elif not line.startswith("\\"):
                old_line = None
                if line.startswith("@@"):
                    match = HEAD.match(line)
                    if match:
                        old_line = int(match[1])
        elif line.startswith("--- "):
            original = line[4:].split("\t", 1)[0]
            current = original[2:] if original.startswith("a/") else None
        elif line.startswith("@@"):
            match = HEAD.match(line)
            if match:
                old_line = int(match[1])


def select(patch, maps, tests):
    # An unmapped file or unsupported diff gets the complete suite.
    files = {}
    for path, line in changes(patch):
        if path not in maps:
            return tests
        files.setdefault(path, set()).add(str(line))
    if not files:
        return tests
    chosen = set()
    for path, lines in files.items():
        mapping = maps[path]
        hits = {test for line in lines for test in mapping["lines"].get(line, ())}
        chosen.update(hits or mapping["file"])
    return [test for test in tests if test["id"] in chosen] if chosen else tests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("/data"))
    parser.add_argument("--coverage-map", type=Path)
    args = parser.parse_args()
    tests = json.loads((args.data / "tests.json").read_text())["tests"]
    maps = json.loads(args.coverage_map.read_text()) if args.coverage_map else {}
    full = schedule(tests)
    for patch in sorted((args.data / "commits").glob("*.patch")):
        selected = select(patch.read_text(encoding="utf-8"), maps, tests) if maps else tests
        workers = full if selected is tests else schedule(selected)
        print(json.dumps({"commit": patch.stem, "workers": workers}, separators=(",", ":")))
    print("Coverage map enabled" if maps else "All-tests scheduling baseline", file=sys.stderr)


if __name__ == "__main__":
    main()
