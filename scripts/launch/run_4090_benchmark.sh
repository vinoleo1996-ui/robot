#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
REPORT_DIR="${ROOT_DIR}/runtime/benchmarks"
mkdir -p "${REPORT_DIR}"

TS="$(date +%Y%m%d_%H%M%S)"
RAW_LOG="${REPORT_DIR}/validate_4090_${TS}.log"
MD_REPORT="${REPORT_DIR}/validate_4090_${TS}.md"

PY_BIN="${PY_BIN:-python3}"
CAMERA_DEVICE="${CAMERA_DEVICE:-0}"
ITERATIONS="${ITERATIONS:-300}"
POLL_INTERVAL="${POLL_INTERVAL:-0.033}"

echo "[benchmark] running validate_4090 ..."
"${PY_BIN}" "${ROOT_DIR}/scripts/validate/validate_4090.py" \
  --config "${ROOT_DIR}/configs/runtime/desktop_4090/desktop_4090.yaml" \
  --detectors "${ROOT_DIR}/configs/detectors/desktop_4090/desktop_4090.yaml" \
  --stabilizer "${ROOT_DIR}/configs/stabilizer/default.yaml" \
  --slow-scene-config "${ROOT_DIR}/configs/slow_scene/default.yaml" \
  --iterations "${ITERATIONS}" \
  --poll-interval "${POLL_INTERVAL}" \
  --camera-device-index "${CAMERA_DEVICE}" \
  --enable-slow-scene \
  --require-gpu | tee "${RAW_LOG}"

{
  echo "# 4090 Benchmark Report"
  echo
  echo "- Timestamp: ${TS}"
  echo "- Camera device: ${CAMERA_DEVICE}"
  echo "- Iterations: ${ITERATIONS}"
  echo "- Poll interval: ${POLL_INTERVAL}"
  echo "- Raw log: ${RAW_LOG}"
  echo
  echo "## Raw Summary"
  echo
  echo '```text'
  cat "${RAW_LOG}"
  echo '```'
} > "${MD_REPORT}"

echo "[benchmark] report generated: ${MD_REPORT}"
