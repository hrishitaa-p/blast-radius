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
