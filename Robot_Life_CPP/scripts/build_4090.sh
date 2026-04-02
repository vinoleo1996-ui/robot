#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build_4090"

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

python3 "${ROOT_DIR}/scripts/check_full_migration.py"

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
  -DCMAKE_BUILD_TYPE=Release \
  -DROBOT_LIFE_CPP_ENABLE_CUDA=ON \
  -DROBOT_LIFE_CPP_REQUIRE_CUDA=ON \
  -DROBOT_LIFE_CPP_BUILD_TESTS=ON

"${CMAKE_BIN}" --build "${BUILD_DIR}" -j
echo "build complete: ${BUILD_DIR}"
