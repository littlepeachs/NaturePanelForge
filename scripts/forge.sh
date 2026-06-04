#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

"${PYTHON_BIN}" forge.py "$@"
