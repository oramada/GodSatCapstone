# Data sources and limits

## Archived orbital elements

The fetch script reads the pinned Hugging Face dataset revision recorded in [`data/raw/source-manifest.json`](../data/raw/source-manifest.json): `juliensimon/space-track-tle-history` at revision `974246e5ff943175a4a736047a87668fa0361850`. Five annual Parquet files cover the four-year study window from October 2022 through October 2026. Their total download size is 4,408,816,978 bytes (about 4.41 GB); exact sizes and LFS SHA-256 hashes are in the manifest. The source dataset declares CC BY 4.0. Cite the dataset and its upstream Space-Track provenance in student work.

This is historical two-line-element (TLE) data, not a measured Cartesian trajectory for every object at every instant. SGP4 propagation produces modeled positions between available element epochs. Object coverage, element update cadence, and record quality vary.

## Catalog metadata

`scripts/fetch_four_year_data.py` downloads the latest public CelesTrak SATCAT CSV to `data/raw/satcat.csv`. The companion `data/raw/satcat-manifest.json` records the retrieval time, source URL, byte count, and SHA-256. Since this catalog is current and changes over time, two students may create different current-payload cohorts even when using the same historical TLE archive. Preserve the manifest with results. The catalog's present-day object type and decay fields cannot be treated as historical status labels.

## Excluded ground sensor observations

The starter's hyperparameter campaign does not require measured ground-sensor observations. It simulates sensor tasking and dropout. Local experimental and observation data from the research workspace are not included in this repository. A claim about real-world effectiveness needs a separately documented, licensed, and independently validated observation dataset and corresponding calibration protocol.

## Optional state-vector export

To reconstruct one SGP4 TEME state for every archived element epoch, run `python scripts/export_state_vectors.py --cohort all`. It writes a resumable local Parquet dataset under `data/historical_state_vectors_all/`. The full export is a separate multi-gigabyte derived artifact. It contains irregularly timed states at source element epochs; it is not a uniform, continuous, independently observed trajectory. You can limit the first run for a storage/runtime check with `--limit 10000` and a separate output folder.

## Download and storage

The large Parquet files, SATCAT snapshot, derived cohort, scenarios, and outputs are excluded from Git. Run `python scripts/fetch_four_year_data.py` to retrieve the pinned archive, then `python scripts/export_current.py` to construct the cohort used by the default sensor configuration. Check the SHA-256 values against the checked-in source manifest before using the files.
