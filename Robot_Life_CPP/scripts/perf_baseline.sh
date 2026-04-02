#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build"
BIN="${BUILD_DIR}/robot_life_cpp_main"
OUT_DIR="${ROOT_DIR}/docs/perf"
BASELINE_JSON="${OUT_DIR}/latest_baseline.json"
BASELINE_TXT="${OUT_DIR}/latest_baseline.txt"
THRESHOLDS_JSON="${OUT_DIR}/baseline_thresholds.json"
MODE="record"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compare)
      MODE="compare"
      shift
      ;;
    --record)
      MODE="record"
      shift
      ;;
    --refresh-thresholds)
      MODE="refresh-thresholds"
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Usage:
  perf_baseline.sh [--record|--compare|--refresh-thresholds]

Modes:
  --record              Measure and write latest_baseline.json/txt
  --compare             Measure and compare against baseline_thresholds.json
  --refresh-thresholds   Measure and rewrite baseline_thresholds.json from current run
EOF
      exit 0
      ;;
    *)
      echo "unknown argument: $1"
      exit 2
      ;;
  esac
done

mkdir -p "${OUT_DIR}"

if [[ ! -x "${BIN}" ]]; then
  "${ROOT_DIR}/scripts/regression.sh" >/dev/null
fi

ROOT_DIR="${ROOT_DIR}" \
BIN="${BIN}" \
OUT_DIR="${OUT_DIR}" \
BASELINE_JSON="${BASELINE_JSON}" \
BASELINE_TXT="${BASELINE_TXT}" \
THRESHOLDS_JSON="${THRESHOLDS_JSON}" \
PERF_MODE="${MODE}" \
python3 - <<'PY'
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone

root = pathlib.Path(os.environ["ROOT_DIR"])
bin_path = pathlib.Path(os.environ["BIN"])
out_json = pathlib.Path(os.environ["BASELINE_JSON"])
out_txt = pathlib.Path(os.environ["BASELINE_TXT"])
thresholds_path = pathlib.Path(os.environ["THRESHOLDS_JSON"])
mode = os.environ["PERF_MODE"]


def run_case(name, argv):
    started = time.perf_counter()
    proc = subprocess.run(
        argv,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    ended = time.perf_counter()
    return {
        "name": name,
        "command": argv,
        "duration_ms": int(round((ended - started) * 1000)),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


cases = [
    ("doctor", [str(bin_path), "doctor"]),
    ("run_live_native", [str(bin_path), "run-live", "--profile", "mac_debug_native", "--ticks", "4", "--ui", "false"]),
    ("run_live_deepstream_mock", [str(bin_path), "run-live", "--profile", "linux_deepstream_4vision", "--ticks", "4", "--ui", "false"]),
]

results = [run_case(name, argv) for name, argv in cases]
payload = {
    "schema": "robot_life_cpp.perf_baseline.v1",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "root": str(root),
    "cases": results,
}
out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

txt_lines = [
    "# Performance Baseline",
    f"generated_at: {payload['generated_at']}",
    "",
]
for result in results:
    txt_lines.extend([
        f"## {result['name']}",
        f"duration_ms: {result['duration_ms']}",
        f"returncode: {result['returncode']}",
        "stdout:",
        result["stdout"].rstrip("\n"),
    ])
    if result["stderr"].strip():
        txt_lines.extend(["stderr:", result["stderr"].rstrip("\n")])
    txt_lines.append("")
out_txt.write_text("\n".join(txt_lines).rstrip() + "\n", encoding="utf-8")


def load_thresholds(path: pathlib.Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


if mode == "refresh-thresholds":
    thresholds = {
        "schema": "robot_life_cpp.perf_thresholds.v1",
        "generated_at": payload["generated_at"],
        "root": str(root),
        "cases": [
            {
                "name": result["name"],
                "reference_duration_ms": result["duration_ms"],
                "max_duration_ms": max(100, result["duration_ms"] * 3),
                "max_regression_pct": 2.5,
            }
            for result in results
        ],
    }
    thresholds_path.write_text(json.dumps(thresholds, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"thresholds written: {thresholds_path}")
    sys.exit(0)

if mode == "compare":
    thresholds = load_thresholds(thresholds_path)
    if thresholds is None:
        print(f"missing thresholds file: {thresholds_path}", file=sys.stderr)
        sys.exit(1)
    threshold_map = {item["name"]: item for item in thresholds.get("cases", [])}
    failures = []
    for result in results:
        threshold = threshold_map.get(result["name"])
        if threshold is None:
            failures.append(f"no threshold for case: {result['name']}")
            continue
        if result["returncode"] != 0:
            failures.append(f"{result['name']}: returncode {result['returncode']}")
        allowed_by_ratio = int(round(threshold["reference_duration_ms"] * threshold.get("max_regression_pct", 1.0)))
        allowed = min(int(threshold["max_duration_ms"]), max(allowed_by_ratio, 1))
        if result["duration_ms"] > allowed:
            failures.append(
                f"{result['name']}: duration {result['duration_ms']}ms > allowed {allowed}ms "
                f"(reference={threshold['reference_duration_ms']}ms, max={threshold['max_duration_ms']}ms, "
                f"ratio={threshold.get('max_regression_pct', 1.0)})"
            )
    if failures:
        print("PERF_COMPARE_FAIL")
        for line in failures:
            print(f"- {line}")
        sys.exit(1)
    print(f"PERF_COMPARE_PASS: {thresholds_path}")

print(f"baseline written: {out_json}")
PY
