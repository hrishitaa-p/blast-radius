# Blast Radius

RWX Builders Buildathon submission for selecting and scheduling SQLGlot tests.
Edits confined to mapped fixtures run the tests that read those fixtures on the
official pinned revision. All other patches run the entire test inventory. For
each selection the scheduler tries one through eight workers and minimizes the
largest recorded worker load plus two seconds per worker.

## Verification

The 30 official samples scored 827.874 simulated seconds with zero misses. The
official starter scored 1210.470 seconds with zero misses on the same samples.
These timings exclude the selector's CPU usage. An exploratory source-coverage
selector missed failures on the samples, so source changes use the full suite.

Extract the official starter's sample directory beside this README, then run
`make sample` with Docker and linux/amd64 support. To score directly with Python:

```sh
python3 selector.py --data sample > output.jsonl
python3 score.py sample sample/answers.json output.jsonl
```

The sample inputs and answers are outside the image. The image uses the pinned
base from the official starter and requires no runtime network access.

## Rebuild the fixture map

Check out SQLGlot at `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. Install its
test dependencies plus pytest and coverage.py in an isolated environment, then
run:

```sh
python3 fixture_usage.py /path/to/pinned/sqlglot fixtures-map.json
```

The map records file reads during baseline tests. Neither map generation nor
the selector reads sample answers.
