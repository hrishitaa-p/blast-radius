# Blast Radius

RWX Builders Buildathon selector and worker scheduler for SQLGlot. It uses
coverage measured on the official pinned revision, including an offline
instrumented run of the optimizer and executor tests that normally use child
processes. It also maps fixture readers and uses a conservative full-suite
fallback for unrecognized patches.

Selections use changed-line coverage, widening to enclosing function coverage
for boolean expressions and to file coverage for recursive functions. Edits to
simple constants also include measured attribute readers. Plain comment
insertions outside multiline tokens include tests that inspect source text.
For each selection, the scheduler tries one through eight workers and minimizes
the largest recorded load plus two seconds per worker.

## Local verification

On the 30 official samples this configuration scored 184.695 simulated seconds
with zero misses before CPU time. This is a local score. The practice and final
datasets are scored by the organizers.

Extract the starter's sample directory beside this README, then run
`make sample` with Docker and linux/amd64 support. Or run the local scorer:

```sh
python3 selector.py --data sample > output.jsonl
python3 score.py sample sample/answers.json output.jsonl
```

The image runs offline and includes the selector and its maps. The sample
patches and answers stay outside the image.

## Rebuild the baseline maps

Check out SQLGlot at `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. Install its
test dependencies plus pytest and coverage.py in an isolated environment. Put
the environment's Python on PATH so SQLGlot subprocess tests can find it.

```sh
python3 build_coverage.py /path/to/sqlglot baseline.json
python3 build_coverage.py /path/to/sqlglot workers.json --worker-tests
python3 fixture_usage.py /path/to/sqlglot fixtures-map.json
python3 compile_map.py /path/to/sqlglot baseline.json coverage-map.json --worker-coverage workers.json
```

The map-building commands use only the pinned SQLGlot source and its tests.
