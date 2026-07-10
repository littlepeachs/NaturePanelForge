# SciFigure2Code Evaluation

Standalone evaluator for exported `FigureComplexityDataset_*` datasets.

## Quick Smoke Test

```bash
python -m SciFigure2Code.evaluation \
  --dataset SciFigure2Code/benchmark_ready/clean_tiny100.json \
  --backend mock \
  --limit 1 \
  --expose-target-paths \
  --output-dir BenchmarkRuns/mock_smoke
```

The mock backend is only for pipeline validation. It returns deterministic
matplotlib code so dataset loading, code extraction, code execution, artifact
discovery, per-sample JSON, and summary files can be checked quickly.

Validate the selected dataset without running a model:

```bash
python -m SciFigure2Code.evaluation \
  --validate-dataset \
  --limit 20 \
  --output-dir SciFigure2Code/evaluation/runs/validate20
```

List available local models:

```bash
python -m SciFigure2Code.evaluation --list-models
```

Shard a large run:

```bash
python -m SciFigure2Code.evaluation \
  --backend mock \
  --num-shards 8 \
  --shard-index 0 \
  --output-dir SciFigure2Code/evaluation/runs/mock_shard0
```

Rebuild summaries from existing `result.json` files:

```bash
python -m SciFigure2Code.evaluation \
  --aggregate-existing \
  --output-dir SciFigure2Code/evaluation/runs/mock_shard0
```

## Local Transformers Backend

```bash
python -m SciFigure2Code.evaluation \
  --backend transformers \
  --model-id chartide_8b \
  --limit 3 \
  --level low \
  --output-dir BenchmarkRuns/chartide_low3
```

Important outputs:

- `SAMPLE_ID/prompt.txt`: prompt sent to the backend.
- `SAMPLE_ID/model_output.txt`: raw model text.
- `SAMPLE_ID/candidate.py`: extracted Python script.
- `SAMPLE_ID/candidate.png` and `candidate.pdf`: normalized artifacts.
- `SAMPLE_ID/result.json`: per-sample metadata, execution status, and metrics.
- `summary.csv` and `summary.json`: run-level metrics.

## Metric Schema

Each per-sample `result.json` contains:

- `metrics`: deterministic artifact and image-proxy metrics.
- `benchmark_metrics.p0_core`: main leaderboard metrics.
- `benchmark_metrics.p1_diagnostic`: breakdown and error-analysis metrics.
- `benchmark_metrics.p2_auxiliary`: supporting metrics such as pixel and code similarity.
- `benchmark_metrics.breakdown_keys`: complexity, domain, topic, and chart subtype.

The current framework fills these with deterministic execution/image/code
proxies so the pipeline can run offline. A VLM judge backend can later replace
or augment those fields without changing the output schema.

`summary.json` aggregates:

- execution pass rate and artifact success rates,
- leaderboard score,
- P0/P1/P2 metric means,
- breakdowns by complexity, domain, chart subtype, domain x complexity, and
  subtype x complexity.

## Backend Extension

Implement `CodeGenerationBackend.generate(request)` and pass it as
`--backend module.path:ClassName`. The request contains the `Sample`, prompt,
target image path, and per-sample output directory.
