#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${PROJECT_DIR}/logs"
LOG_FILE="${LOG_DIR}/ui_demo_stable.log"
PID_FILE="${LOG_DIR}/ui_demo_stable.pid"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8765}"
CAMERA_DEVICE="${CAMERA_DEVICE:-0}"
CAMERA_TIMEOUT_MS="${CAMERA_TIMEOUT_MS:-200}"
REFRESH_MS="${REFRESH_MS:-400}"
RUNTIME_CONFIG="${RUNTIME_CONFIG:-${PROJECT_DIR}/configs/runtime/desktop_4090/desktop_4090_gpu_stable.yaml}"
DETECTOR_CONFIG="${DETECTOR_CONFIG:-${PROJECT_DIR}/configs/detectors/desktop_4090/desktop_4090_stable.yaml}"
STABILIZER_CONFIG="${STABILIZER_CONFIG:-${PROJECT_DIR}/configs/stabilizer/desktop_4090_stable.yaml}"
SLOW_SCENE_CONFIG="${SLOW_SCENE_CONFIG:-${PROJECT_DIR}/configs/slow_scene/local_qwen35_4b_stable.yaml}"

if [[ -x "${PROJECT_DIR}/.venv/bin/python3" ]]; then
  PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python3"
else
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export PYTHONUNBUFFERED=1

CUDA_LIB_PATHS="$("${PYTHON_BIN}" - <<'PY'
import sys
from pathlib import Path
paths = []
seen = set()
for entry in sys.path:
    if not entry:
        continue
    root = Path(entry).expanduser() / "nvidia"
    if not root.is_dir():
        continue
    for lib_dir in sorted(root.glob("*/lib")):
        value = str(lib_dir.resolve())
        if value not in seen:
            seen.add(value)
            paths.append(value)
print(":".join(paths))
PY
)"
if [[ -n "${CUDA_LIB_PATHS}" ]]; then
  export LD_LIBRARY_PATH="${CUDA_LIB_PATHS}:${LD_LIBRARY_PATH:-}"
fi

mkdir -p "${LOG_DIR}"

is_running() {
  if [[ ! -f "${PID_FILE}" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  [[ -n "${pid}" ]] || return 1
  ps -p "${pid}" >/dev/null 2>&1 || return 1
  local stat
  stat="$(ps -o stat= -p "${pid}" 2>/dev/null | tr -d '[:space:]' || true)"
  [[ -n "${stat}" ]] || return 1
  [[ "${stat}" != *Z* ]]
}

health_ok() {
  NO_PROXY="127.0.0.1,localhost" curl -fsS --max-time 1 "http://${HOST}:${PORT}/api/state" >/dev/null 2>&1
}

start() {
  if is_running; then
    echo "ui-demo already running: pid=$(cat "${PID_FILE}")"
    status
    return 0
  fi

  : > "${LOG_FILE}"
  setsid "${PYTHON_BIN}" -u -m robot_life.app ui-demo \
    --config "${RUNTIME_CONFIG}" \
    --detectors "${DETECTOR_CONFIG}" \
    --stabilizer-config "${STABILIZER_CONFIG}" \
    --slow-scene-config "${SLOW_SCENE_CONFIG}" \
    --camera-device "${CAMERA_DEVICE}" \
    --camera-read-timeout-ms "${CAMERA_TIMEOUT_MS}" \
    --enable-slow-scene \
    --host "${HOST}" \
    --port "${PORT}" \
    --refresh-ms "${REFRESH_MS}" \
    </dev/null >> "${LOG_FILE}" 2>&1 &
  echo $! > "${PID_FILE}"
  local max_wait_s=20
  local waited=0
  while (( waited < max_wait_s )); do
    if ! is_running; then
      break
    fi
    if health_ok; then
      echo "started ui-demo stable: pid=$(cat "${PID_FILE}") url=http://${HOST}:${PORT}"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done

  if is_running; then
    kill "$(cat "${PID_FILE}")" >/dev/null 2>&1 || true
    sleep 1
  fi
  rm -f "${PID_FILE}"

  echo "failed to start ui-demo stable. recent logs:"
  tail -n 80 "${LOG_FILE}" || true
  return 1
}

stop() {
  if ! is_running; then
    echo "ui-demo stable is not running"
    rm -f "${PID_FILE}"
    return 0
  fi

  local pid
  pid="$(cat "${PID_FILE}")"
  kill "${pid}" >/dev/null 2>&1 || true
  sleep 1
  if ps -p "${pid}" >/dev/null 2>&1; then
    kill -9 "${pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${PID_FILE}"
  echo "stopped ui-demo stable: pid=${pid}"
}

status() {
  if ! is_running; then
    rm -f "${PID_FILE}"
    echo "ui-demo stable status: stopped"
    return 1
  fi

  local pid
  pid="$(cat "${PID_FILE}")"
  echo "ui-demo stable status: running pid=${pid}"
  ps -o pid,ppid,stat,%cpu,%mem,etime,cmd -p "${pid}" || true
  if ! health_ok; then
    echo "health: unavailable"
    return 0
  fi

  local state_json
  state_json="$(NO_PROXY="127.0.0.1,localhost" curl -sS --max-time 2 "http://${HOST}:${PORT}/api/state" || true)"
  if [[ -z "${state_json}" ]]; then
    echo "health: unavailable"
    return 0
  fi

  python3 - "${state_json}" <<'PY'
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
    f"loop_fps={s.get('loop_fps')}",
    f"latency_ms={s.get('last_latency_ms')}",
    f"queue_pending={s.get('queue_pending')}",
    f"slow_queue={s.get('slow_queue_depth')}",
    f"slow_timeout={s.get('slow_timed_out')}",
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
  RUNTIME_CONFIG=/abs/path/runtime.yaml DETECTOR_CONFIG=/abs/path/detectors.yaml scripts/launch/run_ui_stable.sh start
  scripts/launch/run_ui_stable.sh start
  scripts/launch/run_ui_stable.sh stop
  scripts/launch/run_ui_stable.sh restart
  scripts/launch/run_ui_stable.sh status
  scripts/launch/run_ui_stable.sh logs [N]
  scripts/launch/run_ui_stable.sh follow
EOF
}

cmd="${1:-status}"
case "${cmd}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  logs) logs "${2:-120}" ;;
  follow) follow ;;
  *) usage; exit 1 ;;
esac
