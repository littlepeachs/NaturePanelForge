"""Local model inventory and benchmark capability metadata."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_VLM_ROOT = Path(os.environ.get("VLM_ROOT", ".models")).expanduser()
VLM_MODEL_ROOT = Path(os.environ.get("VLM_MODEL_ROOT", str(DEFAULT_VLM_ROOT / "models"))).expanduser()

ZERO_SHOT_11_MODEL_IDS: tuple[str, ...] = (
    "intern_s2_preview",
    "glm_4_5v",
    "llava_onevision_qwen2_72b",
    "ovis2_6_80b_a3b",
    "phi4_reasoning_vision_15b",
    "molmo_72b",
    "qwen3_5_122b_a10b",
    "gemma4_31b_it",
    "pixtral_12b",
    "chartcoder",
    "chartide_8b",
)


@dataclass(frozen=True)
class LocalModelSpec:
    model_id: str
    rel_path: str
    size_label: str
    model_type: str
    preferred_backend: str
    supports_multi_image: bool
    multi_image_evidence: str
    max_images: int = 1
    adapter_ready: bool = True
    multi_image_verified: bool = False
    notes: str = ""

    @property
    def model_path(self) -> Path:
        return VLM_MODEL_ROOT / self.rel_path

    @property
    def one_shot_image_strategy(self) -> str:
        return "native_multi_image" if self.supports_multi_image else "text_exemplar_single_image"

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_path": self.model_path,
            "size_label": self.size_label,
            "model_type": self.model_type,
            "preferred_backend": self.preferred_backend,
            "supports_multi_image": self.supports_multi_image,
            "max_images": self.max_images,
            "adapter_ready": self.adapter_ready,
            "multi_image_verified": self.multi_image_verified,
            "one_shot_image_strategy": self.one_shot_image_strategy,
            "multi_image_evidence": self.multi_image_evidence,
            "notes": self.notes,
        }


LOCAL_MODEL_SPECS: tuple[LocalModelSpec, ...] = (
    LocalModelSpec(
        "chartcoder",
        "xxxllz/ChartCoder",
        "14G",
        "llava_deepseek",
        "chartcoder",
        False,
        "Current dedicated ChartCoder backend accepts one image tensor.",
        1,
        True,
        False,
        "Scientific chart-to-code specialist baseline.",
    ),
    LocalModelSpec(
        "chartide_8b",
        "Fengx1nn/CharTide-8B",
        "17G",
        "qwen3_vl",
        "transformers",
        True,
        "Qwen3-VL processor supports chat content with multiple image items.",
        2,
        True,
        False,
    ),
    LocalModelSpec(
        "phi4_reasoning_vision_15b",
        "microsoft/Phi-4-reasoning-vision-15B",
        "29G",
        "phi4-siglip",
        "transformers",
        False,
        "Bundled sample_inference.py demonstrates single-image prompts.",
        1,
        True,
        False,
        "Use text exemplar for one-shot until a multi-image Phi adapter is verified.",
    ),
    LocalModelSpec(
        "kimi_vl_a3b_thinking",
        "moonshotai/Kimi-VL-A3B-Thinking-2506",
        "31G",
        "kimi_vl",
        "transformers",
        True,
        "Kimi-VL processor follows multimodal chat content; use native multi-image once environment loads.",
        2,
        False,
        False,
    ),
    LocalModelSpec(
        "pixtral_12b",
        "mistralai/Pixtral-12B-2409",
        "24G",
        "pixtral/mistral",
        "pixtral",
        True,
        "Pixtral architecture is designed for arbitrary interleaved image-text prompts.",
        2,
        True,
        False,
        "Local files use Mistral native format; run with the dedicated Pixtral backend.",
    ),
    LocalModelSpec(
        "gemma4_26b_a4b_it",
        "google/gemma-4-26B-A4B-it",
        "49G",
        "gemma4",
        "transformers",
        True,
        "Gemma vision chat processors accept image content lists; verify with installed transformers.",
        2,
        False,
        False,
    ),
    LocalModelSpec(
        "gemma4_31b_it",
        "google/gemma-4-31B-it",
        "59G",
        "gemma4",
        "transformers",
        True,
        "Gemma vision chat processors accept image content lists; verify with installed transformers.",
        2,
        False,
        False,
    ),
    LocalModelSpec(
        "intern_s2_preview",
        "internlm/Intern-S2-Preview",
        "69G",
        "intern_s2_preview",
        "transformers",
        True,
        "Intern-S series README documents image-text chat templates with multimodal content.",
        2,
        False,
        False,
    ),
    LocalModelSpec(
        "llava_onevision_qwen2_72b",
        "llava-hf/llava-onevision-qwen2-72b-ov-hf",
        "137G",
        "llava_onevision",
        "transformers",
        True,
        "LLaVA-OneVision README explicitly supports single-image, multi-image, and video scenarios.",
        2,
        True,
        False,
    ),
    LocalModelSpec(
        "ovis2_6_80b_a3b",
        "AIDC-AI/Ovis2.6-80B-A3B",
        "151G",
        "ovis2_6_next",
        "transformers",
        True,
        "Ovis multimodal chat format supports interleaved visual inputs; verify on smoke before full runs.",
        2,
        False,
        False,
    ),
    LocalModelSpec(
        "glm_4_5v",
        "zai-org/GLM-4.5V",
        "201G",
        "glm4v_moe",
        "transformers",
        True,
        "GLM vision chat processor accepts multimodal content; verify multi-image on smoke.",
        2,
        True,
        False,
    ),
    LocalModelSpec(
        "qwen3_5_122b_a10b",
        "Qwen/Qwen3.5-122B-A10B",
        "234G",
        "qwen3_5_moe",
        "transformers",
        True,
        "Qwen multimodal processor family supports multi-image chat content.",
        2,
        False,
        False,
        "Current environment may need newer Qwen3.5 support.",
    ),
    LocalModelSpec(
        "molmo_72b",
        "allenai/Molmo-72B-0924",
        "274G",
        "molmo",
        "transformers",
        False,
        "Molmo local processor path is single-image oriented in this checkout.",
        1,
        False,
        False,
        "Use text exemplar for one-shot until a multi-image Molmo adapter is verified.",
    ),
    LocalModelSpec(
        "qwen3_vl_235b_a22b",
        "Qwen/Qwen3-VL-235B-A22B-Instruct",
        "439G",
        "qwen3_vl_moe",
        "transformers",
        True,
        "Qwen3-VL-MoE processor supports chat content with multiple image items.",
        2,
        True,
        False,
    ),
    LocalModelSpec(
        "internvl3_5_241b_a28b",
        "OpenGVLab/InternVL3_5-241B-A28B",
        "449G",
        "internvl_chat",
        "transformers",
        True,
        "InternVL chat models support multi-image conversations in the InternVL family.",
        2,
        False,
        False,
    ),
    LocalModelSpec(
        "intern_s1",
        "internlm/Intern-S1",
        "449G",
        "interns1",
        "transformers",
        True,
        "Intern-S1 README documents multimodal chat templates and image content.",
        2,
        False,
        False,
    ),
)


def local_model_specs() -> list[LocalModelSpec]:
    return list(LOCAL_MODEL_SPECS)


def zero_shot_11_model_specs() -> list[LocalModelSpec]:
    by_id = {spec.model_id: spec for spec in LOCAL_MODEL_SPECS}
    return [by_id[model_id] for model_id in ZERO_SHOT_11_MODEL_IDS]


def get_model_spec(model_id_or_path: str | Path | None) -> LocalModelSpec | None:
    if model_id_or_path is None:
        return None
    value = str(model_id_or_path)
    path = Path(value).expanduser()
    for spec in LOCAL_MODEL_SPECS:
        if value == spec.model_id or value == spec.rel_path:
            return spec
        try:
            if path.resolve() == spec.model_path.resolve():
                return spec
        except Exception:
            pass
    return None


def prompt_modes() -> tuple[str, ...]:
    return ("zeroshot", "cot", "oneshot", "oneshot_cot")
