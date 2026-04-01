#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from robot_life.runtime import probe_live_microphone_source
from robot_life.runtime import load_detector_config, microphone_source_options_from_detector_cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate microphone availability and fallback mode.")
    parser.add_argument(
        "--detectors",
        type=Path,
        default=PROJECT_ROOT / "configs" / "detectors" / "local" / "local_mac_fast_reaction.yaml",
    )
    parser.add_argument(
        "--require-real",
        action="store_true",
        help="Exit with failure unless a real microphone backend is selected.",
    )
    args = parser.parse_args()

    detector_cfg = load_detector_config(args.detectors)
    probe = probe_live_microphone_source(**microphone_source_options_from_detector_cfg(detector_cfg))
    print("=== Microphone Validation Summary ===")
    print(f"mode={probe.mode}")
    print(f"backend={probe.backend}")
    print(f"input_device_count={probe.input_device_count}")
    print(f"default_input_index={probe.default_input_index}")
    print(f"selected_device={probe.selected_device}")
    print(f"selected_device_name={probe.selected_device_name}")
    if probe.input_device_names:
        print(f"input_device_names={','.join(probe.input_device_names)}")
    print(f"arecord_available={probe.arecord_available}")
    if probe.warning:
        print(f"warning={probe.warning}")

    if args.require_real and probe.mode != "real":
        print("FAIL")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
