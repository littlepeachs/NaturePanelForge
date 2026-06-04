#!/usr/bin/env python3
"""User-facing single-image entry point for Codex panel-to-code reproduction."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


BASE_DIR = Path(__file__).resolve().parents[1]


def safe_name(value: str) -> str:
    value = (value or "").strip() or "user_panel"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "user_panel"


def resolve_path(path: Path | str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else (BASE_DIR / path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_image_to_target(image_path: Path, target_path: Path) -> dict[str, Any]:
    if not image_path.exists():
        raise FileNotFoundError(f"input image not found: {image_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as original:
        img = ImageOps.exif_transpose(original)
        width, height = img.size
        if img.mode in {"RGBA", "LA"}:
            img.save(target_path)
        else:
            img.convert("RGB").save(target_path)
    return {"width": width, "height": height, "format": image_path.suffix.lower().lstrip(".")}


def copy_optional_pdf(pdf_path: Path | None, target_pdf: Path) -> str:
    if pdf_path is None:
        return ""
    if not pdf_path.exists():
        raise FileNotFoundError(f"input PDF not found: {pdf_path}")
    target_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, target_pdf)
    return str(target_pdf)


def build_panel_bundle(
    *,
    image_path: Path,
    out_root: Path,
    panel_id: str,
    caption: str,
    chart_type: str,
    source_pdf: Path | None = None,
    overwrite: bool = False,
) -> tuple[Path, dict[str, Any]]:
    panel_id = safe_name(panel_id)
    panel_dir = out_root / "Reproduce_Statistical" / safe_name(chart_type) / panel_id
    if panel_dir.exists() and overwrite:
        shutil.rmtree(panel_dir)
    panel_dir.mkdir(parents=True, exist_ok=True)

    image_info = copy_image_to_target(image_path, panel_dir / "target.png")
    target_pdf = copy_optional_pdf(source_pdf, panel_dir / "target.pdf")

    metadata = {
        "panel_id": panel_id,
        "source": "user_image",
        "input_image_path": str(image_path),
        "input_pdf_path": str(source_pdf) if source_pdf else "",
        "target_png_path": str(panel_dir / "target.png"),
        "target_pdf_path": target_pdf,
        "caption": caption,
        "category": "data_statistical",
        "data_subtype": safe_name(chart_type),
        "image_width": image_info["width"],
        "image_height": image_info["height"],
        "input_format": image_info["format"],
    }
    write_json(panel_dir / "metadata.json", metadata)

    qwen_score = {
        "panel_id": panel_id,
        "category": "data_statistical",
        "data_subtype": safe_name(chart_type),
        "source": "user_supplied",
        "reason": "User supplied a target image directly; no Qwen scoring was run.",
    }
    write_json(panel_dir / "qwen_score.json", qwen_score)
    (panel_dir / "qwen_prompt.md").write_text(
        "User-supplied image workflow. Qwen scoring was not required for this single-image reproduction task.\n",
        encoding="utf-8",
    )
    (panel_dir / "raw_response.txt").write_text("", encoding="utf-8")

    panel_list = out_root / "Reproduce_Statistical" / "panel_dirs.txt"
    panel_list.parent.mkdir(parents=True, exist_ok=True)
    panel_list.write_text(str(panel_dir) + "\n", encoding="utf-8")
    return panel_dir, metadata


def build_codex_command(args: argparse.Namespace, panel_dir: Path, out_root: Path) -> list[str]:
    reviews_dir = out_root / "Reproduce_Statistical_Reviews"
    specs_dir = out_root / "Reproduce_Statistical_Specs"
    cmd = [
        sys.executable,
        str(BASE_DIR / "examples" / "prompt_codex_reproduce_fig02_g.py"),
        "--panel-dir",
        str(panel_dir),
        "--panel-root",
        str(out_root / "Reproduce_Statistical"),
        "--reviews-dir",
        str(reviews_dir),
        "--specs-dir",
        str(specs_dir),
        "--model",
        args.model,
        "--reasoning-effort",
        args.reasoning_effort,
        "--jobs",
        "1",
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
    if args.skip_existing:
        cmd.append("--skip-existing")
    if args.stream_events:
        cmd.append("--stream-events")
    if args.dry_run:
        cmd.append("--dry-run")
    return cmd


def review_dir_for_panel(panel_dir: Path, out_root: Path) -> Path:
    panel_root = out_root / "Reproduce_Statistical"
    try:
        relative = panel_dir.relative_to(panel_root)
    except ValueError:
        relative = Path(panel_dir.name)
    return out_root / "Reproduce_Statistical_Reviews" / relative


def expected_result_paths(panel_dir: Path, out_root: Path, output_stem: str = "reproduce_panel") -> dict[str, Path]:
    review_dir = review_dir_for_panel(panel_dir, out_root)
    return {
        "script": panel_dir / f"{output_stem}.py",
        "png": panel_dir / f"{output_stem}.png",
        "pdf": panel_dir / f"{output_stem}.pdf",
        "review_summary": review_dir / f"{output_stem}_review_summary.json",
        "review_notes": review_dir / f"{output_stem}_review_notes.md",
        "run_log": review_dir / f"{output_stem}_run_log.md",
    }


def load_review_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "invalid_json", "review_passed": False}
    return payload if isinstance(payload, dict) else {"status": "invalid_json", "review_passed": False}


def build_result_summary(
    *,
    panel_dir: Path,
    out_root: Path,
    metadata: dict[str, Any],
    exit_code: int,
    dry_run: bool,
) -> tuple[dict[str, Any], int]:
    paths = expected_result_paths(panel_dir, out_root)
    required_keys = ["script", "png", "pdf", "review_summary"]
    missing = [] if dry_run else [str(paths[key]) for key in required_keys if not paths[key].exists()]
    code = paths["script"].read_text(encoding="utf-8", errors="replace") if paths["script"].exists() else ""
    review_summary = load_review_summary(paths["review_summary"])
    review_passed = bool(review_summary.get("review_passed")) if review_summary else False
    live_contract_checked = not dry_run
    contract_passed = live_contract_checked and exit_code == 0 and not missing and review_passed
    status = "dry_run" if dry_run else ("ok" if contract_passed else "failed")
    summary = {
        "status": status,
        "live_contract_checked": live_contract_checked,
        "contract_passed": contract_passed,
        "panel_dir": str(panel_dir),
        "metadata_path": str(panel_dir / "metadata.json"),
        "target_png_path": metadata["target_png_path"],
        "reproduce_script_path": str(paths["script"]),
        "reproduce_png_path": str(paths["png"]),
        "reproduce_pdf_path": str(paths["pdf"]),
        "review_summary_path": str(paths["review_summary"]),
        "review_notes_path": str(paths["review_notes"]),
        "run_log_path": str(paths["run_log"]),
        "codex_command_exit_code": exit_code,
        "missing_outputs": missing,
        "review_passed": review_passed,
        "review_summary": review_summary,
        "code": code,
    }
    return_code = 0 if dry_run or contract_passed else (exit_code if exit_code else 1)
    return summary, return_code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reproduce one user-supplied scientific figure panel image with the Codex agent loop."
    )
    parser.add_argument("--image", type=Path, required=True, help="Input target image, for example a PNG panel.")
    parser.add_argument("--source-pdf", type=Path, default=None, help="Optional target PDF copied into the task bundle.")
    parser.add_argument("--out-root", type=Path, default=BASE_DIR / "UserRuns" / "single_image_demo")
    parser.add_argument("--panel-id", default="", help="Stable ID for the user panel. Defaults to the image stem.")
    parser.add_argument("--caption", default="", help="Optional caption or visual description for Codex.")
    parser.add_argument("--chart-type", default="user_supplied", help="Chart subtype directory name.")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--max-codex-processes", type=int, default=8)
    parser.add_argument("--process-user", default=os.environ.get("USER", "unknown"))
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--review-rounds", type=int, default=4)
    parser.add_argument("--codex-retries", type=int, default=8)
    parser.add_argument("--codex-retry-sleep", type=float, default=20.0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--stream-events", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Prepare the bundle and print the Codex prompt without running Codex.")
    parser.add_argument("--print-command", action="store_true", help="Print the underlying Codex batch command.")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    image_path = resolve_path(args.image)
    source_pdf = resolve_path(args.source_pdf) if args.source_pdf else None
    out_root = resolve_path(args.out_root)
    panel_id = args.panel_id or image_path.stem
    if not args.process_user:
        args.process_user = os.environ.get("USER", "unknown")

    panel_dir, metadata = build_panel_bundle(
        image_path=image_path,
        out_root=out_root,
        panel_id=panel_id,
        caption=args.caption,
        chart_type=args.chart_type,
        source_pdf=source_pdf,
        overwrite=args.overwrite,
    )
    cmd = build_codex_command(args, panel_dir, out_root)
    if args.print_command:
        print(" ".join(str(item) for item in cmd), flush=True)
    result = subprocess.run(cmd, cwd=BASE_DIR, check=False)
    summary, return_code = build_result_summary(
        panel_dir=panel_dir,
        out_root=out_root,
        metadata=metadata,
        exit_code=result.returncode,
        dry_run=args.dry_run,
    )
    write_json(panel_dir / "user_reproduce_summary.json", summary)
    write_json(panel_dir / "result.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
