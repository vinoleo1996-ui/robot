#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ROOT_DIR}/build/robot_life_cpp_main"

if [[ ! -x "${BIN}" ]]; then
  echo "robot_life_cpp_main not built: ${BIN}"
  exit 1
fi

TMP_DIR="$(mktemp -d /tmp/robot_life_cpp_ui_smoke.XXXXXX)"
HTML_PATH="${TMP_DIR}/dashboard.html"
JSON_PATH="${TMP_DIR}/dashboard.json"
LOG_PATH="${TMP_DIR}/ui.log"

"${BIN}" ui-demo \
  --profile mac_debug_native \
  --ticks 2 \
  --ui-html-out "${HTML_PATH}" \
  --ui-json-out "${JSON_PATH}" > "${LOG_PATH}"

[[ -f "${HTML_PATH}" ]]
[[ -f "${JSON_PATH}" ]]
grep -q "Robot Life Debug UI" "${HTML_PATH}"
grep -q "\"load_shed\"" "${JSON_PATH}"

echo "UI_DASHBOARD_SMOKE_PASS: ${TMP_DIR}"
