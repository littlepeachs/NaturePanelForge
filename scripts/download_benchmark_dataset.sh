#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

DATASET_REPO="${DATASET_REPO:-littlepeachs/SciPanelForge}"
DATASET_DIR="${DATASET_DIR:-${NPF_ROOT}/.data/SciPanelForge}"

mkdir -p "${DATASET_DIR}"

"${PYTHON_BIN}" - "${DATASET_REPO}" "${DATASET_DIR}" <<'PY'
import os
import sys
from pathlib import Path
from huggingface_hub import snapshot_download

repo_id = sys.argv[1]
local_dir = Path(sys.argv[2]).expanduser().resolve()
token = os.environ.get("HF_TOKEN") or None
snapshot_download(
    repo_id=repo_id,
    repo_type="dataset",
    local_dir=str(local_dir),
    token=token,
)

preferred = [
    "clean_tiny100.json",
    "clean_mini500.json",
    "clean_dev1000.json",
    "clean_samples.json",
]
found = []
for name in preferred:
    found.extend(sorted(local_dir.rglob(name)))

print(f"dataset_dir={local_dir}")
if found:
    print("manifests:")
    for path in found:
        print(f"  {path}")
    print(f"export SCIFIGURE_DATASET={found[0]}")
else:
    print("No clean_*.json manifest was found. Inspect the downloaded dataset layout and set SCIFIGURE_DATASET manually.")
PY
