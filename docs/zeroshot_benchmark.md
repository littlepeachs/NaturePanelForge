# Zero-Shot SciFigure2Code Benchmark

NaturePanelForge includes the SciFigure2Code zero-shot evaluator used for the
11-model `clean_tiny100` smoke benchmark. The evaluator asks a vision-language
model to generate executable Python plotting code from a target scientific
panel image, runs the generated code in a guarded environment, and reports
P0/P1/P2 metrics.

## Install

```bash
cd NaturePanelForge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For large local VLMs, use the PyTorch/CUDA environment that matches your
machine. Pixtral additionally needs the Mistral inference stack; ChartCoder
needs a local checkout of the ChartCoder source tree that provides `llava`.

## Dataset Manifests

The GitHub repository keeps the small smoke manifest under:

```text
SciFigure2Code/benchmark_ready/
```

Recommended manifests:

| Manifest | Use |
|---|---|
| `clean_tiny100.json` | checked-in quick smoke / pilot |
| `clean_mini500.json` | download from the Hugging Face dataset release |
| `clean_dev1000.json` | download from the Hugging Face dataset release |
| `clean_samples.json` | download from the Hugging Face dataset release |

Set the manifest with:

```bash
export SCIFIGURE_DATASET="${PWD}/SciFigure2Code/benchmark_ready/clean_tiny100.json"
```

If the released dataset is not already local, download it from Hugging Face and
point `SCIFIGURE_DATASET` to the downloaded clean manifest.

```bash
bash scripts/download_benchmark_dataset.sh
export SCIFIGURE_DATASET=/path/to/downloaded/clean_tiny100.json
```

## Model Download

The fixed 11-model zero-shot roster is:

| model_id | Model path under `VLM_MODEL_ROOT` | Backend |
|---|---|---|
| `intern_s2_preview` | `internlm/Intern-S2-Preview` | transformers |
| `glm_4_5v` | `zai-org/GLM-4.5V` | transformers |
| `llava_onevision_qwen2_72b` | `llava-hf/llava-onevision-qwen2-72b-ov-hf` | transformers |
| `ovis2_6_80b_a3b` | `AIDC-AI/Ovis2.6-80B-A3B` | transformers |
| `phi4_reasoning_vision_15b` | `microsoft/Phi-4-reasoning-vision-15B` | transformers |
| `molmo_72b` | `allenai/Molmo-72B-0924` | transformers |
| `qwen3_5_122b_a10b` | `Qwen/Qwen3.5-122B-A10B` | transformers |
| `gemma4_31b_it` | `google/gemma-4-31B-it` | transformers |
| `pixtral_12b` | `mistralai/Pixtral-12B-2409` | pixtral |
| `chartcoder` | `xxxllz/ChartCoder` | chartcoder |
| `chartide_8b` | `Fengx1nn/CharTide-8B` | transformers |

Configure local paths:

```bash
source configs/zeroshot.env.example
export HF_TOKEN=hf_...
export VLM_ROOT="${PWD}/.models"
export VLM_MODEL_ROOT="${VLM_ROOT}/models"
```

List the roster:

```bash
bash scripts/download_zeroshot_models.sh --list
```

Download one model:

```bash
bash scripts/download_zeroshot_models.sh chartide_8b
```

Download the fixed 11-model roster:

```bash
bash scripts/download_zeroshot_models.sh
```

Some repositories are gated or very large. Accept the model license on Hugging
Face first and set `HF_TOKEN`. For ChartCoder, also set:

```bash
export CHARTCODER_REPO=/path/to/ChartCoder
```

## Validate The Evaluator

Run a fast mock backend check before loading VLM weights:

```bash
python -m SciFigure2Code.evaluation \
  --dataset SciFigure2Code/benchmark_ready/clean_tiny100.json \
  --backend mock \
  --limit 1 \
  --expose-target-paths \
  --output-dir BenchmarkRuns/mock_smoke
```

Validate a manifest without running a model:

```bash
python -m SciFigure2Code.evaluation \
  --validate-dataset \
  --dataset "${SCIFIGURE_DATASET}" \
  --limit 20 \
  --output-dir BenchmarkRuns/validate20
```

Generate the 11-model dry-run command matrix without loading weights:

```bash
python -m SciFigure2Code.evaluation \
  --dataset "${SCIFIGURE_DATASET}" \
  --limit 2 \
  --zero-shot-11-models \
  --benchmark-mode zeroshot \
  --dry-run-matrix \
  --output-dir BenchmarkRuns/dryrun_zeroshot11
```

## Run Benchmarks

Run one model on 100 samples:

```bash
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
export GPU_IDS=0
bash scripts/run_zeroshot_model.sh chartide_8b 0 100 "${SCIFIGURE_DATASET}"
```

Run the fixed 11-model roster sequentially:

```bash
export GPU_IDS=0
export LIMIT=100
bash scripts/run_zeroshot_11models.sh
```

Run the roster in parallel by cycling over visible GPUs:

```bash
export GPU_IDS=0,1,2,3
export RUN_PARALLEL=1
export LIMIT=100
bash scripts/run_zeroshot_11models.sh
```

Summarize existing runs:

```bash
python scripts/summarize_zeroshot_runs.py \
  --run-root BenchmarkRuns \
  --output BenchmarkRuns/zeroshot_summary.csv
```

Each per-model output directory contains:

- `run_config.json`
- `selected_samples.json`
- one directory per sample with `prompt.txt`, `model_output.txt`,
  `candidate.py`, `candidate.png`, `candidate.pdf`, `review_feedback.json`,
  and `result.json`
- `summary.csv`
- `summary.json`

## Metrics

The evaluator writes:

- P0 core metrics: execution, visual fidelity, chart type, layout, data pattern,
  text labels, axes, legends/colorbars, component completeness, and clarity.
- P1 diagnostics: style, color, typography, scientific labels, panel context,
  caption consistency, code editability, re-render stability, and stratified
  breakdown hooks.
- P2 auxiliary metrics: pixel similarity, code similarity, runtime efficiency,
  library/API appropriateness, and optional judge agreement hooks.

`Avg. Score` is the mean of available P0 core metrics after execution gating. It
is useful as a compact leaderboard column, but model reports should still show
the separate P0/P1/P2 dimensions.

## Current 11-Model Smoke Result

These are zero-shot proxy means on `clean_tiny100` with the fixed short prompt.
The table is a smoke benchmark snapshot, not a final full-set ranking.

| Group | Model | Valid | Visual | Type | Layout | Data | Text | Axis | Clarity | Avg. Score |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| General VLM | Intern-S2-Preview | 84.00 | 47.51 | 64.24 | 45.83 | 47.51 | 47.51 | 47.38 | 42.76 | 51.99 |
| General VLM | GLM-4.5V | 81.00 | 44.68 | 63.73 | 43.23 | 44.68 | 44.68 | 44.70 | 40.21 | 49.48 |
| General VLM | LLaVA-OneVision-72B | 79.00 | 41.43 | 55.24 | 40.43 | 41.43 | 41.43 | 41.01 | 37.29 | 45.87 |
| General VLM | Ovis2-6-80B-A3B | 71.00 | 38.85 | 53.96 | 37.51 | 38.85 | 38.85 | 39.06 | 34.96 | 42.96 |
| General VLM | Phi-4-Reasoning-Vision-15B | 71.00 | 37.47 | 50.76 | 36.80 | 37.47 | 37.47 | 37.89 | 33.72 | 41.73 |
| General VLM | Molmo-72B | 68.00 | 33.90 | 47.95 | 33.29 | 33.90 | 33.90 | 34.55 | 30.51 | 38.38 |
| General VLM | Qwen3.5-122B-A10B | 66.00 | 38.06 | 50.68 | 37.23 | 38.06 | 38.06 | 38.06 | 34.26 | 41.57 |
| General VLM | Gemma-4-31B-IT | 58.00 | 35.38 | 45.15 | 33.81 | 35.38 | 35.38 | 35.16 | 31.84 | 37.91 |
| General VLM | Pixtral-12B | 32.00 | 16.69 | 22.25 | 16.19 | 16.69 | 16.69 | 16.60 | 15.02 | 18.49 |
| Finetuned ChartVLM | ChartCoder | 54.00 | 28.64 | 40.75 | 27.65 | 28.64 | 28.64 | 28.80 | 25.77 | 31.93 |
| Finetuned ChartVLM | ChartIDE-8B | 82.00 | 48.30 | 62.22 | 46.63 | 48.30 | 48.30 | 48.38 | 43.47 | 52.26 |

CSV copy: `docs/assets/benchmark/zeroshot_11models_clean_tiny100.csv`.
