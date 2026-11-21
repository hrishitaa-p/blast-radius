"""Record the lines of the pinned SQLGlot checkout that run while importing it.

Coverage contexts credit import-time execution to whichever test first imported
a lazily loaded module, so these lines need wider selection than their own
line coverage.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from build_coverage import verify_checkout

PROBE = r"""
import importlib, json, pkgutil, sys
import coverage
collector = coverage.Coverage(source=["sqlglot"], config_file=False, data_file=None)
collector.start()
import sqlglot
eager = sorted(getattr(module, "__file__", None) or "" for name, module in list(sys.modules.items()) if name.split(".")[0] == "sqlglot")
for module in pkgutil.walk_packages(sqlglot.__path__, "sqlglot."):
    try:
        importlib.import_module(module.name)
    except Exception as error:
        print(module.name, error, file=sys.stderr)
for dialect in sqlglot.dialects.Dialects:
    sqlglot.Dialect.get_or_raise(dialect.value)
collector.stop()
data = collector.get_data()
print(json.dumps({"eager": [name for name in eager if name], "lines": {name: sorted(data.lines(name) or ()) for name in data.measured_files()}}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    verify_checkout(checkout)
    result = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=checkout, capture_output=True, text=True, check=True,
    )
    sys.stderr.write(result.stderr)
    probe = json.loads(result.stdout)
    relative = lambda name: Path(name).resolve().relative_to(checkout).as_posix()
    output = {
        # Modules a bare "import sqlglot" loads, which a child-process test checks.
        "eager": sorted(relative(name) for name in probe["eager"]),
        "lines": {relative(name): found for name, found in probe["lines"].items()},
    }
    args.output.write_text(json.dumps(output, sort_keys=True, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
