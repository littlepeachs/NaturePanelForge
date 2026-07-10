"""Dataset loading for exported SciFigure2Code figure-complexity datasets."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .schemas import Sample


class DatasetLoader:
    """Load samples from a FigureComplexityDataset_* export.

    The current exports contain a root manifest with paths relative to the
    SciFigureHub repository root. This loader also tolerates absolute paths and
    manifests whose paths are relative to the dataset root.
    """

    def __init__(self, dataset_root: str | Path, repo_root: str | Path | None = None):
        self.dataset_root = Path(dataset_root).expanduser().resolve()
        self.repo_root = Path(repo_root).expanduser().resolve() if repo_root else self._infer_repo_root()
        self.rejected_records: list[dict[str, Any]] = []

    def _infer_repo_root(self) -> Path:
        start = self.dataset_root if self.dataset_root.is_dir() else self.dataset_root.parent
        for parent in (start, *start.parents):
            if (parent / "SciFigure2Code").exists() or any(parent.glob("FigureComplexityDataset_*")):
                return parent
        if self.dataset_root.name.startswith("FigureComplexityDataset"):
            return self.dataset_root.parent
        return Path.cwd().resolve()

    def manifest_path(self) -> Path:
        if self.dataset_root.is_file():
            if self.dataset_root.suffix.lower() not in {".json", ".csv"}:
                raise ValueError(f"Unsupported manifest file type: {self.dataset_root}")
            return self.dataset_root
        json_path = self.dataset_root / "manifest.json"
        csv_path = self.dataset_root / "manifest.csv"
        if json_path.exists():
            return json_path
        if csv_path.exists():
            return csv_path
        raise FileNotFoundError(f"No manifest.json or manifest.csv found under {self.dataset_root}")

    def load(
        self,
        levels: Iterable[str] | None = None,
        sample_ids: Iterable[str] | None = None,
        subtypes: Iterable[str] | None = None,
        subjects: Iterable[str] | None = None,
        limit: int | None = None,
        require_target: bool = True,
    ) -> list[Sample]:
        self.rejected_records = []
        records = self._read_manifest(self.manifest_path())
        samples = []
        for index, record in enumerate(records):
            try:
                samples.append(self._record_to_sample(record))
            except Exception as exc:
                self.rejected_records.append(
                    {
                        "index": index,
                        "error": f"{exc.__class__.__name__}: {exc}",
                        "record": dict(record) if isinstance(record, dict) else {"raw": repr(record)},
                    }
                )
        samples = self._filter(samples, levels, sample_ids, subtypes, subjects, require_target)
        samples.sort(key=lambda sample: sample.panel_id)
        if limit is not None:
            samples = samples[: max(0, limit)]
        return samples

    def _read_manifest(self, manifest_path: Path) -> list[dict[str, Any]]:
        if manifest_path.suffix == ".json":
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return [dict(item) for item in payload]
            if isinstance(payload, dict):
                for key in ("samples", "records", "items", "data"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        return [dict(item) for item in value]
            raise ValueError(f"Unsupported JSON manifest structure: {manifest_path}")

        with manifest_path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def _record_to_sample(self, record: dict[str, Any]) -> Sample:
        panel_id = str(record.get("panel_id") or self._last_path_part(record.get("dataset_dir")) or "unknown")
        dataset_dir = self._resolve_optional_path(record.get("dataset_dir"))
        target_png = self._resolve_optional_path(record.get("target_png"))
        target_pdf = self._resolve_optional_path(record.get("target_pdf"))
        reference_png = self._resolve_optional_path(record.get("reproduce_png") or record.get("reference_png"))
        reference_pdf = self._resolve_optional_path(record.get("reproduce_pdf") or record.get("reference_pdf"))
        reference_code = self._resolve_optional_path(record.get("reproduce_code") or record.get("reference_code"))
        description_md = self._resolve_optional_path(record.get("description_md"))
        level = str(
            record.get("complexity_level")
            or record.get("threshold_complexity_level")
            or record.get("original_complexity_level")
            or ""
        )
        return Sample(
            panel_id=panel_id,
            dataset_root=self.dataset_root,
            repo_root=self.repo_root,
            dataset_dir=dataset_dir,
            target_png=target_png,
            target_pdf=target_pdf,
            reference_png=reference_png,
            reference_pdf=reference_pdf,
            reference_code=reference_code,
            description_md=description_md,
            subject=str(record.get("subject", "")),
            topic=str(record.get("topic", "")),
            subtype=str(record.get("subtype", "")),
            complexity_level=level,
            refine_complexity_score=record.get("refine_complexity_score"),
            caption=str(record.get("caption", "")),
            content_summary=str(record.get("content_summary", "")),
            complexity_reason=str(record.get("complexity_reason", "")),
            record=dict(record),
        )

    def _resolve_optional_path(self, value: Any) -> Path | None:
        if value in (None, ""):
            return None
        path = Path(str(value)).expanduser()
        if path.is_absolute():
            if path.exists():
                return path
            remapped = self._remap_missing_absolute_path(path)
            if remapped is not None:
                return remapped

        manifest_dir = self.dataset_root.parent if self.dataset_root.is_file() else self.dataset_root
        candidates = [
            self.repo_root / path,
            manifest_dir / path,
            Path.cwd().resolve() / path,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        return (self.repo_root / path).resolve()

    def _remap_missing_absolute_path(self, path: Path) -> Path | None:
        """Map release-builder absolute paths onto a local dataset checkout."""

        markers = (
            "FigureComplexityDataset_3levels_threshold_1_3_4_5_6_10",
            "FigureComplexityDataset_3levels",
            "SciFigure2Code",
        )
        manifest_dir = self.dataset_root.parent if self.dataset_root.is_file() else self.dataset_root
        parts = path.parts
        for marker in markers:
            if marker not in parts:
                continue
            index = parts.index(marker)
            suffix = Path(*parts[index + 1 :])
            candidates = [
                self.repo_root / marker / suffix,
                manifest_dir / marker / suffix,
                self.dataset_root / marker / suffix if self.dataset_root.is_dir() else manifest_dir / marker / suffix,
                manifest_dir / suffix,
            ]
            for candidate in candidates:
                if candidate.exists():
                    return candidate.resolve()
            return (self.repo_root / marker / suffix).resolve()
        return None

    @staticmethod
    def _last_path_part(value: Any) -> str:
        if value in (None, ""):
            return ""
        return Path(str(value)).name

    @staticmethod
    def _filter(
        samples: list[Sample],
        levels: Iterable[str] | None,
        sample_ids: Iterable[str] | None,
        subtypes: Iterable[str] | None,
        subjects: Iterable[str] | None,
        require_target: bool,
    ) -> list[Sample]:
        level_set = {item for item in levels or []}
        id_set = {item for item in sample_ids or []}
        subtype_set = {item for item in subtypes or []}
        subject_set = {item for item in subjects or []}

        def keep(sample: Sample) -> bool:
            if level_set and sample.complexity_level not in level_set:
                return False
            if id_set and sample.panel_id not in id_set:
                return False
            if subtype_set and sample.subtype not in subtype_set:
                return False
            if subject_set and sample.subject not in subject_set:
                return False
            if require_target and (sample.target_png is None or not sample.target_png.exists()):
                return False
            return True

        return [sample for sample in samples if keep(sample)]


def load_samples(dataset_root: str | Path, **kwargs: Any) -> list[Sample]:
    return DatasetLoader(dataset_root, repo_root=kwargs.pop("repo_root", None)).load(**kwargs)
