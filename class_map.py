"""Compile class_usage.py's output into per-file class line ranges.

Each entry is [start, stop, [test ids]] for a class whose instances (or a
subclass's) some test created. selector.py adds these tests when an edit
lands in a class body outside any function, where line coverage names only
the first importer.

    python3 class_map.py /path/to/sqlglot class-usage.json class-map.json
"""

import argparse
import ast
import json
from pathlib import Path

from build_coverage import verify_checkout


def module_name(path):
    parts = Path(path).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("usage", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    verify_checkout(args.checkout)
    usage = json.loads(args.usage.read_text(encoding="utf-8"))
    ids = sorted({name for names in usage.values() for name in names})
    index = {name: number for number, name in enumerate(ids)}
    files = {}
    for source in sorted((args.checkout / "sqlglot").rglob("*.py")):
        path = source.relative_to(args.checkout).as_posix()
        module = module_name(path)
        ranges = []

        def visit(node, prefix):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    qualname = prefix + child.name
                    start = min([child.lineno, *(item.lineno for item in child.decorator_list)])
                    names = usage.get(f"{module}:{qualname}")
                    if names:
                        ranges.append([start, child.end_lineno, sorted(index[name] for name in names)])
                    visit(child, qualname + ".")

        visit(ast.parse(source.read_text(encoding="utf-8")), "")
        if ranges:
            files[path] = ranges
    args.output.write_text(json.dumps({"ids": ids, "files": files}, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
