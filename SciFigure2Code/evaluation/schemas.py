"""Typed records passed between evaluation stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Sample:
    panel_id: str
    dataset_root: Path
    repo_root: Path
    dataset_dir: Path | None
    target_png: Path | None
    target_pdf: Path | None = None
    reference_png: Path | None = None
    reference_pdf: Path | None = None
    reference_code: Path | None = None
    description_md: Path | None = None
    subject: str = ""
    topic: str = ""
    subtype: str = ""
    complexity_level: str = ""
    refine_complexity_score: str | float | int | None = None
    caption: str = ""
    content_summary: str = ""
    complexity_reason: str = ""
    record: dict[str, Any] = field(default_factory=dict)

    def metadata_for_prompt(self) -> dict[str, Any]:
        return {
            "panel_id": self.panel_id,
            "subject": self.subject,
            "topic": self.topic,
            "chart_subtype": self.subtype,
            "complexity_level": self.complexity_level,
            "refine_complexity_score": self.refine_complexity_score,
            "journal": self.record.get("journal", ""),
            "doi": self.record.get("doi", ""),
        }

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "panel_id": self.panel_id,
            "dataset_root": self.dataset_root,
            "repo_root": self.repo_root,
            "dataset_dir": self.dataset_dir,
            "target_png": self.target_png,
            "target_pdf": self.target_pdf,
            "reference_png": self.reference_png,
            "reference_pdf": self.reference_pdf,
            "reference_code": self.reference_code,
            "description_md": self.description_md,
            "subject": self.subject,
            "topic": self.topic,
            "subtype": self.subtype,
            "complexity_level": self.complexity_level,
            "refine_complexity_score": self.refine_complexity_score,
            "caption": self.caption,
            "content_summary": self.content_summary,
            "complexity_reason": self.complexity_reason,
            "record": self.record,
        }


@dataclass
class GenerationRequest:
    sample: Sample
    prompt: str
    output_dir: Path
    image_path: Path | None = None
    image_paths: list[Path] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResult:
    text: str
    backend_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeExtractionResult:
    code: str
    strategy: str
    language: str = "python"
    fenced_blocks: int = 0
    compile_ok: bool = False
    compile_error: str | None = None
