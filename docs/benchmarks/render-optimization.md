# Studio rendering optimization

## Passes 1–2: idle gating and packed point updates

Baseline: `680c242`, Studio's Sam UI branch. Same local 16,896-object, 11-epoch
ITRS catalog scene in both builds (scene SHA-256
`291f1284ff7aecc4932d57c4e4fe344f1864d7d938fe19ef3dc74e0296721ca0`).
The source is a modeled catalog, not observation truth.

Run `node scripts/studio/benchmark_renderer.mjs /path/to/scene.json` with Node.
Without a path, the harness builds a 16,896-object synthetic fixture. It uses
real Rust/WASM evaluation and the production renderer's update method with
Cesium submission stubbed. The harness warms up 20 ticks and records 100 ticks.
For the baseline, copy the harness into a checkout of `680c242` and use the
same scene path. These timings exclude browser layout, GPU work and Cesium
internals; setter counts include writes even if Cesium would ignore the value.

| Workload | Version | Median ms | p95 ms | Point writes | Explicit render requests | Widget updates |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Paused | Baseline | 6.341 | 8.486 | 6,748,600 | 100 | 100 |
| Paused | Idle gating | 0.0006 | 0.0009 | 0 | 0 | 100 |
| Paused | Packed updates | 0.0006 | 0.0009 | 0 | 0 | 100 |
| Playing | Baseline | 6.074 | 7.532 | 6,748,600 | 100 | 100 |
| Playing | Idle gating | 6.309 | 7.989 | 6,748,600 | 100 | 100 |
| Playing | Packed updates | 2.080 | 5.346 | 1,679,800 | 100 | 100 |

Paused ticks continue servicing Cesium camera input, inertia and tile loading.
They no longer rewrite unchanged catalog points or force draws. The Three.js
preview skips rendering at zero layout size and invalidates when it becomes
visible or resizes. Playing ticks read a reusable WASM output view, reuse
Cartesian scratch storage, calculate one coordinate transform per frame, and
apply color/size changes only on a state or focus change. Cesium's vendored
point position setter clones the supplied Cartesian coordinates. Positions
remain Float64 before transfer to Cesium, and gaps remain hidden.

### Browser spot checks

Same in-app browser, catalog source, high-definition quality, inspector closed,
default layers, playback at 0.35 steps/s. The counter reports **loop updates**,
not completed GPU frames; CPU p95 is the time inside the render callback.
Samples are individual two-second windows, not a sustained benchmark.

| Workload | Baseline updates/s | Optimized updates/s | Baseline CPU p95 ms | Optimized CPU p95 ms |
| --- | ---: | ---: | ---: | ---: |
| Paused | 34.4 | 56.9 | 9.2 | 2.4 |
| Playing | 31.6 | 33.4 | 10.8 | 6.9 |

Manual verification: playback advanced UTC, pause held UTC, camera drag
changed framing while paused, reset restored the view, picking selected
IRIDIUM 106, and opening Inspect drew its illustrative preview while paused.
The screenshot is saved locally at `outputs/render-profile/catalog-inspect.png`.
No resolution or scene-quality defaults were reduced.

Regression gates: production UI build and type check passed; 67 React UI tests,
34 Studio JS tests and 3 Rust tests passed. The renderer regression exercises
idle gating, preview resize invalidation, focus/mode/layer changes and a missing
position during interpolation. `git diff --check` passed.

## Pass 3: scene responses and window loading

Run `python -m scripts.studio.benchmark_scene_service SCENE_JSON MANIFEST_JSON`
from the checkout. For the baseline, copy the benchmark script into a checkout
of `680c242` and use the same absolute artifact paths. Results here are one run
per path in the same Python environment and are handler timings, not transfer or
browser parse times. See [the raw timing and digest records](scene-service.json).

| 16,896-object workload | Baseline first | Optimized first | Baseline repeat | Optimized repeat |
| --- | ---: | ---: | ---: | ---: |
| Standalone scene | 2.998 s | 1.240 s | 2.263 s | 0.012 s |
| First sequence window | 2.579 s | 1.036 s | 2.564 s | 0.012 s |
| Next sequence window | 2.573 s | 0.963 s | 2.567 s | 0.011 s |

All six comparisons had identical semantic SHA-256 digests of the decoded
response. Compact JSON reduced the first window from 27.63 MB to 26.18 MB.
Canonical scene adapters validate positions and velocities once and retain the
parsed arrays while sanitizing metadata. The HTTP response no longer makes a
second recursive copy. A shared 64 MiB LRU retains encoded responses; a warm
request still reads and hashes the source and, for sequences, verifies the
current window against the validated manifest. Legacy replays with sidecars
are intentionally uncached. Concurrent cold requests can still repeat work.

### Browser window transition

With both builds serving the same 12-window catalog sequence, load window 1,
then focus the timeline and press End to seek to the unprefetched final window.
Timing starts immediately before the key action and ends when the UI displays
`2026-11-08 19:55:00.000 UTC`. One browser sample per build: **2,360 ms baseline,
1,287 ms optimized**. This includes UI automation overhead, server processing,
loopback transfer, JSON parsing and scene installation; it does not time GPU
presentation. Starting again at window 1, optimized playback at 3 steps/s
advanced automatically through window 5 before being paused. Screenshot:
`outputs/render-profile/sequence-optimized.png`.

Targeted regression suite: **102 Python tests passed**, including repeat cache
reuse, invalidation on same-size tampering with the original modification time,
updated standalone positions and provenance, and legacy sidecar changes.
Existing scene, sequence, environment, attitude, numerical, and ground link
checks also passed. `git diff --check` passed.

## Pass 4: window installation and actual draw counts

Run `node scripts/studio/benchmark_window_install.mjs WINDOW_0.json WINDOW_1.json`
with two adjacent sequence artifacts. The harness alternates both 16,896-object
windows 12 times, using real WASM and the production scene-install logic with
Cesium collections stubbed. It excludes WebGL work, transfer and browser parsing.

| Metric | Before | After |
| --- | ---: | ---: |
| WASM preparation median | 56.37 ms | 46.27 ms |
| Stubbed renderer installation median | 1.06 ms | 1.14 ms |
| Primitives added across 12 transitions | 202,788 | 12 |
| Collection clears | 60 | 24 |
| Model-load requests | 24 | 0 |

Same-layout WASM scenes overwrite existing storage and rebuild the ID and track
indices. Same-sequence ITRS/TEME windows with identical ordered IDs and kinds
keep point primitives and models, but rebuild trajectory-dependent trails and
invalidate the last frame. Changed rosters, changed frames and GCRS preloading
use the full install path. The stubbed install wall time did not improve; the
large difference is the removed primitive/model churn. The browser cold End
seek in this pass took 1.30 s, close to pass 3's 1.29 s spot check.

The menu now separates loop updates from Cesium `postRender` events. The latter
count draws submitted by Cesium, not GPU completion or display presentation.
For a baseline with identical instrumentation, apply only the draw-count
listener and readout changes to `680c242` and build it. Use the same catalog
sequence, high-definition setting, closed inspector and default layers. At the
first epoch, sample the paused menu; close it, drag from (410,455) to (520,430)
in the 1280×720 viewport, reopen it and read the gesture window. Then play at
0.35 steps/s and read a settled two-second window. The gesture is a brief
browser automation drag, not a sustained camera stress benchmark.

| Browser spot check | Baseline updates/s | Baseline draws/s | Optimized updates/s | Optimized draws/s | CPU p95 before → after |
| --- | ---: | ---: | ---: | ---: | ---: |
| Paused | 26.8 | 26.8 | 57.0 | 0.0 | 8.3 → 0.5 ms |
| Paused camera gesture | 25.9 | 25.9 | 54.5 | 0.5 | 7.9 → 0.6 ms |
| Playing after gesture | 25.4 | 25.4 | 26.8 | 26.8 | 9.3 → 5.2 ms |

The gesture retained the same UTC and triggered a draw; settled final-window
view returned to zero draws. Screenshot: `outputs/render-profile/idle-draws.png`.
The rebuild and type check passed, with **67 React UI and 36 Studio JS tests**.
The new regressions verify same-layout WASM scene replacement with missing data
and changed observation state, and preservation of picking primitives with
updated data on window rebind. `git diff --check` passed.

## Pass 5: lossless packed scene transport

Run `python -m scripts.studio.benchmark_packed_scene MANIFEST_JSON 1` on the
16,896-object sequence. The service serializes the same verified window twice
per format; Node decodes nine times per format and checks strict equality of
the complete decoded objects. See [raw measurements](packed-scene.json).

| Metric | JSON | Float64 |
| --- | ---: | ---: |
| Response bytes | 26,177,764 | 12,868,881 |
| First service response | 1.116 s | 0.798 s |
| Repeat service response | 14.6 ms | 14.4 ms |
| Median Node decode | 59.7 ms | 14.0 ms |

Browser scene requests opt in through `Accept: application/vnd.godsat.scene-f64`.
The `GDS1` response has a little-endian 32-bit JSON metadata length, UTF-8
metadata, and little-endian Float64 position and optional velocity tracks in
object order. An all-NaN vector denotes a missing sample. The decoder rejects
bad dimensions, lengths and partial invalid vectors. It reconstructs the same
scene objects used by interpolation, picking, analysis and JSON export. The
existing JSON endpoint remains the default for non-opt-in clients, and the new
browser build also loaded correctly against the previous JSON-only service.

One cold End-key seek to the sequence's final timestamp took **0.892 s** in the
packed browser build, versus **1.302 s** in the previous JSON browser spot
check. These are separate spot observations, not a controlled latency
population. The final screenshot is `outputs/render-profile/packed-window.png`.

### Resolution diagnostic

On the packed build, play the same catalog from the first epoch at 0.35 steps/s,
with the default camera, default layers and a closed inspector. The CSS viewport
was 1280×720 in both cases. Read a settled two-second draw sample after changing
only the existing Render quality choice and returning to the first epoch.

| Quality | Drawing buffer | Draws/s | CPU callback p95 |
| --- | --- | ---: | ---: |
| High definition | 2560×1440 | 26.0 | 6.5 ms |
| Balanced | 1280×720 | 53.6 | 5.3 ms |

This is evidence of a resolution-sensitive bottleneck, not a GPU timer result.
The high-definition setting was restored and defaults were not changed.
Production build and type check passed. Regression checks: **103 Python,
38 Studio JS and 67 React UI tests**, including HTTP negotiation and exact
mixed-velocity/missing-sample round trips. `git diff --check` passed.

## Pass 6: direct WASM staging and GPU diagnostics

The packed decoder stages Float64 coordinates in the WASM frame order while
materializing the normal scene. WASM preparation copies those arrays in bulk
rather than traversing the scene again. The staged data is single-use and capped
at 16 MiB per decoded scene; larger scenes, JSON scenes and revisited windows
use ordinary preparation. The 16,896-object, 11-epoch fixture uses 8.92 MB of
staging storage. The saved wire format and exported scene are unchanged.

Run `node scripts/studio/benchmark_packed_staging.mjs WINDOW.bin` on an opt-in
`GDS1` response from `/api/studio/window` (use the packed `Accept` header above).
The harness decodes and prepares 15 times, drops three warm-up iterations, and
compares the entire WASM output against ordinary preparation at all 11 epochs
and all 10 midpoints.

| Median on the same packed window | Before | After |
| --- | ---: | ---: |
| Decode and stage | 15.68 ms | 15.09 ms |
| WASM preparation | 38.38 ms | 5.32 ms |

All 21 full output arrays matched exactly, including missing positions and
track state. Tests cover mixed linear/Hermite tracks and revisiting a consumed
staged scene. Production build/type check, **39 Studio JS tests and 67 UI tests**
passed. `git diff --check` passed.

### GPU measurements at full resolution

Open Studio with `?gpu-profile=1`; the View options menu reports the p95 and
sample count from the [WebGL elapsed-time query](https://registry.khronos.org/webgl/extensions/EXT_disjoint_timer_query_webgl2/).
The diagnostic keeps at most one query pending, ignores non-draw updates and
invalidated samples, and reports unsupported browsers explicitly. Results are
GPU time for commands bracketed around the Cesium widget draw; they exclude
browser compositing and display presentation. Normal mode does not run queries.

Use the same 16,896-object sequence, 2560×1440 drawing buffer, default layers,
closed inspector and 0.35 steps/s. These are two-second samples, with small
GPU sample counts and expected measurement variance:

| Configuration | Draws/s | GPU p95 | Sample count |
| --- | ---: | ---: | ---: |
| Original settings, first sample | 27.2 | 50.3 ms | 14 |
| Default framebuffer antialiasing off only | 28.2 | 51.9 ms | 14 |
| FXAA off only | 27.5 | 53.2 ms | 11 |
| Original settings, restored build | 27.0 | 54.4 ms | 18 |

The two alternatives were temporary builds and were reverted: neither showed
a clear GPU improvement. The FXAA-off fixed-epoch image changed 178,953 of
646,400 compared pixels, with 18,812 pixels differing by more than eight in
at least one RGB channel. The default-framebuffer comparison changed 96 pixels
and none by more than eight. Comparisons used rows 95–599 of the 1280×720
screenshots, outside most UI controls. Final proof: `outputs/render-profile/gpu-timing.png`.
The vendored Cesium point collection also assigns its single translucent mode
to a different pass than its mixed mode, so that switch was not applied as a
visual-equivalent optimization.

## Pass 7: layer isolation and static reloads

At 2560×1440 internal resolution, open `?gpu-profile=1` with no `isolate`
parameter for the control. Repeat with `isolate=points-off`,
`isolate=atmosphere-off`, and `isolate=globe-off`. Use the same sequence, camera,
first epoch, default layers, inspector closed and playback at 0.35 steps/s.
Discard the first readout and record the following two two-second intervals.
These diagnostic views intentionally omit content. Regular Studio URLs keep
all layer behavior and quality settings unchanged.

| GPU condition | GPU p50, two intervals | GPU p95, two intervals | Draws/s, two intervals |
| --- | --- | --- | --- |
| Full view | 45.7 / 45.3 ms | 54.6 / 52.5 ms | 26.8 / 27.8 |
| Catalog markers hidden | 39.8 / 39.4 ms | 44.2 / 46.9 ms | 37.5 / 36.3 |
| Atmosphere hidden | 44.6 / 46.9 ms | 52.2 / 54.8 ms | 27.4 / 27.6 |
| Globe and imagery hidden | 34.8 / 35.8 ms | 42.1 / 42.7 ms | 28.2 / 29.2 |

The deltas are not additive per-layer costs: hiding geometry changes occlusion
and the rendering passes. Globe and marker work both matter, and removing the
atmosphere alone did not yield a clear speedup. The GPU query does not measure
browser compositing, so the remaining difference between GPU duration and draw
cadence is not assigned to a specific compositor stage.

For repeated startup, static files now have byte-derived ETags. Existing files
revalidate with `304` when their bytes match, including after a reload. Changed
bytes get a new ETag even with the original size and modification time. Scene,
artifact and experiment APIs retain `no-store`.

Run `python -m scripts.studio.benchmark_static_assets http://127.0.0.1:8769`.
The before/after services served the same nine startup assets and had identical
first-response bytes. On revalidation the baseline sent **8,213,353 bytes**;
the optimized service sent **zero response-body bytes** across all nine files.
Browser service logs independently recorded nine `304` responses on reload.
These figures are static transfer savings, not whole-page startup timings.

## Final verification and tradeoffs

- **Benchmarks at scale:** the reports above include paused, playing, camera
  gesture, scene opening, cold/warm response and window-transition evidence
  for the same 16,896-object catalog. Measurements distinguish CPU callbacks,
  Cesium draws, WebGL GPU queries and end-to-end seek latency.
- **Rendering and data work:** paused draws fell to zero, hidden previews no
  longer draw, and the point-update loop avoids unchanged styles and repeated
  allocations. Window handoffs reuse matching primitives and WASM buffers;
  the packed path cuts transfer size and preparation time without changing
  coordinate precision or source validity checks.
- **Full sequence precision:** `node scripts/studio/verify_sequence_transport.mjs
  http://127.0.0.1:8769` verified identical decoded JSON and Float64 scenes across
  all 12 windows. The full WASM output matched at 252 epoch/midpoint evaluations,
  including gaps, observations and interpolation state. JSON remains the export
  and fallback representation.
- **Runtime and fidelity:** final browser playback ran from 18:55:00 to
  19:55:00 UTC at 3 steps/s and stopped at the end. Picking CALSPHERE 1 and
  opening its preview worked at the final epoch. The final screenshot is
  `outputs/render-profile/final-sequence-inspect.png`. Full resolution,
  antialiasing, FXAA and original blend ordering are retained. Window rebinds
  also invalidate the radio path even when its local step is unchanged.
- **Final gates:** production build/typecheck, source/bundle stamp, 104 Python,
  39 Studio JS, 67 React UI and 3 Rust tests passed. `git diff --check` passed.

The remaining high-definition limit is GPU work: the tested configuration
still draws around 27 times/s on this machine. Lower internal resolution is
available through the existing Balanced preset, but has a sharpness tradeoff.
The tested antialiasing and layer alternatives either did not improve GPU time
or removed visible content, so they were not applied to the normal view.
A different globe/point pipeline would need its own image, picking and GPU
validation. There is no claimed 60 FPS guarantee or cross-device benchmark.
