#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 MODEL_ID [GPU_ID] [LIMIT] [DATASET]" >&2
  echo "Example: $0 chartide_8b 0 100 SciFigure2Code/benchmark_ready/clean_tiny100.json" >&2
  exit 2
fi

MODEL_ID="$1"
GPU_ID="${2:-${CUDA_VISIBLE_DEVICES:-0}}"
LIMIT="${3:-${LIMIT:-100}}"
DATASET="${4:-${SCIFIGURE_DATASET:-${NPF_ROOT}/SciFigure2Code/benchmark_ready/clean_tiny100.json}}"
MODE="${BENCHMARK_MODE:-zeroshot}"
PROMPT_STYLE="${PROMPT_STYLE:-short}"
MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-2048}"
TIMEOUT="${TIMEOUT:-180}"
VLM_ROOT="${VLM_ROOT:-${NPF_ROOT}/.models}"
VLM_MODEL_ROOT="${VLM_MODEL_ROOT:-${VLM_ROOT}/models}"
RUN_ROOT="${BENCHMARK_RUN_ROOT:-${NPF_ROOT}/BenchmarkRuns}"
RUN_LABEL="${RUN_LABEL:-$(date +%Y%m%d_%H%M%S)}"
OUT_DIR="${RUN_ROOT}/${MODEL_ID}_${MODE}_${LIMIT}_${RUN_LABEL}"
LOG_DIR="${RUN_ROOT}/logs"
LOG_FILE="${LOG_DIR}/${MODEL_ID}_${MODE}_${LIMIT}_${RUN_LABEL}.log"
TIME_FILE="${LOG_DIR}/${MODEL_ID}_${MODE}_${LIMIT}_${RUN_LABEL}.time.json"

mkdir -p "${OUT_DIR}" "${LOG_DIR}"
export VLM_ROOT VLM_MODEL_ROOT
export HF_HOME="${HF_HOME:-${VLM_ROOT}/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-${HF_HOME}/hub}"
export HF_XET_CACHE="${HF_XET_CACHE:-${HF_HOME}/xet}"
export HF_ASSETS_CACHE="${HF_ASSETS_CACHE:-${HF_HOME}/assets}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

START_EPOCH="$(date +%s)"
START_ISO="$(date --iso-8601=seconds)"
STATUS="success"

{
  echo "model_id=${MODEL_ID}"
  echo "gpu_id=${GPU_ID}"
  echo "limit=${LIMIT}"
  echo "mode=${MODE}"
  echo "prompt_style=${PROMPT_STYLE}"
  echo "dataset=${DATASET}"
  echo "output_dir=${OUT_DIR}"
  echo "start=${START_ISO}"
} > "${LOG_FILE}"

set +e
CUDA_VISIBLE_DEVICES="${GPU_ID}" \
"${PYTHON_BIN}" -m SciFigure2Code.evaluation \
  --dataset "${DATASET}" \
  --model-id "${MODEL_ID}" \
  --benchmark-mode "${MODE}" \
  --prompt-style "${PROMPT_STYLE}" \
  --limit "${LIMIT}" \
  --max-new-tokens "${MAX_NEW_TOKENS}" \
  --timeout "${TIMEOUT}" \
  --gpus "${GPU_ID}" \
  --vlm-root "${VLM_ROOT}" \
  --resume \
  --output-dir "${OUT_DIR}" \
  >> "${LOG_FILE}" 2>&1
RC="$?"
set -e

END_EPOCH="$(date +%s)"
END_ISO="$(date --iso-8601=seconds)"
if [[ "${RC}" != "0" ]]; then
  STATUS="failed"
fi

cat > "${TIME_FILE}" <<JSON
{
  "model_id": "${MODEL_ID}",
  "gpu_id": "${GPU_ID}",
  "limit": ${LIMIT},
  "mode": "${MODE}",
  "prompt_style": "${PROMPT_STYLE}",
  "max_new_tokens": ${MAX_NEW_TOKENS},
  "dataset": "${DATASET}",
  "output_dir": "${OUT_DIR}",
  "log_file": "${LOG_FILE}",
  "start_iso": "${START_ISO}",
  "end_iso": "${END_ISO}",
  "elapsed_seconds": $((END_EPOCH - START_EPOCH)),
  "returncode": ${RC},
  "status": "${STATUS}"
}
JSON

echo "status=${STATUS}"
echo "output_dir=${OUT_DIR}"
echo "log_file=${LOG_FILE}"
echo "time_file=${TIME_FILE}"

exit "${RC}"
