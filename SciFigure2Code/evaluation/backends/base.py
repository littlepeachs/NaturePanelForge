"""Backend interface and registry."""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from typing import Any

from ..schemas import GenerationRequest, GenerationResult


class CodeGenerationBackend(ABC):
    name = "base"
    supports_images = False
    supports_multi_images = False
    max_images = 1

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError


def create_backend(name: str, **kwargs: Any) -> CodeGenerationBackend:
    if ":" in name:
        module_name, class_name = name.split(":", 1)
        module = importlib.import_module(module_name)
        backend_cls = getattr(module, class_name)
        return backend_cls(**kwargs)

    normalized = name.strip().lower()
    if normalized == "mock":
        from .mock import MockBackend

        return MockBackend(**kwargs)
    if normalized == "transformers":
        from .transformers_backend import TransformersBackend

        return TransformersBackend(**kwargs)
    if normalized == "chartcoder":
        from .chartcoder import ChartCoderBackend

        return ChartCoderBackend(**kwargs)
    if normalized == "pixtral":
        from .pixtral import PixtralBackend

        return PixtralBackend(**kwargs)
    raise ValueError(f"Unknown backend '{name}'. Use mock, transformers, chartcoder, or module.path:ClassName.")
