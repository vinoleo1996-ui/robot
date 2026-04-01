#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! "${PYTHON_BIN}" -m venv --clear .venv 2>/dev/null; then
  "${PYTHON_BIN}" -m virtualenv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev,mvp,audio]"

echo "Bootstrap complete."
echo "Using Python: ${PYTHON_BIN}"
echo "Activate with: source .venv/bin/activate"
