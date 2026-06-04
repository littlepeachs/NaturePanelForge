#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

SUBJECT="${SUBJECT:-biology}"
TOPIC="${TOPIC:-AI_biology}"
QUERY_DOMAIN="${QUERY_DOMAIN:-biology}"
TARGET_PAPERS="${TARGET_PAPERS:-2}"
BATCH_SIZE="${BATCH_SIZE:-${TARGET_PAPERS}}"
MAX_BATCHES="${MAX_BATCHES:-1}"
FIGURES_PER_PAPER="${FIGURES_PER_PAPER:-2}"
YEARS="${YEARS:-2025,2026}"
FULL_FIGURE_WORKERS="${FULL_FIGURE_WORKERS:-8}"
FULL_FIGURE_BATCH_SIZE="${FULL_FIGURE_BATCH_SIZE:-4}"
FULL_FIGURE_BATCH_SLEEP="${FULL_FIGURE_BATCH_SLEEP:-0.5}"
DRY_RUN="${DRY_RUN:-0}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-0}"
RESUME_RUN="${RESUME_RUN:-${RUN_DIR:-}}"

SEARCH_TERM="${SEARCH_TERM:-}"
if [[ -z "${SEARCH_TERM}" ]]; then
  IFS=',' read -r -a YEAR_ARGS <<< "${YEARS}"
  SEARCH_TERM="$("${PYTHON_BIN}" agent_loop/keyword_query_builder.py query --domain "${QUERY_DOMAIN}" --years "${YEAR_ARGS[@]}")"
fi

START_EPOCH="$(date +%s)"
CMD=(
  "${PYTHON_BIN}" run_continuous_pipeline.py
  --subject "${SUBJECT}"
  --topic "${TOPIC}"
  --batch-size "${BATCH_SIZE}"
  --target-papers "${TARGET_PAPERS}"
  --figures-per-paper "${FIGURES_PER_PAPER}"
  --years "${YEARS}"
  --max-batches "${MAX_BATCHES}"
  --run-root "${RUN_ROOT}"
  --state-root "${STATE_ROOT}"
  --final-root "${FINAL_ROOT}"
  --full-figure-workers "${FULL_FIGURE_WORKERS}"
  --full-figure-batch-size "${FULL_FIGURE_BATCH_SIZE}"
  --full-figure-batch-sleep "${FULL_FIGURE_BATCH_SLEEP}"
  --panel-splitter codex
  --skip-yolo
  --skip-qwen
  --skip-codex
  --search-term "${SEARCH_TERM}"
)
if [[ -n "${RESUME_RUN}" ]]; then
  CMD+=(--resume-run "${RESUME_RUN}")
fi
if [[ "${SKIP_DOWNLOAD}" == "1" ]]; then
  CMD+=(--skip-download)
fi
if [[ "${DRY_RUN}" == "1" ]]; then
  CMD+=(--dry-run)
fi

"${CMD[@]}"

END_EPOCH="$(date +%s)"
echo "paper_to_fullfig elapsed: $(format_duration "$((END_EPOCH - START_EPOCH))")"
