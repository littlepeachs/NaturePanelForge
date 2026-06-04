#!/usr/bin/env python3
"""Copy review-passed reproduced statistical panels into gallery/<subject>/<topic>/<subtype>/."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def resolve_path(path: Path | str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else BASE_DIR / path


def latest_run_dir(subject: str, topic: str) -> Path:
    run_root = BASE_DIR / "PipelineRuns" / subject / topic
    candidates = sorted(path for path in run_root.glob("run_*") if path.is_dir())
    if not candidates:
        raise SystemExit(
            "No run directory was provided and none were found under "
            f"{rel(run_root)}. Pass --run-dir or run scripts/run_demo_paper_to_fullfig.sh first."
        )
    return candidates[-1]


def safe_name(value: str) -> str:
    value = (value or "").strip() or "unknown"
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export review-passed reproduced panels to gallery.")
    parser.add_argument(
        "--run-dir",
        type=Path,
        action="append",
        default=None,
    )
    parser.add_argument("--subject", default="biology")
    parser.add_argument("--topic", default="AI_biology")
    parser.add_argument("--gallery-root", type=Path, default=BASE_DIR / "gallery")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--all-refined", action="store_true", help="Export every complete panel under Reproduce_Statistical_Refined.")
    parser.add_argument("--refined-only", action="store_true", help="Export only review-passed panels from Reproduce_Statistical_Refined.")
    return parser.parse_args()


def collect_candidates_for_run(run_dir: Path, run_order: int, *, refined_only: bool = False) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    source_sets = [
        (
            "refined",
            run_dir / "Reproduce_Statistical_Refined",
            run_dir / "Reproduce_Statistical_Refined_Reviews",
            run_dir / "Reproduce_Statistical_Refined_Specs",
        ),
        (
            "main",
            run_dir / "Reproduce_Statistical",
            run_dir / "Reproduce_Statistical_Reviews",
            run_dir / "Reproduce_Statistical_Specs",
        ),
        (
            "test15",
            run_dir / "Reproduce_Statistical_test15",
            run_dir / "Reproduce_Statistical_Reviews_test15",
            run_dir / "Reproduce_Statistical_Specs_test15",
        ),
    ]
    if refined_only:
        source_sets = source_sets[:1]
    for source_name, data_root, review_root, spec_root in source_sets:
        if not data_root.exists() or not review_root.exists():
            continue
        for summary_path in review_root.glob("**/reproduce_panel_review_summary.json"):
            rel_review = summary_path.relative_to(review_root)
            panel_rel = rel_review.parent
            panel_id = panel_rel.name
            subtype = panel_rel.parent.name if str(panel_rel.parent) != "." else "other_data_display"
            panel_dir = data_root / panel_rel
            review_dir = review_root / panel_rel
            spec_dir = spec_root / panel_rel if spec_root.exists() else None
            try:
                summary = load_json(summary_path)
            except Exception:
                continue
            if summary.get("review_passed") is not True:
                continue
            required = [
                panel_dir / "metadata.json",
                panel_dir / "reproduce_panel.py",
                panel_dir / "reproduce_panel.png",
                panel_dir / "reproduce_panel.pdf",
                review_dir / "reproduce_panel_run_log.md",
                review_dir / "reproduce_panel_review_notes.md",
                review_dir / "reproduce_panel_review_summary.json",
            ]
            if not all(path.exists() for path in required):
                continue
            priority = 1 if source_name == "main" else 0
            if source_name == "refined":
                priority = 2
            existing = records.get(panel_id)
            if existing is not None and existing["priority"] >= priority:
                continue
            records[panel_id] = {
                "panel_id": panel_id,
                "subtype": safe_name(subtype),
                "panel_dir": panel_dir,
                "review_dir": review_dir,
                "spec_dir": spec_dir,
                "summary": summary,
                "source_set": source_name,
                "priority": priority,
                "run_order": run_order,
                "run_dir": run_dir,
            }
    return records


def collect_all_refined_for_run(run_dir: Path, run_order: int) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    data_root = run_dir / "Reproduce_Statistical_Refined"
    review_root = run_dir / "Reproduce_Statistical_Refined_Reviews"
    spec_root = run_dir / "Reproduce_Statistical_Refined_Specs"
    if not data_root.exists():
        return records

    for panel_dir in sorted(path for path in data_root.glob("*/*") if path.is_dir()):
        panel_rel = panel_dir.relative_to(data_root)
        panel_id = panel_rel.name
        subtype = panel_rel.parent.name if str(panel_rel.parent) != "." else "other_data_display"
        review_dir = review_root / panel_rel
        spec_dir = spec_root / panel_rel if spec_root.exists() else None
        required = [
            panel_dir / "metadata.json",
            panel_dir / "reproduce_panel.py",
            panel_dir / "reproduce_panel.png",
            panel_dir / "reproduce_panel.pdf",
        ]
        if not all(path.exists() for path in required):
            continue

        summary: dict[str, Any] = {}
        for summary_path in [
            review_dir / "reproduce_panel_review_summary.json",
            review_dir / "source_reproduce_panel_review_summary.json",
        ]:
            if summary_path.exists():
                try:
                    summary = load_json(summary_path)
                    break
                except Exception:
                    summary = {}

        records[panel_id] = {
            "panel_id": panel_id,
            "subtype": safe_name(subtype),
            "panel_dir": panel_dir,
            "review_dir": review_dir,
            "spec_dir": spec_dir,
            "summary": summary,
            "source_set": "refined",
            "priority": 2,
            "run_order": run_order,
            "run_dir": run_dir,
        }
    return records


def collect_candidates(run_dirs: list[Path], *, all_refined: bool = False, refined_only: bool = False) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for run_order, run_dir in enumerate(run_dirs):
        current = (
            collect_all_refined_for_run(run_dir, run_order)
            if all_refined
            else collect_candidates_for_run(run_dir, run_order, refined_only=refined_only)
        )
        for panel_id, record in current.items():
            existing = records.get(panel_id)
            if existing is None:
                records[panel_id] = record
                continue
            existing_key = (existing.get("priority", -1), existing.get("run_order", -1))
            current_key = (record.get("priority", -1), record.get("run_order", -1))
            if current_key >= existing_key:
                records[panel_id] = record
    return records


def copy_tree_files(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in sorted(src_dir.iterdir()):
        if item.is_file():
            shutil.copy2(item, dst_dir / item.name)


def export_gallery(args: argparse.Namespace) -> dict[str, Any]:
    run_dirs = [resolve_path(path) for path in args.run_dir] if args.run_dir else [latest_run_dir(args.subject, args.topic)]
    gallery_topic_dir = resolve_path(args.gallery_root) / args.subject / args.topic
    candidates = collect_candidates(run_dirs, all_refined=args.all_refined, refined_only=args.refined_only)
    exported_rows: list[dict[str, Any]] = []

    for panel_id in sorted(candidates):
        record = candidates[panel_id]
        panel_dir = record["panel_dir"]
        review_dir = record["review_dir"]
        spec_dir = record.get("spec_dir")
        subtype = record["subtype"]
        dst_dir = gallery_topic_dir / subtype / panel_id
        if dst_dir.exists() and args.overwrite:
            shutil.rmtree(dst_dir)
        dst_dir.mkdir(parents=True, exist_ok=True)

        copy_tree_files(panel_dir, dst_dir)
        copy_tree_files(review_dir, dst_dir)
        if isinstance(spec_dir, Path) and spec_dir.exists():
            copy_tree_files(spec_dir, dst_dir)

        gallery_record = {
            "panel_id": panel_id,
            "subtype": subtype,
            "source_run_dir": rel(record["run_dir"]),
            "source_set": record["source_set"],
            "source_panel_dir": rel(panel_dir),
            "source_review_dir": rel(review_dir),
            "source_spec_dir": rel(spec_dir) if isinstance(spec_dir, Path) else "",
            "gallery_dir": rel(dst_dir),
            "review_passed": record["summary"].get("review_passed"),
            "review_rounds_completed": record["summary"].get("review_rounds_completed"),
            "max_review_rounds": record["summary"].get("max_review_rounds"),
            "final_assessment": record["summary"].get("final_assessment", ""),
        }
        write_json(dst_dir / "gallery_record.json", gallery_record)
        exported_rows.append(gallery_record)

    write_csv(gallery_topic_dir / "manifest.csv", exported_rows)
    write_json(gallery_topic_dir / "manifest.json", exported_rows)
    summary = {
        "run_dirs": [rel(path) for path in run_dirs],
        "gallery_dir": rel(gallery_topic_dir),
        "exported_panels": len(exported_rows),
        "subtypes": sorted({row["subtype"] for row in exported_rows}),
    }
    write_json(gallery_topic_dir / "summary.json", summary)
    return summary


def main() -> int:
    args = parse_args()
    summary = export_gallery(args)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
