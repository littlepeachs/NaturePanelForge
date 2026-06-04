#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_ROOT="${REPO_ROOT}/skills"
DEST_ROOT="${CODEX_HOME:-${HOME}/.codex}/skills"

if [[ ! -d "${SOURCE_ROOT}" ]]; then
  echo "ERROR: skills directory not found: ${SOURCE_ROOT}" >&2
  exit 1
fi

if [[ "${DRY_RUN:-0}" != "1" ]]; then
  mkdir -p "${DEST_ROOT}"
fi

for skill_dir in "${SOURCE_ROOT}"/*; do
  [[ -d "${skill_dir}" ]] || continue
  skill_name="$(basename "${skill_dir}")"
  if [[ ! -f "${skill_dir}/SKILL.md" ]]; then
    echo "Skipping ${skill_name}: missing SKILL.md" >&2
    continue
  fi

  dest_dir="${DEST_ROOT}/${skill_name}"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    echo "Would install ${skill_name} -> ${dest_dir}"
  else
    rm -rf "${dest_dir}"
    mkdir -p "${dest_dir}"
    cp -a "${skill_dir}/." "${dest_dir}/"
    echo "Installed ${skill_name} -> ${dest_dir}"
  fi
done
