"""Compile reusable coverage groups from the pinned SQLGlot baseline."""

import argparse
import ast
from collections import defaultdict
import json
import tokenize
from pathlib import Path

from build_coverage import verify_checkout


def scope_ranges(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sorted(
        (
            (min([node.lineno, *(item.lineno for item in node.decorator_list)]), node.end_lineno)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        key=lambda pair: (pair[1] - pair[0], pair),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("coverage", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--worker-coverage", type=Path)
    args = parser.parse_args()
    verify_checkout(args.checkout)
    coverage = json.loads(args.coverage.read_text())
    if args.worker_coverage:
        supplemental = json.loads(args.worker_coverage.read_text())
        for path, mapping in supplemental.items():
            base = coverage.setdefault(path, {"file": [], "lines": {}})
            base["file"] = sorted(set(base["file"]).union(mapping["file"]))
            for line, names in mapping["lines"].items():
                base["lines"][line] = sorted(set(base["lines"].get(line, ())).union(names))
    ids = {}
    groups = {}

    def group(names):
        key = tuple(sorted(ids.setdefault(name, len(ids)) for name in sorted(set(names))))
        return groups.setdefault(key, len(groups))

    # Changes to class/module constants may only execute at import. Attribute
    # reads recorded under tests reveal users of those definitions.
    references = defaultdict(set)
    definitions = defaultdict(list)
    for path, mapping in coverage.items():
        tree = ast.parse((args.checkout / path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                references[node.attr].update(mapping["lines"].get(str(node.lineno), ()))
            if isinstance(node, (ast.ClassDef, ast.Module)):
                for statement in node.body:
                    if isinstance(statement, ast.Assign):
                        targets = statement.targets
                    elif isinstance(statement, ast.AnnAssign):
                        targets = [statement.target]
                    else:
                        continue
                    if not isinstance(statement.value, (ast.Constant, ast.UnaryOp)):
                        continue
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id.isupper():
                            definitions[path].append((statement.lineno, statement.end_lineno, target.id))

    files = {}
    for path, mapping in coverage.items():
        line_hits = {int(line): names for line, names in mapping["lines"].items()}
        tree = ast.parse((args.checkout / path).read_text(encoding="utf-8"))
        recursive = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == node.name
                for child in ast.walk(node)
            ):
                recursive.append([node.lineno, node.end_lineno])
        with tokenize.open(args.checkout / path) as source:
            tokens = list(tokenize.generate_tokens(source.readline))
        multiline = [[token.start[0], token.end[0]] for token in tokens if token.start[0] < token.end[0]]
        scopes = []
        for start, stop in scope_ranges(args.checkout / path):
            names = {name for line in range(start, stop + 1) for name in line_hits.get(line, ())}
            if names:
                scopes.append([start, stop, group(names)])
        files[path] = {
            "file": group(mapping["file"]),
            "lines": {line: group(names) for line, names in line_hits.items()},
            "scopes": scopes,
            "recursive": recursive,
            "multiline": multiline,
            "attributes": [
                [start, stop, group(references[name])]
                for start, stop, name in definitions[path] if references[name]
            ],
        }
    source_tests = []
    source_apis = {"read_text", "read_bytes", "getsource", "getsourcelines", "co_firstlineno"}
    for path in (args.checkout / "tests").rglob("test_*.py"):
        module = path.relative_to(args.checkout).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.Attribute) and node.attr in source_apis for node in ast.walk(tree)):
            source_tests.append(module)
    data = {
        "ids": list(ids),
        "groups": list(groups),
        "files": files,
        "source_tests": sorted(source_tests),
    }
    args.output.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
