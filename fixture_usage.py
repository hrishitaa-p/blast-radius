"""Record pytest node IDs that read fixtures on the pinned checkout."""

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import sys

import pytest

from build_coverage import verify_checkout


class FixtureReads:
    def __init__(self, checkout):
        self.checkout = checkout
        self.node = None
        self.reads = defaultdict(set)

    def audit(self, event, args):
        if event != "open" or not isinstance(args[0], str):
            return
        path = os.path.relpath(args[0], self.checkout)
        if path.startswith("tests/fixtures/"):
            self.reads[path].add(self.node or "")

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
    tracker = FixtureReads(checkout)
    sys.addaudithook(tracker.audit)
    tests = [
        str(path.relative_to(checkout))
        for path in sorted((checkout / "tests").rglob("test_*.py"))
        if any(term in path.read_text(encoding="utf-8") for term in (
            "load_sql_fixtures", "load_sql_fixture_pairs", "FIXTURES_DIR"
        ))
    ]
    if pytest.main(["-q", *tests], plugins=[tracker]) != pytest.ExitCode.OK:
        raise SystemExit("Fixture map requires passing baseline tests")
    mapping = {path: sorted(ids) for path, ids in tracker.reads.items() if "" not in ids}
    output.write_text(json.dumps(mapping, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
