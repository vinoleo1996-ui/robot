#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build_orin_nx"
BIN="${BUILD_DIR}/robot_life_cpp_main"

PROFILE="${PROFILE:-deepstream_prod}"
RUNTIME_TUNING="${RUNTIME_TUNING:-${ROOT_DIR}/configs/runtime_tuning.yaml}"
GRAPH_CONFIG="${GRAPH_CONFIG:-${ROOT_DIR}/configs/deepstream_4vision.yaml}"
METADATA_PATH="${ROBOT_LIFE_CPP_DEEPSTREAM_METADATA_PATH:-/tmp/robot_life_cpp_deepstream_metadata.ndjson}"
APP_CONFIG_PATH="${ROBOT_LIFE_CPP_DEEPSTREAM_APP_CONFIG_PATH:-/tmp/robot_life_cpp_deepstream_app_orin.txt}"
DEEPSTREAM_MODE="${ROBOT_LIFE_CPP_DEEPSTREAM_MODE:-real}"
RUN_TICKS="${RUN_TICKS:-8}"
RUN_UI="${RUN_UI:-false}"
BUILD_TESTS="${BUILD_TESTS:-ON}"
GENERATOR="${GENERATOR:-Ninja}"
ORIN_SET_PERF="${ORIN_SET_PERF:-0}"
TEGRSTATS_INTERVAL_MS="${TEGRSTATS_INTERVAL_MS:-1000}"

usage() {
  cat <<'EOF'
Usage:
  scripts/orin_nx_deploy_debug.sh doctor
  scripts/orin_nx_deploy_debug.sh build
  scripts/orin_nx_deploy_debug.sh run
  scripts/orin_nx_deploy_debug.sh ui
  scripts/orin_nx_deploy_debug.sh smoke

Environment overrides:
  PROFILE=deepstream_prod
  RUNTIME_TUNING=/abs/path/runtime_tuning.yaml
  GRAPH_CONFIG=/abs/path/deepstream_4vision.yaml
  ROBOT_LIFE_CPP_DEEPSTREAM_METADATA_PATH=/tmp/robot_life_cpp_deepstream_metadata.ndjson
  ROBOT_LIFE_CPP_DEEPSTREAM_APP_CONFIG_PATH=/tmp/robot_life_cpp_deepstream_app_orin.txt
  ROBOT_LIFE_CPP_DEEPSTREAM_MODE=real
  RUN_TICKS=8
  RUN_UI=false
  BUILD_TESTS=ON
  ORIN_SET_PERF=1
EOF
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

log() {
  printf '[orin-nx] %s\n' "$*"
}

warn() {
  printf '[orin-nx][warn] %s\n' "$*" >&2
}

die() {
  printf '[orin-nx][fail] %s\n' "$*" >&2
  exit 1
}

resolve_cmake() {
  if have_cmd cmake; then
    echo "cmake"
    return
  fi
  if [[ -x "${ROOT_DIR}/../.venv/bin/cmake" ]]; then
    export PATH="${ROOT_DIR}/../.venv/bin:${PATH}"
    echo "${ROOT_DIR}/../.venv/bin/cmake"
    return
  fi
  die "cmake not found"
}

prepare_generator() {
  if [[ "${GENERATOR}" == "Ninja" ]] && ! have_cmd ninja; then
    if [[ -x "${ROOT_DIR}/../.venv/bin/ninja" ]]; then
      export PATH="${ROOT_DIR}/../.venv/bin:${PATH}"
    else
      GENERATOR="Unix Makefiles"
    fi
  fi
}

detect_deepstream_dir() {
  if [[ -n "${DEEPSTREAM_DIR:-}" && -d "${DEEPSTREAM_DIR}" ]]; then
    echo "${DEEPSTREAM_DIR}"
    return
  fi
  local candidates=(
    "/opt/nvidia/deepstream/deepstream"
    "/opt/nvidia/deepstream/deepstream-8.0"
    "/opt/nvidia/deepstream/deepstream-7.1"
    "/opt/nvidia/deepstream/deepstream-7.0"
    "/opt/nvidia/deepstream/deepstream-6.4"
  )
  local path
  for path in "${candidates[@]}"; do
    if [[ -d "${path}" ]]; then
      echo "${path}"
      return
    fi
  done
  echo ""
}

detect_deepstream_app() {
  if [[ -n "${DEEPSTREAM_APP:-}" && -x "${DEEPSTREAM_APP}" ]]; then
    echo "${DEEPSTREAM_APP}"
    return
  fi
  if have_cmd deepstream-app; then
    command -v deepstream-app
    return
  fi
  local ds_dir
  ds_dir="$(detect_deepstream_dir)"
  if [[ -n "${ds_dir}" && -x "${ds_dir}/bin/deepstream-app" ]]; then
    echo "${ds_dir}/bin/deepstream-app"
    return
  fi
  echo ""
}

jetpack_version() {
  if have_cmd dpkg-query && dpkg-query -W -f='${Version}' nvidia-jetpack >/dev/null 2>&1; then
    dpkg-query -W -f='${Version}' nvidia-jetpack 2>/dev/null || true
    return
  fi
  echo "unknown"
}

l4t_release() {
  if [[ -f /etc/nv_tegra_release ]]; then
    tr -d '\n' </etc/nv_tegra_release
    return
  fi
  echo "unknown"
}

maybe_enable_perf_mode() {
  if [[ "${ORIN_SET_PERF}" != "1" ]]; then
    return
  fi
  if ! have_cmd nvpmodel || ! have_cmd jetson_clocks; then
    warn "nvpmodel/jetson_clocks not available, skip perf mode"
    return
  fi
  if [[ "$(id -u)" -eq 0 ]]; then
    log "enabling max perf mode as root"
    nvpmodel -m 0 || warn "nvpmodel -m 0 failed"
    jetson_clocks || warn "jetson_clocks failed"
    return
  fi
  if have_cmd sudo && sudo -n true >/dev/null 2>&1; then
    log "enabling max perf mode via sudo"
    sudo -n nvpmodel -m 0 || warn "sudo nvpmodel -m 0 failed"
    sudo -n jetson_clocks || warn "sudo jetson_clocks failed"
    return
  fi
  warn "ORIN_SET_PERF=1 but no non-interactive sudo available, skip perf mode"
}

start_tegrastats() {
  if ! have_cmd tegrastats; then
    return
  fi
  local log_path="${ROOT_DIR}/logs/orin_tegrastats.log"
  mkdir -p "${ROOT_DIR}/logs"
  log "starting tegrastats -> ${log_path}"
  tegrastats --interval "${TEGRSTATS_INTERVAL_MS}" >"${log_path}" 2>&1 &
  TEGRASTATS_PID=$!
}

stop_tegrastats() {
  if [[ -n "${TEGRASTATS_PID:-}" ]]; then
    kill "${TEGRASTATS_PID}" >/dev/null 2>&1 || true
    wait "${TEGRASTATS_PID}" 2>/dev/null || true
  fi
}

run_doctor() {
  local arch
  arch="$(uname -m)"
  local ds_dir
  ds_dir="$(detect_deepstream_dir)"
  local ds_app
  ds_app="$(detect_deepstream_app)"

  log "Orin NX deploy doctor"
  log "root=${ROOT_DIR}"
  log "arch=${arch}"
  log "jetpack=$(jetpack_version)"
  log "l4t=$(l4t_release)"
  log "deepstream_dir=${ds_dir:-missing}"
  log "deepstream_app=${ds_app:-missing}"

  [[ "${arch}" == "aarch64" ]] || die "expected aarch64 Jetson host, got ${arch}"
  have_cmd python3 || die "python3 missing"
  have_cmd c++ || die "c++ missing"
  have_cmd gst-inspect-1.0 || die "gstreamer tools missing"
  [[ -f "${GRAPH_CONFIG}" ]] || die "graph config missing: ${GRAPH_CONFIG}"
  [[ -f "${RUNTIME_TUNING}" ]] || die "runtime tuning missing: ${RUNTIME_TUNING}"

  [[ -n "${ds_dir}" ]] || die "DeepStream directory not found"
  [[ -x "${ds_app}" ]] || die "deepstream-app not found"
  [[ -d "$(dirname "${METADATA_PATH}")" ]] || die "metadata path parent missing: ${METADATA_PATH}"

  export DEEPSTREAM_DIR="${ds_dir}"
  export DEEPSTREAM_APP="${ds_app}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_GRAPH_CONFIG="${GRAPH_CONFIG}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_METADATA_PATH="${METADATA_PATH}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_APP_CONFIG_PATH="${APP_CONFIG_PATH}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_MODE="${DEEPSTREAM_MODE}"

  "${ROOT_DIR}/scripts/doctor.sh"
  if [[ -x "${BIN}" ]]; then
    "${BIN}" doctor
  else
    log "binary not built yet, compiled doctor skipped"
  fi
}

run_build() {
  local cmake_bin
  cmake_bin="$(resolve_cmake)"
  prepare_generator

  python3 "${ROOT_DIR}/scripts/check_full_migration.py"

  export DEEPSTREAM_DIR="${DEEPSTREAM_DIR:-$(detect_deepstream_dir)}"
  export DEEPSTREAM_APP="${DEEPSTREAM_APP:-$(detect_deepstream_app)}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_GRAPH_CONFIG="${GRAPH_CONFIG}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_METADATA_PATH="${METADATA_PATH}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_APP_CONFIG_PATH="${APP_CONFIG_PATH}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_MODE="${DEEPSTREAM_MODE}"

  log "configuring build dir ${BUILD_DIR}"
  "${cmake_bin}" -S "${ROOT_DIR}" -B "${BUILD_DIR}" \
    -G "${GENERATOR}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DROBOT_LIFE_CPP_ENABLE_CUDA=ON \
    -DROBOT_LIFE_CPP_REQUIRE_CUDA=ON \
    -DROBOT_LIFE_CPP_BUILD_TESTS="${BUILD_TESTS}"

  log "building"
  "${cmake_bin}" --build "${BUILD_DIR}" -j"$(getconf _NPROCESSORS_ONLN)"
}

ensure_built() {
  [[ -x "${BIN}" ]] || die "binary not found: ${BIN}; run build first"
}

run_live() {
  ensure_built
  local ds_dir
  ds_dir="${DEEPSTREAM_DIR:-$(detect_deepstream_dir)}"
  local ds_app
  ds_app="${DEEPSTREAM_APP:-$(detect_deepstream_app)}"
  [[ -n "${ds_dir}" ]] || die "DeepStream directory not found"
  [[ -x "${ds_app}" ]] || die "deepstream-app not found"

  export DEEPSTREAM_DIR="${ds_dir}"
  export DEEPSTREAM_APP="${ds_app}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_GRAPH_CONFIG="${GRAPH_CONFIG}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_METADATA_PATH="${METADATA_PATH}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_APP_CONFIG_PATH="${APP_CONFIG_PATH}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_MODE="${DEEPSTREAM_MODE}"

  mkdir -p "$(dirname "${METADATA_PATH}")" "$(dirname "${APP_CONFIG_PATH}")"
  : > "${METADATA_PATH}"

  maybe_enable_perf_mode
  start_tegrastats
  trap stop_tegrastats EXIT

  log "running profile=${PROFILE} mode=${DEEPSTREAM_MODE} ui=${RUN_UI} ticks=${RUN_TICKS}"
  "${BIN}" run-live \
    --profile "${PROFILE}" \
    --runtime-tuning "${RUNTIME_TUNING}" \
    --ticks "${RUN_TICKS}" \
    --reload-tuning true \
    --ui "${RUN_UI}"
}

run_smoke() {
  ensure_built
  local ds_app
  ds_app="${DEEPSTREAM_APP:-$(detect_deepstream_app)}"
  [[ -x "${ds_app}" ]] || die "deepstream-app not found"

  export DEEPSTREAM_APP="${ds_app}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_GRAPH_CONFIG="${GRAPH_CONFIG}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_METADATA_PATH="${METADATA_PATH}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_APP_CONFIG_PATH="${APP_CONFIG_PATH}"
  export ROBOT_LIFE_CPP_DEEPSTREAM_MODE=real

  log "deepstream backend real smoke"
  "${BIN}" deepstream-backend \
    --mode real \
    --frames 32 \
    --interval-ms 5 \
    --graph-config "${GRAPH_CONFIG}" \
    --metadata-path "${METADATA_PATH}" \
    --write-app-config "${APP_CONFIG_PATH}" \
    --deepstream-app "${DEEPSTREAM_APP}"
}

main() {
  local cmd="${1:-help}"
  case "${cmd}" in
    doctor)
      run_doctor
      ;;
    build)
      run_build
      ;;
    run)
      run_live
      ;;
    ui)
      RUN_UI=true
      run_live
      ;;
    smoke)
      run_smoke
      ;;
    help|-h|--help)
      usage
      ;;
    *)
      usage
      die "unknown command: ${cmd}"
      ;;
  esac
}

main "$@"
