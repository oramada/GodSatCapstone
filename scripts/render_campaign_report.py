"""Regenerate one campaign report and its figures from persisted run outputs."""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from godsat.report import generate


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
