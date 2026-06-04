#!/usr/bin/env python3
"""Batch-run Codex CLI to refine existing panel reproductions."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import time
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PANEL_DIRS: list[Path] = []

import sys

sys.path.insert(0, str(PROJECT_ROOT))

from examples.prompt_codex_reproduce_fig02_g import (  # noqa: E402
    collect_panel_dirs,
    infer_panel_root,
    is_retryable_codex_error,
    mirrored_dir,
    output_paths,
    read_text_excerpt,
    resolve_optional_dir,
    run_codex_with_capacity,
    sleep_before_retry,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-run Codex final-polish prompts for panel reproductions.")
    parser.add_argument("--panel-dir", action="append", type=Path)
    parser.add_argument("--panel-glob", action="append")
    parser.add_argument("--panel-list", type=Path)
    parser.add_argument("--panel-root", type=Path)
    parser.add_argument("--reviews-dir", type=Path)
    parser.add_argument("--specs-dir", type=Path)
    parser.add_argument("--output-stem", default="reproduce_panel", help="Refined output stem inside refined panel dirs.")
    parser.add_argument("--model", help="Optional model override passed to codex exec.")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--max-codex-processes", type=int, default=16)
    parser.add_argument("--process-user", default=os.environ.get("USER", "unknown"))
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--review-rounds", type=int, default=4)
    parser.add_argument("--codex-retries", type=int, default=8)
    parser.add_argument("--codex-retry-sleep", type=float, default=20.0)
    parser.add_argument("--stream-events", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def review_summary_complete(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    required = {
        "status",
        "review_passed",
        "review_rounds_completed",
        "max_review_rounds",
        "final_assessment",
        "font_audit_passed",
        "layout_audit_passed",
        "edge_visibility_passed",
    }
    if not required.issubset(data):
        return False
    return bool(data.get("review_passed") is True)


def complexity_assessment_complete(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    required = {
        "panel_id",
        "refine_complexity_score",
        "complexity_reason",
        "caption_based_content_summary",
    }
    if not required.issubset(data):
        return False
    try:
        score = float(data.get("refine_complexity_score"))
    except Exception:
        return False
    if not (0.0 <= score <= 10.0):
        return False
    if not str(data.get("complexity_reason", "")).strip():
        return False
    if not str(data.get("caption_based_content_summary", "")).strip():
        return False
    return True


def refined_output_paths(panel_dir: Path, output_stem: str, review_dir: Path) -> dict[str, Path]:
    paths = output_paths(panel_dir, output_stem, review_dir).copy()
    paths["complexity_assessment"] = panel_dir / "refine_complexity_assessment.json"
    return paths


def refined_outputs_complete(paths: dict[str, Path]) -> bool:
    required = ["script", "png", "pdf", "log", "review_notes", "review_summary", "complexity_assessment"]
    if not all(paths[key].exists() for key in required):
        return False
    return review_summary_complete(paths["review_summary"]) and complexity_assessment_complete(paths["complexity_assessment"])


def validate_refine_panel_dir(panel_dir: Path) -> None:
    if not panel_dir.is_dir():
        raise FileNotFoundError(f"panel directory not found: {panel_dir}")
    required = [
        panel_dir / "target.png",
        panel_dir / "reproduce_panel.py",
        panel_dir / "reproduce_panel.png",
        panel_dir / "reproduce_panel.pdf",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("missing required refined-input files: " + ", ".join(missing))


def read_json_dict(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def refine_context(panel_dir: Path, review_dir: Path, spec_dir: Path) -> str:
    parts = []
    for path, limit in [
        (panel_dir / "refine_stage_metadata.json", 4000),
        (panel_dir / "metadata.json", 5000),
        (panel_dir / "qwen_score.json", 2500),
        (panel_dir / "raw_response.txt", 1500),
        (panel_dir / "qwen_prompt.md", 2500),
        (panel_dir / "reproduce_panel.py", 9000),
        (review_dir / "source_reproduce_panel_review_summary.json", 2500),
        (review_dir / "source_reproduce_panel_review_notes.md", 3500),
        (review_dir / "source_reproduce_panel_run_log.md", 3500),
        (spec_dir / "source_reproduce_panel_prompt.md", 3500),
        (spec_dir / "source_reproduce_panel_raw_response.txt", 2500),
    ]:
        parts.append(f"--- {path.name} ---\n{read_text_excerpt(path, limit)}")
    return "\n\n".join(parts)


def build_prompt(panel_dir: Path, review_dir: Path, spec_dir: Path, output_stem: str, review_rounds: int) -> str:
    paths = refined_output_paths(panel_dir, output_stem, review_dir)
    target_image = panel_dir / "target.png"
    target_pdf = panel_dir / "target.pdf"
    panel_id = panel_dir.name
    current_script = panel_dir / f"{output_stem}.py"
    current_png = panel_dir / f"{output_stem}.png"
    current_pdf = panel_dir / f"{output_stem}.pdf"
    metadata = read_json_dict(panel_dir / "metadata.json")
    panel_caption = str(metadata.get("panel_caption", "")).strip()
    figure_caption = str(metadata.get("figure_caption", "")).strip()
    source_review_summary = review_dir / "source_reproduce_panel_review_summary.json"
    source_review_notes = review_dir / "source_reproduce_panel_review_notes.md"
    source_review_log = review_dir / "source_reproduce_panel_run_log.md"

    return f"""
You are running inside a writable Codex CLI workspace at:
{PROJECT_ROOT}

Task:
Polish and improve an existing scientific figure panel reproduction with Python/matplotlib.
This is a final refinement pass, not a from-scratch redraw. Split the work into
two roles: a code-writing/refine agent that edits the existing script, and a
review/polish agent that audits the refined render against the target and the
current reproduction. If subagent tools are available, use a worker/code-writing
agent and an explorer/review agent. If subagent tools are unavailable in this
nested run, simulate the two roles in separate write/review passes and record
that fallback in the run log.

Panel id:
{panel_id}

Refined panel directory:
{panel_dir}

Target files:
- target image: {target_image}
- target PDF: {target_pdf}

Current baseline reproduction to improve:
- current Python script: {current_script}
- current PNG: {current_png}
- current PDF: {current_pdf}

Caption context:
- panel caption: {panel_caption or "(not provided)"}
- figure caption: {figure_caption or "(not provided)"}

Reference first-pass review artifacts:
- source review summary: {source_review_summary}
- source review notes: {source_review_notes}
- source run log: {source_review_log}

Required refined outputs in the same panel directory:
- Refined Python script: {paths["script"]}
- Refined PNG reproduction: {paths["png"]}
- Refined PDF reproduction: {paths["pdf"]}
- Complexity assessment JSON: {paths["complexity_assessment"]}

Required refined review outputs in the review directory:
- Review directory: {review_dir}
- Run log: {paths["log"]}
- Review notes: {paths["review_notes"]}
- Review summary JSON: {paths["review_summary"]}

Hard constraints:
- Do not overwrite or modify target.png, target.pdf, metadata.json,
  qwen_score.json, qwen_prompt.md, raw_response.txt, refine_stage_metadata.json,
  or any `source_*` reference file.
- Modify the existing `{paths["script"].name}` in place rather than creating a
  second competing script. Start by reading the current script and improving it.
- Create or overwrite only these seven refined outputs:
  `{paths["script"].name}`, `{paths["png"].name}`, `{paths["pdf"].name}`,
  `{paths["log"].name}`, `{paths["review_notes"].name}`, `{paths["review_summary"].name}`,
  `{paths["complexity_assessment"].name}`.
- The script must be standalone, deterministic, and runnable as:
  python {paths["script"]}
- The script must define main() -> int and use matplotlib with the Agg backend.
- The script itself must save both PNG and PDF outputs to the required paths.
- Use the target image dimensions as the main canvas-size reference.
- Do not rely on automatic tight layout/cropping as a polish fix. Avoid
  `plt.tight_layout()`, `fig.tight_layout()`, `constrained_layout=True`, and
  `savefig(..., bbox_inches="tight")` unless there is a very specific written
  reason in the run log. Prefer explicit figure size, axes positions,
  `subplots_adjust`, labelpad/tick padding, legend anchoring, and manual margins.
  Final `savefig` calls should preserve the designed canvas instead of cropping
  to a tight bounding box. If the current script already uses tight layout or
  tight bbox saving and labels/legends overlap or sit near edges, replace that
  layout logic with explicit spacing.
- Set the font family to Arial everywhere practical. Prefer a global matplotlib
  Arial setting; if needed, use explicit FontProperties pointing at the Arial
  font file. The review agent must fail the panel if font usage is inconsistent.
- Prioritize these polish goals:
  1. Arial font consistency
  2. sensible font-size hierarchy
  3. no label/tick/legend/title/colorbar overflow
  4. no overlap between x/y labels, tick labels, and legends
  5. correct rendering of x/y label symbols, including Greek letters,
     minus signs, subscripts, superscripts, and other special glyphs
  6. no text overlapping axes spines, panel borders, or figure edges
  7. complete visibility of all edge content
  8. closer visual match to target colors, spacing, widths, legend layout, and typography
- Treat any overlap or near-overlap as a review failure, even when nothing is
  technically clipped. Explicitly check x tick labels against x-axis labels,
  y tick labels against y-axis labels, tick labels against neighboring tick
  labels, legends against axes/data/text, colorbar ticks/labels against the
  colorbar/title, titles against panel letters, annotations against spines, and
  all text against the figure frame. Fix overlaps by changing axes geometry,
  padding, legend placement, tick rotation/alignment, or margins; do not solve
  overlap merely by making all fonts too small.
- If the target PNG appears cropped and cuts off labels, ticks, panel letters,
  legends, or other edge content, but your refined reproduction contains the full
  intended content, do not crop the refined reproduction just to match that defect.
  Preserve complete readable labels/content and note the target-crop issue in the run log.
- If the target panel mixes a statistical/data plot with small schematic,
  cartoon, mechanism, or workflow elements that are not practical to recreate
  faithfully with code, prioritize reproducing the code-drawable data/plot
  portion. It is acceptable to omit or simplify those non-code-friendly
  schematic elements.
- Perform iterative code-writing/review passes with a maximum of {review_rounds}
  total write/review iterations.
- After each write pass, run the script and inspect the new PNG. The next review
  pass must focus on font family, font size hierarchy, edge visibility, text
  overlap, legend placement, and remaining fine-grained visual mismatches.
- Review the actual saved PNG/PDF outputs, not only the matplotlib interactive
  canvas. In particular, confirm that the saved PNG has no axis/tick/legend/title
  collisions introduced by final rendering, DPI, or savefig settings.
- The review role must write concrete per-round findings to
  {paths["review_notes"]}. If any issue is found, the next write pass must edit
  the Python code itself before rerunning.
- Write the run log with elapsed time, role split, iteration count, assumptions,
  final PNG dimensions, Arial usage approach, and a round-by-round summary of
  which review findings led to code changes.
- Save {paths["complexity_assessment"]} as JSON. This file must assess how hard
  this panel is to refine from the current baseline into a high-quality result.
  The complexity is not about how hard the science is. It is about code-editing
  difficulty in this refine stage, considering the gap between current output
  and target, layout/annotation density, edge sensitivity, nonstandard visual
  elements, and how easy the current script is to edit safely.
- In the same JSON file, add a concise English description of what this panel
  shows. Use the caption as supporting context, but keep the image as the final
  ground truth and do not invent details that are not visible or strongly
  supported by the caption.
- Save {paths["complexity_assessment"]} with keys:
  `panel_id`, `refine_complexity_score`, `complexity_reason`,
  `caption_based_content_summary`.
- `refine_complexity_score` must be a 0-10 score where 0 means trivial final
  polish and 10 means very hard final polish from the current baseline.
- `complexity_reason` must be brief and concrete.
- `caption_based_content_summary` must be a brief factual English summary of
  the panel content in one or two sentences.
- Save {paths["review_summary"]} as JSON with keys:
  `status`, `review_passed`, `review_rounds_completed`, `max_review_rounds`,
  `final_assessment`, `font_audit_passed`, `layout_audit_passed`,
  and `edge_visibility_passed`.

Helpful source context:
{refine_context(panel_dir, review_dir, spec_dir)}

Recommended workflow:
1. Read the current `{paths["script"].name}` and inspect the current PNG against target.png.
2. Read the source first-pass review notes/summary to avoid repeating old issues.
3. Refine the existing script in place. Do not simply restate prior conclusions.
4. Run `python {paths["script"]}` and verify that `{paths["png"]}` and `{paths["pdf"]}` exist.
5. Review the refined PNG against target.png, concentrating on:
   - Arial consistency
   - font sizes
   - x/y label, x/y tick, title, colorbar, and legend overlap checks
   - whether any text touches or nearly touches axes spines, neighboring labels,
     the legend box, colorbar, panel letter, or the figure frame
   - correct rendering of x/y label symbols and special glyphs
   - label/tick/legend/title/colorbar boundary safety
   - explicit-layout spacing instead of tight-layout or tight-bbox cropping
   - complete visibility near all four edges
   - small code-fixable visual mismatches
6. Before finalizing, write the complexity assessment JSON and make sure the
   concise caption-based content summary is specific to this panel rather than
   generic boilerplate.
7. Iterate until the refined result is clearly better than the incoming baseline.
8. Final response should report only created files, final PNG size, iteration
   count, and the regeneration command.
""".strip()


def run_one_panel(panel_dir: Path, args: argparse.Namespace) -> tuple[Path, bool, str]:
    validate_refine_panel_dir(panel_dir)
    review_dir = mirrored_dir(panel_dir, args.panel_root, args.reviews_dir)
    spec_dir = mirrored_dir(panel_dir, args.panel_root, args.specs_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    if spec_dir != panel_dir:
        spec_dir.mkdir(parents=True, exist_ok=True)
    paths = refined_output_paths(panel_dir, args.output_stem, review_dir)
    prompt_path = spec_dir / f"{args.output_stem}_prompt.md"
    raw_response_path = spec_dir / f"{args.output_stem}_raw_response.txt"
    if args.skip_existing and refined_outputs_complete(paths):
        return panel_dir, True, "skipped existing refined outputs"

    prompt = build_prompt(panel_dir, review_dir, spec_dir, args.output_stem, args.review_rounds)
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    if args.dry_run:
        return panel_dir, True, prompt

    answer = ""
    start = time.monotonic()
    max_attempts = max(1, args.codex_retries)
    for attempt in range(1, max_attempts + 1):
        try:
            if attempt > 1:
                sleep_before_retry(args.codex_retry_sleep, attempt - 1, panel_dir.name)
            answer = run_codex_with_capacity(
                prompt,
                cwd=PROJECT_ROOT,
                panel_id=panel_dir.name,
                process_user=args.process_user,
                max_codex_processes=args.max_codex_processes,
                poll_seconds=args.poll_seconds,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                sandbox="workspace-write",
                timeout=args.timeout,
                stream_events=args.stream_events,
            )
            break
        except Exception as exc:
            if attempt >= max_attempts or not is_retryable_codex_error(exc):
                raise
            print(
                f"[{panel_dir.name}] transient Codex failure on attempt "
                f"{attempt}/{max_attempts}: {type(exc).__name__}: {exc}",
                flush=True,
            )
    raw_response_path.write_text(answer + "\n", encoding="utf-8")
    missing = [path for path in paths.values() if not path.exists()]
    if missing:
        raise RuntimeError("missing expected refined outputs: " + ", ".join(str(path) for path in missing))
    if not review_summary_complete(paths["review_summary"]):
        raise RuntimeError(f"refined review summary incomplete or not passed: {paths['review_summary']}")
    if not complexity_assessment_complete(paths["complexity_assessment"]):
        raise RuntimeError(f"refined complexity assessment incomplete: {paths['complexity_assessment']}")
    elapsed = time.monotonic() - start
    return panel_dir, True, f"completed in {elapsed:.1f}s\n{answer}"


def main() -> int:
    args = parse_args()
    panel_dirs = collect_panel_dirs(args)
    args.panel_root = infer_panel_root(panel_dirs, resolve_optional_dir(args.panel_root))
    args.reviews_dir = resolve_optional_dir(args.reviews_dir)
    args.specs_dir = resolve_optional_dir(args.specs_dir)
    if args.jobs < 1:
        print("ERROR: --jobs must be >= 1", file=sys.stderr)
        return 1
    if args.max_codex_processes < 1:
        print("ERROR: --max-codex-processes must be >= 1", file=sys.stderr)
        return 1
    if args.review_rounds < 1:
        print("ERROR: --review-rounds must be >= 1", file=sys.stderr)
        return 1
    if args.codex_retries < 1:
        print("ERROR: --codex-retries must be >= 1", file=sys.stderr)
        return 1

    print(f"Refined panels: {len(panel_dirs)}", flush=True)
    print(f"Panel root: {args.panel_root}", flush=True)
    if args.reviews_dir:
        print(f"Reviews root: {args.reviews_dir}", flush=True)
    if args.specs_dir:
        print(f"Specs root: {args.specs_dir}", flush=True)
    for panel_dir in panel_dirs:
        print(f"  {panel_dir}", flush=True)

    if args.dry_run:
        for panel_dir in panel_dirs:
            review_dir = mirrored_dir(panel_dir, args.panel_root, args.reviews_dir)
            spec_dir = mirrored_dir(panel_dir, args.panel_root, args.specs_dir)
            print("\n" + "=" * 100)
            print(f"PROMPT FOR {panel_dir.name}")
            print("=" * 100)
            print(build_prompt(panel_dir, review_dir, spec_dir, args.output_stem, args.review_rounds))
        return 0

    max_workers = min(args.jobs, len(panel_dirs), args.max_codex_processes)
    failures = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_panel = {executor.submit(run_one_panel, panel_dir, args): panel_dir for panel_dir in panel_dirs}
        for future in concurrent.futures.as_completed(future_to_panel):
            panel_dir = future_to_panel[future]
            try:
                _, _, message = future.result()
            except Exception as exc:
                failures += 1
                print(f"\nFAILED: {panel_dir}\n{exc}", file=sys.stderr, flush=True)
                print(traceback.format_exc(), file=sys.stderr, flush=True)
            else:
                print(f"\nDONE: {panel_dir}\n{message}", flush=True)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
