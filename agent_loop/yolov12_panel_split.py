#!/usr/bin/env python3
"""Split full scientific figures into panels with a YOLOv12 panel detector."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FULL_FIGURES_CSV = BASE_DIR / "FullFigures" / "full_figures.csv"
DEFAULT_PANELS_DIR = BASE_DIR / "Panels"
DEFAULT_REVIEWS_DIR = BASE_DIR / "PanelReviews"
DEFAULT_DEPS = BASE_DIR / ".deps" / "figpanel_min"
DEFAULT_YOLO_REPO = os.environ.get("YOLOV12_PANEL_REPO", "mermermer/figpanel-yolov12")
DEFAULT_YOLO_FILENAME = os.environ.get("YOLOV12_PANEL_FILENAME", "v4.pt")


@dataclass
class DetectedBox:
    bbox: list[int]
    confidence: float
    class_id: int
    label: str = ""

    @property
    def x0(self) -> int:
        return self.bbox[0]

    @property
    def y0(self) -> int:
        return self.bbox[1]

    @property
    def x1(self) -> int:
        return self.bbox[2]

    @property
    def y1(self) -> int:
        return self.bbox[3]

    @property
    def width(self) -> int:
        return max(0, self.x1 - self.x0)

    @property
    def height(self) -> int:
        return max(0, self.y1 - self.y0)

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0


def ensure_ultralytics():
    if str(DEFAULT_DEPS) not in sys.path and DEFAULT_DEPS.exists():
        sys.path.insert(0, str(DEFAULT_DEPS))
    try:
        from ultralytics import YOLO  # type: ignore
    except Exception as exc:
        raise SystemExit(
            "ultralytics is required for YOLOv12 panel splitting. "
            "Install it in the active environment or keep .deps/figpanel_min on PYTHONPATH."
        ) from exc
    return YOLO


def default_hf_cache_home() -> Path:
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home)
    return BASE_DIR / ".cache" / "huggingface"


def cached_hf_weight(repo_id: str = DEFAULT_YOLO_REPO, filename: str = DEFAULT_YOLO_FILENAME) -> Path | None:
    cache_root = default_hf_cache_home() / "hub"
    model_dir = cache_root / f"models--{repo_id.replace('/', '--')}"
    refs_main = model_dir / "refs" / "main"
    candidates: list[Path] = []
    if refs_main.exists():
        revision = refs_main.read_text(encoding="utf-8").strip()
        if revision:
            candidates.append(model_dir / "snapshots" / revision / filename)
    candidates.extend(sorted((model_dir / "snapshots").glob(f"*/{filename}")) if (model_dir / "snapshots").exists() else [])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_weights(value: str) -> str:
    if value:
        path = Path(value)
        if path.exists():
            return str(path)
        return value
    env_value = os.environ.get("YOLOV12_PANEL_MODEL", "")
    if env_value:
        path = Path(env_value)
        if path.exists():
            return str(path)
        return env_value
    cached = cached_hf_weight()
    if cached:
        return str(cached)
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
    except Exception:
        return DEFAULT_YOLO_REPO
    return hf_hub_download(repo_id=DEFAULT_YOLO_REPO, filename=DEFAULT_YOLO_FILENAME)


def rel(path: Path) -> str:
    return str(path.relative_to(BASE_DIR))


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


def load_figures(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def parse_class_ids(value: str) -> set[int] | None:
    if not value.strip():
        return None
    return {int(item.strip()) for item in value.split(",") if item.strip()}


def yolo_boxes(result, width: int, height: int, conf_threshold: float, keep_class_ids: set[int] | None) -> list[dict]:
    boxes: list[dict] = []
    if result.boxes is None:
        return boxes
    xyxy = result.boxes.xyxy.cpu().numpy()
    confs = result.boxes.conf.cpu().numpy()
    classes = result.boxes.cls.cpu().numpy() if result.boxes.cls is not None else [0] * len(xyxy)
    for coords, conf, cls in zip(xyxy, confs, classes):
        class_id = int(cls)
        if keep_class_ids is not None and class_id not in keep_class_ids:
            continue
        if float(conf) < conf_threshold:
            continue
        x0, y0, x1, y1 = [int(round(v)) for v in coords]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(width, x1), min(height, y1)
        if x1 - x0 < 20 or y1 - y0 < 20:
            continue
        boxes.append({"bbox": [x0, y0, x1, y1], "confidence": float(conf), "class_id": class_id})
    return sorted(boxes, key=lambda item: (item["bbox"][1], item["bbox"][0]))


def draw_review(image: Image.Image, boxes: list[dict], out_path: Path, *, captions: list[DetectedBox] | None = None) -> None:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    for index, item in enumerate(boxes, start=1):
        box = item["bbox"]
        draw.rectangle(box, outline=(36, 114, 255), width=4)
        label = item.get("label") or str(index)
        draw.text((box[0] + 6, box[1] + 6), f"{label}:{item['confidence']:.2f}", fill=(220, 0, 0))
    for caption in captions or []:
        draw.rectangle(caption.bbox, outline=(35, 160, 70), width=3)
        text = caption.label or f"{caption.confidence:.2f}"
        draw.text((caption.x0 + 2, max(0, caption.y0 - 16)), text, fill=(35, 160, 70))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


PANEL_MARK_RE = re.compile(r"(?:(?<=^)|(?<=[.;]))\s*([a-z])\s*(?:[-–—]\s*([a-z]))?\s*(?:[,.)]\s*)?(?=[A-Z0-9(])")


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


def reading_order(boxes: list[DetectedBox]) -> list[DetectedBox]:
    if not boxes:
        return []
    median_h = sorted(box.height for box in boxes)[len(boxes) // 2]
    row_tol = max(16, int(median_h * 2.5))
    rows: list[list[DetectedBox]] = []
    for box in sorted(boxes, key=lambda item: (item.y0, item.x0)):
        for row in rows:
            row_y = sum(item.y0 for item in row) / len(row)
            if abs(box.y0 - row_y) <= row_tol:
                row.append(box)
                break
        else:
            rows.append([box])
    ordered: list[DetectedBox] = []
    for row in sorted(rows, key=lambda group: min(item.y0 for item in group)):
        ordered.extend(sorted(row, key=lambda item: item.x0))
    return ordered


def convert_boxes(items: list[dict]) -> list[DetectedBox]:
    return [
        DetectedBox(
            bbox=list(item["bbox"]),
            confidence=float(item["confidence"]),
            class_id=int(item["class_id"]),
            label=str(item.get("label", "")),
        )
        for item in items
    ]


def classify_caption_crop(image: Image.Image, caption: DetectedBox, allowed_labels: list[str]) -> tuple[str, float] | None:
    try:
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        from nature_panel_forge.build_figure_assets import classify_label_crop
    except Exception:
        return None
    pad = max(3, int(max(caption.width, caption.height) * 0.25))
    crop = image.crop(
        (
            max(0, caption.x0 - pad),
            max(0, caption.y0 - pad),
            min(image.width, caption.x1 + pad),
            min(image.height, caption.y1 + pad),
        )
    )
    return classify_label_crop(crop, allowed_labels)


def choose_label_anchors(
    image: Image.Image,
    raw_captions: list[DetectedBox],
    labels: list[str],
) -> list[DetectedBox]:
    captions = [
        cap
        for cap in raw_captions
        if cap.width <= image.width * 0.12
        and cap.height <= image.height * 0.12
        and cap.area <= image.width * image.height * 0.02
    ]
    if not captions:
        return []

    if not labels:
        inferred = reading_order(captions)
        generated = [chr(ord("a") + index) for index in range(min(len(inferred), 26))]
        for cap, label in zip(inferred, generated):
            cap.label = label
        return inferred[: len(generated)]

    by_label: dict[str, tuple[DetectedBox, float]] = {}
    for cap in captions:
        classified = classify_caption_crop(image, cap, labels)
        if classified is None:
            continue
        label, score = classified
        combined = score * cap.confidence
        if label not in by_label or combined > by_label[label][1]:
            by_label[label] = (cap, combined)

    anchors: list[DetectedBox] = []
    used: set[tuple[int, int, int, int]] = set()
    for label in labels:
        if label in by_label:
            cap = by_label[label][0]
            cap.label = label
            anchors.append(cap)
            used.add(tuple(cap.bbox))

    missing = [label for label in labels if label not in {cap.label for cap in anchors}]
    if missing:
        remaining = [cap for cap in reading_order(captions) if tuple(cap.bbox) not in used]
        for label, cap in zip(missing, remaining):
            cap.label = label
            anchors.append(cap)

    order = {label: index for index, label in enumerate(labels)}
    return sorted(anchors, key=lambda item: order.get(item.label, 999))


def box_distance_to_label(subplot: DetectedBox, label: DetectedBox) -> float:
    cx, cy = subplot.center
    lx, ly = label.x0, label.y0
    if label.x0 >= subplot.x0 and label.y0 >= subplot.y0 and label.x1 <= subplot.x1 and label.y1 <= subplot.y1:
        return 0.0
    penalty = 0.0
    if subplot.x1 < label.x0:
        penalty += (label.x0 - subplot.x1) * 1.5
    if subplot.y1 < label.y0:
        penalty += (label.y0 - subplot.y1) * 1.5
    return math.hypot(cx - lx, cy - ly) + penalty


def union_bbox(boxes: list[DetectedBox], width: int, height: int, margin: int) -> list[int]:
    x0 = max(0, min(box.x0 for box in boxes) - margin)
    y0 = max(0, min(box.y0 for box in boxes) - margin)
    x1 = min(width, max(box.x1 for box in boxes) + margin)
    y1 = min(height, max(box.y1 for box in boxes) + margin)
    return [x0, y0, x1, y1]


def overlap_fraction(a: DetectedBox, b: DetectedBox) -> float:
    x0, y0 = max(a.x0, b.x0), max(a.y0, b.y0)
    x1, y1 = min(a.x1, b.x1), min(a.y1, b.y1)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    return inter / max(1, min(a.area, b.area))


def dedupe_subplots(subplots: list[DetectedBox]) -> list[DetectedBox]:
    selected: list[DetectedBox] = []
    for box in sorted(subplots, key=lambda item: item.confidence, reverse=True):
        if any(overlap_fraction(box, existing) > 0.85 for existing in selected):
            continue
        selected.append(box)
    return selected


def box_contains_anchor(box: DetectedBox, anchor: DetectedBox) -> bool:
    cx, cy = anchor.center
    return box.x0 <= cx <= box.x1 and box.y0 <= cy <= box.y1


def spans_multiple_panel_labels(box: DetectedBox, anchors: list[DetectedBox], width: int, height: int) -> bool:
    """Reject YOLO boxes that are likely layout containers, not one labeled panel."""
    if len(anchors) <= 1:
        return False

    inside = [anchor for anchor in anchors if box_contains_anchor(box, anchor)]
    if len(inside) >= 2:
        return True

    left_tol = max(45, int(width * 0.08))
    y_tol = max(18, int(height * 0.012))
    left_edge_hits = [
        anchor
        for anchor in anchors
        if anchor.x0 <= box.x0
        and box.x0 - anchor.x0 <= left_tol
        and box.y0 - y_tol <= anchor.y0 <= box.y1 + y_tol
    ]
    combined_labels = {anchor.label for anchor in inside + left_edge_hits}
    return len(combined_labels) >= 2


def label_subplot_score(label: DetectedBox, subplot: DetectedBox, width: int, height: int) -> float:
    """Score whether a subplot belongs to the panel whose visible label is `label`.

    Scientific panel letters usually sit at the top-left of the panel or just
    outside the content. Center-distance assignment over-splits rows and steals
    right-side plots; this score favors labels aligned with the subplot top edge.
    """
    top_band = max(45, int(subplot.height * 0.18), int(height * 0.025))
    left_slack = max(70, int(width * 0.05))

    if label.y0 > subplot.y1:
        return float("inf")
    if label.x0 > subplot.x1 + left_slack:
        return float("inf")
    if label.y0 > subplot.y0 + top_band:
        return float("inf")

    dy = abs(label.y0 - subplot.y0)
    if label.y0 < subplot.y0:
        dy *= 0.75
    dx = abs(label.x0 - subplot.x0)
    if label.x0 <= subplot.x0:
        dx *= 0.65
    if subplot.x0 <= label.x0 <= subplot.x1:
        dx *= 0.35

    below_penalty = max(0, label.y0 - subplot.y0) * 0.6
    return dy * 8.0 + dx * 0.45 + below_penalty


def assign_subplots_to_labels(
    subplots: list[DetectedBox],
    anchors: list[DetectedBox],
    width: int,
    height: int,
) -> dict[str, list[DetectedBox]]:
    assignments: dict[str, list[DetectedBox]] = {anchor.label: [anchor] for anchor in anchors}
    min_area = max(60 * 60, int(width * height * 0.0015))

    for subplot in sorted(subplots, key=lambda item: (item.y0, item.x0, -item.area)):
        if subplot.area < min_area or subplot.width < 45 or subplot.height < 45:
            continue
        if spans_multiple_panel_labels(subplot, anchors, width, height):
            continue

        scored = [(label_subplot_score(anchor, subplot, width, height), anchor) for anchor in anchors]
        score, best = min(scored, key=lambda item: item[0])
        if math.isinf(score):
            continue
        assignments[best.label].append(subplot)

    return assignments


def layout_fallback_bbox(
    anchor: DetectedBox,
    anchors: list[DetectedBox],
    width: int,
    height: int,
    margin: int,
) -> list[int]:
    row_tol = max(55, int(height * 0.035))
    same_row = [
        other
        for other in anchors
        if other.label != anchor.label and abs(other.y0 - anchor.y0) <= row_tol and other.x0 > anchor.x0
    ]
    lower = [other for other in anchors if other.y0 > anchor.y0 + row_tol]

    x0 = max(0, anchor.x0 - margin)
    y0 = max(0, anchor.y0 - margin)
    x1 = min(width, min((other.x0 for other in same_row), default=width) - margin)
    y1 = min(height, min((other.y0 for other in lower), default=height) - margin)

    min_width = max(120, int(width * 0.22))
    min_height = max(120, int(height * 0.22))
    if x1 - x0 < max(80, int(width * 0.08)):
        if x1 >= width:
            x0 = max(0, x1 - min_width)
        else:
            x1 = min(width, x0 + min_width)
    if y1 - y0 < max(80, int(height * 0.08)):
        if y1 >= height:
            y0 = max(0, y1 - min_height)
        else:
            y1 = min(height, y0 + min_height)
    return [x0, y0, x1, y1]


def enforce_min_panel_size(panel_boxes: list[dict], width: int, height: int) -> list[dict]:
    min_width = max(100, int(width * 0.04))
    min_height = max(100, int(height * 0.08))
    fixed: list[dict] = []
    for item in panel_boxes:
        x0, y0, x1, y1 = item["bbox"]
        if x1 - x0 < min_width:
            extra = min_width - (x1 - x0)
            x0 = max(0, x0 - extra // 2)
            x1 = min(width, x1 + extra - extra // 2)
            if x1 - x0 < min_width and x0 == 0:
                x1 = min(width, min_width)
            if x1 - x0 < min_width and x1 == width:
                x0 = max(0, width - min_width)
        if y1 - y0 < min_height:
            extra = min_height - (y1 - y0)
            y0 = max(0, y0 - extra // 2)
            y1 = min(height, y1 + extra - extra // 2)
            if y1 - y0 < min_height and y0 == 0:
                y1 = min(height, min_height)
            if y1 - y0 < min_height and y1 == height:
                y0 = max(0, height - min_height)
        updated = dict(item)
        updated["bbox"] = [x0, y0, x1, y1]
        fixed.append(updated)
    return fixed


def clip_heavy_overlaps(panel_boxes: list[dict], width: int, height: int) -> list[dict]:
    """Make labeled panel boxes mostly disjoint without dropping labels."""
    if len(panel_boxes) <= 1:
        return enforce_min_panel_size(panel_boxes, width, height)

    boxes = [dict(item) for item in panel_boxes]
    for _ in range(2):
        changed = False
        for i in range(len(boxes)):
            ax0, ay0, ax1, ay1 = boxes[i]["bbox"]
            for j in range(i + 1, len(boxes)):
                bx0, by0, bx1, by1 = boxes[j]["bbox"]
                aw, ah = max(1, ax1 - ax0), max(1, ay1 - ay0)
                bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)
                acx, acy = (ax0 + ax1) / 2.0, (ay0 + ay1) / 2.0
                bcx, bcy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0

                ix0, iy0 = max(ax0, bx0), max(ay0, by0)
                ix1, iy1 = min(ax1, bx1), min(ay1, by1)
                if ix1 <= ix0 or iy1 <= iy0:
                    continue
                overlap_w, overlap_h = ix1 - ix0, iy1 - iy0
                if overlap_w < 8 or overlap_h < 8:
                    continue

                horizontal = abs(acx - bcx) / max(1.0, max(aw, bw)) >= abs(acy - bcy) / max(1.0, max(ah, bh))
                if horizontal and overlap_h >= min(ah, bh) * 0.18:
                    cut = int(round((ax1 + bx0) / 2.0)) if acx <= bcx else int(round((bx1 + ax0) / 2.0))
                    if acx <= bcx:
                        ax1 = max(ax0 + 30, min(ax1, cut))
                        bx0 = min(bx1 - 30, max(bx0, cut))
                    else:
                        bx1 = max(bx0 + 30, min(bx1, cut))
                        ax0 = min(ax1 - 30, max(ax0, cut))
                    changed = True
                elif (not horizontal) and overlap_w >= min(aw, bw) * 0.18:
                    cut = int(round((ay1 + by0) / 2.0)) if acy <= bcy else int(round((by1 + ay0) / 2.0))
                    if acy <= bcy:
                        ay1 = max(ay0 + 30, min(ay1, cut))
                        by0 = min(by1 - 30, max(by0, cut))
                    else:
                        by1 = max(by0 + 30, min(by1, cut))
                        ay0 = min(ay1 - 30, max(ay0, cut))
                    changed = True

                boxes[i]["bbox"] = [ax0, ay0, ax1, ay1]
                boxes[j]["bbox"] = [bx0, by0, bx1, by1]
            ax0, ay0, ax1, ay1 = boxes[i]["bbox"]
        if not changed:
            break
    boxes = [item for item in boxes if item["bbox"][2] - item["bbox"][0] >= 30 and item["bbox"][3] - item["bbox"][1] >= 30]
    return enforce_min_panel_size(boxes, width, height)


def label_grouped_boxes(
    image: Image.Image,
    raw_boxes: list[dict],
    row: dict,
    *,
    allow_whole_figure_fallback: bool,
) -> tuple[list[dict], list[DetectedBox], str, dict[str, str]]:
    labels, caption_map = expected_labels(row)
    boxes = convert_boxes(raw_boxes)
    captions = [box for box in boxes if box.class_id == 0]
    subplots = [box for box in boxes if box.class_id == 1]
    anchors = choose_label_anchors(image, captions, labels)
    if labels and len(anchors) < len(labels) and subplots:
        existing = {anchor.label for anchor in anchors}
        ordered_subplots = reading_order(subplots)
        used_synthetic: set[int] = set()
        for label in labels:
            if label in existing:
                continue
            label_index = labels.index(label)
            candidate_index = min(label_index, len(ordered_subplots) - 1)
            while candidate_index in used_synthetic and candidate_index + 1 < len(ordered_subplots):
                candidate_index += 1
            source = ordered_subplots[candidate_index]
            used_synthetic.add(candidate_index)
            size = max(16, min(40, int(min(source.width, source.height) * 0.08)))
            x0 = max(0, source.x0)
            y0 = max(0, source.y0)
            anchors.append(
                DetectedBox(
                    bbox=[x0, y0, min(image.width, x0 + size), min(image.height, y0 + size)],
                    confidence=0.01,
                    class_id=0,
                    label=label,
                )
            )
    if labels:
        order = {label: index for index, label in enumerate(labels)}
        anchors = sorted(anchors, key=lambda item: order.get(item.label, 999))
    else:
        anchors = reading_order(anchors)

    if not anchors:
        if allow_whole_figure_fallback:
            return (
                [{"bbox": [0, 0, image.width, image.height], "confidence": 1.0, "class_id": -1, "label": ""}],
                [],
                "yolov12_label_whole_figure_fallback",
                caption_map,
            )
        return [], [], "yolov12_label_unresolved", caption_map

    assignments = assign_subplots_to_labels(subplots, anchors, image.width, image.height)

    margin = max(8, int(min(image.size) * 0.008))
    panel_boxes: list[dict] = []
    for anchor in anchors:
        group = assignments.get(anchor.label, [anchor])
        assigned_count = max(0, len(group) - 1)
        if assigned_count:
            bbox = union_bbox(group, image.width, image.height, margin)
        else:
            bbox = layout_fallback_bbox(anchor, anchors, image.width, image.height, margin)
        if bbox[2] - bbox[0] < 20 or bbox[3] - bbox[1] < 20:
            continue
        confidence = min(1.0, sum(box.confidence for box in group) / max(1, len(group)))
        panel_boxes.append(
            {
                "bbox": bbox,
                "confidence": confidence,
                "class_id": 1,
                "label": anchor.label,
                "assigned_subplots": assigned_count,
            }
        )
    panel_boxes = clip_heavy_overlaps(panel_boxes, image.width, image.height)

    if not panel_boxes and allow_whole_figure_fallback:
        panel_boxes = [{"bbox": [0, 0, image.width, image.height], "confidence": 1.0, "class_id": -1, "label": ""}]

    return panel_boxes, anchors, "yolov12_label_anchor", caption_map


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
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def split(args: argparse.Namespace) -> None:
    weights = resolve_weights(args.weights)

    figures_csv = Path(args.full_figures_csv)
    if not figures_csv.is_absolute():
        figures_csv = BASE_DIR / figures_csv
    panels_dir = Path(args.panels_dir)
    if not panels_dir.is_absolute():
        panels_dir = BASE_DIR / panels_dir
    reviews_dir = Path(args.reviews_dir)
    if not reviews_dir.is_absolute():
        reviews_dir = BASE_DIR / reviews_dir

    if args.overwrite:
        shutil.rmtree(panels_dir, ignore_errors=True)
        shutil.rmtree(reviews_dir, ignore_errors=True)
    panels_dir.mkdir(parents=True, exist_ok=True)
    reviews_dir.mkdir(parents=True, exist_ok=True)

    YOLO = ensure_ultralytics()
    print(f"YOLOv12 weights: {weights}", flush=True)
    model = YOLO(weights)
    keep_class_ids = parse_class_ids(args.keep_class_ids)
    figure_rows = load_figures(figures_csv)
    if args.limit:
        figure_rows = figure_rows[: args.limit]

    panel_rows: list[dict] = []
    for fig_index, row in enumerate(figure_rows, start=1):
        image_path = BASE_DIR / row["relative_path"]
        with Image.open(image_path) as opened:
            image = white_background(opened)
        result = model.predict(str(image_path), imgsz=args.imgsz, conf=args.conf, verbose=False)[0]
        raw_boxes = yolo_boxes(result, image.width, image.height, args.conf, None)
        caption_anchors: list[DetectedBox] = []
        caption_by_label: dict[str, str] = {}
        split_method = "yolov12"
        if args.split_mode == "label":
            boxes, caption_anchors, split_method, caption_by_label = label_grouped_boxes(
                image,
                raw_boxes,
                row,
                allow_whole_figure_fallback=args.allow_whole_figure_fallback,
            )
        else:
            boxes = [box for box in raw_boxes if keep_class_ids is None or int(box["class_id"]) in keep_class_ids]
        if not boxes and args.allow_whole_figure_fallback:
            boxes = [{"bbox": [0, 0, image.width, image.height], "confidence": 1.0, "class_id": -1}]
        if not boxes:
            print(f"[{fig_index}/{len(figure_rows)}] no panels: {rel(image_path)}")
            continue

        paper_id = row["paper_id"]
        paper_panel_dir = panels_dir / paper_id
        paper_panel_dir.mkdir(parents=True, exist_ok=True)
        review_path = reviews_dir / paper_id / f"fig{int(row['figure_index']):02d}_yolov12_review.png"
        draw_review(image, boxes, review_path, captions=caption_anchors)

        for ordinal, item in enumerate(boxes, start=1):
            x0, y0, x1, y1 = item["bbox"]
            panel_label = item.get("label", "")
            stem_suffix = panel_label if panel_label else f"panel{ordinal:02d}"
            stem = f"fig{int(row['figure_index']):02d}_{stem_suffix}"
            png_path = paper_panel_dir / f"{stem}.png"
            pdf_path = paper_panel_dir / f"{stem}.pdf"
            crop = image.crop((x0, y0, x1, y1))
            crop.save(png_path)
            image_to_pdf(png_path, pdf_path)
            panel_rows.append(
                {
                    "paper_id": paper_id,
                    "doi": row.get("doi", ""),
                    "pmcid": row.get("pmcid", ""),
                    "journal": row.get("journal", ""),
                    "publication_date": row.get("publication_date", ""),
                    "figure_label": row.get("figure_label", ""),
                    "figure_index": row.get("figure_index", ""),
                    "panel_label": panel_label,
                    "panel_ordinal": ordinal,
                    "relative_path": rel(png_path),
                    "panel_pdf_path": rel(pdf_path),
                    "source_figure_path": row.get("relative_path", ""),
                    "source_figure_pdf_path": row.get("figure_pdf_path", ""),
                    "source_figure_url": row.get("source_url", ""),
                    "review_path": rel(review_path),
                    "bbox_xyxy": json.dumps(item["bbox"]),
                    "split_method": split_method,
                    "yolo_confidence": round(item["confidence"], 4),
                    "yolo_class_id": item["class_id"],
                    "assigned_subplots": item.get("assigned_subplots", ""),
                    "panel_caption": caption_by_label.get(panel_label, row.get("caption", "")),
                    "figure_caption": row.get("caption", ""),
                }
            )
        label_info = ",".join(str(item.get("label", "")) for item in boxes if item.get("label"))
        print(f"[{fig_index}/{len(figure_rows)}] {rel(image_path)} panels={len(boxes)} mode={args.split_mode} labels={label_info}")

    write_csv(panels_dir / "panels.csv", panel_rows)
    (panels_dir / "panels.json").write_text(json.dumps(panel_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"figures": len(figure_rows), "panels": len(panel_rows), "panels_csv": rel(panels_dir / "panels.csv")}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Split panels with YOLOv12")
    parser.add_argument("--full-figures-csv", default=str(DEFAULT_FULL_FIGURES_CSV.relative_to(BASE_DIR)))
    parser.add_argument("--panels-dir", default=str(DEFAULT_PANELS_DIR.relative_to(BASE_DIR)))
    parser.add_argument("--reviews-dir", default=str(DEFAULT_REVIEWS_DIR.relative_to(BASE_DIR)))
    parser.add_argument("--weights", default="")
    parser.add_argument("--split-mode", choices=["label", "subplot"], default="label")
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--conf", type=float, default=0.20)
    parser.add_argument(
        "--keep-class-ids",
        default="1",
        help="Comma-separated YOLO class IDs to crop as panels. Empty keeps all classes. figpanel-yolov12 uses 1=subplot and 0=caption.",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-whole-figure-fallback", action="store_true")
    args = parser.parse_args()
    split(args)


if __name__ == "__main__":
    main()
