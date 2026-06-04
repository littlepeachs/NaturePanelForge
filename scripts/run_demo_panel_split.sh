#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

RUN_DIR="$(resolve_run_dir)"
SPECS_DIR="${RUN_DIR}/PanelSplitSpecsCodex_full"
mkdir -p "${SPECS_DIR}"

ARGS=(
  "${PYTHON_BIN}" agent_loop/codex_panel_split.py
  --full-figures-csv "${RUN_DIR}/FullFigures/full_figures.csv"
  --panels-dir "${RUN_DIR}/Panels_codex_full"
  --reviews-dir "${RUN_DIR}/PanelReviews_codex_full"
  --specs-dir "${SPECS_DIR}"
  --model "${CODEX_MODEL:-gpt-5.4}"
  --reasoning-effort "${CODEX_REASONING_EFFORT:-medium}"
  --jobs "${CODEX_JOBS:-4}"
  --max-codex-processes "${MAX_CODEX_PROCESSES:-8}"
  --process-user "${CODEX_PROCESS_USER}"
  --timeout "${CODEX_TIMEOUT:-2400}"
  --review-rounds "${CODEX_REVIEW_ROUNDS:-4}"
  --codex-retries "${CODEX_RETRIES:-8}"
  --codex-retry-sleep "${CODEX_RETRY_SLEEP:-20}"
  --poll-seconds "${CODEX_POLL_SECONDS:-10}"
)
if [[ "${PANEL_LIMIT:-5}" != "0" ]]; then
  ARGS+=(--limit "${PANEL_LIMIT:-5}")
fi
if [[ "${PANEL_OVERWRITE:-0}" == "1" ]]; then
  ARGS+=(--overwrite)
else
  ARGS+=(--skip-existing)
fi

"${ARGS[@]}"
