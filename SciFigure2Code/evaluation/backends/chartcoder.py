"""ChartCoder backend using the official LLaVA-style loader."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schemas import GenerationRequest, GenerationResult
from .base import CodeGenerationBackend


@dataclass
class ChartCoderBackend(CodeGenerationBackend):
    model_path: str | Path
    chartcoder_repo: str | Path = os.environ.get("CHARTCODER_REPO", ".deps/ChartCoder")
    vlm_root: str | Path = os.environ.get("VLM_ROOT", ".models")
    max_new_tokens: int = 4096
    device_map: str | None = "auto"
    gpus: str | None = None
    attn_implementation: str | None = "sdpa"
    temperature: float = 0.0
    top_p: float = 0.95
    use_image: bool = True

    name = "chartcoder"
    supports_images = True
    supports_multi_images = False
    max_images = 1

    _model: Any = field(default=None, init=False, repr=False)
    _tokenizer: Any = field(default=None, init=False, repr=False)
    _image_processor: Any = field(default=None, init=False, repr=False)
    _context_len: int | None = field(default=None, init=False, repr=False)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self._load()
        image_path = request.image_path if self.use_image else None
        if self.use_image and request.image_paths:
            image_path = request.image_paths[-1]
        text = self._generate_text(request.prompt, image_path)
        return GenerationResult(
            text=text,
            backend_name=self.name,
            metadata={
                "model_path": str(Path(self.model_path).expanduser()),
                "chartcoder_repo": str(Path(self.chartcoder_repo).expanduser()),
                "max_new_tokens": self.max_new_tokens,
                "device_map": self.device_map,
                "attn_implementation": self.attn_implementation,
                "use_image": bool(image_path),
                "image_count": 1 if image_path else 0,
                "supports_multi_images": self.supports_multi_images,
                "context_len": self._context_len,
            },
        )

    def _configure_environment(self) -> None:
        chartcoder_repo = Path(self.chartcoder_repo).expanduser()
        if str(chartcoder_repo) not in sys.path:
            sys.path.insert(0, str(chartcoder_repo))
        vlm_root = Path(self.vlm_root).expanduser()
        if self.gpus:
            os.environ.setdefault("CUDA_VISIBLE_DEVICES", self.gpus)
        os.environ.setdefault("HF_HOME", str(vlm_root / ".cache" / "huggingface"))
        os.environ.setdefault("HF_HUB_CACHE", str(vlm_root / ".cache" / "huggingface" / "hub"))
        os.environ.setdefault("HF_XET_CACHE", str(vlm_root / ".cache" / "huggingface" / "xet"))
        os.environ.setdefault("HF_ASSETS_CACHE", str(vlm_root / ".cache" / "huggingface" / "assets"))

    def _load(self) -> None:
        if self._model is not None:
            return
        self._configure_environment()

        from llava.model.builder import load_pretrained_model

        tokenizer, model, image_processor, context_len = load_pretrained_model(
            str(Path(self.model_path).expanduser()),
            None,
            "llava_deepseekcoder",
            device_map=self.device_map or "auto",
            attn_implementation=self.attn_implementation or "sdpa",
        )
        model.eval()
        self._tokenizer = tokenizer
        self._model = model
        self._image_processor = image_processor
        self._context_len = context_len

    def _generate_text(self, prompt: str, image_path: Path | None) -> str:
        import torch
        from PIL import Image
        from llava.constants import DEFAULT_IMAGE_TOKEN, IMAGE_TOKEN_INDEX
        from llava.mm_utils import process_images, tokenizer_image_token

        device = next(self._model.parameters()).device
        dtype = next(self._model.parameters()).dtype
        if image_path:
            image = Image.open(image_path).convert("RGB")
            chartcoder_prompt = f"### Instruction:\n{DEFAULT_IMAGE_TOKEN}\n{prompt}\n### Response:\n"
            input_ids = tokenizer_image_token(
                chartcoder_prompt,
                self._tokenizer,
                IMAGE_TOKEN_INDEX,
                return_tensors="pt",
            ).unsqueeze(0).to(device)
            image_tensor = process_images([image], self._image_processor, self._model.config)[0]
            images = image_tensor.unsqueeze(0).to(device=device, dtype=dtype)
            image_sizes = [image.size]
        else:
            chartcoder_prompt = f"### Instruction:\n{prompt}\n### Response:\n"
            input_ids = self._tokenizer(chartcoder_prompt, return_tensors="pt").input_ids.to(device)
            images = None
            image_sizes = None

        generate_kwargs: dict[str, Any] = {
            "do_sample": self.temperature > 0,
            "max_new_tokens": self.max_new_tokens,
            "use_cache": True,
        }
        if self.temperature > 0:
            generate_kwargs["temperature"] = self.temperature
            generate_kwargs["top_p"] = self.top_p
        if images is not None:
            generate_kwargs["images"] = images
            generate_kwargs["image_sizes"] = image_sizes

        with torch.inference_mode():
            output_ids = self._model.generate(input_ids, **generate_kwargs)

        return self._tokenizer.batch_decode(output_ids, skip_special_tokens=True)[0].strip()
