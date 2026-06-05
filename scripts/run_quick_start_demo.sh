#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

DEMO_DIR="${NPF_ROOT}/docs/demo/quick_start_bubble_plot"
OUT_ROOT="${OUT_ROOT:-${NPF_ROOT}/UserRuns/quick_start_bubble_plot}"
CAPTION="${CAPTION:-A faceted GO enrichment bubble plot comparing Human and Mouse columns across FHO, Erythroid, Lymphoid, and Myeloid row groups. The x axis is -log10(p.value), bubble size encodes log10(count), and colors encode biological groups.}"

mkdir -p "${OUT_ROOT}"

echo "[demo] target panel: ${DEMO_DIR}/target.png"
echo "[demo] editable reference script: ${DEMO_DIR}/reproduce_panel.py"

"${PYTHON_BIN}" "${DEMO_DIR}/reproduce_panel.py"
echo "[demo] offline render complete:"
echo "  ${DEMO_DIR}/reproduce_panel.png"
echo "  ${DEMO_DIR}/reproduce_panel.pdf"

if [[ "${RUN_CODEX:-0}" == "1" ]]; then
  echo "[demo] running Codex single-panel-image agent loop"
  "${PYTHON_BIN}" "${NPF_ROOT}/forge.py" single-panel-image \
    --image "${DEMO_DIR}/target.png" \
    --source-pdf "${DEMO_DIR}/target.pdf" \
    --panel-id quick_start_bubble_plot \
    --chart-type bubble_plot \
    --caption "${CAPTION}" \
    --out-root "${OUT_ROOT}" \
    --model "${CODEX_MODEL:-gpt-5.4}" \
    --reasoning-effort "${CODEX_REASONING_EFFORT:-medium}" \
    --review-rounds "${CODEX_REVIEW_ROUNDS:-4}" \
    --skip-existing
  echo "[demo] Codex output root: ${OUT_ROOT}"
else
  echo "[demo] skipped live Codex loop. To run it:"
  echo "  RUN_CODEX=1 bash scripts/run_quick_start_demo.sh"
fi
