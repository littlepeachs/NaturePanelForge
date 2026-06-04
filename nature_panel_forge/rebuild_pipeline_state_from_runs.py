#!/usr/bin/env python3
"""Rebuild global paper-level dedupe state from all run*/Papers/papers.csv/json files."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from nature_panel_forge.run_continuous_pipeline import (
    BASE_DIR,
    normalize_doi,
    normalize_pmcid,
    read_json,
    resolve_under_base,
    write_json,
)


def read_papers_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_papers_json(path: Path) -> list[dict[str, Any]]:
    data = read_json(path, [])
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def load_papers(run_dir: Path) -> tuple[list[dict[str, Any]], str]:
    csv_path = run_dir / "Papers" / "papers.csv"
    json_path = run_dir / "Papers" / "papers.json"
    if csv_path.exists():
        return read_papers_csv(csv_path), str(csv_path)
    if json_path.exists():
        return read_papers_json(json_path), str(json_path)
    papers_dir = run_dir / "Papers"
    if papers_dir.exists():
        records: list[dict[str, Any]] = []
        for paper_json in sorted(path for path in papers_dir.glob("*.json") if path.name != "papers.json"):
            record = read_json(paper_json, {})
            if isinstance(record, dict):
                records.append(record)
        if records:
            return records, str(papers_dir / "*.json")
    return [], ""


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild PipelineState from run*/Papers/papers.csv/json.")
    parser.add_argument("--subject", default="", help="Optional legacy filter. Empty means all subjects.")
    parser.add_argument("--topic", default="", help="Optional legacy filter. Empty means all topics.")
    parser.add_argument("--run-root", type=Path, default=BASE_DIR / "PipelineRuns")
    parser.add_argument("--state-root", type=Path, default=BASE_DIR / "PipelineState")
    parser.add_argument(
        "--drop-panel-ids",
        action="store_true",
        help="Also clear processed_panel_ids instead of preserving existing panel-level state.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def state_path(args: argparse.Namespace) -> Path:
    return resolve_under_base(args.state_root) / "state.json"


def default_global_state() -> dict[str, Any]:
    return {
        "scope": "global",
        "processed_dois": [],
        "processed_pmcids": [],
        "processed_panel_ids": [],
        "runs": [],
    }


def run_search_roots(args: argparse.Namespace) -> list[Path]:
    run_root = resolve_under_base(args.run_root)
    if args.subject and args.topic:
        return [run_root / args.subject / args.topic]
    if args.subject:
        subject_root = run_root / args.subject
        return sorted(path for path in subject_root.glob("*") if path.is_dir()) if subject_root.exists() else []
    return sorted(path for path in run_root.glob("*/*") if path.is_dir()) if run_root.exists() else []


def collect_runs(args: argparse.Namespace) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    run_records: list[dict[str, Any]] = []
    dois: set[str] = set()
    pmcids: set[str] = set()

    for run_base in run_search_roots(args):
        if not run_base.exists():
            continue
        for run_dir in sorted(path for path in run_base.glob("run_*") if path.is_dir()):
            papers, source_path = load_papers(run_dir)
            if not papers:
                continue
            run_dois: set[str] = set()
            run_pmcids: set[str] = set()
            for row in papers:
                doi = normalize_doi(row.get("doi", ""))
                pmcid = normalize_pmcid(row.get("pmcid", ""))
                if doi:
                    run_dois.add(doi)
                    dois.add(doi)
                if pmcid:
                    run_pmcids.add(pmcid)
                    pmcids.add(pmcid)
            run_records.append(
                {
                    "run_dir": rel(run_dir),
                    "papers_source": rel(Path(source_path)) if source_path else "",
                    "downloaded_papers": len(papers),
                    "unique_dois": len(run_dois),
                    "unique_pmcids": len(run_pmcids),
                    "rebuilt_from_papers": True,
                }
            )
    return run_records, dois, pmcids


def main() -> int:
    args = parse_args()
    path = state_path(args)
    existing = read_json(path, default_global_state())
    rebuilt_runs, dois, pmcids = collect_runs(args)

    state = default_global_state()
    state["processed_dois"] = sorted(dois)
    state["processed_pmcids"] = sorted(pmcids)
    state["processed_panel_ids"] = [] if args.drop_panel_ids else sorted(set(existing.get("processed_panel_ids", [])))
    state["runs"] = rebuilt_runs
    if "last_dedupe_scan" in existing:
        state["last_dedupe_scan"] = existing["last_dedupe_scan"]
    state["last_paper_rebuild"] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source": (
            f"{rel(resolve_under_base(args.run_root) / args.subject / args.topic)}/run_*/Papers/papers.csv|json"
            if args.subject and args.topic
            else f"{rel(resolve_under_base(args.run_root))}/*/*/run_*/Papers/papers.csv|json"
        ),
        "run_count": len(rebuilt_runs),
        "processed_dois": len(state["processed_dois"]),
        "processed_pmcids": len(state["processed_pmcids"]),
        "processed_panel_ids": len(state["processed_panel_ids"]),
        "drop_panel_ids": args.drop_panel_ids,
    }

    if args.dry_run:
        print(
            {
                "state_path": str(path),
                "run_count": len(rebuilt_runs),
                "processed_dois": len(state["processed_dois"]),
                "processed_pmcids": len(state["processed_pmcids"]),
                "processed_panel_ids": len(state["processed_panel_ids"]),
            }
        )
        return 0

    backup_path = path.with_suffix(".json.bak")
    backup_created = False
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        backup_created = True
    write_json(path, state)
    print(
        {
            "state_path": str(path),
            "backup_path": str(backup_path) if backup_created else "",
            "run_count": len(rebuilt_runs),
            "processed_dois": len(state["processed_dois"]),
            "processed_pmcids": len(state["processed_pmcids"]),
            "processed_panel_ids": len(state["processed_panel_ids"]),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
