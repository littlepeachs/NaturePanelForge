#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NPF_ROOT="${NPF_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
cd "${NPF_ROOT}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
RUN_ROOT="${RUN_ROOT:-${NPF_ROOT}/PipelineRuns}"
STATE_ROOT="${STATE_ROOT:-${NPF_ROOT}/PipelineState}"
FINAL_ROOT="${FINAL_ROOT:-${NPF_ROOT}/Final}"
GALLERY_ROOT="${GALLERY_ROOT:-${NPF_ROOT}/gallery}"
CODEX_PROCESS_USER="${CODEX_PROCESS_USER:-${USER:-unknown}}"

mkdir -p "${RUN_ROOT}" "${STATE_ROOT}" "${FINAL_ROOT}" "${GALLERY_ROOT}"

latest_run_dir() {
  local subject="${1:?subject required}"
  local topic="${2:?topic required}"
  find "${RUN_ROOT}/${subject}/${topic}" -mindepth 1 -maxdepth 1 -type d -name 'run_*' 2>/dev/null | sort | tail -n 1
}

resolve_run_dir() {
  local subject="${SUBJECT:-biology}"
  local topic="${TOPIC:-AI_biology}"
  if [[ -n "${RUN_DIR:-}" ]]; then
    printf '%s\n' "${RUN_DIR}"
    return 0
  fi
  local found
  found="$(latest_run_dir "${subject}" "${topic}")"
  if [[ -z "${found}" ]]; then
    echo "ERROR: RUN_DIR is not set and no run_* directory exists under ${RUN_ROOT}/${subject}/${topic}" >&2
    exit 1
  fi
  printf '%s\n' "${found}"
}

format_duration() {
  local total="$1"
  printf "%02d:%02d:%02d" "$((total / 3600))" "$(((total % 3600) / 60))" "$((total % 60))"
}
