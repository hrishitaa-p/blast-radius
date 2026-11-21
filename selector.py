"""Select SQLGlot tests and schedule them under the official worker cost."""

import argparse
import json
from pathlib import Path
import re
import sys

MAX_WORKERS = 8
WORKER_COST_MS = 2_000
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")


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


def changed_lines(body):
    cursor = None
    lines = set()
    deleted = False
    added_at = []
    for line in body.split("\n") + [" "]:
        match = HUNK.match(line)
        if line.startswith("-") and cursor is not None:
            lines.add(cursor)
            cursor += 1
            deleted = True
        elif line.startswith("+") and cursor is not None:
            added_at.append(cursor)
        else:
            if not deleted:
                for anchor in added_at:
                    lines.update((max(anchor - 1, 1), anchor))
            deleted = False
            added_at.clear()
            if match:
                cursor = int(match[1])
            elif cursor is not None and line.startswith(" "):
                cursor += 1
    return lines


def select(patch, fixture_map, source_map, tests, mode):
    blocks = re.split(r"(?m)(?=^diff --git )", patch)
    chosen = set()
    for block in blocks:
        if not block.strip():
            continue
        header, sep, rest = block.partition("\n@@ ")
        if not sep or not header.startswith("diff --git "):
            return tests
        lines = header.splitlines()
        if len(lines) != 4 or not lines[1].startswith("index "):
            return tests
        old, new = lines[2:]
        if not old.startswith("--- a/") or new != "+++ b/" + old[6:]:
            return tests
        path = old[6:]
        if path in fixture_map:
            chosen.update(fixture_map[path])
            continue
        mapping = source_map["files"].get(path)
        if mapping is None:
            return tests
        indices = set()
        groups = source_map["groups"]
        body = sep[1:] + rest
        touched = changed_lines(body)
        additions = [line[1:] for line in body.split("\n") if line.startswith("+")]
        removed = any(line.startswith("-") for line in body.split("\n"))
        if (
            not removed and additions
            and all(re.fullmatch(r"[ ]*# [A-Z][A-Za-z0-9 ,.'!?-]*", line) for line in additions)
            and min(touched, default=0) > 2
            and not any(start <= line <= stop for start, stop in mapping["multiline"] for line in touched)
        ):
            chosen.update(test["id"] for test in tests if test["file"] in source_map["source_tests"])
            continue
        if any(start <= line <= stop for start, stop in mapping["recursive"] for line in touched):
            chosen.update(source_map["ids"][index] for index in groups[mapping["file"]])
            continue
        for start, stop, key in mapping.get("attributes", ()):
            if any(start <= line <= stop for line in touched):
                indices.update(groups[key])
        boolean_lines = [
            line[1:] for line in body.split("\n") if line.startswith(("+", "-"))
        ]
        scope_required = mode == "scope" or (
            mode == "line" and any(re.search(r"\b(?:and|or|not)\b", line) for line in boolean_lines)
        )
        if mode == "line" and not scope_required:
            for line in touched:
                direct = mapping["lines"].get(str(line))
                if direct is not None:
                    indices.update(groups[direct])
        if scope_required or (mode == "line" and not indices):
            for line in touched:
                scope = next((key for start, stop, key in mapping["scopes"] if start <= line <= stop), None)
                if scope is not None:
                    indices.update(groups[scope])
        if not indices:
            indices.update(groups[mapping["file"]])
        chosen.update(source_map["ids"][index] for index in indices)
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
    parser.add_argument("--source-map", type=Path, default=Path(__file__).with_name("coverage-map.json"))
    parser.add_argument("--mode", choices=("line", "scope", "file"), default="line")
    args = parser.parse_args()
    tests = json.loads((args.data / "tests.json").read_text(encoding="utf-8"))["tests"]
    fixture_map = json.loads(args.fixture_map.read_text(encoding="utf-8"))
    source_map = json.loads(args.source_map.read_text(encoding="utf-8"))
    full = schedule(tests)
    for patch in sorted((args.data / "commits").glob("*.patch")):
        selected = select(patch.read_text(encoding="utf-8"), fixture_map, source_map, tests, args.mode)
        workers = full if selected is tests else schedule(selected)
        print(json.dumps({"commit": patch.stem, "workers": workers}, separators=(",", ":")))
    print("Scheduled baseline coverage, fixture readers, or the full suite", file=sys.stderr)


if __name__ == "__main__":
    main()
