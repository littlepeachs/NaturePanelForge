#!/usr/bin/env python3
"""Batch prompt Codex CLI to reproduce high-quality figure panels.

The nested Codex run for each panel is instructed to split the task into a
code-writing role and a review role, iterate, then save code/rendered outputs
in the panel directory plus review/spec artifacts in mirrored directories.

Run a custom batch:
  python3 examples/prompt_codex_reproduce_fig02_g.py \\
    --panel-list PipelineRuns/biology/AI_biology/<run>/Reproduce_Statistical/panel_dirs.txt --jobs 8
"""

from __future__ import annotations

import argparse
import concurrent.futures
import glob
import json
import os
import queue
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PANEL_DIRS: list[Path] = []

START_LOCK = threading.Lock()

sys.path.insert(0, str(PROJECT_ROOT))

from examples.call_codex_cli import require_codex_cli  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-run Codex panel reproduction prompts.")
    parser.add_argument(
        "--panel-dir",
        action="append",
        type=Path,
        help="Panel directory containing target.png. Can be passed multiple times.",
    )
    parser.add_argument(
        "--panel-glob",
        action="append",
        help="Glob relative to project root, or absolute glob, selecting panel directories.",
    )
    parser.add_argument(
        "--panel-list",
        type=Path,
        help="Text file with one panel directory per line. Blank lines and # comments are ignored.",
    )
    parser.add_argument(
        "--panel-root",
        type=Path,
        help="Optional root used to mirror panel subdirectories under review/spec roots.",
    )
    parser.add_argument(
        "--reviews-dir",
        type=Path,
        help="Optional mirrored root for review artifacts.",
    )
    parser.add_argument(
        "--specs-dir",
        type=Path,
        help="Optional mirrored root for prompt/raw-response artifacts.",
    )
    parser.add_argument("--output-stem", default="reproduce_panel", help="Output filename stem per panel.")
    parser.add_argument("--model", help="Optional model override passed to codex exec.")
    parser.add_argument(
        "--reasoning-effort",
        default="medium",
        help="Optional model reasoning effort passed to codex exec config.",
    )
    parser.add_argument("--timeout", type=int, default=2400, help="Timeout per panel in seconds.")
    parser.add_argument("--jobs", type=int, default=6, help="Maximum parallel panel jobs.")
    parser.add_argument(
        "--max-codex-processes",
        type=int,
        default=16,
        help="Maximum total codex processes allowed for --process-user before starting another.",
    )
    parser.add_argument(
        "--process-user",
        default=os.environ.get("USER", "unknown"),
        help="User whose codex processes are counted.",
    )
    parser.add_argument("--poll-seconds", type=float, default=10.0, help="Capacity polling interval.")
    parser.add_argument("--review-rounds", type=int, default=4, help="Maximum write/review iterations per panel.")
    parser.add_argument("--codex-retries", type=int, default=8, help="Retry attempts for retryable Codex/API failures.")
    parser.add_argument("--codex-retry-sleep", type=float, default=20.0, help="Base sleep seconds before retry.")
    parser.add_argument("--stream-events", action="store_true", help="Print Codex JSONL events.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip panels with all expected outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts without running Codex.")
    return parser.parse_args()


def resolve_panel_dir(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def resolve_optional_dir(path: Path | None) -> Path | None:
    if path is None:
        return None
    return resolve_panel_dir(path)


def collect_panel_dirs(args: argparse.Namespace) -> list[Path]:
    panel_dirs: list[Path] = []

    if args.panel_dir:
        panel_dirs.extend(resolve_panel_dir(path) for path in args.panel_dir)

    if args.panel_list:
        list_path = resolve_panel_dir(args.panel_list)
        for line in list_path.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item and not item.startswith("#"):
                panel_dirs.append(resolve_panel_dir(Path(item)))

    if args.panel_glob:
        for pattern in args.panel_glob:
            if Path(pattern).is_absolute():
                panel_dirs.extend(Path(path).resolve() for path in glob.glob(pattern) if Path(path).is_dir())
            else:
                panel_dirs.extend(path.resolve() for path in PROJECT_ROOT.glob(pattern) if path.is_dir())

    if not panel_dirs and DEFAULT_PANEL_DIRS:
        panel_dirs = [path.resolve() for path in DEFAULT_PANEL_DIRS]

    deduped: list[Path] = []
    seen: set[Path] = set()
    for panel_dir in panel_dirs:
        if panel_dir not in seen:
            deduped.append(panel_dir)
            seen.add(panel_dir)
    return deduped


def infer_panel_root(panel_dirs: list[Path], explicit_root: Path | None) -> Path:
    if explicit_root is not None:
        return explicit_root
    if not panel_dirs:
        return PROJECT_ROOT
    common = os.path.commonpath([str(path) for path in panel_dirs])
    return Path(common)


def mirrored_dir(panel_dir: Path, panel_root: Path, mirror_root: Path | None) -> Path:
    if mirror_root is None:
        return panel_dir
    relative = panel_dir.relative_to(panel_root)
    return mirror_root / relative


def output_paths(panel_dir: Path, output_stem: str, review_dir: Path) -> dict[str, Path]:
    return {
        "script": panel_dir / f"{output_stem}.py",
        "png": panel_dir / f"{output_stem}.png",
        "pdf": panel_dir / f"{output_stem}.pdf",
        "log": review_dir / f"{output_stem}_run_log.md",
        "review_notes": review_dir / f"{output_stem}_review_notes.md",
        "review_summary": review_dir / f"{output_stem}_review_summary.json",
    }


def read_text_excerpt(path: Path, max_chars: int) -> str:
    if not path.exists():
        return f"{path.name}: MISSING"
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n...[truncated]"


def panel_context(panel_dir: Path) -> str:
    parts = []
    for filename, limit in [
        ("metadata.json", 5000),
        ("qwen_score.json", 2000),
        ("raw_response.txt", 1500),
        ("qwen_prompt.md", 2500),
    ]:
        path = panel_dir / filename
        parts.append(f"--- {filename} ---\n{read_text_excerpt(path, limit)}")
    return "\n\n".join(parts)


def build_prompt(panel_dir: Path, review_dir: Path, output_stem: str, review_rounds: int) -> str:
    paths = output_paths(panel_dir, output_stem, review_dir)
    target_image = panel_dir / "target.png"
    target_pdf = panel_dir / "target.pdf"
    panel_id = panel_dir.name

    return f"""
You are running inside a writable Codex CLI workspace at:
{PROJECT_ROOT}

Task:
Reproduce one scientific figure panel with Python/matplotlib. Split the work into
two roles: a code-writing agent that implements the reproduction script, and a
review agent that audits rendered output against the target. If subagent tools
are available, use a worker/code-writing agent and an explorer/review agent. If
subagent tools are unavailable in this nested run, simulate the two roles in
separate write/review passes and record that fallback in the run log.

Panel id:
{panel_id}

Panel directory:
{panel_dir}

Target files:
- target image: {target_image}
- target PDF: {target_pdf}

Required outputs in the same panel directory:
- Python script: {paths["script"]}
- PNG reproduction: {paths["png"]}
- PDF reproduction: {paths["pdf"]}

Required review outputs in the review directory:
- Review directory: {review_dir}
- Run log: {paths["log"]}
- Review notes: {paths["review_notes"]}
- Review summary JSON: {paths["review_summary"]}

Hard constraints:
- Do not overwrite or modify target.png, target.pdf, metadata.json,
  qwen_score.json, qwen_prompt.md, or raw_response.txt.
- Create or overwrite only the six required files listed above.
- The script must be standalone, deterministic, and runnable as:
  python {paths["script"]}
- The script must define main() -> int and use matplotlib with the Agg backend.
- The script itself must save both PNG and PDF outputs to the required paths.
- Use the target image dimensions as the main canvas-size reference.
- Prefer matplotlib primitives, patches, imshow gradients, and text placement
  over raster tracing. The output should be an editable-code approximation.
- Match the target as closely as practical: plot type, data values visible in
  the panel, labels, ticks, legends, colors, line widths, fonts, spacing,
  panel label, and overall crop.
- If the target PNG appears cropped and cuts off labels, ticks, panel letters,
  legends, or other edge content, but your reproduction contains the full
  intended content, do not crop the reproduction just to match that defect.
  Preserve complete readable labels/content. This applies specifically to
  truncated panel letters such as a/b/c/d/e and truncated axis/legend text as
  well. Do not intentionally reproduce those truncation defects; note the
  target-crop issue in the run log.
- If the target panel mixes a statistical/data plot with small schematic,
  cartoon, mechanism, or workflow elements that are not practical to recreate
  faithfully with code, prioritize reproducing the code-drawable data/plot
  portion. It is acceptable to omit or simplify those non-code-friendly
  schematic elements.
- Perform iterative code-writing/review passes with a maximum of {review_rounds} total
  write/review iterations. Use at least two iterations when meaningful, but
  stop early if the first reviewed output is already very close.
- After each write pass, run the script and inspect the PNG dimensions. Review
  visual discrepancies and then revise.
- The review role must write concrete per-round findings to
  {paths["review_notes"]}. If any issue is found, the next write pass must edit
  the Python code itself before rerunning.
- Write the run log with elapsed time, role split, iteration count, assumptions,
  final PNG dimensions, all output paths, and a round-by-round summary of which
  review findings led to code changes.
- Save {paths["review_summary"]} as JSON with keys:
  `status`, `review_passed`, `review_rounds_completed`, `max_review_rounds`,
  and `final_assessment`.

Helpful source context:
{panel_context(panel_dir)}

Recommended workflow:
1. Inspect target.png and metadata/qwen files. Determine chart subtype and read
   visible numeric/text values from the target.
2. Code-writing role creates {paths["script"]}.
3. Run `python {paths["script"]}` and check that {paths["png"]} and {paths["pdf"]} exist.
4. Review role compares the rendered PNG against target.png and lists concrete
   fixes for data, geometry, colors, fonts, panel letters, labels, tick labels,
   legends, titles, colorbars, and any cropped content in {paths["review_notes"]}.
5. Iterate code and review until close enough.
6. Final response should report only created files, final PNG size, iteration
   count, and the regeneration command.
""".strip()


def is_codex_process(comm: str, args: str) -> bool:
    if comm == "codex":
        return True
    try:
        argv = shlex.split(args)
    except ValueError:
        argv = args.split()
    basenames = {Path(item).name for item in argv[:4]}
    if "codex" in basenames:
        return True
    if "codex" in args and " exec " in f" {args} " and "prompt_codex_reproduce" not in args:
        return True
    return False


def count_codex_processes(user: str) -> int:
    result = subprocess.run(
        ["ps", "-u", user, "-o", "pid=,comm=,args="],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    count = 0
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) < 2:
            continue
        comm = fields[1]
        args = fields[2] if len(fields) == 3 else ""
        if is_codex_process(comm, args):
            count += 1
    return count


def wait_for_codex_capacity(user: str, max_processes: int, poll_seconds: float, panel_id: str) -> None:
    while True:
        active = count_codex_processes(user)
        if active < max_processes:
            return
        print(
            f"[{panel_id}] waiting: {active} codex processes for user {user}; "
            f"limit is {max_processes}",
            flush=True,
        )
        time.sleep(poll_seconds)


def run_codex_with_capacity(
    prompt: str,
    *,
    cwd: Path,
    panel_id: str,
    process_user: str,
    max_codex_processes: int,
    poll_seconds: float,
    model: str | None,
    reasoning_effort: str,
    sandbox: str,
    timeout: int,
    stream_events: bool,
) -> str:
    codex = require_codex_cli()

    with tempfile.NamedTemporaryFile(prefix=f"codex-last-{panel_id}-", suffix=".txt") as last_message:
        cmd = [
            codex,
            "exec",
            "--skip-git-repo-check",
            "--json",
            "--output-last-message",
            last_message.name,
            "--sandbox",
            sandbox,
            "--cd",
            str(cwd),
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)

        with START_LOCK:
            wait_for_codex_capacity(process_user, max_codex_processes, poll_seconds, panel_id)
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

        def reader(pipe, name: str, out_queue: queue.Queue[tuple[str, str | None]]) -> None:
            try:
                for item in pipe:
                    out_queue.put((name, item))
            finally:
                out_queue.put((name, None))

        output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
        open_pipes = 0
        if process.stdout is not None:
            open_pipes += 1
            threading.Thread(target=reader, args=(process.stdout, "stdout", output_queue), daemon=True).start()
        if process.stderr is not None:
            open_pipes += 1
            threading.Thread(target=reader, args=(process.stderr, "stderr", output_queue), daemon=True).start()

        events: list[dict] = []
        stderr_lines: list[str] = []
        try:
            deadline = time.monotonic() + timeout
            while open_pipes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
                    raise TimeoutError(f"codex exec timed out after {timeout} seconds for {panel_id}")
                try:
                    name, line = output_queue.get(timeout=min(1.0, remaining))
                except queue.Empty:
                    continue
                if line is None:
                    open_pipes -= 1
                    continue
                if name == "stderr":
                    stderr_lines.append(line)
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"type": "raw_stdout", "text": line}
                events.append(event)
                if stream_events:
                    print(f"[{panel_id}] {json.dumps(event, ensure_ascii=False)}", flush=True)
            return_code = process.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            raise TimeoutError(f"codex exec timed out after {timeout} seconds for {panel_id}") from exc

        stderr = "".join(stderr_lines)
        final_text = Path(last_message.name).read_text(encoding="utf-8").strip()
        if return_code != 0:
            event_summary = "\n".join(json.dumps(e, ensure_ascii=False) for e in events[-5:])
            raise RuntimeError(
                f"codex exec failed for {panel_id} with exit code {return_code}\n\n"
                f"stderr:\n{stderr}\n\nlast events:\n{event_summary}"
            )
        return final_text


RETRYABLE_CODEX_ERROR_MARKERS = (
    "502 bad gateway",
    "upstream request failed",
    "reconnecting...",
    "reconnecting",
    "stream disconnected before completion",
    "at capacity",
    "capacity",
    "rate limit",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
)


def is_retryable_codex_error(exc: BaseException) -> bool:
    message = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in message for marker in RETRYABLE_CODEX_ERROR_MARKERS)


def sleep_before_retry(base_seconds: float, attempt: int, panel_id: str) -> None:
    delay = max(1.0, base_seconds * attempt)
    print(f"[{panel_id}] retrying after {delay:.0f}s", flush=True)
    time.sleep(delay)


def validate_panel_dir(panel_dir: Path) -> None:
    if not panel_dir.is_dir():
        raise FileNotFoundError(f"panel directory not found: {panel_dir}")
    if not (panel_dir / "target.png").exists():
        raise FileNotFoundError(f"target.png not found in panel directory: {panel_dir}")


def run_one_panel(panel_dir: Path, args: argparse.Namespace) -> tuple[Path, bool, str]:
    validate_panel_dir(panel_dir)
    review_dir = mirrored_dir(panel_dir, args.panel_root, args.reviews_dir)
    spec_dir = mirrored_dir(panel_dir, args.panel_root, args.specs_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    if spec_dir != panel_dir:
        spec_dir.mkdir(parents=True, exist_ok=True)
    paths = output_paths(panel_dir, args.output_stem, review_dir)
    prompt_path = spec_dir / f"{args.output_stem}_prompt.md"
    raw_response_path = spec_dir / f"{args.output_stem}_raw_response.txt"
    if args.skip_existing and all(path.exists() for path in paths.values()):
        return panel_dir, True, "skipped existing outputs"

    prompt = build_prompt(panel_dir, review_dir, args.output_stem, args.review_rounds)
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    if args.dry_run:
        return panel_dir, True, prompt

    start = time.monotonic()
    answer = ""
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
        raise RuntimeError("missing expected outputs: " + ", ".join(str(path) for path in missing))
    elapsed = time.monotonic() - start
    return panel_dir, True, f"completed in {elapsed:.1f}s\n{answer}"


def main() -> int:
    args = parse_args()
    panel_dirs = collect_panel_dirs(args)
    if not panel_dirs:
        print(
            "ERROR: no panel directories selected. Pass --panel-list, --panel-dir, or --panel-glob "
            "after running scripts/run_demo_reproduce.sh or export_qwen_selected_panels.py.",
            file=sys.stderr,
        )
        return 1
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

    print(f"Panels: {len(panel_dirs)}", flush=True)
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
            print("\n" + "=" * 100)
            print(f"PROMPT FOR {panel_dir.name}")
            print("=" * 100)
            print(build_prompt(panel_dir, review_dir, args.output_stem, args.review_rounds))
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
