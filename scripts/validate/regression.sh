#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

"${PYTHON_BIN}" -m compileall -q src
"${PYTHON_BIN}" -m pytest -q tests/unit/test_cli_smoke.py tests/unit/test_cli_shared_camera.py tests/integration/test_e2e_smoke.py
"${PYTHON_BIN}" scripts/validate/validate_fast_reaction_experience.py --duration-sec 1 --config configs/runtime/app.default.yaml --detectors configs/detectors/local/local_mac_fast_reaction.yaml >/dev/null
bash "${ROOT_DIR}/scripts/validate/smoke_mock_profile.sh"
bash "${ROOT_DIR}/scripts/validate/smoke_local_mac_profile.sh"
bash "${ROOT_DIR}/scripts/validate/smoke_local_mac_lite_profile.sh"
bash "${ROOT_DIR}/scripts/validate/smoke_local_mac_realtime_profile.sh"
bash "${ROOT_DIR}/scripts/validate/smoke_desktop_4090_profile.sh"

echo "Regression suite passed."
