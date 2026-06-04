#!/usr/bin/env python3
"""Unified user-facing CLI for NaturePanelForge workflows."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

import reproduce_image


BASE_DIR = Path(__file__).resolve().parent


def resolve_path(path: Path | str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else BASE_DIR / path


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


def copy_full_figure_image(image_path: Path, target_path: Path) -> tuple[int, int]:
    if not image_path.exists():
        raise FileNotFoundError(f"input full figure image not found: {image_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as original:
        img = ImageOps.exif_transpose(original)
        width, height = img.size
        if img.mode in {"RGBA", "LA"}:
            img.save(target_path)
        else:
            img.convert("RGB").save(target_path)
    return width, height


def normalize_doi(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
    return urllib.parse.unquote(text).strip()


def normalize_pmcid(value: str) -> str:
    text = value.strip()
    match = re.search(r"(?:PMC)?(\d+)", text, flags=re.IGNORECASE)
    return f"PMC{match.group(1)}" if match else text


def paper_url_identifier(value: str) -> tuple[str, str] | None:
    text = value.strip()
    if not text:
        return None
    parsed = urllib.parse.urlparse(text)
    path = urllib.parse.unquote(parsed.path or "")
    pmc_match = re.search(r"/articles/(PMC\d+)/?", path, flags=re.IGNORECASE)
    if pmc_match:
        return "pmcid", normalize_pmcid(pmc_match.group(1))
    doi_match = re.search(r"/(10\.\d{4,9}/.+)$", path, flags=re.IGNORECASE)
    if doi_match:
        return "doi", normalize_doi(doi_match.group(1))
    if text.lower().startswith("doi:") or text.lower().startswith("10."):
        return "doi", normalize_doi(text)
    if re.fullmatch(r"(?:PMC)?\d+", text, flags=re.IGNORECASE):
        return "pmcid", normalize_pmcid(text)
    return None


def pmcid_query(pmcid: str) -> str:
    normalized = normalize_pmcid(pmcid)
    numeric = normalized[3:] if normalized.upper().startswith("PMC") else normalized
    return f'({normalized}[PMCID] OR {numeric}[UID])'


def doi_query(doi: str) -> str:
    return f'"{normalize_doi(doi)}"[DOI]'


def paper_identifier_query(args: argparse.Namespace) -> str:
    if getattr(args, "doi", ""):
        return doi_query(args.doi)
    if getattr(args, "pmcid", ""):
        return pmcid_query(args.pmcid)
    if getattr(args, "paper_url", ""):
        parsed = paper_url_identifier(args.paper_url)
        if parsed is None:
            raise ValueError(f"could not infer DOI or PMCID from --paper-url: {args.paper_url}")
        kind, value = parsed
        return doi_query(value) if kind == "doi" else pmcid_query(value)
    if getattr(args, "paper_query", ""):
        return args.paper_query
    return getattr(args, "search_term", "") or ""


def prepare_single_full_image_run(
    *,
    image_path: Path,
    out_root: Path,
    paper_id: str,
    figure_index: int,
    caption: str,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    run_dir = out_root
    if run_dir.exists() and overwrite:
        shutil.rmtree(run_dir)
    full_dir = run_dir / "FullFigures"
    target = full_dir / f"{paper_id}__fig{figure_index:02d}.png"
    width, height = copy_full_figure_image(image_path, target)
    row = {
        "paper_id": paper_id,
        "doi": "",
        "pmcid": "",
        "journal": "user_supplied",
        "publication_date": "",
        "figure_label": f"Figure {figure_index}",
        "figure_index": figure_index,
        "relative_path": str(target),
        "source_url": "",
        "caption": caption,
        "parsed_panel_labels": "",
        "width": width,
        "height": height,
    }
    csv_path = full_dir / "full_figures.csv"
    write_csv(csv_path, [row])
    write_json(full_dir / "full_figures.json", [row])
    write_json(
        run_dir / "user_full_figure_metadata.json",
        {
            "mode": "single-full-image",
            "input_image_path": str(image_path),
            "run_dir": str(run_dir),
            "full_figures_csv": str(csv_path),
            "paper_id": paper_id,
            "figure_index": figure_index,
            "caption": caption,
        },
    )
    return run_dir, csv_path


def add_codex_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=os.environ.get("CODEX_MODEL", "gpt-5.4"))
    parser.add_argument("--reasoning-effort", default=os.environ.get("CODEX_REASONING_EFFORT", "medium"))
    parser.add_argument("--max-codex-processes", type=int, default=int(os.environ.get("MAX_CODEX_PROCESSES", "8")))
    parser.add_argument("--process-user", default=os.environ.get("CODEX_PROCESS_USER", os.environ.get("USER", "unknown")))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("CODEX_TIMEOUT", "2400")))
    parser.add_argument("--poll-seconds", type=float, default=float(os.environ.get("CODEX_POLL_SECONDS", "10")))
    parser.add_argument("--review-rounds", type=int, default=int(os.environ.get("CODEX_REVIEW_ROUNDS", "4")))
    parser.add_argument("--codex-retries", type=int, default=int(os.environ.get("CODEX_RETRIES", "8")))
    parser.add_argument("--codex-retry-sleep", type=float, default=float(os.environ.get("CODEX_RETRY_SLEEP", "20")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-command", action="store_true")


def single_panel_image(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(BASE_DIR / "reproduce_image.py"),
        "--image",
        str(resolve_path(args.image)),
        "--out-root",
        str(resolve_path(args.out_root)),
        "--panel-id",
        args.panel_id or Path(args.image).stem,
        "--chart-type",
        args.chart_type,
        "--caption",
        args.caption,
        "--model",
        args.model,
        "--reasoning-effort",
        args.reasoning_effort,
        "--max-codex-processes",
        str(args.max_codex_processes),
        "--process-user",
        args.process_user,
        "--timeout",
        str(args.timeout),
        "--poll-seconds",
        str(args.poll_seconds),
        "--review-rounds",
        str(args.review_rounds),
        "--codex-retries",
        str(args.codex_retries),
        "--codex-retry-sleep",
        str(args.codex_retry_sleep),
    ]
    if args.source_pdf:
        cmd.extend(["--source-pdf", str(resolve_path(args.source_pdf))])
    if args.overwrite:
        cmd.append("--overwrite")
    if args.skip_existing:
        cmd.append("--skip-existing")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.print_command:
        cmd.append("--print-command")
    return run_command(cmd)


def single_full_image(args: argparse.Namespace) -> int:
    paper_id = reproduce_image.safe_name(args.paper_id or Path(args.image).stem)
    run_dir, full_csv = prepare_single_full_image_run(
        image_path=resolve_path(args.image),
        out_root=resolve_path(args.out_root),
        paper_id=paper_id,
        figure_index=args.figure_index,
        caption=args.caption,
        overwrite=args.overwrite,
    )
    cmd = [
        sys.executable,
        str(BASE_DIR / "agent_loop" / "codex_panel_split.py"),
        "--full-figures-csv",
        str(full_csv),
        "--panels-dir",
        str(run_dir / "Panels_codex_full"),
        "--reviews-dir",
        str(run_dir / "PanelReviews_codex_full"),
        "--specs-dir",
        str(run_dir / "PanelSplitSpecsCodex_full"),
        "--model",
        args.model,
        "--reasoning-effort",
        args.reasoning_effort,
        "--jobs",
        str(args.jobs),
        "--max-codex-processes",
        str(args.max_codex_processes),
        "--process-user",
        args.process_user,
        "--timeout",
        str(args.timeout),
        "--review-rounds",
        str(args.review_rounds),
        "--codex-retries",
        str(args.codex_retries),
        "--codex-retry-sleep",
        str(args.codex_retry_sleep),
        "--poll-seconds",
        str(args.poll_seconds),
    ]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.skip_existing:
        cmd.append("--skip-existing")
    if args.print_command:
        print(" ".join(str(item) for item in cmd), flush=True)
    return run_command(cmd)


def paper_command(args: argparse.Namespace, *, target_papers: int, batch_size: int) -> list[str]:
    query = paper_identifier_query(args)
    cmd = [
        sys.executable,
        str(BASE_DIR / "run_continuous_pipeline.py"),
        "--subject",
        args.subject,
        "--topic",
        args.topic,
        "--batch-size",
        str(batch_size),
        "--target-papers",
        str(target_papers),
        "--figures-per-paper",
        str(args.figures_per_paper),
        "--years",
        args.years,
        "--max-batches",
        str(args.max_batches),
        "--run-root",
        str(resolve_path(args.run_root)),
        "--state-root",
        str(resolve_path(args.state_root)),
        "--final-root",
        str(resolve_path(args.final_root)),
        "--full-figure-workers",
        str(args.full_figure_workers),
        "--full-figure-batch-size",
        str(args.full_figure_batch_size),
        "--full-figure-batch-sleep",
        str(args.full_figure_batch_sleep),
        "--panel-splitter",
        "codex",
        "--codex-split-model",
        args.codex_split_model,
        "--codex-split-reasoning-effort",
        args.codex_split_reasoning_effort,
        "--codex-split-jobs",
        str(args.codex_split_jobs),
        "--codex-split-timeout",
        str(args.codex_split_timeout),
        "--codex-split-review-rounds",
        str(args.codex_split_review_rounds),
        "--qwen-model",
        str(resolve_path(args.qwen_model)),
        "--qwen-backend",
        args.qwen_backend,
        "--qwen-batch-size",
        str(args.qwen_batch_size),
        "--codex-jobs",
        str(args.codex_jobs),
        "--max-codex-processes",
        str(args.max_codex_processes),
        "--codex-process-user",
        args.codex_process_user,
        "--codex-timeout",
        str(args.codex_timeout),
        "--codex-model",
        args.codex_model,
        "--quality-limit",
        str(args.quality_limit),
    ]
    if query:
        cmd.extend(["--search-term", query])
    if args.resume_run:
        cmd.extend(["--resume-run", str(resolve_path(args.resume_run))])
    if args.dry_run:
        cmd.append("--dry-run")
    if args.download_only:
        cmd.extend(["--skip-yolo", "--skip-qwen", "--skip-codex"])
    if args.skip_download:
        cmd.append("--skip-download")
    if args.skip_full_figures:
        cmd.append("--skip-full-figures")
    if args.skip_qwen:
        cmd.append("--skip-qwen")
    if args.skip_codex:
        cmd.append("--skip-codex")
    if args.prepare_qwen_only:
        cmd.append("--prepare-qwen-only")
    if args.stream_codex_events:
        cmd.append("--stream-codex-events")
    return cmd


def single_paper(args: argparse.Namespace) -> int:
    cmd = paper_command(args, target_papers=1, batch_size=1)
    if args.print_command:
        print(" ".join(str(item) for item in cmd), flush=True)
    return run_command(cmd)


def batched_paper(args: argparse.Namespace) -> int:
    cmd = paper_command(args, target_papers=args.target_papers, batch_size=args.batch_size)
    if args.print_command:
        print(" ".join(str(item) for item in cmd), flush=True)
    return run_command(cmd)


def run_command(cmd: list[str]) -> int:
    result = subprocess.run(cmd, cwd=BASE_DIR, check=False)
    return result.returncode


def add_paper_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--subject", default="biology")
    parser.add_argument("--topic", default="AI_biology")
    parser.add_argument("--years", default="2025,2026")
    parser.add_argument("--figures-per-paper", type=int, default=5)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--run-root", type=Path, default=BASE_DIR / "PipelineRuns")
    parser.add_argument("--state-root", type=Path, default=BASE_DIR / "PipelineState")
    parser.add_argument("--final-root", type=Path, default=BASE_DIR / "Final")
    parser.add_argument("--full-figure-workers", type=int, default=16)
    parser.add_argument("--full-figure-batch-size", type=int, default=16)
    parser.add_argument("--full-figure-batch-sleep", type=float, default=0.5)
    parser.add_argument("--search-term", default="")
    parser.add_argument("--paper-query", default="", help="Alias for --search-term, useful for one exact paper query.")
    parser.add_argument("--doi", default="", help="Exact DOI for single-paper mode, for example 10.1038/s41467-025-00000-0.")
    parser.add_argument("--pmcid", default="", help="Exact PMCID for single-paper mode, for example PMC1234567.")
    parser.add_argument("--paper-url", default="", help="DOI or PMC article URL for single-paper mode.")
    parser.add_argument("--resume-run", type=Path, default=None)
    parser.add_argument("--qwen-model", type=Path, default=Path(os.environ.get("QWEN_MODEL_PATH", "models/Qwen3.6-27B")))
    parser.add_argument("--qwen-backend", choices=["auto", "transformers", "openai"], default=os.environ.get("QWEN_BACKEND", "transformers"))
    parser.add_argument("--qwen-batch-size", type=int, default=int(os.environ.get("SCORE_BATCH_SIZE", "1")))
    parser.add_argument("--codex-split-model", default=os.environ.get("CODEX_MODEL", "gpt-5.4"))
    parser.add_argument("--codex-split-reasoning-effort", default=os.environ.get("CODEX_REASONING_EFFORT", "medium"))
    parser.add_argument("--codex-split-jobs", type=int, default=int(os.environ.get("CODEX_SPLIT_JOBS", os.environ.get("CODEX_JOBS", "8"))))
    parser.add_argument("--codex-split-timeout", type=int, default=int(os.environ.get("CODEX_SPLIT_TIMEOUT", os.environ.get("CODEX_TIMEOUT", "2400"))))
    parser.add_argument("--codex-split-review-rounds", type=int, default=int(os.environ.get("CODEX_REVIEW_ROUNDS", "4")))
    parser.add_argument("--codex-jobs", type=int, default=int(os.environ.get("CODEX_JOBS", "6")))
    parser.add_argument("--max-codex-processes", type=int, default=int(os.environ.get("MAX_CODEX_PROCESSES", "16")))
    parser.add_argument("--codex-process-user", default=os.environ.get("CODEX_PROCESS_USER", os.environ.get("USER", "unknown")))
    parser.add_argument("--codex-timeout", type=int, default=int(os.environ.get("CODEX_TIMEOUT", "2400")))
    parser.add_argument("--codex-model", default=os.environ.get("CODEX_MODEL", "gpt-5.4"))
    parser.add_argument("--quality-limit", type=int, default=int(os.environ.get("QUALITY_LIMIT", "0")))
    parser.add_argument("--download-only", action="store_true", help="Stop after paper/full-figure assets.")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-full-figures", action="store_true")
    parser.add_argument("--skip-qwen", action="store_true")
    parser.add_argument("--skip-codex", action="store_true")
    parser.add_argument("--prepare-qwen-only", action="store_true")
    parser.add_argument("--stream-codex-events", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-command", action="store_true")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NaturePanelForge four-mode command line interface.")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_panel = sub.add_parser("single-panel-image", help="Reproduce one already-cropped panel image into code.")
    p_panel.add_argument("--image", type=Path, required=True)
    p_panel.add_argument("--source-pdf", type=Path, default=None)
    p_panel.add_argument("--out-root", type=Path, default=BASE_DIR / "UserRuns" / "single_panel")
    p_panel.add_argument("--panel-id", default="")
    p_panel.add_argument("--caption", default="")
    p_panel.add_argument("--chart-type", default="user_supplied")
    p_panel.add_argument("--overwrite", action="store_true")
    p_panel.add_argument("--skip-existing", action="store_true")
    add_codex_common(p_panel)
    p_panel.set_defaults(func=single_panel_image)

    p_full = sub.add_parser("single-full-image", help="Split one full figure image into panels with Codex.")
    p_full.add_argument("--image", type=Path, required=True)
    p_full.add_argument("--out-root", type=Path, default=BASE_DIR / "UserRuns" / "single_full")
    p_full.add_argument("--paper-id", default="")
    p_full.add_argument("--figure-index", type=int, default=1)
    p_full.add_argument("--caption", default="")
    p_full.add_argument("--jobs", type=int, default=1)
    p_full.add_argument("--overwrite", action="store_true")
    p_full.add_argument("--skip-existing", action="store_true")
    add_codex_common(p_full)
    p_full.set_defaults(func=single_full_image)

    p_single_paper = sub.add_parser("single-paper", help="Retrieve one paper and its full figures.")
    add_paper_common(p_single_paper)
    p_single_paper.set_defaults(func=single_paper)

    p_batched = sub.add_parser("batched-paper", help="Retrieve a batch of papers and full figures.")
    add_paper_common(p_batched)
    p_batched.add_argument("--target-papers", type=int, default=20)
    p_batched.add_argument("--batch-size", type=int, default=20)
    p_batched.set_defaults(func=batched_paper)

    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
