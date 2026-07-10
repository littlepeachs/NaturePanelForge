#!/usr/bin/env python3
"""Summarize SciFigure2Code zero-shot benchmark run directories."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


P0_FIELDS = (
    "execution_pass_rate",
    "overall_visual_fidelity",
    "chart_type_consistency",
    "layout_consistency",
    "data_pattern_fidelity",
    "text_label_fidelity",
    "axis_fidelity",
    "legend_colorbar_completeness",
    "component_completeness",
    "clarity_overlap_score",
)

P1_FIELDS = (
    "style_consistency",
    "color_consistency",
    "typography_quality",
    "scientific_label_fidelity",
    "panel_context_fidelity",
    "caption_consistency",
    "code_editability",
    "re_render_stability",
)

P2_FIELDS = (
    "pixel_similarity",
    "clip_similarity",
    "code_similarity_to_reference",
    "runtime_efficiency",
    "library_api_appropriateness",
    "judge_agreement",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--run-label", default=None, help="Only summarize logs/output dirs containing this run label.")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    run_root = Path(args.run_root).expanduser()
    rows = []
    for time_path in sorted((run_root / "logs").glob("*.time.json")):
        if args.run_label and args.run_label not in time_path.name:
            continue
        time_info = _load_json(time_path)
        rows.append(_row_from_time(time_info))

    output = Path(args.output) if args.output else run_root / (
        f"zeroshot_summary_{args.run_label}.csv" if args.run_label else "zeroshot_summary.csv"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = _columns()
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    json_path = output.with_suffix(".json")
    json_path.write_text(json.dumps({"run_root": str(run_root), "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"summary_csv={output}")
    print(f"summary_json={json_path}")
    return 0


def _row_from_time(time_info: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(str(time_info.get("output_dir", "")))
    summary_json = output_dir / "summary.json"
    aggregate: dict[str, Any] = {}
    total_samples = None
    if summary_json.exists():
        payload = _load_json(summary_json)
        aggregate = payload.get("aggregate", {})
        total_samples = payload.get("total_samples")

    row: dict[str, Any] = {
        "model_id": time_info.get("model_id"),
        "mode": time_info.get("mode"),
        "prompt_style": time_info.get("prompt_style"),
        "limit": time_info.get("limit"),
        "samples": total_samples,
        "status": time_info.get("status"),
        "returncode": time_info.get("returncode"),
        "elapsed_seconds": time_info.get("elapsed_seconds"),
        "elapsed_minutes": _round(float(time_info.get("elapsed_seconds") or 0) / 60.0),
        "avg_score": _mean(aggregate.get("leaderboard_score")),
        "output_dir": str(output_dir),
        "summary_json": str(summary_json) if summary_json.exists() else "",
        "log_file": time_info.get("log_file"),
    }
    _add_metric_group(row, "p0", P0_FIELDS, aggregate.get("p0_core", {}))
    _add_metric_group(row, "p1", P1_FIELDS, aggregate.get("p1_diagnostic", {}))
    _add_metric_group(row, "p2", P2_FIELDS, aggregate.get("p2_auxiliary", {}))
    return row


def _add_metric_group(row: dict[str, Any], prefix: str, fields: tuple[str, ...], payload: Any) -> None:
    payload = payload if isinstance(payload, dict) else {}
    for field in fields:
        row[f"{prefix}_{field}"] = _mean(payload.get(field))


def _mean(value: Any) -> float | None:
    if isinstance(value, dict) and isinstance(value.get("mean"), (int, float)):
        return _round(float(value["mean"]))
    if isinstance(value, (int, float)):
        return _round(float(value))
    return None


def _round(value: float) -> float:
    return round(value, 4)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _columns() -> list[str]:
    base = [
        "model_id",
        "mode",
        "prompt_style",
        "limit",
        "samples",
        "status",
        "returncode",
        "elapsed_seconds",
        "elapsed_minutes",
        "avg_score",
    ]
    metrics = [f"p0_{field}" for field in P0_FIELDS]
    metrics += [f"p1_{field}" for field in P1_FIELDS]
    metrics += [f"p2_{field}" for field in P2_FIELDS]
    return base + metrics + ["output_dir", "summary_json", "log_file"]


if __name__ == "__main__":
    raise SystemExit(main())
