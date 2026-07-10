# SciFigure2Code Local Model Benchmark Plan

This plan describes the portable NaturePanelForge zero-shot benchmark workflow.
For full commands, see `docs/zeroshot_benchmark.md`.

## Dataset

Use the audited clean benchmark manifests. The GitHub repository checks in only
the tiny smoke manifest; larger manifests should be downloaded from the Hugging
Face dataset release.

- `SciFigure2Code/benchmark_ready/clean_tiny100.json`: prompt/backend smoke tests.
- `clean_mini500.json`: first model comparison; download from the dataset release.
- `clean_dev1000.json`: medium-cost comparison; download from the dataset release.
- `clean_samples.json`: full clean benchmark, 6,740 samples; download from the dataset release.

## Environment

```bash
cd NaturePanelForge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
source configs/zeroshot.env.example
```

Set these variables for your machine:

```bash
export HF_TOKEN=hf_...
export VLM_ROOT="${PWD}/.models"
export VLM_MODEL_ROOT="${VLM_ROOT}/models"
export SCIFIGURE_DATASET="${PWD}/SciFigure2Code/benchmark_ready/clean_tiny100.json"
export BENCHMARK_RUN_ROOT="${PWD}/BenchmarkRuns"
```

## Metric Policy

Report dimensions separately. Do not use a single weighted final score as the
main result.

Core report dimensions:

- execution pass rate
- visual fidelity
- chart type consistency
- layout consistency
- data pattern fidelity
- text and label fidelity
- axis fidelity
- legend/colorbar completeness
- component completeness
- clarity/overlap
- scientific notation fidelity
- code validity/editability
- direct image dependency rate
- pixel painting/raster tracing rate

Always break down by complexity level, subject/domain, and chart subtype.

## Fixed 11-Model Zero-Shot Roster

| model_id | Local path under `VLM_MODEL_ROOT` | Backend |
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

Kimi is not part of this fixed 11-model smoke result because no completed
100-sample run was available for that snapshot.

## Commands

Download model weights:

```bash
bash scripts/download_zeroshot_models.sh --list
bash scripts/download_zeroshot_models.sh chartide_8b
bash scripts/download_zeroshot_models.sh
```

Validate a manifest:

```bash
python -m SciFigure2Code.evaluation \
  --validate-dataset \
  --dataset "${SCIFIGURE_DATASET}" \
  --limit 20 \
  --output-dir BenchmarkRuns/validate20
```

Dry-run the fixed 11-model matrix without loading weights:

```bash
python -m SciFigure2Code.evaluation \
  --dataset "${SCIFIGURE_DATASET}" \
  --limit 2 \
  --zero-shot-11-models \
  --benchmark-mode zeroshot \
  --dry-run-matrix \
  --output-dir BenchmarkRuns/dryrun_zeroshot11
```

Run one model:

```bash
bash scripts/run_zeroshot_model.sh chartide_8b 0 100 "${SCIFIGURE_DATASET}"
```

Run all 11:

```bash
export GPU_IDS=0,1,2,3
export RUN_PARALLEL=1
bash scripts/run_zeroshot_11models.sh
```
