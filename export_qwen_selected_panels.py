#!/usr/bin/env python3
"""Export Qwen-scored schematic and statistical panels for downstream use."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SCORES_CSV = BASE_DIR / "PanelScores" / "panel_scores.csv"
DEFAULT_SCHEMATIC_DIR = BASE_DIR / "Final_Schematic"
DEFAULT_DATA_DIR = BASE_DIR / "Reproduce_Statistical"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def safe_name(value: str) -> str:
    value = (value or "").strip() or "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def parse_float(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text or text.lower() == "null":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_rows(path: Path, limit: int = 0) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"missing scores CSV: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return rows[:limit] if limit else rows


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


def copy_if_exists(src_rel: str, dst: Path) -> str:
    if not src_rel:
        return ""
    src = BASE_DIR / src_rel
    if not src.exists():
        return ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return rel(dst)


def copy_sibling_if_exists(src_rel: str, sibling_name: str, dst: Path) -> str:
    if not src_rel:
        return ""
    src = (BASE_DIR / src_rel).with_name(sibling_name)
    if not src.exists():
        return ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return rel(dst)


def export_panel(
    row: dict[str, str],
    out_dir: Path,
    *,
    selection_category: str,
    selection_reason: str,
) -> dict[str, Any]:
    panel_id = safe_name(row.get("panel_id") or "unknown_panel")
    out_dir.mkdir(parents=True, exist_ok=True)

    image_path = copy_if_exists(row.get("relative_path", ""), out_dir / "target.png")
    pdf_path = copy_if_exists(row.get("panel_pdf_path", ""), out_dir / "target.pdf")
    score_path = copy_if_exists(row.get("score_path", ""), out_dir / "qwen_score.json")
    prompt_path = copy_if_exists(row.get("prompt_path", ""), out_dir / "qwen_prompt.md")
    raw_response_path = copy_sibling_if_exists(row.get("score_path", ""), "raw_response.txt", out_dir / "raw_response.txt")

    metadata = {
        **row,
        "panel_id": panel_id,
        "selection_category": selection_category,
        "selection_reason": selection_reason,
        "export_dir": rel(out_dir),
        "curated_image_path": image_path,
        "curated_pdf_path": pdf_path,
        "export_score_path": score_path,
        "export_prompt_path": prompt_path,
        "export_raw_response_path": raw_response_path,
    }
    metadata_path = out_dir / "metadata.json"
    write_json(metadata_path, metadata)
    metadata["export_metadata_path"] = rel(metadata_path)
    return metadata


def summarize_counts(
    rows: list[dict[str, str]],
    schematic_rows: list[dict[str, Any]],
    data_rows: list[dict[str, Any]],
    ignored_rows: list[dict[str, Any]],
    *,
    min_data_purity_score: float,
    min_code_reproducibility_score: float,
    min_aesthetic_score: float,
) -> dict[str, Any]:
    return {
        "input_rows": len(rows),
        "selected_schematic": len(schematic_rows),
        "selected_data_statistical": len(data_rows),
        "ignored": len(ignored_rows),
        "data_selection_thresholds": {
            "min_data_purity_score": min_data_purity_score,
            "min_code_reproducibility_score": min_code_reproducibility_score,
            "min_aesthetic_score": min_aesthetic_score,
        },
        "input_by_category": dict(Counter((row.get("category") or "unknown") for row in rows)),
        "selected_data_by_subtype": dict(Counter((row.get("data_subtype") or "other_data_display") for row in data_rows)),
    }


def data_selection_failure_reason(row: dict[str, str], args: argparse.Namespace) -> str | None:
    data_purity_score = parse_float(row.get("data_purity_score"))
    code_reproducibility_score = parse_float(row.get("code_reproducibility_score"))
    aesthetic_score = parse_float(row.get("aesthetic_score"))

    checks = [
        ("data_purity_score", data_purity_score, args.min_data_purity_score),
        ("code_reproducibility_score", code_reproducibility_score, args.min_code_reproducibility_score),
        ("aesthetic_score", aesthetic_score, args.min_aesthetic_score),
    ]
    failed: list[str] = []
    for name, value, threshold in checks:
        if value is None:
            failed.append(f"{name}=missing<threshold={threshold:g}")
        elif value < threshold:
            failed.append(f"{name}={value:g}<threshold={threshold:g}")
    if failed:
        return "data_threshold_failed:" + ";".join(failed)
    return None


def run(args: argparse.Namespace) -> None:
    scores_csv = Path(args.scores_csv)
    if not scores_csv.is_absolute():
        scores_csv = BASE_DIR / scores_csv
    schematic_dir = Path(args.schematic_dir)
    if not schematic_dir.is_absolute():
        schematic_dir = BASE_DIR / schematic_dir
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = BASE_DIR / data_dir

    if args.overwrite and schematic_dir.exists():
        shutil.rmtree(schematic_dir)
    if args.overwrite and data_dir.exists():
        shutil.rmtree(data_dir)
    schematic_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    rows = load_rows(scores_csv, args.limit)
    schematic_rows: list[dict[str, Any]] = []
    data_rows: list[dict[str, Any]] = []
    ignored_rows: list[dict[str, Any]] = []
    panel_dirs: list[str] = []

    for row in rows:
        category = (row.get("category") or "").strip()
        panel_id = safe_name(row.get("panel_id") or "unknown_panel")
        if category == "schematic":
            exported = export_panel(
                row,
                schematic_dir / panel_id,
                selection_category="schematic",
                selection_reason="qwen_category=schematic",
            )
            schematic_rows.append(exported)
            continue
        if category == "data_statistical":
            failure_reason = data_selection_failure_reason(row, args)
            if failure_reason is not None:
                ignored_rows.append({**row, "ignore_reason": failure_reason})
                continue
            subtype = safe_name(row.get("data_subtype") or "other_data_display")
            panel_dir = data_dir / subtype / panel_id
            exported = export_panel(
                row,
                panel_dir,
                selection_category="data_statistical",
                selection_reason=(
                    "qwen_category=data_statistical"
                    f";data_purity_score>={args.min_data_purity_score:g}"
                    f";code_reproducibility_score>={args.min_code_reproducibility_score:g}"
                    f";aesthetic_score>={args.min_aesthetic_score:g}"
                ),
            )
            exported["codex_subtype"] = row.get("data_subtype") or "other_data_display"
            exported["panel_dir"] = str(panel_dir.resolve())
            data_rows.append(exported)
            panel_dirs.append(str(panel_dir.resolve()))
            continue
        ignored_rows.append(
            {
                **row,
                "ignore_reason": f"category_not_selected:{category or 'unknown'}",
            }
        )

    write_csv(schematic_dir / "manifest.csv", schematic_rows)
    write_json(schematic_dir / "manifest.json", schematic_rows)
    write_json(
        schematic_dir / "summary.json",
        {
            "selected_schematic": len(schematic_rows),
            "outputs": {
                "manifest_csv": "manifest.csv",
                "manifest_json": "manifest.json",
            },
        },
    )

    write_csv(data_dir / "manifest.csv", data_rows)
    write_json(data_dir / "manifest.json", data_rows)
    write_csv(data_dir / "agent_queue.csv", data_rows)
    write_csv(data_dir / "ignored.csv", ignored_rows)
    write_json(data_dir / "ignored.json", ignored_rows)
    (data_dir / "panel_dirs.txt").write_text("\n".join(panel_dirs) + ("\n" if panel_dirs else ""), encoding="utf-8")
    summary = summarize_counts(
        rows,
        schematic_rows,
        data_rows,
        ignored_rows,
        min_data_purity_score=args.min_data_purity_score,
        min_code_reproducibility_score=args.min_code_reproducibility_score,
        min_aesthetic_score=args.min_aesthetic_score,
    )
    summary["outputs"] = {
        "schematic_manifest_csv": rel(schematic_dir / "manifest.csv"),
        "data_manifest_csv": rel(data_dir / "manifest.csv"),
        "data_agent_queue_csv": rel(data_dir / "agent_queue.csv"),
        "data_panel_dirs_txt": rel(data_dir / "panel_dirs.txt"),
        "ignored_csv": rel(data_dir / "ignored.csv"),
    }
    write_json(data_dir / "summary.json", summary)
    print(json.dumps({**summary, "schematic_dir": rel(schematic_dir), "data_dir": rel(data_dir)}, ensure_ascii=False, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Qwen-selected schematic and statistical panels.")
    parser.add_argument("--scores-csv", default=rel(DEFAULT_SCORES_CSV))
    parser.add_argument("--schematic-dir", default=rel(DEFAULT_SCHEMATIC_DIR))
    parser.add_argument("--data-dir", default=rel(DEFAULT_DATA_DIR))
    parser.add_argument("--min-data-purity-score", type=float, default=10.0)
    parser.add_argument("--min-code-reproducibility-score", type=float, default=9.0)
    parser.add_argument("--min-aesthetic-score", type=float, default=8.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
