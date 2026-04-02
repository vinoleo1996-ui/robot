#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_BIN="${ROOT_DIR}/build/robot_life_cpp_main"
TMP_DIR="$(mktemp -d /tmp/robot_life_cpp_ds_fail.XXXXXX)"
METADATA_PATH="${TMP_DIR}/metadata.ndjson"
APP_CONFIG_PATH="${TMP_DIR}/deepstream_app.txt"
OUTPUT_PATH="${TMP_DIR}/output.log"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

python3 - <<PY
from pathlib import Path
Path("${METADATA_PATH}").write_text("", encoding="utf-8")
PY

set +e
"${BUILD_BIN}" deepstream-backend \
  --mode real \
  --deepstream-app /usr/bin/false \
  --graph-config "${ROOT_DIR}/configs/deepstream_4vision.yaml" \
  --metadata-path "${METADATA_PATH}" \
  --write-app-config "${APP_CONFIG_PATH}" \
  --frames 12 \
  --interval-ms 10 > "${OUTPUT_PATH}"
rc=$?
set -e

if [[ "${rc}" -ne 5 ]]; then
  printf 'unexpected exit code: %s\n' "${rc}" >&2
  cat "${OUTPUT_PATH}" >&2
  exit 1
fi

grep -q '^HEALTH|failed|' "${OUTPUT_PATH}"
grep -q 'before metadata ready' "${OUTPUT_PATH}"
grep -q '^HEALTH|stopping|deepstream-app exited with code 1$' "${OUTPUT_PATH}"
[[ -s "${APP_CONFIG_PATH}" ]]

printf 'DEEPSTREAM_REAL_BRIDGE_FAILURE_SMOKE_PASS: %s\n' "${OUTPUT_PATH}"
