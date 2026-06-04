#!/usr/bin/env python3
"""Build the static SciFigureHub website catalog from gallery exports."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps


GALLERY_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = GALLERY_ROOT / "site-data" / "catalog.json"
PREVIEW_ROOT = GALLERY_ROOT / "site-data" / "previews"
RESAMPLE_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
COMPLEXITY_BINS = [(0, 20), (20, 40), (40, 60), (60, 70), (70, 80), (80, 90), (90, 101)]
REFINE_COMPLEXITY_BINS = [
    ("1", 1, 2),
    ("2-3", 2, 4),
    ("4-5", 4, 6),
    ("6-7", 6, 8),
    ("8-10", 8, 10.0001),
]


def configure_gallery_root(path: Path) -> None:
    global GALLERY_ROOT, CATALOG_PATH, PREVIEW_ROOT
    GALLERY_ROOT = path.resolve()
    CATALOG_PATH = GALLERY_ROOT / "site-data" / "catalog.json"
    PREVIEW_ROOT = GALLERY_ROOT / "site-data" / "previews"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the static gallery catalog.")
    parser.add_argument("--gallery-root", type=Path, default=GALLERY_ROOT)
    return parser.parse_args()


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def rel(path: Path | str | None) -> str | None:
    if not path:
        return None
    path_obj = gallery_path(path)
    try:
        return path_obj.relative_to(GALLERY_ROOT).as_posix()
    except ValueError:
        return path_obj.as_posix()


def gallery_path(path: Path | str) -> Path:
    path_obj = Path(path)
    if path_obj.is_absolute():
        return path_obj
    parts = path_obj.parts
    if parts and parts[0] == "gallery":
        return GALLERY_ROOT.joinpath(*parts[1:])
    return GALLERY_ROOT / path_obj


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def maybe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def doi_url(doi: str | None) -> str | None:
    return f"https://doi.org/{doi}" if doi else None


def source_link(url: str | None) -> str | None:
    return url if url and url.startswith(("http://", "https://")) else None


def preview_path(dataset_id: str, panel_id: str, kind: str) -> Path:
    return PREVIEW_ROOT / Path(dataset_id) / panel_id / f"{kind}.png"


def build_preview(src_path: Path, dst_path: Path) -> None:
    if dst_path.exists() and dst_path.stat().st_mtime >= src_path.stat().st_mtime:
        return
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src_path) as original:
        img = ImageOps.exif_transpose(original).convert("RGBA")
        background = Image.new("RGBA", img.size, img.getpixel((0, 0)))
        diff = ImageChops.difference(img, background)
        bbox = diff.getbbox()
        if bbox:
            pad = max(12, min(img.size) // 40)
            left = max(0, bbox[0] - pad)
            top = max(0, bbox[1] - pad)
            right = min(img.width, bbox[2] + pad)
            bottom = min(img.height, bbox[3] + pad)
            cropped = img.crop((left, top, right, bottom))
        else:
            cropped = img
        cropped.save(dst_path, format="PNG", optimize=True)


def image_complexity(src_path: Path) -> dict[str, float]:
    """Return a reproducible visual complexity score for a cropped panel preview."""
    with Image.open(src_path) as original:
        img = ImageOps.exif_transpose(original).convert("RGBA")
        canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
        canvas.alpha_composite(img)
        rgb = canvas.convert("RGB")
        rgb.thumbnail((512, 512), RESAMPLE_LANCZOS)

        width, height = rgb.size
        total = max(1, width * height)
        gray = ImageOps.grayscale(rgb)
        entropy = max(0.0, min(gray.entropy() / 8.0, 1.0))

        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_hist = edges.histogram()
        edge_density = sum(edge_hist[28:]) / total
        edge_norm = min(edge_density / 0.22, 1.0)

        bg_color = rgb.getpixel((0, 0))
        background = Image.new("RGB", rgb.size, bg_color)
        diff = ImageChops.difference(rgb, background).convert("L")
        diff_hist = diff.histogram()
        content_density = sum(diff_hist[22:]) / total
        content_norm = min(content_density / 0.55, 1.0)

        quantized = rgb.quantize(colors=64)
        color_hist = quantized.histogram()
        color_threshold = max(1, int(total * 0.0005))
        color_count = sum(1 for count in color_hist if count > color_threshold)
        color_diversity = min(color_count / 64.0, 1.0)

    score = 100 * (
        0.38 * entropy
        + 0.34 * edge_norm
        + 0.18 * color_diversity
        + 0.10 * content_norm
    )
    return {
        "score": round(score, 2),
        "entropy": round(entropy, 4),
        "edgeDensity": round(edge_density, 4),
        "colorDiversity": round(color_diversity, 4),
        "contentDensity": round(content_density, 4),
    }


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * pct
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def summarize_complexity(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    bins = []
    for lower, upper in COMPLEXITY_BINS:
        count = sum(1 for value in values if lower <= value < upper)
        label = f"{lower}-{upper if upper <= 100 else 100}"
        bins.append({"range": label, "count": count})
    return {
        "average": round(sum(values) / len(values), 2) if values else 0,
        "min": round(min(values), 2) if values else 0,
        "max": round(max(values), 2) if values else 0,
        "p25": round(percentile(ordered, 0.25), 2) if values else 0,
        "median": round(percentile(ordered, 0.5), 2) if values else 0,
        "p75": round(percentile(ordered, 0.75), 2) if values else 0,
        "bins": bins,
    }


def summarize_refine_complexity(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    bins = []
    for label, lower, upper in REFINE_COMPLEXITY_BINS:
        count = sum(1 for value in values if lower <= value < upper)
        bins.append({"range": label, "count": count})
    exact = Counter(str(int(value)) if float(value).is_integer() else f"{value:.1f}" for value in values)
    return {
        "availableCount": len(values),
        "average": round(sum(values) / len(values), 2) if values else 0,
        "min": round(min(values), 2) if values else 0,
        "max": round(max(values), 2) if values else 0,
        "p25": round(percentile(ordered, 0.25), 2) if values else 0,
        "median": round(percentile(ordered, 0.5), 2) if values else 0,
        "p75": round(percentile(ordered, 0.75), 2) if values else 0,
        "bins": bins,
        "scoreCounts": [{"score": score, "count": count} for score, count in sorted(exact.items(), key=lambda item: float(item[0]))],
    }


def item_complexity_sort_value(item: dict[str, Any]) -> float:
    refine_score = item.get("refineComplexity", {}).get("score")
    if refine_score is not None:
        return to_float(refine_score)
    return to_float(item.get("complexity", {}).get("score")) / 10.0


def dataset_label(dataset_dir: Path) -> str:
    return " / ".join(dataset_dir.relative_to(GALLERY_ROOT).parts)


def discover_dataset_roots() -> list[Path]:
    roots: list[Path] = []
    for summary_path in sorted(GALLERY_ROOT.glob("**/summary.json")):
        if any(part in {"assets", "site-data", "tools", "__pycache__"} for part in summary_path.parts):
            continue
        dataset_dir = summary_path.parent
        if any(part.endswith("_smoke") for part in dataset_dir.relative_to(GALLERY_ROOT).parts):
            continue
        manifest_path = dataset_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        roots.append(dataset_dir)
    return roots


def build_item(dataset: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    panel_dir = gallery_path(row["gallery_dir"])
    record = load_json(panel_dir / "gallery_record.json", {})
    metadata = load_json(panel_dir / "metadata.json", {})
    qwen = load_json(panel_dir / "qwen_score.json", {})
    review = load_json(panel_dir / "reproduce_panel_review_summary.json", {})
    refine_complexity = load_json(panel_dir / "refine_complexity_assessment.json", {})

    panel_id = row.get("panel_id") or record.get("panel_id") or metadata.get("panel_id")
    subtype = row.get("subtype") or record.get("subtype") or qwen.get("data_subtype")
    publication_date = metadata.get("publication_date") or ""
    doi = metadata.get("doi") or metadata.get("paper_id")
    quality_score = to_float(qwen.get("overall_quality_score", metadata.get("overall_quality_score")))
    review_passed = to_bool(review.get("review_passed", row.get("review_passed", record.get("review_passed"))))
    review_rounds = to_float(review.get("review_rounds_completed", row.get("review_rounds_completed", 0)))
    max_rounds = to_float(review.get("max_review_rounds", row.get("max_review_rounds", 0)))
    target_preview = preview_path(dataset["id"], panel_id, "target")
    reproduce_preview = preview_path(dataset["id"], panel_id, "reproduce")
    build_preview(panel_dir / "target.png", target_preview)
    build_preview(panel_dir / "reproduce_panel.png", reproduce_preview)
    complexity = image_complexity(target_preview)
    refine_complexity_score = maybe_float(refine_complexity.get("refine_complexity_score"))

    item = {
        "id": panel_id,
        "uid": f"{dataset['id']}::{panel_id}",
        "dataset": {
            "id": dataset["id"],
            "path": dataset["path"],
            "title": dataset["title"],
            "subject": dataset["subject"],
            "topic": dataset["topic"],
            "summary": dataset["summary"],
        },
        "subtype": subtype,
        "title": f"{metadata.get('figure_label', 'Figure')} {metadata.get('panel_label', '').strip()}".strip(),
        "doi": doi,
        "doiUrl": doi_url(doi),
        "journal": metadata.get("journal"),
        "publicationDate": publication_date,
        "paperId": metadata.get("paper_id"),
        "figureId": metadata.get("figure_id"),
        "figureLabel": metadata.get("figure_label"),
        "panelLabel": metadata.get("panel_label"),
        "caption": metadata.get("panel_caption") or metadata.get("figure_caption") or "",
        "figureCaption": metadata.get("figure_caption") or "",
        "splitReason": metadata.get("split_reason") or "",
        "selectionReason": metadata.get("selection_reason") or "",
        "sourceFigureUrl": source_link(metadata.get("source_figure_url")),
        "paths": {
            "panelDir": rel(panel_dir),
            "target": rel(panel_dir / "target.png"),
            "targetPreview": rel(target_preview),
            "targetPdf": rel(panel_dir / "target.pdf"),
            "reproduce": rel(panel_dir / "reproduce_panel.png"),
            "reproducePreview": rel(reproduce_preview),
            "reproducePdf": rel(panel_dir / "reproduce_panel.pdf"),
            "reproduceCode": rel(panel_dir / "reproduce_panel.py"),
            "metadata": rel(panel_dir / "metadata.json"),
            "galleryRecord": rel(panel_dir / "gallery_record.json"),
            "qwenScore": rel(panel_dir / "qwen_score.json"),
            "qwenPrompt": rel(panel_dir / "qwen_prompt.md"),
            "reviewSummary": rel(panel_dir / "reproduce_panel_review_summary.json"),
            "reviewNotes": rel(panel_dir / "reproduce_panel_review_notes.md"),
            "runLog": rel(panel_dir / "reproduce_panel_run_log.md"),
            "rawResponse": rel(panel_dir / "raw_response.txt"),
            "refineComplexityAssessment": rel(panel_dir / "refine_complexity_assessment.json") if (panel_dir / "refine_complexity_assessment.json").exists() else None,
        },
        "complexity": complexity,
        "refineComplexity": {
            "score": refine_complexity_score,
            "reason": refine_complexity.get("complexity_reason") or "",
            "captionSummary": refine_complexity.get("caption_based_content_summary") or "",
        },
        "galleryRecord": {
            "sourceRunDir": record.get("source_run_dir"),
            "sourceSet": record.get("source_set"),
            "sourcePanelDir": record.get("source_panel_dir"),
            "sourceReviewDir": record.get("source_review_dir"),
            "reviewPassed": to_bool(record.get("review_passed")),
            "reviewRoundsCompleted": to_float(record.get("review_rounds_completed")),
            "maxReviewRounds": to_float(record.get("max_review_rounds")),
            "finalAssessment": record.get("final_assessment") or "",
        },
        "qwen": {
            "category": qwen.get("category") or metadata.get("category"),
            "dataSubtype": qwen.get("data_subtype") or subtype,
            "isCompletePanel": to_bool(qwen.get("is_complete_panel", metadata.get("is_complete_panel"))),
            "hasForeignOverlap": to_bool(qwen.get("has_foreign_overlap", metadata.get("has_foreign_overlap"))),
            "xyLabelComplete": qwen.get("xy_label_complete") or metadata.get("xy_label_complete"),
            "xyTickComplete": qwen.get("xytick_complete") or metadata.get("xytick_complete"),
            "clarityIntegrityScore": to_float(qwen.get("clarity_integrity_score", metadata.get("clarity_integrity_score"))),
            "dataPurityScore": to_float(qwen.get("data_purity_score", metadata.get("data_purity_score"))),
            "codeReproducibilityScore": to_float(qwen.get("code_reproducibility_score", metadata.get("code_reproducibility_score"))),
            "aestheticScore": to_float(qwen.get("aesthetic_score", metadata.get("aesthetic_score"))),
            "overallQualityScore": quality_score,
            "confidence": to_float(qwen.get("confidence", metadata.get("confidence"))),
            "isGoodQuality": to_bool(qwen.get("is_good_quality", metadata.get("is_good_quality"))),
            "shortReason": qwen.get("short_reason") or metadata.get("short_reason") or "",
        },
        "review": {
            "status": review.get("status") or "unknown",
            "passed": review_passed,
            "roundsCompleted": review_rounds,
            "maxRounds": max_rounds,
            "finalAssessment": review.get("final_assessment") or row.get("final_assessment") or record.get("final_assessment") or "",
        },
        "sort": {
            "quality": quality_score,
            "review": (1 if review_passed else 0) * 100 - review_rounds,
            "date": publication_date,
            "complexity": complexity["score"],
        },
    }
    return item


def summarize_dataset(dataset_dir: Path, summary: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    subtypes = Counter(item["subtype"] for item in items)
    journals = Counter(item["journal"] for item in items if item["journal"])
    quality_values = [item["qwen"]["overallQualityScore"] for item in items]
    review_rounds = [item["review"]["roundsCompleted"] for item in items]
    complexity_values = [item["complexity"]["score"] for item in items if item.get("complexity")]
    refine_complexity_values = [item["refineComplexity"]["score"] for item in items if item.get("refineComplexity") and item["refineComplexity"].get("score") is not None]
    return {
        "id": dataset_dir.relative_to(GALLERY_ROOT).as_posix(),
        "path": dataset_dir.relative_to(GALLERY_ROOT).as_posix(),
        "title": dataset_label(dataset_dir),
        "subject": dataset_dir.relative_to(GALLERY_ROOT).parts[0] if len(dataset_dir.relative_to(GALLERY_ROOT).parts) > 0 else "",
        "topic": dataset_dir.relative_to(GALLERY_ROOT).parts[1] if len(dataset_dir.relative_to(GALLERY_ROOT).parts) > 1 else "",
        "summary": rel(dataset_dir / "summary.json"),
        "manifest": rel(dataset_dir / "manifest.json"),
        "exportedPanels": summary.get("exported_panels", len(items)),
        "panelCount": len(items),
        "subtypeCount": len(subtypes),
        "reviewPassedCount": sum(1 for item in items if item["review"]["passed"]),
        "averageQuality": round(sum(quality_values) / len(quality_values), 2) if quality_values else 0,
        "averageReviewRounds": round(sum(review_rounds) / len(review_rounds), 2) if review_rounds else 0,
        "complexity": summarize_complexity(complexity_values),
        "refineComplexity": summarize_refine_complexity(refine_complexity_values),
        "dateMin": min((item["publicationDate"] for item in items if item["publicationDate"]), default=""),
        "dateMax": max((item["publicationDate"] for item in items if item["publicationDate"]), default=""),
        "journals": [{"name": name, "count": count} for name, count in journals.most_common()],
        "subtypes": [{"name": name, "count": count} for name, count in sorted(subtypes.items())],
    }


def summarize_subjects(datasets: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    subjects = sorted({dataset.get("subject", "") for dataset in datasets if dataset.get("subject")})
    rows: list[dict[str, Any]] = []
    for subject in subjects:
        subject_items = [item for item in items if item["dataset"]["subject"] == subject]
        subject_datasets = [dataset for dataset in datasets if dataset.get("subject") == subject]
        journals = Counter(item["journal"] for item in subject_items if item["journal"])
        subtypes = Counter(item["subtype"] for item in subject_items)
        quality_values = [item["qwen"]["overallQualityScore"] for item in subject_items]
        rows.append(
            {
                "id": subject,
                "label": subject.replace("_", " ").title(),
                "datasetIds": [dataset["id"] for dataset in subject_datasets],
                "panelCount": len(subject_items),
                "datasetCount": len(subject_datasets),
                "journalCount": len(journals),
                "subtypeCount": len(subtypes),
                "reviewPassedCount": sum(1 for item in subject_items if item["review"]["passed"]),
                "averageQuality": round(sum(quality_values) / len(quality_values), 2) if quality_values else 0,
                "journals": [{"name": name, "count": count} for name, count in journals.most_common()],
                "subtypes": [{"name": name, "count": count} for name, count in sorted(subtypes.items())],
            }
        )
    return rows


def main() -> None:
    args = parse_args()
    configure_gallery_root(args.gallery_root)

    dataset_dirs = discover_dataset_roots()
    datasets: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []

    for dataset_dir in dataset_dirs:
        summary = load_json(dataset_dir / "summary.json", {})
        manifest = load_json(dataset_dir / "manifest.json", [])
        dataset_stub = {
            "id": dataset_dir.relative_to(GALLERY_ROOT).as_posix(),
            "path": dataset_dir.relative_to(GALLERY_ROOT).as_posix(),
            "title": dataset_label(dataset_dir),
            "subject": dataset_dir.relative_to(GALLERY_ROOT).parts[0] if len(dataset_dir.relative_to(GALLERY_ROOT).parts) > 0 else "",
            "topic": dataset_dir.relative_to(GALLERY_ROOT).parts[1] if len(dataset_dir.relative_to(GALLERY_ROOT).parts) > 1 else "",
            "summary": rel(dataset_dir / "summary.json"),
        }
        dataset_items = [build_item(dataset_stub, row) for row in manifest]
        dataset_items.sort(key=lambda item: (item_complexity_sort_value(item), item["sort"]["quality"], item["sort"]["review"], item["sort"]["date"]), reverse=True)
        datasets.append(summarize_dataset(dataset_dir, summary, dataset_items))
        items.extend(dataset_items)

    items.sort(key=lambda item: (item_complexity_sort_value(item), item["sort"]["quality"], item["sort"]["review"], item["sort"]["date"]), reverse=True)

    subtypes = Counter(item["subtype"] for item in items)
    journals = Counter(item["journal"] for item in items if item["journal"])
    quality_values = [item["qwen"]["overallQualityScore"] for item in items]
    review_rounds = [item["review"]["roundsCompleted"] for item in items]
    complexity_values = [item["complexity"]["score"] for item in items if item.get("complexity")]
    refine_complexity_values = [item["refineComplexity"]["score"] for item in items if item.get("refineComplexity") and item["refineComplexity"].get("score") is not None]

    catalog = {
        "schemaVersion": 5,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": {
            "galleryRoot": rel(GALLERY_ROOT),
            "datasetCount": len(datasets),
            "datasetPaths": [dataset["path"] for dataset in datasets],
        },
        "datasets": datasets,
        "stats": {
            "panelCount": len(items),
            "subtypeCount": len(subtypes),
            "reviewPassedCount": sum(1 for item in items if item["review"]["passed"]),
            "subjectCount": len({dataset["subject"] for dataset in datasets if dataset.get("subject")}),
            "averageQuality": round(sum(quality_values) / len(quality_values), 2) if quality_values else 0,
            "averageReviewRounds": round(sum(review_rounds) / len(review_rounds), 2) if review_rounds else 0,
            "complexity": summarize_complexity(complexity_values),
            "refineComplexity": summarize_refine_complexity(refine_complexity_values),
            "dateMin": min((item["publicationDate"] for item in items if item["publicationDate"]), default=""),
            "dateMax": max((item["publicationDate"] for item in items if item["publicationDate"]), default=""),
            "subjects": summarize_subjects(datasets, items),
            "journals": [{"name": name, "count": count} for name, count in journals.most_common()],
            "subtypes": [{"name": name, "count": count} for name, count in sorted(subtypes.items())],
        },
        "items": items,
    }

    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CATALOG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(catalog, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")

    print(f"Wrote {CATALOG_PATH.relative_to(GALLERY_ROOT)} with {len(items)} panels")


if __name__ == "__main__":
    main()
