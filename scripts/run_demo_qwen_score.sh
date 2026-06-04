#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

RUN_DIR="$(resolve_run_dir)"
PANELS_DIR="${PANELS_DIR:-${RUN_DIR}/Panels_codex_full}"
SCORES_DIR="${SCORES_DIR:-${RUN_DIR}/QwenPanelScore}"
QWEN_MODEL_PATH="${QWEN_MODEL_PATH:-${NPF_ROOT}/models/Qwen3.6-27B}"
SCORE_BATCH_SIZE="${SCORE_BATCH_SIZE:-4}"

"${PYTHON_BIN}" agent_loop/build_codex_panels_manifest.py \
  --run-dir "${RUN_DIR}" \
  --panels-dir "${PANELS_DIR}" \
  --specs-dir "${RUN_DIR}/PanelSplitSpecsCodex_full"

COMMON_SCORE_ARGS=(
  --panels-csv "${PANELS_DIR}/panels.csv"
  --scores-dir "${SCORES_DIR}"
  --model-path "${QWEN_MODEL_PATH}"
  --backend transformers
  --device-map auto
  --batch-size "${SCORE_BATCH_SIZE}"
)
if [[ "${OVERWRITE:-0}" == "1" ]]; then
  COMMON_SCORE_ARGS+=(--overwrite)
fi

CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}" \
PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}" \
"${PYTHON_BIN}" agent_loop/qwen_panel_scoring.py prepare "${COMMON_SCORE_ARGS[@]}"

CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}" \
PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}" \
"${PYTHON_BIN}" agent_loop/qwen_panel_scoring.py score "${COMMON_SCORE_ARGS[@]}"
