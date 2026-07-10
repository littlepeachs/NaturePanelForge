"""Build the 8-metric tiny benchmark report from run artifacts and AI judge JSON.

This script intentionally does not call an AI model itself. It writes per-mode
judge request packets, then merges JSON returned by an external judge session.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


MODES = ("zeroshot", "cot", "oneshot", "oneshot_cot")

AI_METRICS = (
    "overall_visual_fidelity",
    "chart_type_consistency",
    "layout_component_consistency",
    "data_pattern_fidelity",
    "text_scientific_label_fidelity",
    "axis_legend_colorbar_fidelity",
    "clarity_typography_quality",
)

ALL_METRICS = ("valid_code_rate", *AI_METRICS)

RUBRIC = {
    "overall_visual_fidelity": {
        "scale": "0-100",
        "definition": "Overall visual and semantic similarity between target and generated figure.",
    },
    "chart_type_consistency": {
        "scale": "0/1/2",
        "definition": "Whether all primary and secondary chart types match.",
    },
    "layout_component_consistency": {
        "scale": "0/1/2",
        "definition": "Whether subplot layout, insets, legends, colorbars, annotations, and component placement match.",
    },
    "data_pattern_fidelity": {
        "scale": "0/1/2",
        "definition": "Whether trends, distributions, heatmap hotspots, clusters, and statistical patterns are preserved.",
    },
    "text_scientific_label_fidelity": {
        "scale": "0/1/2",
        "definition": "Whether titles, labels, annotations, units, symbols, and scientific names are preserved.",
    },
    "axis_legend_colorbar_fidelity": {
        "scale": "0/1/2",
        "definition": "Whether axis scales/ranges/ticks plus legend/colorbar content and mapping are correct.",
    },
    "clarity_typography_quality": {
        "scale": "0/1/2",
        "definition": "Whether the figure is legible, unclipped, and free of damaging text/element overlap.",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create SciFigure2Code 8-metric report.")
    parser.add_argument("--run-root", required=True, help="Run root containing zeroshot/cot/oneshot/oneshot_cot subdirs.")
    parser.add_argument("--judge-dir", default=None, help="Directory containing <mode>.json judge responses.")
    parser.add_argument("--output-dir", default=None, help="Output directory for report files.")
    parser.add_argument("--write-requests", action="store_true", help="Write judge request packets/prompts.")
    args = parser.parse_args()

    run_root = Path(args.run_root)
    judge_dir = Path(args.judge_dir) if args.judge_dir else run_root / "ai_judge_8metrics"
    output_dir = Path(args.output_dir) if args.output_dir else run_root / "eight_metrics"
    judge_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    payload = {"run_root": str(run_root), "judge_dir": str(judge_dir), "metrics": ALL_METRICS, "modes": []}
    for mode in MODES:
        result_path = _find_result(run_root / mode)
        if result_path is None:
            row = _missing_row(mode)
            rows.append(row)
            payload["modes"].append({"mode": mode, "status": "missing_result"})
            continue

        result = _load_json(result_path)
        packet = _judge_packet(mode, result_path, result)
        if args.write_requests:
            _write_request_files(judge_dir, mode, packet)

        judge_path = judge_dir / f"{mode}.json"
        judge = _load_json(judge_path) if judge_path.exists() else None
        row = _row_from_result(mode, result_path, result, judge)
        rows.append(row)
        payload["modes"].append({"mode": mode, "result": str(result_path), "judge_response": str(judge_path), "row": row})

    csv_path = output_dir / "eight_metrics_summary.csv"
    json_path = output_dir / "eight_metrics_summary.json"
    _write_csv(csv_path, rows)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"eight_metrics_csv={csv_path}")
    print(f"eight_metrics_json={json_path}")
    if args.write_requests:
        print(f"judge_requests={judge_dir}")
    return 0


def _find_result(mode_dir: Path) -> Path | None:
    matches = sorted(mode_dir.glob("*/result.json"))
    return matches[0] if matches else None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _judge_packet(mode: str, result_path: Path, result: dict[str, Any]) -> dict[str, Any]:
    prompt_bundle = result.get("prompt_bundle", {})
    execution = result.get("execution", {})
    sample = result.get("sample", {})
    return {
        "mode": mode,
        "sample_id": sample.get("panel_id", ""),
        "target_png": _target_png(prompt_bundle, sample),
        "candidate_png": execution.get("candidate_png"),
        "candidate_code": str(result_path.parent / "candidate.py"),
        "result_json": str(result_path),
        "one_shot_strategy": prompt_bundle.get("one_shot_strategy", "none"),
        "deterministic_gate": _valid_gate(result),
        "rubric": RUBRIC,
        "expected_json_schema": {
            "overall_visual_fidelity": {"score": "integer 0-100", "reason": "short reason"},
            "chart_type_consistency": {"score": "0, 1, or 2", "reason": "short reason"},
            "layout_component_consistency": {"score": "0, 1, or 2", "reason": "short reason"},
            "data_pattern_fidelity": {"score": "0, 1, or 2", "reason": "short reason"},
            "text_scientific_label_fidelity": {"score": "0, 1, or 2", "reason": "short reason"},
            "axis_legend_colorbar_fidelity": {"score": "0, 1, or 2", "reason": "short reason"},
            "clarity_typography_quality": {"score": "0, 1, or 2", "reason": "short reason"},
        },
    }


def _write_request_files(judge_dir: Path, mode: str, packet: dict[str, Any]) -> None:
    (judge_dir / f"{mode}_request.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt = (
        "You are an expert scientific chart-to-code evaluator.\n"
        "Compare the target image and candidate image. Return strict JSON only.\n"
        "Use 0-100 for overall_visual_fidelity. Use 0/1/2 for all other AI metrics.\n"
        "0 means wrong or missing, 1 means partially correct, 2 means essentially correct.\n"
        "Evaluate the candidate as a rendered scientific figure, not as a natural image.\n\n"
        f"Judge packet:\n{json.dumps(packet, ensure_ascii=False, indent=2)}\n"
    )
    (judge_dir / f"{mode}_prompt.txt").write_text(prompt, encoding="utf-8")


def _row_from_result(mode: str, result_path: Path, result: dict[str, Any], judge: dict[str, Any] | None) -> dict[str, Any]:
    sample = result.get("sample", {})
    prompt_bundle = result.get("prompt_bundle", {})
    execution = result.get("execution", {})
    gate = _valid_gate(result)
    row = {
        "mode": mode,
        "sample_id": sample.get("panel_id", ""),
        "model_id": (result.get("model") or {}).get("model_id", result.get("backend", {}).get("name", "")),
        "one_shot_strategy": prompt_bundle.get("one_shot_strategy", "none"),
        "target_png": _target_png(prompt_bundle, sample),
        "candidate_png": execution.get("candidate_png"),
        "result_json": str(result_path),
        "valid_code_rate": 100.0 if gate["valid_code"] else 0.0,
        "valid_code_reason": "; ".join(gate["failures"]) or "valid plotting code",
    }
    judge_metrics = _judge_metrics(judge)
    for metric in AI_METRICS:
        score, normalized, reason = _score_metric(metric, judge_metrics.get(metric))
        if not gate["valid_code"]:
            normalized = 0.0
            reason = f"gated to zero because valid_code failed: {row['valid_code_reason']}"
        row[metric] = normalized
        row[f"{metric}_raw"] = score
        row[f"{metric}_reason"] = reason
    numeric = [row[key] for key in ALL_METRICS if isinstance(row.get(key), (int, float))]
    row["mean_8metric_score"] = sum(float(value) for value in numeric) / len(numeric) if numeric else None
    return row


def _missing_row(mode: str) -> dict[str, Any]:
    row = {"mode": mode, "valid_code_rate": 0.0, "valid_code_reason": "missing result.json"}
    for metric in AI_METRICS:
        row[metric] = None
        row[f"{metric}_raw"] = None
        row[f"{metric}_reason"] = "missing result.json"
    row["mean_8metric_score"] = None
    return row


def _valid_gate(result: dict[str, Any]) -> dict[str, Any]:
    execution = result.get("execution", {})
    review = (
        result.get("review_agent", {}).get("after_execution")
        or result.get("review_agent", {}).get("after_extraction")
        or result.get("review_agent", {}).get("after_backend")
        or {}
    )
    checks = review.get("checks", {}) if isinstance(review, dict) else {}
    failures = []
    if not execution.get("command_success"):
        failures.append("execution_failed")
    if not execution.get("candidate_png_exists"):
        failures.append("candidate_png_missing")
    if not checks.get("compile_ok"):
        failures.append("compile_failed")
    if not checks.get("has_savefig"):
        failures.append("savefig_missing")
    if checks.get("direct_image_dependency"):
        failures.append("direct_image_dependency")
    if checks.get("pixel_painting_or_raster_tracing"):
        failures.append("pixel_painting_or_raster_tracing")
    return {"valid_code": not failures, "failures": failures, "checks": checks}


def _target_png(prompt_bundle: dict[str, Any], sample: dict[str, Any]) -> str:
    image_paths = prompt_bundle.get("image_paths") or []
    image_roles = prompt_bundle.get("image_roles") or []
    for path, role in zip(image_paths, image_roles):
        if role == "target":
            return str(path)
    if image_paths:
        return str(image_paths[-1])
    return str(sample.get("target_png") or "")


def _judge_metrics(judge: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(judge, dict):
        return {}
    if isinstance(judge.get("metrics"), dict):
        return judge["metrics"]
    return judge


def _score_metric(metric: str, value: Any) -> tuple[float | None, float | None, str]:
    if isinstance(value, dict):
        raw = value.get("score", value.get("raw_score", value.get("normalized_score")))
        reason = str(value.get("reason", ""))
    else:
        raw = value
        reason = ""
    score = _to_float(raw)
    if score is None:
        return None, None, reason or "judge score missing"
    if metric == "overall_visual_fidelity":
        return score, _bounded(score), reason
    return score, _bounded(score * 50.0), reason


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _bounded(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "mode",
        "sample_id",
        "model_id",
        "one_shot_strategy",
        "valid_code_rate",
        "overall_visual_fidelity",
        "chart_type_consistency",
        "layout_component_consistency",
        "data_pattern_fidelity",
        "text_scientific_label_fidelity",
        "axis_legend_colorbar_fidelity",
        "clarity_typography_quality",
        "mean_8metric_score",
        "valid_code_reason",
        "target_png",
        "candidate_png",
        "result_json",
    ]
    for metric in AI_METRICS:
        columns.extend([f"{metric}_raw", f"{metric}_reason"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
