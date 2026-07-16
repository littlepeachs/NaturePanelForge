"""Prompt construction for figure-to-code generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .schemas import Sample
from .utils import read_text_limited


@dataclass
class PromptConfig:
    style: str = "short"
    mode: str = "zeroshot"
    supports_multi_image: bool = False
    include_caption: bool = True
    include_description: bool = True
    include_complexity_reason: bool = True
    max_caption_chars: int = 2500
    max_description_chars: int = 3000
    max_one_shot_code_chars: int = 32000
    max_cot_reasoning_chars: int = 8000
    cot_reasoning_tokens: int = 768


@dataclass(frozen=True)
class PromptBundle:
    prompt: str
    image_paths: list[Path]
    image_roles: list[str]
    mode: str
    style: str
    one_shot_strategy: str = "none"
    exemplar_panel_id: str = ""
    exemplar_image_path: Path | None = None
    target_image_path: Path | None = None


SHORT_IMAGE_ONLY_PROMPT = """You are given one scientific figure panel image. Write a complete, self-contained Python script that recreates it as a new plotted figure.

Requirements:
- Return only executable Python code. No markdown, no explanation, and no repeated prompt text.
- Use only Python standard-library modules plus numpy, pandas, matplotlib, and seaborn. Do not import specialized third-party plotting packages such as matplotlib_venn, upsetplot, plotly, bokeh, altair, graphviz, cartopy, geopandas, or networkx.
- Do not load, copy, trace, crop, modify, or sample pixels from the input image. Do not use PIL, OpenCV, skimage, imageio, plt.imread, or mpimg.imread to read the target image.
- Do not recreate the figure by painting individual pixels or raster blocks. Use plotting primitives and generated or estimated numeric data; synthetic data are acceptable when exact values are unavailable.
- Match the figure as closely as possible, including chart type, layout, data trends, axes, ticks, labels, legend or colorbar, annotations, fonts, colors, and overall style.
- The code must run in an empty working directory.
- The generated Python code must start with import os as the very first line.
- Do not put comments, markdown fences, future imports, or any other code before import os.
- Use a non-interactive backend such as matplotlib.use("Agg").
- Do not enable external LaTeX rendering. Never set text.usetex to True; use matplotlib mathtext for math labels.
- Matplotlib numeric style parameters must be numbers, not strings. For example, write lw=2 and s=10 instead of lw="2" or s="10".
- If using seaborn, pass x and y as keyword arguments, for example sns.lineplot(x=x, y=y, ax=ax), not sns.lineplot(x, y, ax=ax).
- Do not call plt.show().
- At the end of the generated Python script, after all plotting commands, save the final figure to both required paths. The generated code must end with these four executable lines:
  png_path = os.environ.get("SCIFIGURE_CANDIDATE_PNG", "candidate.png")
  pdf_path = os.environ.get("SCIFIGURE_CANDIDATE_PDF", "candidate.pdf")
  fig.savefig(png_path, dpi=200, bbox_inches="tight")
  fig.savefig(pdf_path, bbox_inches="tight")

Return the Python script now. The answer is invalid if it repeats the prompt, uses plt.show(), does not start with import os, or does not end with the four required savefig lines.
"""


def build_prompt_bundle(
    sample: Sample,
    config: PromptConfig | None = None,
    one_shot_sample: Sample | None = None,
) -> PromptBundle:
    config = config or PromptConfig()
    mode = _normalize_mode(config.mode)
    base_prompt = _build_base_prompt(sample, config)
    prompt = _apply_mode_instructions(base_prompt, mode)
    images = [sample.target_png] if sample.target_png else []
    image_roles = ["target"] if sample.target_png else []
    one_shot_strategy = "none"
    exemplar_id = ""
    exemplar_image_path = None

    if mode in {"oneshot", "oneshot_cot"}:
        if one_shot_sample is None:
            raise ValueError(f"prompt mode {mode} requires one_shot_sample")
        exemplar_id = one_shot_sample.panel_id
        exemplar_code = _one_shot_code(one_shot_sample, config.max_one_shot_code_chars)
        exemplar_image_path = _one_shot_image(one_shot_sample)
        if config.supports_multi_image:
            one_shot_strategy = "native_multi_image"
            images = [exemplar_image_path] + images
            image_roles = ["one_shot_exemplar"] + image_roles
            prompt = _prepend_native_one_shot(prompt, exemplar_code)
        else:
            if not sample.target_png:
                raise ValueError(f"target sample {sample.panel_id} has no target image for one-shot mode")
            one_shot_strategy = "tiled_single_image"
            images = [sample.target_png]
            image_roles = ["one_shot_exemplar_and_target_tile"]
            prompt = _prepend_tiled_one_shot(prompt, one_shot_sample, exemplar_code)

    return PromptBundle(
        prompt=prompt,
        image_paths=[path for path in images if path is not None],
        image_roles=image_roles,
        mode=mode,
        style=config.style,
        one_shot_strategy=one_shot_strategy,
        exemplar_panel_id=exemplar_id,
        exemplar_image_path=exemplar_image_path,
        target_image_path=sample.target_png,
    )


def materialize_prompt_bundle(bundle: PromptBundle, artifact_dir: Path) -> PromptBundle:
    """Create deferred prompt artifacts, such as a single-image ICL tile."""

    if bundle.one_shot_strategy != "tiled_single_image":
        return bundle
    if not bundle.exemplar_image_path or not bundle.target_image_path:
        raise ValueError("tiled one-shot mode requires both exemplar and target image paths")
    output_path = Path(artifact_dir) / "icl_exemplar_target.png"
    _write_icl_tile(bundle.exemplar_image_path, bundle.target_image_path, output_path)
    return replace(
        bundle,
        image_paths=[output_path],
        image_roles=["one_shot_exemplar_and_target_tile"],
    )


def build_cot_reasoning_prompt(bundle: PromptBundle) -> str:
    """Build the first, reasoning-only turn of the two-stage CoT protocol."""

    image_context = "the attached target scientific figure panel"
    if bundle.one_shot_strategy == "native_multi_image":
        image_context = "Image 2, the target panel; Image 1 is the one-shot exemplar"
    elif bundle.one_shot_strategy == "tiled_single_image":
        image_context = "the TARGET region of the attached tile; EXAMPLE is the one-shot exemplar"
    return (
        "You are in the reasoning stage of a scientific figure-to-code task.\n"
        f"Study {image_context}.\n"
        "Produce a concise, concrete reconstruction plan before any code is written. Cover:\n"
        "1. chart type and panel layout;\n"
        "2. axes, scales, ticks, labels, and ranges;\n"
        "3. data series, approximate trends, colors, and markers;\n"
        "4. legends, colorbars, annotations, and typography;\n"
        "5. the matplotlib construction order and likely failure points.\n"
        "Do not output Python code or markdown code fences in this stage. "
        "End with the exact marker PLAN_COMPLETE.\n"
    )


def build_cot_answer_prompt(base_prompt: str, reasoning: str, max_chars: int = 8000) -> str:
    """Inject the separately generated reasoning into the final code turn."""

    plan = (reasoning or "").strip()
    if not plan:
        raise ValueError("CoT reasoning stage returned no text")
    if len(plan) > max_chars:
        plan = plan[:max_chars].rstrip() + "\n...[reasoning truncated]"
    return (
        base_prompt.rstrip()
        + "\n\nA separate reasoning turn produced the following reconstruction plan:\n"
        + "<reconstruction_plan>\n"
        + plan
        + "\n</reconstruction_plan>\n\n"
        + "Follow this plan, but now return only the final executable Python script. "
        + "Do not repeat or discuss the plan.\n"
    )


def build_prompt(sample: Sample, config: PromptConfig | None = None) -> str:
    return build_prompt_bundle(sample, config).prompt


def _build_base_prompt(sample: Sample, config: PromptConfig) -> str:
    if config.style == "short":
        return SHORT_IMAGE_ONLY_PROMPT

    metadata = sample.metadata_for_prompt()
    sections: list[str] = [SHORT_IMAGE_ONLY_PROMPT.rstrip()]
    if config.style in {"metadata", "full"}:
        sections.extend(["", "Sample metadata:"])
        for key, value in metadata.items():
            if value not in (None, ""):
                sections.append(f"- {key}: {value}")

    if config.style in {"metadata", "full"} and sample.content_summary:
        sections.extend(["", "Panel content summary:", sample.content_summary])
    if config.style == "full" and config.include_complexity_reason and sample.complexity_reason:
        sections.extend(["", "Complexity note:", sample.complexity_reason])
    if config.style == "full" and config.include_caption and sample.caption:
        caption = sample.caption[: config.max_caption_chars]
        if len(sample.caption) > config.max_caption_chars:
            caption += "\n...[truncated]"
        sections.extend(["", "Figure caption:", caption])
    if config.style == "full" and config.include_description and sample.description_md:
        description = read_text_limited(sample.description_md, config.max_description_chars)
        if description:
            sections.extend(["", "Dataset description markdown:", description])

    return "\n".join(sections).strip() + "\n"


def _normalize_mode(mode: str) -> str:
    normalized = str(mode or "zeroshot").strip().lower().replace("-", "_")
    aliases = {
        "zero_shot": "zeroshot",
        "zero": "zeroshot",
        "zs": "zeroshot",
        "chain_of_thought": "cot",
        "one_shot": "oneshot",
        "os": "oneshot",
        "icl": "oneshot",
        "one_shot_cot": "oneshot_cot",
        "oneshot+cot": "oneshot_cot",
        "one-shot+cot": "oneshot_cot",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"zeroshot", "cot", "oneshot", "oneshot_cot"}:
        raise ValueError(f"Unsupported prompt mode: {mode}")
    return normalized


def _apply_mode_instructions(prompt: str, mode: str) -> str:
    if mode in {"cot", "oneshot_cot"}:
        return (
            prompt.rstrip()
            + "\n\nCoT protocol: the evaluator will first run a separate reasoning turn, then "
            + "provide that plan back to you for this final code-only answer.\n"
        )
    return prompt


def _prepend_native_one_shot(prompt: str, exemplar_code: str) -> str:
    prefix = (
        "One-shot example:\n"
        "- Image 1 is an example scientific figure panel.\n"
        "- The reference Python code for Image 1 is below.\n"
        "- Image 2 is the target figure panel you must redraw now.\n\n"
        "Reference code for Image 1:\n"
        "```python\n"
        f"{exemplar_code.rstrip()}\n"
        "```\n\n"
        "Now write code for Image 2 only.\n\n"
    )
    return prefix + prompt


def _prepend_tiled_one_shot(prompt: str, exemplar: Sample, exemplar_code: str) -> str:
    prefix = (
        "One-shot example for a model interface that accepts one image:\n"
        "- The attached image is a tile with two labeled regions.\n"
        "- EXAMPLE is the reference figure corresponding to the Python code below.\n"
        "- TARGET is the scientific figure panel you must redraw now.\n"
        f"- Example panel id: {exemplar.panel_id}\n"
        f"- Example chart subtype: {exemplar.subtype}\n"
        "- Use the example image-code mapping as guidance, but write code for TARGET only.\n\n"
        "Reference example code:\n"
        "```python\n"
        f"{exemplar_code.rstrip()}\n"
        "```\n\n"
    )
    return prefix + prompt


def _one_shot_code(sample: Sample, max_chars: int) -> str:
    if sample.reference_code and sample.reference_code.exists():
        code = sample.reference_code.read_text(encoding="utf-8", errors="replace")
        code = _sanitize_one_shot_code(code)
        if len(code) <= max_chars:
            return code
        return code[:max_chars].rstrip() + "\n# ...[reference code truncated for prompt length]\n"
    raise ValueError(f"one-shot exemplar {sample.panel_id} has no readable reference code")


def _one_shot_image(sample: Sample) -> Path:
    if sample.reference_png and sample.reference_png.exists():
        return sample.reference_png
    raise ValueError(f"one-shot exemplar {sample.panel_id} has no readable reference image")


def _write_icl_tile(exemplar_path: Path, target_path: Path, output_path: Path) -> None:
    from PIL import Image, ImageDraw, ImageOps

    cell_size = (1024, 1024)
    header_height = 52
    background = (255, 255, 255)
    canvas = Image.new("RGB", (cell_size[0] * 2, cell_size[1] + header_height), background)
    draw = ImageDraw.Draw(canvas)
    draw.text((16, 17), "EXAMPLE", fill=(0, 0, 0))
    draw.text((cell_size[0] + 16, 17), "TARGET", fill=(0, 0, 0))
    draw.line((cell_size[0], 0, cell_size[0], canvas.height), fill=(80, 80, 80), width=3)

    for column, path in enumerate((exemplar_path, target_path)):
        with Image.open(path) as source:
            fitted = ImageOps.contain(source.convert("RGB"), cell_size)
        x0 = column * cell_size[0] + (cell_size[0] - fitted.width) // 2
        y0 = header_height + (cell_size[1] - fitted.height) // 2
        canvas.paste(fitted, (x0, y0))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=True)


def _sanitize_one_shot_code(code: str) -> str:
    code = code.replace("\r\n", "\n").replace("\r", "\n")
    code = re.sub(r"\nOUT_DIR\s*=\s*Path\(\s*.*?\)\s*\n", "\n", code, flags=re.DOTALL)
    code = re.sub(
        r"(?m)^PNG_PATH\s*=.*$",
        'PNG_PATH = os.environ.get("SCIFIGURE_CANDIDATE_PNG", "candidate.png")',
        code,
    )
    code = re.sub(
        r"(?m)^PDF_PATH\s*=.*$",
        'PDF_PATH = os.environ.get("SCIFIGURE_CANDIDATE_PDF", "candidate.pdf")',
        code,
    )

    def scrub_local_path(match: re.Match[str]) -> str:
        quote = match.group("quote")
        return f"{quote}.{quote}"

    return re.sub(
        r"(?P<quote>[\"'])/(?:ssd\d*|home|mnt|data)[^\"']*(?P=quote)",
        scrub_local_path,
        code,
    ).strip()
