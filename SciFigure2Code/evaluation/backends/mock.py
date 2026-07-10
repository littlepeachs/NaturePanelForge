"""Mock backend used for fast end-to-end evaluator checks."""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import GenerationRequest, GenerationResult
from .base import CodeGenerationBackend


COPY_TARGET_CODE = r'''
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    target_png = Path(os.environ.get("SCIFIGURE_TARGET_PNG", ""))
    if target_png.is_file():
        from PIL import Image

        with Image.open(target_png) as image:
            width, height = image.size
            fig, ax = plt.subplots(figsize=(width / 200, height / 200), dpi=200)
            ax.imshow(image.convert("RGB"))
            ax.set_axis_off()
            fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
            return fig

    fig, ax = plt.subplots(figsize=(6, 4), dpi=120)
    ax.text(0.5, 0.5, "mock candidate", ha="center", va="center")
    ax.set_axis_off()
    return fig


fig = main()
png_path = os.environ.get("SCIFIGURE_CANDIDATE_PNG", "candidate.png")
pdf_path = os.environ.get("SCIFIGURE_CANDIDATE_PDF", "candidate.pdf")
fig.savefig(png_path, dpi=200, bbox_inches="tight")
fig.savefig(pdf_path, bbox_inches="tight")
'''


@dataclass
class MockBackend(CodeGenerationBackend):
    """Return deterministic Python code for fast evaluator plumbing checks.

    This backend is intentionally not a model baseline. It exists to validate
    dataset loading, code extraction, execution, artifact discovery, and metric
    aggregation without loading a large VLM.
    """

    mode: str = "copy_target"

    name = "mock"
    supports_images = True

    def generate(self, request: GenerationRequest) -> GenerationResult:
        code = COPY_TARGET_CODE.strip()
        if self.mode == "reference" and request.sample.reference_code and request.sample.reference_code.exists():
            code = request.sample.reference_code.read_text(encoding="utf-8", errors="replace").strip()
        return GenerationResult(
            text=f"```python\n{code}\n```\n",
            backend_name=self.name,
            metadata={"mode": self.mode},
        )
