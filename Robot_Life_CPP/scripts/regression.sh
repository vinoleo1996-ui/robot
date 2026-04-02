#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build"

CMAKE_BIN="${CMAKE_BIN:-cmake}"
if ! command -v "${CMAKE_BIN}" >/dev/null 2>&1; then
  if [[ -x "${ROOT_DIR}/../.venv/bin/cmake" ]]; then
    CMAKE_BIN="${ROOT_DIR}/../.venv/bin/cmake"
    export PATH="${ROOT_DIR}/../.venv/bin:${PATH}"
  else
    echo "cmake not found. install cmake first."
    exit 1
  fi
fi

if ! command -v ctest >/dev/null 2>&1; then
  if [[ -x "${ROOT_DIR}/../.venv/bin/ctest" ]]; then
    export PATH="${ROOT_DIR}/../.venv/bin:${PATH}"
  fi
fi

GENERATOR="${GENERATOR:-Ninja}"
if [[ "${GENERATOR}" == "Ninja" ]] && ! command -v ninja >/dev/null 2>&1; then
  if [[ -x "${ROOT_DIR}/../.venv/bin/ninja" ]]; then
    export PATH="${ROOT_DIR}/../.venv/bin:${PATH}"
  else
    GENERATOR="Unix Makefiles"
  fi
fi

"${CMAKE_BIN}" -S "${ROOT_DIR}" -B "${BUILD_DIR}" \
  -G "${GENERATOR}" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DROBOT_LIFE_CPP_ENABLE_CUDA=OFF \
  -DROBOT_LIFE_CPP_BUILD_TESTS=ON
"${CMAKE_BIN}" --build "${BUILD_DIR}" -j
"${ROOT_DIR}/scripts/doctor.sh"
ctest --test-dir "${BUILD_DIR}" --output-on-failure
"${BUILD_DIR}/robot_life_cpp_main" doctor
"${ROOT_DIR}/scripts/deepstream_real_bridge_smoke.sh"
"${ROOT_DIR}/scripts/deepstream_real_bridge_failure_smoke.sh"
"${ROOT_DIR}/scripts/ui_dashboard_smoke.sh"
"${BUILD_DIR}/robot_life_cpp_main" run-live --profile mac_debug_native --ticks 2 --ui false
"${BUILD_DIR}/robot_life_cpp_main"
