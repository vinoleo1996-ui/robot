#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "error: expected virtualenv python at ${PYTHON_BIN}"
  exit 1
fi

DURATION_SEC="${DURATION_SEC:-15}"
CAMERA_DEVICE="${CAMERA_DEVICE:-0}"
CAMERA_READ_TIMEOUT_MS="${CAMERA_READ_TIMEOUT_MS:-220}"
STRICT_CAMERA_INDEX="${STRICT_CAMERA_INDEX:-0}"
PRECHECK_SCRIPT="${ROOT_DIR}/scripts/validate/preflight_local_fast_reaction.py"

if [[ ! -f "${PRECHECK_SCRIPT}" ]]; then
  echo "error: preflight script not found: ${PRECHECK_SCRIPT}"
  exit 1
fi

preflight_output="$("${PYTHON_BIN}" "${PRECHECK_SCRIPT}" \
  --runtime-config "${ROOT_DIR}/configs/runtime/local/local_mac_fast_reaction_realtime.yaml" \
  --detector-config "${ROOT_DIR}/configs/detectors/local/local_mac_fast_reaction_realtime.yaml" \
  --stabilizer-config "${ROOT_DIR}/configs/stabilizer/local/local_mac_fast_reaction.yaml" \
  --camera-device-index "${CAMERA_DEVICE}" 2>&1)" || {
    printf '%s\n' "${preflight_output}"
    echo "[error] preflight failed, benchmark aborted."
    exit 1
  }

printf '%s\n' "${preflight_output}"
RESOLVED_CAMERA="$(printf '%s\n' "${preflight_output}" | awk -F= '/^camera_device_actual=/{print $2; exit}')"
if [[ "${RESOLVED_CAMERA}" =~ ^[0-9]+$ ]]; then
  CAMERA_DEVICE="${RESOLVED_CAMERA}"
fi

STRICT_ARGS=()
if [[ "${STRICT_CAMERA_INDEX}" == "1" ]]; then
  STRICT_ARGS+=(--strict-camera-index)
fi

echo "[info] benchmark camera_device=${CAMERA_DEVICE} strict=${STRICT_CAMERA_INDEX}"

exec "${PYTHON_BIN}" scripts/validate/validate_fast_reaction_experience.py \
  --config configs/runtime/local/local_mac_fast_reaction_realtime.yaml \
  --detectors configs/detectors/local/local_mac_fast_reaction_realtime.yaml \
  --stabilizer configs/stabilizer/local/local_mac_fast_reaction.yaml \
  --duration-sec "${DURATION_SEC}" \
  --camera-device-index "${CAMERA_DEVICE}" \
  --camera-read-timeout-ms "${CAMERA_READ_TIMEOUT_MS}" \
  "${STRICT_ARGS[@]}" \
  "$@"
