#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/ui_demo_local_fast_reaction.log"
PID_FILE="${LOG_DIR}/ui_demo_local_fast_reaction.pid"
CACHE_DIR="${PROJECT_DIR}/.cache/matplotlib"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8766}"
CAMERA_DEVICE="${CAMERA_DEVICE:-0}"
MICROPHONE_DEVICE="${MICROPHONE_DEVICE:-auto}"
CAMERA_TIMEOUT_MS="${CAMERA_TIMEOUT_MS:-}"
REFRESH_MS="${REFRESH_MS:-}"
STARTUP_STABILITY_WAIT_S="${STARTUP_STABILITY_WAIT_S:-3}"
STARTUP_MAX_WAIT_S="${STARTUP_MAX_WAIT_S:-20}"
STARTUP_INITIALIZING_GRACE_S="${STARTUP_INITIALIZING_GRACE_S:-45}"
STARTUP_HEALTH_MAX_TIME_S="${STARTUP_HEALTH_MAX_TIME_S:-3}"
STARTUP_INITIALIZING_MAX_TIME_S="${STARTUP_INITIALIZING_MAX_TIME_S:-10}"
RUNTIME_CONFIG="${RUNTIME_CONFIG:-}"
DETECTOR_CONFIG="${DETECTOR_CONFIG:-}"
STABILIZER_CONFIG="${STABILIZER_CONFIG:-}"
ARBITRATION_CONFIG="${ARBITRATION_CONFIG:-}"
SAFETY_CONFIG="${SAFETY_CONFIG:-}"
PRECHECK_SCRIPT="${PROJECT_DIR}/scripts/validate/preflight_local_fast_reaction.py"
PROFILE_ENV_SCRIPT="${PROJECT_DIR}/scripts/launch/profile_env.py"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
MOCK_RUNTIME_CONFIG="${MOCK_RUNTIME_CONFIG:-${PROJECT_DIR}/configs/runtime/app.default.yaml}"
PROFILE_KEY=""

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "error: expected virtualenv python at ${PYTHON_BIN}"
  echo "hint: run scripts/bootstrap/bootstrap_env.sh first"
  exit 1
fi

export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export PYTHONUNBUFFERED=1
export MPLCONFIGDIR="${MPLCONFIGDIR:-${CACHE_DIR}}"
if [[ -n "${MICROPHONE_DEVICE}" && "${MICROPHONE_DEVICE}" != "auto" ]]; then
  export ROBOT_LIFE_MIC_DEVICE="${MICROPHONE_DEVICE}"
else
  unset ROBOT_LIFE_MIC_DEVICE || true
fi

mkdir -p "${LOG_DIR}"
mkdir -p "${CACHE_DIR}"

load_profile_spec() {
  local profile_mode="${1:-full}"
  local resolved_runtime=""
  local resolved_detector=""
  local resolved_stabilizer=""
  local resolved_arbitration=""
  local resolved_safety=""
  local resolved_camera_timeout=""
  local resolved_refresh=""
  local resolved_key=""

  while IFS='=' read -r key value; do
    case "${key}" in
      PROFILE_KEY) resolved_key="${value}" ;;
      RUNTIME_CONFIG) resolved_runtime="${value}" ;;
      DETECTOR_CONFIG) resolved_detector="${value}" ;;
      STABILIZER_CONFIG) resolved_stabilizer="${value}" ;;
      ARBITRATION_CONFIG) resolved_arbitration="${value}" ;;
      SAFETY_CONFIG) resolved_safety="${value}" ;;
      CAMERA_TIMEOUT_MS) resolved_camera_timeout="${value}" ;;
      REFRESH_MS) resolved_refresh="${value}" ;;
    esac
  done < <("${PYTHON_BIN}" "${PROFILE_ENV_SCRIPT}" --profile "${profile_mode}")

  PROFILE_KEY="${resolved_key}"
  RUNTIME_CONFIG="${RUNTIME_CONFIG:-${resolved_runtime}}"
  DETECTOR_CONFIG="${DETECTOR_CONFIG:-${resolved_detector}}"
  STABILIZER_CONFIG="${STABILIZER_CONFIG:-${resolved_stabilizer}}"
  ARBITRATION_CONFIG="${ARBITRATION_CONFIG:-${resolved_arbitration}}"
  SAFETY_CONFIG="${SAFETY_CONFIG:-${resolved_safety}}"
  CAMERA_TIMEOUT_MS="${CAMERA_TIMEOUT_MS:-${resolved_camera_timeout}}"
  REFRESH_MS="${REFRESH_MS:-${resolved_refresh}}"
}

is_running() {
  local pid
  pid="$(find_running_pid 2>/dev/null || true)"
  [[ -n "${pid}" ]]
}

find_running_pid() {
  local pid=""
  if [[ -f "${PID_FILE}" ]]; then
    pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  fi
  if [[ -n "${pid}" ]] && ps -p "${pid}" >/dev/null 2>&1; then
    local stat
    stat="$(ps -o stat= -p "${pid}" 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ -n "${stat}" && "${stat}" != *Z* ]]; then
      echo "${pid}"
      return 0
    fi
  fi
  pid="$(
    ps ax -o pid= -o command= 2>/dev/null \
      | awk -v host="${HOST}" -v port="${PORT}" '
        index($0, "robot_life.app ui-demo") && index($0, "--host " host) && index($0, "--port " port) {
          print $1
          exit
        }
      ' \
      || true
  )"
  [[ -n "${pid}" ]] || return 1
  local stat
  stat="$(ps -o stat= -p "${pid}" 2>/dev/null | tr -d '[:space:]' || true)"
  [[ -n "${stat}" && "${stat}" != *Z* ]] || return 1
  printf '%s\n' "${pid}" > "${PID_FILE}"
  echo "${pid}"
}

health_fetch() {
  local max_time="${1:-3}"
  NO_PROXY="127.0.0.1,localhost" curl -fsS --max-time "${max_time}" "http://${HOST}:${PORT}/api/state"
}

health_ok() {
  health_fetch "${1:-3}" >/dev/null 2>&1
}

health_startup_state() {
  local state_json="${1:-}"
  "${PYTHON_BIN}" - "${state_json}" <<'PY'
import json
import sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    print("unavailable")
    raise SystemExit(0)
value = str(payload.get("startup_state") or "running").strip().lower() or "running"
print(value)
PY
}

preflight() {
  "${PYTHON_BIN}" "${PRECHECK_SCRIPT}" \
    --runtime-config "${RUNTIME_CONFIG}" \
    --detector-config "${DETECTOR_CONFIG}" \
    --arbitration-config "${ARBITRATION_CONFIG}" \
    --stabilizer-config "${STABILIZER_CONFIG}" \
    --safety-config "${SAFETY_CONFIG}" \
    --camera-device-index "${CAMERA_DEVICE}"
}

start() {
  local skip_preflight="${1:-0}"
  local mock_if_unavailable="${2:-0}"
  local ci_mock="${3:-0}"
  local profile_mode="${4:-full}"
  local foreground="${5:-0}"
  if is_running; then
    local running_pid
    running_pid="$(find_running_pid)"
    local running_cmd=""
    running_cmd="$(ps -o command= -p "${running_pid}" 2>/dev/null || true)"
    local expected_detector="${DETECTOR_CONFIG}"
    if [[ -n "${running_cmd}" && "${running_cmd}" == *"--detectors ${expected_detector}"* ]]; then
      echo "ui-demo local fast-reaction already running: pid=${running_pid}"
      status
      return 0
    fi
    echo "ui-demo local fast-reaction is running with another profile; restarting..."
    stop
  fi

  local start_mode="real"
  local launch_camera_device="${CAMERA_DEVICE}"
  if [[ "${ci_mock}" == "1" ]]; then
    echo "ci-mock mode enabled; skipping hardware preflight and forcing mock runtime."
    start_mode="mock"
  fi
  if [[ "${skip_preflight}" != "1" && "${ci_mock}" != "1" ]]; then
    local preflight_output=""
    local preflight_rc=0
    set +e
    preflight_output="$(preflight 2>&1)"
    preflight_rc=$?
    set -e
    [[ -n "${preflight_output}" ]] && printf '%s\n' "${preflight_output}"
    if [[ "${preflight_rc}" -ne 0 ]]; then
      if [[ "${mock_if_unavailable}" == "1" ]]; then
        echo "real-device preflight failed; switching to mock fallback for UI experience."
        start_mode="mock"
      else
      echo "real-device preflight failed."
        echo "hint: rerun with './scripts/launch/run_ui_local_fast_reaction.sh start --mock-if-unavailable' to体验 UI 和仲裁链路。"
        echo "hint: rerun with './scripts/launch/run_ui_local_fast_reaction.sh start --skip-preflight' only when you are debugging startup details."
        return "${preflight_rc}"
      fi
    else
      local resolved_camera=""
      resolved_camera="$(printf '%s\n' "${preflight_output}" | awk -F= '/^camera_device_actual=/{print $2; exit}')"
      if [[ "${resolved_camera}" =~ ^[0-9]+$ ]]; then
        launch_camera_device="${resolved_camera}"
        if [[ "${launch_camera_device}" != "${CAMERA_DEVICE}" ]]; then
          echo "preflight resolved camera_device=${launch_camera_device} (requested=${CAMERA_DEVICE})"
        fi
      fi
    fi
  elif [[ "${ci_mock}" != "1" ]]; then
    echo "warning: preflight skipped by --skip-preflight"
  fi

  : > "${LOG_FILE}"
  local runtime_config="${RUNTIME_CONFIG}"
  local real_args=(--real)
  if [[ "${start_mode}" == "mock" ]]; then
    runtime_config="${MOCK_RUNTIME_CONFIG}"
    real_args=()
  fi
  local launch_cmd=(
    "${PYTHON_BIN}" -u -m robot_life.app ui-demo
    --config "${runtime_config}"
    --detectors "${DETECTOR_CONFIG}"
    --arbitration-config "${ARBITRATION_CONFIG}"
    --stabilizer-config "${STABILIZER_CONFIG}"
    --safety-config "${SAFETY_CONFIG}"
    --camera-device "${launch_camera_device}"
    --camera-read-timeout-ms "${CAMERA_TIMEOUT_MS}"
    --host "${HOST}"
    --port "${PORT}"
    --refresh-ms "${REFRESH_MS}"
  )
  if [[ ${#real_args[@]} -gt 0 ]]; then
    launch_cmd+=("${real_args[@]}")
  fi
  if [[ "${foreground}" == "1" && "${ci_mock}" != "1" && "${start_mode}" == "real" ]]; then
    rm -f "${PID_FILE}"
    echo "starting ui-demo local fast-reaction in foreground: url=http://${HOST}:${PORT} profile=${PROFILE_KEY:-${profile_mode}} camera=${launch_camera_device} mic=${MICROPHONE_DEVICE}"
    "${launch_cmd[@]}"
    return $?
  fi
  rm -f "${PID_FILE}"
  local wrapper_cmd=(
    /bin/sh -c 'echo $$ > "$1"; shift; exec "$@"' sh "${PID_FILE}" "${launch_cmd[@]}"
  )
  if command -v setsid >/dev/null 2>&1; then
    setsid "${wrapper_cmd[@]}" </dev/null >> "${LOG_FILE}" 2>&1 &
  else
    nohup "${wrapper_cmd[@]}" </dev/null >> "${LOG_FILE}" 2>&1 &
  fi

  local max_wait_s="${STARTUP_MAX_WAIT_S}"
  local startup_grace_s="${STARTUP_INITIALIZING_GRACE_S}"
  local hard_wait_s=$(( max_wait_s > startup_grace_s ? max_wait_s : startup_grace_s ))
  local waited=0
  while (( waited < hard_wait_s )); do
    if ! is_running; then
      break
    fi
    local health_timeout="${STARTUP_HEALTH_MAX_TIME_S}"
    local state_json=""
    state_json="$(health_fetch "${health_timeout}" 2>/dev/null || true)"
    local startup_state="unavailable"
    if [[ -n "${state_json}" ]]; then
      startup_state="$(health_startup_state "${state_json}")"
      if [[ "${startup_state}" == "booting" || "${startup_state}" == "initializing" ]]; then
        health_timeout="${STARTUP_INITIALIZING_MAX_TIME_S}"
      fi
    fi
    if [[ -z "${state_json}" && (( waited < startup_grace_s )) ]]; then
      sleep 1
      waited=$((waited + 1))
      continue
    fi
    if [[ -n "${state_json}" && "${startup_state}" != "failed" && "${startup_state}" != "unavailable" ]]; then
      if [[ "${startup_state}" != "running" ]]; then
        sleep 1
        waited=$((waited + 1))
        continue
      fi
      local stable_elapsed=0
      while (( stable_elapsed < STARTUP_STABILITY_WAIT_S )); do
        sleep 1
        waited=$((waited + 1))
        if ! is_running; then
          break
        fi
        if ! health_ok "${STARTUP_HEALTH_MAX_TIME_S}"; then
          break
        fi
        stable_elapsed=$((stable_elapsed + 1))
      done
      if is_running && (( stable_elapsed >= STARTUP_STABILITY_WAIT_S )); then
        echo "started ui-demo local fast-reaction: pid=$(cat "${PID_FILE}") url=http://${HOST}:${PORT} mode=${start_mode} profile=${PROFILE_KEY:-${profile_mode}} camera=${launch_camera_device} mic=${MICROPHONE_DEVICE}"
        return 0
      fi
      if ! is_running; then
        echo "ui-demo local fast-reaction started but exited during warmup (${STARTUP_STABILITY_WAIT_S}s)"
        break
      fi
    fi
    sleep 1
    waited=$((waited + 1))
  done

  if is_running; then
    local running_pid
    running_pid="$(find_running_pid)"
    echo "started ui-demo local fast-reaction but health endpoint is still warming up: pid=${running_pid} url=http://${HOST}:${PORT}"
    echo "hint: use 'scripts/launch/run_ui_local_fast_reaction.sh status' or open the page directly and wait a few more seconds."
    return 0
  fi
  rm -f "${PID_FILE}"
  echo "failed to start ui-demo local fast-reaction. recent logs:"
  tail -n 80 "${LOG_FILE}" || true
  if grep -qi "not authorized to capture video" "${LOG_FILE}" 2>/dev/null; then
    echo "hint: macOS 相机权限还没有给当前终端。请去“系统设置 -> 隐私与安全性 -> 相机”授权后重试。"
  fi
  if [[ "${profile_mode}" == "full-gpu" ]]; then
    echo "hint: full-gpu 在部分 Apple Silicon 环境可能启动后快速退出。建议先用 '--realtime' 验证 5 路链路稳定性。"
  fi
  if [[ "${start_mode}" == "real" ]]; then
    echo "hint: 你也可以先执行 './scripts/launch/run_ui_local_fast_reaction.sh start --mock-if-unavailable' 体验 UI 和仲裁链路。"
  fi
  return 1
}

stop() {
  if ! is_running; then
    echo "ui-demo local fast-reaction is not running"
    rm -f "${PID_FILE}"
    return 0
  fi
  local pid
  pid="$(find_running_pid)"
  kill "${pid}" >/dev/null 2>&1 || true
  local waited=0
  while (( waited < 5 )) && ps -p "${pid}" >/dev/null 2>&1; do
    sleep 1
    waited=$((waited + 1))
  done
  if ps -p "${pid}" >/dev/null 2>&1; then
    kill -9 "${pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${PID_FILE}"
  echo "stopped ui-demo local fast-reaction: pid=${pid}"
}

status() {
  if ! is_running; then
    rm -f "${PID_FILE}"
    echo "ui-demo local fast-reaction status: stopped"
    return 1
  fi

  local pid
  pid="$(find_running_pid)"
  echo "ui-demo local fast-reaction status: running pid=${pid}"
  ps -o pid,ppid,stat,%cpu,%mem,etime,command -p "${pid}" || true
  if ! health_ok 3; then
    echo "health: unavailable"
    return 0
  fi

  local state_json
  state_json="$(health_fetch 3 || true)"
  if [[ -z "${state_json}" ]]; then
    echo "health: unavailable"
    return 0
  fi

  "${PYTHON_BIN}" - "${state_json}" <<'PY'
import json
import sys
try:
    s = json.loads(sys.argv[1])
except Exception:
    print("health: unavailable")
    raise SystemExit(0)
print(
    "health:",
    f"mode={s.get('mode')}",
    f"startup_state={s.get('startup_state')}",
    f"loop_fps={s.get('loop_fps')}",
    f"latency_ms={s.get('last_latency_ms')}",
    f"queue_pending={s.get('queue_pending')}",
    f"preemptions={s.get('preemptions')}",
)
PY
}

logs() {
  tail -n "${1:-120}" "${LOG_FILE}"
}

follow() {
  tail -f "${LOG_FILE}"
}

usage() {
  cat <<'EOF'
Usage:
  scripts/launch/run_ui_local_fast_reaction.sh preflight [--hybrid]
  scripts/launch/run_ui_local_fast_reaction.sh preflight [--lite]
  scripts/launch/run_ui_local_fast_reaction.sh preflight [--full-gpu]
  scripts/launch/run_ui_local_fast_reaction.sh preflight [--realtime]
  scripts/launch/run_ui_local_fast_reaction.sh start [--foreground] [--skip-preflight] [--mock-if-unavailable] [--ci-mock] [--hybrid]
  scripts/launch/run_ui_local_fast_reaction.sh start [--foreground] [--skip-preflight] [--mock-if-unavailable] [--ci-mock] [--lite]
  scripts/launch/run_ui_local_fast_reaction.sh start [--foreground] [--skip-preflight] [--mock-if-unavailable] [--ci-mock] [--full-gpu]
  scripts/launch/run_ui_local_fast_reaction.sh start [--foreground] [--skip-preflight] [--mock-if-unavailable] [--ci-mock] [--realtime]
  scripts/launch/run_ui_local_fast_reaction.sh stop
  scripts/launch/run_ui_local_fast_reaction.sh restart [--foreground] [--skip-preflight] [--mock-if-unavailable] [--ci-mock] [--hybrid]
  scripts/launch/run_ui_local_fast_reaction.sh restart [--foreground] [--skip-preflight] [--mock-if-unavailable] [--ci-mock] [--lite]
  scripts/launch/run_ui_local_fast_reaction.sh restart [--foreground] [--skip-preflight] [--mock-if-unavailable] [--ci-mock] [--full-gpu]
  scripts/launch/run_ui_local_fast_reaction.sh restart [--foreground] [--skip-preflight] [--mock-if-unavailable] [--ci-mock] [--realtime]
  scripts/launch/run_ui_local_fast_reaction.sh status
  scripts/launch/run_ui_local_fast_reaction.sh logs [N]
  scripts/launch/run_ui_local_fast_reaction.sh follow
EOF
}

cmd="${1:-status}"
shift || true
skip_preflight=0
mock_if_unavailable=0
ci_mock=0
foreground=0
profile_mode="full"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-preflight)
      skip_preflight=1
      ;;
    --mock-if-unavailable)
      mock_if_unavailable=1
      ;;
    --ci-mock)
      ci_mock=1
      ;;
    --foreground)
      foreground=1
      ;;
    --lite)
      profile_mode="lite"
      ;;
    --hybrid)
      profile_mode="hybrid"
      ;;
    --full-gpu)
      profile_mode="full-gpu"
      ;;
    --realtime)
      profile_mode="realtime"
      ;;
    *)
      if [[ "${cmd}" == "logs" ]]; then
        break
      fi
      echo "unknown option: $1"
      usage
      exit 1
      ;;
  esac
  shift
done

load_profile_spec "${profile_mode}"
case "${cmd}" in
  preflight) preflight ;;
  start) start "${skip_preflight}" "${mock_if_unavailable}" "${ci_mock}" "${profile_mode}" "${foreground}" ;;
  stop) stop ;;
  restart) stop; start "${skip_preflight}" "${mock_if_unavailable}" "${ci_mock}" "${profile_mode}" "${foreground}" ;;
  status) status ;;
  logs) logs "${1:-120}" ;;
  follow) follow ;;
  *) usage; exit 1 ;;
esac
