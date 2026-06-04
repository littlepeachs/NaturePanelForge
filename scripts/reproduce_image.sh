#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if [[ -z "${IMAGE_PATH:-}" ]]; then
  echo "ERROR: set IMAGE_PATH=/path/to/panel.png" >&2
  exit 1
fi

ARGS=(
  "${PYTHON_BIN}" -m nature_panel_forge.reproduce_image
  --image "${IMAGE_PATH}"
  --out-root "${OUT_ROOT:-${NPF_ROOT}/UserRuns/single_image_demo}"
  --chart-type "${CHART_TYPE:-user_supplied}"
  --model "${CODEX_MODEL:-gpt-5.4}"
  --reasoning-effort "${CODEX_REASONING_EFFORT:-medium}"
  --max-codex-processes "${MAX_CODEX_PROCESSES:-8}"
  --process-user "${CODEX_PROCESS_USER}"
  --timeout "${CODEX_TIMEOUT:-2400}"
  --poll-seconds "${CODEX_POLL_SECONDS:-10}"
  --review-rounds "${CODEX_REVIEW_ROUNDS:-4}"
  --codex-retries "${CODEX_RETRIES:-8}"
  --codex-retry-sleep "${CODEX_RETRY_SLEEP:-20}"
)
if [[ -n "${PANEL_ID:-}" ]]; then
  ARGS+=(--panel-id "${PANEL_ID}")
fi
if [[ -n "${CAPTION:-}" ]]; then
  ARGS+=(--caption "${CAPTION}")
fi
if [[ -n "${SOURCE_PDF:-}" ]]; then
  ARGS+=(--source-pdf "${SOURCE_PDF}")
fi
if [[ "${OVERWRITE:-0}" == "1" ]]; then
  ARGS+=(--overwrite)
fi
if [[ "${SKIP_EXISTING:-1}" == "1" ]]; then
  ARGS+=(--skip-existing)
fi
if [[ "${STREAM_EVENTS:-0}" == "1" ]]; then
  ARGS+=(--stream-events)
fi
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  ARGS+=(--dry-run)
fi
if [[ "${PRINT_COMMAND:-0}" == "1" ]]; then
  ARGS+=(--print-command)
fi

"${ARGS[@]}"
