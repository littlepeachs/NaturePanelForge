#!/usr/bin/env python3
"""Split full scientific figures into panels with Codex visual inspection."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FULL_FIGURES_CSV = BASE_DIR / "FullFigures" / "full_figures.csv"
DEFAULT_PANELS_DIR = BASE_DIR / "Panels"
DEFAULT_REVIEWS_DIR = BASE_DIR / "PanelReviewsCodex"
DEFAULT_SPECS_DIR = BASE_DIR / "PanelSplitSpecsCodex"
DEFAULT_FINISHED_DIR_NAME = "Panel_full_finsh"
PANEL_MARK_RE = re.compile(r"(?:(?<=^)|(?<=[.;]))\s*([a-z])\s*(?:[-–—]\s*([a-z]))?\s*(?:[,.)]\s*)?(?=[A-Z0-9(])")
START_LOCK = threading.Lock()

sys.path.insert(0, str(BASE_DIR))

from examples.call_codex_cli import require_codex_cli  # noqa: E402


@dataclass
class PanelSpec:
    label: str
    bbox: list[int]
    confidence: float
    reason: str


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def resolve_path(path: Path | str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else BASE_DIR / path


def white_background(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA"):
        bg = Image.new("RGBA", image.size, "WHITE")
        bg.alpha_composite(image.convert("RGBA"))
        return bg.convert("RGB")
    return image.convert("RGB")


def image_to_pdf(image_path: Path, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as img:
        white_background(img).save(pdf_path, "PDF", resolution=300.0)


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def expand_label_range(start: str, end: str | None) -> list[str]:
    if not end:
        return [start]
    a, b = ord(start), ord(end)
    if not (97 <= a <= b <= 122) or b - a > 25:
        return [start]
    return [chr(code) for code in range(a, b + 1)]


def labels_from_caption(caption: str) -> tuple[list[str], dict[str, str]]:
    text = " ".join(caption.replace("\u2013", "-").replace("\u2014", "-").split())
    matches = list(PANEL_MARK_RE.finditer(text))
    labels: list[str] = []
    mapping: dict[str, str] = {}
    for index, match in enumerate(matches):
        expanded = expand_label_range(match.group(1), match.group(2))
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[match.start() : segment_end].strip()
        for label in expanded:
            if label not in labels:
                labels.append(label)
            mapping[label] = segment
    return labels, mapping


def expected_labels(row: dict) -> tuple[list[str], dict[str, str]]:
    labels = [item.strip() for item in row.get("parsed_panel_labels", "").split(",") if item.strip()]
    caption_labels, caption_map = labels_from_caption(row.get("caption", ""))
    if labels:
        return labels, caption_map
    return caption_labels, caption_map


def code_loop_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "figure_id": {"type": "string"},
            "split_script_path": {"type": "string"},
            "final_spec_path": {"type": "string"},
            "all_review_passed": {"type": "boolean"},
            "review_rounds": {"type": "integer"},
            "notes": {"type": "string"},
        },
        "required": [
            "figure_id",
            "split_script_path",
            "final_spec_path",
            "all_review_passed",
            "review_rounds",
            "notes",
        ],
    }


def figure_id(row: dict) -> str:
    return f"{row.get('paper_id', 'unknown')}__fig{int(row.get('figure_index') or 0):02d}"


def build_prompt(
    row: dict,
    image_path: Path,
    width: int,
    height: int,
    labels: list[str],
    review_rounds: int,
    panel_dir: Path,
    review_dir: Path,
    spec_dir: Path,
) -> str:
    label_text = ", ".join(labels) if labels else "none parsed; infer visible panel letters or use panel01/panel02"
    figure_index = int(row.get("figure_index") or 0)
    script_path = spec_dir / f"fig{figure_index:02d}_split_figure.py"
    final_spec_path = spec_dir / f"fig{figure_index:02d}_final_spec.json"
    review_notes_path = spec_dir / f"fig{figure_index:02d}_review_notes.md"
    crop_sheet_path = spec_dir / f"fig{figure_index:02d}_final_crops.png"
    overlay_path = review_dir / f"fig{figure_index:02d}_codex_review.png"
    return f"""
This Codex session is responsible for exactly one full scientific figure. Treat
this as one complete mini-project for that figure only.

You MUST implement the panel split by writing and running Python code. Do not
return only bounding boxes for the parent process to crop. The parent process
will only read your files and summarize them; it will not crop or repair panels.

Inside this same Codex session, run a two-agent code-in-the-loop workflow:

1. Split Agent writes `{rel(script_path)}`. The script must use PIL/matplotlib
   or similar Python code to crop the attached full figure into panel PNG/PDF
   files. The bbox definitions must live in the script in an obvious editable
   data structure such as `PANEL_SPECS = [...]`.
2. Split Agent runs the script and creates the initial crops, an overlay review
   image, a crop sheet, and a draft JSON spec.
3. Review Agent inspects the original figure, the generated crop files, the
   overlay, and the crop sheet. It must write concrete review suggestions to
   `{rel(review_notes_path)}`. The Review Agent must reject any crop with missing
   or clipped panel letters, axes, tick labels, x/y labels, legends, titles,
   colorbars, annotations, or neighboring-panel contamination.
4. If the Review Agent finds any issue, Split Agent MUST edit
   `{rel(script_path)}` to fix only the failed panel bboxes and rerun the script.
   The review suggestions must cause code/bbox edits, followed by a rerun.
5. Perform {review_rounds} review pass(es). If a pass finds no issue, record
   that the code was left unchanged for that pass. If any issue is found in any
   pass, code must be edited and rerun before the next pass.
6. Only after the final review, write `{rel(final_spec_path)}` and return the
   final JSON response required by the schema.

This is mandatory: review suggestions must drive code changes in
`{rel(script_path)}`. Do not merely describe fixes. Do not rely on the parent
program to crop or repair the images.

Figure:
- figure_id: {figure_id(row)}
- image path: {rel(image_path)}
- image size: width={width}, height={height}
- paper_id: {row.get('paper_id', '')}
- DOI: {row.get('doi', '')}
- figure_label: {row.get('figure_label', '')}
- expected panel labels from caption: {label_text}

Required output paths:
- Split script: {rel(script_path)}
- Final spec JSON: {rel(final_spec_path)}
- Review notes: {rel(review_notes_path)}
- Final crop sheet: {rel(crop_sheet_path)}
- Overlay review image: {rel(overlay_path)}
- Panel output directory: {rel(panel_dir)}
- Review output directory: {rel(review_dir)}
- Specs/code directory: {rel(spec_dir)}

Required panel image naming:
- Save each final panel PNG as `{rel(panel_dir)}/fig{figure_index:02d}_<label>.png`
  where <label> is a, b, c, ... when visible, otherwise panel01, panel02, ...
- Save each corresponding PDF as `{rel(panel_dir)}/fig{figure_index:02d}_<label>.pdf`
- The final spec must contain each panel's `relative_path` and `panel_pdf_path`.
- The saved Python script must be the source of truth for the final crop bboxes.
  Its final run must produce the exact PNG/PDF files referenced by the spec.

Panel splitting rules:
- Use original image pixel coordinates in [x0, y0, x1, y1].
- Split according to the panel labels already present in the image, for example
  a, b, c, d or a-h.
- Each output panel must contain only the content for that label.
- Each bbox must completely preserve the visible panel letter, statistical plot
  body, x-axis label, y-axis label, x/y tick labels, legend, title or subplot
  title if present, colorbar, annotations, grouping labels, icon explanations,
  scale bars, and every visual/text element directly belonging to that panel.
- Never cut off axes, labels, tick labels, legends, titles, colorbars,
  annotations, panel letters, or any other necessary explanatory element.
- Treat text near a crop edge as a likely failure. If any panel letter, title,
  axis label, tick label, legend entry, colorbar tick/label, significance mark,
  bracket, group label, or annotation would touch or sit within a few pixels of
  the crop boundary, expand that side until there is visible white/background
  margin around the complete element.
- Never include content from a different panel: no other panel letter, image
  edge, leftover axis-label characters, legend, title, icon, colorbar, plot
  mark, or photo/schematic fragment.
- If two panels are very close, prioritize full preservation of the target
  panel labels and annotations. Choose a boundary in white/empty space whenever
  possible.
- Do not crop only the inner plotting area; keep the complete independent panel.
- Do not split legends, insets, zoom boxes, colorbars, molecular cartoons, or
  example images away from their parent panel when they belong to the same
  labelled panel.
- If a labelled panel contains multiple internal subplots/insets, output one
  bbox around the whole labelled panel.
- If there are visible panel letters, use those letters as labels.
- If no panel letters are visible but the figure has multiple independent
  charts/images, output panel01, panel02, ... in reading order.
- If the full figure is genuinely one panel, output one bbox labelled panel01
  around the full content, with a small margin.
- Prefer slightly larger complete boxes over tight crops that cut text, but do
  not include other panel content merely to add margin.
- For statistical panels, verify all four sides explicitly:
  left side preserves y-axis label and y tick labels; bottom side preserves
  x-axis label and x tick labels; top side preserves panel letter/title and
  statistical brackets; right side preserves legends, colorbars, colorbar tick
  labels, and right-side annotations.
- Avoid heavy overlap between adjacent top-level panel boxes.
- Ignore article page margins or empty white margins where possible.
- Before returning JSON, mentally inspect every proposed crop and confirm:
  clean content, no other panel remnants, complete statistical labels, complete
  legends/colorbars, and no clipping, truncated glyphs, missing tick labels, or
  cut-off annotations.

Internal Review Agent checklist for every proposed panel:
1. Left edge: y-axis title, rotated y label, y tick labels, panel letter,
   left-side annotations, error bars, brackets, and data marks are complete.
2. Bottom edge: x-axis title, x tick labels, rotated category labels,
   sample-size labels, footer annotations, and lower legends are complete.
3. Top edge: panel letter, title/subtitle, statistics brackets, p-values,
   arrows, and top annotations are complete.
4. Right edge: legend, legend title, colorbar, colorbar label, colorbar tick
   labels, right-side axis labels, and right-side annotations are complete.
5. If any glyph touches the crop edge, is cut mid-letter, or has unclear
   padding, the panel fails review and the bbox must be expanded on that side.
6. If expanding would include another panel, move the boundary into the blank
   gap. If unavoidable, prioritize complete target-panel labels and keep only
   clean white/background margin, not neighboring content.
7. Final bboxes should usually include a small background margin around all
   labels/legends/colorbars. A slightly larger clean crop is better than a
   tight crop that risks missing xytick, xylabel, legend, colorbar, or title.

Required implementation details for `{rel(script_path)}`:
- Read the source image from `{rel(image_path)}`.
- Convert transparent images to a white RGB background before cropping.
- Define all final bboxes in code, not only in a JSON file.
- Save every panel PNG and PDF under `{rel(panel_dir)}`.
- Save an overlay image with labelled rectangles to `{rel(overlay_path)}`.
- Save a crop sheet showing all final crops to `{rel(crop_sheet_path)}`.
- Save `{rel(final_spec_path)}` with the final bboxes, output paths,
  review status, and review history.
- Running `python3 {rel(script_path)}` from `{rel(BASE_DIR)}` must regenerate the
  final PNG/PDF/spec/review artifacts without manual edits.

Final JSON requirements:
- Your final assistant response must be the schema JSON only.
- `{rel(final_spec_path)}` must contain:
- Replace the example panel below with the real panel list and real bboxes.
  {{
    "figure_id": "{figure_id(row)}",
    "image_width": {width},
    "image_height": {height},
    "all_review_passed": true,
    "review_rounds": {review_rounds},
    "review_notes_path": "{rel(review_notes_path)}",
    "split_script_path": "{rel(script_path)}",
    "crop_sheet_path": "{rel(crop_sheet_path)}",
    "overlay_path": "{rel(overlay_path)}",
    "panels": [
      {{
        "label": "a",
        "bbox_xyxy": [0, 0, 100, 100],
        "confidence": 0.95,
        "reason": "include review-driven bbox changes",
        "relative_path": "{rel(panel_dir)}/fig{figure_index:02d}_a.png",
        "panel_pdf_path": "{rel(panel_dir)}/fig{figure_index:02d}_a.pdf",
        "review_passed": true,
        "edge_check": "left/bottom/top/right labels, ticks, legends, colorbar checked"
      }}
    ],
    "review_history": [
      {{
        "round": 1,
        "review_agent_suggestions": "specific issues, if any",
        "split_agent_code_changes": "bbox/code edits made before rerun"
      }}
    ]
  }}
- The final assistant response's `final_spec_path` must point to that file.

Caption:
{row.get('caption', '')}
""".strip()


def is_codex_process(comm: str, args: str) -> bool:
    if comm == "codex":
        return True
    try:
        argv = shlex.split(args)
    except ValueError:
        argv = args.split()
    basenames = {Path(item).name for item in argv[:4]}
    return "codex" in basenames or ("codex" in args and " exec " in f" {args} " and "codex_panel_split.py" not in args)


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
        if is_codex_process(fields[1], fields[2] if len(fields) == 3 else ""):
            count += 1
    return count


def wait_for_codex_capacity(user: str, max_processes: int, poll_seconds: float, figure: str) -> None:
    while True:
        active = count_codex_processes(user)
        if active < max_processes:
            return
        print(f"[{figure}] waiting: {active} codex processes for user {user}; limit is {max_processes}", flush=True)
        time.sleep(poll_seconds)


def run_codex_json(
    prompt: str,
    image_paths: Path | list[Path],
    *,
    figure: str,
    model: str,
    reasoning_effort: str,
    process_user: str,
    max_codex_processes: int,
    poll_seconds: float,
    timeout: int,
    stream_events: bool,
    schema: dict[str, Any],
    sandbox: str = "read-only",
) -> str:
    codex = require_codex_cli()
    attached_images = [image_paths] if isinstance(image_paths, Path) else list(image_paths)
    with tempfile.TemporaryDirectory(prefix=f"codex-panel-{figure}-") as tmp:
        tmp_dir = Path(tmp)
        last_message = tmp_dir / "last_message.txt"
        schema_path = tmp_dir / "schema.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        cmd = [
            codex,
            "exec",
            "--skip-git-repo-check",
            "--json",
            "--output-last-message",
            str(last_message),
            "--output-schema",
            str(schema_path),
            "--sandbox",
            sandbox,
            "--cd",
            str(BASE_DIR),
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
        ]
        for image_path in attached_images:
            cmd.extend(["--image", str(image_path)])
        cmd.extend(["--model", model, prompt])
        with START_LOCK:
            wait_for_codex_capacity(process_user, max_codex_processes, poll_seconds, figure)
            process = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
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
        deadline = time.monotonic() + timeout
        while open_pipes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                raise TimeoutError(f"codex panel split timed out after {timeout}s for {figure}")
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
            if name == "stdout":
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"type": "raw_stdout", "text": line}
                events.append(event)
                if stream_events:
                    print(f"[{figure}] {json.dumps(event, ensure_ascii=False)}", flush=True)
        try:
            return_code = process.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            raise TimeoutError(f"codex panel split did not exit cleanly after completion for {figure}") from exc
        stderr = "".join(stderr_lines)

        final_text = last_message.read_text(encoding="utf-8").strip() if last_message.exists() else ""
        if return_code != 0:
            event_summary = "\n".join(json.dumps(e, ensure_ascii=False) for e in events[-5:])
            raise RuntimeError(
                f"codex panel split failed for {figure} with exit code {return_code}\n"
                f"stderr:\n{stderr}\nlast events:\n{event_summary}"
            )
        return final_text


RETRYABLE_CODEX_ERROR_MARKERS = (
    "502 bad gateway",
    "upstream request failed",
    "reconnecting...",
    "reconnecting",
    "unexpected status 502",
    "timed out",
    "timeout",
    "thread not found",
    "session not found",
)


def is_retryable_codex_error(exc: BaseException) -> bool:
    message = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in message for marker in RETRYABLE_CODEX_ERROR_MARKERS)


def cleanup_codex_figure_outputs(
    panel_dir: Path,
    review_dir: Path,
    spec_dir: Path,
    figure_index: int,
    *,
    preserve_names: set[str] | None = None,
) -> None:
    prefix = f"fig{figure_index:02d}_"
    preserve_names = preserve_names or set()
    for directory in (panel_dir, review_dir, spec_dir):
        if not directory.exists():
            continue
        for path in directory.glob(f"{prefix}*"):
            if path.name in preserve_names:
                continue
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)


def sleep_before_retry(base_seconds: float, attempt: int, figure: str) -> None:
    delay = max(1.0, base_seconds * attempt)
    print(f"[{figure}] retrying after {delay:.0f}s", flush=True)
    time.sleep(delay)


def parse_json_response(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    else:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError(f"no JSON object found in Codex response: {text[:500]}")
        text = match.group(0)
    return json.loads(text)


def safe_label(label: object, ordinal: int) -> str:
    value = str(label or "").strip().lower()
    if re.fullmatch(r"[a-z]", value):
        return value
    if re.fullmatch(r"panel\d{1,3}", value):
        return value
    return f"panel{ordinal:02d}"


def panel_output_name(figure_index: int, panel_label: str, ordinal: int) -> str:
    suffix = panel_label if panel_label else f"panel{ordinal:02d}"
    return f"fig{figure_index:02d}_{suffix}"


def strict_bbox(raw_bbox: object, width: int, height: int) -> list[int] | None:
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None
    try:
        x0, y0, x1, y1 = [int(round(float(value))) for value in raw_bbox]
    except (TypeError, ValueError):
        return None
    if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
        return None
    if x1 - x0 < 20 or y1 - y0 < 20:
        return None
    return [x0, y0, x1, y1]


def spec_path_value(data: dict, key: str, fallback: Path) -> Path:
    value = str(data.get(key) or "").strip()
    return resolve_path(value) if value else fallback


def panel_path_value(item: dict, key: str, fallback: Path) -> Path:
    value = str(item.get(key) or "").strip()
    return resolve_path(value) if value else fallback


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def load_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def finished_dir_for(panels_dir: Path, value: str | None) -> Path:
    if value:
        return resolve_path(value)
    return panels_dir.parent / DEFAULT_FINISHED_DIR_NAME


def load_finished_panel_rows(finished_dir: Path) -> list[dict]:
    csv_path = finished_dir / "panels.csv"
    json_path = finished_dir / "panels.json"
    if csv_path.exists():
        return read_csv(csv_path)
    return load_json_list(json_path)


def load_finished_figure_records(finished_dir: Path) -> list[dict]:
    csv_path = finished_dir / "finished_figures.csv"
    json_path = finished_dir / "finished_figures.json"
    records = read_csv(csv_path) if csv_path.exists() else load_json_list(json_path)
    if records:
        return records
    fallback: list[dict] = []
    for spec_path in sorted((finished_dir / "_specs").glob("*/fig*_final_spec.json")):
        paper_id = spec_path.parent.name
        match = re.match(r"fig(\d+)_final_spec\.json$", spec_path.name)
        if not match:
            continue
        fallback.append(
            {
                "figure_id": f"{paper_id}__fig{int(match.group(1)):02d}",
                "paper_id": paper_id,
                "figure_index": int(match.group(1)),
                "finished_spec_path": rel(spec_path),
            }
        )
    return fallback


def load_finished_figure_ids(finished_dir: Path) -> set[str]:
    figure_ids: set[str] = set()
    for row in load_finished_figure_records(finished_dir):
        figure = str(row.get("figure_id") or "").strip()
        if figure:
            figure_ids.add(figure)
    return figure_ids


def restore_finished_panel_files(finished_dir: Path, panels_dir: Path) -> int:
    if not finished_dir.exists():
        return 0
    copied = 0
    for paper_dir in sorted(path for path in finished_dir.iterdir() if path.is_dir() and not path.name.startswith("_")):
        target_dir = panels_dir / paper_dir.name
        target_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted(paper_dir.iterdir()):
            if not src.is_file() or src.suffix.lower() not in {".png", ".pdf"}:
                continue
            dst = target_dir / src.name
            if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                shutil.copy2(src, dst)
                copied += 1
    return copied


def resolve_final_spec_path(response: dict, fallback: Path) -> Path:
    candidate = spec_path_value(response, "final_spec_path", fallback)
    if candidate.exists():
        return candidate
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"Codex response did not create final spec: {candidate}")


def panel_rows_from_code_loop_spec(
    row: dict,
    data: dict,
    *,
    spec_path: Path,
    panel_dir: Path,
    review_dir: Path,
    width: int,
    height: int,
    min_review_rounds: int,
) -> tuple[list[dict], list[PanelSpec]]:
    raw_panels = data.get("panels")
    if not isinstance(raw_panels, list) or not raw_panels:
        raise ValueError(f"final spec has no panels: {spec_path}")

    figure_index = int(row["figure_index"])
    overlay_path = spec_path_value(data, "overlay_path", review_dir / f"fig{figure_index:02d}_codex_review.png")
    split_script_path = spec_path_value(data, "split_script_path", spec_path.parent / f"fig{figure_index:02d}_split_figure.py")
    crop_sheet_path = spec_path_value(data, "crop_sheet_path", spec_path.parent / f"fig{figure_index:02d}_final_crops.png")
    review_notes_path = spec_path_value(data, "review_notes_path", spec_path.parent / f"fig{figure_index:02d}_review_notes.md")
    _, caption_by_label = expected_labels(row)

    if not data.get("all_review_passed", False):
        raise ValueError(f"Codex review did not pass for {spec_path}")
    try:
        review_rounds = int(data.get("review_rounds", 0) or 0)
    except (TypeError, ValueError):
        review_rounds = 0
    if review_rounds < min_review_rounds:
        raise ValueError(f"Codex review_rounds={review_rounds}, expected at least {min_review_rounds}: {spec_path}")
    review_history = data.get("review_history")
    if not isinstance(review_history, list) or len(review_history) < min_review_rounds:
        raise ValueError(f"Codex review_history is missing or too short in {spec_path}")
    for required_path, description in [
        (split_script_path, "split script"),
        (review_notes_path, "review notes"),
        (crop_sheet_path, "crop sheet"),
        (overlay_path, "overlay review image"),
    ]:
        if not required_path.exists():
            raise FileNotFoundError(f"missing Codex-generated {description}: {required_path}")

    rows: list[dict] = []
    specs: list[PanelSpec] = []
    seen: set[str] = set()
    for ordinal, item in enumerate(raw_panels, start=1):
        if not isinstance(item, dict):
            continue
        label = safe_label(item.get("label"), ordinal)
        if label in seen:
            label = f"panel{ordinal:02d}"
        seen.add(label)
        bbox = strict_bbox(item.get("bbox_xyxy"), width, height)
        if bbox is None:
            raise ValueError(f"invalid bbox for panel {label} in {spec_path}: {item.get('bbox_xyxy')}")
        stem = panel_output_name(figure_index, label, ordinal)
        png_path = panel_path_value(item, "relative_path", panel_dir / f"{stem}.png")
        pdf_path = panel_path_value(item, "panel_pdf_path", panel_dir / f"{stem}.pdf")
        if not png_path.exists():
            fallback_png = panel_dir / f"{stem}.png"
            if fallback_png.exists():
                png_path = fallback_png
            else:
                raise FileNotFoundError(f"missing Codex-generated panel PNG for {label}: {png_path}")
        if not pdf_path.exists():
            fallback_pdf = panel_dir / f"{stem}.pdf"
            if fallback_pdf.exists():
                pdf_path = fallback_pdf
            else:
                # The crop itself must be produced by the Codex-written script.
                # Converting the already generated panel image keeps downstream
                # consumers working without changing crop boundaries.
                image_to_pdf(png_path, pdf_path)
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = round(max(0.0, min(1.0, confidence)), 4)
        reason = str(item.get("reason", ""))[:500]
        specs.append(PanelSpec(label=label, bbox=bbox, confidence=confidence, reason=reason))
        rows.append(
            {
                "paper_id": row["paper_id"],
                "doi": row.get("doi", ""),
                "pmcid": row.get("pmcid", ""),
                "journal": row.get("journal", ""),
                "publication_date": row.get("publication_date", ""),
                "figure_label": row.get("figure_label", ""),
                "figure_index": row.get("figure_index", ""),
                "panel_label": label,
                "panel_ordinal": ordinal,
                "relative_path": rel(png_path),
                "panel_pdf_path": rel(pdf_path),
                "source_figure_path": row.get("relative_path", ""),
                "source_figure_pdf_path": row.get("figure_pdf_path", ""),
                "source_figure_url": row.get("source_url", ""),
                "review_path": rel(overlay_path),
                "bbox_xyxy": json.dumps(bbox),
                "split_method": "codex_code_loop",
                "codex_confidence": confidence,
                "assigned_subplots": "",
                "panel_caption": caption_by_label.get(label, row.get("caption", "")),
                "figure_caption": row.get("caption", ""),
                "split_reason": reason,
                "review_passed": bool(item.get("review_passed", data.get("all_review_passed", False))),
                "edge_check": str(item.get("edge_check", "")),
                "split_script_path": rel(split_script_path),
                "final_spec_path": rel(spec_path),
                "crop_sheet_path": rel(crop_sheet_path),
                "review_notes_path": rel(review_notes_path),
            }
        )
    if not rows:
        raise ValueError(f"final spec has no valid panel rows: {spec_path}")
    return rows, specs


def limit_rows_by_papers(rows: list[dict], paper_limit: int) -> list[dict]:
    if paper_limit <= 0:
        return rows
    selected: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        paper_id = row.get("paper_id", "")
        if paper_id not in seen:
            if len(seen) >= paper_limit:
                break
            seen.add(paper_id)
        selected.append(row)
    return selected


def process_figure(index: int, row: dict, args: argparse.Namespace) -> tuple[int, dict, list[dict]]:
    image_path = resolve_path(row["relative_path"])
    labels, _ = expected_labels(row)
    with Image.open(image_path) as opened:
        image = white_background(opened)
    figure = figure_id(row)
    figure_index = int(row["figure_index"])
    panels_dir = resolve_path(args.panels_dir)
    reviews_dir = resolve_path(args.reviews_dir)
    specs_dir = resolve_path(args.specs_dir)
    panel_dir = panels_dir / row["paper_id"]
    review_dir = reviews_dir / row["paper_id"]
    spec_dir = specs_dir / row["paper_id"]
    panel_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)
    final_spec_path = spec_dir / f"fig{figure_index:02d}_final_spec.json"
    prompt = build_prompt(row, image_path, image.width, image.height, labels, args.review_rounds, panel_dir, review_dir, spec_dir)
    prompt_path = spec_dir / f"fig{figure_index:02d}_prompt.md"
    raw_path = spec_dir / f"fig{figure_index:02d}_raw_response.txt"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")

    if args.dry_run:
        status = {
            "figure_id": figure,
            "paper_id": row.get("paper_id", ""),
            "figure_index": row.get("figure_index", ""),
            "source_figure_path": row.get("relative_path", ""),
            "panel_count": 0,
            "expected_labels": ",".join(labels),
            "spec_path": rel(final_spec_path),
            "prompt_path": rel(prompt_path),
            "raw_response_path": "",
            "status": "dry_run",
        }
        print(f"[{index}] {figure} dry-run prompt={prompt_path}", flush=True)
        return index, status, []

    data: dict | None = None
    spec_path = final_spec_path
    if args.skip_existing and final_spec_path.exists():
        try:
            data = load_json(final_spec_path)
            panel_rows, specs = panel_rows_from_code_loop_spec(
                row,
                data,
                spec_path=final_spec_path,
                panel_dir=panel_dir,
                review_dir=review_dir,
                width=image.width,
                height=image.height,
                min_review_rounds=args.review_rounds,
            )
        except Exception as exc:
            print(f"[{index}] {figure} existing Codex split incomplete; rerunning ({exc})", flush=True)
            data = None

    if data is None:
        max_attempts = max(1, args.codex_retries)
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                cleanup_codex_figure_outputs(
                    panel_dir,
                    review_dir,
                    spec_dir,
                    figure_index,
                    preserve_names={prompt_path.name},
                )
                sleep_before_retry(args.codex_retry_sleep, attempt - 1, figure)
            try:
                print(f"[{index}] {figure} codex attempt {attempt}/{max_attempts}", flush=True)
                raw = run_codex_json(
                    prompt,
                    image_path,
                    figure=figure,
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                    process_user=args.process_user,
                    max_codex_processes=args.max_codex_processes,
                    poll_seconds=args.poll_seconds,
                    timeout=args.timeout,
                    stream_events=args.stream_events,
                    schema=code_loop_output_schema(),
                    sandbox="workspace-write",
                )
                raw_path.write_text(raw + "\n", encoding="utf-8")
                response = parse_json_response(raw)
                spec_path = resolve_final_spec_path(response, final_spec_path)
                data = load_json(spec_path)
                panel_rows, specs = panel_rows_from_code_loop_spec(
                    row,
                    data,
                    spec_path=spec_path,
                    panel_dir=panel_dir,
                    review_dir=review_dir,
                    width=image.width,
                    height=image.height,
                    min_review_rounds=args.review_rounds,
                )
                break
            except Exception as exc:
                if attempt >= max_attempts or not is_retryable_codex_error(exc):
                    raise
                print(
                    f"[{index}] {figure} transient Codex failure on attempt "
                    f"{attempt}/{max_attempts}: {type(exc).__name__}: {exc}",
                    flush=True,
                )
        if data is None:
            raise RuntimeError(f"Codex retry loop ended without data for {figure}")

    try:
        review_rounds = int(data.get("review_rounds", args.review_rounds) or 0)
    except (TypeError, ValueError):
        review_rounds = args.review_rounds
    review_passed = bool(data.get("all_review_passed", False))
    review_notes_path = spec_path_value(data, "review_notes_path", spec_dir / f"fig{figure_index:02d}_review_notes.md")
    review_notes = ""
    if review_notes_path.exists():
        review_notes = review_notes_path.read_text(encoding="utf-8", errors="replace")[:2000]
    if not review_notes:
        review_notes = str(data.get("notes", data.get("review_summary", "")))[:2000]
    status = {
        "figure_id": figure,
        "paper_id": row.get("paper_id", ""),
        "figure_index": row.get("figure_index", ""),
        "source_figure_path": row.get("relative_path", ""),
        "panel_count": len(panel_rows),
        "expected_labels": ",".join(labels),
        "spec_path": rel(spec_path),
        "prompt_path": rel(prompt_path),
        "raw_response_path": rel(raw_path) if raw_path.exists() else "",
        "status": "dry_run" if args.dry_run else "ok",
        "review_passed": review_passed,
        "review_rounds": review_rounds,
        "review_notes": review_notes,
        "split_method": "codex_code_loop",
        "split_script_path": rel(spec_path_value(data, "split_script_path", spec_dir / f"fig{figure_index:02d}_split_figure.py")),
        "crop_sheet_path": rel(spec_path_value(data, "crop_sheet_path", spec_dir / f"fig{figure_index:02d}_final_crops.png")),
        "overlay_path": rel(spec_path_value(data, "overlay_path", review_dir / f"fig{figure_index:02d}_codex_review.png")),
    }
    print(f"[{index}] {figure} panels={len(panel_rows)} labels={','.join(spec.label for spec in specs)}", flush=True)
    return index, status, panel_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split panels with a per-figure Codex code/review loop.")
    parser.add_argument("--full-figures-csv", default=str(DEFAULT_FULL_FIGURES_CSV.relative_to(BASE_DIR)))
    parser.add_argument("--panels-dir", default=str(DEFAULT_PANELS_DIR.relative_to(BASE_DIR)))
    parser.add_argument("--reviews-dir", default=str(DEFAULT_REVIEWS_DIR.relative_to(BASE_DIR)))
    parser.add_argument("--specs-dir", default=str(DEFAULT_SPECS_DIR.relative_to(BASE_DIR)))
    parser.add_argument("--finished-dir", default="")
    parser.add_argument("--model", default=os.environ.get("CODEX_MODEL", "gpt-5.4"))
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--max-codex-processes", type=int, default=16)
    parser.add_argument("--process-user", default=os.environ.get("USER", "unknown"))
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--codex-retries", type=int, default=5)
    parser.add_argument("--codex-retry-sleep", type=float, default=60.0)
    parser.add_argument(
        "--review-rounds",
        type=int,
        default=4,
        help="Internal split-agent/review-agent audit passes requested inside each per-figure Codex session.",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--limit-papers", type=int, default=0, help="Limit to the first N unique paper_id values in the figures CSV.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--stream-events", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.jobs < 1:
        raise SystemExit("--jobs must be >= 1")
    if args.max_codex_processes < 1:
        raise SystemExit("--max-codex-processes must be >= 1")
    if args.codex_retries < 1:
        raise SystemExit("--codex-retries must be >= 1")
    if args.codex_retry_sleep < 0:
        raise SystemExit("--codex-retry-sleep must be >= 0")
    if args.review_rounds < 0:
        raise SystemExit("--review-rounds must be >= 0")
    if args.limit_papers < 0:
        raise SystemExit("--limit-papers must be >= 0")

    figures_csv = resolve_path(args.full_figures_csv)
    if not figures_csv.exists():
        raise SystemExit(f"missing full figures CSV: {figures_csv}")
    panels_dir = resolve_path(args.panels_dir)
    reviews_dir = resolve_path(args.reviews_dir)
    specs_dir = resolve_path(args.specs_dir)
    finished_dir = finished_dir_for(panels_dir, args.finished_dir)
    if args.overwrite:
        shutil.rmtree(panels_dir, ignore_errors=True)
        shutil.rmtree(reviews_dir, ignore_errors=True)
        shutil.rmtree(specs_dir, ignore_errors=True)
    panels_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    specs_dir.mkdir(parents=True, exist_ok=True)
    finished_figure_ids = load_finished_figure_ids(finished_dir)
    finished_panel_rows = load_finished_panel_rows(finished_dir)
    finished_status_rows = []
    for row in load_finished_figure_records(finished_dir):
        try:
            figure_index = int(row.get("figure_index") or 0)
        except (TypeError, ValueError):
            figure_index = 0
        finished_status_rows.append(
            {
                "figure_id": row.get("figure_id", ""),
                "paper_id": row.get("paper_id", ""),
                "figure_index": row.get("figure_index", ""),
                "panel_count": row.get("panel_count", ""),
                "status": "finished_cache",
                "review_passed": True,
                "review_rounds": row.get("review_rounds", ""),
                "finished_spec_path": row.get("finished_spec_path", ""),
            }
        )

    figure_rows = read_csv(figures_csv)
    if args.limit_papers:
        figure_rows = limit_rows_by_papers(figure_rows, args.limit_papers)
    if args.limit:
        figure_rows = figure_rows[: args.limit]
    if finished_figure_ids:
        before = len(figure_rows)
        figure_rows = [row for row in figure_rows if figure_id(row) not in finished_figure_ids]
        print(
            f"Finished cache: skipped {before - len(figure_rows)} figures from {rel(finished_dir) if finished_dir.exists() else finished_dir}",
            flush=True,
        )
    print(f"Codex panel split figures: {len(figure_rows)}", flush=True)

    statuses: list[dict] = list(finished_status_rows)
    panel_rows: list[dict] = list(finished_panel_rows)
    failures = 0
    max_workers = min(args.jobs, len(figure_rows), args.max_codex_processes) if figure_rows else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(process_figure, index, row, args): index
            for index, row in enumerate(figure_rows, start=1)
        }
        results: list[tuple[int, dict, list[dict]]] = []
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results.append(future.result())
            except Exception as exc:
                failures += 1
                print(f"\nFAILED figure index {index}: {exc}", file=sys.stderr, flush=True)
                print(traceback.format_exc(), file=sys.stderr, flush=True)
        for _, status, rows in sorted(results, key=lambda item: item[0]):
            statuses.append(status)
            panel_rows.extend(rows)

    write_csv(panels_dir / "panels.csv", panel_rows)
    (panels_dir / "panels.json").write_text(json.dumps(panel_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(specs_dir / "status.csv", statuses)
    (specs_dir / "status.json").write_text(json.dumps(statuses, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "figures": len(figure_rows),
                "panels": len(panel_rows),
                "failures": failures,
                "panels_csv": rel(panels_dir / "panels.csv"),
                "status_csv": rel(specs_dir / "status.csv"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
