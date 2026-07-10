#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/download_zeroshot_models.sh [MODEL_ID ...]
  bash scripts/download_zeroshot_models.sh --list

If no MODEL_ID is given, downloads the fixed 11-model zero-shot roster.
Set HF_TOKEN for gated repositories and VLM_ROOT/VLM_MODEL_ROOT to choose the
local cache location.
USAGE
}

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

model_rel_path() {
  case "$1" in
    chartcoder) printf '%s\n' "xxxllz/ChartCoder" ;;
    chartide_8b) printf '%s\n' "Fengx1nn/CharTide-8B" ;;
    phi4_reasoning_vision_15b) printf '%s\n' "microsoft/Phi-4-reasoning-vision-15B" ;;
    pixtral_12b) printf '%s\n' "mistralai/Pixtral-12B-2409" ;;
    gemma4_31b_it) printf '%s\n' "google/gemma-4-31B-it" ;;
    intern_s2_preview) printf '%s\n' "internlm/Intern-S2-Preview" ;;
    llava_onevision_qwen2_72b) printf '%s\n' "llava-hf/llava-onevision-qwen2-72b-ov-hf" ;;
    ovis2_6_80b_a3b) printf '%s\n' "AIDC-AI/Ovis2.6-80B-A3B" ;;
    glm_4_5v) printf '%s\n' "zai-org/GLM-4.5V" ;;
    qwen3_5_122b_a10b) printf '%s\n' "Qwen/Qwen3.5-122B-A10B" ;;
    molmo_72b) printf '%s\n' "allenai/Molmo-72B-0924" ;;
    *) return 1 ;;
  esac
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--list" ]]; then
  for model_id in "${ZERO_SHOT_MODELS[@]}"; do
    printf '%-32s %s\n' "${model_id}" "$(model_rel_path "${model_id}")"
  done
  exit 0
fi

VLM_ROOT="${VLM_ROOT:-${NPF_ROOT}/.models}"
VLM_MODEL_ROOT="${VLM_MODEL_ROOT:-${VLM_ROOT}/models}"
export HF_HOME="${HF_HOME:-${VLM_ROOT}/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-${HF_HOME}/hub}"
export HF_XET_CACHE="${HF_XET_CACHE:-${HF_HOME}/xet}"
export HF_ASSETS_CACHE="${HF_ASSETS_CACHE:-${HF_HOME}/assets}"
mkdir -p "${VLM_MODEL_ROOT}" "${HF_HOME}" "${HF_HUB_CACHE}" "${HF_XET_CACHE}" "${HF_ASSETS_CACHE}"

MODELS=("$@")
if [[ "${#MODELS[@]}" -eq 0 ]]; then
  MODELS=("${ZERO_SHOT_MODELS[@]}")
fi

for model_id in "${MODELS[@]}"; do
  rel_path="$(model_rel_path "${model_id}")" || {
    echo "ERROR: unknown model id: ${model_id}" >&2
    exit 2
  }
  repo_id="${rel_path}"
  local_dir="${VLM_MODEL_ROOT}/${rel_path}"
  mkdir -p "${local_dir}"
  echo "[download] ${model_id} <- ${repo_id}"
  echo "[target]   ${local_dir}"
  "${PYTHON_BIN}" - "${repo_id}" "${local_dir}" <<'PY'
import os
import sys
from huggingface_hub import snapshot_download

repo_id = sys.argv[1]
local_dir = sys.argv[2]
token = os.environ.get("HF_TOKEN") or None
snapshot_download(
    repo_id=repo_id,
    repo_type="model",
    local_dir=local_dir,
    token=token,
)
print(local_dir)
PY
done

cat <<EOF

Downloaded model root:
  ${VLM_MODEL_ROOT}

For ChartCoder, also set CHARTCODER_REPO to a local checkout of the ChartCoder
source tree that provides the llava package:
  export CHARTCODER_REPO=/path/to/ChartCoder
EOF
