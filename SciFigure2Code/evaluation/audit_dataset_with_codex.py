#!/usr/bin/env python3
"""Audit exported SciFigure2Code samples with parallel Codex CLI workers.

This script audits existing benchmark folders. It does not edit sample
directories: nested Codex runs in read-only mode by default and the parent
process writes audit artifacts under a separate output directory.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from SciFigure2Code.evaluation.dataset import DatasetLoader
    from SciFigure2Code.evaluation.schemas import Sample
    from SciFigure2Code.evaluation.utils import ensure_dir, now_iso, safe_name, write_json
else:
    from .dataset import DatasetLoader
    from .schemas import Sample
    from .utils import ensure_dir, now_iso, safe_name, write_json


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = PROJECT_ROOT / "FigureComplexityDataset_3levels_threshold_1_3_4_5_6_10"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "SciFigure2Code" / "audits" / "codex_dataset_audit"
DEFAULT_JOBS = 16
DEFAULT_TIMEOUT = 900


sys.path.insert(0, str(PROJECT_ROOT))

from examples.prompt_codex_reproduce_fig02_g import (  # noqa: E402
    is_retryable_codex_error,
    run_codex_with_capacity,
    sleep_before_retry,
)


@dataclass
class StaticFinding:
    category: str
    severity_hint: str
    line: int
    text: str
    reason: str


@dataclass
class StaticPrecheck:
    panel_id: str
    code_path: str
    direct_image_load_hints: int
    target_or_source_dependency_hints: int
    pixel_painting_hints: int
    raster_tracing_hints: int
    text_overlap_known_from_review: bool | None
    review_passed: bool | None
    findings: list[StaticFinding]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit SciFigure2Code sample folders with Codex.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="FigureComplexityDataset_* root.")
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT, help="Repository root for manifest paths.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Audit output root.")
    parser.add_argument("--level", action="append", choices=["low", "medium", "high", "unknown_complexity"])
    parser.add_argument("--subject", action="append", help="Filter by subject/domain; repeatable.")
    parser.add_argument("--subtype", action="append", help="Filter by chart subtype; repeatable.")
    parser.add_argument("--sample-id", action="append", help="Audit only this panel_id; repeatable.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum selected samples after filtering.")
    parser.add_argument("--num-shards", type=int, default=None, help="Split matched samples into this many shards.")
    parser.add_argument("--shard-index", type=int, default=None, help="Run only this zero-based shard.")
    parser.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help="Parallel Codex workers.")
    parser.add_argument(
        "--max-codex-processes",
        type=int,
        default=DEFAULT_JOBS,
        help="Maximum active codex processes allowed for --process-user.",
    )
    parser.add_argument("--process-user", default="liwentao", help="User whose codex processes are counted.")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Timeout per sample in seconds.")
    parser.add_argument("--model", default=None, help="Optional Codex model override.")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--codex-retries", type=int, default=3)
    parser.add_argument("--codex-retry-sleep", type=float, default=15.0)
    parser.add_argument("--sandbox", default="read-only", choices=["read-only", "workspace-write", "danger-full-access"])
    parser.add_argument("--skip-existing", action="store_true", help="Skip samples with complete audit.json.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing audit artifacts.")
    parser.add_argument("--dry-run", action="store_true", help="Build queue/prompts but do not run Codex.")
    parser.add_argument("--dry-run-prompt-limit", type=int, default=3, help="How many prompts to write during dry run.")
    parser.add_argument("--stream-events", action="store_true", help="Print nested Codex JSONL events.")
    return parser.parse_args(argv)


def resolve(path: Path) -> Path:
    return path.expanduser().resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def apply_shard(samples: list[Sample], num_shards: int | None, shard_index: int | None) -> list[Sample]:
    if num_shards is None and shard_index is None:
        return samples
    if num_shards is None or shard_index is None:
        raise SystemExit("--num-shards and --shard-index must be provided together")
    if num_shards <= 0:
        raise SystemExit("--num-shards must be positive")
    if shard_index < 0 or shard_index >= num_shards:
        raise SystemExit("--shard-index must be in [0, num_shards)")
    return [sample for idx, sample in enumerate(samples) if idx % num_shards == shard_index]


def audit_dir_for(output_dir: Path, sample: Sample) -> Path:
    return output_dir / safe_name(sample.panel_id)


def audit_json_complete(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    required = {"panel_id", "status", "overall_pass", "severity", "issue_flags", "evidence", "confidence"}
    if not required.issubset(data):
        return False
    flags = data.get("issue_flags")
    return isinstance(flags, dict) and data.get("status") in {"complete", "error"}


def read_json_dict(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def read_text_limited(path: Path | None, max_chars: int = 3000) -> str:
    if path is None or not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[truncated]"


def path_from_record(sample: Sample, key: str) -> Path | None:
    value = sample.record.get(key)
    if value in (None, ""):
        return None
    path = Path(str(value))
    return path if path.is_absolute() else sample.repo_root / path


def line_findings(code_path: Path, patterns: list[tuple[str, str, str, str]]) -> list[StaticFinding]:
    if not code_path.is_file():
        return []
    findings: list[StaticFinding] = []
    lines = code_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        for category, severity, reason, pattern in patterns:
            if re.search(pattern, line, flags=re.IGNORECASE):
                findings.append(
                    StaticFinding(
                        category=category,
                        severity_hint=severity,
                        line=lineno,
                        text=stripped[:240],
                        reason=reason,
                    )
                )
                break
        if len(findings) >= 80:
            break
    return findings


def static_precheck(sample: Sample) -> StaticPrecheck:
    code_path = sample.reference_code or path_from_record(sample, "reproduce_code") or Path("")
    review = read_json_dict(path_from_record(sample, "review_summary_json"))
    patterns = [
        (
            "direct_image_load",
            "major",
            "The code appears to open/read an image file; check whether it loads target/source/reproduction pixels.",
            r"\b(Image\.open|plt\.imread|mpimg\.imread|cv2\.imread|imageio\.imread|skimage\.io\.imread)\b",
        ),
        (
            "target_or_source_dependency",
            "critical",
            "The code references target/source artifacts; this can indicate direct image editing or copying.",
            r"(target\.png|target_pdf|SCIFIGURE_TARGET|source_figure|source_.*png|curated_image_path|target_path)",
        ),
        (
            "copy_or_base64",
            "critical",
            "The code appears to copy/decode an image artifact instead of reconstructing the plot.",
            r"(shutil\.copy|copyfile|base64\.b64decode|BytesIO\()",
        ),
        (
            "pixel_painting",
            "major",
            "The code appears to set individual pixels or loop over image dimensions.",
            r"(putpixel|pixels?\[|np\.ndindex|for\s+\w+\s+in\s+range\([^)]*(width|height|CANVAS_W|CANVAS_H|shape))",
        ),
        (
            "raster_tracing",
            "major",
            "The code appears to construct large raster canvases; check whether this is data-matrix plotting or raster tracing.",
            r"(np\.zeros\([^)]*(CANVAS|height|width|H\s*,\s*W)|Image\.new\(|fromarray\(|imshow\()",
        ),
    ]
    findings = line_findings(code_path, patterns)
    direct_image = sum(1 for item in findings if item.category == "direct_image_load")
    target_ref = sum(1 for item in findings if item.category in {"target_or_source_dependency", "copy_or_base64"})
    pixel = sum(1 for item in findings if item.category == "pixel_painting")
    raster = sum(1 for item in findings if item.category == "raster_tracing")
    layout_passed = review.get("layout_audit_passed")
    return StaticPrecheck(
        panel_id=sample.panel_id,
        code_path=str(code_path),
        direct_image_load_hints=direct_image,
        target_or_source_dependency_hints=target_ref,
        pixel_painting_hints=pixel,
        raster_tracing_hints=raster,
        text_overlap_known_from_review=(False if layout_passed is False else True if layout_passed is True else None),
        review_passed=(True if review.get("review_passed") is True else False if review.get("review_passed") is False else None),
        findings=findings[:40],
    )


def precheck_to_json(precheck: StaticPrecheck) -> dict[str, Any]:
    payload = asdict(precheck)
    payload["findings"] = [asdict(item) for item in precheck.findings]
    return payload


def build_prompt(sample: Sample, audit_dir: Path, precheck: StaticPrecheck) -> str:
    metadata_path = path_from_record(sample, "metadata_json")
    qwen_path = path_from_record(sample, "qwen_score_json")
    review_path = path_from_record(sample, "review_summary_json")
    complexity_path = path_from_record(sample, "complexity_json")
    description_path = sample.description_md or path_from_record(sample, "description_md")
    code_path = sample.reference_code or path_from_record(sample, "reproduce_code")
    target_png = sample.target_png or path_from_record(sample, "target_png")
    reference_png = sample.reference_png or path_from_record(sample, "reproduce_png")

    return f"""
You are auditing one SciFigure2Code benchmark sample. This is a quality-control
audit, not a rewrite task. Do not edit files. Read the target image, reproduced
image, and reproduction code, then return one JSON object only.

Panel id: {sample.panel_id}
Audit output directory managed by parent process: {audit_dir}

Files to inspect:
- target panel image: {target_png}
- current reproduced image: {reference_png}
- reproduction code: {code_path}
- metadata JSON: {metadata_path}
- Qwen score JSON: {qwen_path}
- prior review summary JSON: {review_path}
- complexity JSON: {complexity_path}
- description markdown: {description_path}

What to audit:
1. Text overlap / clipping / font crowding. This is usually minor unless it
   damages readability or hides important labels.
2. Plotting logic errors. This is major. The reference code should reconstruct
   an editable scientific plot from visible values, data arrays, plotting
   primitives, or a meaningful matrix. It is NOT acceptable to imitate a plot
   by painting one pixel/cell at a time from a raster or by using thousands of
   hard-coded rectangles/colors that amount to image tracing. For heatmaps,
   imshow/pcolormesh is acceptable only when the code defines a meaningful data
   matrix or synthetic data matrix. It is not acceptable if the matrix is just
   sampled from the target image or manually transcribed as raster pixels.
3. Direct original-image editing. This is critical. The code must not load
   target.png, the source full figure, a prior reproduction image, or another
   paper image and then crop, copy, annotate, recolor, or lightly edit it.
   Maps are not exempt: loading the original map image and drawing on top of it
   is a direct-image-edit failure.

Static precheck hints from the parent process. These are hints, not final
judgment; verify by reading the code and images:
{json.dumps(precheck_to_json(precheck), ensure_ascii=False, indent=2)}

Relevant text excerpts:
--- description.md ---
{read_text_limited(description_path, 2500)}

--- metadata.json ---
{read_text_limited(metadata_path, 3500)}

--- qwen_score.json ---
{read_text_limited(qwen_path, 1600)}

--- reproduce_panel_review_summary.json ---
{read_text_limited(review_path, 1600)}

Required JSON response schema:
{{
  "panel_id": "{sample.panel_id}",
  "status": "complete",
  "overall_pass": true,
  "severity": "clean",
  "issue_flags": {{
    "text_overlap": false,
    "plotting_logic_error": false,
    "direct_image_edit": false,
    "pixel_painting_or_raster_tracing": false,
    "execution_or_artifact_problem": false,
    "other": false
  }},
  "issue_summary": "One concise sentence.",
  "evidence": [
    {{
      "issue": "short issue name",
      "severity": "minor|major|critical",
      "file": "path or image name",
      "line": 123,
      "finding": "specific observation",
      "why_it_matters": "specific consequence"
    }}
  ],
  "recommended_action": "keep|minor_fix|rewrite_plot_logic|remove_image_dependency|manual_review",
  "confidence": 0.0
}}

Severity rules:
- "clean": no meaningful issue found.
- "minor": only text overlap/font/crowding or other small polish issue.
- "major": plotting logic is wrong, raster-traced, or not meaningfully editable.
- "critical": direct target/source image loading/editing/copying, or benchmark
  leakage that makes the sample invalid.

Return only the JSON object. Do not wrap it in Markdown. Do not include prose
outside JSON.
""".strip()


JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_audit_json(text: str, sample: Sample) -> dict[str, Any]:
    stripped = (text or "").strip()
    candidates = [stripped]
    match = JSON_OBJECT_RE.search(stripped)
    if match:
        candidates.append(match.group(0))
    last_error = ""
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return normalize_audit_payload(payload, sample)
        except Exception as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
    raise ValueError(f"could not parse audit JSON for {sample.panel_id}: {last_error}")


def normalize_audit_payload(payload: dict[str, Any], sample: Sample) -> dict[str, Any]:
    flags = payload.get("issue_flags")
    if not isinstance(flags, dict):
        flags = {}
    normalized_flags = {
        "text_overlap": bool(flags.get("text_overlap", False)),
        "plotting_logic_error": bool(flags.get("plotting_logic_error", False)),
        "direct_image_edit": bool(flags.get("direct_image_edit", False)),
        "pixel_painting_or_raster_tracing": bool(flags.get("pixel_painting_or_raster_tracing", False)),
        "execution_or_artifact_problem": bool(flags.get("execution_or_artifact_problem", False)),
        "other": bool(flags.get("other", False)),
    }
    severity = str(payload.get("severity") or "").strip().lower()
    if severity not in {"clean", "minor", "major", "critical"}:
        if normalized_flags["direct_image_edit"]:
            severity = "critical"
        elif normalized_flags["plotting_logic_error"] or normalized_flags["pixel_painting_or_raster_tracing"]:
            severity = "major"
        elif normalized_flags["text_overlap"] or normalized_flags["other"]:
            severity = "minor"
        else:
            severity = "clean"
    confidence = payload.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except Exception:
        confidence = 0.0
    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    return {
        "panel_id": sample.panel_id,
        "status": "complete",
        "overall_pass": bool(payload.get("overall_pass", severity == "clean")),
        "severity": severity,
        "issue_flags": normalized_flags,
        "issue_summary": str(payload.get("issue_summary") or "").strip(),
        "evidence": evidence,
        "recommended_action": str(payload.get("recommended_action") or "manual_review").strip(),
        "confidence": confidence,
        "audited_at": now_iso(),
        "sample": sample.to_json_dict(),
    }


def run_one_sample(sample: Sample, args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    sample_dir = ensure_dir(audit_dir_for(output_dir, sample))
    audit_path = sample_dir / "audit.json"
    prompt_path = sample_dir / "prompt.md"
    response_path = sample_dir / "raw_response.txt"
    precheck_path = sample_dir / "static_precheck.json"
    error_path = sample_dir / "error.json"

    if args.skip_existing and not args.overwrite and audit_json_complete(audit_path):
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        payload["resumed"] = True
        return payload

    precheck = static_precheck(sample)
    write_json(precheck_path, precheck_to_json(precheck))
    prompt = build_prompt(sample, sample_dir, precheck)
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    if args.dry_run:
        return {
            "panel_id": sample.panel_id,
            "status": "dry_run",
            "overall_pass": None,
            "severity": "not_run",
            "issue_flags": {},
            "issue_summary": "Dry run only; Codex was not called.",
            "evidence": [],
            "recommended_action": "not_run",
            "confidence": 0.0,
            "sample": sample.to_json_dict(),
        }

    max_attempts = max(1, args.codex_retries)
    answer = ""
    for attempt in range(1, max_attempts + 1):
        try:
            if attempt > 1:
                sleep_before_retry(args.codex_retry_sleep, attempt - 1, sample.panel_id)
            answer = run_codex_with_capacity(
                prompt,
                cwd=PROJECT_ROOT,
                panel_id=sample.panel_id,
                process_user=args.process_user,
                max_codex_processes=args.max_codex_processes,
                poll_seconds=args.poll_seconds,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                sandbox=args.sandbox,
                timeout=args.timeout,
                stream_events=args.stream_events,
            )
            break
        except Exception as exc:
            if attempt >= max_attempts or not is_retryable_codex_error(exc):
                error_payload = {
                    "panel_id": sample.panel_id,
                    "status": "error",
                    "error": f"{exc.__class__.__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                    "sample": sample.to_json_dict(),
                    "failed_at": now_iso(),
                }
                write_json(error_path, error_payload)
                raise
            print(
                f"[{sample.panel_id}] transient Codex failure on attempt {attempt}/{max_attempts}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    response_path.write_text(answer + "\n", encoding="utf-8")
    audit = parse_audit_json(answer, sample)
    write_json(audit_path, audit)
    return audit


def write_selected_samples(output_dir: Path, samples: list[Sample]) -> None:
    write_json(output_dir / "selected_samples.json", [sample.to_json_dict() for sample in samples])


def summary_row(audit: dict[str, Any]) -> dict[str, Any]:
    sample = audit.get("sample", {})
    flags = audit.get("issue_flags", {}) if isinstance(audit.get("issue_flags"), dict) else {}
    return {
        "panel_id": audit.get("panel_id", sample.get("panel_id", "")),
        "status": audit.get("status", ""),
        "overall_pass": audit.get("overall_pass"),
        "severity": audit.get("severity", ""),
        "recommended_action": audit.get("recommended_action", ""),
        "confidence": audit.get("confidence", ""),
        "text_overlap": flags.get("text_overlap", False),
        "plotting_logic_error": flags.get("plotting_logic_error", False),
        "direct_image_edit": flags.get("direct_image_edit", False),
        "pixel_painting_or_raster_tracing": flags.get("pixel_painting_or_raster_tracing", False),
        "execution_or_artifact_problem": flags.get("execution_or_artifact_problem", False),
        "other": flags.get("other", False),
        "issue_summary": audit.get("issue_summary", ""),
        "subject": sample.get("subject", ""),
        "subtype": sample.get("subtype", ""),
        "complexity_level": sample.get("complexity_level", ""),
        "refine_complexity_score": sample.get("refine_complexity_score", ""),
    }


def audit_has_problem(audit: dict[str, Any]) -> bool:
    status = audit.get("status")
    if status != "complete":
        return False
    flags = audit.get("issue_flags", {}) if isinstance(audit.get("issue_flags"), dict) else {}
    return (
        audit.get("overall_pass") is False
        or audit.get("severity") in {"minor", "major", "critical"}
        or any(flags.get(key) is True for key in flags)
    )


def audit_folder_path_from_item(audit: dict[str, Any]) -> str:
    sample = audit.get("sample", {}) if isinstance(audit.get("sample"), dict) else {}
    return str(sample.get("dataset_dir") or "")


def write_problematic_folder_index(output_dir: Path, audits: list[dict[str, Any]]) -> None:
    completed = [item for item in audits if item.get("status") == "complete"]
    problematic = [item for item in completed if audit_has_problem(item)]
    errors = [item for item in audits if item.get("status") == "error"]
    issue_keys = [
        "text_overlap",
        "plotting_logic_error",
        "direct_image_edit",
        "pixel_painting_or_raster_tracing",
        "execution_or_artifact_problem",
        "other",
    ]

    def compact(item: dict[str, Any]) -> dict[str, Any]:
        sample = item.get("sample", {}) if isinstance(item.get("sample"), dict) else {}
        flags = item.get("issue_flags", {}) if isinstance(item.get("issue_flags"), dict) else {}
        panel_id = str(item.get("panel_id") or sample.get("panel_id") or "unknown")
        return {
            "folder": str(sample.get("dataset_dir") or ""),
            "panel_id": panel_id,
            "severity": item.get("severity", ""),
            "recommended_action": item.get("recommended_action", ""),
            "issue_flags": {key: bool(flags.get(key, False)) for key in issue_keys},
            "issue_summary": item.get("issue_summary", ""),
            "audit_json": str(output_dir / safe_name(panel_id) / "audit.json"),
        }

    write_json(
        output_dir / "problematic_folders.json",
        {
            "created_at": now_iso(),
            "total_audits": len(audits),
            "completed": len(completed),
            "problematic_count": len(problematic),
            "problematic_rate": (len(problematic) / len(completed) if completed else None),
            "error_count": len(errors),
            "problematic_folders": [compact(item) for item in problematic],
            "error_folders": [compact(item) for item in errors],
        },
    )
    write_json(
        output_dir / "problematic_folder_paths.json",
        {
            "created_at": now_iso(),
            "total_audits": len(audits),
            "completed": len(completed),
            "problematic_count": len(problematic),
            "problematic_rate": (len(problematic) / len(completed) if completed else None),
            "error_count": len(errors),
            "problematic_folder_paths": [audit_folder_path for audit_folder_path in map(audit_folder_path_from_item, problematic) if audit_folder_path],
            "error_folder_paths": [audit_folder_path for audit_folder_path in map(audit_folder_path_from_item, errors) if audit_folder_path],
        },
    )


def write_summary(output_dir: Path, audits: list[dict[str, Any]]) -> None:
    rows = [summary_row(item) for item in audits]
    columns = [
        "panel_id",
        "status",
        "overall_pass",
        "severity",
        "recommended_action",
        "confidence",
        "text_overlap",
        "plotting_logic_error",
        "direct_image_edit",
        "pixel_painting_or_raster_tracing",
        "execution_or_artifact_problem",
        "other",
        "issue_summary",
        "subject",
        "subtype",
        "complexity_level",
        "refine_complexity_score",
    ]
    with (output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    severity_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    flag_counts = {
        "text_overlap": 0,
        "plotting_logic_error": 0,
        "direct_image_edit": 0,
        "pixel_painting_or_raster_tracing": 0,
        "execution_or_artifact_problem": 0,
        "other": 0,
    }
    for row in rows:
        severity = str(row.get("severity") or "unknown")
        action = str(row.get("recommended_action") or "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        action_counts[action] = action_counts.get(action, 0) + 1
        for key in flag_counts:
            if row.get(key) is True:
                flag_counts[key] += 1
    write_json(
        output_dir / "summary.json",
        {
            "created_at": now_iso(),
            "total": len(rows),
            "completed": sum(1 for row in rows if row.get("status") == "complete"),
            "dry_run": sum(1 for row in rows if row.get("status") == "dry_run"),
            "errors": sum(1 for row in rows if row.get("status") == "error"),
            "severity_counts": severity_counts,
            "recommended_action_counts": action_counts,
            "issue_flag_counts": flag_counts,
            "summary_csv": output_dir / "summary.csv",
        },
    )
    write_problematic_folder_index(output_dir, audits)


def write_dry_run_prompts(samples: list[Sample], output_dir: Path, args: argparse.Namespace) -> None:
    count = max(0, min(args.dry_run_prompt_limit, len(samples)))
    prompt_root = ensure_dir(output_dir / "dry_run_prompts")
    for sample in samples[:count]:
        sample_dir = ensure_dir(prompt_root / safe_name(sample.panel_id))
        precheck = static_precheck(sample)
        write_json(sample_dir / "static_precheck.json", precheck_to_json(precheck))
        (sample_dir / "prompt.md").write_text(build_prompt(sample, sample_dir, precheck) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args() if argv is None else parse_args(argv)
    dataset_root = resolve(args.dataset)
    repo_root = resolve(args.repo_root)
    output_dir = ensure_dir(resolve(args.output_dir))

    if args.jobs < 1:
        raise SystemExit("--jobs must be >= 1")
    if args.max_codex_processes < 1:
        raise SystemExit("--max-codex-processes must be >= 1")
    if args.codex_retries < 1:
        raise SystemExit("--codex-retries must be >= 1")

    loader = DatasetLoader(dataset_root, repo_root=repo_root)
    samples = loader.load(
        levels=args.level,
        sample_ids=args.sample_id,
        subtypes=args.subtype,
        subjects=args.subject,
        limit=args.limit,
        require_target=True,
    )
    samples = apply_shard(samples, args.num_shards, args.shard_index)
    if not samples:
        raise SystemExit("No samples matched the requested filters.")

    write_json(
        output_dir / "run_config.json",
        {
            "created_at": now_iso(),
            "dataset": dataset_root,
            "repo_root": repo_root,
            "output_dir": output_dir,
            "sample_count": len(samples),
            "jobs": args.jobs,
            "max_codex_processes": args.max_codex_processes,
            "process_user": args.process_user,
            "timeout": args.timeout,
            "model": args.model,
            "reasoning_effort": args.reasoning_effort,
            "sandbox": args.sandbox,
            "dry_run": args.dry_run,
            "filters": {
                "level": args.level,
                "subject": args.subject,
                "subtype": args.subtype,
                "sample_id": args.sample_id,
                "limit": args.limit,
                "num_shards": args.num_shards,
                "shard_index": args.shard_index,
            },
        },
    )
    write_selected_samples(output_dir, samples)
    print(f"Loaded {len(samples)} samples from {loader.manifest_path()}", flush=True)
    print(f"Audit output: {output_dir}", flush=True)
    print(f"jobs={args.jobs} max_codex_processes={args.max_codex_processes} sandbox={args.sandbox}", flush=True)

    if args.dry_run:
        write_dry_run_prompts(samples, output_dir, args)
        dry_audits = [run_one_sample(sample, args, output_dir) for sample in samples]
        write_summary(output_dir, dry_audits)
        print(f"dry_run_selected_samples={output_dir / 'selected_samples.json'}", flush=True)
        print(f"dry_run_prompts={output_dir / 'dry_run_prompts'}", flush=True)
        print(f"summary_json={output_dir / 'summary.json'}", flush=True)
        return 0

    max_workers = min(args.jobs, args.max_codex_processes, len(samples))
    audits: list[dict[str, Any]] = []
    failures = 0
    start = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_sample = {executor.submit(run_one_sample, sample, args, output_dir): sample for sample in samples}
        for done, future in enumerate(concurrent.futures.as_completed(future_to_sample), start=1):
            sample = future_to_sample[future]
            try:
                audit = future.result()
            except Exception as exc:
                failures += 1
                audit = {
                    "panel_id": sample.panel_id,
                    "status": "error",
                    "overall_pass": False,
                    "severity": "error",
                    "issue_flags": {},
                    "issue_summary": f"{exc.__class__.__name__}: {exc}",
                    "evidence": [],
                    "recommended_action": "manual_review",
                    "confidence": 0.0,
                    "sample": sample.to_json_dict(),
                }
                write_json(audit_dir_for(output_dir, sample) / "audit.json", audit)
                print(f"[{done}/{len(samples)}] ERROR {sample.panel_id}: {exc}", file=sys.stderr, flush=True)
                print(traceback.format_exc(), file=sys.stderr, flush=True)
            else:
                print(
                    f"[{done}/{len(samples)}] {sample.panel_id} "
                    f"{audit.get('severity')} pass={audit.get('overall_pass')}",
                    flush=True,
                )
            audits.append(audit)

    write_summary(output_dir, audits)
    elapsed = time.monotonic() - start
    print(f"summary_json={output_dir / 'summary.json'}", flush=True)
    print(f"elapsed_seconds={elapsed:.1f}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
