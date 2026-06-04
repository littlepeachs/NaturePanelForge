#!/usr/bin/env python3
"""Continuous SciFigureHub pipeline orchestrator.

Pipeline:
paper discovery/download -> full figures -> YOLOv12 panels -> Qwen scoring ->
strict high-quality statistical-panel export -> Codex reproduction -> Final.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_QWEN_MODEL = Path(os.environ.get("QWEN_MODEL_PATH", str(BASE_DIR / "models" / "Qwen3.6-27B")))
DOI_PATTERN = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
NATURE_DOI_PATTERN = re.compile(r"(10\.1038/[A-Za-z0-9._-]+)")
NATURE_PAPER_ID_PATTERN = re.compile(r"(10-1038-[A-Za-z0-9-]+)")
NATURE_PANEL_ID_PATTERN = re.compile(r"(10-1038-[A-Za-z0-9-]+__fig[A-Za-z0-9_.-]+)")
SCAN_FILE_NAMES = {
    "download_manifest.json",
    "final_record.json",
    "manifest.csv",
    "manifest.json",
    "metadata.json",
    "panel_scores.csv",
    "panel_scores.json",
    "papers.csv",
    "papers.json",
    "state.json",
}
SKIP_SCAN_DIRS = {
    ".git",
    ".ipynb_checkpoints",
    "__pycache__",
    "logs",
}


def rel(path: Path) -> str:
    return str(path.relative_to(BASE_DIR))


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
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


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def safe_name(value: str) -> str:
    value = value.strip() or "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def normalize_doi(value: object) -> str:
    text = unquote(str(value or "")).strip()
    if not text:
        return ""
    text = text.replace("https://doi.org/", "").replace("http://doi.org/", "")
    text = text.replace("https://dx.doi.org/", "").replace("http://dx.doi.org/", "")
    match = NATURE_DOI_PATTERN.search(text) or DOI_PATTERN.search(text)
    if match:
        text = match.group(1)
    text = text.strip().rstrip(".,;)]}\"'")
    return text.lower() if text.startswith("10.") and "/" in text else ""


def doi_from_paper_id(value: object) -> str:
    text = str(value or "").strip()
    if "__" in text:
        text = text.split("__", 1)[0]
    match = NATURE_PAPER_ID_PATTERN.search(text)
    if not match:
        return ""
    paper_id = match.group(1)
    return f"10.1038/{paper_id[len('10-1038-'):]}"


def normalize_pmcid(value: object) -> str:
    match = re.search(r"\bPMC\d+\b", str(value or ""), flags=re.IGNORECASE)
    return match.group(0).upper() if match else ""


def normalize_panel_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = NATURE_PANEL_ID_PATTERN.search(text)
    if not match:
        return ""
    panel_id = match.group(1)
    for suffix in [".png", ".pdf", ".json", ".jpg", ".jpeg", ".tif", ".tiff"]:
        if panel_id.lower().endswith(suffix):
            panel_id = panel_id[: -len(suffix)]
            break
    return panel_id


def add_identifier(bucket: set[str], value: str) -> None:
    value = str(value or "").strip()
    if value:
        bucket.add(value)


def collect_identifiers_from_text(text: object, found: dict[str, set[str]]) -> None:
    value = str(text or "")
    if not value:
        return
    add_identifier(found["dois"], normalize_doi(value))
    add_identifier(found["pmcids"], normalize_pmcid(value))
    panel_id = normalize_panel_id(value)
    if panel_id:
        add_identifier(found["panel_ids"], panel_id)
        add_identifier(found["dois"], doi_from_paper_id(panel_id))
    paper_doi = doi_from_paper_id(value)
    if paper_doi:
        add_identifier(found["dois"], paper_doi)


def collect_identifiers_from_record(record: dict, found: dict[str, set[str]]) -> None:
    for key in [
        "doi",
        "doi_url",
        "paper_doi",
        "article_doi",
        "pmcid",
        "pmc_id",
        "paper_id",
        "article_id",
        "panel_id",
        "relative_path",
        "target_path",
        "export_dir",
        "final_dir",
        "final_target_path",
        "source_figure_url",
    ]:
        if key in record:
            collect_identifiers_from_text(record.get(key), found)


def collect_identifiers_from_json_payload(payload: Any, found: dict[str, set[str]]) -> None:
    if isinstance(payload, dict):
        collect_identifiers_from_record(payload, found)
        for value in payload.values():
            if isinstance(value, (dict, list)):
                collect_identifiers_from_json_payload(value, found)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, (dict, list)):
                collect_identifiers_from_json_payload(item, found)
            else:
                collect_identifiers_from_text(item, found)


def collect_identifiers_from_file(path: Path, found: dict[str, set[str]]) -> None:
    try:
        if path.suffix.lower() == ".json":
            collect_identifiers_from_json_payload(json.loads(path.read_text(encoding="utf-8")), found)
        elif path.suffix.lower() == ".csv":
            for row in read_csv(path):
                collect_identifiers_from_record(row, found)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        print(f"skip dedupe scan file {path}: {exc}")


def default_dedupe_roots(args: argparse.Namespace) -> list[Path]:
    return [
        resolve_under_base(args.final_root),
        resolve_under_base(args.run_root),
        resolve_under_base(args.state_root),
        BASE_DIR / "Papers",
        BASE_DIR / "Figures",
        BASE_DIR / "FullFigures",
        BASE_DIR / "FigurePDFs",
        BASE_DIR / "Panels",
        BASE_DIR / "PanelScores",
        BASE_DIR / "PanelScoresStrict",
        BASE_DIR / "HighQualityPanelsStrict",
    ]


def scan_existing_outputs(args: argparse.Namespace) -> tuple[dict[str, set[str]], list[Path]]:
    found = {"dois": set(), "pmcids": set(), "panel_ids": set()}
    roots = default_dedupe_roots(args) + [resolve_under_base(path) for path in (args.dedupe_root or [])]
    existing_roots: list[Path] = []
    seen_roots: set[Path] = set()
    for root in roots:
        root = root.resolve()
        if root in seen_roots or not root.exists():
            continue
        seen_roots.add(root)
        existing_roots.append(root)
        if root.is_file():
            collect_identifiers_from_text(root.name, found)
            if root.name in SCAN_FILE_NAMES:
                collect_identifiers_from_file(root, found)
            continue
        for current_dir, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in SKIP_SCAN_DIRS]
            for dirname in dirnames:
                collect_identifiers_from_text(dirname, found)
            for filename in filenames:
                if filename in SCAN_FILE_NAMES:
                    file_path = Path(current_dir) / filename
                    collect_identifiers_from_text(file_path.name, found)
                    collect_identifiers_from_file(file_path, found)
    return found, existing_roots


def merge_scanned_identifiers(state: dict, found: dict[str, set[str]]) -> dict[str, int]:
    mapping = {
        "processed_dois": "dois",
        "processed_pmcids": "pmcids",
        "processed_panel_ids": "panel_ids",
    }
    added: dict[str, int] = {}
    for state_key, found_key in mapping.items():
        before = set(str(item).strip() for item in state.get(state_key, []) if str(item).strip())
        merged = before | found[found_key]
        state[state_key] = sorted(merged)
        added[state_key] = len(merged) - len(before)
    return added


def augment_state_from_existing_outputs(args: argparse.Namespace, state: dict) -> dict[str, Any]:
    if args.no_scan_existing:
        return {
            "enabled": False,
            "roots": [],
            "found": {"dois": 0, "pmcids": 0, "panel_ids": 0},
            "added": {"processed_dois": 0, "processed_pmcids": 0, "processed_panel_ids": 0},
        }
    found, roots = scan_existing_outputs(args)
    added = merge_scanned_identifiers(state, found)
    summary = {
        "enabled": True,
        "roots": [rel(root) if root.is_relative_to(BASE_DIR) else str(root) for root in roots],
        "found": {key: len(value) for key, value in found.items()},
        "added": added,
    }
    state["last_dedupe_scan"] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        **summary,
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the continuous SciFigureHub pipeline.")
    parser.add_argument("--subject", default="biology", help="Final subject directory.")
    parser.add_argument("--topic", default="AI_biology", help="Final topic directory.")
    parser.add_argument("--batch-size", type=int, default=100, help="Papers per run batch.")
    parser.add_argument("--target-papers", type=int, default=100, help="Total new papers to attempt this invocation.")
    parser.add_argument("--figures-per-paper", type=int, default=5)
    parser.add_argument("--full-figure-workers", type=int, default=16)
    parser.add_argument("--full-figure-batch-size", type=int, default=16)
    parser.add_argument("--full-figure-batch-sleep", type=float, default=1.0)
    parser.add_argument("--years", default="2025,2026", help="Comma-separated PMC publication years.")
    parser.add_argument("--search-term", default="", help="Override the PMC query.")
    parser.add_argument("--run-root", type=Path, default=BASE_DIR / "PipelineRuns")
    parser.add_argument("--state-root", type=Path, default=BASE_DIR / "PipelineState")
    parser.add_argument("--final-root", type=Path, default=BASE_DIR / "Final")
    parser.add_argument(
        "--dedupe-root",
        type=Path,
        action="append",
        default=[],
        help="Additional file or directory to scan for already processed DOI/PMCID/panel IDs.",
    )
    parser.add_argument(
        "--no-scan-existing",
        action="store_true",
        help="Disable startup scan of existing outputs. State-file exclusions still apply.",
    )
    parser.add_argument("--resume-run", type=Path, help="Resume an existing run directory.")
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument(
        "--yolo-weights",
        default=os.environ.get("YOLOV12_PANEL_MODEL", ""),
        help="Optional YOLOv12 weights. If omitted, yolov12_panel_split.py auto-discovers the cached figpanel-yolov12 v4.pt.",
    )
    parser.add_argument("--yolo-imgsz", type=int, default=1280)
    parser.add_argument("--yolo-conf", type=float, default=0.20)
    parser.add_argument("--allow-whole-figure-fallback", action="store_true")
    parser.add_argument("--panel-splitter", choices=["yolo", "codex"], default="yolo")
    parser.add_argument("--codex-split-model", default=os.environ.get("CODEX_MODEL", "gpt-5.4"))
    parser.add_argument("--codex-split-reasoning-effort", default="medium")
    parser.add_argument("--codex-split-jobs", type=int, default=8)
    parser.add_argument("--codex-split-timeout", type=int, default=900)
    parser.add_argument("--codex-split-limit", type=int, default=0)
    parser.add_argument("--codex-split-review-rounds", type=int, default=4)
    parser.add_argument("--qwen-model", type=Path, default=DEFAULT_QWEN_MODEL)
    parser.add_argument("--qwen-backend", choices=["auto", "transformers", "openai"], default="transformers")
    parser.add_argument("--qwen-api-base", default="")
    parser.add_argument("--qwen-batch-size", type=int, default=1)
    parser.add_argument("--qwen-device-map", default="auto")
    parser.add_argument("--prepare-qwen-only", action="store_true", help="Prepare Qwen prompts but skip scoring.")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-full-figures", action="store_true")
    parser.add_argument("--skip-yolo", action="store_true")
    parser.add_argument("--skip-qwen", action="store_true")
    parser.add_argument("--skip-codex", action="store_true")
    parser.add_argument("--codex-jobs", type=int, default=6)
    parser.add_argument("--max-codex-processes", type=int, default=16)
    parser.add_argument("--codex-process-user", default=os.environ.get("USER", "unknown"))
    parser.add_argument("--codex-timeout", type=int, default=2400)
    parser.add_argument("--codex-model", default="")
    parser.add_argument("--stream-codex-events", action="store_true")
    parser.add_argument("--quality-limit", type=int, default=0, help="Limit selected high-quality panels for Codex.")
    parser.add_argument("--overwrite-run-products", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def resolve_under_base(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (BASE_DIR / path).resolve()


def state_path(args: argparse.Namespace) -> Path:
    return resolve_under_base(args.state_root) / "state.json"


def default_state(args: argparse.Namespace) -> dict:
    return {
        "scope": "global",
        "processed_dois": [],
        "processed_pmcids": [],
        "processed_panel_ids": [],
        "runs": [],
    }


def load_state(args: argparse.Namespace) -> dict:
    state = read_json(state_path(args), default_state(args))
    for key in ["processed_dois", "processed_pmcids", "processed_panel_ids", "runs"]:
        state.setdefault(key, [])
    return state


def save_state(args: argparse.Namespace, state: dict) -> None:
    state["processed_dois"] = sorted(set(state.get("processed_dois", [])))
    state["processed_pmcids"] = sorted(set(state.get("processed_pmcids", [])))
    state["processed_panel_ids"] = sorted(set(state.get("processed_panel_ids", [])))
    write_json(state_path(args), state)


def run_dir_for(args: argparse.Namespace, batch_index: int) -> Path:
    if args.resume_run:
        return resolve_under_base(args.resume_run)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return resolve_under_base(args.run_root) / args.subject / args.topic / f"run_{stamp}_batch{batch_index:03d}"


def paths_for(run_dir: Path) -> dict[str, Path]:
    return {
        "papers": run_dir / "Papers",
        "figures": run_dir / "Figures",
        "full_figures": run_dir / "FullFigures",
        "figure_pdfs": run_dir / "FigurePDFs",
        "panels": run_dir / "Panels",
        "panel_full_finsh": run_dir / "Panel_full_finsh",
        "panel_reviews": run_dir / "PanelReviews",
        "panel_split_specs": run_dir / "PanelSplitSpecsCodex",
        "scores": run_dir / "PanelScores",
        "pending": run_dir / "HighQualityPending",
        "logs": run_dir / "logs",
        "cursor": run_dir / "download_cursor.json",
        "manifest": run_dir / "download_manifest.json",
        "exclude_dois": run_dir / "exclude_dois.txt",
        "exclude_pmcids": run_dir / "exclude_pmcids.txt",
        "run_state": run_dir / "state.json",
    }


def ensure_run_dirs(path_map: dict[str, Path]) -> None:
    for key in [
        "papers",
        "figures",
        "full_figures",
        "figure_pdfs",
        "panels",
        "panel_reviews",
        "panel_split_specs",
        "panel_full_finsh",
        "scores",
        "pending",
        "logs",
    ]:
        path_map[key].mkdir(parents=True, exist_ok=True)


def command_text(cmd: list[str]) -> str:
    return " ".join(str(item) for item in cmd)


def run_command(
    cmd: list[str],
    *,
    log_path: Path,
    env: dict[str, str] | None = None,
    dry_run: bool = False,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    header = f"$ {command_text(cmd)}\n"
    if dry_run:
        print(header.strip())
        return
    with log_path.open("w", encoding="utf-8") as log:
        log.write(header)
        log.flush()
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        process = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            env=merged_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(f"command failed with exit code {process.returncode}: {command_text(cmd)}; log={log_path}")


def ai_biology_query() -> str:
    result = subprocess.run(
        [sys.executable, "agent_loop/keyword_query_builder.py", "query"],
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def write_identifier_files(path_map: dict[str, Path], state: dict, dry_run: bool) -> None:
    doi_count = len(set(state.get("processed_dois", [])))
    pmcid_count = len(set(state.get("processed_pmcids", [])))
    if dry_run:
        print(f"Would write DOI exclusions ({doi_count}): {path_map['exclude_dois']}")
        print(f"Would write PMCID exclusions ({pmcid_count}): {path_map['exclude_pmcids']}")
        return
    path_map["exclude_dois"].write_text("\n".join(sorted(set(state.get("processed_dois", [])))) + "\n", encoding="utf-8")
    path_map["exclude_pmcids"].write_text("\n".join(sorted(set(state.get("processed_pmcids", [])))) + "\n", encoding="utf-8")


def download_papers(args: argparse.Namespace, path_map: dict[str, Path], state: dict, target_papers: int) -> None:
    if args.skip_download:
        return
    query = args.search_term or ai_biology_query()
    env = {
        "PAPERS_DIR": rel(path_map["papers"]),
        "FIGURES_DIR": rel(path_map["figures"]),
        "DOWNLOAD_MANIFEST": rel(path_map["manifest"]),
        "DOWNLOAD_CURSOR_FILE": rel(path_map["cursor"]),
        "TARGET_PAPERS": str(target_papers),
        "FIGURES_PER_PAPER": str(args.figures_per_paper),
        "PMC_SEARCH_TERM": query,
        "PMC_SEARCH_SORT": "pub date",
        "PMC_YEARS": args.years,
        "EXCLUDE_DOIS_FILE": rel(path_map["exclude_dois"]),
        "EXCLUDE_PMCIDS_FILE": rel(path_map["exclude_pmcids"]),
        "ALLOW_PARTIAL_DOWNLOAD": "1",
    }
    run_command(
        [sys.executable, "download_nature_oa_figures.py"],
        log_path=path_map["logs"] / "01_download.log",
        env=env,
        dry_run=args.dry_run,
    )


def build_full_figures(args: argparse.Namespace, path_map: dict[str, Path]) -> None:
    if args.skip_full_figures:
        return
    env = {
        "HF_ENDPOINT": os.environ.get("HF_ENDPOINT", "https://hf-mirror.com"),
        "HF_HOME": os.environ.get("HF_HOME", str(BASE_DIR / ".cache" / "huggingface")),
        "YOLO_CONFIG_DIR": os.environ.get("YOLO_CONFIG_DIR", str(BASE_DIR / ".cache" / "ultralytics")),
        "PYTHONPATH": f"{BASE_DIR / '.deps' / 'figpanel_min'}{os.environ.get('PYTHONPATH', '') and ':' + os.environ['PYTHONPATH']}",
        "PAPERS_JSON": rel(path_map["papers"] / "papers.json"),
        "FULL_FIGURES_DIR": rel(path_map["full_figures"]),
        "FIGURE_PDFS_DIR": rel(path_map["figure_pdfs"]),
        "PANELS_DIR": rel(path_map["panels"]),
        "PANEL_REVIEWS_DIR": rel(path_map["panel_reviews"]),
        "BUILD_FIGURE_ASSETS_SKIP_PANEL_SPLIT": "1" if args.panel_splitter == "codex" else "0",
        "BUILD_FIGURE_ASSETS_WORKERS": str(args.full_figure_workers),
        "BUILD_FIGURE_ASSETS_BATCH_SIZE": str(args.full_figure_batch_size),
        "BUILD_FIGURE_ASSETS_BATCH_SLEEP": str(args.full_figure_batch_sleep),
    }
    run_command(
        [sys.executable, "build_figure_assets.py"],
        log_path=path_map["logs"] / "02_full_figures.log",
        env=env,
        dry_run=args.dry_run,
    )


def yolo_split(args: argparse.Namespace, path_map: dict[str, Path]) -> None:
    if args.skip_yolo:
        return
    cmd = [
        sys.executable,
        "agent_loop/yolov12_panel_split.py",
        "--full-figures-csv",
        rel(path_map["full_figures"] / "full_figures.csv"),
        "--panels-dir",
        rel(path_map["panels"]),
        "--reviews-dir",
        rel(path_map["panel_reviews"]),
        "--imgsz",
        str(args.yolo_imgsz),
        "--conf",
        str(args.yolo_conf),
        "--overwrite",
    ]
    if args.yolo_weights:
        cmd.extend(["--weights", args.yolo_weights])
    if args.allow_whole_figure_fallback:
        cmd.append("--allow-whole-figure-fallback")
    run_command(cmd, log_path=path_map["logs"] / "03_yolo_split.log", dry_run=args.dry_run)


def codex_split(args: argparse.Namespace, path_map: dict[str, Path]) -> None:
    if args.skip_yolo:
        return
    cmd = [
        sys.executable,
        "agent_loop/codex_panel_split.py",
        "--full-figures-csv",
        rel(path_map["full_figures"] / "full_figures.csv"),
        "--panels-dir",
        rel(path_map["panels"]),
        "--reviews-dir",
        rel(path_map["panel_reviews"]),
        "--specs-dir",
        rel(path_map["panel_split_specs"]),
        "--finished-dir",
        rel(path_map["panel_full_finsh"]),
        "--model",
        args.codex_split_model,
        "--reasoning-effort",
        args.codex_split_reasoning_effort,
        "--jobs",
        str(args.codex_split_jobs),
        "--max-codex-processes",
        str(args.max_codex_processes),
        "--process-user",
        args.codex_process_user,
        "--timeout",
        str(args.codex_split_timeout),
        "--review-rounds",
        str(args.codex_split_review_rounds),
        "--overwrite",
    ]
    if args.codex_split_limit:
        cmd.extend(["--limit", str(args.codex_split_limit)])
    if args.stream_codex_events:
        cmd.append("--stream-events")
    run_command(cmd, log_path=path_map["logs"] / "03_codex_panel_split.log", dry_run=args.dry_run)


def split_panels(args: argparse.Namespace, path_map: dict[str, Path]) -> None:
    if args.panel_splitter == "codex":
        codex_split(args, path_map)
    else:
        yolo_split(args, path_map)


def qwen_score(args: argparse.Namespace, path_map: dict[str, Path]) -> None:
    if args.skip_qwen:
        return
    common = [
        "--panels-csv",
        rel(path_map["panels"] / "panels.csv"),
        "--scores-dir",
        rel(path_map["scores"]),
        "--model-path",
        str(args.qwen_model),
        "--backend",
        args.qwen_backend,
        "--batch-size",
        str(args.qwen_batch_size),
        "--device-map",
        args.qwen_device_map,
        "--overwrite" if args.overwrite_run_products else "",
    ]
    common = [item for item in common if item]
    if args.qwen_api_base:
        common.extend(["--api-base", args.qwen_api_base])
    run_command(
        [sys.executable, "agent_loop/qwen_panel_scoring.py", "prepare", *common],
        log_path=path_map["logs"] / "04_qwen_prepare.log",
        dry_run=args.dry_run,
    )
    if args.prepare_qwen_only:
        return
    run_command(
        [sys.executable, "agent_loop/qwen_panel_scoring.py", "score", *common],
        log_path=path_map["logs"] / "05_qwen_score.log",
        dry_run=args.dry_run,
    )


def strict_reject_reasons(row: dict) -> list[str]:
    reasons: list[str] = []
    if row.get("category") != "data_statistical":
        reasons.append("category_not_data_statistical")
    if not truthy(row.get("is_complete_panel")):
        reasons.append("not_complete_panel")
    if truthy(row.get("has_foreign_overlap")):
        reasons.append("has_foreign_overlap")
    if row.get("data_purity") != "pure_data_statistical":
        reasons.append("data_purity_not_pure")
    if number(row.get("data_purity_score")) != 10.0:
        reasons.append("data_purity_score_not_10")
    if number(row.get("code_reproducibility_score")) < 9.0:
        reasons.append("code_reproducibility_lt_9")
    if number(row.get("aesthetic_score")) < 8.0:
        reasons.append("aesthetic_lt_8")
    return reasons


def copy_if_exists(src: Path, dst: Path) -> str:
    if not src.exists() or not src.is_file():
        return ""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return rel(dst)


def source_path(value: str) -> Path:
    if not value or not str(value).strip():
        return Path("/__missing_sci_figure_hub_file__")
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


def existing_final_panel_dir(args: argparse.Namespace, panel_id: str) -> Path | None:
    if not panel_id:
        return None
    final_topic_dir = resolve_under_base(args.final_root) / args.subject / args.topic
    if not final_topic_dir.exists():
        return None
    for candidate in final_topic_dir.glob(f"*/{panel_id}"):
        if candidate.is_dir():
            return candidate
    return None


def export_high_quality(args: argparse.Namespace, path_map: dict[str, Path], state: dict) -> list[dict]:
    scores_csv = path_map["scores"] / "panel_scores.csv"
    if args.dry_run:
        print(f"Would select strict high-quality statistical panels from {scores_csv}")
        return []
    rows = read_csv(scores_csv)
    processed_panels = set(state.get("processed_panel_ids", []))
    selected: list[dict] = []
    rejected: list[dict] = []
    for row in rows:
        panel_id = safe_name(row.get("panel_id") or "")
        reasons = strict_reject_reasons(row)
        if panel_id in processed_panels:
            reasons.append("already_processed_panel")
        if existing_final_panel_dir(args, panel_id):
            reasons.append("already_in_final")
        if reasons:
            rejected.append({**row, "reject_reasons": ";".join(reasons)})
            continue
        subtype = safe_name(row.get("data_subtype") or "other_data_display")
        panel_dir = path_map["pending"] / panel_id
        panel_dir.mkdir(parents=True, exist_ok=True)
        target_path = source_path(row.get("target_path") or row.get("relative_path", ""))
        pdf_path = source_path(row.get("panel_pdf_path", ""))
        score_path = source_path(row.get("score_path", ""))
        prompt_path = source_path(row.get("prompt_path", ""))
        raw_response_path = score_path.parent / "raw_response.txt" if score_path.exists() else source_path("")
        exported = {
            **row,
            "selection_category": "strict_high_quality_statistical",
            "selection_reason": "data_statistical; complete; no_overlap; purity_score=10; code>=9; aesthetic>=8",
            "final_subject": args.subject,
            "final_topic": args.topic,
            "export_dir": rel(panel_dir),
            "export_image_path": copy_if_exists(target_path, panel_dir / "target.png"),
            "export_pdf_path": copy_if_exists(pdf_path, panel_dir / "target.pdf"),
            "export_score_path": copy_if_exists(score_path, panel_dir / "qwen_score.json"),
            "export_prompt_path": copy_if_exists(prompt_path, panel_dir / "qwen_prompt.md"),
            "export_raw_response_path": copy_if_exists(raw_response_path, panel_dir / "raw_response.txt"),
        }
        write_json(panel_dir / "metadata.json", exported)
        selected.append(exported)
        if args.quality_limit and len(selected) >= args.quality_limit:
            break
    write_csv(path_map["pending"] / "manifest.csv", selected)
    write_json(path_map["pending"] / "manifest.json", selected)
    write_csv(path_map["pending"] / "rejected.csv", rejected)
    write_json(
        path_map["pending"] / "summary.json",
        {
            "input_rows": len(rows),
            "selected": len(selected),
            "rejected": len(rejected),
            "selection_filter": {
                "category": "data_statistical",
                "is_complete_panel": True,
                "has_foreign_overlap": False,
                "data_purity_score": 10,
                "code_reproducibility_score_min": 9,
                "aesthetic_score_min": 8,
            },
        },
    )
    (path_map["pending"] / "panel_dirs.txt").write_text(
        "\n".join(str(path_map["pending"] / row["panel_id"]) for row in selected) + ("\n" if selected else ""),
        encoding="utf-8",
    )
    return selected


def run_codex(args: argparse.Namespace, path_map: dict[str, Path], selected: list[dict]) -> None:
    if args.skip_codex or not selected:
        return
    cmd = [
        sys.executable,
        "examples/prompt_codex_reproduce_fig02_g.py",
        "--panel-list",
        rel(path_map["pending"] / "panel_dirs.txt"),
        "--jobs",
        str(args.codex_jobs),
        "--max-codex-processes",
        str(args.max_codex_processes),
        "--process-user",
        args.codex_process_user,
        "--timeout",
        str(args.codex_timeout),
        "--skip-existing",
    ]
    if args.codex_model:
        cmd.extend(["--model", args.codex_model])
    if args.stream_codex_events:
        cmd.append("--stream-events")
    run_command(cmd, log_path=path_map["logs"] / "06_codex.log", dry_run=args.dry_run)


def archive_to_final(args: argparse.Namespace, path_map: dict[str, Path], selected: list[dict]) -> list[dict]:
    if args.dry_run:
        print(f"Would archive selected panels to {resolve_under_base(args.final_root) / args.subject / args.topic}")
        return []
    archived: list[dict] = []
    final_topic_dir = resolve_under_base(args.final_root) / args.subject / args.topic
    for row in selected:
        panel_id = safe_name(row.get("panel_id") or "")
        subtype = safe_name(row.get("data_subtype") or "other_data_display")
        src_dir = path_map["pending"] / panel_id
        required = [
            src_dir / "target.png",
            src_dir / "metadata.json",
            src_dir / "qwen_score.json",
        ]
        if not args.skip_codex:
            required.extend(
                [
                    src_dir / "reproduce_panel.py",
                    src_dir / "reproduce_panel.png",
                    src_dir / "reproduce_panel.pdf",
                    src_dir / "reproduce_panel_run_log.md",
                ]
            )
        if any(not path.exists() for path in required):
            continue
        dst_dir = final_topic_dir / subtype / panel_id
        if dst_dir.exists():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        for item in src_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, dst_dir / item.name)
        archived_row = {
            **row,
            "final_dir": rel(dst_dir),
            "final_target_path": rel(dst_dir / "target.png"),
            "final_metadata_path": rel(dst_dir / "metadata.json"),
            "final_reproduce_script": rel(dst_dir / "reproduce_panel.py") if (dst_dir / "reproduce_panel.py").exists() else "",
            "final_reproduce_png": rel(dst_dir / "reproduce_panel.png") if (dst_dir / "reproduce_panel.png").exists() else "",
            "final_reproduce_pdf": rel(dst_dir / "reproduce_panel.pdf") if (dst_dir / "reproduce_panel.pdf").exists() else "",
        }
        write_json(dst_dir / "final_record.json", archived_row)
        archived.append(archived_row)
    existing = read_csv(final_topic_dir / "manifest.csv")
    by_panel = {row.get("panel_id"): row for row in existing if row.get("panel_id")}
    for row in archived:
        by_panel[row["panel_id"]] = row
    manifest = list(by_panel.values())
    write_csv(final_topic_dir / "manifest.csv", manifest)
    write_json(final_topic_dir / "manifest.json", manifest)
    return archived


def update_state_from_papers(
    args: argparse.Namespace,
    run_dir: Path,
    path_map: dict[str, Path],
    state: dict,
    *,
    stage: str,
) -> dict[str, int]:
    if args.dry_run:
        return {"papers": 0, "added_dois": 0, "added_pmcids": 0}
    papers_path = path_map["papers"] / "papers.json"
    papers = read_json(papers_path, [])
    if not isinstance(papers, list):
        papers = []
    found = {"dois": set(), "pmcids": set(), "panel_ids": set()}
    for paper in papers:
        if isinstance(paper, dict):
            collect_identifiers_from_record(paper, found)
    before_dois = set(str(item).strip() for item in state.get("processed_dois", []) if str(item).strip())
    before_pmcids = set(str(item).strip() for item in state.get("processed_pmcids", []) if str(item).strip())
    state.setdefault("processed_dois", [])
    state.setdefault("processed_pmcids", [])
    state["processed_dois"] = sorted(before_dois | found["dois"])
    state["processed_pmcids"] = sorted(before_pmcids | found["pmcids"])
    update_record = {
        "run_dir": rel(run_dir),
        "stage": stage,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "papers_json": rel(papers_path),
        "downloaded_papers": len(papers),
        "found_dois": len(found["dois"]),
        "found_pmcids": len(found["pmcids"]),
        "added_dois": len(set(state["processed_dois"]) - before_dois),
        "added_pmcids": len(set(state["processed_pmcids"]) - before_pmcids),
    }
    state["last_paper_state_update"] = update_record
    write_json(run_dir / "paper_download_state_update.json", update_record)
    save_state(args, state)
    return {
        "papers": len(papers),
        "added_dois": update_record["added_dois"],
        "added_pmcids": update_record["added_pmcids"],
    }


def update_run_and_global_state(
    args: argparse.Namespace,
    run_dir: Path,
    path_map: dict[str, Path],
    state: dict,
    selected: list[dict],
    archived: list[dict],
) -> None:
    if args.dry_run:
        return
    papers = read_json(path_map["papers"] / "papers.json", [])
    run_record = {
        "run_dir": rel(run_dir),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "downloaded_papers": len(papers),
        "selected_panels": len(selected),
        "archived_panels": len(archived),
    }
    state.setdefault("processed_dois", [])
    state.setdefault("processed_pmcids", [])
    state.setdefault("processed_panel_ids", [])
    state.setdefault("runs", [])
    found = {"dois": set(), "pmcids": set(), "panel_ids": set()}
    for paper in papers:
        if isinstance(paper, dict):
            collect_identifiers_from_record(paper, found)
    state["processed_dois"].extend(found["dois"])
    state["processed_pmcids"].extend(found["pmcids"])
    state["processed_panel_ids"].extend(row.get("panel_id", "") for row in archived if row.get("panel_id"))
    state["runs"].append(run_record)
    write_json(path_map["run_state"], {**run_record, "selected": selected, "archived": archived})
    save_state(args, state)


def run_batch(args: argparse.Namespace, state: dict, batch_index: int, target_papers: int) -> None:
    run_dir = run_dir_for(args, batch_index)
    path_map = paths_for(run_dir)
    print(f"Run directory: {run_dir}")
    if not args.dry_run:
        ensure_run_dirs(path_map)
    write_identifier_files(path_map, state, args.dry_run)
    download_papers(args, path_map, state, target_papers)
    update_state_from_papers(args, run_dir, path_map, state, stage="after_paper_download")
    build_full_figures(args, path_map)
    split_panels(args, path_map)
    qwen_score(args, path_map)
    selected = export_high_quality(args, path_map, state)
    run_codex(args, path_map, selected)
    archived = archive_to_final(args, path_map, selected)
    update_run_and_global_state(args, run_dir, path_map, state, selected, archived)


def validate_args(args: argparse.Namespace) -> None:
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    if args.target_papers < 1:
        raise SystemExit("--target-papers must be >= 1")
    if args.full_figure_workers < 1:
        raise SystemExit("--full-figure-workers must be >= 1")
    if args.full_figure_batch_size < 1:
        raise SystemExit("--full-figure-batch-size must be >= 1")
    if args.full_figure_batch_sleep < 0:
        raise SystemExit("--full-figure-batch-sleep must be >= 0")
    if args.max_batches < 1:
        raise SystemExit("--max-batches must be >= 1")
    if args.max_codex_processes < 1:
        raise SystemExit("--max-codex-processes must be >= 1")
    if args.codex_split_jobs < 1:
        raise SystemExit("--codex-split-jobs must be >= 1")
    if args.codex_split_review_rounds < 0:
        raise SystemExit("--codex-split-review-rounds must be >= 0")
    if args.resume_run and args.max_batches != 1:
        raise SystemExit("--resume-run can only be used with --max-batches 1")


def main() -> int:
    args = parse_args()
    validate_args(args)
    state = load_state(args)
    dedupe_summary = augment_state_from_existing_outputs(args, state)
    if dedupe_summary["enabled"]:
        add_verb = "would add" if args.dry_run else "added"
        print(
            "Dedupe scan: "
            f"{dedupe_summary['found']['dois']} DOI, "
            f"{dedupe_summary['found']['pmcids']} PMCID, "
            f"{dedupe_summary['found']['panel_ids']} panel IDs found; "
            f"{add_verb} {dedupe_summary['added']['processed_dois']} DOI, "
            f"{dedupe_summary['added']['processed_pmcids']} PMCID, "
            f"{dedupe_summary['added']['processed_panel_ids']} panel IDs to state."
        )
        if not args.dry_run:
            save_state(args, state)
    else:
        print("Dedupe scan: disabled; using state-file exclusions only.")
    remaining = args.target_papers
    batches = min(args.max_batches, max(1, (args.target_papers + args.batch_size - 1) // args.batch_size))
    start = time.monotonic()
    for batch_index in range(1, batches + 1):
        target = min(args.batch_size, remaining)
        run_batch(args, state, batch_index, target)
        remaining -= target
        if remaining <= 0:
            break
    print(f"Pipeline invocation finished in {time.monotonic() - start:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
