#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

echo "[1/6] paper_to_fullfig"
bash scripts/run_demo_paper_to_fullfig.sh

RUN_DIR="${RUN_DIR:-$(resolve_run_dir)}"
export RUN_DIR
echo "[run-dir] ${RUN_DIR}"

echo "[2/6] panel_split"
bash scripts/run_demo_panel_split.sh

echo "[3/6] qwen_score"
bash scripts/run_demo_qwen_score.sh

echo "[4/6] codex_reproduce"
bash scripts/run_demo_reproduce.sh

echo "[5/6] codex_refine"
bash scripts/run_demo_refine.sh

echo "[6/6] gallery_export"
bash scripts/run_demo_gallery.sh
