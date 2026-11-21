"""Measure test coverage on an unmodified checkout of the official revision."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import coverage
import pytest

REVISION = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"


class TestContexts:
    def __init__(self, collector):
        self.collector = collector

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_protocol(self, item):
        self.collector.switch_context(item.nodeid)
        try:
            return (yield)
        finally:
            self.collector.switch_context("")


def verify_checkout(checkout):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    if revision != REVISION or subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=checkout
    ):
        raise SystemExit("Use a clean checkout of the official pinned revision")



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
    collector = coverage.Coverage(source=["sqlglot"], config_file=False, data_file=None)
    with collector.collect():
        status = pytest.main(
            ["-q", "tests", "--deselect=tests/dialects/test_sqlite.py::TestSQLite::test_variadic_iif_execution"],
            plugins=[TestContexts(collector)],
        )
    if status != pytest.ExitCode.OK:
        raise SystemExit("Coverage requires a passing baseline suite")

    data = collector.get_data()
    mapping = {}
    for filename in sorted(data.measured_files()):
        lines = {}
        contexts = set()
        for line, line_contexts in data.contexts_by_lineno(filename).items():
            ids = sorted(context for context in line_contexts if context)
            if ids:
                lines[str(line)] = ids
                contexts.update(ids)
        if contexts:
            relative = Path(filename).relative_to(checkout).as_posix()
            mapping[relative] = {"file": sorted(contexts), "lines": lines}
    output.write_text(json.dumps(mapping, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
