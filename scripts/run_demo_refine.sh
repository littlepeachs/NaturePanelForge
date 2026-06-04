#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

RUN_DIR="$(resolve_run_dir)"
SOURCE_DATA_DIR="${SOURCE_DATA_DIR:-${RUN_DIR}/Reproduce_Statistical}"
SOURCE_REVIEWS_DIR="${SOURCE_REVIEWS_DIR:-${RUN_DIR}/Reproduce_Statistical_Reviews}"
SOURCE_SPECS_DIR="${SOURCE_SPECS_DIR:-${RUN_DIR}/Reproduce_Statistical_Specs}"
REFINED_DATA_DIR="${REFINED_DATA_DIR:-${RUN_DIR}/Reproduce_Statistical_Refined}"
REFINED_REVIEWS_DIR="${REFINED_REVIEWS_DIR:-${RUN_DIR}/Reproduce_Statistical_Refined_Reviews}"
REFINED_SPECS_DIR="${REFINED_SPECS_DIR:-${RUN_DIR}/Reproduce_Statistical_Refined_Specs}"

PREPARE_ARGS=(
  "${PYTHON_BIN}" prepare_refined_reproduce_panels.py
  --source-data-dir "${SOURCE_DATA_DIR}" \
  --source-reviews-dir "${SOURCE_REVIEWS_DIR}" \
  --source-specs-dir "${SOURCE_SPECS_DIR}" \
  --refined-data-dir "${REFINED_DATA_DIR}" \
  --refined-reviews-dir "${REFINED_REVIEWS_DIR}" \
  --refined-specs-dir "${REFINED_SPECS_DIR}"
)
if [[ "${PREPARE_LIMIT:-0}" != "0" ]]; then
  PREPARE_ARGS+=(--limit "${PREPARE_LIMIT}")
fi
if [[ "${PREPARE_OVERWRITE:-0}" == "1" ]]; then
  PREPARE_ARGS+=(--overwrite)
fi
"${PREPARE_ARGS[@]}"

"${PYTHON_BIN}" examples/prompt_codex_refine_reproduce.py \
  --panel-list "${REFINED_DATA_DIR}/panel_dirs.txt" \
  --panel-root "${REFINED_DATA_DIR}" \
  --reviews-dir "${REFINED_REVIEWS_DIR}" \
  --specs-dir "${REFINED_SPECS_DIR}" \
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
