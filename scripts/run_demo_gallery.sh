#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

RUN_DIR="$(resolve_run_dir)"
SUBJECT="${SUBJECT:-biology}"
TOPIC="${TOPIC:-AI_biology}"

EXPORT_ARGS=(
  "${PYTHON_BIN}" -m nature_panel_forge.export_reproduced_gallery
  --run-dir "${RUN_DIR}" \
  --subject "${SUBJECT}" \
  --topic "${TOPIC}" \
  --gallery-root "${GALLERY_ROOT}" \
  --overwrite
)
if [[ "${REFINED_ONLY:-0}" == "1" ]]; then
  EXPORT_ARGS+=(--refined-only)
fi
if [[ "${ALL_REFINED:-0}" == "1" ]]; then
  EXPORT_ARGS+=(--all-refined)
fi
"${EXPORT_ARGS[@]}"

"${PYTHON_BIN}" gallery/tools/build_catalog.py --gallery-root "${GALLERY_ROOT}"

echo "Serve locally with:"
echo "  cd ${GALLERY_ROOT} && python3 -m http.server ${GALLERY_PORT:-18081} --bind 0.0.0.0"
echo "Then open: http://<server-ip>:${GALLERY_PORT:-18081}/"
