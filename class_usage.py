"""Record which sqlglot classes each test instantiates, on the pinned checkout.

Class bodies (TRANSFORMS, FUNCTIONS, KEYWORDS, flags, arg_types) run once at
import, so line coverage cannot say which tests depend on them. A test that
creates an instance of a class, or of any subclass, reads its class body.
This wraps every ``__init__`` defined in sqlglot and records the instance's
type for the running test, then maps each class to its users through the MRO.

    python3 class_usage.py /path/to/sqlglot class-usage.json
"""

import argparse
from collections import defaultdict
import functools
import importlib
import json
import os
from pathlib import Path
import pkgutil
import sys

import pytest

from build_coverage import verify_checkout


class Recorder:
    def __init__(self):
        self.node = None
        self.seen = defaultdict(set)

    def wrap(self, cls):
        original = cls.__dict__["__init__"]
        seen, recorder = self.seen, self

        @functools.wraps(original)
        def __init__(obj, *args, **kwargs):
            if recorder.node is not None:
                seen[type(obj)].add(recorder.node)
            return original(obj, *args, **kwargs)

        cls.__init__ = __init__

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_protocol(self, item):
        self.node = item.nodeid
        try:
            return (yield)
        finally:
            self.node = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    output = args.output.resolve()
    verify_checkout(checkout)
    os.chdir(checkout)
    sys.path.insert(0, str(checkout))

    import sqlglot

    for info in pkgutil.walk_packages(sqlglot.__path__, prefix="sqlglot."):
        if info.name != "sqlglot.__main__":
            try:
                importlib.import_module(info.name)
            except Exception:
                pass
    recorder = Recorder()
    wrapped = 0
    for module in list(sys.modules.values()):
        if not getattr(module, "__name__", "").startswith("sqlglot"):
            continue
        for value in list(vars(module).values()):
            stack = [value]
            while stack:
                cls = stack.pop()
                if not isinstance(cls, type) or not cls.__module__.startswith("sqlglot"):
                    continue
                stack.extend(v for v in vars(cls).values() if isinstance(v, type))
                init = cls.__dict__.get("__init__")
                if callable(init) and not getattr(init, "__wrapped__", None) and hasattr(init, "__code__"):
                    try:
                        recorder.wrap(cls)
                        wrapped += 1
                    except (TypeError, AttributeError):
                        pass
    print(f"wrapped {wrapped} __init__ methods", file=sys.stderr)
    status = pytest.main(
        ["-q", "-p", "no:cacheprovider", "tests",
         "--deselect=tests/dialects/test_sqlite.py::TestSQLite::test_variadic_iif_execution"],
        plugins=[recorder],
    )
    if status != pytest.ExitCode.OK:
        raise SystemExit("Class usage requires a passing baseline suite")

    users = defaultdict(set)
    for cls, nodes in recorder.seen.items():
        for base in cls.__mro__:
            if base.__module__.startswith("sqlglot"):
                users[f"{base.__module__}:{base.__qualname__}"].update(nodes)
    output.write_text(
        json.dumps({key: sorted(nodes) for key, nodes in sorted(users.items())}, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
