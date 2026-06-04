# Tutorial

This is the short path for using NaturePanelForge. The full pipeline is:

```text
paper/full figure -> panel split -> Qwen score -> Codex reproduce -> final refine -> gallery
```

Gallery demo:

```text
http://166.111.35.177:18081/
```

## 1. Install

```bash
cd NaturePanelForge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp configs/demo.env.example .env
source .env
```

Required external tools:

- Codex CLI
- local Qwen vision model for panel scoring
- network access for open-access paper and figure download

Set Qwen:

```bash
export QWEN_MODEL_PATH=/path/to/Qwen3.6-27B
export CUDA_VISIBLE_DEVICES=0
```

## 2. One Panel Image To Code

Use this when you already have a cropped target panel image.

```bash
python3 forge.py single-panel-image \
  --image /path/to/target_panel.png \
  --panel-id demo_panel \
  --chart-type bar \
  --caption "A grouped bar chart with error bars and a legend." \
  --out-root UserRuns/demo_panel \
  --review-rounds 4 \
  --skip-existing
```

Live output:

```text
UserRuns/demo_panel/Reproduce_Statistical/bar/demo_panel/
  target.png
  metadata.json
  qwen_score.json
  reproduce_panel.py
  reproduce_panel.png
  reproduce_panel.pdf
  user_reproduce_summary.json
  result.json
```

Dry run:

```bash
python3 forge.py single-panel-image \
  --image /path/to/target_panel.png \
  --out-root UserRuns/dry_run \
  --dry-run \
  --print-command
```

Dry-run summaries set `live_contract_checked=false` and `contract_passed=false`; a live run must create the code, PNG/PDF, and passing review summary.

## 3. One Full Figure Image To Panels

Use this when you have one multi-panel full figure image.

```bash
python3 forge.py single-full-image \
  --image /path/to/full_figure.png \
  --paper-id user_figure \
  --figure-index 1 \
  --caption "Full figure caption or visual description." \
  --out-root UserRuns/single_full
```

Key outputs:

```text
UserRuns/single_full/FullFigures/full_figures.csv
UserRuns/single_full/Panels_codex_full/
UserRuns/single_full/PanelReviews_codex_full/
UserRuns/single_full/PanelSplitSpecsCodex_full/
```

## 4. One Paper

```bash
python3 forge.py single-paper \
  --subject biology \
  --topic AI_biology \
  --doi 10.1038/s41467-025-12345-6 \
  --years 2025,2026 \
  --figures-per-paper 5
```

Use `--download-only` to stop after paper metadata and full figures:

```bash
python3 forge.py single-paper \
  --pmcid PMC1234567 \
  --download-only
```

## 5. Batched Papers

```bash
python3 forge.py batched-paper \
  --subject biology \
  --topic AI_biology \
  --years 2025,2026 \
  --target-papers 20 \
  --batch-size 20 \
  --figures-per-paper 5
```

## 6. Full Demo Script

Run a small two-paper demo:

```bash
TARGET_PAPERS=2 FIGURES_PER_PAPER=2 bash scripts/run_full_pipeline.sh
```

Run a larger materials batch:

```bash
SUBJECT=materials \
TOPIC=AI_materials \
QUERY_DOMAIN=materials \
YEARS=2024,2025,2026 \
TARGET_PAPERS=200 \
BATCH_SIZE=200 \
FIGURES_PER_PAPER=5 \
FULL_FIGURE_WORKERS=16 \
CODEX_MODEL=gpt-5.4 \
CODEX_JOBS=32 \
MAX_CODEX_PROCESSES=40 \
CODEX_TIMEOUT=3000 \
CODEX_REVIEW_ROUNDS=4 \
SCORE_BATCH_SIZE=16 \
bash scripts/run_full_pipeline.sh
```

## 7. Install The Codex Skill

```bash
bash scripts/install_skills.sh
```

Dry-run the installer:

```bash
DRY_RUN=1 bash scripts/install_skills.sh
```

This installs `skills/codex-panel-reproduce` into `${CODEX_HOME:-$HOME/.codex}/skills`.

## 8. Serve Gallery

```bash
cd gallery
python3 -m http.server 18081 --bind 0.0.0.0
```

Open:

```text
http://<server-ip>:18081/
```

## 9. Tests

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Tests do not download papers, call Qwen, or invoke live Codex.
