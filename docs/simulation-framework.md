# Satellite simulation framework

This is an in-progress extension of the canonical Experiment Studio, not an
operational tracking system. Satellite positions derived from catalog mean
elements are predictions. Environmental inputs can independently be observed,
modeled, or illustrative; neither changes the other source's classification.

## Run a catalog window

Install the project's dependencies and simulation extra, or install NumPy,
SGP4 and Astropy in a lightweight Python 3.11+ environment for just this path.

```sh
python -m godsat.simulation --catalog data/catalog.json --format omm \
  --start 2026-11-08T00:00:00Z --duration 600 --step 10 \
  --environment data/ionosphere.json --environment data/weather.json \
  --environment data/magnetic-field.json --output outputs/simulation/scene.json
python -m godsat.studio --output outputs/simulation --port 8765
```

Choose `outputs/simulation/scene.json` in Scene source and Whole system.
Use `--format tle` for a checksum-validated two/three-line TLE catalog. Inputs
must be a single snapshot with unique satellite identities. OMM uses
SGP4/WGS72, Earth/TEME/UTC conventions; incompatible fields are rejected.
Missing redundant GP fields follow the documented CelesTrak defaults.
This command reads local products. Download/normalization is an explicit prior
step, so playback works offline and does not silently refresh scientific inputs.

The exporter supports up to 20,000 objects, 1,200 frames and 1,200,000 total
position samples per window, and the existing 64 MiB scene limit still applies.
These are memory bounds, not a guaranteed frame rate. Large scenes show a trail
only for the focus object, preserving individual satellite points. For longer
runs, export a playback sequence as described below.

SGP4 failures, future elements, and elements older than `--max-age-hours` stay
unavailable. No observation history or covariance is inferred. TEME output is
available with `--frame TEME`; default ITRS output uses Astropy's frame transform
and records the installed EOP table hash, prediction status and warnings.
Offline bundled EOP can be predicted or out of range; inspect that provenance.

## Environmental input contract

`schemas/godsat.environment.v1.schema.json` describes normalized point samples.
The Python validator additionally enforces source identity, validity ordering,
and complete geodetic east/north/up magnetic vectors. Repeat `--environment`
to merge independently sourced files; duplicate source IDs are rejected.

```json
{
  "schema": "godsat.environment.v1",
  "sources": [{
    "id": "example", "name": "Illustrative format example",
    "kind": "illustrative", "reference": "Documentation example, not measurements"
  }],
  "samples": [{
    "source_id": "example", "time_utc": "2026-11-08T00:00:00Z",
    "valid_until_utc": "2026-11-08T00:05:00Z",
    "latitude_deg": 35, "longitude_deg": -120, "altitude_km": 350,
    "values": {"vertical_tec_tecu": 10}
  }]
}
```

Supported quantities: vertical TEC (TECU), electron density (m⁻³), magnetic ENU
components (nT), cloud fraction (0–1), pressure (Pa), temperature (K), and neutral
density (kg/m³). Source references should identify the dataset/model version;
input SHA-256 is added at ingestion. A supplied validity interval is a claim by
the input producer, not an independently verified uncertainty bound.

The environmental selector displays valid samples at their actual geodetic
locations, with a numeric range and source classifications. No spatial or
temporal interpolation, global coverage, or missing values are invented.
Magnetic lines show local direction with exaggerated constant length, not field
lines obtained by integrating the magnetic model. At most 2,000 environmental
samples are displayed with even thinning across the input; the legend states
displayed/valid counts. Earth-centered framing is the default for mixed LEO/GEO
catalogs; choose Entire catalog extent to include the most distant trajectories.

The decorative cloud texture and qualitative ionosphere shell remain separate
display controls. Environmental samples drive the optional ground-radio path
estimates described below. They do not modify SGP4 forces or establish sensor
detections. `ionospheric_group_delay_m` implements the first-order 40.3·STEC/f²
relation, requiring **slant** TEC; vertical TEC is not silently substituted.

## Authoritative model boundaries and next work

- [CelesTrak GP conventions](https://celestrak.org/NORAD/documentation/gp-data-formats.php)
  and [SGP4 tutorial](https://celestrak.org/software/tutorials/sgp4.php): catalog
  elements belong to their matching propagator. A numerical force model needs
  a consistent initial state, spacecraft properties, and independent validation.
- [IERS ITRS](https://www.iers.org/iers/en/dataproducts/itrs/itrs): precise
  terrestrial/celestial relationships require Earth orientation parameters.
- [NOAA GloTEC](https://www.spaceweather.gov/products/glotec): the adapter reads
  assimilative model TEC columns and F2 peak densities with their timestamps and
  quality flags. This is not a local volumetric plasma solver.
- [NOAA IGRF](https://www.ncei.noaa.gov/products/international-geomagnetic-reference-field):
  the IGRF-14 adapter uses pinned `ppigrf==2.1.0` coefficients, geodetic inputs and
  ENU field components. Its domain is restricted to 1900–2029 and 0–2,000 km.
  It excludes external storm fields and small-scale crustal anomalies.
- [ESA ionospheric delay](https://gssc.esa.int/navipedia/index.php/Ionospheric_Delay):
  link delay depends on the integrated electron density along the signal path.

Future extensions include fuller signal propagation, browser frame budgets across
additional devices/workloads, and independently calibrated orbit/environmental
uncertainty. The integrated local validation is recorded in
`benchmarks/platform-audit.json`. Existing implementation agreement does not
establish real-world orbit or environmental prediction accuracy.

## Supplied attitude

Each object can carry an `attitude` record as defined by
`schemas/godsat.attitude.v1.schema.json`. It must declare the same reference frame
as the scene, Hamilton `xyzw` active `body_to_reference` rotations, a source kind
and reference, and descriptions of all three right-handed body axes. Its unit
quaternion array must match the scene timestamps; missing entries are `null`.
Conflicting frames, unspecified conventions and nonunit rotations are rejected.

The spacecraft inspector applies those rotations through the fixed display-axis
transform and uses shortest-path SLERP between adjacent valid samples. This is
an interpolation assumption, not evidence of intermediate attitude: rotations
of more than 180 degrees between samples are ambiguous without angular-rate
history. Null intervals hide the spacecraft model instead of filling the gap.
The inspector shows source and axis conventions; the mesh remains generic and
does not establish actual dimensions or geometry. Scenes without attitude keep
the explicitly illustrative Earth-pointing pose. Sequence boundary and roster
hashes include supplied attitude and its conventions.

## Separate numerical force model

The catalog SGP4 branch is unchanged. A separate, bounded numerical experiment
starts from supplied **osculating GCRS position and velocity**, with explicit
spacecraft mass, drag area and drag coefficient whenever drag is enabled.
It must not be initialized by treating TLE mean elements as osculating elements.
Unknown spacecraft properties are not filled in from catalog names.

```sh
python -m godsat.simulation.inputs space-weather --output data/environment/space-weather.csv
python -m godsat.simulation.numerical --initial configs/numerical-example.json \
  --space-weather data/environment/space-weather.csv --output outputs/numerical-example/scene.json
python -m scripts.studio.benchmark_numerical --objects 1000 \
  --drivers data/environment/space-weather.csv
```

The example initial state and spacecraft properties are explicitly synthetic.
The numerical branch supports central gravity, J2 in Earth-fixed axes,
atmospheric drag, and optional geometric Sun/Moon third-body gravity. It uses
vectorized fixed-step RK4. Positions and velocities are transformed with
Astropy/IERS at every RK stage; co-rotating atmospheric velocity is subtracted
before computing drag. Position units are km, velocity km/s, while density and
spacecraft area/mass enter the drag equation in SI units. The output is the same
ITRS scene contract with velocity-aware playback.

[NRLMSIS 2.1](https://www.nrl.navy.mil/Our-Work/Areas-of-Research/Space-Science/)
supplies an empirical neutral atmosphere, through pinned `pymsis==0.12.0`.
The wrapper always receives explicit F10.7 and seven-element Ap inputs and never
downloads or invents driver values while integrating. The adapter selects the
previous day's observed-distance F10.7, the current centered 81-day mean, and
the current/previous Ap bins as defined by the
[pymsis input contract](https://swxtrec.github.io/pymsis/reference/generated/pymsis.msis.calculate.html).
The CSV parser uses named [CelesTrak columns](https://celestrak.org/SpaceData/SpaceWx-format.php).
It refuses missing values and preserves flux qualifiers, which can identify
predictions or interpolated values. Centered means can include future predicted
data; the CSV does not identify provenance separately for every Ap bin.

The driver file, NRLMSIS parameter file, adapter, numerical source and initial
experiment hashes are recorded. The optional `dynamics` dependency group
installs the atmosphere wrapper; NRLMSIS has its own
[usage terms](https://github.com/SWxTREC/pymsis/blob/main/MSIS2_LICENSE).
The model source is not vendored into this repository.

Runs are bounded to 24 hours, 100,000 integration steps, and the existing scene
sample budget. The adapter refuses density requests outside 0–1,000 km
geodetic altitude and trajectories below the nominal Earth radius plus 100 km.
A domain failure aborts export; it does not silently substitute zero drag.
Output cadence must be an integer multiple of the integration step. Smaller
steps must be checked for convergence for the actual configuration.

This remains a model experiment. Neutral winds, solar radiation pressure,
maneuvers, higher gravity harmonics, tides and relativistic terms are omitted.
The built-in third-body ephemeris is not a precision navigation ephemeris.
No measured attitude or covariance is invented, and the generic spacecraft
shape/pose remains an illustration. Integration convergence is separate from
initial-state, spacecraft-property, atmosphere and force-model uncertainty.

Validation includes a closed-form circular-orbit check, step-size convergence,
J2 nodal precession against the first-order secular formula, co-rotation/frame
checks, drag direction/scaling, and third-body tidal limits. Twenty-four
published NRLMSIS reference outputs in the pinned package are checked with the
documented printed-reference tolerance after converting CGS density to SI.
The 1,000-object synthetic benchmark compares the same experiment with and
without drag and refines a 16-object subset from 10-second to 5-second steps.
Its `benchmark.json` and `drag-comparison.csv` are model-sensitivity evidence,
not measured orbit errors.

The recorded run in `benchmarks/numerical-1000.json` completed 1,440 batched force
evaluations for 1,000 synthetic spacecraft over one hour in 11.46 seconds on this
laptop. Final drag/no-drag differences ranged from 13.91 to 33.45 m, with a
19.75 m median. The maximum 10-second/5-second step difference on the 16-object
subset was 0.01323 m. Neither comparison measures agreement with real satellite
trajectories. All 1,000 displayed tracks retain the illustrative source label.

## Environmental propagation estimates

Attach the explicit ground-link configuration when exporting either a scene or
a windowed sequence:

```sh
python -m godsat.simulation.inputs weather --latitude 0 --longitude 0 \
  --time 2026-11-08T18:55:00Z --hold-seconds 3600 \
  --output data/environment/equatorial-weather-hourly.json
python -m godsat.simulation --catalog data/catalog-active.json \
  --start 2026-11-08T18:55:00Z --duration 300 --step 30 \
  --environment data/environment/glotec.json \
  --environment data/environment/equatorial-weather-hourly.json \
  --ground-links configs/ground-links-example.json --output outputs/catalog-links/scene.json
```

The example station is hypothetical, at 0° latitude/longitude with explicitly
assumed zero ellipsoidal and orthometric heights. It is not an operational
station. The weather command chooses the preceding hourly model sample and
records an explicit zero-order hold; it does not label that value a measurement
at the requested minute. Use actual source epochs for a new run.

The browser's ground-radio panel computes the focused satellite's snapshot
geometry and these separate propagation effects, at the saved sample epochs:

- **Dry slant delay:** the Saastamoinen/Davis zenith hydrostatic term
  `0.0022768 * pressure_hPa / (1 - 0.00266*cos(2*latitude) - 0.00028*H_km)`,
  multiplied by a secant elevation mapping. Orthometric station height and a
  pressure sample with a known compatible vertical datum are required. Pressure
  farther than the configured distance or height limits is not used. This is
  the hydrostatic term only, following the
  [IERS reference](https://www.iers.org/SharedDocs/Publikationen/EN/IERS/Publications/tn/TechnNote32/tn32.pdf?__blob=publicationFile).
- **Ionospheric group delay:** a single-shell mapping converts VTEC to slant TEC
  along the geometric ray; `40.3e16 * slant_TECU / frequency_Hz²` gives metres,
  following [ESA's relation](https://gssc.esa.int/navipedia/index.php/Ionospheric_Delay).
  The target must be above the source's entire modeled column (8,500 km for the
  ingested GloTEC product). LEO targets inside that column require a vertical
  profile and receive an unavailable result, not the full-column correction.
- **Uplink Faraday rotation:** `2.36e4 * slant_electrons_m2 * B_parallel_T / f²`
  estimates rotation using IGRF-14 at the shell pierce point. The propagation
  direction is defined from station to satellite. This approximates the
  density-weighted magnetic field by one shell value; it follows the
  [ITU ionospheric propagation framework](https://www.itu.int/rec/R-REC-P.531/en).

The example configuration requests bilinear TEC interpolation from four valid
corners in one timestamped regular grid. It wraps longitude at the dateline,
requires declared grid spacing, and does not fill missing corners or interpolate
between epochs. The input inspector records each corner, weight, maximum source
distance, pressure time, and magnetic coefficient hash. A nearest-sample option
is also available and identified explicitly. These are model estimates; source
uncertainty is not inferred from interpolation.

Dashed lines show geometric candidate radio paths above the elevation mask,
not successful observations. Cloud fraction remains contextual area coverage,
not optical opacity or a detection probability. The calculations omit wet delay,
refraction, diffraction, multipath, clock corrections, light-time iteration,
Sagnac/relativity, and a receiver/link-budget model. Component delays are not
presented as a complete ranging solution. No environmental force is added to
the SGP4 catalog trajectories.

`/api/studio/links` computes a bounded timeline for one selected object/station
from the same content-identified scene or sequence window. Its jobs are
serialized to bound heavy allocations. The UI cancels stale requests and checks
the returned scene hash before displaying results. Saved observation/custody
fields remain unchanged.

For a reproducible local calculation:

```sh
python -m godsat.simulation.links --scene outputs/catalog-links/scene.json \
  --object 64723 --station equator-example --output outputs/catalog-links/propagation.json
```

The recorded MTG-S1 snapshot at 18:55 UTC, using the hypothetical 1.57542 GHz
link and the retrieved products, yields approximately 2.311 m dry slant delay,
7.519 m ionospheric group delay and 2.837° uplink Faraday rotation. See
`benchmarks/ground-link-effects.json` for input distances, TEC corner weights,
timestamps and limitations. These numbers are model outputs, not measured
tracking error or a verified MTG-S1 communications link.

The added analytic checks cover zenith geometry, the inverse-frequency-squared
ionosphere/Faraday relation, missing/stale inputs, satellites below the TEC
column top, incompatible vertical datums, and bilinear interpolation across the
dateline without filling holes. Browser inspection also verifies that the
component values reach the selected-object panel. Focus selection now searches
the full catalog while listing at most 200 matches plus the current object;
unchanged readouts are not rewritten every animation frame. This avoids the
large-DOM update slowdown encountered with the original 16,896-option dropdown.

## Long-duration playback

```sh
python -m godsat.simulation --catalog data/catalog-active.json \
  --start 2026-11-08T18:55:00Z --duration 3600 --step 30 --window-seconds 300 \
  --environment data/environment/glotec.json --environment data/environment/igrf14.json \
  --output outputs/catalog-sequence/scene-sequence.json
```

Choose the `scene-sequence.json` manifest in the same Scene source menu. Each
window is a normal bounded scene, with one shared boundary frame. The manifest
records per-window content hashes, the object roster hash, and hashes of both
boundary states. Loading checks all of those before returning a window. Paths
must remain in the manifest directory; symlinks and traversal are rejected.
The sequence manifest is written only after all windows have been exported.

The browser keeps at most two completed windows in its cache, prefetches the
next, and drops older windows. Large or delayed transfers hold the current
boundary frame until the next window is ready. Scrubbing chooses the relevant
window directly. Camera position and focused object survive a transition.
Environmental samples are included only when their declared validity overlaps
the window. The complete source metadata remains visible even where no samples
are valid. The timeline spans the full run; orbit trails and the Export window
button cover only the active window.

This sequence format supports catalog geometry with unknown observation history.
It rejects non-null observation arrays: carrying detection custody across
windows requires an explicit initial observation state and is not inferred.
There is no full-run scene retained in the browser or server. The exporter and
server still use bounded in-memory JSON per window; browser heap and WASM memory
can retain allocation high-water marks after buffers are released.

The one-hour 16,896-object validation run produced 12 windows and 121 distinct
epochs. `benchmarks/sequence-16896.json` records validation of every window through
the production loader. Unit tests additionally compare the windowed output with
a one-shot export, reject tampering and path escape, exercise backward seeking,
and check that the completed-window cache stays at two entries. These bounds do
not imply unlimited-duration retention or an operational live tracking service.

The one-hour sequence was also played automatically in the in-app browser at
three steps/second, reached window 12/12 at 19:55 UTC, and stopped normally.
The server recorded successful requests for every later window (indices 1–11).
Direct end/start seeking and rapid end/start scrubbing were checked afterward;
the displayed cache diagnostics stayed at two completed windows and the latest
requested epoch won. `benchmarks/sequence-browser.json` records the completion
snapshot. This is a local browser smoke test, not a multi-hour endurance test.

## Source adapters

```sh
python -m godsat.simulation.inputs catalog --group active --output data/catalog-active.json
python -m godsat.simulation.inputs glotec --hold-seconds 600 --output data/environment/glotec.json
python -m godsat.simulation.inputs weather --latitude 0 --longitude 0 \
  --hold-seconds 900 --output data/environment/weather.json
python -m godsat.simulation.inputs igrf --points data/field-points.json \
  --time 2026-11-08T18:55:00Z --hold-seconds 600 --output data/environment/igrf14.json
python -m godsat.simulation.inputs ionex --input data/input.inx --output data/environment/ionex.json
```

`field-points.json` is an array of objects containing `latitude_deg`,
`longitude_deg` and `altitude_km`. Download times above are examples; align a
simulation with the actual product epochs. The default sample hold is **zero**:
samples are valid at their own timestamp only. `--hold-seconds` explicitly
requests a zero-order hold and records that approximation; it is not a measured
validity duration. Sources outside their coverage remain unavailable.

Raw downloads and SHA-256 metadata are retained next to the normalized files.
GloTEC grid quality flags remain attached to samples; a flag of zero does not
become an observation. TEC is a vertical column, plotted at ground coordinates;
peak density is placed at the modeled F2 peak altitude. The IONEX adapter accepts
uncompressed version 1.x two-dimensional TEC maps, handles the exponent and
9999 missing sentinel, and converts spherical/geocentric grid locations to
WGS84 geodetic positions. It rejects unsupported 3D maps; RMS and height
correction maps are not used.

[Open-Meteo](https://open-meteo.com/en/docs) current weather is explicitly
classified as model output, with pressure converted from hPa to Pa, temperature
from Celsius to kelvin, and cloud percentage to a fraction. Temperature is
placed two metres above the returned surface elevation. No ground weather
observation is implied.

## Velocity-aware playback

New catalog scenes include `velocities_km_s`, the derivative in the same declared
frame as each position. Astropy transforms the full position/velocity state,
including Earth's rotation for ITRS. Interpolation tangents are centered
numerical derivatives of the SGP4 position curve (offsets ±0.25 seconds), not
the independent SGP4 state-velocity output. The latter produced metre-scale
errors away from interval midpoints for some catalog objects. The browser's Rust core and JavaScript
fallback use cubic Hermite interpolation. Old position-only scenes still use
linear interpolation. Missing derivatives in a velocity-bearing trajectory make
that interval unavailable; they never trigger an undocumented linear fallback.
Exact position samples remain visible even when the following interval is missing.

This convention follows the use of position derivatives in ephemeris
interpolation described by [NAIF](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/req/spk.html).
Interpolation is only a display reconstruction of the saved ephemeris, not an
additional force model.

## Reproducible checks

```sh
python -m pytest tests/unit/test_simulation.py tests/unit/test_simulation_providers.py tests/unit/test_studio.py
npm run test:studio
cargo test --manifest-path rust/studio-core/Cargo.toml
python -m scripts.studio.benchmark_simulation --objects 10000
node scripts/studio/validate_interpolation.mjs outputs/simulation-benchmark/interpolation-reference.json
python -m scripts.studio.validate_igrf --source data/reference/igrf14.f
```

The reference test checks the published Vanguard SGP4 epoch vector, then
separately tests EOP frame roundtrip, stale/future masking and environmental
validity. Neither a roundtrip nor SGP4 agreement measures real orbit error.

The local synthetic benchmark on November 8, 2026 produced 610,000 valid states
for 10,000 satellites and 61 frames in 1.805 s, plus 0.543 s JSON serialization
(36,320,786 bytes). The checked-in summary is in
`docs/benchmarks/simulation-10000.json`; the generated scene is local output.
Browser loading and rendering were checked manually, but FPS has not yet been
measured. A 10-second cadence incurred a 107.293 m maximum midpoint error over
the first 100 synthetic objects when linear interpolation was compared with
SGP4. That is a measured interpolation limitation, not claimed orbit accuracy.

With velocity-aware playback, the newer 10,000-object benchmark uses 31 frames
at a 20-second cadence. Across 15,000 off-grid samples on 100 synthetic objects,
the maximum error relative to direct SGP4/Astropy ITRS evaluation was 0.004542 m,
versus 424.728 m for linear interpolation at that cadence. Actual JavaScript and
WASM results agreed in this run. See `benchmarks/simulation-hermite-10000.json`
and `benchmarks/interpolation-validation.json`. These are implementation and
interpolation checks, not centimetre-accurate real satellite tracking claims.

IGRF-14 was independently compared with NOAA's official Fortran source, using
180 cases across four epochs, five latitudes, three longitudes and three
altitudes. Maximum ENU component disagreement was 0.016661 nT. The source hash,
compiler and reference vectors are in `benchmarks/igrf14-reference.json`. This
checks implementation consistency with the standard model, not the model's
accuracy against nature.

The downloaded active catalog contained 16,896 objects. The locally rendered
21-frame window includes 352,758 successful position samples; stale elements,
future epochs and SGP4 errors remain unavailable. The scene includes 5,184
GloTEC TEC columns, 5,184 F2 peak densities, and 408 IGRF vectors. The weather
product falls outside that particular window and is correctly absent from its
active layers. See `benchmarks/catalog-environment-audit.json` for hashes,
timestamps and counts.

A second interpolation check samples 133 objects across the real catalog,
including eccentricity extremes up to 0.84055719, at five fractions of every
30-second interval. Maximum error across 13,300 positions is 0.029942 m;
`benchmarks/catalog-interpolation-validation.json` records the result. The
original use of SGP4 state velocities reached 6.549 m in this same test;
differentiating the position curve fixed the inconsistency. The 12-record
offline regression fixture preserves extreme-element cases without downloading
current data during tests.

Manual whole-system playback in the in-app browser reported around 56 FPS with
16,896 catalog objects and the electron-density overlay on this laptop; the
main-thread frame-submission p95 was about 16 ms in sampled two-second windows.
These are sampled local UI readings, not a sustained cross-device guarantee or
GPU timing. The header now exposes these measurements for repeatable inspection.
