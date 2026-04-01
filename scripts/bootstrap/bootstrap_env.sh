#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-}"
PARSE_PYTHON="${PYTHON_BIN:-python3}"
REQUIRES_PYTHON="$("$PARSE_PYTHON" - <<'PY'
from pathlib import Path
import re

content = Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'requires-python\s*=\s*"\s*>=\s*([0-9]+)\.([0-9]+)', content)
if match is None:
    print("3 11")
else:
    print(match.group(1), match.group(2))
PY
)"
read -r REQUIRED_MAJOR REQUIRED_MINOR <<<"$REQUIRES_PYTHON"

resolve_python_bin() {
  if [[ -n "${PYTHON_BIN}" ]]; then
    echo "${PYTHON_BIN}"
    return 0
  fi

  local candidates=(
    "python${REQUIRED_MAJOR}.${REQUIRED_MINOR}"
    "python${REQUIRED_MAJOR}"
    "python3"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      if "${candidate}" - <<PY >/dev/null 2>&1
import sys
sys.exit(0 if sys.version_info >= (${REQUIRED_MAJOR}, ${REQUIRED_MINOR}) else 1)
PY
      then
        echo "${candidate}"
        return 0
      fi
    fi
  done

  if command -v uv >/dev/null 2>&1; then
    local uv_python
    uv_python="$(uv python find "${REQUIRED_MAJOR}.${REQUIRED_MINOR}" 2>/dev/null || true)"
    if [[ -n "${uv_python}" ]]; then
      echo "${uv_python}"
      return 0
    fi
  fi

  return 1
}

if ! PYTHON_BIN="$(resolve_python_bin)"; then
  echo "Error: Python ${REQUIRED_MAJOR}.${REQUIRED_MINOR} or higher is required by pyproject.toml."
  echo "Hint: install it first, e.g. 'uv python install ${REQUIRED_MAJOR}.${REQUIRED_MINOR}'."
  exit 1
fi

if ! "$PYTHON_BIN" - <<PY
import sys
sys.exit(0 if sys.version_info >= (${REQUIRED_MAJOR}, ${REQUIRED_MINOR}) else 1)
PY
then
  echo "Error: Python ${REQUIRED_MAJOR}.${REQUIRED_MINOR} or higher is required by pyproject.toml."
  exit 1
fi

if ! "$PYTHON_BIN" -m venv --clear .venv 2>/dev/null; then
  if "$PYTHON_BIN" -m virtualenv .venv 2>/dev/null; then
    :
  elif command -v uv >/dev/null 2>&1; then
    rm -rf .venv
    uv venv --clear --seed --python "$PYTHON_BIN" .venv
  else
    echo "Error: failed to create .venv with ${PYTHON_BIN}."
    echo "Hint: install virtualenv or uv, then retry."
    exit 1
  fi
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,mvp,audio]"

echo "Environment ready."
echo "Using Python: $PYTHON_BIN ($("$PYTHON_BIN" --version 2>/dev/null))"
echo "Activate with: source .venv/bin/activate"
