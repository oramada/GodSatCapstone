# Script and documentation review

This review distinguishes a redundant tool from a historical tool that still
supports recorded research. Script count alone does not determine what can be
removed safely.

## Removed

`scripts/archive/download.py` duplicated the supported
`scripts/data/fetch_four_year_data.py` workflow. It selected the latest upstream
revision rather than the committed source pin and could overwrite the local
download manifest. No current source code or test imported it. Use the pinned
fetcher instead; the removed file remains available in Git history at commit
`6274677`.

## Retained

- `scripts/archive/audit.py` is still called by the state-vector finalization
  pipeline to build archive coverage evidence. Removing it would break that
  dependency.
- Payload-only and all-catalogue coverage tools have different populations,
  time bounds and output checks. They are not interchangeable duplicates.
- Sensor-specific analysis, validation and figure tools support distinct earlier
  datasets and reports. They are outside the current workflow but remain useful
  for checking those results.
- Formal verification tools and original-controller probes have separate scopes;
  passing a component probe does not replace a full controller check.

The script audit found no identical Python syntax-tree implementations. This
does not prove that every remaining tool is necessary. Further consolidation
needs a demonstrated replacement and preservation of the relevant checks.

## Documentation clarity

The main reading path is:

1. [Repository overview](../README.md).
2. [Current results and limitations](../reports/README.md).
3. [Setup and command meanings](setup.md).
4. [Exact participant scope](iridium-next-ground-scope.md).

Historical protocol, execution and research-extension pages now identify their
scope at the top. They cannot establish completion of the current NEXT/ground
study. The tool index separates the short current setup from the broader research
tool collection. The setup guide distinguishes data availability, orbital-input
preparation and actual campaign readiness.

Remaining scientific limits are stated rather than hidden: the subsequent NEXT rerun uses an explicit hypothetical ground-tracking role, MEO is disabled, published-baseline reproduction is unverified,
and the draft's numerical gains have not been established.
