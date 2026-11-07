# Experiment Studio

The repository frontend is now **GoDSAT Experiment Studio**. Its default globe renderer is CesiumJS 1.147.0, with a Rust/WebAssembly CPU core. Three.js supplies only the embedded spacecraft close-up using standard PBR materials; it is not a separate visualization. It uses one 3D renderer for a single target, all exported objects in a run, and deliberately illustrative teaching scenes. Studio is the sole application. Old `/legacy`, `/index.html` and `/studio/` links redirect to `/`.

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

- **Single example / Whole system**: one focused target plus sensors, or all exported objects. The built-in examples use one or all 80 pinned Iridium NEXT names and one or six configured stations. Their geometry and observations are constructed, not an experimental result.
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

The API is read-only, loopback-bound and uses opaque discovered IDs, not arbitrary file paths. Symlinked files are excluded. Previews and replay dimensions are bounded (64 MiB scene input, 1,200 times, 2,000 objects, 200,000 table rows). These are explicit interactive limits, not a claim to stream arbitrarily large campaigns. Export a time window from larger products.

## Checks

```sh
python -m pytest tests/unit/test_studio.py tests/research/test_server.py
npm run test:studio
```

New adapters belong in `godsat/studio/scene.py`; all presentation belongs in `web/studio/`. Vendor changes must update the pinned version and license. The browser never loads untrusted artifact HTML or executes experiment code.

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
