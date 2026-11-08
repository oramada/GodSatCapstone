# Satellite simulation validation

The platform now has separate catalog-prediction and numerical-experiment paths,
source-labeled environmental inputs, bounded streaming playback and supplied
attitude support. The local integrated audit is in
[`benchmarks/platform-audit.json`](benchmarks/platform-audit.json); usage, models
and source references are in [`simulation-framework.md`](simulation-framework.md).

| Capability | Evidence and boundary |
| --- | --- |
| Catalog scale | 16,896 catalog objects, 12 verified playback windows spanning an hour. Stale, future and failed propagations remain unavailable. |
| Playback accuracy | 13,300 off-grid comparisons across 133 real catalog elements: maximum 0.029942 m against direct SGP4/Astropy evaluation. This is interpolation agreement, not real orbit accuracy. |
| Neutral atmosphere | NRLMSIS 2.1 with explicit F10.7 and seven-element Ap history. Driver, parameter and source hashes retained. |
| Numerical forces | Explicit osculating initial states and spacecraft properties; central gravity, J2, optional drag and Sun/Moon terms. 1,000 synthetic spacecraft over one hour in 11.46 s locally. |
| Extended force models | Optional degree 2–8 zonal gravity, cannonball solar pressure with spherical-Earth eclipse, and Schwarzschild correction. A 1,000-object, one-hour synthetic run completed in 16.76 s; 16-object 5 s versus 2.5 s comparison differed by at most 0.844 mm. [Evidence](benchmarks/extended-forces-1000.json). These are model and numerical checks, not orbit-truth validation. |
| Numerical convergence | Maximum 0.01323 m difference between 10 s and 5 s steps on a 16-object subset. Analytic circular-orbit, J2 precession and atmosphere reference checks also pass. |
| Environmental inputs | NOAA GloTEC, IONEX, IGRF-14, weather and space-weather adapters preserve sample epochs, units, provenance and missing-data boundaries. |
| Magnetic implementation | 180 comparisons with NOAA's IGRF implementation: maximum ENU component difference 0.016661 nT. This does not establish field accuracy against nature. |
| Ground signal components | Explicit hypothetical station and frequency; dry pressure delay, single-shell TEC delay and Faraday estimate with assumptions and unavailable components labeled. |
| Attitude | Explicit Hamilton body-to-reference quaternions; frame/source/axis validation, shortest-path interpolation and visible missing-data gaps. Generic geometry remains labeled. |
| Local browser | About 58 FPS with 16,896 catalog objects and electron-density overlay in the final sampled view. CPU submission timing, not sustained GPU or cross-device performance. |
| Regression checks | 57 Python, 21 JavaScript and 3 Rust tests pass; `git diff --check` passes. |

The scene and environment models distinguish observed, modeled and illustrative
inputs. No detection history, orbit covariance, spacecraft properties or measured
attitude is inferred from a catalog identity. Numerical initial states used in
benchmarks are synthetic. Earth texture and cloud texture are illustrative.

Known physical limits include empirical density error, predicted Earth orientation,
limited environmental sampling, absent neutral winds, truncated gravity and
approximate third-body ephemerides. Optional solar radiation pressure, degree 2–8
zonal gravity and the leading Schwarzschild correction are described in
[extended force models](extended-force-models.md); these additions do not remove
the other physical limitations. Signal components do
not constitute a complete navigation or communication solution: iterative light
time, wet delay, relativistic terms and full hardware/link-budget models remain
future extensions. Reference agreement and numerical convergence must never be
reported as centimeter-accurate tracking of real satellites.

Generated inputs, scenes and screenshots are
under `data/` and `outputs/`; reproducible configuration, code, schemas, tests and
compact evidence records are in the repository source tree.
