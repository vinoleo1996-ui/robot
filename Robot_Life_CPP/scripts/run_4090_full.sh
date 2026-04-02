#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build_4090"
BIN="${BUILD_DIR}/robot_life_cpp_main"

"${ROOT_DIR}/scripts/build_4090.sh"

if [[ ! -x "${BIN}" ]]; then
  echo "binary not found: ${BIN}"
  exit 1
fi

echo "running: ${BIN}"
OUTPUT="$("${BIN}" run-live --profile linux_deepstream_4vision --ticks 4 --ui false)"
echo "${OUTPUT}"
if ! grep -q "CUDA available: yes" <<<"${OUTPUT}"; then
  echo "ERROR: CUDA runtime is not active. This script is for RTX 4090 deployment."
  exit 2
fi
