"""End-to-end SciFigure2Code evaluation pipeline."""

from __future__ import annotations

import csv
import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

from .agents import CodeReviewAgent, CodeWritingAgent
from .backends.base import CodeGenerationBackend
from .code_extract import extract_python_code
from .metrics import P0_METRICS, P1_METRICS, P2_METRICS, compute_basic_metrics, compute_benchmark_metrics
from .prompts import PromptConfig, build_prompt_bundle
from .runner import CodeRunner, RunnerConfig
from .schemas import Sample
from .utils import ensure_dir, load_json, now_iso, safe_name, stable_json_hash, write_json


@dataclass
class EvalConfig:
    output_dir: Path
    runner: RunnerConfig = field(default_factory=RunnerConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    one_shot_sample: Sample | None = None
    model: dict[str, Any] = field(default_factory=dict)
    resume: bool = False
    overwrite: bool = False


def run_evaluation(samples: list[Sample], backend: CodeGenerationBackend, config: EvalConfig) -> dict[str, Any]:
    output_dir = ensure_dir(Path(config.output_dir))
    runner = CodeRunner(config.runner)
    writer_agent = CodeWritingAgent(backend)
    reviewer_agent = CodeReviewAgent()
    config.prompt.supports_multi_image = bool(getattr(backend, "supports_multi_images", False))
    results: list[dict[str, Any]] = []
    run_signature = _run_signature(backend, config)

    write_json(
        output_dir / "run_config.json",
        {
            "created_at": now_iso(),
            "run_signature": run_signature,
            "backend": backend.name,
            "sample_count": len(samples),
            "output_dir": output_dir,
            "runner": config.runner,
            "prompt": config.prompt,
            "model": config.model,
            "one_shot_sample": config.one_shot_sample.to_json_dict() if config.one_shot_sample else None,
            "resume": config.resume,
            "overwrite": config.overwrite,
        },
    )
    write_json(output_dir / "selected_samples.json", [sample.to_json_dict() for sample in samples])

    for index, sample in enumerate(samples, start=1):
        sample_dir = ensure_dir(output_dir / safe_name(sample.panel_id))
        result_path = sample_dir / "result.json"
        if config.resume and result_path.exists() and not config.overwrite:
            result = load_json(result_path)
            resume_check = _resume_check(result, sample, run_signature)
            if resume_check["ok"]:
                result["resumed"] = True
                result["resume_check"] = resume_check
                results.append(result)
                continue

        one_shot_sample = _one_shot_for_sample(samples, sample, config)
        result = _evaluate_one(
            index,
            len(samples),
            sample,
            backend,
            config,
            runner,
            writer_agent,
            reviewer_agent,
            sample_dir,
            run_signature,
            one_shot_sample,
        )
        write_json(result_path, result)
        results.append(result)

    summary = write_summaries(results, output_dir)
    return summary


def _one_shot_for_sample(samples: list[Sample], sample: Sample, config: EvalConfig) -> Sample | None:
    mode = str(config.prompt.mode or "zeroshot").replace("-", "_").lower()
    if mode not in {"oneshot", "oneshot_cot", "one_shot", "one_shot_cot"}:
        return None
    if config.one_shot_sample and config.one_shot_sample.panel_id != sample.panel_id:
        return config.one_shot_sample
    for candidate in samples:
        if candidate.panel_id != sample.panel_id:
            return candidate
    return config.one_shot_sample


def _evaluate_one(
    index: int,
    total: int,
    sample: Sample,
    backend: CodeGenerationBackend,
    config: EvalConfig,
    runner: CodeRunner,
    writer_agent: CodeWritingAgent,
    reviewer_agent: CodeReviewAgent,
    sample_dir: Path,
    run_signature: str,
    one_shot_sample: Sample | None,
) -> dict[str, Any]:
    prompt_bundle = build_prompt_bundle(sample, config.prompt, one_shot_sample=one_shot_sample)
    prompt = prompt_bundle.prompt
    (sample_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json(sample_dir / "prompt_bundle.json", prompt_bundle)
    write_json(sample_dir / "sample_record.json", sample.to_json_dict())
    local_targets = _copy_target_artifacts(sample, sample_dir)

    result: dict[str, Any] = {
        "created_at": now_iso(),
        "index": index,
        "total": total,
        "run_signature": run_signature,
        "sample_signature": _sample_signature(sample),
        "sample": sample.to_json_dict(),
        "model": config.model,
        "backend": {"name": backend.name},
        "prompt_bundle": prompt_bundle,
        "writer_agent": {"name": writer_agent.name},
        "review_agent": {"name": reviewer_agent.name},
        "paths": {
            "sample_dir": sample_dir,
            "prompt": sample_dir / "prompt.txt",
            "prompt_bundle": sample_dir / "prompt_bundle.json",
            **local_targets,
            "raw_model_output": sample_dir / "model_output.txt",
            "candidate_code": sample_dir / "candidate.py",
            "review_feedback": sample_dir / "review_feedback.json",
            "result_json": sample_dir / "result.json",
        },
    }

    try:
        generation = writer_agent.write_code(
            sample=sample,
            prompt=prompt,
            image_paths=prompt_bundle.image_paths,
            output_dir=sample_dir,
            options={
                "prompt_mode": prompt_bundle.mode,
                "prompt_style": prompt_bundle.style,
                "one_shot_strategy": prompt_bundle.one_shot_strategy,
                "exemplar_panel_id": prompt_bundle.exemplar_panel_id,
            },
        )
    except Exception as exc:
        result["backend"].update({"ok": False, "error": f"{exc.__class__.__name__}: {exc}"})
        result["writer_agent"].update({"ok": False, "error": f"{exc.__class__.__name__}: {exc}"})
        result["review_agent"]["after_backend"] = reviewer_agent.review(
            code_text="",
            code_extraction={"compile_ok": False, "compile_error": "backend_error"},
            execution={"command_success": False, "candidate_png_exists": False, "candidate_pdf_exists": False},
        )
        write_json(sample_dir / "review_feedback.json", result["review_agent"])
        result["traceback"] = traceback.format_exc()
        result["execution"] = {"skipped": True, "reason": "backend_error"}
        result["metrics"] = compute_basic_metrics(sample.target_png, None, None)
        result["benchmark_metrics"] = compute_benchmark_metrics(
            sample=sample,
            basic_metrics=result["metrics"],
            execution=result["execution"],
            code_extraction=None,
            code_text="",
        )
        return result

    (sample_dir / "model_output.txt").write_text(generation.text, encoding="utf-8")
    result["backend"].update({"ok": True, "metadata": generation.metadata})
    result["writer_agent"].update({"ok": True, "metadata": generation.metadata})

    try:
        extraction = extract_python_code(generation.text)
    except Exception as exc:
        result["code_extraction"] = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
        result["review_agent"]["after_extraction"] = reviewer_agent.review(code_text="", code_extraction=result["code_extraction"])
        write_json(sample_dir / "review_feedback.json", result["review_agent"])
        result["traceback"] = traceback.format_exc()
        result["execution"] = {"skipped": True, "reason": "code_extraction_error"}
        result["metrics"] = compute_basic_metrics(sample.target_png, None, None)
        result["benchmark_metrics"] = compute_benchmark_metrics(
            sample=sample,
            basic_metrics=result["metrics"],
            execution=result["execution"],
            code_extraction=result.get("code_extraction"),
            code_text="",
        )
        return result
    result["code_extraction"] = extraction
    review_after_extraction = reviewer_agent.review(code_text=extraction.code, code_extraction=extraction)
    result["review_agent"]["after_extraction"] = review_after_extraction
    if not extraction.code:
        result["execution"] = {"skipped": True, "reason": "no code extracted"}
        write_json(sample_dir / "review_feedback.json", result["review_agent"])
        result["metrics"] = compute_basic_metrics(sample.target_png, None, None)
        result["benchmark_metrics"] = compute_benchmark_metrics(
            sample=sample,
            basic_metrics=result["metrics"],
            execution=result["execution"],
            code_extraction=result.get("code_extraction"),
            code_text="",
        )
        return result

    try:
        execution = runner.run(extraction.code, sample, sample_dir)
    except Exception as exc:
        result["execution"] = {
            "skipped": True,
            "reason": "runner_error",
            "error": f"{exc.__class__.__name__}: {exc}",
        }
        result["review_agent"]["after_execution"] = reviewer_agent.review(
            code_text=extraction.code,
            code_extraction=extraction,
            execution=result["execution"],
        )
        write_json(sample_dir / "review_feedback.json", result["review_agent"])
        result["traceback"] = traceback.format_exc()
        result["metrics"] = compute_basic_metrics(sample.target_png, None, None)
        result["benchmark_metrics"] = compute_benchmark_metrics(
            sample=sample,
            basic_metrics=result["metrics"],
            execution=result["execution"],
            code_extraction=result.get("code_extraction"),
            code_text=extraction.code,
        )
        return result

    result["execution"] = execution
    result["review_agent"]["after_execution"] = reviewer_agent.review(
        code_text=extraction.code,
        code_extraction=extraction,
        execution=execution,
    )
    write_json(sample_dir / "review_feedback.json", result["review_agent"])
    result["metrics"] = compute_basic_metrics(
        sample.target_png,
        execution.get("candidate_png"),
        execution.get("candidate_pdf"),
    )
    result["benchmark_metrics"] = compute_benchmark_metrics(
        sample=sample,
        basic_metrics=result["metrics"],
        execution=execution,
        code_extraction=extraction,
        code_text=extraction.code,
    )
    result["evaluation_metadata"] = {
        "sample_id": sample.panel_id,
        "model_id": config.model.get("model_id") or backend.name,
        "task_type": "scientific_panel_to_code",
        "prompt_mode": prompt_bundle.mode,
        "prompt_style": prompt_bundle.style,
        "one_shot_strategy": prompt_bundle.one_shot_strategy,
        "exemplar_panel_id": prompt_bundle.exemplar_panel_id,
        "domain": sample.subject,
        "chart_subtype": sample.subtype,
        "complexity_score": sample.refine_complexity_score,
        "complexity_bin": sample.complexity_level,
    }
    return result


def write_summaries(results: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    rows = [_summary_row(result) for result in results]
    csv_path = output_dir / "summary.csv"
    json_path = output_dir / "summary.json"

    columns = _summary_columns()
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    aggregate = _aggregate(rows)
    payload = {
        "created_at": now_iso(),
        "summary_csv": csv_path,
        "total_samples": len(rows),
        "aggregate": aggregate,
        "samples": rows,
    }
    write_json(json_path, payload)
    return {"summary_csv": csv_path, "summary_json": json_path, "aggregate": aggregate}


def aggregate_existing_results(output_dir: Path) -> dict[str, Any]:
    """Rebuild summary files from existing per-sample result.json artifacts."""

    output_dir = Path(output_dir)
    if not output_dir.exists():
        raise FileNotFoundError(f"output directory does not exist: {output_dir}")
    results = []
    for result_path in sorted(output_dir.rglob("result.json")):
        try:
            result = load_json(result_path)
        except Exception as exc:
            result = {
                "created_at": now_iso(),
                "sample": {"panel_id": result_path.parent.name},
                "backend": {"name": "", "ok": False, "error": f"could not load result: {exc.__class__.__name__}: {exc}"},
                "execution": {"skipped": True, "reason": "result_json_load_error"},
                "metrics": compute_basic_metrics(None, None, None),
                "paths": {"result_json": result_path},
            }
        results.append(result)
    if not results:
        raise FileNotFoundError(f"no per-sample result.json files found under {output_dir}")
    return write_summaries(results, output_dir)


def _summary_columns() -> list[str]:
    return [
        "panel_id",
        "complexity_level",
        "refine_complexity_score",
        "subject",
        "topic",
        "subtype",
        "model_id",
        "model_path",
        "model_type",
        "adapter_ready",
        "supports_multi_image",
        "max_images",
        "prompt_mode",
        "prompt_style",
        "one_shot_strategy",
        "exemplar_panel_id",
        "backend",
        "backend_ok",
        "code_compile_ok",
        "review_ok",
        "direct_image_dependency",
        "pixel_painting_or_raster_tracing",
        "command_success",
        "timed_out",
        "returncode",
        "elapsed_seconds",
        "candidate_png_exists",
        "candidate_pdf_exists",
        "image_ok",
        "target_width",
        "target_height",
        "candidate_width",
        "candidate_height",
        "width_match",
        "height_match",
        "mae",
        "rmse",
        "psnr",
        "ncc",
        "l1_similarity",
        "nonwhite_iou",
        "ssim",
        "leaderboard_score",
        *[f"p0_{name}" for name in P0_METRICS],
        *[f"p1_{name}" for name in P1_METRICS],
        *[f"p2_{name}" for name in P2_METRICS],
        "result_json",
        "candidate_png",
        "candidate_pdf",
    ]


def _summary_row(result: dict[str, Any]) -> dict[str, Any]:
    sample = result.get("sample", {})
    execution = result.get("execution", {})
    code_extraction = result.get("code_extraction", {})
    metrics = result.get("metrics", {})
    artifacts = metrics.get("artifacts", {})
    image = metrics.get("image", {})
    benchmark = result.get("benchmark_metrics", {})
    paths = result.get("paths", {})
    backend = result.get("backend", {})
    model = result.get("model", {})
    prompt_bundle = result.get("prompt_bundle", {})
    review = (
        result.get("review_agent", {}).get("after_execution")
        or result.get("review_agent", {}).get("after_extraction")
        or result.get("review_agent", {}).get("after_backend")
        or {}
    )
    review_checks = review.get("checks", {}) if isinstance(review, dict) else {}
    row = {
        "panel_id": sample.get("panel_id", ""),
        "complexity_level": sample.get("complexity_level", ""),
        "refine_complexity_score": sample.get("refine_complexity_score", ""),
        "subject": sample.get("subject", ""),
        "topic": sample.get("topic", ""),
        "subtype": sample.get("subtype", ""),
        "model_id": _field(model, "model_id") or backend.get("name", ""),
        "model_path": _field(model, "model_path"),
        "model_type": _field(model, "model_type"),
        "adapter_ready": _field(model, "adapter_ready"),
        "supports_multi_image": _field(model, "supports_multi_image"),
        "max_images": _field(model, "max_images"),
        "prompt_mode": _field(prompt_bundle, "mode"),
        "prompt_style": _field(prompt_bundle, "style"),
        "one_shot_strategy": _field(prompt_bundle, "one_shot_strategy"),
        "exemplar_panel_id": _field(prompt_bundle, "exemplar_panel_id"),
        "backend": backend.get("name", ""),
        "backend_ok": backend.get("ok", False),
        "code_compile_ok": _field(code_extraction, "compile_ok"),
        "review_ok": review.get("ok") if isinstance(review, dict) else None,
        "direct_image_dependency": review_checks.get("direct_image_dependency"),
        "pixel_painting_or_raster_tracing": review_checks.get("pixel_painting_or_raster_tracing"),
        "command_success": execution.get("command_success", False),
        "timed_out": execution.get("timed_out", False),
        "returncode": execution.get("returncode"),
        "elapsed_seconds": execution.get("elapsed_seconds"),
        "candidate_png_exists": artifacts.get("candidate_png_exists", execution.get("candidate_png_exists", False)),
        "candidate_pdf_exists": artifacts.get("candidate_pdf_exists", execution.get("candidate_pdf_exists", False)),
        "image_ok": image.get("ok", False),
        "target_width": image.get("target_width"),
        "target_height": image.get("target_height"),
        "candidate_width": image.get("candidate_width"),
        "candidate_height": image.get("candidate_height"),
        "width_match": image.get("width_match"),
        "height_match": image.get("height_match"),
        "mae": image.get("mae"),
        "rmse": image.get("rmse"),
        "psnr": image.get("psnr"),
        "ncc": image.get("ncc"),
        "l1_similarity": image.get("l1_similarity"),
        "nonwhite_iou": image.get("nonwhite_iou"),
        "ssim": image.get("ssim"),
        "result_json": paths.get("result_json"),
        "candidate_png": execution.get("candidate_png"),
        "candidate_pdf": execution.get("candidate_pdf"),
    }
    row["leaderboard_score"] = _metric_score(benchmark.get("leaderboard_score"))
    for metric_name in P0_METRICS:
        row[f"p0_{metric_name}"] = _metric_score(benchmark.get("p0_core", {}).get(metric_name))
    for metric_name in P1_METRICS:
        row[f"p1_{metric_name}"] = _metric_score(benchmark.get("p1_diagnostic", {}).get(metric_name))
    for metric_name in P2_METRICS:
        row[f"p2_{metric_name}"] = _metric_score(benchmark.get("p2_auxiliary", {}).get(metric_name))
    return row


def _field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    aggregate = {
        "total": len(rows),
        "valid_count": len(rows),
        "executed_count": sum(1 for row in rows if _as_bool(row.get("command_success"))),
        "failed_count": sum(1 for row in rows if not _as_bool(row.get("command_success"))),
        "backend_ok": _rate(rows, "backend_ok"),
        "code_compile_ok": _rate(rows, "code_compile_ok"),
        "command_success": _rate(rows, "command_success"),
        "execution_pass_rate": _rate(rows, "command_success"),
        "review_pass_rate": _rate(rows, "review_ok"),
        "direct_image_dependency_rate": _rate(rows, "direct_image_dependency"),
        "pixel_painting_or_raster_tracing_rate": _rate(rows, "pixel_painting_or_raster_tracing"),
        "candidate_png_exists": _rate(rows, "candidate_png_exists"),
        "candidate_pdf_exists": _rate(rows, "candidate_pdf_exists"),
        "image_ok": _rate(rows, "image_ok"),
        "leaderboard_score": _stats_numeric(rows, "leaderboard_score"),
        "p0_core": {name: _stats_numeric(rows, f"p0_{name}") for name in P0_METRICS},
        "p1_diagnostic": {name: _stats_numeric(rows, f"p1_{name}") for name in P1_METRICS},
        "p2_auxiliary": {name: _stats_numeric(rows, f"p2_{name}") for name in P2_METRICS},
        "mean_metrics": _mean_metrics(rows),
        "breakdowns": {
            "by_model": _breakdown(rows, "model_id"),
            "by_model_x_mode": _breakdown(rows, "model_id", "prompt_mode"),
            "by_complexity": _breakdown(rows, "complexity_level"),
            "by_domain": _breakdown(rows, "subject"),
            "by_chart_subtype": _breakdown(rows, "subtype"),
            "by_domain_x_complexity": _breakdown(rows, "subject", "complexity_level"),
            "by_subtype_x_complexity": _breakdown(rows, "subtype", "complexity_level"),
        },
    }
    aggregate["p1_diagnostic"]["complexity_stratified_score"] = _aggregate_only_stats(aggregate["breakdowns"]["by_complexity"])
    aggregate["p1_diagnostic"]["chart_subtype_score"] = _aggregate_only_stats(aggregate["breakdowns"]["by_chart_subtype"])
    aggregate["p1_diagnostic"]["domain_robustness"] = _aggregate_only_stats(aggregate["breakdowns"]["by_domain"])
    return aggregate


def _rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if _as_bool(row.get(key))) / len(rows)


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _mean_metrics(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    metrics = {}
    for key in ("mae", "rmse", "psnr", "ncc", "l1_similarity", "nonwhite_iou", "ssim", "elapsed_seconds"):
        values = []
        for row in rows:
            value = row.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        metrics[key] = mean(values) if values else None
    return metrics


def _metric_score(metric: Any) -> float | None:
    if isinstance(metric, dict):
        value = metric.get("normalized_score")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _mean_numeric(rows: list[dict[str, Any]], key: str) -> float | None:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return mean(values) if values else None


def _stats_numeric(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return {
        "count": len(values),
        "null_count": len(rows) - len(values),
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "std": pstdev(values) if len(values) > 1 else 0.0 if values else None,
    }


def _breakdown(rows: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = " / ".join(str(row.get(key) or "unknown") for key in keys)
        groups.setdefault(label, []).append(row)
    return {
        label: {
            "sample_count": len(group_rows),
            "execution_pass_rate": _rate(group_rows, "command_success"),
            "leaderboard_score": _stats_numeric(group_rows, "leaderboard_score"),
            "p0_core": {name: _stats_numeric(group_rows, f"p0_{name}") for name in P0_METRICS},
            "mean_metrics": _mean_metrics(group_rows),
        }
        for label, group_rows in sorted(groups.items())
    }


def _aggregate_only_stats(breakdown: dict[str, Any]) -> dict[str, Any]:
    values = []
    for cell in breakdown.values():
        stat = cell.get("leaderboard_score", {})
        value = stat.get("mean") if isinstance(stat, dict) else None
        if isinstance(value, (int, float)):
            values.append(float(value))
    return {
        "status": "aggregate_only",
        "count": len(values),
        "null_count": len(breakdown) - len(values),
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "std": pstdev(values) if len(values) > 1 else 0.0 if values else None,
        "method": "breakdown_leaderboard_score",
    }


def _run_signature(backend: CodeGenerationBackend, config: EvalConfig) -> str:
    return stable_json_hash(
        {
            "backend_name": backend.name,
            "backend_class": backend.__class__.__module__ + "." + backend.__class__.__name__,
            "model": config.model,
            "runner": config.runner,
            "prompt": config.prompt,
        }
    )


def _sample_signature(sample: Sample) -> str:
    return stable_json_hash(
        {
            "panel_id": sample.panel_id,
            "target_png": sample.target_png,
            "target_pdf": sample.target_pdf,
            "reference_code": sample.reference_code,
            "subject": sample.subject,
            "topic": sample.topic,
            "subtype": sample.subtype,
            "complexity_level": sample.complexity_level,
            "refine_complexity_score": sample.refine_complexity_score,
        }
    )


def _resume_check(result: dict[str, Any], sample: Sample, run_signature: str) -> dict[str, Any]:
    reasons = []
    if result.get("run_signature") != run_signature:
        reasons.append("run_signature_mismatch")
    if result.get("sample_signature") != _sample_signature(sample):
        reasons.append("sample_signature_mismatch")
    execution = result.get("execution", {})
    if execution.get("candidate_png_exists") and not _path_exists(execution.get("candidate_png")):
        reasons.append("candidate_png_missing")
    if execution.get("candidate_pdf_exists") and not _path_exists(execution.get("candidate_pdf")):
        reasons.append("candidate_pdf_missing")
    if not result.get("benchmark_metrics"):
        reasons.append("benchmark_metrics_missing")
    return {"ok": not reasons, "reasons": reasons}


def _path_exists(value: Any) -> bool:
    if not value:
        return False
    try:
        return Path(str(value)).exists()
    except Exception:
        return False


def _copy_target_artifacts(sample: Sample, sample_dir: Path) -> dict[str, Path]:
    """Keep target images beside generated artifacts for inspection/judging."""

    copied: dict[str, Path] = {}
    if sample.target_png and sample.target_png.exists():
        target_png = sample_dir / "target.png"
        _copy_if_needed(sample.target_png, target_png)
        copied["target_png_local"] = target_png
    if sample.target_pdf and sample.target_pdf.exists():
        target_pdf = sample_dir / "target.pdf"
        _copy_if_needed(sample.target_pdf, target_pdf)
        copied["target_pdf_local"] = target_pdf
    return copied


def _copy_if_needed(src: Path, dst: Path) -> None:
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return
    shutil.copy2(src, dst)
