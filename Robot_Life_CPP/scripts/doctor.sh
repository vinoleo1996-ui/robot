#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

failures=0

check() {
  local ok="$1"
  local name="$2"
  local detail="$3"
  if [[ "$ok" == "1" ]]; then
    printf '  [ok] %s: %s\n' "$name" "$detail"
  else
    printf '  [fail] %s: %s\n' "$name" "$detail"
    failures=$((failures + 1))
  fi
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

host_platform="$(uname -s | tr '[:upper:]' '[:lower:]')"
printf 'Robot Life C++ Doctor Script\n'
printf '  root: %s\n' "$ROOT_DIR"
printf '  platform: %s\n' "$host_platform"

check "$(command_exists python3 && echo 1 || echo 0)" "python3" "required"
check "$(command_exists cmake && echo 1 || echo 0)" "cmake" "required"
check "$(command_exists c++ && echo 1 || echo 0)" "c++" "required"
check "$(command_exists ninja && echo 1 || echo 0)" "ninja" "recommended"

for path in \
  "$ROOT_DIR/configs/app.yaml" \
  "$ROOT_DIR/configs/detectors.yaml" \
  "$ROOT_DIR/configs/slow_scene.yaml" \
  "$ROOT_DIR/configs/stabilizer.yaml" \
  "$ROOT_DIR/configs/runtime_tuning.yaml" \
  "$ROOT_DIR/configs/deepstream_4vision.yaml" \
  "$ROOT_DIR/configs/profile_catalog.yaml"
do
  check "$([[ -f "$path" ]] && echo 1 || echo 0)" "file" "$path"
done

for dir in \
  "$ROOT_DIR/models" \
  "$ROOT_DIR/models/native" \
  "$ROOT_DIR/models/deepstream"
do
  if [[ -d "$dir" ]]; then
    check 1 "directory" "$dir"
  else
    mkdir -p "$dir"
    check 1 "directory" "$dir (created)"
  fi
done

catalog="$ROOT_DIR/configs/profile_catalog.yaml"
for profile in mac_debug_native linux_deepstream_4vision linux_cpu_fallback_safe; do
  if grep -q "^  ${profile}:" "$catalog"; then
    check 1 "profile" "$profile"
  else
    check 0 "profile" "$profile"
  fi
done

if grep -q "^default_profile: mac_debug_native$" "$catalog"; then
  check 1 "default_profile" "mac_debug_native"
else
  check 0 "default_profile" "expected mac_debug_native"
fi

if [[ "$host_platform" == "linux" ]]; then
  check "$([[ -n "${DEEPSTREAM_DIR:-}" || -d /opt/nvidia/deepstream/deepstream ]] && echo 1 || echo 0)" \
    "deepstream_runtime_hint" \
    "${DEEPSTREAM_DIR:-/opt/nvidia/deepstream/deepstream}"
  deepstream_app="${DEEPSTREAM_APP:-}"
  if [[ -z "$deepstream_app" ]]; then
    if command_exists deepstream-app; then
      deepstream_app="$(command -v deepstream-app)"
    else
      deepstream_app="/opt/nvidia/deepstream/deepstream/bin/deepstream-app"
    fi
  fi
  check "$([[ -x "$deepstream_app" ]] && echo 1 || echo 0)" "deepstream_app" "$deepstream_app"
  deepstream_metadata_path="${ROBOT_LIFE_CPP_DEEPSTREAM_METADATA_PATH:-/tmp/robot_life_cpp_deepstream_metadata.ndjson}"
  check "$([[ -d "$(dirname "$deepstream_metadata_path")" ]] && echo 1 || echo 0)" \
    "deepstream_metadata_bridge" \
    "$deepstream_metadata_path"
else
  check 1 "deepstream_runtime_hint" "non-linux host uses native development profile"
  check 1 "deepstream_app" "non-linux host uses native development profile"
  check 1 "deepstream_metadata_bridge" "non-linux host uses native development profile"
fi

if [[ -x "$ROOT_DIR/build/robot_life_cpp_main" ]]; then
  if "$ROOT_DIR/build/robot_life_cpp_main" doctor; then
    check 1 "compiled_doctor" "$ROOT_DIR/build/robot_life_cpp_main doctor"
  else
    check 0 "compiled_doctor" "$ROOT_DIR/build/robot_life_cpp_main doctor"
  fi
else
  check 1 "compiled_doctor" "build/robot_life_cpp_main not present yet"
fi

if [[ "$failures" -gt 0 ]]; then
  printf 'Doctor result: FAIL (%s issues)\n' "$failures"
  exit 1
fi

printf 'Doctor result: PASS\n'
