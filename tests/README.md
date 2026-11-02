# Tests

`python -m pytest -q` runs `tests/unit/`, the portable CI suite. These tests use synthetic fixtures and do not require the local multi-gigabyte archives.

`tests/research/` contains supplementary checks for local research inputs and optional dependencies. Run them explicitly after preparing their inputs:

```bash
python -m pytest tests/research --collect-only -q
python -m pytest tests/research/test_catalog_trajectory.py -q
```

Missing source data or historical results do not count as successful validation. Research checks remain separate from the portable suite for that reason.
