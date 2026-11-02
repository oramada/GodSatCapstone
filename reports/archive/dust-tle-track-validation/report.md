# DUST annotated tracks against historical satellite orbits

This analysis asks whether each DUST annotated object track has a geometrically consistent match in the historical GP/TLE catalog. DUST supplies timestamps, image-plane annotations, WCS pointing, and spacecraft position for the frames, but it does not provide NORAD identities for these labels.

The matcher first takes the 50 nearest fresh catalog objects to the first annotated line of sight, then ranks that shortlist by median angular residual over the first up-to-five annotated frames. It scores the remaining frames as temporal holdouts. Target and observer are transformed to TEME at each DUST timestamp; SGP4 uses the most recent archived element no older than 72 hours. The host CASSIOPE ID 39265 is excluded. The 0.15° reference in the tables is a descriptive tolerance near 1.4 camera pixels, not a validated acceptance threshold.

## Full annotated-track coverage

The checksum-verified DUST archive contains 160 annotated tracks. The method found usable WCS and spacecraft ephemeris for 156 tracks; four tracks have no annotated frame with both metadata types. The independent audit confirmed those four cases from the archive contents and verified the archive MD5, every output track, the frame-level residual arithmetic, and aggregate totals.

| Measure | Result |
|---|---:|
| Annotated tracks attempted | 160 |
| Tracks with usable WCS and ephemeris | 156 |
| Tracks with at least three temporal holdout frames | 139 |
| Held-out frame residuals | 2,930 |
| Held-out residual median / p95 / maximum | 0.218° / 12.969° / 177.450° |
| Held-out frames under 0.15° | 42.1% |
| Tracks with training median and holdout median both under 0.15° | 57 of 139 |

The aggregate does not support catalog-wide identity assignment yet. Some tracks follow a catalog trajectory within about a pixel; many have degree-scale or larger errors. These outliers remain in the reported results. They could reflect ambiguous first-frame candidates, track or timestamp mapping issues, WCS/pose errors, missing or maneuvering catalog objects, or propagation limitations; the available annotations do not tell us which cause applies.

## Outlier diagnosis

The data audit finds no session-wide image/H5 indexing shift: all 1,378 image stems match the H5 stems in sorted frame order across 22 sessions. All 1,378 H5 UTC times fall 0.219–0.313 seconds after the second encoded in their filenames. For SET 2, all 2,046 MOT boxes exactly match the corresponding class-1 YOLO boxes after converting their normalized centers and widths/heights to 256-pixel coordinates. This supports the zero-based pixel coordinates used for RSO detections.

The Corr star-pixel coordinates use a separate convention. Across 1,148 Corr/WCS pairs and 35,600 matched stars, the WCS-to-star median residual is lowest when evaluating Corr field coordinates at x−1,y−1: 195 arcsec pooled median, compared with 596 arcsec at x,y. The per-frame median residual has a 95th percentile of 655 arcsec. All 2,046 Set 2 RSO MOT boxes match their normalized YOLO boxes exactly after conversion to 256-pixel coordinates; the publisher's annotation code creates those coordinates from OpenCV pixel locations. The RSO annotation coordinates are therefore not shifted by one pixel in the orbit matcher; doing so would mix the Corr and MOT coordinate conventions.

This star-based WCS residual does not explain the largest orbit-track errors. For example, the 2023-06-03 SET 1 session has a 178 arcsec median matched-star residual, while one track has a 7.80° median held-out orbit residual. A six-case sensitivity run varied the shortlist from 50 to 23,087 candidates and the element-age limit from 72 hours to 30 days. Every case selected NORAD 46757 and returned the same 1.689° training median and 7.804° held-out median. This points to a track/catalog identity, observation geometry, or object-orbit issue beyond a simple frame index, filename timestamp, one-pixel convention, shortlist-size, or freshness-cutoff error. The annotations provide no NORAD truth with which to isolate the cause.

The image/H5, timestamp, YOLO-box, and track residual evidence is recorded in [`all-sets-trackfit-v2/independent_audit.json`](all-sets-trackfit-v2/independent_audit.json). The separate matched-star audit and per-frame residual table are in [`wcs-star-calibration/summary.json`](wcs-star-calibration/summary.json) and [`wcs-star-calibration/per_frame_wcs_star_residuals.csv`](wcs-star-calibration/per_frame_wcs_star_residuals.csv). The candidate-list and freshness sensitivity results are in [`outlier-sensitivity/2023_06_03_track_2.json`](outlier-sensitivity/2023_06_03_track_2.json).

### Applying star-derived pointing corrections

I also estimated a per-frame east/north WCS correction from the median residual between matched stars and their catalog coordinates, then applied it to each RSO ray before orbit comparison. This is an independent calibration signal from the RSO labels. The complete 156-track corrected run and its independent audit are in [`all-sets-star-corrected-v1/`](all-sets-star-corrected-v1/).

| Measure | Raw DUST WCS | Star-corrected WCS |
|---|---:|---:|
| Held-out frame residuals | 2,930 | 2,930 |
| Pooled held-out median / p95 residual | 0.218° / 12.969° | 0.232° / 13.647° |
| Held-out frames under 0.15° | 42.116% | 42.082% |
| Candidate NORAD IDs changed | — | 0 of 156 |
| Tracks improved / degraded by >0.01° median | — | 17 / 12 |
| Tracks with training and holdout medians under 0.15° | 57 of 139 | 57 of 139 |

The same-candidate, frame-level median residual change is −0.00106°, while the pooled median and p95 both become slightly worse. The correction does not account for the multi-degree residuals, does not change any selected ID, and does not improve the descriptive track count. The raw DUST WCS remains the primary result; the corrected run is retained as a checked sensitivity analysis. The per-track comparison is in [`star-correction-comparison/summary.json`](star-correction-comparison/summary.json) and [`star-correction-comparison/per_track_comparison.csv`](star-correction-comparison/per_track_comparison.csv).

## Example temporal holdouts

These four tracks show the low-residual end of the sample. The selected object is ranked from the first up-to-five frames; the table scores only later frames.

| DUST session / track | Selected NORAD | First-frame nearest / runner-up angle | Held-out frames | Held-out median / p95 / max residual | Under 0.15° |
|---|---:|---:|---:|---:|---:|
| 2023-01-16 / 1 | 18312 | 0.023° / 2.462° | 36 | 0.083° / 0.167° / 0.208° | 83.3% |
| 2023-01-21 / 1 | 18312 | 0.312° / 0.823° | 22 | 0.070° / 0.105° / 0.119° | 100.0% |
| 2023-01-21 / 2 | 7594 | 0.094° / 0.824° | 10 | 0.085° / 0.135° / 0.158° | 90.0% |
| 2023-01-21 / 3 | 49216 | 0.126° / 2.286° | 10 | 0.122° / 0.140° / 0.144° | 100.0% |

NORAD 18312 is selected again across two separate sessions, which is encouraging consistency evidence, but it is not an independent identity label. Individual detailed outputs are in [`all-sets-trackfit-v2/`](all-sets-trackfit-v2/); the independently reconstructed summary is [`independent_audit.json`](all-sets-trackfit-v2/independent_audit.json).

## Reproduction

Run the catalog-matched batch and its independent audit with:

```sh
PYTHONPATH=. .venv/bin/python scripts/validate_all_dust_tle_tracks.py \
  --output-dir outputs/dust-tle-track-validation/all-sets-trackfit-v2
PYTHONPATH=. .venv/bin/python scripts/validate_all_dust_tle_tracks.py \
  --star-pointing-correction \
  --output-dir outputs/dust-tle-track-validation/all-sets-star-corrected-v1
PYTHONPATH=. .venv/bin/python scripts/audit_all_dust_tle_tracks.py \
  --output-dir outputs/dust-tle-track-validation/all-sets-trackfit-v2
PYTHONPATH=. .venv/bin/python scripts/audit_all_dust_tle_tracks.py \
  --output-dir outputs/dust-tle-track-validation/all-sets-star-corrected-v1
PYTHONPATH=. .venv/bin/python scripts/compare_dust_star_pointing_correction.py
PYTHONPATH=. .venv/bin/python scripts/audit_dust_wcs_star_calibration.py \
  --output-dir outputs/dust-tle-track-validation/wcs-star-calibration
PYTHONPATH=. .venv/bin/python scripts/audit_dust_tle_outlier_sensitivity.py \
  --output outputs/dust-tle-track-validation/outlier-sensitivity/2023_06_03_track_2.json
```

The per-track command is `scripts/validate_dust_tle_track.py`. Dependencies include `h5py`, added to both `requirements.txt` and the project dependency list for reading DUST's H5 telemetry. The dataset archive MD5 is `a31b62290eface15e519ed954124d59c`.
