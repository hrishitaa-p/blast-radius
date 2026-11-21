"""Select SQLGlot tests and schedule them under the official worker cost."""

import argparse
import json
from pathlib import Path
import re
import sys

MAX_WORKERS = 8
WORKER_COST_MS = 2_000
PINNED = Path(__file__).with_name("pinned")
IMPORT_LINES = {}
# Imports SQLGlot in a child process, which coverage does not follow.
EAGER = set()
TEST_IMPORTS = {}
# Tests that created an instance of each class (or a subclass), by line range.
CLASS_USERS = {}
IMPORT_TESTS = {"tests/dialects/test_dialect.py::TestDialect::test_lazy_load"}
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


def patched_source(original, body):
    """Apply one file's hunks to the pinned source, or None if they do not fit."""
    old = original.split("\n")
    out = []
    cursor = 0
    lines = body.split("\n")
    index = 0
    while index < len(lines):
        match = HUNK.match(lines[index])
        index += 1
        if not match:
            if lines[index - 1].strip():
                return None
            continue
        start = int(match[1]) - 1 if int(match[1]) > 0 else 0
        if start < cursor:
            return None
        out.extend(old[cursor:start])
        cursor = start
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            index += 1
            if line.startswith("\\"):
                continue
            if line.startswith("+"):
                out.append(line[1:])
            elif line.startswith((" ", "-")) or line == "":
                if line == "" and (index == len(lines) or cursor >= len(old)):
                    continue
                if cursor >= len(old) or old[cursor] != line[1:]:
                    return None
                if not line.startswith("-"):
                    out.append(old[cursor])
                cursor += 1
            else:
                return None
    out.extend(old[cursor:])
    return "\n".join(out)


def compiles(path, body):
    """False when the patched module would fail to import with a syntax error."""
    source = PINNED / path
    if not source.is_file():
        return False
    patched = patched_source(source.read_text(encoding="utf-8"), body)
    if patched is None:
        return False
    try:
        compile(patched, path, "exec", dont_inherit=True)
    except (SyntaxError, ValueError):
        return False
    return True


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
        if path.startswith("tests/") and path.endswith(".py"):
            # A test-tree edit can only fail tests in that file or in test files
            # importing it. Package initializers load for every test below them.
            importers = TEST_IMPORTS.get(path)
            if importers is None or path.endswith("/__init__.py"):
                return tests
            chosen.update(test["id"] for test in tests if test["file"] in importers)
            continue
        mapping = source_map["files"].get(path)
        if mapping is None:
            return tests
        indices = set()
        groups = source_map["groups"]
        body = sep[1:] + rest
        if not compiles(path, body):
            # A syntax error fails every test whose file imports this module.
            return tests
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
        import_time = IMPORT_LINES.get(path, set())
        if mode == "line":
            for line in touched:
                function = next(
                    (span for span in mapping.get("functions", ()) if span[0] <= line <= span[2]),
                    None,
                )
                if function is None:
                    # Import-time code: its line coverage names only the first
                    # importer, so take every test that used the file.
                    indices.update(groups[mapping["file"]])
                    chosen.update(IMPORT_TESTS if path in EAGER else ())
                    # A class body (TRANSFORMS, KEYWORDS, flags) is read by
                    # every test that used the class, even one that never ran
                    # a function in this file.
                    for start, stop, users in CLASS_USERS.get(path, ()):
                        if start <= line <= stop:
                            chosen.update(users)
                    continue
                if line < function[1]:
                    # Signature or decorator: it affects every caller.
                    indices.update(groups[function[3] if function[3] is not None else mapping["file"]])
                    chosen.update(IMPORT_TESTS if path in EAGER else ())
                    continue
                if line in import_time:
                    # A function body that runs while some module loads.
                    indices.update(groups[mapping["file"]])
                    chosen.update(IMPORT_TESTS if path in EAGER else ())
                direct = mapping["lines"].get(str(line))
                if direct is not None:
                    indices.update(groups[direct])
                # A short-circuited operand on its own line has no coverage of
                # its own, so take every test that ran the whole statement.
                statement = next(
                    (key for start, stop, key in mapping.get("statements", ()) if start <= line <= stop),
                    None,
                )
                if statement is not None:
                    indices.update(groups[statement])
        if mode == "scope" or (mode == "line" and not indices):
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
    imports = json.loads(Path(__file__).with_name("import-lines.json").read_text(encoding="utf-8"))
    IMPORT_LINES.update((path, set(lines)) for path, lines in imports["lines"].items())
    EAGER.update(imports["eager"])
    TEST_IMPORTS.update(json.loads(Path(__file__).with_name("test-imports.json").read_text(encoding="utf-8")))
    classes = json.loads(Path(__file__).with_name("class-map.json").read_text(encoding="utf-8"))
    CLASS_USERS.update(
        (path, [(start, stop, {classes["ids"][number] for number in users}) for start, stop, users in ranges])
        for path, ranges in classes["files"].items()
    )
    full = schedule(tests)
    for patch in sorted((args.data / "commits").glob("*.patch")):
        selected = select(patch.read_text(encoding="utf-8"), fixture_map, source_map, tests, args.mode)
        workers = full if selected is tests else schedule(selected)
        print(json.dumps({"commit": patch.stem, "workers": workers}, separators=(",", ":")))
    print("Scheduled baseline coverage, fixture readers, or the full suite", file=sys.stderr)


if __name__ == "__main__":
    main()
