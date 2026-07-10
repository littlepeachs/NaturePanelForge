#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ZERO_SHOT_MODELS=(
  intern_s2_preview
  glm_4_5v
  llava_onevision_qwen2_72b
  ovis2_6_80b_a3b
  phi4_reasoning_vision_15b
  molmo_72b
  qwen3_5_122b_a10b
  gemma4_31b_it
  pixtral_12b
  chartcoder
  chartide_8b
)

LIMIT="${LIMIT:-100}"
DATASET="${SCIFIGURE_DATASET:-${NPF_ROOT}/SciFigure2Code/benchmark_ready/clean_tiny100.json}"
RUN_LABEL="${RUN_LABEL:-$(date +%Y%m%d_%H%M%S)}"
RUN_PARALLEL="${RUN_PARALLEL:-0}"
IFS=',' read -r -a GPUS <<< "${GPU_IDS:-0}"

if [[ "${#GPUS[@]}" -eq 0 ]]; then
  GPUS=(0)
fi

echo "dataset=${DATASET}"
echo "limit=${LIMIT}"
echo "run_label=${RUN_LABEL}"
echo "gpu_ids=${GPU_IDS:-0}"
echo "parallel=${RUN_PARALLEL}"

PIDS=()
for index in "${!ZERO_SHOT_MODELS[@]}"; do
  model_id="${ZERO_SHOT_MODELS[$index]}"
  gpu_id="${GPUS[$((index % ${#GPUS[@]}))]}"
  echo "[run] ${model_id} gpu=${gpu_id}"
  if [[ "${RUN_PARALLEL}" == "1" ]]; then
    RUN_LABEL="${RUN_LABEL}" bash scripts/run_zeroshot_model.sh "${model_id}" "${gpu_id}" "${LIMIT}" "${DATASET}" &
    PIDS+=("$!")
  else
    RUN_LABEL="${RUN_LABEL}" bash scripts/run_zeroshot_model.sh "${model_id}" "${gpu_id}" "${LIMIT}" "${DATASET}"
  fi
done

if [[ "${#PIDS[@]}" -gt 0 ]]; then
  FAILED=0
  for pid in "${PIDS[@]}"; do
    if ! wait "${pid}"; then
      FAILED=1
    fi
  done
  if [[ "${FAILED}" != "0" ]]; then
    exit 1
  fi
fi

"${PYTHON_BIN}" scripts/summarize_zeroshot_runs.py \
  --run-root "${BENCHMARK_RUN_ROOT:-${NPF_ROOT}/BenchmarkRuns}" \
  --run-label "${RUN_LABEL}"
