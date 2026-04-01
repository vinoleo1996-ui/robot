#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import monotonic, sleep

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from robot_life.common.config import load_app_config
from robot_life.runtime import (
    LiveLoop,
    SourceBundle,
    SyntheticCameraSource,
    build_live_camera_source,
    build_pipeline_registry,
)


def _default_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def _camera_read_timeout_s(timeout_ms: int) -> float:
    return max(20, int(timeout_ms)) / 1000.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a camera-only live-loop validation and verify frame packets are produced."
    )
    parser.add_argument("--iterations", type=int, default=60)
    parser.add_argument("--poll-interval", type=float, default=1.0 / 30.0)
    parser.add_argument("--camera-device-index", type=int, default=0)
    parser.add_argument("--camera-read-timeout-ms", type=int, default=120)
    parser.add_argument("--min-camera-packets", type=int, default=1)
    parser.add_argument("--max-camera-recoveries", type=int, default=999999)
    parser.add_argument("--max-camera-failures", type=int, default=999999)
    parser.add_argument("--mock-drivers", action="store_true", help="Force synthetic camera for smoke tests.")
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_path("configs", "runtime", "local", "local_mac_fast_reaction.yaml"),
    )
    args = parser.parse_args()

    app_cfg = load_app_config(args.config)
    use_mock_drivers = bool(args.mock_drivers or app_cfg.runtime.mock_drivers)

    source_bundle = SourceBundle(
        camera=(
            SyntheticCameraSource()
            if use_mock_drivers
            else build_live_camera_source(
                device_index=args.camera_device_index,
                read_timeout_s=_camera_read_timeout_s(args.camera_read_timeout_ms),
            )
        )
    )
    registry = build_pipeline_registry(
        enabled_pipelines=[],
        detector_cfg={},
        mock_drivers=use_mock_drivers,
    )
    loop = LiveLoop(registry=registry, source_bundle=source_bundle)

    iterations = max(1, args.iterations)
    camera_packet_count = 0
    camera_opened = False
    camera_health: dict[str, object] = {}

    try:
        loop.start()
        camera_opened = source_bundle.camera is not None and source_bundle.camera.is_open
        for _ in range(iterations):
            started = monotonic()
            result = loop.run_once()
            if "camera" in result.collected_frames.packets:
                camera_packet_count += 1
            elapsed = monotonic() - started
            sleep(max(0.0, args.poll_interval - elapsed))
    finally:
        loop.stop()
        camera = source_bundle.camera
        if camera is not None and hasattr(camera, "snapshot_health"):
            try:
                camera_health = camera.snapshot_health()
            except Exception:
                camera_health = {}

    print("=== Camera-Only Validation Summary ===")
    print(f"config={args.config}")
    print(f"mock_drivers={use_mock_drivers}")
    print(f"iterations={iterations}")
    print(f"camera_opened={camera_opened}")
    print(f"camera_packets={camera_packet_count}")
    print(f"camera_read_timeout_ms={args.camera_read_timeout_ms}")
    print(f"min_camera_packets={args.min_camera_packets}")
    if camera_health:
        print(f"camera_backend={camera_health.get('backend', '-')}")
        print(f"camera_total_failures={camera_health.get('total_failures', 0)}")
        print(f"camera_recovery_count={camera_health.get('recovery_count', 0)}")
        print(f"camera_last_frame_at={camera_health.get('last_frame_at')}")

    failures: list[str] = []
    if not camera_opened:
        failures.append("camera source did not open successfully")
    if camera_packet_count < args.min_camera_packets:
        failures.append(
            f"camera packets {camera_packet_count} below minimum {args.min_camera_packets}"
        )
    total_failures = int(camera_health.get("total_failures", 0) or 0)
    recovery_count = int(camera_health.get("recovery_count", 0) or 0)
    if total_failures > args.max_camera_failures:
        failures.append(
            f"camera total_failures {total_failures} exceeded max {args.max_camera_failures}"
        )
    if recovery_count > args.max_camera_recoveries:
        failures.append(
            f"camera recovery_count {recovery_count} exceeded max {args.max_camera_recoveries}"
        )

    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
