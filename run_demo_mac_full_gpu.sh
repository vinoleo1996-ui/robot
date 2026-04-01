#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8766}"
AUTO_OPEN_BROWSER="${AUTO_OPEN_BROWSER:-1}"
URL="http://${HOST}:${PORT}"

echo "=================================================="
echo " Robot Life - Mac Fast Reaction Demo (Full GPU) "
echo "=================================================="
echo "Profile: full-gpu"
echo "URL: ${URL}"
echo "This script starts the experimental full-gpu profile and tries to open the browser automatically."
echo "Use '--mock-if-unavailable' if you want to体验 UI without camera / microphone permissions."
echo "Use '--ci-mock' if you want a deterministic mock launch for smoke / CI."
echo ""

export LC_ALL="${LC_ALL:-en_US.UTF-8}"
export LANG="${LANG:-en_US.UTF-8}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="${PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION:-python}"

if [[ ! -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
    "${PROJECT_DIR}/scripts/bootstrap/bootstrap_env.sh"
fi

"${PROJECT_DIR}/scripts/launch/run_ui_local_fast_reaction.sh" start --full-gpu "$@"

echo ""
echo "UI address: ${URL}"

if [[ "${AUTO_OPEN_BROWSER}" == "1" ]] && command -v open >/dev/null 2>&1; then
    open "${URL}" >/dev/null 2>&1 || true
fi
