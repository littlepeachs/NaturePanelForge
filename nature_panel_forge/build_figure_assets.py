#!/usr/bin/env python3
"""Build full-size figure assets, PDFs, panel crops, and panel metadata.

Inputs:
  Papers/papers.json created by download_nature_oa_figures.py

Outputs:
  FullFigures/<paper_id>/figNN.<ext>
  FigurePDFs/<paper_id>/figNN.pdf
  Panels/<paper_id>/figNN_<panel>.png
  Panels/<paper_id>/figNN_<panel>.pdf
  Panels/panels.csv and Panels/panels.json
"""

from __future__ import annotations

import csv
import concurrent.futures
import io
import json
import math
import os
import re
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from scipy import ndimage


BASE_DIR = Path(__file__).resolve().parents[1]
PAPERS_JSON = BASE_DIR / os.environ.get("PAPERS_JSON", "Papers/papers.json")
FULL_FIGURES_DIR = BASE_DIR / os.environ.get("FULL_FIGURES_DIR", "FullFigures")
FIGURE_PDFS_DIR = BASE_DIR / os.environ.get("FIGURE_PDFS_DIR", "FigurePDFs")
PANELS_DIR = BASE_DIR / os.environ.get("PANELS_DIR", "Panels")
PANEL_REVIEWS_DIR = BASE_DIR / os.environ.get("PANEL_REVIEWS_DIR", "PanelReviews")
USER_AGENT = "Mozilla/5.0 SciFigureHub/1.0"
NATURE_MEDIA_BASE = "https://media.springernature.com/full"
MAX_SEGMENT_DIM = 1400
MIN_PANEL_AREA_FRAC = 0.002
FIGPANEL_DEPS_DIR = BASE_DIR / os.environ.get("FIGPANEL_DEPS_DIR", ".deps/figpanel_min")
FIGPANEL_CONF = 0.15
FIGPANEL_IOU = 0.5
SKIP_PANEL_SPLIT = os.environ.get("BUILD_FIGURE_ASSETS_SKIP_PANEL_SPLIT", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
}
BUILD_WORKERS = max(1, int(os.environ.get("BUILD_FIGURE_ASSETS_WORKERS", "1")))
BUILD_BATCH_SIZE = max(1, int(os.environ.get("BUILD_FIGURE_ASSETS_BATCH_SIZE", str(BUILD_WORKERS))))
BUILD_BATCH_SLEEP = max(0.0, float(os.environ.get("BUILD_FIGURE_ASSETS_BATCH_SLEEP", "1.0")))


@dataclass
class Box:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return max(0, self.x1 - self.x0)

    @property
    def height(self) -> int:
        return max(0, self.y1 - self.y0)

    @property
    def area(self) -> int:
        return self.width * self.height

    def as_list(self) -> list[int]:
        return [self.x0, self.y0, self.x1, self.y1]

    def expand(self, margin: int, width: int, height: int) -> "Box":
        return Box(
            max(0, self.x0 - margin),
            max(0, self.y0 - margin),
            min(width, self.x1 + margin),
            min(height, self.y1 + margin),
        )


def http_get(url: str, timeout: int = 60) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def rel(path: Path) -> str:
    return str(path.relative_to(BASE_DIR))


def figure_stem(figure: dict) -> str:
    original = figure.get("original_member") or figure.get("output_file", "")
    return Path(original).stem


def nature_media_urls(doi: str, stem: str) -> Iterable[str]:
    encoded_doi = urllib.parse.quote(doi, safe="")
    encoded_article = f"art%3A{encoded_doi}"
    for ext in (".png", ".jpg", ".jpeg"):
        yield f"{NATURE_MEDIA_BASE}/springer-static/image/{encoded_article}/MediaObjects/{stem}{ext}"


def image_extension(content_type: str, fallback_url: str) -> str:
    content_type = content_type.lower()
    if "png" in content_type:
        return ".png"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    suffix = Path(urllib.parse.urlparse(fallback_url).path).suffix.lower()
    return suffix if suffix in {".png", ".jpg", ".jpeg"} else ".png"


def download_full_figure(paper: dict, figure: dict, out_dir: Path) -> tuple[Path, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = figure_stem(figure)
    figure_index = int(figure["index"])
    last_error: Exception | None = None

    urls = list(nature_media_urls(paper["doi"], stem))
    for url in urls:
        suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
        cached = out_dir / f"fig{figure_index:02d}{suffix}"
        if cached.exists():
            try:
                with Image.open(cached) as img:
                    img.verify()
                return cached, url
            except OSError:
                cached.unlink(missing_ok=True)

    for url in urls:
        try:
            data, content_type = http_get(url)
            if not content_type.lower().startswith("image/"):
                continue
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
            ext = image_extension(content_type, url)
            out_path = out_dir / f"fig{figure_index:02d}{ext}"
            out_path.write_bytes(data)
            return out_path, url
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc

    local_fallback = BASE_DIR / figure["output_file"]
    if local_fallback.exists():
        fallback_path = out_dir / f"fig{figure_index:02d}{local_fallback.suffix.lower()}"
        fallback_path.write_bytes(local_fallback.read_bytes())
        return fallback_path, rel(local_fallback)

    raise RuntimeError(f"could not download full figure for {paper['doi']} {stem}: {last_error}")


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


def normalize_caption(caption: str) -> str:
    return " ".join(caption.replace("\u2013", "-").replace("\u2014", "-").split())


def expand_label_range(start: str, end: str | None) -> list[str]:
    if not end:
        return [start]
    a, b = ord(start), ord(end)
    if not (97 <= a <= b <= 122) or b - a > 25:
        return [start]
    return [chr(code) for code in range(a, b + 1)]


PANEL_MARK_RE = re.compile(
    r"(?:(?<=^)|(?<=[.;]))\s*([a-z])\s*(?:[-–—]\s*([a-z]))?\s*(?:[,.)]\s*)?(?=[A-Z0-9(])"
)


def panel_caption_map(caption: str) -> tuple[list[str], dict[str, str]]:
    text = normalize_caption(caption)
    matches = list(PANEL_MARK_RE.finditer(text))
    labels: list[str] = []
    mapping: dict[str, str] = {}

    for index, match in enumerate(matches):
        start, end = match.group(1), match.group(2)
        expanded = expand_label_range(start, end)
        segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segment = text[match.start() : segment_end].strip()
        for label in expanded:
            if label not in labels:
                labels.append(label)
            mapping[label] = segment

    return labels, mapping


def figure_mask(image: Image.Image) -> np.ndarray:
    arr = np.asarray(white_background(image))
    # Keep both dark ink and colored objects, but ignore almost-white background.
    white = (arr[:, :, 0] > 245) & (arr[:, :, 1] > 245) & (arr[:, :, 2] > 245)
    return ~white


def content_bbox(mask: np.ndarray, width: int, height: int) -> Box:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return Box(0, 0, width, height)
    margin = max(4, int(min(width, height) * 0.006))
    return Box(
        max(0, int(xs.min()) - margin),
        max(0, int(ys.min()) - margin),
        min(width, int(xs.max()) + 1 + margin),
        min(height, int(ys.max()) + 1 + margin),
    )


def scale_for_segmentation(width: int, height: int) -> float:
    longest = max(width, height)
    return min(1.0, MAX_SEGMENT_DIM / float(longest))


def connected_boxes(mask: np.ndarray, iterations: int) -> list[Box]:
    total_area = mask.shape[0] * mask.shape[1]
    dilated = ndimage.binary_dilation(mask, structure=np.ones((3, 3)), iterations=iterations)
    labeled, _ = ndimage.label(dilated)
    objects = ndimage.find_objects(labeled)
    boxes: list[Box] = []

    for obj in objects:
        if obj is None:
            continue
        y_slice, x_slice = obj
        box = Box(x_slice.start, y_slice.start, x_slice.stop, y_slice.stop)
        if box.area < total_area * MIN_PANEL_AREA_FRAC:
            continue
        if box.width < 20 or box.height < 20:
            continue
        boxes.append(box)
    return sorted(boxes, key=lambda box: (box.y0, box.x0))


def box_distance(a: Box, b: Box) -> float:
    dx = max(0, max(a.x0, b.x0) - min(a.x1, b.x1))
    dy = max(0, max(a.y0, b.y0) - min(a.y1, b.y1))
    overlap_x = max(0, min(a.x1, b.x1) - max(a.x0, b.x0))
    overlap_y = max(0, min(a.y1, b.y1) - max(a.y0, b.y0))
    overlap_bonus = 0.25 * (overlap_x + overlap_y)
    return math.hypot(dx, dy) - overlap_bonus


def merge_pair(boxes: list[Box]) -> list[Box]:
    if len(boxes) <= 1:
        return boxes
    best_pair: tuple[int, int] | None = None
    best_distance = float("inf")
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            distance = box_distance(boxes[i], boxes[j])
            if distance < best_distance:
                best_distance = distance
                best_pair = (i, j)

    if best_pair is None:
        return boxes

    i, j = best_pair
    merged = Box(
        min(boxes[i].x0, boxes[j].x0),
        min(boxes[i].y0, boxes[j].y0),
        max(boxes[i].x1, boxes[j].x1),
        max(boxes[i].y1, boxes[j].y1),
    )
    new_boxes = [box for k, box in enumerate(boxes) if k not in {i, j}]
    new_boxes.append(merged)
    return sorted(new_boxes, key=lambda box: (box.y0, box.x0))


def score_boxes(boxes: list[Box], target_count: int, width: int, height: int) -> float:
    if not boxes:
        return float("inf")
    count_penalty = abs(len(boxes) - target_count) / max(1, target_count)
    areas = np.array([box.area for box in boxes], dtype=float)
    area_cv = float(areas.std() / max(1.0, areas.mean()))
    huge_penalty = sum(1 for box in boxes if box.area > width * height * 0.65)
    min_width = max(70, int(width * 0.04))
    min_height = max(70, int(height * 0.04))
    tiny_penalty = sum(1 for box in boxes if box.width < min_width or box.height < min_height)
    return count_penalty * 2.0 + area_cv * 0.15 + huge_penalty * 0.5 + tiny_penalty * 1.5


def boxes_are_reasonable(boxes: list[Box], target_count: int, width: int, height: int) -> bool:
    if not boxes:
        return False
    if target_count > 1 and len(boxes) != target_count:
        return False
    min_width = max(70, int(width * 0.04))
    min_height = max(70, int(height * 0.04))
    for box in boxes:
        if box.width < min_width or box.height < min_height:
            return False
        if box.width / max(1, box.height) > 12 or box.height / max(1, box.width) > 12:
            return False
    return True


def grid_boxes(mask: np.ndarray, target_count: int) -> list[Box]:
    height, width = mask.shape
    outer = content_bbox(mask, width, height)
    best: tuple[float, int, int] | None = None
    for rows in range(1, min(target_count, 6) + 1):
        cols = math.ceil(target_count / rows)
        if cols > 8:
            continue
        cell_aspect = (outer.width / cols) / max(1, outer.height / rows)
        score = abs(rows * cols - target_count) + 0.2 * abs(math.log(max(cell_aspect, 0.05)))
        if best is None or score < best[0]:
            best = (score, rows, cols)

    if best is None:
        return [outer]

    _, rows, cols = best
    boxes: list[Box] = []
    for row in range(rows):
        for col in range(cols):
            x0 = outer.x0 + round(outer.width * col / cols)
            x1 = outer.x0 + round(outer.width * (col + 1) / cols)
            y0 = outer.y0 + round(outer.height * row / rows)
            y1 = outer.y0 + round(outer.height * (row + 1) / rows)
            boxes.append(Box(x0, y0, x1, y1))
    return boxes[:target_count] if boxes else [outer]


def detect_panel_boxes(image: Image.Image, target_count: int) -> tuple[list[Box], str]:
    width, height = image.size
    if target_count <= 1:
        return [Box(0, 0, width, height)], "whole_figure"

    scale = scale_for_segmentation(width, height)
    seg_image = image
    if scale < 1.0:
        seg_image = image.resize((round(width * scale), round(height * scale)), Image.Resampling.LANCZOS)
    mask = figure_mask(seg_image)
    seg_h, seg_w = mask.shape

    candidates: list[tuple[float, list[Box], str]] = []
    for iterations in (3, 5, 8, 12, 16, 24):
        boxes = connected_boxes(mask, iterations)
        if not boxes:
            continue
        while len(boxes) > target_count:
            boxes = merge_pair(boxes)
        candidates.append((score_boxes(boxes, target_count, seg_w, seg_h), boxes, f"connected_dilation_{iterations}"))

    if candidates:
        score, boxes, method = sorted(candidates, key=lambda item: item[0])[0]
        if boxes_are_reasonable(boxes, target_count, seg_w, seg_h) and score < 1.8:
            return scale_boxes(boxes, scale, width, height), method

    boxes = grid_boxes(mask, target_count)
    return scale_boxes(boxes, scale, width, height), "grid_fallback"


def scale_boxes(boxes: list[Box], scale: float, width: int, height: int) -> list[Box]:
    margin = max(8, int(min(width, height) * 0.012))
    scaled: list[Box] = []
    for box in boxes:
        if scale < 1.0:
            scaled_box = Box(
                int(box.x0 / scale),
                int(box.y0 / scale),
                int(math.ceil(box.x1 / scale)),
                int(math.ceil(box.y1 / scale)),
            )
        else:
            scaled_box = box
        scaled.append(scaled_box.expand(margin, width, height))
    return sorted(scaled, key=lambda item: (item.y0, item.x0))


DATA_KEYWORDS = {
    "mean",
    "s.d",
    "sd",
    "sem",
    "p-value",
    "p values",
    "n =",
    "box",
    "plot",
    "rate",
    "ratio",
    "quantification",
    "quantified",
    "expression",
    "levels",
    "curve",
    "histogram",
    "violin",
    "bar",
    "scatter",
    "heatmap",
    "volcano",
    "umap",
    "pca",
    "spectrum",
    "spectra",
    "counts",
    "percentage",
    "correlation",
    "distribution",
}
SCHEMATIC_KEYWORDS = {
    "schematic",
    "diagram",
    "workflow",
    "model",
    "illustration",
    "cartoon",
    "overview",
    "pipeline",
    "architecture",
    "design",
    "mechanism",
    "scheme",
}
IMAGE_KEYWORDS = {
    "representative image",
    "representative images",
    "microscopy",
    "micrograph",
    "photograph",
    "confocal",
    "scale bar",
    "tem",
    "sem image",
}


def keyword_score(text: str, keywords: set[str]) -> int:
    lowered = text.lower()
    return sum(1 for keyword in keywords if keyword in lowered)


def axis_score(image: Image.Image) -> float:
    arr = np.asarray(white_background(image).resize((min(500, image.width), min(500, image.height))))
    black = (arr[:, :, 0] < 90) & (arr[:, :, 1] < 90) & (arr[:, :, 2] < 90)
    row_score = np.count_nonzero(black.mean(axis=1) > 0.16)
    col_score = np.count_nonzero(black.mean(axis=0) > 0.16)
    return min(3.0, (row_score + col_score) / 8.0)


def image_texture_score(image: Image.Image) -> float:
    gray = np.asarray(white_background(image).convert("L").resize((180, 180)), dtype=float)
    gx = np.abs(np.diff(gray, axis=1)).mean()
    gy = np.abs(np.diff(gray, axis=0)).mean()
    return float((gx + gy) / 2.0)


def classify_panel(image: Image.Image, caption: str) -> tuple[str, float, str]:
    data = keyword_score(caption, DATA_KEYWORDS)
    schematic = keyword_score(caption, SCHEMATIC_KEYWORDS)
    image_like = keyword_score(caption, IMAGE_KEYWORDS)
    axes = axis_score(image)
    texture = image_texture_score(image)

    data_score = data * 1.4 + axes
    schematic_score = schematic * 1.6
    image_score = image_like * 1.5 + (1.0 if texture > 18 else 0.0)

    scores = {
        "data_statistical": data_score,
        "schematic": schematic_score,
        "microscopy_or_photo": image_score,
        "other_or_mixed": 0.8,
    }
    category = max(scores, key=scores.get)
    ordered = sorted(scores.values(), reverse=True)
    confidence = max(0.2, min(0.95, (ordered[0] - ordered[1] + 1.0) / 4.0))
    reason = f"keywords(data={data}, schematic={schematic}, image={image_like}); axes={axes:.2f}; texture={texture:.2f}"
    return category, confidence, reason


def panel_output_name(figure_index: int, panel_label: str, ordinal: int) -> str:
    suffix = panel_label if panel_label else f"panel{ordinal:02d}"
    return f"fig{figure_index:02d}_{suffix}"


def clear_previous_panel_outputs(panel_dir: Path, figure_index: int) -> None:
    prefix = f"fig{figure_index:02d}_"
    for old_file in panel_dir.glob(f"{prefix}*"):
        if old_file.is_file() and old_file.suffix.lower() in {".png", ".pdf"}:
            old_file.unlink()


def optional_figpanel():
    if not FIGPANEL_DEPS_DIR.exists():
        return None
    dep_path = str(FIGPANEL_DEPS_DIR)
    if dep_path not in sys.path:
        sys.path.insert(0, dep_path)
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HOME", str(BASE_DIR / ".cache" / "huggingface"))
    os.environ.setdefault("YOLO_CONFIG_DIR", str(BASE_DIR / ".cache" / "ultralytics"))
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")
    try:
        import figpanel  # type: ignore
    except Exception:
        return None
    return figpanel


def font_paths() -> list[Path]:
    candidates = [
        "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/croscore/Arimo-Bold.ttf",
    ]
    return [Path(path) for path in candidates if Path(path).exists()]


def normalized_letter_mask(image: Image.Image, size: int = 40) -> np.ndarray | None:
    gray = np.asarray(ImageOps.grayscale(white_background(image)))
    mask = gray < 180
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    crop = Image.fromarray((mask[y0:y1, x0:x1] * 255).astype("uint8"))
    width, height = crop.size
    if width == 0 or height == 0:
        return None
    scale = min((size - 8) / width, (size - 8) / height)
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    crop = crop.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("L", (size, size), 0)
    canvas.paste(crop, ((size - new_size[0]) // 2, (size - new_size[1]) // 2))
    return np.asarray(canvas, dtype=float) / 255.0


_LETTER_TEMPLATES: list[tuple[str, np.ndarray]] | None = None


def letter_templates() -> list[tuple[str, np.ndarray]]:
    global _LETTER_TEMPLATES
    if _LETTER_TEMPLATES is not None:
        return _LETTER_TEMPLATES

    templates: list[tuple[str, np.ndarray]] = []
    for font_path in font_paths():
        for font_size in range(20, 46, 2):
            font = ImageFont.truetype(str(font_path), font_size)
            for letter in string.ascii_lowercase:
                image = Image.new("RGB", (80, 80), "white")
                draw = ImageDraw.Draw(image)
                bbox = draw.textbbox((0, 0), letter, font=font)
                draw.text((20 - bbox[0], 20 - bbox[1]), letter, font=font, fill="black")
                mask = normalized_letter_mask(image)
                if mask is not None:
                    templates.append((letter, mask))
    _LETTER_TEMPLATES = templates
    return templates


def classify_label_crop(crop: Image.Image, allowed_labels: list[str]) -> tuple[str, float] | None:
    mask = normalized_letter_mask(crop)
    if mask is None:
        return None
    allowed = set(allowed_labels)
    best_letter = ""
    best_score = -1.0
    for letter, template in letter_templates():
        if letter not in allowed:
            continue
        intersection = np.minimum(mask, template).sum()
        union = np.maximum(mask, template).sum() + 1e-6
        iou = float(intersection / union)
        mse = float(((mask - template) ** 2).mean())
        score = iou - 0.5 * mse
        if score > best_score:
            best_score = score
            best_letter = letter
    if not best_letter or best_score < 0.45:
        return None
    return best_letter, best_score


def box_center(box: Box) -> tuple[float, float]:
    return (box.x0 + box.x1) / 2.0, (box.y0 + box.y1) / 2.0


def contains_center(outer: Box, inner: Box) -> bool:
    cx, cy = box_center(inner)
    return outer.x0 <= cx <= outer.x1 and outer.y0 <= cy <= outer.y1


def overlap_fraction(a: Box, b: Box) -> float:
    x0, y0 = max(a.x0, b.x0), max(a.y0, b.y0)
    x1, y1 = min(a.x1, b.x1), min(a.y1, b.y1)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    return inter / max(1, min(a.area, b.area))


def dedupe_boxes(boxes: list[tuple[Box, float]], target_count: int) -> list[tuple[Box, float]]:
    selected: list[tuple[Box, float]] = []
    for box, confidence in sorted(boxes, key=lambda item: item[1], reverse=True):
        if any(overlap_fraction(box, existing) > 0.8 for existing, _ in selected):
            continue
        selected.append((box, confidence))
    if len(selected) > target_count:
        selected = selected[:target_count]
    return selected


def nearest_subplot(caption_box: Box, subplots: list[tuple[Box, float]]) -> tuple[Box, float] | None:
    containing = [(box, conf) for box, conf in subplots if contains_center(box, caption_box)]
    if containing:
        return max(containing, key=lambda item: item[1])
    cx, cy = box_center(caption_box)
    best: tuple[float, tuple[Box, float]] | None = None
    for box, conf in subplots:
        sx, sy = box.x0, box.y0
        distance = math.hypot(cx - sx, cy - sy)
        if best is None or distance < best[0]:
            best = (distance, (box, conf))
    return best[1] if best else None


def figpanel_boxes(image_path: Path, image: Image.Image, labels: list[str]) -> tuple[list[Box], str, Path | None]:
    figpanel = optional_figpanel()
    if figpanel is None or len(labels) <= 1:
        return [], "", None

    try:
        detected = figpanel.detect(str(image_path), conf=FIGPANEL_CONF, iou=FIGPANEL_IOU)
    except Exception:
        return [], "", None

    width, height = image.size
    raw_subplots = [
        (Box(int(x0), int(y0), int(x1), int(y1)).expand(5, width, height), float(conf))
        for x0, y0, x1, y1, conf in detected.get("subplots", [])
        if (x1 - x0) * (y1 - y0) > width * height * 0.01
    ]
    subplots = dedupe_boxes(raw_subplots, len(labels))
    if len(subplots) < len(labels):
        return [], "", None

    caption_hits: dict[str, tuple[Box, float]] = {}
    for x0, y0, x1, y1, conf in detected.get("captions", []):
        caption_box = Box(int(x0), int(y0), int(x1), int(y1)).expand(3, width, height)
        crop = image.crop(tuple(caption_box.as_list()))
        classified = classify_label_crop(crop, labels)
        if classified is None:
            continue
        label, score = classified
        combined_score = score * float(conf)
        if label not in caption_hits or combined_score > caption_hits[label][1]:
            caption_hits[label] = (caption_box, combined_score)

    assigned: dict[str, Box] = {}
    used_subplots: set[int] = set()
    for label in labels:
        if label not in caption_hits:
            continue
        nearest = nearest_subplot(caption_hits[label][0], subplots)
        if nearest is None:
            continue
        box, _ = nearest
        idx = next((i for i, (candidate, _) in enumerate(subplots) if candidate == box), None)
        if idx is None or idx in used_subplots:
            continue
        assigned[label] = box
        used_subplots.add(idx)

    remaining_labels = [label for label in labels if label not in assigned]
    remaining_subplots = [box for i, (box, _) in enumerate(subplots) if i not in used_subplots]
    if remaining_labels and len(remaining_labels) == len(remaining_subplots):
        for label, box in zip(remaining_labels, sorted(remaining_subplots, key=lambda item: (item.x0, item.y0))):
            assigned[label] = box

    if len(assigned) != len(labels):
        return [], "", None

    review_path = save_panel_review(image_path, assigned, detected)
    return [assigned[label] for label in labels], "figpanel_detect", review_path


def save_panel_review(image_path: Path, assigned: dict[str, Box], detected: dict) -> Path:
    review_path = PANEL_REVIEWS_DIR / image_path.parent.name / f"{image_path.stem}_review.png"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as opened:
        canvas = white_background(opened)
    draw = ImageDraw.Draw(canvas)
    line_width = max(3, round(min(canvas.size) / 350))
    for label, box in assigned.items():
        draw.rectangle(box.as_list(), outline=(36, 114, 255), width=line_width)
        draw.text((box.x0 + 6, box.y0 + 6), label, fill=(220, 0, 0))
    for x0, y0, x1, y1, _ in detected.get("captions", []):
        draw.rectangle([x0, y0, x1, y1], outline=(35, 160, 70), width=max(2, line_width - 1))
    canvas.save(review_path)
    return review_path


def process_figure(paper: dict, figure: dict) -> tuple[dict, list[dict]]:
    paper_id = paper["paper_id"]
    figure_index = int(figure["index"])

    full_dir = FULL_FIGURES_DIR / paper_id
    pdf_dir = FIGURE_PDFS_DIR / paper_id
    panel_dir = PANELS_DIR / paper_id
    panel_dir.mkdir(parents=True, exist_ok=True)
    clear_previous_panel_outputs(panel_dir, figure_index)

    full_image_path, source_url = download_full_figure(paper, figure, full_dir)
    figure_pdf_path = pdf_dir / f"fig{figure_index:02d}.pdf"
    image_to_pdf(full_image_path, figure_pdf_path)

    caption = figure.get("caption", "")
    labels, caption_by_label = panel_caption_map(caption)
    target_count = len(labels) if labels else 1

    with Image.open(full_image_path) as opened:
        image = white_background(opened)

    if SKIP_PANEL_SPLIT:
        figure_record = {
            "paper_id": paper_id,
            "doi": paper["doi"],
            "pmcid": paper["pmcid"],
            "journal": paper["journal"],
            "publication_date": paper["publication_date"],
            "figure_label": figure.get("label", f"Fig. {figure_index}"),
            "figure_index": figure_index,
            "relative_path": rel(full_image_path),
            "figure_pdf_path": rel(figure_pdf_path),
            "source_url": source_url,
            "panel_count": target_count,
            "parsed_panel_labels": ",".join(labels),
            "split_method": "panel_split_skipped",
            "review_path": "",
            "caption": caption,
        }
        return figure_record, []

    review_path: Path | None = None
    boxes, split_method, review_path = figpanel_boxes(full_image_path, image, labels)
    if not boxes:
        boxes, split_method = detect_panel_boxes(image, target_count)

    panel_records: list[dict] = []
    for ordinal, box in enumerate(boxes, start=1):
        label = labels[ordinal - 1] if ordinal - 1 < len(labels) else ""
        panel_caption = caption_by_label.get(label, caption)
        panel_base = panel_output_name(figure_index, label, ordinal)
        panel_image_path = panel_dir / f"{panel_base}.png"
        panel_pdf_path = panel_dir / f"{panel_base}.pdf"
        crop = image.crop(tuple(box.as_list()))
        crop.save(panel_image_path)
        image_to_pdf(panel_image_path, panel_pdf_path)
        category, confidence, reason = classify_panel(crop, panel_caption)

        panel_records.append(
            {
                "paper_id": paper_id,
                "doi": paper["doi"],
                "pmcid": paper["pmcid"],
                "journal": paper["journal"],
                "publication_date": paper["publication_date"],
                "figure_label": figure.get("label", f"Fig. {figure_index}"),
                "figure_index": figure_index,
                "panel_label": label,
                "panel_ordinal": ordinal,
                "category": category,
                "classification_confidence": round(confidence, 3),
                "classification_reason": reason,
                "relative_path": rel(panel_image_path),
                "panel_pdf_path": rel(panel_pdf_path),
                "source_figure_path": rel(full_image_path),
                "source_figure_pdf_path": rel(figure_pdf_path),
                "source_figure_url": source_url,
                "review_path": rel(review_path) if review_path else "",
                "bbox_xyxy": json.dumps(box.as_list()),
                "split_method": split_method,
                "panel_caption": panel_caption,
                "figure_caption": caption,
            }
        )

    figure_record = {
        "paper_id": paper_id,
        "doi": paper["doi"],
        "pmcid": paper["pmcid"],
        "figure_label": figure.get("label", f"Fig. {figure_index}"),
        "figure_index": figure_index,
        "relative_path": rel(full_image_path),
        "figure_pdf_path": rel(figure_pdf_path),
        "source_url": source_url,
        "panel_count": len(panel_records),
        "parsed_panel_labels": ",".join(labels),
        "split_method": split_method,
        "review_path": rel(review_path) if review_path else "",
        "caption": caption,
    }
    return figure_record, panel_records


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    papers = json.loads(PAPERS_JSON.read_text(encoding="utf-8"))
    FULL_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_PDFS_DIR.mkdir(parents=True, exist_ok=True)
    PANELS_DIR.mkdir(parents=True, exist_ok=True)
    PANEL_REVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    figure_rows: list[dict] = []
    panel_rows: list[dict] = []

    tasks = [
        (paper_index, paper, figure)
        for paper_index, paper in enumerate(papers, start=1)
        for figure in paper["figures"]
    ]

    def run_task(task: tuple[int, dict, dict]) -> tuple[int, dict | None, list[dict]]:
        paper_index, paper, figure = task
        try:
            figure_record, panel_records = process_figure(paper, figure)
        except Exception as exc:
            print(f"skip {paper['doi']} {figure.get('label')}: {exc}", flush=True)
            return paper_index, None, []
        print(
            f"processed paper {paper_index:02d}/{len(papers)} "
            f"{paper['doi']} {figure_record['figure_label']} "
            f"panels={len(panel_records)} method={figure_record['split_method']}",
            flush=True,
        )
        if BUILD_WORKERS == 1:
            time.sleep(0.2)
        return paper_index, figure_record, panel_records

    if BUILD_WORKERS == 1:
        results = [run_task(task) for task in tasks]
    else:
        batch_size = min(BUILD_BATCH_SIZE, len(tasks))
        max_workers = min(BUILD_WORKERS, batch_size)
        print(
            f"parallel full-figure workers={max_workers} batch_size={batch_size} "
            f"batch_sleep={BUILD_BATCH_SLEEP}s",
            flush=True,
        )
        results = []
        for start in range(0, len(tasks), batch_size):
            batch = tasks[start : start + batch_size]
            batch_index = start // batch_size + 1
            batch_total = (len(tasks) + batch_size - 1) // batch_size
            print(f"full-figure batch {batch_index}/{batch_total} size={len(batch)}", flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(batch))) as executor:
                results.extend(executor.map(run_task, batch))
            if start + batch_size < len(tasks) and BUILD_BATCH_SLEEP > 0:
                time.sleep(BUILD_BATCH_SLEEP)

    ordered_results = [item for item in results if item[1] is not None]
    ordered_results.sort(key=lambda item: (item[0], int(item[1]["figure_index"])))
    for _, figure_record, panel_records in ordered_results:
        if figure_record is None:
            continue
        figure_rows.append(figure_record)
        panel_rows.extend(panel_records)

    write_csv(FULL_FIGURES_DIR / "full_figures.csv", figure_rows)
    write_csv(FIGURE_PDFS_DIR / "figure_pdfs.csv", figure_rows)
    write_csv(PANELS_DIR / "panels.csv", panel_rows)
    (PANELS_DIR / "panels.json").write_text(
        json.dumps(panel_rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (FULL_FIGURES_DIR / "full_figures.json").write_text(
        json.dumps(figure_rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary: dict[str, int] = {}
    for row in panel_rows:
        summary[row["category"]] = summary.get(row["category"], 0) + 1
    print(f"done: {len(figure_rows)} figures, {len(panel_rows)} panels")
    print("classification:", json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
