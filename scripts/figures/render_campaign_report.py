"""Regenerate one campaign report and its figures from persisted run outputs."""
from __future__ import annotations

# Support both module execution and direct script paths.
if __package__ in (None, ""):
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))


import argparse
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.report import generate
from godsat.design import FACTORS


def correct_screening_table(report, analyses):
    """Label every effect by its response and include accelerator time."""
    metrics = [key for key in ("objective", "custody_continuity", "slew_energy_proxy",
                              "false_track_proxy", "wall_seconds", "gpu_hours") if key in analyses]
    labels = {"objective": "Objective effect", "custody_continuity": "Custody effect",
              "slew_energy_proxy": "Slew-proxy effect", "false_track_proxy": "False-track effect",
              "wall_seconds": "Runtime effect", "gpu_hours": "GPU-hours effect"}
    table = ["| Factor | " + " | ".join(labels[key] for key in metrics) + " |",
             "|---|" + "---:|" * len(metrics)]
    table += ["| " + factor + " | " + " | ".join(
        f"{analyses[key]['main_effects'][factor]:.6f}" for key in metrics) + " |"
        for factor in FACTORS]
    lines = report.splitlines()
    begin = next(index for index, line in enumerate(lines) if line.startswith("| Factor |"))
    end = begin + 1
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return "\n".join(lines[:begin] + table + lines[end:]) + "\n"


def read_csv(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def render(folder: pathlib.Path) -> None:
    folder = folder.resolve()
    summary = json.loads((folder / "summary.json").read_text())
    analyses = json.loads((folder / "screening_analysis.json").read_text())
    surfaces = json.loads((folder / "response_surfaces.json").read_text())
    design_rows = sorted(read_csv(folder / "rsm_design.csv"), key=lambda row: int(row["run"]))
    response_rows = read_csv(folder / "responses.csv")
    rows_by_name = {row["name"]: row for row in response_rows}
    rsm_rows = []
    for index in range(len(design_rows)):
        name = f"rsm_{index:02d}"
        if name not in rows_by_name:
            raise ValueError(f"Missing persisted treatment response: {name}")
        rsm_rows.append({key: float(value) for key, value in rows_by_name[name].items()
                         if key in analyses and value not in ("", None)})
    local = [[float(row[f"x{index}"]) for index in (1, 2, 3)] for row in design_rows]
    if len(rsm_rows) != int(summary["rsm_runs"]):
        raise ValueError("RSM design, persisted responses, and summary counts disagree")
    generate(folder, None, None, local, rsm_rows, analyses, surfaces, summary)
    report_path = folder / "report.md"
    report = correct_screening_table(report_path.read_text(), analyses)
    provenance = ("**Protocol provenance:** configuration labels such as `paper-exact` do not establish "
                  "exact reproduction. The design PDF referenced by this repository has not been supplied "
                  "in this checkout, so its requirements have not been independently verified.\n\n")
    source_pdf = ROOT / "docs/papers/methodology.pdf"
    if not source_pdf.is_file():
        heading, body = report.split("\n", 1)
        report = heading + "\n\n" + provenance + body.lstrip("\n")
    if (ROOT / "outputs/study-execution/source-inventory/original-framework.json").is_file():
        report = report.replace(
            "The original GoDSAT code, published baseline configuration, and calibrated sensor model were not supplied.",
            "A related local MATLAB/Q-table framework was identified, but its relationship to this actor-critic study has not been verified. An exact baseline configuration and calibrated sensor model are unavailable.")
    report_path.write_text(report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="campaign output folder to render")
    args = parser.parse_args()
    render(pathlib.Path(args.output))
    print(json.dumps({"status": "completed", "output": str(pathlib.Path(args.output).resolve()),
                      "report": str((pathlib.Path(args.output).resolve() / "report.md")),
                      "plots": 6}, indent=2))


if __name__ == "__main__":
    main()
