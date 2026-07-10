"""Generic local Hugging Face transformers backend skeleton for VLMs."""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schemas import GenerationRequest, GenerationResult
from .base import CodeGenerationBackend


@dataclass
class TransformersBackend(CodeGenerationBackend):
    """Load a local VLM/text model with transformers and generate code.

    The loader is deliberately generic so it can point at any local model
    directory. For model families with custom helper APIs, add a new backend
    class and keep this one as the common fallback.
    """

    model_path: str | Path
    vlm_root: str | Path = os.environ.get("VLM_ROOT", ".models")
    max_new_tokens: int = 4096
    device_map: str | None = "auto"
    dtype: str = "auto"
    gpus: str | None = None
    attn_implementation: str | None = None
    trust_remote_code: bool = True
    do_sample: bool = False
    temperature: float = 0.0
    use_image: bool = True
    supports_multi_images: bool = True
    extra_generate_kwargs: dict[str, Any] = field(default_factory=dict)

    name = "transformers"
    supports_images = True
    max_images = 2

    _model: Any = field(default=None, init=False, repr=False)
    _processor: Any = field(default=None, init=False, repr=False)
    _tokenizer: Any = field(default=None, init=False, repr=False)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self._load()
        image_paths = self._request_image_paths(request)
        if self._is_molmo():
            return self._generate_molmo(request.prompt, image_paths)
        if self._is_ovis():
            return self._generate_ovis(request.prompt, image_paths)

        chat_text = self._build_chat_text(request.prompt, image_paths)
        inputs = self._build_inputs(chat_text, image_paths)

        import torch

        inputs = self._move_batch_to_device(inputs, self._first_parameter_device(torch))
        input_len = inputs["input_ids"].shape[-1] if isinstance(inputs, dict) and "input_ids" in inputs else None
        generate_kwargs: dict[str, Any] = {
            "max_new_tokens": self.max_new_tokens,
            "do_sample": self.do_sample,
        }
        if self.do_sample and self.temperature:
            generate_kwargs["temperature"] = self.temperature
        generate_kwargs.update(self.extra_generate_kwargs)

        with torch.inference_mode():
            output_ids = self._model.generate(**inputs, **generate_kwargs)

        text = self._decode(output_ids, input_len)
        return GenerationResult(
            text=text,
            backend_name=self.name,
            metadata={
                "model_path": str(Path(self.model_path).expanduser()),
                "max_new_tokens": self.max_new_tokens,
                "device_map": self.device_map,
                "dtype": self.dtype,
                "use_image": bool(image_paths),
                "image_count": len(image_paths),
                "supports_multi_images": self.supports_multi_images,
            },
        )

    def _is_molmo(self) -> bool:
        config = getattr(self._model, "config", None)
        model_type = str(getattr(config, "model_type", "") or "").lower()
        model_path = str(Path(self.model_path).expanduser()).lower()
        return (
            (model_type == "molmo" or "molmo" in model_path or hasattr(self._model, "generate_from_batch"))
            and hasattr(self._processor, "process")
            and hasattr(self._model, "generate_from_batch")
        )

    def _is_ovis(self) -> bool:
        config = getattr(self._model, "config", None)
        model_type = str(getattr(config, "model_type", "") or "").lower()
        model_path = str(Path(self.model_path).expanduser()).lower()
        return model_type.startswith("ovis2_6") or "ovis2.6" in model_path or "ovis2_6" in model_path

    def _generate_molmo(self, prompt: str, image_paths: list[Path]) -> GenerationResult:
        """Run AllenAI Molmo through its native processor/generate API."""

        import torch
        from PIL import Image
        from transformers import GenerationConfig

        images = None
        if image_paths:
            images = [Image.open(image_paths[0]).convert("RGB")]

        inputs = self._processor.process(images=images, text=prompt)
        device = getattr(self._model, "device", None) or self._first_parameter_device(torch)
        batch = {}
        for key, value in inputs.items():
            if hasattr(value, "to"):
                value = value.to(device)
                if key == "images" and str(self.dtype).lower() in {"bfloat16", "bf16"}:
                    value = value.to(torch.bfloat16)
                value = value.unsqueeze(0)
            batch[key] = value

        generation_config = GenerationConfig(
            max_new_tokens=self.max_new_tokens,
            do_sample=self.do_sample,
            stop_strings="<|endoftext|>",
        )
        if self.do_sample and self.temperature:
            generation_config.temperature = self.temperature

        with torch.inference_mode(), torch.autocast(device_type="cuda", enabled=torch.cuda.is_available(), dtype=torch.bfloat16):
            output_ids = self._model.generate_from_batch(
                batch,
                generation_config,
                tokenizer=self._processor.tokenizer,
                **self.extra_generate_kwargs,
            )

        input_len = batch["input_ids"].shape[-1]
        generated_tokens = output_ids[0, input_len:]
        text = self._processor.tokenizer.decode(generated_tokens, skip_special_tokens=True)
        return GenerationResult(
            text=self._strip_chat_echo(text),
            backend_name=self.name,
            metadata={
                "model_path": str(Path(self.model_path).expanduser()),
                "max_new_tokens": self.max_new_tokens,
                "device_map": self.device_map,
                "dtype": self.dtype,
                "use_image": bool(images),
                "image_count": len(images or []),
                "supports_multi_images": False,
                "molmo_native_generate": True,
            },
        )

    def _generate_ovis(self, prompt: str, image_paths: list[Path]) -> GenerationResult:
        """Run Ovis2.6 through its native preprocess_inputs/generate API."""

        import torch
        from PIL import Image

        content: list[dict[str, Any]] = []
        for image_path in image_paths:
            content.append({"type": "image", "image": Image.open(image_path).convert("RGB")})
        content.append({"type": "text", "text": prompt})
        messages = [{"role": "user", "content": content if image_paths else prompt}]

        input_ids, pixel_values, grid_thws = self._model.preprocess_inputs(
            messages=messages,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        device = self._first_parameter_device(torch)
        input_ids = input_ids.to(device)
        if pixel_values is not None:
            pixel_values = pixel_values.to(device)
        if grid_thws is not None:
            grid_thws = grid_thws.to(device)

        generate_kwargs: dict[str, Any] = {
            "max_new_tokens": self.max_new_tokens,
            "do_sample": self.do_sample,
            "enable_thinking": False,
            "enable_thinking_budget": False,
        }
        if self.do_sample and self.temperature:
            generate_kwargs["temperature"] = self.temperature
        generate_kwargs.update(self.extra_generate_kwargs)

        with torch.inference_mode():
            output_ids = self._model.generate(
                inputs=input_ids,
                pixel_values=pixel_values,
                grid_thws=grid_thws,
                **generate_kwargs,
            )

        text = self._model.text_tokenizer.decode(output_ids[0], skip_special_tokens=True)
        return GenerationResult(
            text=self._strip_chat_echo(text),
            backend_name=self.name,
            metadata={
                "model_path": str(Path(self.model_path).expanduser()),
                "max_new_tokens": self.max_new_tokens,
                "device_map": self.device_map,
                "dtype": self.dtype,
                "use_image": bool(image_paths),
                "image_count": len(image_paths),
                "supports_multi_images": self.supports_multi_images,
                "ovis_native_generate": True,
            },
        )

    def _request_image_paths(self, request: GenerationRequest) -> list[Path]:
        if not self.use_image:
            return []
        image_paths = list(request.image_paths or [])
        if not image_paths and request.image_path:
            image_paths = [request.image_path]
        if not self.supports_multi_images and len(image_paths) > 1:
            return [image_paths[-1]]
        return image_paths

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
        import transformers
        from transformers import AutoProcessor, AutoTokenizer

        model_path = Path(self.model_path).expanduser()
        self._patch_transformers_compat(torch, transformers)
        self._patch_local_remote_model_compat(model_path, transformers)
        processor_errors = []
        try:
            self._processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=self.trust_remote_code)
        except Exception as exc:
            processor_errors.append(f"AutoProcessor: {exc}")
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=self.trust_remote_code)
        except Exception as exc:
            processor_errors.append(f"AutoTokenizer: {exc}")
        if self._processor is None and self._tokenizer is None:
            raise RuntimeError("Could not load processor or tokenizer:\n" + "\n".join(processor_errors))

        kwargs: dict[str, Any] = {"trust_remote_code": self.trust_remote_code}
        if self.device_map:
            kwargs["device_map"] = self.device_map
        if self.dtype:
            kwargs["torch_dtype"] = self._dtype_arg(torch)
        if self.attn_implementation:
            kwargs["attn_implementation"] = self.attn_implementation

        loader_names = [
            "AutoModelForImageTextToText",
            "AutoModelForVision2Seq",
            "AutoModelForCausalLM",
            "AutoModel",
        ]
        if self._is_gemma4_path(model_path):
            loader_names.insert(0, "AutoModelForMultimodalLM")

        errors = []
        for loader_name in loader_names:
            loader = getattr(transformers, loader_name, None)
            if loader is None:
                continue
            try:
                self._model = loader.from_pretrained(model_path, **kwargs)
                self._model.eval()
                return
            except Exception as exc:
                errors.append(f"{loader_name}: {exc}")
        raise RuntimeError("Could not load model. Tried:\n" + "\n".join(errors))

    @staticmethod
    def _patch_transformers_compat(torch: Any, transformers: Any) -> None:
        """Patch small remote-code compatibility gaps across local envs."""

        activations = getattr(transformers, "activations", None)
        if activations is not None and not hasattr(activations, "PytorchGELUTanh"):
            class PytorchGELUTanh(torch.nn.GELU):
                def __init__(self) -> None:
                    super().__init__(approximate="tanh")

            activations.PytorchGELUTanh = PytorchGELUTanh
        utils = getattr(transformers, "utils", None)
        if utils is not None and not hasattr(utils, "is_flash_attn_greater_or_equal_2_10"):
            utils.is_flash_attn_greater_or_equal_2_10 = lambda: False
        try:
            from transformers.utils import import_utils

            if not hasattr(import_utils, "is_torch_fx_available"):
                import_utils.is_torch_fx_available = lambda: True
        except Exception:
            pass
        pre_trained_model = getattr(transformers, "PreTrainedModel", None)
        if pre_trained_model is not None:
            if not hasattr(pre_trained_model, "is_parallelizable"):
                pre_trained_model.is_parallelizable = False
            if not hasattr(pre_trained_model, "all_tied_weights_keys"):
                pre_trained_model.all_tied_weights_keys = {}
            for attr in ("_supports_sdpa", "_supports_flash_attn_2", "_supports_flex_attn"):
                if not hasattr(pre_trained_model, attr):
                    setattr(pre_trained_model, attr, False)
        try:
            from transformers.cache_utils import Cache

            if not hasattr(Cache, "get_usable_length"):
                def get_usable_length(self, new_seq_length: int, layer_idx: int = 0) -> int:
                    return self.get_seq_length(layer_idx)

                Cache.get_usable_length = get_usable_length
        except Exception:
            pass
        try:
            from transformers.models.qwen3_next.modeling_qwen3_next import Qwen3NextForCausalLM

            if not hasattr(Qwen3NextForCausalLM, "is_parallelizable"):
                Qwen3NextForCausalLM.is_parallelizable = False
        except Exception:
            pass

    @staticmethod
    def _patch_local_remote_model_compat(model_path: Path, transformers: Any) -> None:
        """Patch remote-code model classes before AutoModel.from_pretrained loads weights."""

        try:
            config = json.loads((model_path / "config.json").read_text())
        except Exception:
            return
        model_type = str(config.get("model_type") or "").lower()
        auto_map = config.get("auto_map") or {}
        if not (model_type.startswith("ovis2_6") or "modeling_ovis2_6" in json.dumps(auto_map)):
            return

        try:
            from transformers.dynamic_module_utils import get_class_from_dynamic_module
        except Exception:
            return

        class_refs = {
            ref
            for ref in auto_map.values()
            if isinstance(ref, str) and ref.startswith("modeling_ovis2_6.")
        }
        class_refs.update(
            {
                "modeling_ovis2_6.Ovis2_6ForCausalLM",
                "modeling_ovis2_6.Ovis2_6_MoeForCausalLM",
                "modeling_ovis2_6.Ovis2_6_NextForCausalLM",
            }
        )

        def compatible_tie_weights(self: Any, *args: Any, **kwargs: Any) -> Any:
            llm = getattr(self, "llm", None)
            if llm is not None and hasattr(llm, "tie_weights"):
                try:
                    return llm.tie_weights(*args, **kwargs)
                except TypeError:
                    return llm.tie_weights()
            return None

        compatible_tie_weights._scifigurehub_compat = True  # type: ignore[attr-defined]
        for class_ref in sorted(class_refs):
            try:
                klass = get_class_from_dynamic_module(
                    class_ref,
                    model_path,
                    local_files_only=True,
                    trust_remote_code=True,
                )
            except Exception:
                continue
            current = getattr(klass, "tie_weights", None)
            if getattr(current, "_scifigurehub_compat", False):
                continue
            klass.tie_weights = compatible_tie_weights

    def _config_model_type(self, model_path: Path | None = None) -> str:
        config = getattr(self._model, "config", None)
        model_type = str(getattr(config, "model_type", "") or "").lower()
        if model_type:
            return model_type
        path = Path(model_path or self.model_path).expanduser()
        try:
            data = json.loads((path / "config.json").read_text())
            return str(data.get("model_type", "") or "").lower()
        except Exception:
            return ""

    def _is_gemma4_path(self, model_path: Path) -> bool:
        path_text = str(model_path).lower()
        return self._config_model_type(model_path) == "gemma4" or "gemma-4" in path_text or "gemma4" in path_text

    def _is_phi4(self) -> bool:
        path_text = str(Path(self.model_path).expanduser()).lower()
        model_type = self._config_model_type()
        return "phi4" in model_type or "phi-4" in path_text or "phi4" in path_text

    def _is_kimi(self) -> bool:
        path_text = str(Path(self.model_path).expanduser()).lower()
        model_type = self._config_model_type()
        return "kimi" in model_type or "kimi-vl" in path_text or "kimi_vl" in path_text

    def _dtype_arg(self, torch: Any) -> Any:
        mapping = {
            "auto": "auto",
            "bfloat16": torch.bfloat16,
            "bf16": torch.bfloat16,
            "float16": torch.float16,
            "fp16": torch.float16,
            "float32": torch.float32,
            "fp32": torch.float32,
        }
        return mapping.get(str(self.dtype).lower(), "auto")

    def _build_chat_text(self, prompt: str, image_paths: list[Path]) -> str:
        if self._is_phi4():
            content = f"<image>\n{prompt}" if image_paths else prompt
            messages = [{"role": "user", "content": content}]
            templater = getattr(self._processor, "tokenizer", None) or self._tokenizer
            if templater is not None and hasattr(templater, "apply_chat_template"):
                try:
                    return self._apply_chat_template(templater, messages)
                except Exception:
                    return content
            return content

        if image_paths:
            content = [{"type": "image", "image": str(path)} for path in image_paths]
            content.append({"type": "text", "text": prompt})
            messages = [
                {
                    "role": "user",
                    "content": content,
                }
            ]
        else:
            messages = [{"role": "user", "content": prompt}]

        templater = self._processor if hasattr(self._processor, "apply_chat_template") else self._tokenizer
        if templater is not None and hasattr(templater, "apply_chat_template"):
            try:
                return self._apply_chat_template(templater, messages)
            except Exception:
                fallback = [{"role": "user", "content": prompt}]
                try:
                    return self._apply_chat_template(templater, fallback)
                except Exception:
                    return prompt
        return prompt

    @staticmethod
    def _apply_chat_template(templater: Any, messages: list[dict[str, Any]]) -> str:
        """Apply chat templates while disabling Qwen-style thinking when supported."""

        try:
            return templater.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            return templater.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    def _build_inputs(self, text: str, image_paths: list[Path]) -> Any:
        images = None
        if image_paths:
            from PIL import Image

            images = [Image.open(path).convert("RGB") for path in image_paths]

        if self._processor is not None:
            if self._is_phi4():
                return self._processor(text=text, images=images, return_tensors="pt")
            attempts = []
            if images is not None:
                attempts.extend(
                    [
                        lambda: self._processor(text=[text], images=images, return_tensors="pt"),
                        lambda: self._processor(images=images, text=[text], return_tensors="pt"),
                        lambda: self._processor(text, images=images, return_tensors="pt"),
                    ]
                )
            attempts.extend(
                [
                    lambda: self._processor(text=[text], return_tensors="pt"),
                    lambda: self._processor(text, return_tensors="pt"),
                ]
            )
            for attempt in attempts:
                try:
                    return attempt()
                except Exception:
                    continue

        if self._tokenizer is None:
            raise RuntimeError("Neither processor nor tokenizer could build inputs.")
        return self._tokenizer(text, return_tensors="pt")

    def _first_parameter_device(self, torch: Any) -> Any:
        try:
            return next(self._model.parameters()).device
        except StopIteration:
            return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    @staticmethod
    def _move_batch_to_device(batch: Any, device: Any) -> Any:
        if hasattr(batch, "to"):
            try:
                return batch.to(device)
            except Exception:
                pass
        if not isinstance(batch, dict):
            return batch
        for key, value in list(batch.items()):
            if hasattr(value, "to"):
                batch[key] = value.to(device)
        return batch

    def _decode(self, output_ids: Any, input_len: int | None) -> str:
        new_tokens = output_ids
        try:
            if input_len and output_ids.shape[-1] > input_len:
                new_tokens = output_ids[:, input_len:]
        except Exception:
            pass
        if self._is_phi4() and self._tokenizer is not None:
            try:
                token_ids = new_tokens[0].detach().cpu().tolist()
                token_ids = [int(token_id) for token_id in token_ids if int(token_id) >= 0]
                return self._strip_chat_echo(self._tokenizer.decode(token_ids, skip_special_tokens=True))
            except Exception:
                pass

        decoder = self._processor if hasattr(self._processor, "batch_decode") else self._tokenizer
        if decoder is None:
            return str(output_ids)
        return self._strip_chat_echo(decoder.batch_decode(new_tokens, skip_special_tokens=True)[0])

    @staticmethod
    def _strip_chat_echo(text: str) -> str:
        """Remove decoded chat-template echo when generation slicing is unavailable."""

        markers = (
            "assistantimport os",
            "assistant\nimport os",
            "assistant\r\nimport os",
            "<|im_start|>assistant\n",
            "<|im_assistant|>assistant<|im_middle|>",
            "\nassistant\n",
            "\nassistant\n\n",
            "assistant\n",
            "assistant",
        )
        best_index = -1
        best_marker = ""
        for marker in markers:
            index = text.rfind(marker)
            if index > best_index:
                best_index = index
                best_marker = marker
        if best_index >= 0:
            if best_marker.endswith("import os"):
                return "import os" + text[best_index + len(best_marker) :]
            return text[best_index + len(best_marker) :].lstrip()
        return text
