# Display assets

- `earth-day.jpg`: Three.js example `earth_atmos_2048.jpg`, retrieved 2026-11-06 from https://threejs.org/examples/textures/planets/earth_atmos_2048.jpg
- `earth-clouds.png`: Three.js example `earth_clouds_1024.png`, retrieved 2026-11-06 from https://threejs.org/examples/textures/planets/earth_clouds_1024.png
- The distribution is covered by the Three.js MIT license in `../vendor/THREE-LICENSE.txt`; these are example textures, not remotely requested at runtime.
- `../vendor/three.module.js`: unmodified Three.js 0.160.1, retrieved from https://cdn.jsdelivr.net/npm/three@0.160.1/build/three.module.js . License included adjacent to it.

Textures are static visual context, not weather, surface or cloud measurements at the replay epoch. The procedural moon texture is an illustrative crater pattern, not a lunar map. No external texture or script requests occur during use.

- `iridium-illustrative.gltf`: original procedural model built for this studio; simplified body, antenna and solar arrays. Not manufacturer CAD or measured geometry.
- `../vendor/cesium/`: CesiumJS 1.147.0 browser distribution, Apache-2.0, with its LICENSE and third-party notices. Built-in atmosphere/material/lighting shaders are used by the default renderer. Download source: https://registry.npmjs.org/cesium/-/cesium-1.147.0.tgz .
- `../wasm/godsat_studio_core.wasm`: built from `rust/studio-core`, not a third-party binary. Rebuild with `python3 scripts/studio/build_wasm.py` from the repository root.
