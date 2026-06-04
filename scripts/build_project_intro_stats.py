#!/usr/bin/env python3
"""Build dataset statistics and plots for the NaturePanelForge intro/methods doc."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


QWEN_SCORE_FIELDS = [
    "clarity_integrity_score",
    "data_purity_score",
    "code_reproducibility_score",
    "aesthetic_score",
    "overall_quality_score",
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score_label(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def manifest_paths(gallery_root: Path, include_smoke: bool) -> list[Path]:
    paths = sorted(gallery_root.glob("*/*/manifest.json"))
    if include_smoke:
        return paths
    return [path for path in paths if "smoke" not in str(path).lower()]


def collect_records(gallery_root: Path, include_smoke: bool = False) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for manifest_path in manifest_paths(gallery_root, include_smoke=include_smoke):
        rows = read_json(manifest_path)
        if not isinstance(rows, list):
            continue
        dataset_id = "/".join(manifest_path.relative_to(gallery_root).parts[:2])
        subject = manifest_path.relative_to(gallery_root).parts[0]
        for row in rows:
            if not isinstance(row, dict):
                continue
            gallery_dir = gallery_root.parent / row.get("gallery_dir", "")
            qwen = read_json(gallery_dir / "qwen_score.json") if (gallery_dir / "qwen_score.json").exists() else {}
            complexity = (
                read_json(gallery_dir / "refine_complexity_assessment.json")
                if (gallery_dir / "refine_complexity_assessment.json").exists()
                else {}
            )
            metadata = read_json(gallery_dir / "metadata.json") if (gallery_dir / "metadata.json").exists() else {}
            record = {
                "dataset_id": dataset_id,
                "subject": subject,
                "panel_id": row.get("panel_id"),
                "subtype": row.get("subtype") or qwen.get("data_subtype") or "unknown",
                "review_passed": bool(row.get("review_passed")),
                "review_rounds_completed": as_float(row.get("review_rounds_completed")),
                "qwen_category": qwen.get("category", "missing"),
                "journal": metadata.get("journal") or "unknown",
                "publication_date": metadata.get("publication_date") or "",
                "refine_complexity_score": as_float(complexity.get("refine_complexity_score")),
            }
            for field in QWEN_SCORE_FIELDS:
                record[field] = as_float(qwen.get(field))
            records.append(record)
    return records


def value_counts(values: list[Any]) -> list[dict[str, Any]]:
    counts = Counter(v for v in values if v is not None and v != "")
    def sort_key(item: tuple[Any, int]) -> tuple[int, float | str]:
        key, _ = item
        try:
            return (0, float(key))
        except (TypeError, ValueError):
            return (1, str(key))
    return [{"value": str(k), "count": v} for k, v in sorted(counts.items(), key=sort_key)]


def numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    sorted_values = sorted(values)
    def quantile(q: float) -> float:
        if len(sorted_values) == 1:
            return sorted_values[0]
        pos = (len(sorted_values) - 1) * q
        lo = int(pos)
        hi = min(lo + 1, len(sorted_values) - 1)
        frac = pos - lo
        return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac
    return {
        "count": len(values),
        "mean": round(mean(values), 3),
        "min": min(values),
        "p25": round(quantile(0.25), 3),
        "median": round(quantile(0.5), 3),
        "p75": round(quantile(0.75), 3),
        "max": max(values),
    }


def build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_subject[record["subject"]].append(record)

    subjects = []
    for subject, rows in sorted(by_subject.items()):
        subjects.append(
            {
                "subject": subject,
                "panels": len(rows),
                "review_passed": sum(1 for row in rows if row["review_passed"]),
                "qwen_available": sum(1 for row in rows if row.get("overall_quality_score") is not None),
                "complexity_available": sum(1 for row in rows if row.get("refine_complexity_score") is not None),
                "unique_journals": len({row["journal"] for row in rows if row["journal"] != "unknown"}),
                "chart_subtypes": len({row["subtype"] for row in rows if row["subtype"] != "unknown"}),
            }
        )

    qwen_distributions = {
        field: value_counts([score_label(v) for v in [row.get(field) for row in records] if isinstance(v, float)])
        for field in QWEN_SCORE_FIELDS
    }
    complexity_values = [
        row["refine_complexity_score"]
        for row in records
        if isinstance(row.get("refine_complexity_score"), float)
    ]
    complexity_distribution = value_counts([score_label(v) for v in complexity_values])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_panels": len(records),
        "subjects": subjects,
        "qwen": {
            "fields": QWEN_SCORE_FIELDS,
            "overall_quality_summary": numeric_summary(
                [row["overall_quality_score"] for row in records if isinstance(row.get("overall_quality_score"), float)]
            ),
            "distributions": qwen_distributions,
        },
        "codex_refine_complexity": {
            "summary": numeric_summary(complexity_values),
            "distribution": complexity_distribution,
        },
        "qwen_categories": value_counts([row.get("qwen_category") for row in records]),
        "chart_subtypes_top20": Counter(row["subtype"] for row in records).most_common(20),
    }


def write_csvs(records: list[dict[str, Any]], summary: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "dataset_subject_counts.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary["subjects"][0].keys()))
        writer.writeheader()
        writer.writerows(summary["subjects"])
    with (out_dir / "qwen_overall_quality_distribution.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["value", "count"])
        writer.writeheader()
        writer.writerows(summary["qwen"]["distributions"]["overall_quality_score"])
    with (out_dir / "qwen_score_dimension_distribution.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value", "count"])
        writer.writeheader()
        for metric, rows in summary["qwen"]["distributions"].items():
            for row in rows:
                writer.writerow({"metric": metric, **row})
    with (out_dir / "codex_refine_complexity_distribution.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["value", "count"])
        writer.writeheader()
        writer.writerows(summary["codex_refine_complexity"]["distribution"])
    with (out_dir / "dataset_stats_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)


def plot(summary: dict[str, Any], out_dir: Path) -> None:
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "Arial",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.dpi": 180,
        }
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    subjects = summary["subjects"]
    labels = [item["subject"].title() for item in subjects]
    counts = [item["panels"] for item in subjects]
    fig, ax = plt.subplots(figsize=(8.8, 4.6))
    bars = ax.bar(labels, counts, color=["#2563eb", "#0d9488", "#d97706", "#7c3aed", "#0891b2"][: len(labels)])
    ax.set_ylabel("Panels")
    ax.set_title("Current Gallery Dataset Size by Domain")
    ax.bar_label(bars, labels=[f"{v:,}" for v in counts], padding=3, fontsize=9)
    ax.set_ylim(0, max(counts) * 1.16)
    fig.tight_layout()
    fig.savefig(out_dir / "dataset_domain_counts.png", bbox_inches="tight")
    plt.close(fig)

    qdist = summary["qwen"]["distributions"]["overall_quality_score"]
    qlabels = [item["value"] for item in qdist]
    qcounts = [item["count"] for item in qdist]
    fig, ax = plt.subplots(figsize=(8.8, 4.6))
    bars = ax.bar(qlabels, qcounts, color="#2563eb")
    ax.set_xlabel("Qwen overall_quality_score")
    ax.set_ylabel("Panels")
    ax.set_title("Qwen Overall Quality Score Distribution")
    ax.bar_label(bars, labels=[f"{v:,}" for v in qcounts], padding=3, fontsize=8)
    ax.set_ylim(0, max(qcounts) * 1.18 if qcounts else 1)
    fig.tight_layout()
    fig.savefig(out_dir / "qwen_overall_quality_distribution.png", bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10.8, 5.2))
    metrics = summary["qwen"]["fields"]
    values = sorted(
        {
            item["value"]
            for metric in metrics
            for item in summary["qwen"]["distributions"].get(metric, [])
        },
        key=lambda item: float(item),
    )
    x = list(range(len(values)))
    width = 0.14
    colors = ["#2563eb", "#0d9488", "#d97706", "#7c3aed", "#0891b2"]
    metric_labels = {
        "clarity_integrity_score": "Clarity",
        "data_purity_score": "Data purity",
        "code_reproducibility_score": "Code reproducibility",
        "aesthetic_score": "Aesthetic",
        "overall_quality_score": "Overall",
    }
    for idx, metric in enumerate(metrics):
        counts_by_value = {
            item["value"]: item["count"] for item in summary["qwen"]["distributions"].get(metric, [])
        }
        offsets = [pos + (idx - (len(metrics) - 1) / 2) * width for pos in x]
        ax.bar(
            offsets,
            [counts_by_value.get(value, 0) for value in values],
            width=width,
            color=colors[idx],
            label=metric_labels.get(metric, metric),
        )
    ax.set_xticks(x)
    ax.set_xticklabels(values)
    ax.set_xlabel("Qwen score")
    ax.set_ylabel("Panels")
    ax.set_title("Qwen Score Distribution Across Five Quality Dimensions")
    ax.legend(ncols=2, frameon=False)
    fig.tight_layout()
    fig.savefig(out_dir / "qwen_score_dimension_distribution.png", bbox_inches="tight")
    plt.close(fig)

    cdist = summary["codex_refine_complexity"]["distribution"]
    clabels = [item["value"] for item in cdist]
    ccounts = [item["count"] for item in cdist]
    fig, ax = plt.subplots(figsize=(8.8, 4.6))
    bars = ax.bar(clabels, ccounts, color="#0d9488")
    ax.set_xlabel("Codex refine_complexity_score")
    ax.set_ylabel("Panels")
    ax.set_title("Codex Final-Refine Complexity Distribution")
    ax.bar_label(bars, labels=[f"{v:,}" for v in ccounts], padding=3, fontsize=8)
    ax.set_ylim(0, max(ccounts) * 1.18 if ccounts else 1)
    fig.tight_layout()
    fig.savefig(out_dir / "codex_refine_complexity_distribution.png", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gallery-root", type=Path, default=project_root().parent / "gallery")
    parser.add_argument("--out-dir", type=Path, default=project_root() / "docs" / "assets" / "dataset_stats")
    parser.add_argument("--include-smoke", action="store_true")
    args = parser.parse_args()

    records = collect_records(args.gallery_root, include_smoke=args.include_smoke)
    if not records:
        raise SystemExit(f"No gallery records found under {args.gallery_root}")
    summary = build_summary(records)
    write_csvs(records, summary, args.out_dir)
    plot(summary, args.out_dir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
