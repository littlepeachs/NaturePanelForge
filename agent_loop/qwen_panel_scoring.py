#!/usr/bin/env python3
"""Ask local Qwen3.6-27B to classify and score scientific figure panels."""

from __future__ import annotations

import argparse
import base64
import csv
import gc
import json
import datetime as dt
import re
import shutil
import time
import urllib.request
import os
from pathlib import Path
from typing import Any

from PIL import Image


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PANELS_CSV = BASE_DIR / "Panels" / "panels.csv"
DEFAULT_SCORES_DIR = BASE_DIR / "PanelScores"
DEFAULT_MODEL_PATH = Path(os.environ.get("QWEN_MODEL_PATH", str(BASE_DIR / "models" / "Qwen3.6-27B")))

PANEL_CATEGORIES = ["schematic", "data_statistical", "chemical_structure", "characterization_photo", "other_uncertain"]
DATA_SUBTYPES = [
    "bar",
    "grouped_bar",
    "stacked_bar",
    "line",
    "multi_line",
    "scatter",
    "scatter_with_fit",
    "box",
    "violin",
    "histogram",
    "density",
    "heatmap",
    "confusion_matrix",
    "roc_curve",
    "pr_curve",
    "calibration_curve",
    "umap_tsne_pca",
    "volcano_plot",
    "survival_curve",
    "forest_plot",
    "dot_plot",
    "bubble_plot",
    "matrix_plot",
    "network_plot",
    "sankey_alluvial",
    "geospatial_map",
    "table_like",
    "learning_curve",
    "time_series",
    "dose_response",
    "other_data_display",
]

_TORCHVISION_LIB = None


class BatchOOMSkipped(RuntimeError):
    """Raised when a CUDA OOM batch is intentionally skipped."""


def rel(path: Path) -> str:
    return str(path.relative_to(BASE_DIR))


def stable_panel_id(row: dict) -> str:
    label = row.get("panel_label") or f"panel{row.get('panel_ordinal', '')}"
    raw = f"{row['paper_id']}__fig{int(row['figure_index']):02d}_{label}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)


def build_prompt(row: dict, image_relpath: str) -> str:
    category_list = ", ".join(PANEL_CATEGORIES)
    subtype_list = ", ".join(DATA_SUBTYPES)
    return f"""你是一个科学论文图像 panel 评估器。请直接观察图像 `{image_relpath}`，并结合 caption，但不要只根据 caption 判断。

任务：
1. 判断 panel 类别，只能从这些类别里选一个：{category_list}
   - schematic: 示意图、流程图、模型架构、机制图、概念图。
   - data_statistical: 数据统计图或可视化图，例如曲线、柱状图、散点图、热图、UMAP、ROC、箱线图等。
   - chemical_structure: 化学结构式、小分子结构、反应式、分子示意结构。
   - characterization_photo: 显微照片、组织/医学图像、SEM/TEM/AFM、谱图、蛋白/晶体/材料表征图、实验照片。
   - other_uncertain: 无法确定、混合且不可分、裁剪错误或不属于以上类别。
2. 如果类别是 data_statistical，请从这些数据图类型里选一个：{subtype_list}。否则写 null。
3. 评价 panel，所有分数都是 0 到 10。最重要的是 clarity_integrity_score：
   - clarity_integrity_score: panel 是否完整、清晰、没有被裁掉、没有其他 panel 的一部分重叠或混入、文字/坐标轴/图例是否可读。这个指标最重要。
   - is_complete_panel: 该裁剪是否像一个完整独立 panel。
   - has_foreign_overlap: 是否有其他 panel 的边缘、标签、曲线、照片或文字混入当前图。
   - xy_label_applicable: 这个 panel 是否本来就应该有 x/y 轴 label 或等价轴标题。
   - xy_label_complete: 如果本 panel 应该有 x/y 轴 label 或等价轴标题，判断这些标签是否完整可见；只能填 yes 或 no。
   - xytick_applicable: 这个 panel 是否本来就应该有 x/y tick labels 或等价刻度文字。
   - xytick_complete: 如果本 panel 应该有 x/y tick labels 或等价刻度文字，判断这些 tick labels 是否完整可见；只能填 yes 或 no。
   - data_purity: 如果是数据统计图，判断它是纯数据统计图，还是混入 schematic/photo/chemical structure；只能填 pure_data_statistical、data_with_schematic_or_photo、not_data_statistical、uncertain。
   - data_purity_score: 只有 data_statistical 需要评；非数据图写 null。请严格打分，不要默认给 9 或 10。
     * 10: 极少数情况。只能给完全纯净、独立、完整的数据统计图；所有主要视觉元素都必须是数据编码、坐标轴、图例、统计标注或必要文字。只要出现 schematic、照片/显微图、化学结构、蛋白结构、流程箭头、仪器/细胞/器官图标、机制图、概念插画、表征图残片或其它 panel 边缘，就不能给 10。
     * 9: 仍然是纯数据统计图，但存在轻微瑕疵，例如很少量解释性图标、边缘无关文字、密集标注、局部裁剪紧张、多个子图挤在一起但没有非数据主体。
     * 8 或以下: 数据图与 schematic/photo/chemical/characterization 元素明显混合，或裁剪包含其它 panel 内容，或纯净性无法确认。
   - code_reproducibility_score: 是否可以用 Python/R/Matplotlib/Seaborn/Plotly 等代码较好地模仿复现。请严格打分，不要默认给 9 或 10。
     * 10: 极少数情况。只能给标准、干净、独立的数据统计图；用常规绘图库和合理数据即可高度复现到接近原图，坐标轴、图例、颜色、标记、统计标注、布局都明确，且不需要图像粘贴、手工描摹、蛋白/化学/显微/照片/示意元素。
     * 9: 少数优秀情况。必须是纯数据统计图，并且用代码可以复现到很相似；只允许少量字体、颜色或标注微调。若需要明显人工调参、复杂拼版、密集注释、手动摆放大量文字或无法确定数据编码，请最多给 8。
     * 8: 清晰完整的普通数据统计图，代码可以复现主要趋势或图型，但视觉细节、排版、颜色、标注或局部元素难以准确复现。大多数论文里的常规好图应该是 8，而不是 9。
     * 7 或以下: 混合了非代码图像元素、结构渲染、照片/显微图、复杂手绘示意，或数据图不完整/不清晰。
   - aesthetic_score: 美学程度，包括颜色、排版、留白、字体、视觉层次和是否适合作为高质量图例。请严格打分，不要默认给 9 或 10。
     * 10: 极少数情况。只给颜色克制且有层次、排版均衡、留白合理、字体清晰、图例/标注不拥挤、整体可作为高质量示范图的 panel。
     * 9: 少数优秀情况。必须明显优于普通 Nature 论文图，整体精致、颜色和排版有设计感，只有很小瑕疵。若只是清楚、专业、常规好看，请给 8。
     * 8: 清楚可用、专业但视觉设计普通；大多数完整清晰的论文 panel 应该落在 7 到 8.5，而不是 9。
     * 7 或以下: 拥挤、颜色杂乱、文字难读、排版失衡、裁剪不佳或整体观感一般。
   - overall_quality_score: 综合分，优先受 clarity_integrity_score 影响，其次考虑 data_purity_score、code_reproducibility_score、aesthetic_score。

高分校准规则：
- 7 分表示可用；8 分已经表示好；9 分只能给明显优秀且少数的 panel；10 分必须非常少见。
- 普通但清晰完整的 Nature 论文数据图通常是 8，不是 9。
- 普通但专业的配色和排版通常是 8，不是 9。
- 如果你犹豫 9 还是 10，请给 9；如果你犹豫 8 还是 9，请给 8；如果你犹豫 7 还是 8，请给 7。
- 只要 panel 不完整、混入其它 panel、或者文字/图例明显影响读图，clarity_integrity_score 和 overall_quality_score 都不能超过 8。
- 对 data_purity_score=10、code_reproducibility_score=9/10、aesthetic_score=9/10 尤其要保守，避免把普通论文图统一打成 9 或 10。

请只输出一个 JSON 对象，不要输出 Markdown，不要输出解释段落。JSON schema:
{{
  "panel_id": "{stable_panel_id(row)}",
  "category": "schematic | data_statistical | chemical_structure | characterization_photo | other_uncertain",
  "data_subtype": null,
  "is_complete_panel": true,
  "has_foreign_overlap": false,
  "xy_label_applicable": true,
  "xy_label_complete": "yes",
  "xytick_applicable": true,
  "xytick_complete": "yes",
  "clarity_integrity_score": 0.0,
  "data_purity": "pure_data_statistical | data_with_schematic_or_photo | not_data_statistical | uncertain",
  "data_purity_score": null,
  "code_reproducibility_score": 0.0,
  "aesthetic_score": 0.0,
  "overall_quality_score": 0.0,
  "confidence": 0.0,
  "is_good_quality": false,
  "short_reason": "一句话说明裁剪完整性、是否混入其他图、以及复现/美学判断"
}}

Caption:
{row.get("panel_caption") or row.get("figure_caption") or ""}
"""


def load_rows(path: Path, limit: int | None = None) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"missing panels CSV: {path}. Run YOLOv12 panel splitting first.")
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    return rows[:limit] if limit else rows


def prepare_bundle(row: dict, scores_dir: Path, overwrite: bool) -> dict:
    pid = stable_panel_id(row)
    panel_dir = scores_dir / pid
    panel_dir.mkdir(parents=True, exist_ok=True)
    image_src = BASE_DIR / row["relative_path"]
    image_dst = panel_dir / "target.png"
    if overwrite or not image_dst.exists():
        shutil.copy2(image_src, image_dst)
    metadata = {**row, "panel_id": pid, "target_path": rel(image_dst)}
    prompt = build_prompt(row, rel(image_dst))
    (panel_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (panel_dir / "qwen_prompt.md").write_text(prompt, encoding="utf-8")
    return {"panel_id": pid, "panel_dir": panel_dir, "target_path": image_dst, "prompt": prompt, "metadata": metadata}


def extract_json(text: str) -> dict:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    match = re.search(r"```json\s*(\{.*?\})\s*```", cleaned, flags=re.S)
    if match:
        cleaned = match.group(1)
    else:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise ValueError(f"no JSON object found in response: {text[:500]}")
        cleaned = match.group(0)
    data = json.loads(cleaned)
    return validate_score(data)


def validate_score(data: dict) -> dict:
    def normalize_yes_no(value: object, default: str = "no") -> str:
        text = str(value or "").strip().lower()
        if text in {"yes", "y", "true", "1"}:
            return "yes"
        if text in {"no", "n", "false", "0"}:
            return "no"
        return default

    category = data.get("category")
    if category not in PANEL_CATEGORIES:
        data["category"] = "other_uncertain"
    if data["category"] == "data_statistical":
        if data.get("data_subtype") not in DATA_SUBTYPES:
            data["data_subtype"] = "other_data_display"
    else:
        data["data_subtype"] = None

    data["is_complete_panel"] = bool(data.get("is_complete_panel", False))
    data["has_foreign_overlap"] = bool(data.get("has_foreign_overlap", False))
    data["xy_label_applicable"] = bool(data.get("xy_label_applicable", False))
    data["xy_label_complete"] = normalize_yes_no(data.get("xy_label_complete"), "no")
    data["xytick_applicable"] = bool(data.get("xytick_applicable", False))
    data["xytick_complete"] = normalize_yes_no(data.get("xytick_complete"), "no")

    data_purity = data.get("data_purity")
    valid_purities = {"pure_data_statistical", "data_with_schematic_or_photo", "not_data_statistical", "uncertain"}
    if data["category"] != "data_statistical":
        data["data_purity"] = "not_data_statistical"
        data["data_purity_score"] = None
    else:
        if data_purity not in valid_purities:
            data["data_purity"] = "uncertain"
        if data["data_purity"] == "not_data_statistical":
            data["data_purity"] = "uncertain"
        try:
            purity_score = float(data.get("data_purity_score", 0))
        except (TypeError, ValueError):
            purity_score = 0.0
        data["data_purity_score"] = round(max(0.0, min(10.0, purity_score)), 3)

    legacy_clarity = data.get("clarity_integrity_score", data.get("clarity_score", 0))
    data["clarity_integrity_score"] = legacy_clarity
    for key in ["clarity_integrity_score", "code_reproducibility_score", "aesthetic_score", "overall_quality_score", "confidence"]:
        try:
            value = float(data.get(key, 0))
        except (TypeError, ValueError):
            value = 0.0
        if key == "confidence":
            value = max(0.0, min(1.0, value))
        else:
            value = max(0.0, min(10.0, value))
        data[key] = round(value, 3)
    data["is_good_quality"] = bool(
        data.get("clarity_integrity_score", 0) >= 8.0
        and data.get("overall_quality_score", 0) >= 8.0
        and data.get("is_complete_panel", False)
        and not data.get("has_foreign_overlap", False)
    )
    data["short_reason"] = str(data.get("short_reason", ""))[:500]
    return data


def image_data_url(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else "png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


def load_scoring_image(path: Path, args: argparse.Namespace) -> Image.Image:
    image = Image.open(path).convert("RGB")
    max_edge = int(getattr(args, "max_image_edge", 0) or 0)
    if max_edge > 0 and max(image.size) > max_edge:
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return image


def call_openai_compatible(args: argparse.Namespace, image_path: Path, prompt: str) -> str:
    api_base = args.api_base.rstrip("/")
    body = {
        "model": args.model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url(image_path)}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": args.max_new_tokens,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "extra_body": {"top_k": 20, "chat_template_kwargs": {"enable_thinking": False}},
    }
    request = urllib.request.Request(
        f"{api_base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {args.api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=args.timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def load_transformers(args: argparse.Namespace):
    try:
        import torch
        ensure_torchvision_available(torch)
        from transformers import AutoProcessor
        try:
            from transformers import AutoModelForImageTextToText
        except ImportError:
            from transformers import AutoModelForCausalLM as AutoModelForImageTextToText
    except Exception as exc:
        raise SystemExit(
            "transformers/torch are required for --backend transformers. "
            "Install a Qwen3.6-compatible transformers build. "
            f"Original error: {type(exc).__name__}: {exc}"
        ) from exc

    model_path = Path(args.model_path)
    processor = AutoProcessor.from_pretrained(str(model_path), trust_remote_code=True)
    tokenizer = getattr(processor, "tokenizer", None)
    if tokenizer is not None:
        tokenizer.padding_side = "left"
        if getattr(tokenizer, "pad_token", None) is None and getattr(tokenizer, "eos_token", None) is not None:
            tokenizer.pad_token = tokenizer.eos_token
    kwargs: dict[str, Any] = {"trust_remote_code": True}
    if args.torch_dtype == "bfloat16":
        kwargs["dtype"] = torch.bfloat16
    elif args.torch_dtype == "float16":
        kwargs["dtype"] = torch.float16
    else:
        kwargs["dtype"] = torch.float32
    if args.device_map:
        kwargs["device_map"] = args.device_map
    kwargs["local_files_only"] = True
    kwargs["low_cpu_mem_usage"] = True
    model = AutoModelForImageTextToText.from_pretrained(str(model_path), **kwargs)
    if not args.device_map and args.device:
        model = model.to(args.device)
    model.eval()
    return processor, model, torch


def register_torchvision_nms_schema(torch) -> None:
    """Work around torchvision builds that register fake nms before defining it."""
    global _TORCHVISION_LIB
    try:
        _TORCHVISION_LIB = torch.library.Library("torchvision", "DEF")
        _TORCHVISION_LIB.define("nms(Tensor dets, Tensor scores, float iou_threshold) -> Tensor")
    except Exception:
        pass


def ensure_torchvision_available(torch) -> None:
    """Pre-register missing torchvision ops before any torchvision import."""
    register_torchvision_nms_schema(torch)
    try:
        import torchvision  # noqa: F401
        return
    except Exception:
        raise


def call_transformers(processor, model, torch, image_path: Path, prompt: str, args: argparse.Namespace) -> str:
    image = load_scoring_image(image_path, args)
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
    try:
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], return_tensors="pt")
    device = next(model.parameters()).device
    inputs = {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}
    with torch.no_grad():
        generated = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
    input_len = inputs["input_ids"].shape[-1]
    decoded = processor.batch_decode(generated[:, input_len:], skip_special_tokens=True)
    return decoded[0]


def call_transformers_batch(processor, model, torch, bundles: list[dict], args: argparse.Namespace) -> list[str]:
    images = []
    texts = []
    for bundle in bundles:
        image = load_scoring_image(bundle["target_path"], args)
        images.append(image)
        messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": bundle["prompt"]}]}]
        try:
            text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        except TypeError:
            text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        texts.append(text)

    inputs = processor(text=texts, images=images, return_tensors="pt", padding=True)
    device = next(model.parameters()).device
    inputs = {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}
    with torch.no_grad():
        generated = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
    input_len = inputs["input_ids"].shape[-1]
    return processor.batch_decode(generated[:, input_len:], skip_special_tokens=True)


def is_cuda_oom_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "out of memory" in message and "cuda" in message


def clear_cuda_memory(torch) -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        try:
            torch.cuda.ipc_collect()
        except Exception:
            pass


def call_transformers_batch_adaptive(processor, model, torch, bundles: list[dict], args: argparse.Namespace) -> list[str]:
    try:
        return call_transformers_batch(processor, model, torch, bundles, args)
    except RuntimeError as exc:
        if not is_cuda_oom_error(exc):
            raise
        clear_cuda_memory(torch)
        print(
            f"CUDA OOM at batch_size={len(bundles)}; skipping batch",
            flush=True,
        )
        raise BatchOOMSkipped(str(exc)) from exc


def write_oom_skip(bundle: dict, exc: BaseException, batch_size: int) -> None:
    skip_path = bundle["panel_dir"] / "qwen_oom_skipped.json"
    payload = {
        "panel_id": bundle["panel_id"],
        "target_path": rel(bundle["target_path"]),
        "status": "skipped_due_to_cuda_oom",
        "skipped_batch_size": batch_size,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
    }
    skip_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def run(args: argparse.Namespace) -> None:
    if args.command == "warm":
        warm(args)
        return

    panels_csv = Path(args.panels_csv)
    if not panels_csv.is_absolute():
        panels_csv = BASE_DIR / panels_csv
    scores_dir = Path(args.scores_dir)
    if not scores_dir.is_absolute():
        scores_dir = BASE_DIR / scores_dir
    if args.overwrite and scores_dir.exists() and args.command == "prepare":
        shutil.rmtree(scores_dir)
    scores_dir.mkdir(parents=True, exist_ok=True)

    rows = load_rows(panels_csv, args.limit or None)
    if args.num_shards > 1:
        if args.shard_index < 0 or args.shard_index >= args.num_shards:
            raise SystemExit("--shard-index must be between 0 and --num-shards - 1")
        rows = [row for row_index, row in enumerate(rows) if row_index % args.num_shards == args.shard_index]
        score_csv_name = f"panel_scores_shard{args.shard_index:02d}.csv"
        score_json_name = f"panel_scores_shard{args.shard_index:02d}.json"
    else:
        score_csv_name = "panel_scores.csv"
        score_json_name = "panel_scores.json"
    bundles = [prepare_bundle(row, scores_dir, args.overwrite) for row in rows]
    if args.command == "prepare":
        write_csv(scores_dir / "pending.csv", [{"panel_id": b["panel_id"], "prompt_path": rel(b["panel_dir"] / "qwen_prompt.md"), "target_path": rel(b["target_path"])} for b in bundles])
        print(json.dumps({"prepared": len(bundles), "scores_dir": rel(scores_dir)}, ensure_ascii=False))
        return

    backend = args.backend
    if backend == "auto":
        backend = "openai" if args.api_base else "transformers"

    tf_backend = None
    if backend == "transformers":
        tf_backend = load_transformers(args)

    scored_rows: list[dict] = []
    skipped_oom = 0
    index = 0
    while index < len(bundles):
        if backend == "transformers" and args.batch_size > 1:
            batch = bundles[index : index + args.batch_size]
            index += len(batch)
            pending_batch: list[dict] = []
            for offset, bundle in enumerate(batch, start=index - len(batch) + 1):
                score_path = bundle["panel_dir"] / "qwen_score.json"
                if score_path.exists() and not args.overwrite:
                    score = json.loads(score_path.read_text(encoding="utf-8"))
                    scored_rows.append({**bundle["metadata"], **score, "score_path": rel(score_path)})
                    print(
                        f"[{offset}/{len(bundles)}] {bundle['panel_id']} {score.get('category')} "
                        f"score={score.get('overall_quality_score')} cached",
                        flush=True,
                    )
                else:
                    pending_batch.append(bundle)

            if pending_batch:
                processor, model, torch = tf_backend
                try:
                    raw_outputs = call_transformers_batch_adaptive(processor, model, torch, pending_batch, args)
                except BatchOOMSkipped as exc:
                    for bundle in pending_batch:
                        write_oom_skip(bundle, exc, len(pending_batch))
                        skipped_oom += 1
                        print(
                            f"[skip-oom] {bundle['panel_id']} skipped with batch_size={len(pending_batch)}",
                            flush=True,
                        )
                    write_csv(scores_dir / score_csv_name, scored_rows)
                    (scores_dir / score_json_name).write_text(
                        json.dumps(scored_rows, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    continue
                for bundle, raw in zip(pending_batch, raw_outputs):
                    score_path = bundle["panel_dir"] / "qwen_score.json"
                    (bundle["panel_dir"] / "raw_response.txt").write_text(raw, encoding="utf-8")
                    try:
                        score = extract_json(raw)
                    except Exception as exc:
                        (bundle["panel_dir"] / "raw_response_invalid.txt").write_text(raw, encoding="utf-8")
                        print(f"[retry-single] {bundle['panel_id']} invalid batch JSON: {type(exc).__name__}: {exc}", flush=True)
                        try:
                            raw = call_transformers_batch_adaptive(processor, model, torch, [bundle], args)[0]
                        except BatchOOMSkipped as retry_exc:
                            write_oom_skip(bundle, retry_exc, 1)
                            skipped_oom += 1
                            print(f"[skip-oom] {bundle['panel_id']} skipped on single retry", flush=True)
                            continue
                        (bundle["panel_dir"] / "raw_response.txt").write_text(raw, encoding="utf-8")
                        try:
                            score = extract_json(raw)
                        except Exception as retry_exc:
                            score = validate_score(
                                {
                                    "panel_id": bundle["panel_id"],
                                    "category": "other_uncertain",
                                    "data_subtype": None,
                                    "is_complete_panel": False,
                                    "has_foreign_overlap": True,
                                    "xy_label_applicable": False,
                                    "xy_label_complete": "no",
                                    "xytick_applicable": False,
                                    "xytick_complete": "no",
                                    "clarity_integrity_score": 0.0,
                                    "data_purity": "uncertain",
                                    "data_purity_score": None,
                                    "code_reproducibility_score": 0.0,
                                    "aesthetic_score": 0.0,
                                    "overall_quality_score": 0.0,
                                    "confidence": 0.0,
                                    "is_good_quality": False,
                                    "short_reason": f"Qwen did not return valid JSON after retry: {type(retry_exc).__name__}",
                                }
                            )
                    score["panel_id"] = bundle["panel_id"]
                    score["target_path"] = rel(bundle["target_path"])
                    score["prompt_path"] = rel(bundle["panel_dir"] / "qwen_prompt.md")
                    score_path.write_text(json.dumps(score, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    scored_rows.append({**bundle["metadata"], **score, "score_path": rel(score_path)})
                    print(
                        f"[{len(scored_rows)}/{len(bundles)}] {bundle['panel_id']} {score.get('category')} "
                        f"score={score.get('overall_quality_score')}",
                        flush=True,
                    )
            write_csv(scores_dir / score_csv_name, scored_rows)
            (scores_dir / score_json_name).write_text(json.dumps(scored_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            continue

        bundle = bundles[index]
        index += 1
        score_path = bundle["panel_dir"] / "qwen_score.json"
        if score_path.exists() and not args.overwrite:
            score = json.loads(score_path.read_text(encoding="utf-8"))
        else:
            if backend == "openai":
                raw = call_openai_compatible(args, bundle["target_path"], bundle["prompt"])
            elif backend == "transformers":
                processor, model, torch = tf_backend
                try:
                    raw = call_transformers(processor, model, torch, bundle["target_path"], bundle["prompt"], args)
                except RuntimeError as exc:
                    if is_cuda_oom_error(exc):
                        clear_cuda_memory(torch)
                        write_oom_skip(bundle, exc, 1)
                        skipped_oom += 1
                        print(f"[skip-oom] {bundle['panel_id']} skipped at batch_size=1", flush=True)
                        continue
                    raise
            else:
                raise SystemExit(f"unsupported backend: {backend}")
            (bundle["panel_dir"] / "raw_response.txt").write_text(raw, encoding="utf-8")
            score = extract_json(raw)
            score["panel_id"] = bundle["panel_id"]
            score["target_path"] = rel(bundle["target_path"])
            score["prompt_path"] = rel(bundle["panel_dir"] / "qwen_prompt.md")
            score_path.write_text(json.dumps(score, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        scored_rows.append({**bundle["metadata"], **score, "score_path": rel(score_path)})
        print(f"[{index}/{len(bundles)}] {bundle['panel_id']} {score.get('category')} score={score.get('overall_quality_score')}", flush=True)

    write_csv(scores_dir / score_csv_name, scored_rows)
    (scores_dir / score_json_name).write_text(json.dumps(scored_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "scored": len(scored_rows),
                "skipped_oom": skipped_oom,
                "scores_csv": rel(scores_dir / score_csv_name),
            },
            ensure_ascii=False,
        )
    )


def warm(args: argparse.Namespace) -> None:
    scores_dir = Path(args.scores_dir)
    if not scores_dir.is_absolute():
        scores_dir = BASE_DIR / scores_dir
    scores_dir.mkdir(parents=True, exist_ok=True)
    processor, model, torch = load_transformers(args)
    devices = sorted({str(param.device) for param in model.parameters()})
    memory: dict[str, Any] = {}
    if torch.cuda.is_available():
        for idx in range(torch.cuda.device_count()):
            free, total = torch.cuda.mem_get_info(idx)
            memory[f"cuda:{idx}"] = {
                "name": torch.cuda.get_device_name(idx),
                "free_gb": round(free / 1024**3, 3),
                "total_gb": round(total / 1024**3, 3),
                "allocated_gb": round(torch.cuda.memory_allocated(idx) / 1024**3, 3),
                "reserved_gb": round(torch.cuda.memory_reserved(idx) / 1024**3, 3),
            }
    payload = {
        "pid": os.getpid(),
        "model_path": str(args.model_path),
        "processor_class": type(processor).__name__,
        "model_class": type(model).__name__,
        "devices": devices,
        "memory": memory,
        "hold": bool(args.hold),
    }
    (scores_dir / "qwen_warm.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.hold:
        (scores_dir / "qwen_warm_hold.pid").write_text(str(os.getpid()) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
    if args.hold:
        while True:
            time.sleep(3600)


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--panels-csv", default=str(DEFAULT_PANELS_CSV.relative_to(BASE_DIR)))
    parser.add_argument("--scores-dir", default=str(DEFAULT_SCORES_DIR.relative_to(BASE_DIR)))
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--backend", choices=["auto", "transformers", "openai"], default="auto")
    parser.add_argument("--api-base", default="")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--model-name", default="Qwen/Qwen3.6-27B")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--torch-dtype", choices=["bfloat16", "float16", "float32"], default="bfloat16")
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=0.8)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--max-image-edge", type=int, default=1024)
    parser.add_argument("--num-shards", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask Qwen3.6-27B to classify and score panels")
    sub = parser.add_subparsers(dest="command", required=True)
    add_common_args(sub.add_parser("prepare"))
    add_common_args(sub.add_parser("score"))
    p_warm = sub.add_parser("warm")
    add_common_args(p_warm)
    p_warm.add_argument("--hold", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
