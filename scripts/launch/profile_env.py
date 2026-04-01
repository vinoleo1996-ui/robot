#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from robot_life.profiles import get_profile_spec


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit shell-friendly profile env values.")
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()

    spec = get_profile_spec(args.profile)
    print(f"PROFILE_KEY={spec.key}")
    print(f"RUNTIME_CONFIG={spec.runtime_config}")
    print(f"DETECTOR_CONFIG={spec.detector_config}")
    print(f"STABILIZER_CONFIG={spec.stabilizer_config or ''}")
    print(f"ARBITRATION_CONFIG={spec.arbitration_config or ''}")
    print(f"SAFETY_CONFIG={spec.safety_config or ''}")
    print(f"REQUIRED_PIPELINES={','.join(spec.required_pipelines)}")
    print(f"CAMERA_TIMEOUT_MS={spec.default_camera_timeout_ms}")
    print(f"REFRESH_MS={spec.default_refresh_ms}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
