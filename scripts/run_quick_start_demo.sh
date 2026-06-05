#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

DEMO_CASE="${DEMO_CASE:-quick_start_bubble_plot}"
DEMO_DIR="${DEMO_DIR:-${NPF_ROOT}/docs/demo/${DEMO_CASE}}"
PANEL_ID="${PANEL_ID:-${DEMO_CASE}}"
OUT_ROOT="${OUT_ROOT:-${NPF_ROOT}/UserRuns/${DEMO_CASE}}"
CAPTION="${CAPTION:-A faceted GO enrichment bubble plot comparing Human and Mouse columns across FHO, Erythroid, Lymphoid, and Myeloid row groups. The x axis is -log10(p.value), bubble size encodes log10(count), and colors encode biological groups.}"

mkdir -p "${OUT_ROOT}"

if [[ ! -f "${DEMO_DIR}/target.png" ]]; then
  echo "[demo] missing target image: ${DEMO_DIR}/target.png" >&2
  exit 1
fi

if [[ ! -f "${DEMO_DIR}/reproduce_panel.py" ]]; then
  echo "[demo] missing editable reference script: ${DEMO_DIR}/reproduce_panel.py" >&2
  exit 1
fi

SOURCE_PDF_ARGS=()
if [[ -f "${DEMO_DIR}/target.pdf" ]]; then
  SOURCE_PDF_ARGS=(--source-pdf "${DEMO_DIR}/target.pdf")
fi

echo "[demo] case: ${DEMO_CASE}"
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
    "${SOURCE_PDF_ARGS[@]}" \
    --panel-id "${PANEL_ID}" \
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
  echo "  RUN_CODEX=1 DEMO_CASE=${DEMO_CASE} bash scripts/run_quick_start_demo.sh"
fi
