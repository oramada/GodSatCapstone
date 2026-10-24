# Research result snapshots

These reports were copied from the local study workspace as compact, reviewable records. Their source code is in `scripts/`; large Parquet files, image archives, scenario arrays, model checkpoints, and full run outputs are not stored in this repository. Results are tied to the source snapshots and assumptions stated in each report.

- [Paper-study execution report](full-paper-study/final_execution_report.md) and [campaign report](full-paper-study/report.md)
- [Four-regime active-host campaign report](all-orbits-paper-exact-active-hosts/report.md), with its figures and integrity audit
- [DUST annotated-track orbit comparison](dust-tle-track-validation/report.md), with the saved independent audit
- [Four-year simulated dropout report](four-year-quarterly-dropout-v6-active-hosts/dropout_report.md), with its integrity audit
- [Full-catalog weekly tasking audit](full-catalog-tasking-weekly/independent_audit.json)
- [Consolidated system audit](full-system-audit.json)

Interpret these as results of this implementation, not as reproduced claims from the supplied paper. Orbital histories are derived from public element data; several observation and sensor-failure quantities are proxies or simulation assumptions. See [the study protocol](../study-protocol.md) and the individual reports before citing any number.
