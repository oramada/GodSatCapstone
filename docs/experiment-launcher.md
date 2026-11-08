# Local experiment launcher

Choose **Experiment** in Studio. The panel supports generated synthetic circular
constellations or saved `godsat.numerical.v1` initial-state files. Set epoch,
duration, integration step and output cadence; select gravity, third bodies,
solar radiation, relativity and atmospheric drag; then **Validate** and **Run**.
A completed job can be opened as a normal scene without reloading the page.

Generated states are explicitly illustrative. For saved inputs, the original
osculating coordinates and provenance are retained. Spacecraft properties are
changed only when **Override every spacecraft** is checked. A saved zonal model
can be preserved; the alternate WGS-84 preset uses the supplied J2–J4 constants.
The epoch field applies to the supplied Cartesian state, not a propagation of
that state to a different epoch. Neither workflow treats catalog TLE mean
parameters as osculating elements.

Atmospheric drag requires a local space-weather CSV selected by opaque catalog
ID. Validation checks every touched 3-hour driver bin and requires installed
Astropy/pymsis dependencies. The worker copies the selected driver snapshot and
records its original path and hash, so later edits cannot change a running job.
Density still uses the existing bounded NRLMSIS adapter; a trajectory outside its
valid domain fails rather than substituting density. Displayed clouds, magnetic
vectors and TEC layers do not become numerical drag forces.

The launcher permits one worker at a time, at most 2,000 spacecraft and 2,000,000
spacecraft integration steps, and the existing scene-size limits. An independent
timer kills workers exceeding 180 seconds even if the browser stops polling.
Cancel terminates the subprocess. Start-up and model evaluation time depend on
the local machine; progress is a running/finished state and elapsed time, not an
invented percentage.

Each run uses a new `outputs/studio-runs/<random-id>/` directory. It contains the
exact initial configuration, a worker log, optional driver snapshot, result
metadata, and a scene only when successfully generated. Existing artifacts are
not edited. Status polling and the result's scene ID are available to Studio;
a completed scene enters the regular catalog. In-memory job lookup lasts for
the server session, while the saved artifacts persist across server restarts.

The API adds GET `experiments/options`, `experiments/template`, and
`experiments/job`, plus POST `experiments/validate`, `experiments/run`, and
`experiments/cancel`, under `/api/studio/`. Mutation requests require a loopback
Host, matching Origin when supplied, JSON content type, a bounded request body,
and a random per-server token. Execution uses a fixed Python worker module and
server-chosen output paths; no caller shell command or arbitrary write path is
accepted. This is a local research tool, not a multi-user job scheduler.
