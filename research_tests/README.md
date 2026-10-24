# Supplemental tests

These tests cover the local full-system analyses and are kept separate from the portable paper-study suite. They may require optional packages and data or outputs that are downloaded/generated locally.

The baseline CI runs `tests/`, which does not need the multi-gigabyte archives. To try a supplemental test after preparing its inputs, run it explicitly, for example:

```bash
python -m pytest research_tests/test_catalog_trajectory.py -q
```

Check the test's fixtures and required files first. A missing measurement archive or saved run is not evidence that the related analysis passed.
