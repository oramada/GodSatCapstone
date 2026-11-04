# Iridium NEXT and ground systems

The current rerun tracks the full pinned Iridium NEXT membership using six
hypothetical ground sensors. MEO is disabled. This ground-system role is an
explicit execution assumption adopted for the requested rerun; it was not
provided as a measured sensor specification or an author-supplied architecture.

## Participating systems

- All 80 spacecraft in the pinned dedicated CelesTrak NEXT group, including
  listed spares, are tracking targets. Missing historical elements remain
  unavailable; five of the members lack elements in the earliest training scene.
- Ground sensors are co-located at the published SLRF2020 monument positions for
  Yarragadee, Greenbelt, Haleakala, Changchun, Hartebeesthoek and Wettzell.
- No other LEO constellation, legacy Iridium, debris, rocket bodies, GEO or HEO
  objects are added. No optical/radar sensor payload is assumed aboard NEXT.
- Optional MEO requires a named constellation, pinned membership and a separate
  configuration; it has not been selected or executed.

The [NEXT membership](../configs/iridium-next-membership.json),
[ground-coordinate definitions](../configs/ground-tracking-sites.json) and
[active scope](../configs/active-study-scope.json) are committed. The ground
coordinates and velocities come from the [ILRS SLRF2020 reference](https://ilrs.gsfc.nasa.gov/network/site_information/).
These coordinates do not establish that the real stations can observe NEXT.

## Observation model

Historical NEXT states use past-only SGP4 elements. Applicable station coordinate
solutions are propagated by their published secular velocities. Geocentric ITRS
station positions and normals are rotated into TEME with Astropy and local Earth
orientation data. Station-solution gaps are rejected. Ground boresights rotate
with the Earth between commands. The geometric elevation cutoff is 10 degrees.
The [Astropy satellite-coordinate guide](https://docs.astropy.org/en/stable/coordinates/satellites.html)
explains the TEME/ITRS convention.

Detection, clutter, slew torque/inertia, drive efficiency and power remain the
[documented model assumptions](physical-sensor-assumptions.md). The model has no
weather, illumination, atmospheric refraction or continuous exposure/settling
simulation. Reported energy is modeled pointing energy, not total station or
spacecraft consumption. No measured NEXT ground observations calibrate it.

Dropout suppresses simulated sensor returns while preserving evaluation truth.
Historical ephemeris positions remain available as geometric predictions; this
is not a position-estimation error experiment. Independent loss and persistent
sensor-return outages are distinct processes at the same nominal loss probability.
Their realized accepted-look loss fractions need not be identical. Outages suppress returns while pointing commands can still consume energy; station-wide power or communication failures are not modeled.

## Execution and validation

The default config has six ground agents and all 80 target slots. Training uses
three dated one-hour scenes, development selection one scene, and held-out
validation two separate 2026 scenes. The finite 40-episode training budget does
not establish convergence or continuous four-year operations.

The supported full runner is:

```bash
python -m scripts.experiments.run_iridium_ground_study \
  --output outputs/iridium-next-ground-20261104
```

It registers the plan and source hashes before the experiment; runs the 16/15/31
screen/CCD/BO comparison and five-seed retraining; adds 45 development-only CCD
diagnostic runs with distinct seeds; and evaluates paired observation losses.
The extra diagnostics are not hidden inside the 31-treatment search budget.

Frame/elevation cross-checks precede training. Saved policies are replayed, and
selected action traces are reconstructed independently for visibility, detection,
clutter, true custody and torque work. Actual run results and their limits are
linked from [the results index](../reports/README.md).

The scope gate admits only the configured ground model with matching coordinate
pins. Older orbital-only and mixed-catalogue tasking runners remain excluded.
Earlier membership-check fixtures and mixed-satellite results are historical
artifacts, not performance results for this rerun.
