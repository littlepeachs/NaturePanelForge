#!/usr/bin/env python3
"""Prepare a refined reproduction stage from review-passed first-pass panels."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
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
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


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


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def copy_if_exists(src: Path, dst: Path, *, overwrite: bool) -> str:
    if not src.exists():
        return ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not overwrite:
        return ""
    shutil.copy2(src, dst)
    return rel(dst)


def required_source_files(source_panel_dir: Path) -> list[Path]:
    return [
        source_panel_dir / "target.png",
        source_panel_dir / "reproduce_panel.py",
        source_panel_dir / "reproduce_panel.png",
        source_panel_dir / "reproduce_panel.pdf",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare refined reproduction inputs from review-passed panels.")
    parser.add_argument("--source-data-dir", type=Path, required=True)
    parser.add_argument("--source-reviews-dir", type=Path, required=True)
    parser.add_argument("--source-specs-dir", type=Path, required=True)
    parser.add_argument("--refined-data-dir", type=Path, required=True)
    parser.add_argument("--refined-reviews-dir", type=Path, required=True)
    parser.add_argument("--refined-specs-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def eligible_records(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    source_data_dir = resolve_path(args.source_data_dir)
    source_reviews_dir = resolve_path(args.source_reviews_dir)
    source_specs_dir = resolve_path(args.source_specs_dir)
    records: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []

    for summary_path in sorted(source_reviews_dir.glob("**/reproduce_panel_review_summary.json")):
        panel_rel = summary_path.relative_to(source_reviews_dir).parent
        source_panel_dir = source_data_dir / panel_rel
        source_spec_dir = source_specs_dir / panel_rel
        summary = read_json(summary_path, {})
        if not isinstance(summary, dict):
            ignored.append(
                {
                    "panel_rel": str(panel_rel),
                    "source_summary_path": rel(summary_path),
                    "ignore_reason": "invalid_review_summary_json",
                }
            )
            continue
        if summary.get("review_passed") is not True:
            ignored.append(
                {
                    "panel_rel": str(panel_rel),
                    "source_summary_path": rel(summary_path),
                    "ignore_reason": "review_not_passed",
                }
            )
            continue
        missing = [rel(path) for path in required_source_files(source_panel_dir) if not path.exists()]
        if missing:
            ignored.append(
                {
                    "panel_rel": str(panel_rel),
                    "source_summary_path": rel(summary_path),
                    "ignore_reason": "missing_required_source_files",
                    "missing_paths": ";".join(missing),
                }
            )
            continue
        records.append(
            {
                "panel_rel": panel_rel,
                "subtype": panel_rel.parts[0] if panel_rel.parts else "unknown",
                "panel_id": panel_rel.name,
                "source_panel_dir": source_panel_dir,
                "source_review_dir": source_reviews_dir / panel_rel,
                "source_spec_dir": source_spec_dir,
                "source_review_summary_path": summary_path,
                "source_review_summary": summary,
            }
        )

    total_eligible = len(records)
    if args.limit > 0:
        records = records[: args.limit]
    return records, ignored, total_eligible


def maybe_remove_dir(path: Path, *, overwrite: bool, dry_run: bool) -> None:
    if not overwrite or not path.exists():
        return
    if dry_run:
        return
    shutil.rmtree(path)


def prepare_one(record: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    refined_data_dir = resolve_path(args.refined_data_dir)
    refined_reviews_dir = resolve_path(args.refined_reviews_dir)
    refined_specs_dir = resolve_path(args.refined_specs_dir)

    panel_rel: Path = record["panel_rel"]
    source_panel_dir: Path = record["source_panel_dir"]
    source_review_dir: Path = record["source_review_dir"]
    source_spec_dir: Path = record["source_spec_dir"]

    dest_panel_dir = refined_data_dir / panel_rel
    dest_review_dir = refined_reviews_dir / panel_rel
    dest_spec_dir = refined_specs_dir / panel_rel

    if args.overwrite:
        maybe_remove_dir(dest_panel_dir, overwrite=True, dry_run=args.dry_run)
        maybe_remove_dir(dest_review_dir, overwrite=True, dry_run=args.dry_run)
        maybe_remove_dir(dest_spec_dir, overwrite=True, dry_run=args.dry_run)

    file_copies = [
        (source_panel_dir / "target.png", dest_panel_dir / "target.png"),
        (source_panel_dir / "target.pdf", dest_panel_dir / "target.pdf"),
        (source_panel_dir / "metadata.json", dest_panel_dir / "metadata.json"),
        (source_panel_dir / "qwen_score.json", dest_panel_dir / "qwen_score.json"),
        (source_panel_dir / "qwen_prompt.md", dest_panel_dir / "qwen_prompt.md"),
        (source_panel_dir / "raw_response.txt", dest_panel_dir / "raw_response.txt"),
        (source_panel_dir / "reproduce_panel.py", dest_panel_dir / "reproduce_panel.py"),
        (source_panel_dir / "reproduce_panel.png", dest_panel_dir / "reproduce_panel.png"),
        (source_panel_dir / "reproduce_panel.pdf", dest_panel_dir / "reproduce_panel.pdf"),
        (
            source_review_dir / "reproduce_panel_run_log.md",
            dest_review_dir / "source_reproduce_panel_run_log.md",
        ),
        (
            source_review_dir / "reproduce_panel_review_notes.md",
            dest_review_dir / "source_reproduce_panel_review_notes.md",
        ),
        (
            source_review_dir / "reproduce_panel_review_summary.json",
            dest_review_dir / "source_reproduce_panel_review_summary.json",
        ),
        (
            source_spec_dir / "reproduce_panel_prompt.md",
            dest_spec_dir / "source_reproduce_panel_prompt.md",
        ),
        (
            source_spec_dir / "reproduce_panel_raw_response.txt",
            dest_spec_dir / "source_reproduce_panel_raw_response.txt",
        ),
    ]

    copied: list[str] = []
    if not args.dry_run:
        for src, dst in file_copies:
            copied_path = copy_if_exists(src, dst, overwrite=args.overwrite)
            if copied_path:
                copied.append(copied_path)

        metadata = {
            "stage": "final_polish_refine",
            "panel_id": record["panel_id"],
            "subtype": record["subtype"],
            "source_panel_dir": rel(source_panel_dir),
            "source_review_dir": rel(source_review_dir),
            "source_spec_dir": rel(source_spec_dir),
            "refined_panel_dir": rel(dest_panel_dir),
            "refined_review_dir": rel(dest_review_dir),
            "refined_spec_dir": rel(dest_spec_dir),
            "source_review_summary": record["source_review_summary"],
        }
        write_json(dest_panel_dir / "refine_stage_metadata.json", metadata)

    return {
        "panel_id": record["panel_id"],
        "subtype": record["subtype"],
        "panel_rel": str(panel_rel),
        "source_panel_dir": rel(source_panel_dir),
        "source_review_dir": rel(source_review_dir),
        "source_spec_dir": rel(source_spec_dir),
        "refined_panel_dir": rel(dest_panel_dir),
        "refined_review_dir": rel(dest_review_dir),
        "refined_spec_dir": rel(dest_spec_dir),
        "source_review_rounds_completed": record["source_review_summary"].get("review_rounds_completed"),
        "source_final_assessment": record["source_review_summary"].get("final_assessment", ""),
        "copied_files": ";".join(copied),
    }


def run(args: argparse.Namespace) -> None:
    records, ignored, total_eligible = eligible_records(args)
    rows: list[dict[str, Any]] = []
    refined_data_dir = resolve_path(args.refined_data_dir)
    refined_reviews_dir = resolve_path(args.refined_reviews_dir)
    refined_specs_dir = resolve_path(args.refined_specs_dir)

    for record in records:
        rows.append(prepare_one(record, args))

    panel_dirs = [
        str((refined_data_dir / Path(row["panel_rel"])).resolve())
        for row in rows
    ]

    if not args.dry_run:
        refined_data_dir.mkdir(parents=True, exist_ok=True)
        refined_reviews_dir.mkdir(parents=True, exist_ok=True)
        refined_specs_dir.mkdir(parents=True, exist_ok=True)
        (refined_data_dir / "panel_dirs.txt").write_text(
            "\n".join(panel_dirs) + ("\n" if panel_dirs else ""),
            encoding="utf-8",
        )
        write_csv(refined_data_dir / "manifest.csv", rows)
        write_json(refined_data_dir / "manifest.json", rows)
        write_csv(refined_data_dir / "ignored.csv", ignored)
        write_json(refined_data_dir / "ignored.json", ignored)

    summary = {
        "eligible_panels_found": total_eligible,
        "prepared_panels": len(rows),
        "ignored_panels": len(ignored),
        "by_subtype": dict(Counter(row["subtype"] for row in rows)),
        "source_data_dir": rel(resolve_path(args.source_data_dir)),
        "source_reviews_dir": rel(resolve_path(args.source_reviews_dir)),
        "source_specs_dir": rel(resolve_path(args.source_specs_dir)),
        "refined_data_dir": rel(refined_data_dir),
        "refined_reviews_dir": rel(refined_reviews_dir),
        "refined_specs_dir": rel(refined_specs_dir),
        "overwrite": bool(args.overwrite),
        "dry_run": bool(args.dry_run),
        "limit": args.limit,
    }
    if not args.dry_run:
        summary["outputs"] = {
            "panel_dirs_txt": rel(refined_data_dir / "panel_dirs.txt"),
            "manifest_csv": rel(refined_data_dir / "manifest.csv"),
            "ignored_csv": rel(refined_data_dir / "ignored.csv"),
        }
        write_json(refined_data_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def main() -> int:
    args = parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
