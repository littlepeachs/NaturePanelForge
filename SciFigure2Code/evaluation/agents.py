"""Writer and reviewer agents used by the evaluation pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .backends.base import CodeGenerationBackend
from .schemas import GenerationRequest, GenerationResult, Sample
from .utils import now_iso


@dataclass
class CodeWritingAgent:
    backend: CodeGenerationBackend
    name: str = "code_writer_agent"

    def write_code(
        self,
        sample: Sample,
        prompt: str,
        image_paths: list[Path],
        output_dir: Path,
        options: dict[str, Any] | None = None,
    ) -> GenerationResult:
        return self.generate(sample, prompt, image_paths, output_dir, options)

    def generate(
        self,
        sample: Sample,
        prompt: str,
        image_paths: list[Path],
        output_dir: Path,
        options: dict[str, Any] | None = None,
    ) -> GenerationResult:
        max_images = int(getattr(self.backend, "max_images", 1) or 1)
        if len(image_paths) > max_images:
            raise ValueError(f"Backend {self.backend.name} accepts at most {max_images} image(s), got {len(image_paths)}")
        primary_image = image_paths[-1] if image_paths else None
        return self.backend.generate(
            request=GenerationRequest(
                sample=sample,
                prompt=prompt,
                output_dir=output_dir,
                image_path=primary_image,
                image_paths=image_paths,
                options=options or {},
            )
        )


@dataclass
class CodeReviewAgent:
    name: str = "code_review_agent"

    def review(
        self,
        *,
        code_text: str,
        code_extraction: Any,
        execution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        execution = execution or {}
        feedback: list[str] = []
        warnings: list[str] = []
        failures: list[str] = []

        compile_ok = bool(_get(code_extraction, "compile_ok"))
        code_present = bool(code_text.strip())
        if not code_present:
            failures.append("No Python code was extracted from the writer output.")
        elif not compile_ok:
            failures.append(f"Extracted code does not compile: {_get(code_extraction, 'compile_error')}")

        has_savefig = "savefig" in code_text
        if has_savefig:
            feedback.append("Code contains savefig call.")
        else:
            warnings.append("Code does not contain savefig; runner may need artifact fallback.")

        direct_image = _direct_image_dependency(code_text)
        pixel_painting = _pixel_painting(code_text)
        if direct_image:
            failures.append("Code appears to load or edit an input/target image directly.")
        if pixel_painting:
            failures.append("Code appears to paint pixels or trace raster data instead of plotting.")

        command_success = bool(execution.get("command_success"))
        png_exists = bool(execution.get("candidate_png_exists"))
        pdf_exists = bool(execution.get("candidate_pdf_exists"))
        if execution:
            if command_success:
                feedback.append("Code process exited successfully.")
            else:
                failures.append(f"Code execution failed or timed out: returncode={execution.get('returncode')}")
            if not png_exists:
                failures.append("candidate.png was not produced.")
            if not pdf_exists:
                warnings.append("candidate.pdf was not produced.")

        ok = code_present and compile_ok and not direct_image and not pixel_painting
        if execution:
            ok = ok and command_success and png_exists

        return {
            "agent": self.name,
            "created_at": now_iso(),
            "ok": ok,
            "checks": {
                "code_present": code_present,
                "compile_ok": compile_ok,
                "has_savefig": has_savefig,
                "direct_image_dependency": direct_image,
                "pixel_painting_or_raster_tracing": pixel_painting,
                "command_success": command_success if execution else None,
                "candidate_png_exists": png_exists if execution else None,
                "candidate_pdf_exists": pdf_exists if execution else None,
            },
            "feedback": feedback,
            "warnings": warnings,
            "failures": failures,
        }


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _direct_image_dependency(code_text: str) -> bool:
    lowered = code_text.lower()
    suspicious_paths = (
        "scifigure_target_png",
        "scifigure_target_pdf",
        "target.png",
        "target_pdf",
        "target_png",
    )
    image_loaders = ("image.open", "plt.imread", "mpimg.imread", "cv2.imread", "skimage.io.imread", "shutil.copy", "copy2")
    return any(loader in lowered for loader in image_loaders) and any(path in lowered for path in suspicious_paths)


def _pixel_painting(code_text: str) -> bool:
    lowered = code_text.lower()
    if re.search(r"for\s+\w+\s+in\s+range\([^)]*(width|height|shape)", lowered):
        return True
    pixel_tokens = ("putpixel", "set_data", "imshow(np.zeros", "np.zeros_like", "canvas", "pixels[")
    return any(token in lowered for token in pixel_tokens) and "imshow" in lowered
