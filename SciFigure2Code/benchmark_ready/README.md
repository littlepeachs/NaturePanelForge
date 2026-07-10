# SciFigure2Code Benchmark Ready Manifests

This directory contains lightweight benchmark-ready files for clean
SciFigure2Code samples.

Source dataset: exported NaturePanelForge/SciFigure2Code panel folders.
Audit root: Codex clean-sample audit outputs.

To keep the GitHub repository small, only `clean_tiny100.*` is checked in as a
smoke-test manifest. Download larger manifests from the Hugging Face dataset
release and pass them with `--dataset`; when needed, also pass `--repo-root` so
paths can be resolved on your machine.

## Counts

- Total audited samples: 8385
- Clean benchmark candidates: 6740
- Minor issues excluded from clean benchmark: 1308
- Major issues excluded from clean benchmark: 67
- Critical issues excluded from clean benchmark: 270

## Main Files

- `clean_tiny100.*`: deterministic stratified 100-sample subset for smoke tests.
- `clean_summary.json`: distribution statistics.
- `metric_dimensions.json`: metric definitions.

Download-only files:

- `clean_mini500.*`: deterministic stratified 500-sample subset for model development.
- `clean_dev1000.*`: deterministic stratified 1000-sample subset for medium-cost evaluation.
- `clean_samples.*`: full 6,740-sample clean manifest.
- `clean_*_paths.txt`: path lists for the full clean set.

## Reporting Recommendation

Report separate metric dimensions instead of only a weighted final score:
execution, visual fidelity, scientific content fidelity, code validity/editability, and clarity/typography.
A weighted aggregate can be optional, but it should not replace the per-metric table.
