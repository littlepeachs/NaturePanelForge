#!/usr/bin/env python3
"""Build a panels.csv/json manifest from Codex-split panel outputs."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def resolve_path(path: Path | str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else BASE_DIR / path


def latest_run_dir(run_root: Path, subject: str, topic: str) -> Path:
    root = resolve_path(run_root) / subject / topic
    candidates = sorted(path for path in root.glob("run_*") if path.is_dir())
    if not candidates:
        raise SystemExit(
            "No run directory was provided and none were found under "
            f"{rel(root)}. Pass --run-dir or run scripts/run_demo_paper_to_fullfig.sh first."
        )
    return candidates[-1]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON: {path}")
    return data


def figure_index_from_name(path: Path) -> int:
    match = re.match(r"fig(\d+)_final_spec\.json$", path.name)
    if not match:
        raise ValueError(f"cannot parse figure index from {path.name}")
    return int(match.group(1))


def full_figure_lookup(run_dir: Path) -> dict[tuple[str, int], dict[str, str]]:
    rows = read_csv(run_dir / "FullFigures" / "full_figures.csv")
    lookup: dict[tuple[str, int], dict[str, str]] = {}
    for row in rows:
        paper_id = str(row.get("paper_id") or "").strip()
        try:
            figure_index = int(row.get("figure_index") or 0)
        except (TypeError, ValueError):
            continue
        if paper_id:
            lookup[(paper_id, figure_index)] = row
    return lookup


def build_manifest(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    run_dir = resolve_path(args.run_dir)
    panels_dir = resolve_path(args.panels_dir) if args.panels_dir else run_dir / "Panels_codex_full"
    specs_dir = resolve_path(args.specs_dir) if args.specs_dir else run_dir / "PanelSplitSpecsCodex_full"
    out_csv = resolve_path(args.out_csv) if args.out_csv else panels_dir / "panels.csv"
    out_json = resolve_path(args.out_json) if args.out_json else panels_dir / "panels.json"

    lookup = full_figure_lookup(run_dir)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for spec_path in sorted(specs_dir.glob("*/fig*_final_spec.json")):
        paper_id = spec_path.parent.name
        figure_index = figure_index_from_name(spec_path)
        figure_id = f"{paper_id}__fig{figure_index:02d}"
        full_row = lookup.get((paper_id, figure_index), {})
        try:
            data = load_json(spec_path)
        except Exception as exc:
            skipped.append({"figure_id": figure_id, "spec_path": rel(spec_path), "reason": f"invalid_spec:{type(exc).__name__}"})
            continue

        panels = data.get("panels") or []
        if not isinstance(panels, list):
            skipped.append({"figure_id": figure_id, "spec_path": rel(spec_path), "reason": "panels_not_list"})
            continue

        for ordinal, item in enumerate(panels, start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or f"panel{ordinal:02d}").strip()
            rel_png = str(item.get("relative_path") or "").strip()
            rel_pdf = str(item.get("panel_pdf_path") or "").strip()
            if not rel_png:
                skipped.append({"figure_id": figure_id, "spec_path": rel(spec_path), "reason": f"missing_png:{label}"})
                continue
            png_path = resolve_path(rel_png)
            if not png_path.exists():
                skipped.append({"figure_id": figure_id, "spec_path": rel(spec_path), "reason": f"missing_png_file:{label}", "relative_path": rel_png})
                continue
            pdf_path = resolve_path(rel_pdf) if rel_pdf else Path("")
            rows.append(
                {
                    "figure_id": figure_id,
                    "paper_id": paper_id,
                    "doi": full_row.get("doi", ""),
                    "pmcid": full_row.get("pmcid", ""),
                    "journal": full_row.get("journal", ""),
                    "publication_date": full_row.get("publication_date", ""),
                    "figure_label": full_row.get("figure_label", ""),
                    "figure_index": figure_index,
                    "panel_label": label,
                    "panel_ordinal": ordinal,
                    "relative_path": rel(png_path),
                    "panel_pdf_path": rel(pdf_path) if rel_pdf and pdf_path.exists() else rel_pdf,
                    "source_figure_path": full_row.get("relative_path", ""),
                    "source_figure_pdf_path": full_row.get("figure_pdf_path", ""),
                    "source_figure_url": full_row.get("source_url", ""),
                    "bbox_xyxy": json.dumps(item.get("bbox_xyxy", []), ensure_ascii=False),
                    "split_method": "codex_code_loop",
                    "codex_confidence": item.get("confidence", ""),
                    "review_passed": item.get("review_passed", ""),
                    "all_review_passed": data.get("all_review_passed", ""),
                    "review_rounds": data.get("review_rounds", ""),
                    "edge_check": item.get("edge_check", ""),
                    "figure_caption": full_row.get("caption", ""),
                    "panel_caption": full_row.get("caption", ""),
                    "split_reason": item.get("reason", ""),
                    "final_spec_path": rel(spec_path),
                }
            )

    rows.sort(key=lambda row: (str(row.get("paper_id", "")), int(row.get("figure_index", 0)), int(row.get("panel_ordinal", 0))))
    write_csv(out_csv, rows)
    write_json(out_json, rows)
    write_csv(out_csv.with_name("panels_skipped.csv"), skipped)
    write_json(out_json.with_name("panels_skipped.json"), skipped)
    return rows, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Build panels.csv/json for Panels_codex_full from Codex final specs.")
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--run-root", type=Path, default=BASE_DIR / "PipelineRuns")
    parser.add_argument("--subject", default="biology")
    parser.add_argument("--topic", default="AI_biology")
    parser.add_argument("--panels-dir", type=Path, default=None)
    parser.add_argument("--specs-dir", type=Path, default=None)
    parser.add_argument("--out-csv", type=Path, default=None)
    parser.add_argument("--out-json", type=Path, default=None)
    args = parser.parse_args()
    if args.run_dir is None:
        args.run_dir = latest_run_dir(args.run_root, args.subject, args.topic)

    rows, skipped = build_manifest(args)
    print(json.dumps({"panels": len(rows), "skipped": len(skipped), "out_csv": rel(resolve_path(args.out_csv) if args.out_csv else (resolve_path(args.panels_dir) if args.panels_dir else resolve_path(args.run_dir) / "Panels_codex_full") / "panels.csv")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
