"""Metric computation for SciFigure2Code evaluation.

The evaluator has two layers:

1. Deterministic artifact/image/code proxies that can run offline.
2. A stable benchmark metric schema that can later be filled by VLM judges.

The proxy scores are intentionally conservative. They make smoke tests and
large-scale dry runs possible, while the JSON schema already matches the
P0/P1/P2 metric hierarchy used by the benchmark idea document.
"""

from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


def compute_basic_metrics(target_png: Path | None, candidate_png: Path | None, candidate_pdf: Path | None) -> dict[str, Any]:
    artifact_metrics = {
        "candidate_png_exists": bool(candidate_png and candidate_png.exists()),
        "candidate_pdf_exists": bool(candidate_pdf and candidate_pdf.exists()),
        "candidate_png_bytes": _file_size(candidate_png),
        "candidate_pdf_bytes": _file_size(candidate_pdf),
    }
    image_metrics = compute_image_metrics(target_png, candidate_png)
    return {"artifacts": artifact_metrics, "image": image_metrics}


P0_METRICS = [
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
]

P1_METRICS = [
    "style_consistency",
    "color_consistency",
    "typography_quality",
    "scientific_label_fidelity",
    "panel_context_fidelity",
    "caption_consistency",
    "code_editability",
    "re_render_stability",
    "complexity_stratified_score",
    "chart_subtype_score",
    "domain_robustness",
]

P2_METRICS = [
    "pixel_similarity",
    "clip_similarity",
    "code_similarity_to_reference",
    "runtime_efficiency",
    "library_api_appropriateness",
    "judge_agreement",
]


METRIC_DEFINITIONS: dict[str, dict[str, str]] = {
    "execution_pass_rate": {
        "priority": "P0",
        "source": "ChartMimic + RealChart2Code",
        "description": "Whether generated code executes successfully; failed execution gates visual scores to zero.",
    },
    "overall_visual_fidelity": {
        "priority": "P0",
        "source": "ChartMimic high-level VLM score",
        "description": "Overall similarity between target panel and rendered candidate.",
    },
    "chart_type_consistency": {
        "priority": "P0",
        "source": "ChartMimic Type + RealChart2Code Chart Type",
        "description": "Whether the generated chart type matches the target subtype.",
    },
    "layout_consistency": {
        "priority": "P0",
        "source": "ChartMimic Layout + RealChart2Code Spatial Layout",
        "description": "Whether subplot and element layout match the target panel.",
    },
    "data_pattern_fidelity": {
        "priority": "P0",
        "source": "RealChart2Code Data Pattern",
        "description": "Whether trends, distributions, group differences, and error structures match.",
    },
    "text_label_fidelity": {
        "priority": "P0",
        "source": "ChartMimic Text + RealChart2Code Text",
        "description": "Whether title, labels, ticks, legends, annotations, and panel text are complete.",
    },
    "axis_fidelity": {
        "priority": "P0",
        "source": "RealChart2Code Axis Configuration",
        "description": "Whether ranges, ticks, scales, units, and label symbols are faithful.",
    },
    "legend_colorbar_completeness": {
        "priority": "P0",
        "source": "RealChart2Code Axis/Component Completeness",
        "description": "Whether legends and colorbars are present, correct, visible, and non-overlapping.",
    },
    "component_completeness": {
        "priority": "P0",
        "source": "RealChart2Code Component Completeness",
        "description": "Whether essential visual components such as error bars, overlays, insets, and markers are present.",
    },
    "clarity_overlap_score": {
        "priority": "P0",
        "source": "RealChart2Code Visual Clarity",
        "description": "Whether the generated figure is readable and free of damaging overlaps/clipping.",
    },
    "style_consistency": {
        "priority": "P1",
        "source": "RealChart2Code Style",
        "description": "Whether font, marker, grid, line, border, and background styles match.",
    },
    "color_consistency": {
        "priority": "P1",
        "source": "ChartMimic Color + RealChart2Code Color",
        "description": "Whether category and continuous color mappings match.",
    },
    "typography_quality": {
        "priority": "P1",
        "source": "RealChart2Code Typographic Quality",
        "description": "Whether text is legible, consistent, and professionally placed.",
    },
    "scientific_label_fidelity": {
        "priority": "P1",
        "source": "SciFigure2Code-specific",
        "description": "Whether scientific symbols, units, gene/protein names, formulas, and math notation are correct.",
    },
    "panel_context_fidelity": {
        "priority": "P1",
        "source": "SciFigure2Code-specific",
        "description": "Whether panel letters, local titles, local annotations, and panel-specific legends are preserved.",
    },
    "caption_consistency": {
        "priority": "P1",
        "source": "SciFigure2Code-specific",
        "description": "Whether the rendered content is consistent with the source caption and metadata.",
    },
    "code_editability": {
        "priority": "P1",
        "source": "SciFigure2Code-specific",
        "description": "Whether code is readable, executable, and editable.",
    },
    "re_render_stability": {
        "priority": "P1",
        "source": "SciFigure2Code-specific",
        "description": "Whether code can be deterministically re-rendered.",
    },
    "complexity_stratified_score": {
        "priority": "P1",
        "source": "SciFigure2Code-specific",
        "description": "Aggregate score broken down by complexity bins.",
    },
    "chart_subtype_score": {
        "priority": "P1",
        "source": "SciFigure2Code-specific",
        "description": "Aggregate score broken down by chart subtype.",
    },
    "domain_robustness": {
        "priority": "P1",
        "source": "SciFigure2Code-specific",
        "description": "Aggregate score broken down by scientific domain.",
    },
    "pixel_similarity": {
        "priority": "P2",
        "source": "Auxiliary image metric",
        "description": "Pixel-level similarity proxies such as L1, NCC, SSIM, and nonwhite IoU.",
    },
    "clip_similarity": {
        "priority": "P2",
        "source": "Auxiliary semantic image metric",
        "description": "Optional CLIP-like semantic similarity.",
    },
    "code_similarity_to_reference": {
        "priority": "P2",
        "source": "Auxiliary code metric",
        "description": "Text/AST similarity to the agent-verified reference code.",
    },
    "runtime_efficiency": {
        "priority": "P2",
        "source": "Auxiliary execution metric",
        "description": "Runtime and dependency cost of generated plotting code.",
    },
    "library_api_appropriateness": {
        "priority": "P2",
        "source": "Auxiliary code metric",
        "description": "Whether the code uses appropriate plotting/data APIs.",
    },
    "judge_agreement": {
        "priority": "P2",
        "source": "Evaluation reliability metric",
        "description": "Agreement among automatic judges or between automatic judges and humans.",
    },
}


def compute_benchmark_metrics(
    *,
    sample: Any,
    basic_metrics: dict[str, Any],
    execution: dict[str, Any] | None,
    code_extraction: dict[str, Any] | Any | None,
    code_text: str = "",
) -> dict[str, Any]:
    """Return benchmark-grade P0/P1/P2 metric schema for one sample."""

    execution = execution or {}
    image = basic_metrics.get("image", {})
    artifacts = basic_metrics.get("artifacts", {})
    command_success = bool(execution.get("command_success")) and bool(artifacts.get("candidate_png_exists"))
    image_ok = bool(image.get("ok"))
    code_compile_ok = bool(_get(code_extraction, "compile_ok"))
    visual_proxy = _visual_proxy_score(image) if command_success and image_ok else 0.0
    chart_type_proxy = _chart_type_proxy_score(sample, code_text, visual_proxy) if command_success else 0.0
    code_quality_proxy = _code_editability_score(code_text, code_compile_ok, command_success)
    runtime_score = _runtime_efficiency_score(execution.get("elapsed_seconds"), command_success)
    reference_similarity = _code_similarity(sample, code_text)
    p0 = {
        "execution_pass_rate": _metric(
            100.0 if command_success else 0.0,
            "Code executed successfully." if command_success else "Generated code did not execute successfully.",
            method="deterministic_execution_gate",
        ),
        "overall_visual_fidelity": _metric(
            visual_proxy,
            "Offline image-proxy score from L1/NCC/nonwhite-IoU/aHash/SSIM; replaceable by VLM judge.",
            method="deterministic_image_proxy",
        ),
        "chart_type_consistency": _metric(
            chart_type_proxy,
            "Proxy from expected chart subtype and plotting API hints, backed off to visual proxy when image match is high.",
            method="code_api_plus_visual_proxy",
        ),
        "layout_consistency": _metric(
            _bounded(0.55 * visual_proxy + 45.0 * _layout_size_match(image)) if command_success else 0.0,
            "Proxy from visual similarity, target/candidate size match, and aspect-ratio consistency.",
            method="image_layout_proxy",
        ),
        "data_pattern_fidelity": _metric(
            visual_proxy,
            "Proxy from rendered image similarity; VLM/data-pattern judge can replace this field.",
            method="image_pattern_proxy",
        ),
        "text_label_fidelity": _metric(
            _text_label_proxy_score(sample, visual_proxy) if command_success else 0.0,
            "Proxy from visual similarity and source Qwen label/tick completeness metadata.",
            method="metadata_plus_image_proxy",
        ),
        "axis_fidelity": _metric(
            _axis_proxy_score(sample, visual_proxy) if command_success else 0.0,
            "Proxy from visual similarity and source Qwen axis/tick completeness metadata.",
            method="metadata_plus_image_proxy",
        ),
        "legend_colorbar_completeness": _metric(
            _bounded(0.9 * visual_proxy + 10.0 * _contains_any(code_text, ["legend", "colorbar", "cbar"])) if command_success else 0.0,
            "Proxy from visual similarity and generated-code legend/colorbar API hints.",
            method="code_api_plus_image_proxy",
        ),
        "component_completeness": _metric(
            _bounded(0.75 * visual_proxy + 25.0 * float(artifacts.get("candidate_png_exists", False))) if command_success else 0.0,
            "Proxy from visual similarity and rendered artifact completeness.",
            method="artifact_plus_image_proxy",
        ),
        "clarity_overlap_score": _metric(
            _bounded(0.9 * visual_proxy + 10.0 * float(bool(image.get("width_match")) and bool(image.get("height_match")))) if command_success else 0.0,
            "Proxy from visual similarity and no-resize requirement; VLM overlap judge should fill this in final evaluation.",
            method="image_clarity_proxy",
        ),
    }

    p1 = {
        "style_consistency": _metric(visual_proxy if command_success else 0.0, "Proxy from overall image similarity.", method="image_style_proxy"),
        "color_consistency": _metric(_color_proxy_score(image, visual_proxy) if command_success else 0.0, "Proxy from image similarity and nonwhite mask agreement.", method="image_color_proxy"),
        "typography_quality": _metric(_text_label_proxy_score(sample, visual_proxy) if command_success else 0.0, "Proxy from text/label fidelity.", method="text_proxy"),
        "scientific_label_fidelity": _metric(_text_label_proxy_score(sample, visual_proxy) if command_success else 0.0, "Proxy from text/axis label fidelity; final judge should inspect symbols.", method="text_proxy"),
        "panel_context_fidelity": _metric(_panel_context_proxy_score(sample, code_text, visual_proxy) if command_success else 0.0, "Proxy from panel metadata and visual similarity.", method="metadata_plus_image_proxy"),
        "caption_consistency": _metric(None, "Requires a caption-aware VLM judge; prompt includes caption when available.", method="vlm_judge_pending"),
        "code_editability": _metric(code_quality_proxy, "Proxy from code length, compile status, imports, functions, and savefig usage.", method="code_quality_proxy"),
        "re_render_stability": _metric(100.0 if command_success else 0.0, "Single-run stability proxy; repeat-run mode can overwrite this.", method="single_run_proxy"),
        "complexity_stratified_score": _metric(None, "Aggregate-only metric reported in summary breakdowns.", method="aggregate_breakdown"),
        "chart_subtype_score": _metric(None, "Aggregate-only metric reported in summary breakdowns.", method="aggregate_breakdown"),
        "domain_robustness": _metric(None, "Aggregate-only metric reported in summary breakdowns.", method="aggregate_breakdown"),
    }

    p2 = {
        "pixel_similarity": _metric(visual_proxy if command_success else 0.0, "Deterministic pixel/image proxy.", method="l1_ncc_nonwhite_ahash_ssim"),
        "clip_similarity": _metric(None, "Optional CLIP-like scorer is not configured in this framework pass.", method="not_configured"),
        "code_similarity_to_reference": _metric(reference_similarity, "Sequence similarity against agent-verified reference code when available.", method="difflib_sequence_matcher"),
        "runtime_efficiency": _metric(runtime_score, "Score derived from elapsed runtime and execution success.", method="runtime_proxy"),
        "library_api_appropriateness": _metric(_library_api_score(code_text, command_success), "Proxy from use of matplotlib/seaborn/pandas/numpy and output saving.", method="code_api_proxy"),
        "judge_agreement": _metric(None, "Requires multiple VLM/human judges; report at reliability-analysis stage.", method="not_configured"),
    }

    p0_scores = [entry["normalized_score"] for entry in p0.values() if isinstance(entry.get("normalized_score"), (int, float))]
    leaderboard_score = float(sum(p0_scores) / len(p0_scores)) if p0_scores else 0.0
    return {
        "schema_version": "scifigure2code.metrics.v1",
        "score_scale": "0-100",
        "definitions": METRIC_DEFINITIONS,
        "p0_core": p0,
        "p1_diagnostic": p1,
        "p2_auxiliary": p2,
        "leaderboard_score": _metric(
            leaderboard_score,
            "Mean of available P0 core metrics after execution gating.",
            method="mean_p0_core",
        ),
        "breakdown_keys": {
            "complexity_level": getattr(sample, "complexity_level", "") or "unknown",
            "complexity_score": getattr(sample, "refine_complexity_score", None),
            "domain": getattr(sample, "subject", "") or "unknown",
            "topic": getattr(sample, "topic", "") or "unknown",
            "chart_subtype": getattr(sample, "subtype", "") or "unknown",
        },
        "proxy_notice": (
            "This framework run uses deterministic proxy metrics unless a VLM judge backend is added. "
            "The schema is designed to preserve ChartMimic/RealChart2Code-aligned fields."
        ),
    }


def compute_image_metrics(target_png: Path | None, candidate_png: Path | None) -> dict[str, Any]:
    if target_png is None or not target_png.exists():
        return {"ok": False, "error": "target_png missing"}
    if candidate_png is None or not candidate_png.exists():
        return {"ok": False, "error": "candidate_png missing"}

    try:
        import numpy as np
        from PIL import Image
    except Exception as exc:
        return {"ok": False, "error": f"metric dependency missing: {exc.__class__.__name__}: {exc}"}

    try:
        with Image.open(target_png) as target_image, Image.open(candidate_png) as candidate_image:
            target_rgb = target_image.convert("RGB")
            candidate_rgb = candidate_image.convert("RGB")
            target_size = target_rgb.size
            candidate_size = candidate_rgb.size
            if candidate_size != target_size:
                resampling = getattr(Image, "Resampling", Image).LANCZOS
                candidate_for_pixels = candidate_rgb.resize(target_size, resampling)
            else:
                candidate_for_pixels = candidate_rgb

            target_arr = np.asarray(target_rgb, dtype=np.float32)
            candidate_arr = np.asarray(candidate_for_pixels, dtype=np.float32)
            diff = target_arr - candidate_arr
            abs_diff = np.abs(diff)
            mae = float(abs_diff.mean())
            mse = float(np.square(diff).mean())
            rmse = float(math.sqrt(mse))
            psnr = 100.0 if mse == 0 else float(20.0 * math.log10(255.0 / rmse))
            ncc = _normalized_cross_correlation(target_arr, candidate_arr, np)
            nonwhite_target = np.any(target_arr < 250.0, axis=2)
            nonwhite_candidate = np.any(candidate_arr < 250.0, axis=2)
            union = np.logical_or(nonwhite_target, nonwhite_candidate).sum()
            intersection = np.logical_and(nonwhite_target, nonwhite_candidate).sum()
            nonwhite_iou = float(intersection / union) if union else 1.0
            target_nonwhite = float(nonwhite_target.mean())
            candidate_nonwhite = float(nonwhite_candidate.mean())
            ahash_distance = _ahash_distance(target_rgb, candidate_rgb)
            ssim = _optional_ssim(target_arr, candidate_arr)

        return {
            "ok": True,
            "target_width": target_size[0],
            "target_height": target_size[1],
            "candidate_width": candidate_size[0],
            "candidate_height": candidate_size[1],
            "width_match": target_size[0] == candidate_size[0],
            "height_match": target_size[1] == candidate_size[1],
            "aspect_ratio_abs_diff": abs((candidate_size[0] / candidate_size[1]) - (target_size[0] / target_size[1])),
            "resized_for_pixel_metrics": candidate_size != target_size,
            "mae": mae,
            "mse": mse,
            "rmse": rmse,
            "psnr": psnr,
            "ncc": ncc,
            "l1_similarity": max(0.0, 1.0 - mae / 255.0),
            "nonwhite_fraction_target": target_nonwhite,
            "nonwhite_fraction_candidate": candidate_nonwhite,
            "nonwhite_fraction_abs_diff": abs(target_nonwhite - candidate_nonwhite),
            "nonwhite_iou": nonwhite_iou,
            "ahash_hamming": ahash_distance,
            "ahash_similarity": 1.0 - ahash_distance / 64.0,
            "ssim": ssim,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}


def _file_size(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    return path.stat().st_size


def _normalized_cross_correlation(target_arr: Any, candidate_arr: Any, np: Any) -> float | None:
    target = target_arr.reshape(-1).astype(np.float64)
    candidate = candidate_arr.reshape(-1).astype(np.float64)
    target -= target.mean()
    candidate -= candidate.mean()
    denom = float(np.linalg.norm(target) * np.linalg.norm(candidate))
    if denom == 0:
        return None
    return float(np.dot(target, candidate) / denom)


def _ahash_distance(target_image: Any, candidate_image: Any) -> int:
    from PIL import Image

    resampling = getattr(Image, "Resampling", Image).LANCZOS
    target_small = target_image.convert("L").resize((8, 8), resampling)
    candidate_small = candidate_image.convert("L").resize((8, 8), resampling)
    import numpy as np

    target_arr = np.asarray(target_small)
    candidate_arr = np.asarray(candidate_small)
    target_bits = target_arr >= target_arr.mean()
    candidate_bits = candidate_arr >= candidate_arr.mean()
    return int(np.count_nonzero(target_bits != candidate_bits))


def _optional_ssim(target_arr: Any, candidate_arr: Any) -> float | None:
    try:
        from skimage.metrics import structural_similarity

        return float(structural_similarity(target_arr, candidate_arr, channel_axis=2, data_range=255))
    except Exception:
        return None


def _metric(score: float | None, reason: str, *, method: str) -> dict[str, Any]:
    normalized = _bounded(score) if isinstance(score, (int, float)) else None
    if normalized is None:
        if method == "aggregate_breakdown":
            status = "aggregate_only"
        elif method in {"not_configured", "vlm_judge_pending"}:
            status = method
        else:
            status = "not_available"
    else:
        status = "scored"
    return {
        "status": status,
        "raw_score": normalized,
        "normalized_score": normalized,
        "max_score": 100,
        "method": method,
        "reason": reason,
    }


def _visual_proxy_score(image: dict[str, Any]) -> float:
    if not image.get("ok"):
        return 0.0
    scores: list[float] = []
    if isinstance(image.get("l1_similarity"), (int, float)):
        scores.append(100.0 * float(image["l1_similarity"]))
    if isinstance(image.get("ncc"), (int, float)):
        scores.append(100.0 * (float(image["ncc"]) + 1.0) / 2.0)
    if isinstance(image.get("nonwhite_iou"), (int, float)):
        scores.append(100.0 * float(image["nonwhite_iou"]))
    if isinstance(image.get("ahash_similarity"), (int, float)):
        scores.append(100.0 * float(image["ahash_similarity"]))
    if isinstance(image.get("ssim"), (int, float)):
        scores.append(100.0 * float(image["ssim"]))
    if not scores:
        return 0.0
    size_bonus = 6.0 if image.get("width_match") and image.get("height_match") else 0.0
    return _bounded(sum(scores) / len(scores) + size_bonus)


def _layout_size_match(image: dict[str, Any]) -> float:
    if not image.get("ok"):
        return 0.0
    width = 1.0 if image.get("width_match") else 0.0
    height = 1.0 if image.get("height_match") else 0.0
    aspect_diff = image.get("aspect_ratio_abs_diff")
    aspect = max(0.0, 1.0 - min(float(aspect_diff or 0.0), 1.0))
    return (width + height + aspect) / 3.0


def _chart_type_proxy_score(sample: Any, code_text: str, visual_proxy: float) -> float:
    if visual_proxy >= 99.0:
        return 100.0
    subtype = str(getattr(sample, "subtype", "") or "").lower()
    code = code_text.lower()
    expected = {
        "bar": ["bar(", "barh("],
        "grouped_bar": ["bar("],
        "stacked_bar": ["bar("],
        "line": ["plot("],
        "multi_line": ["plot("],
        "scatter": ["scatter("],
        "scatter_with_fit": ["scatter(", "plot("],
        "box": ["boxplot(", "boxplot"],
        "violin": ["violinplot(", "violinplot"],
        "histogram": ["hist(", "histplot"],
        "density": ["kdeplot", "density"],
        "heatmap": ["imshow(", "heatmap", "pcolormesh", "matshow"],
        "confusion_matrix": ["imshow(", "heatmap", "matshow"],
        "roc_curve": ["plot("],
        "umap_tsne_pca": ["scatter("],
        "volcano_plot": ["scatter("],
        "forest_plot": ["errorbar("],
        "dot_plot": ["scatter(", "plot("],
        "bubble_plot": ["scatter("],
        "geospatial_map": ["cartopy", "basemap", "imshow(", "pcolormesh", "scatter("],
        "matrix_plot": ["imshow(", "matshow", "heatmap"],
    }
    hints = expected.get(subtype, [])
    if hints and any(hint in code for hint in hints):
        return _bounded(max(85.0, visual_proxy))
    if any(hint in code for hint in ["plot(", "scatter(", "bar(", "imshow(", "heatmap", "errorbar("]):
        return _bounded(max(55.0, 0.75 * visual_proxy))
    return _bounded(0.65 * visual_proxy)


def _text_label_proxy_score(sample: Any, visual_proxy: float) -> float:
    score = visual_proxy
    record = getattr(sample, "record", {}) or {}
    xy_label = str(record.get("xy_label_complete", "")).lower()
    xytick = str(record.get("xytick_complete", "")).lower()
    if xy_label == "yes":
        score += 3.0
    elif xy_label == "no":
        score -= 5.0
    if xytick == "yes":
        score += 3.0
    elif xytick == "no":
        score -= 5.0
    return _bounded(score)


def _axis_proxy_score(sample: Any, visual_proxy: float) -> float:
    return _text_label_proxy_score(sample, visual_proxy)


def _color_proxy_score(image: dict[str, Any], visual_proxy: float) -> float:
    nonwhite = image.get("nonwhite_iou")
    if isinstance(nonwhite, (int, float)):
        return _bounded(0.75 * visual_proxy + 25.0 * float(nonwhite))
    return visual_proxy


def _panel_context_proxy_score(sample: Any, code_text: str, visual_proxy: float) -> float:
    panel_id = str(getattr(sample, "panel_id", "") or "")
    label = panel_id.rsplit("_", 1)[-1] if "_" in panel_id else ""
    if label and re.fullmatch(r"[A-Za-z]", label) and re.search(rf"['\"]{re.escape(label)}['\"]", code_text):
        return _bounded(visual_proxy + 5.0)
    return visual_proxy


def _code_editability_score(code_text: str, compile_ok: bool, command_success: bool) -> float:
    if not code_text:
        return 0.0
    score = 25.0
    if compile_ok:
        score += 20.0
    if command_success:
        score += 20.0
    if re.search(r"def\s+\w+\(", code_text):
        score += 10.0
    if "savefig" in code_text:
        score += 10.0
    if any(token in code_text for token in ["matplotlib", "seaborn", "pandas", "numpy"]):
        score += 10.0
    if len(code_text) > 20000:
        score -= 10.0
    return _bounded(score)


def _runtime_efficiency_score(elapsed_seconds: Any, command_success: bool) -> float:
    if not command_success:
        return 0.0
    if not isinstance(elapsed_seconds, (int, float)):
        return 75.0
    elapsed = float(elapsed_seconds)
    if elapsed <= 5:
        return 100.0
    if elapsed <= 30:
        return 90.0
    if elapsed <= 120:
        return 70.0
    return 45.0


def _library_api_score(code_text: str, command_success: bool) -> float:
    if not command_success or not code_text:
        return 0.0
    score = 35.0
    for token in ["matplotlib", "pyplot", "seaborn", "numpy", "pandas"]:
        if token in code_text:
            score += 10.0
    if "savefig" in code_text:
        score += 15.0
    return _bounded(score)


def _code_similarity(sample: Any, code_text: str) -> float | None:
    reference_code = getattr(sample, "reference_code", None)
    if reference_code is None or not Path(reference_code).exists() or not code_text:
        return None
    try:
        ref = Path(reference_code).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return _bounded(100.0 * SequenceMatcher(None, _normalize_code(ref), _normalize_code(code_text)).ratio())


def _normalize_code(code: str) -> str:
    code = re.sub(r"#.*", "", code)
    code = re.sub(r"\s+", " ", code)
    return code.strip()


def _contains_any(text: str, needles: list[str]) -> float:
    lowered = text.lower()
    return 1.0 if any(needle in lowered for needle in needles) else 0.0


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _bounded(value: float | int | None, low: float = 0.0, high: float = 100.0) -> float:
    if value is None:
        return 0.0
    try:
        number = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(low, min(high, number))
