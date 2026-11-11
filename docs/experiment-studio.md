# Experiment Studio

The repository frontend is **GoDSAT Experiment Studio**, one integrated simulation and analysis page. Its globe renderer is CesiumJS 1.147.0, with a Rust/WebAssembly CPU core. Three.js supplies the embedded spacecraft close-up. Studio remains the sole application; old `/legacy`, `/index.html` and `/studio/` links redirect to `/`.

## Workspace layout

- **Globe:** Earth occupies the full viewport and stays centered when panels open. Startup loads an available saved sequence, a canonical scene/replay, or an explicitly illustrative example. Satellite points are visible; orbit trails, textured clouds, celestial bodies, and persistent object labels start off.
- **Top toolbar:** choose the scene and open **Experiment**, **Layers**, **Data**, or **Inspect**. All panels start closed. Only one panel opens at a time; each has a close button, and Escape closes it and returns focus to its toolbar button. A panel grows from its toolbar button and closes back to it; it stays mounted while closed, so a half-filled form, a running screen or the spacecraft close-up survives. Panels overlay the globe without resizing its canvas. Space plays or pauses when focus isn't on a control.
- **Bottom playback bar:** play/pause, UTC time, scrubber and speed stay accessible. The options menu contains camera reset, scene export, and compute/performance status.
- **Layers:** environment and display controls, plus focused/all-object visibility.
- **Data:** searchable collections, artifact inspection, numeric product comparison, and the orbital analysis workbench. Matching numeric field names do not establish matching units or experimental conditions.
- **Inspect:** satellite search, object state, supplied attitude, counts, provenance and available ground-link estimates. Clicking a rendered satellite selects it; its compact selection chip opens inspection. Keyboard users can choose the same object through the inspector's search and select controls.

Inventory counts reflect local files. Collections group output/study folders; file modification dates do not prove experiment execution or completion. Filename suggestions remain candidates validated by the scientific adapter before playback.

Collection browsing and comparisons remain read-only. The **Experiment** panel can validate and launch bounded local numerical simulations, cancel a running worker (after a confirmation), and open its saved result. A trail at its foot shows the stage (set up, validate, run, open result), ⌘/Ctrl+Enter runs a validated setup, and a meter shows time used against the 180 s run limit. See [experiment launcher](experiment-launcher.md) for inputs, limits and API safeguards. Existing source artifacts are not edited.

## Start

From the repository root:

```sh
python -m godsat.studio --output outputs/iridium-next-ground --port 8765
```

Open http://127.0.0.1:8765 . This entry point does not import the training stack. Install the project's `ground` extra for NumPy, Parquet inspection and offline Astropy Sun/Moon ephemerides:

```sh
pip install -e '.[ground]'
```

Without Astropy the scene still opens, with Sun/Moon explicitly unavailable. No network access is needed by the frontend. Add other local artifact roots explicitly:

```sh
python -m godsat.studio --data-root /path/to/downloaded/data --data-root /path/to/runs
```

The existing `python -m godsat serve --output ...` command also serves the studio at `/`, and preserves the existing scientific APIs. `/legacy` redirects to Studio. It imports the original server dependencies.

## Explore

- **Focused object / All objects**: one focused target plus sensors, or all exported objects. The built-in examples use one or all 80 pinned Iridium NEXT names and one or six configured stations. Their geometry and observations are constructed, not an experimental result.
- **Scene source**: choose a saved replay, scenario or state table. The inspector's **Open as scene** also works for eligible files not suggested in the menu.
- **Focus object**: choose a target for the enlarged spacecraft and tracking history. Drag to orbit, scroll to zoom, reset to reframe. Pause and scrub frame-by-frame; speeds are explicit steps per second.
- **World layers**: textured Earth, atmospheric limb shader, qualitative ionosphere shader, static cloud texture or overcast variant, epoch-aligned Sun/Moon, orbit trails, last-sighting marker and a capped high-DPI mode.
- **Experiment library**: search and inspect actual local summaries, DOE/CCD/BO tables, manifests, audits, attitude tables, image evidence and other source products. It polls every 15 seconds while visible; changed selected scenes reload while preserving playback position. It does not launch, stop, or alter experiments.
- **Export scene** downloads a portable JSON scene; reopen it by placing it inside a configured artifact root.

## Data adapters and boundaries

| Repository datatype | Supported representation |
| --- | --- |
| `replay.json`, `replays/*.json` | 3D positions, valid mask, sensor/target IDs, actions and detected targets; saved trace metrics remain in scene records |
| Scenario `.npz` (`states`, `ids`, `times`, `agents`) | Full 3D geometry; ground stations are negative IDs; optional sidecar frame; observation state unknown without trace |
| TEME/GCRS/ITRS state CSV and Parquet | 3D positions with explicit frame suffix, object ID and UTC time; missing/error states remain gaps |
| Canonical `godsat.scene.v1` JSON | 3D geometry and explicit detection history, with source metadata and custody window |
| DOE, response, validation, dropout, convergence, coverage, energy and statistics CSV/JSON | Searchable artifact table, numeric preview plots, or JSON inspector; never interpreted as spacecraft positions |
| Sentinel and CASSIOPE attitude CSV/Parquet | Raw typed table/schema inspector; no automatic quaternion-to-body mapping without a verified frame/convention |
| Optical, DUST, ZTF, SLR and other measurement products | Processed CSV/JSON/Parquet inspector and image evidence; angular measurements are not assigned invented range |
| NPY/NPZ arrays | Shape/dtype inspector; scenario NPZs also replay |
| PNG/JPEG/PDF evidence | Inline preview |
| Raw CDF, FITS, HDF5, archives, PyTorch checkpoints | Metadata inventory only; use the repository's scientific preprocessing tools to create an inspectable product |
| XML, text and Markdown reports | Bounded text preview |

All `outputs/`, `data/`, `reports/`, `configs/`, the selected output folder and explicit additional roots are indexed. Large training outputs are not committed with the report. The studio shows what exists locally; it does not claim missing files were replayed. macOS cloud placeholders are not hydrated implicitly. Checkpoints and archives are never unpickled or extracted.

The default latest-study checkout includes the committed report evidence in `reports/evidence/iridium-next-ground-20261104`. To replay the actual study, provide its saved replay or scenario files. A scenario alone supplies geometry, not the detector's observation history. Generic failure to detect is not labeled an imposed dropout because detection can fail for several reasons.

## Canonical scene contract

See `schemas/godsat.scene.v1.schema.json` and `godsat/studio/scene.py`.

```json
{
  "schema": "godsat.scene.v1",
  "title": "Saved demonstration",
  "frame": "TEME",
  "units": "km",
  "times": ["2026-09-15T00:00:00Z", "2026-09-15T00:01:00Z"],
  "objects": [{"id": "41917", "name": "IRIDIUM 106", "kind": "satellite", "positions_km": [[7000,0,0],[6990,100,0]]}],
  "observations": [{"detected": ["41917"], "actions": []}, {"detected": [], "actions": []}],
  "custody_seconds": 180,
  "source": {"kind": "saved", "description": "Document the actual source"},
  "warnings": []
}
```

Times must be ordered, unique and timezone aware; coordinates use the stated geocentric frame and kilometers. Each object has exactly one position (or `null`) per timestamp. `observations: null` means unknown history. A null frame inside the observation array means unknown at that step. An empty `detected` list means a known absence of detections, not missing data. Legacy trace detected indices refer to targets *after* the sensor prefix; the adapter converts them to stable object IDs. Custody expires strictly after the configured window. No interpolation bridges missing positions.

Adapters must supply explicit reference frames, units and provenance. In particular, raw quaternion products have different conventions; display their tables until a verified attitude-frame adapter exists. The current spacecraft model is a simplified Iridium-like, Earth-pointing illustration, not measured attitude or CAD.

## Display versus physics

The Cesium renderer uses its own UTC-driven Sun/Moon rendering and built-in frame transforms. The API also supplies offline Astropy ephemerides as scene metadata. Rendering does not apply forces to a replay. Cesium converts positions to Earth-fixed display coordinates (TEME uses its pseudo-fixed transform; GCRS uses its ICRF transform). These display transforms do not replace the scientific repository's Astropy frame transformations. Static textures, star field and ionosphere coloration do not alter observations, energy, pointing, drag or propagation. No TEC, electron-density or weather data is invented. Original frame coordinates remain unmodified in exported scenes.

Artifact APIs are read-only, loopback-bound and use opaque discovered IDs, not arbitrary file paths. Every Studio request must name a loopback Host (`127.0.0.1`, `localhost` or `[::1]`), so a page on another name that resolves here can't read artifacts or the run token. Studio replies can only be framed by Studio itself. Symlinked files are excluded. Previews and replay dimensions are bounded (64 MiB scene input, 1,200 times, 20,000 objects, 1,200,000 position samples, 200,000 table rows). These are explicit interactive limits, not a claim to stream arbitrarily large campaigns. Export a time window from larger products.

## Interface

The interface is a React app in `web/ui/`, built only from `@sam/design-system` (vendored at `web/ui/vendor/sam-design-system`): its components, tokens and motion. A missing look becomes a variant in the design system, not a class on a screen. `bun run ui:build` type-checks it and writes the static app to `web/studio/app/`, which the Python service serves at `/`. The built files are committed, so running Studio needs no JavaScript toolchain. `web/studio/` keeps the renderer modules the app drives (`cesium-renderer.js`, `detail.js` and the compute core).

## Checks

```sh
python -m pytest tests/unit/test_studio.py tests/research/test_server.py
npm run test:studio
bun run ui:check   # design-system rules, then the app's unit tests
```

`tests/unit/test_studio.py` fails if `web/studio/app/` is stale against `web/ui/src`; rebuild with `bun run ui:build`.

New adapters belong in `godsat/studio/scene.py`; all presentation belongs in `web/ui/`. Vendor changes must update the pinned version and license. The browser never loads untrusted artifact HTML or executes experiment code.

## Rust core and rendering engine

`rust/studio-core` compiles to a 19 KiB WebAssembly module with no third-party Rust dependencies. It precomputes last-sighting indices once, then computes all object positions, custody ages and states in one packed call per frame. The browser uploads positions to the rendering engine; the renderer runs on the GPU. This does not move Python training, propagation or detector modeling into Rust. If WASM cannot load, a JavaScript reference path remains available.

Rebuild and test:

```sh
rustup target add wasm32-unknown-unknown
python3 scripts/studio/build_wasm.py
cargo test --manifest-path rust/studio-core/Cargo.toml
npm run test:studio
npm run bench:compute
```

The recorded [synthetic CPU microbenchmark](benchmarks/studio-compute-node.json) on this Apple M4 Pro measured about 2.17x faster packed evaluation for 80 objects and 1.89x for 2,000 objects versus the equivalent optimized JavaScript loop. These are warmed Node timings over 5,000 evaluations, using seven alternating trials. They do not establish browser FPS, GPU performance or a speedup to the experimental algorithms. The full benchmark is reproducible in `scripts/studio/benchmark_compute.mjs`.

The default Cesium renderer uses its existing atmospheric scattering, Sun, Moon, terrain/globe lighting, image materials and grid materials. No custom GLSL is written in `cesium-renderer.js`. The cloud layer is a textured shell; the ionosphere is an explicitly qualitative grid shell. Neither is a volumetric plasma or weather solver. The retired standalone Three.js globe and old dashboard have been removed. Single-object demonstrations and whole-system playback are modes within this one application.

Cesium is a browser engine. Unity and Unreal are not bundled. Unity would require a separate WebAssembly build; Unreal Pixel Streaming would add a GPU host and streaming service. The versioned scene contract keeps those possible future renderers separate from scientific data adapters. See [Cesium SkyAtmosphere](https://cesium.com/learn/cesiumjs/ref-doc/SkyAtmosphere.html), [Unity Web compatibility](https://docs.unity.com/en-us/engine/6000.0/manual/platform-specific/webgl/intro/browsercompatibility), and [Unreal Pixel Streaming](https://dev.epicgames.com/documentation/unreal-engine/pixel-streaming-in-unreal-engine).

## Catalog simulation and environmental data

See [simulation framework](simulation-framework.md) for the SGP4 catalog exporter,
explicitly sourced environmental point layers, validation results and remaining
accuracy/scalability work. These extend the same Studio entry point.

### Workspace UI design guidance

The generic workspace was reviewed using [UI/UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill), using its data-dense dashboard guidance. The implementation keeps the Studio's dark surfaces and mint accent, uses system sans-serif text and monospace numeric values, and prioritizes saved collections, searchable inputs, comparable results, and spatial inspection. Marketing conversion layouts returned by the design-system search were excluded because this is a research application.

Shared controls have visible keyboard focus, a skip-to-content link, 44px minimum touch targets on coarse-pointer devices, and reduced-motion styles. The integrated workspace was checked at 375, 768, 1024, and 1440 CSS pixels without page-level horizontal overflow. On narrow screens, setup opens in a collapsible overlay and comparison selectors stack. Collection dates remain file modification dates; no execution status is inferred from folder contents.
