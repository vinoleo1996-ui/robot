#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_BIN="${ROOT_DIR}/build/robot_life_cpp_main"
TMP_DIR="$(mktemp -d /tmp/robot_life_cpp_ds_smoke.XXXXXX)"
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

(
  sleep 0.05
  python3 - <<PY
from pathlib import Path
with Path("${METADATA_PATH}").open("a", encoding="utf-8") as fh:
    fh.write("DETECTION|smoke-trace|front_cam|deepstream_face|face_detected|1.5|0.91|camera_id=front_cam;frame_id=1;track_id=person_track_1;bbox=10,20,30,40\n")
PY
) &

"${BUILD_BIN}" deepstream-backend \
  --mode real \
  --deepstream-app /usr/bin/yes \
  --graph-config "${ROOT_DIR}/configs/deepstream_4vision.yaml" \
  --metadata-path "${METADATA_PATH}" \
  --write-app-config "${APP_CONFIG_PATH}" \
  --frames 12 \
  --interval-ms 10 > "${OUTPUT_PATH}"

grep -q '^HEALTH|ready|' "${OUTPUT_PATH}"
grep -q '^DETECTION|smoke-trace|' "${OUTPUT_PATH}"
[[ -s "${APP_CONFIG_PATH}" ]]

printf 'DEEPSTREAM_REAL_BRIDGE_SMOKE_PASS: %s\n' "${OUTPUT_PATH}"
