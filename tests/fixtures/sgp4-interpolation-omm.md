# Interpolation regression catalog

`sgp4-interpolation-omm.json` contains 12 public GP records selected from the
CelesTrak active catalog downloaded on 2026-11-08 at 19:23:11 UTC:
https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json

Full input SHA-256:
`def22a47c49a0300c83401b7fd20f625c3b148d6e11b3d6bbb74fc8e49ad51f3`

Selection includes the three lowest and highest eccentricities and mean motions
among continuously valid objects in the saved 18:55–19:05 UTC test window.
The regression compares display interpolation with direct SGP4 position
evaluation. No record is ground-truth orbit determination or measured telemetry.
