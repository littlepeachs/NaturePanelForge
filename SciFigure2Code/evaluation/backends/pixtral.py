"""Pixtral backend using Mistral's native inference stack."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schemas import GenerationRequest, GenerationResult
from .base import CodeGenerationBackend


@dataclass
class PixtralBackend(CodeGenerationBackend):
    model_path: str | Path
    vlm_root: str | Path = os.environ.get("VLM_ROOT", ".models")
    max_new_tokens: int = 4096
    device_map: str | None = "auto"
    gpus: str | None = None
    dtype: str = "bfloat16"
    attn_implementation: str | None = None
    temperature: float = 0.0
    use_image: bool = True
    do_sample: bool = False

    name = "pixtral"
    supports_images = True
    supports_multi_images = True
    max_images = 2

    _model: Any = field(default=None, init=False, repr=False)
    _tokenizer: Any = field(default=None, init=False, repr=False)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self._load()
        image_paths = self._request_image_paths(request)
        text = self._generate_text(request.prompt, image_paths)
        return GenerationResult(
            text=text,
            backend_name=self.name,
            metadata={
                "model_path": str(Path(self.model_path).expanduser()),
                "max_new_tokens": self.max_new_tokens,
                "dtype": self.dtype,
                "use_image": bool(image_paths),
                "image_count": len(image_paths),
                "supports_multi_images": self.supports_multi_images,
            },
        )

    def _configure_environment(self) -> None:
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

        import torch
        from mistral_inference.transformer import Transformer
        from mistral_common.tokens.tokenizers.mistral import MistralTokenizer

        model_path = Path(self.model_path).expanduser()
        self._tokenizer = MistralTokenizer.from_file(str(model_path / "tekken.json"))
        self._model = Transformer.from_folder(
            model_path,
            max_batch_size=1,
            device="cuda" if torch.cuda.is_available() else "cpu",
            dtype=self._dtype_arg(torch),
        )

    def _request_image_paths(self, request: GenerationRequest) -> list[Path]:
        if not self.use_image:
            return []
        image_paths = list(request.image_paths or [])
        if not image_paths and request.image_path:
            image_paths = [request.image_path]
        return image_paths[: self.max_images]

    def _generate_text(self, prompt: str, image_paths: list[Path]) -> str:
        from PIL import Image
        from mistral_inference.generate import generate
        from mistral_common.protocol.instruct.chunk import ImageChunk, TextChunk
        from mistral_common.protocol.instruct.messages import UserMessage
        from mistral_common.protocol.instruct.request import ChatCompletionRequest

        content = []
        for image_path in image_paths:
            content.append(ImageChunk(image=Image.open(image_path).convert("RGB")))
        content.append(TextChunk(text=prompt))

        request = ChatCompletionRequest(messages=[UserMessage(content=content)])
        encoded = self._tokenizer.encode_chat_completion(request)
        out_tokens, _ = generate(
            [encoded.tokens],
            self._model,
            images=[encoded.images],
            max_tokens=self.max_new_tokens,
            temperature=self.temperature if self.do_sample else 0.0,
            eos_id=self._tokenizer.instruct_tokenizer.tokenizer.eos_id,
        )
        return self._tokenizer.decode(out_tokens[0])

    def _dtype_arg(self, torch: Any) -> Any:
        mapping = {
            "auto": None,
            "bfloat16": torch.bfloat16,
            "bf16": torch.bfloat16,
            "float16": torch.float16,
            "fp16": torch.float16,
            "float32": torch.float32,
            "fp32": torch.float32,
        }
        return mapping.get(str(self.dtype).lower(), torch.bfloat16)
