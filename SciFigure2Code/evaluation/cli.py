"""Command line entry point for SciFigure2Code evaluation."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from SciFigure2Code.evaluation.backends import create_backend
    from SciFigure2Code.evaluation.dataset import DatasetLoader
    from SciFigure2Code.evaluation.model_inventory import get_model_spec, local_model_specs, prompt_modes, zero_shot_11_model_specs
    from SciFigure2Code.evaluation.pipeline import EvalConfig, aggregate_existing_results, run_evaluation
    from SciFigure2Code.evaluation.prompts import PromptConfig, build_prompt_bundle
    from SciFigure2Code.evaluation.runner import RunnerConfig
    from SciFigure2Code.evaluation.utils import ensure_dir, now_iso, safe_name, write_json
else:
    from .backends import create_backend
    from .dataset import DatasetLoader
    from .model_inventory import get_model_spec, local_model_specs, prompt_modes, zero_shot_11_model_specs
    from .pipeline import EvalConfig, aggregate_existing_results, run_evaluation
    from .prompts import PromptConfig, build_prompt_bundle
    from .runner import RunnerConfig
    from .utils import ensure_dir, now_iso, safe_name, write_json


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = os.environ.get("SCIFIGURE_DATASET", str(PACKAGE_ROOT / "benchmark_ready" / "clean_tiny100.json"))
DEFAULT_VLM_ROOT = os.environ.get("VLM_ROOT", str(Path.cwd() / ".models"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SciFigure2Code figure-to-code evaluation.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="FigureComplexityDataset_* root directory.")
    parser.add_argument("--repo-root", default=None, help="SciFigureHub root if manifest paths are not directly resolvable.")
    parser.add_argument("--output-dir", default=None, help="Directory for per-sample outputs and summaries.")
    parser.add_argument("--backend", default="mock", help="mock, transformers, or module.path:ClassName.")
    parser.add_argument("--model-id", default=None, help="Model id from Local Model Inventory; sets --backend and --model-path.")
    parser.add_argument("--all-local-models", action="store_true", help="Use all Local Model Inventory models for matrix dry-run.")
    parser.add_argument("--zero-shot-11-models", action="store_true", help="Use the fixed 11-model zero-shot benchmark roster for matrix dry-run.")
    parser.add_argument("--list-models", action="store_true", help="List local model directories under --vlm-root and exit.")
    parser.add_argument("--validate-dataset", action="store_true", help="Validate selected dataset samples and exit.")
    parser.add_argument("--aggregate-existing", action="store_true", help="Rebuild summary.csv/json from existing per-sample result.json files and exit.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of samples after filtering.")
    parser.add_argument("--num-shards", type=int, default=None, help="Split matched samples into this many shards.")
    parser.add_argument("--shard-index", type=int, default=None, help="Run only this zero-based shard index.")
    parser.add_argument("--level", action="append", choices=["low", "medium", "high", "unknown_complexity"], help="Filter by complexity level; repeatable.")
    parser.add_argument("--sample-id", action="append", help="Evaluate only the given panel_id; repeatable.")
    parser.add_argument("--subtype", action="append", help="Filter by chart subtype; repeatable.")
    parser.add_argument("--subject", action="append", help="Filter by subject/domain; repeatable.")
    parser.add_argument("--allow-missing-target", action="store_true", help="Do not drop samples whose target PNG is missing.")
    parser.add_argument("--resume", action="store_true", help="Reuse existing per-sample result.json files.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing per-sample outputs even with --resume.")
    parser.add_argument("--dry-run", action="store_true", help="Only load/filter samples and write the selected sample manifest.")
    parser.add_argument("--dry-run-matrix", action="store_true", help="Write Local Model Inventory x prompt-mode dry-run matrix without loading models.")

    parser.add_argument("--timeout", type=int, default=180, help="Per-sample code execution timeout in seconds.")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter used to run generated scripts.")
    parser.add_argument("--no-pdf-fallback", action="store_true", help="Do not create candidate.pdf from candidate.png when code omits PDF.")
    parser.add_argument("--no-png-from-pdf", action="store_true", help="Do not render candidate.png from candidate.pdf via pdftoppm.")
    parser.add_argument("--expose-target-paths", action="store_true", help="Expose SCIFIGURE_TARGET_PNG/PDF to candidate code; only use for plumbing mocks.")

    parser.add_argument("--no-caption", action="store_true", help="Do not include figure caption text in the prompt.")
    parser.add_argument("--no-description", action="store_true", help="Do not include description.md text in the prompt.")
    parser.add_argument(
        "--prompt-style",
        default="short",
        choices=["short", "metadata", "full"],
        help="Prompt template: short=image-only fixed prompt, metadata=short plus sample metadata, full=metadata plus caption/description.",
    )
    parser.add_argument(
        "--benchmark-mode",
        default="zeroshot",
        choices=["zeroshot", "cot", "icl", "oneshot", "oneshot_cot"],
        help="Prompting mode for this run.",
    )
    parser.add_argument("--all-modes", action="store_true", help="Run or dry-run all four benchmark modes.")
    parser.add_argument("--one-shot-sample-id", default=None, help="Explicit exemplar panel_id for one-shot modes.")
    parser.add_argument("--max-caption-chars", type=int, default=2500)
    parser.add_argument("--max-description-chars", type=int, default=3000)
    parser.add_argument("--max-one-shot-code-chars", type=int, default=32000)
    parser.add_argument("--cot-reasoning-tokens", type=int, default=768)
    parser.add_argument("--max-cot-reasoning-chars", type=int, default=8000)

    parser.add_argument("--mock-mode", default="copy_target", choices=["copy_target", "reference"], help="Mock backend behavior.")
    parser.add_argument("--model-path", default=None, help="Local model directory for transformers backend.")
    parser.add_argument("--vlm-root", default=DEFAULT_VLM_ROOT, help="VLM root used for Hugging Face cache defaults.")
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--dtype", default="auto", help="auto, bfloat16, float16, float32.")
    parser.add_argument("--gpus", default=None, help="CUDA_VISIBLE_DEVICES value for transformers backend.")
    parser.add_argument("--attn-implementation", default=None, help="Optional transformers attention implementation.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--do-sample", action="store_true")
    parser.add_argument("--no-image", action="store_true", help="Use text-only generation even if the backend supports images.")
    parser.add_argument("--no-trust-remote-code", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.benchmark_mode == "icl":
        args.benchmark_mode = "oneshot"
    if args.list_models:
        _list_models(Path(args.vlm_root).expanduser(), include_inventory=True)
        return 0

    if args.all_local_models and args.zero_shot_11_models:
        raise SystemExit("Use either --all-local-models or --zero-shot-11-models, not both.")
    if (args.all_local_models or args.zero_shot_11_models) and not args.dry_run_matrix:
        raise SystemExit("--all-local-models/--zero-shot-11-models are currently supported for --dry-run-matrix. Run real benchmarks per --model-id.")
    _apply_model_id_defaults(args)
    dataset_root = Path(args.dataset).expanduser()
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else _default_output_dir(args.backend)
    if args.aggregate_existing:
        summary = aggregate_existing_results(output_dir)
        print(f"summary_csv={summary['summary_csv']}")
        print(f"summary_json={summary['summary_json']}")
        return 0

    loader = DatasetLoader(dataset_root, repo_root=args.repo_root)
    samples = loader.load(
        levels=args.level,
        sample_ids=args.sample_id,
        subtypes=args.subtype,
        subjects=args.subject,
        limit=args.limit,
        require_target=not args.allow_missing_target,
    )
    if not samples:
        raise SystemExit("No samples matched the requested filters.")
    samples = _apply_shard(samples, args.num_shards, args.shard_index)
    if not samples:
        raise SystemExit("Shard selection produced zero samples.")
    if args.validate_dataset:
        _validate_samples(samples, output_dir, loader.rejected_records)
        return 0

    modes = list(prompt_modes()) if args.all_modes else [args.benchmark_mode]
    one_shot_sample = _select_one_shot_sample(loader, args, samples, modes)
    if args.dry_run_matrix:
        _write_matrix_dry_run(samples, one_shot_sample, output_dir, args, modes)
        return 0

    if args.all_modes:
        ensure_dir(output_dir)
        summaries = []
        for mode in modes:
            mode_args = argparse.Namespace(**vars(args))
            mode_args.benchmark_mode = mode
            backend = create_backend(mode_args.backend, **_backend_kwargs(mode_args))
            config = _eval_config(mode_args, output_dir / mode, one_shot_sample)
            print(f"Loaded {len(samples)} samples from {loader.manifest_path()}")
            print(f"Backend: {backend.name}")
            print(f"Mode: {mode}")
            print(f"Output: {config.output_dir}")
            if args.dry_run:
                _write_eval_dry_run(samples, config.output_dir)
                summaries.append({"mode": mode, "dry_run": True, "output_dir": config.output_dir})
            else:
                summaries.append({"mode": mode, **run_evaluation(samples, backend, config)})
        write_json(output_dir / "all_modes_summary.json", summaries)
        print(f"all_modes_summary={output_dir / 'all_modes_summary.json'}")
        return 0

    backend = create_backend(args.backend, **_backend_kwargs(args))
    config = _eval_config(args, output_dir, one_shot_sample)

    print(f"Loaded {len(samples)} samples from {loader.manifest_path()}")
    print(f"Backend: {backend.name}")
    print(f"Mode: {args.benchmark_mode}")
    print(f"Output: {output_dir}")
    if args.dry_run:
        _write_eval_dry_run(samples, output_dir)
        return 0
    summary = run_evaluation(samples, backend, config)
    aggregate = summary["aggregate"]
    print(f"summary_csv={summary['summary_csv']}")
    print(f"summary_json={summary['summary_json']}")
    print(
        "rates: "
        f"command_success={aggregate['command_success']:.3f}, "
        f"png={aggregate['candidate_png_exists']:.3f}, "
        f"pdf={aggregate['candidate_pdf_exists']:.3f}, "
        f"image_ok={aggregate['image_ok']:.3f}"
    )
    return 0


def _backend_kwargs(args: argparse.Namespace) -> dict:
    backend_name = args.backend.lower()
    if backend_name == "mock":
        return {"mode": args.mock_mode}
    kwargs = {}
    if backend_name in {"transformers", "chartcoder", "pixtral"}:
        if not args.model_path:
            raise SystemExit(f"--model-path is required for --backend {backend_name}")
        kwargs.update(
            {
                "model_path": args.model_path,
                "vlm_root": args.vlm_root,
                "max_new_tokens": args.max_new_tokens,
                "device_map": None if args.device_map.lower() == "none" else args.device_map,
                "gpus": args.gpus,
                "attn_implementation": args.attn_implementation,
                "temperature": args.temperature,
                "use_image": not args.no_image,
            }
        )
        if backend_name == "transformers":
            spec = get_model_spec(args.model_path)
            kwargs.update(
                {
                    "dtype": args.dtype,
                    "trust_remote_code": not args.no_trust_remote_code,
                    "do_sample": args.do_sample,
                    "supports_multi_images": spec.supports_multi_image if spec else True,
                }
            )
        if backend_name == "pixtral":
            kwargs.update(
                {
                    "dtype": args.dtype,
                    "do_sample": args.do_sample,
                }
            )
    elif ":" in args.backend:
        if args.model_path:
            kwargs["model_path"] = args.model_path
    return kwargs


def _apply_model_id_defaults(args: argparse.Namespace) -> None:
    if not args.model_id:
        return
    spec = get_model_spec(args.model_id)
    if spec is None:
        known = ", ".join(item.model_id for item in local_model_specs())
        raise SystemExit(f"Unknown --model-id {args.model_id!r}. Known ids: {known}")
    args.backend = spec.preferred_backend
    args.model_path = str(spec.model_path)


def _eval_config(args: argparse.Namespace, output_dir: Path, one_shot_sample) -> EvalConfig:
    spec = get_model_spec(args.model_id or args.model_path)
    model = spec.to_json_dict() if spec else {"model_id": args.model_id or args.backend, "model_path": args.model_path or ""}
    return EvalConfig(
        output_dir=output_dir,
        runner=RunnerConfig(
            python=args.python,
            timeout_seconds=args.timeout,
            create_pdf_from_png=not args.no_pdf_fallback,
            render_png_from_pdf=not args.no_png_from_pdf,
            expose_target_paths=args.expose_target_paths,
        ),
        prompt=PromptConfig(
            style=args.prompt_style,
            mode=args.benchmark_mode,
            include_caption=not args.no_caption,
            include_description=not args.no_description,
            max_caption_chars=args.max_caption_chars,
            max_description_chars=args.max_description_chars,
            max_one_shot_code_chars=args.max_one_shot_code_chars,
            max_cot_reasoning_chars=args.max_cot_reasoning_chars,
            cot_reasoning_tokens=args.cot_reasoning_tokens,
            supports_multi_image=bool(spec.supports_multi_image) if spec else False,
        ),
        one_shot_sample=one_shot_sample,
        model=model,
        resume=args.resume,
        overwrite=args.overwrite,
    )


def _select_one_shot_sample(loader: DatasetLoader, args: argparse.Namespace, samples, modes: list[str]):
    if not any(mode in {"oneshot", "oneshot_cot"} for mode in modes):
        return None
    if args.one_shot_sample_id:
        pool = loader.load(sample_ids=[args.one_shot_sample_id], require_target=not args.allow_missing_target)
        if not pool:
            raise SystemExit(f"--one-shot-sample-id not found: {args.one_shot_sample_id}")
        exemplar = pool[0]
        if not exemplar.reference_code or not exemplar.reference_code.exists():
            raise SystemExit(f"--one-shot-sample-id has no readable reference_code: {args.one_shot_sample_id}")
        if not exemplar.reference_png or not exemplar.reference_png.exists():
            raise SystemExit(f"--one-shot-sample-id has no readable reference_png: {args.one_shot_sample_id}")
        return exemplar

    selected_ids = {sample.panel_id for sample in samples}
    pool = loader.load(
        levels=args.level,
        subtypes=args.subtype,
        subjects=args.subject,
        require_target=not args.allow_missing_target,
    )
    for candidate in pool:
        if (
            candidate.panel_id not in selected_ids
            and candidate.reference_code
            and candidate.reference_code.exists()
            and candidate.reference_png
            and candidate.reference_png.exists()
        ):
            return candidate
    raise SystemExit("One-shot modes require at least one exemplar sample; provide --one-shot-sample-id.")


def _write_eval_dry_run(samples, output_dir: Path) -> None:
    ensure_dir(output_dir)
    manifest = output_dir / "selected_samples.json"
    write_json(manifest, [sample.to_json_dict() for sample in samples])
    print(f"dry_run_selected_samples={manifest}")


def _write_matrix_dry_run(samples, one_shot_sample, output_dir: Path, args: argparse.Namespace, modes: list[str]) -> None:
    ensure_dir(output_dir)
    if args.zero_shot_11_models:
        models = zero_shot_11_model_specs()
    elif args.all_local_models or not args.model_id:
        models = local_model_specs()
    else:
        models = [get_model_spec(args.model_id)]
    models = [model for model in models if model is not None]
    if not models:
        raise SystemExit("No Local Model Inventory models selected.")
    target = samples[0]
    rows = []
    for spec in models:
        for mode in modes:
            config = PromptConfig(
                style=args.prompt_style,
                mode=mode,
                supports_multi_image=spec.supports_multi_image,
                include_caption=not args.no_caption,
                include_description=not args.no_description,
                max_one_shot_code_chars=args.max_one_shot_code_chars,
            )
            bundle = build_prompt_bundle(target, config, one_shot_sample=one_shot_sample if mode in {"oneshot", "oneshot_cot"} else None)
            image_count = len(bundle.image_paths)
            status = "supported"
            reasons = []
            if image_count > spec.max_images:
                status = "contract_error"
                reasons.append(f"image_count {image_count} exceeds max_images {spec.max_images}")
            if not spec.adapter_ready:
                reasons.append("adapter_not_yet_verified")
            if bundle.one_shot_strategy == "native_multi_image" and not spec.multi_image_verified:
                reasons.append("native_multi_image_not_yet_smoke_verified")
            dry_run_command = _matrix_command(args, spec.model_id, mode, dry_run=True)
            run_command = _matrix_command(args, spec.model_id, mode, dry_run=False)
            rows.append(
                {
                    "model_id": spec.model_id,
                    "model_path": str(spec.model_path),
                    "backend": spec.preferred_backend,
                    "adapter_ready": spec.adapter_ready,
                    "benchmark_mode": mode,
                    "prompt_style": args.prompt_style,
                    "status": status,
                    "reasons": "; ".join(reasons),
                    "supports_multi_image": spec.supports_multi_image,
                    "multi_image_verified": spec.multi_image_verified,
                    "max_images": spec.max_images,
                    "image_count": image_count,
                    "image_roles": ",".join(bundle.image_roles),
                    "one_shot_strategy": bundle.one_shot_strategy,
                    "exemplar_panel_id": bundle.exemplar_panel_id,
                    "target_panel_id": target.panel_id,
                    "prompt_chars": len(bundle.prompt),
                    "writer_agent": "code_writer_agent",
                    "review_agent": "code_review_agent",
                    "review_rounds": 1,
                    "dry_run_command": dry_run_command,
                    "run_command_template": run_command,
                }
            )

    json_path = output_dir / "benchmark_matrix_dry_run.json"
    csv_path = output_dir / "benchmark_matrix_dry_run.csv"
    commands_path = output_dir / "benchmark_commands.sh"
    write_json(json_path, {"created_at": now_iso(), "sample_count": len(samples), "rows": rows})
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _write_matrix_commands(commands_path, rows)
    prompt_dir = ensure_dir(output_dir / "prompt_previews")
    for mode in modes:
        if mode in {"oneshot", "oneshot_cot"}:
            preview_variants = {
                "native_multi_image": True,
                "text_exemplar_single_image": False,
            }
        else:
            preview_variants = {"base": True}
        for suffix, supports_multi_image in preview_variants.items():
            preview_config = PromptConfig(
                style=args.prompt_style,
                mode=mode,
                supports_multi_image=supports_multi_image,
                max_one_shot_code_chars=args.max_one_shot_code_chars,
            )
            preview_one_shot = one_shot_sample if mode in {"oneshot", "oneshot_cot"} else None
            preview_bundle = build_prompt_bundle(target, preview_config, one_shot_sample=preview_one_shot)
            preview_name = mode if suffix == "base" else f"{mode}_{suffix}"
            (prompt_dir / f"{preview_name}.txt").write_text(preview_bundle.prompt, encoding="utf-8")
            write_json(prompt_dir / f"{preview_name}.json", preview_bundle)
    print(f"dry_run_matrix_json={json_path}")
    print(f"dry_run_matrix_csv={csv_path}")
    print(f"benchmark_commands={commands_path}")
    print(f"prompt_previews={prompt_dir}")


def _matrix_command(args: argparse.Namespace, model_id: str, mode: str, dry_run: bool) -> str:
    python = "python3"
    run_label = "dryrun" if dry_run else "run"
    output = Path("BenchmarkRuns") / f"{model_id}_{mode}_{run_label}"
    parts = [
        python,
        "-m",
        "SciFigure2Code.evaluation",
        "--dataset",
        str(args.dataset),
        "--model-id",
        model_id,
        "--benchmark-mode",
        mode,
        "--prompt-style",
        args.prompt_style,
        "--max-new-tokens",
        str(args.max_new_tokens),
        "--max-one-shot-code-chars",
        str(args.max_one_shot_code_chars),
        "--output-dir",
        str(output),
    ]
    if args.limit is not None:
        parts.extend(["--limit", str(args.limit)])
    if args.one_shot_sample_id:
        parts.extend(["--one-shot-sample-id", args.one_shot_sample_id])
    if dry_run:
        parts.append("--dry-run")
    else:
        parts.append("--resume")
    return " ".join(shlex.quote(part) for part in parts)


def _write_matrix_commands(path: Path, rows: list[dict[str, object]]) -> None:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'cd "$(dirname "${BASH_SOURCE[0]}")/../.."',
        'export VLM_ROOT="${VLM_ROOT:-${PWD}/.models}"',
        'export VLM_MODEL_ROOT="${VLM_MODEL_ROOT:-${VLM_ROOT}/models}"',
        'export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"',
        'export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"',
        "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True",
        "",
        "# Dry-run commands validate CLI/model-id/prompt-mode wiring without loading model weights.",
    ]
    for row in rows:
        lines.extend(
            [
                "",
                f"# {row['model_id']} / {row['benchmark_mode']} / {row['one_shot_strategy']}",
                str(row["dry_run_command"]),
            ]
        )
    lines.extend(
        [
            "",
            "# Real run templates. They are commented out intentionally so this script",
            "# can be executed safely as a dry-run contract check.",
            "# Uncomment one command at a time and set CUDA_VISIBLE_DEVICES per model.",
        ]
    )
    for row in rows:
        lines.extend(
            [
                "",
                f"# {row['model_id']} / {row['benchmark_mode']} / {row['one_shot_strategy']}",
                f"# CUDA_VISIBLE_DEVICES=${{CUDA_VISIBLE_DEVICES:-0}} {row['run_command_template']}",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o755)


def _default_output_dir(backend: str) -> Path:
    timestamp = safe_name(now_iso().replace(":", "-"))
    return Path(__file__).resolve().parent / "runs" / f"{safe_name(backend)}_{timestamp}"


def _apply_shard(samples, num_shards: int | None, shard_index: int | None):
    if num_shards is None and shard_index is None:
        return samples
    if num_shards is None or shard_index is None:
        raise SystemExit("--num-shards and --shard-index must be provided together")
    if num_shards <= 0:
        raise SystemExit("--num-shards must be positive")
    if shard_index < 0 or shard_index >= num_shards:
        raise SystemExit("--shard-index must be in [0, num_shards)")
    return [sample for idx, sample in enumerate(samples) if idx % num_shards == shard_index]


def _list_models(vlm_root: Path, include_inventory: bool = False) -> None:
    if include_inventory:
        print("Local Model Inventory:")
        for spec in local_model_specs():
            print(
                f"{spec.model_id}\t{spec.rel_path}\t{spec.model_type}\t"
                f"backend={spec.preferred_backend}\tmulti_image={spec.supports_multi_image}\t"
                f"max_images={spec.max_images}\tadapter_ready={spec.adapter_ready}"
            )
        print("")
    model_root = vlm_root / "models"
    if not model_root.exists():
        print(f"model root not found yet: {model_root}")
        return
    for model_dir in sorted(path for path in model_root.glob("*/*") if path.is_dir()):
        config = model_dir / "config.json"
        model_type = ""
        architectures = ""
        if config.exists():
            try:
                payload = json.loads(config.read_text(encoding="utf-8"))
                model_type = str(payload.get("model_type") or "")
                architectures = ",".join(payload.get("architectures") or [])
            except Exception as exc:
                model_type = f"config_error:{exc.__class__.__name__}"
        rel = model_dir.relative_to(model_root)
        print(f"{rel}\t{model_type}\t{architectures}")


def _validate_samples(samples, output_dir: Path, rejected_records: list[dict] | None = None) -> None:
    ensure_dir(output_dir)
    rows = []
    for sample in samples:
        row = {
            "panel_id": sample.panel_id,
            "dataset_dir_exists": bool(sample.dataset_dir and sample.dataset_dir.exists()),
            "target_png_exists": bool(sample.target_png and sample.target_png.exists()),
            "reference_code_exists": bool(sample.reference_code and sample.reference_code.exists()),
            "reference_png_exists": bool(sample.reference_png and sample.reference_png.exists()),
            "description_exists": bool(sample.description_md and sample.description_md.exists()),
            "subject": sample.subject,
            "subtype": sample.subtype,
            "complexity_level": sample.complexity_level,
        }
        row["ok"] = row["target_png_exists"]
        rows.append(row)
    payload = {
        "total_samples": len(rows),
        "ok_samples": sum(1 for row in rows if row["ok"]),
        "missing_target_png": [row["panel_id"] for row in rows if not row["target_png_exists"]],
        "missing_reference_code": [row["panel_id"] for row in rows if not row["reference_code_exists"]],
        "rejected_records": rejected_records or [],
        "rejected_count": len(rejected_records or []),
        "samples": rows,
    }
    out = output_dir / "dataset_validation.json"
    write_json(out, payload)
    print(f"dataset_validation={out}")
    print(f"total={payload['total_samples']} ok={payload['ok_samples']} missing_target_png={len(payload['missing_target_png'])}")


if __name__ == "__main__":
    raise SystemExit(main())
