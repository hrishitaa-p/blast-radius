"""Map each pinned SQLGlot test-tree module to the test files that import it.

An edit to a test file can only fail tests defined in that file or in test
files that import it, directly or through other test modules.
"""

import argparse
import ast
from collections import defaultdict
import json
from pathlib import Path

from build_coverage import verify_checkout


def module_path(checkout, name):
    base = checkout / Path(*name.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate.relative_to(checkout).as_posix()
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    verify_checkout(checkout)
    imported_by = defaultdict(set)
    files = sorted(path.relative_to(checkout).as_posix() for path in (checkout / "tests").rglob("*.py"))
    for path in files:
        tree = ast.parse((checkout / path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level:
                raise SystemExit(f"Relative import in {path}; extend this map")
            for name in names:
                if name.split(".")[0] == "tests":
                    target = module_path(checkout, name)
                    if target and target != path:
                        imported_by[target].add(path)
    affected = {}
    for path in files:
        seen, stack = {path}, [path]
        while stack:
            for importer in imported_by.get(stack.pop(), ()):
                if importer not in seen:
                    seen.add(importer)
                    stack.append(importer)
        affected[path] = sorted(seen)
    args.output.write_text(json.dumps(affected, sort_keys=True, indent=0), encoding="utf-8")


if __name__ == "__main__":
    main()
