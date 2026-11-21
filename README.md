# Blast Radius

RWX Builders Buildathon entry for selecting and scheduling SQLGlot regression
tests. The default selector runs the full suite and chooses the cheapest
schedule it finds across one to eight workers. It computes costs in milliseconds
with the official two-second charge per worker.

Run under the official container constraints with `make sample`. Docker must
support linux/amd64. To score the same output locally without Docker:

```sh
python3 selector.py --data sample > output.jsonl
python3 score.py sample sample/answers.json output.jsonl
```

The experimental `--coverage-map` option accepts line and file coverage from
the pinned, unmodified SQLGlot revision, keyed by source path and pytest node ID.
Keep it disabled until a generated map has been evaluated. Sample answers are
used exclusively by the local scorer and are excluded from the image.

## Local baseline

Against the 30 official samples, the starter scored 1210.470 simulated seconds
with zero misses. The scheduler here scored 1104.510 simulated seconds with zero
misses. Those comparisons exclude CPU time.

Extract the official starter's `sample/` directory alongside this README to
repeat the benchmark. To generate an experimental coverage map, install
coverage.py and the pinned checkout's test dependencies in a separate
environment, then run:

```sh
python3 build_coverage.py /path/to/pinned/sqlglot coverage-map.json
python3 selector.py --data sample --coverage-map coverage-map.json > output.jsonl
python3 score.py sample sample/answers.json output.jsonl
```

The baseline image runs with the original pinned Linux image, requires no
network at runtime, and writes the score protocol to stdout. The tournament
requires a public GitHub repository under 20 MB with a root Dockerfile.
