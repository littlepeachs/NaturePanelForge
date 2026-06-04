#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

RUN_DIR="$(resolve_run_dir)"
SCORES_CSV="${SCORES_CSV:-${RUN_DIR}/QwenPanelScore/panel_scores.csv}"
SCHEMATIC_DIR="${SCHEMATIC_DIR:-${RUN_DIR}/Final_Schematic}"
DATA_DIR="${DATA_DIR:-${RUN_DIR}/Reproduce_Statistical}"
REVIEWS_DIR="${REVIEWS_DIR:-${RUN_DIR}/Reproduce_Statistical_Reviews}"
SPECS_DIR="${SPECS_DIR:-${RUN_DIR}/Reproduce_Statistical_Specs}"

EXPORT_ARGS=(
  "${PYTHON_BIN}" export_qwen_selected_panels.py
  --scores-csv "${SCORES_CSV}" \
  --schematic-dir "${SCHEMATIC_DIR}" \
  --data-dir "${DATA_DIR}" \
  --min-data-purity-score "${MIN_DATA_PURITY_SCORE:-10}" \
  --min-code-reproducibility-score "${MIN_CODE_REPRODUCIBILITY_SCORE:-9}" \
  --min-aesthetic-score "${MIN_AESTHETIC_SCORE:-8}"
)
if [[ "${EXPORT_OVERWRITE:-0}" == "1" ]]; then
  EXPORT_ARGS+=(--overwrite)
fi
"${EXPORT_ARGS[@]}"

PANEL_LIST="${DATA_DIR}/panel_dirs.txt"
if [[ "${REPRODUCE_PANEL_LIMIT:-5}" != "0" ]]; then
  PANEL_LIST="${DATA_DIR}/panel_dirs.limit${REPRODUCE_PANEL_LIMIT:-5}.txt"
  grep -v '^[[:space:]]*$' "${DATA_DIR}/panel_dirs.txt" | head -n "${REPRODUCE_PANEL_LIMIT:-5}" > "${PANEL_LIST}"
fi

"${PYTHON_BIN}" examples/prompt_codex_reproduce_fig02_g.py \
  --panel-list "${PANEL_LIST}" \
  --panel-root "${DATA_DIR}" \
  --reviews-dir "${REVIEWS_DIR}" \
  --specs-dir "${SPECS_DIR}" \
  --model "${CODEX_MODEL:-gpt-5.4}" \
  --reasoning-effort "${CODEX_REASONING_EFFORT:-medium}" \
  --jobs "${CODEX_JOBS:-4}" \
  --max-codex-processes "${MAX_CODEX_PROCESSES:-8}" \
  --process-user "${CODEX_PROCESS_USER}" \
  --timeout "${CODEX_TIMEOUT:-2400}" \
  --poll-seconds "${CODEX_POLL_SECONDS:-10}" \
  --review-rounds "${CODEX_REVIEW_ROUNDS:-4}" \
  --codex-retries "${CODEX_RETRIES:-8}" \
  --codex-retry-sleep "${CODEX_RETRY_SLEEP:-20}" \
  --skip-existing
