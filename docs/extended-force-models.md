# Extended numerical force models

These optional terms extend `godsat.simulation.numerical`, not SGP4. Supply
osculating GCRS initial states with provenance. Catalog mean elements and
unknown spacecraft properties are never converted or filled in implicitly.

```sh
python -m godsat.simulation.numerical \
  --initial configs/numerical-extended.json \
  --output outputs/extended-example/scene.json

# Includes the existing NRLMSIS drag model with a pinned local driver file.
python -m scripts.studio.benchmark_extended_forces --objects 1000 \
  --drivers data/environment/space-weather.csv
```

`configs/numerical-extended.json` uses synthetic initial states and hypothetical
mass, effective radiation area and reflectivity. Drag is off in this standalone
example. Set `forces.drag=true` and supply `--space-weather` to enable it.

## Radiation and eclipse

`forces.solar_radiation_pressure=true` requires positive `mass_kg`,
`radiation_area_m2`, and `radiation_coefficient` on every spacecraft. Area is
constant effective projected area; it is not calculated from the displayed model.
The coefficient is the dimensionless cannonball Cr, not the drag coefficient.
Acceleration points away from the instantaneous geometric Sun, scales as
inverse square distance, and uses 4.56e-6 N/m² at one astronomical unit.
Distance units are km; SI acceleration is converted to km/s² once.

The spherical Earth and finite solar disc define full illumination, penumbra,
umbra and annular cases through apparent angular-disc overlap. A uniform solar
disc is assumed. The source records the pressure, astronomical unit, solar radius
and illumination extrema at RK stages. It does not supply eclipse entry/exit
events: test smaller integration steps at transitions. No lunar occultation,
limb darkening, atmospheric refraction, albedo, thermal recoil or attitude-dependent
box-wing response is included. The pressure is a conventional constant, not a
measurement of solar irradiance at the experiment epoch.

Model equation and shadow convention:
[SatKit force-model documentation](https://satkit.dev/guide/forces/#solar-radiation-pressure),
which cites Montenbruck & Gill, *Satellite Orbits*, §3.4.

## Zonal gravity

`forces.zonal_gravity=true` replaces the default monopole/J2 model. Supply
`gravity_model.reference`, `mu_km3_s2`, `reference_radius_km`,
`normalization="unnormalized_Jn"`, and a `coefficients` map keyed by degrees
`"2"` through `"8"`. Omitted degrees are zero. `forces.j2=true` is rejected
in this mode to prevent applying J2 twice.

The acceleration is the analytic gradient of
`U = mu/r * [1 - sum(Jn * (R/r)^n * Pn(z/r))]`, evaluated in Earth-fixed axes
and rotated back to GCRS at each integration stage. Legendre polynomials and
their derivatives use recurrences that stay finite at the poles. Coefficients
are unnormalized Jn; fully normalized coefficients must be converted using
`Jn = -sqrt(2n+1) * Cbar(n,0)` before input. The sample's WGS-84 constants and
J2/J3/J4 values follow
[Vallado et al., Revisiting Spacetrack Report #3](https://celestrak.org/publications/AIAA/2006-6753/AIAA-2006-6753-Rev3.pdf).
This is a zonal truncation, not a complete WGS-84 gravity field. Tesseral,
sectoral and time-variable coefficients, tides and polar-motion gravity terms
are absent.

## Relativity

`forces.schwarzschild=true` adds the spherical first post-Newtonian correction
from [IERS Conventions 2010, §10.3, equation 10.12 first line](https://iers-conventions.obspm.fr/content/chapter10/tn36_c10.pdf),
with beta=gamma=1:

`a = mu/(c² r³) * [(4 mu/r - v·v) r + 4(r·v) v]`.

It uses the selected gravity model's mu and geocentric position/velocity, with
`c=299792.458 km/s`. Frame dragging, de Sitter precession and relativistic
multipoles are absent. The integrator still advances the existing UTC-labelled
elapsed-second grid; this is not a full TT/TCG coordinate-time implementation.
Consequently the term is useful for controlled force-sensitivity experiments,
not a claim of precise relativistic orbit determination.

## Verification and limits

Tests compare zonal accelerations against numerical derivatives of an independent
Legendre-series potential, including both poles and degrees 2–8. J2 also agrees
with the existing closed-form implementation. Solar pressure tests check units,
force direction, inverse-square scaling and zero umbra force. Penumbra fractions
are compared with independent numerical integration of the occulted disc area.
Relativity tests use the circular-orbit analytic limit and rotation covariance.

The benchmark runs 1,000 synthetic spacecraft with all three additions and the
existing drag/Sun/Moon models. It exports a normal Studio scene plus configuration,
source hashes, machine timing, 16-object paired force sensitivities and step-size
comparisons. The compact recorded result is `benchmarks/extended-forces-1000.json`.
The sensitivities are differences between model predictions. Convergence and
reference agreement do not establish absolute accuracy against real orbits.
