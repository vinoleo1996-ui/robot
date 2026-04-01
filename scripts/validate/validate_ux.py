#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from time import monotonic, sleep

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.common.config import load_app_config, load_arbitration_config, load_stabilizer_config
from robot_life.common.schemas import EventPriority
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime import (
    CameraSource,
    build_live_microphone_source,
    LiveLoop,
    LiveLoopDependencies,
    SourceBundle,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
    build_pipeline_registry,
    load_detector_config,
    microphone_source_options_from_detector_cfg,
)


def _default_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def _camera_read_timeout_s(timeout_ms: int) -> float:
    return max(20, int(timeout_ms)) / 1000.0


def _resolve_event_priorities(priority_map: dict[str, str]) -> dict[str, EventPriority]:
    resolved: dict[str, EventPriority] = {}
    for event_type, priority_name in priority_map.items():
        try:
            resolved[str(event_type)] = EventPriority(str(priority_name))
        except ValueError:
            continue
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate UX stability and low-disturbance behavior.")
    parser.add_argument("--duration-sec", type=int, default=600, help="Soak duration in seconds (default 10 min).")
    parser.add_argument("--poll-interval", type=float, default=1.0 / 30.0)
    parser.add_argument("--max-repeat-streak", type=int, default=20)
    parser.add_argument("--max-repeat-within-10s", type=int, default=12)
    parser.add_argument("--camera-device-index", type=int, default=0)
    parser.add_argument("--camera-read-timeout-ms", type=int, default=120)
    parser.add_argument("--min-camera-packets", type=int, default=1)
    parser.add_argument("--min-microphone-packets", type=int, default=0)
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_path("configs", "runtime", "app.default.yaml"),
    )
    parser.add_argument(
        "--detectors",
        type=Path,
        default=_default_path("configs", "detectors", "desktop_4090", "desktop_4090.yaml"),
    )
    parser.add_argument(
        "--stabilizer",
        type=Path,
        default=_default_path("configs", "stabilizer", "default.yaml"),
    )
    parser.add_argument(
        "--arbitration-config",
        type=Path,
        default=_default_path("configs", "arbitration", "default.yaml"),
    )
    args = parser.parse_args()

    app_cfg = load_app_config(args.config)
    detector_cfg = load_detector_config(args.detectors)
    stabilizer_cfg = load_stabilizer_config(args.stabilizer)
    arbitration_cfg = load_arbitration_config(args.arbitration_config)

    registry = build_pipeline_registry(
        enabled_pipelines=app_cfg.runtime.enabled_pipelines,
        detector_cfg=detector_cfg,
        mock_drivers=app_cfg.runtime.mock_drivers,
    )
    dependencies = LiveLoopDependencies(
        builder=EventBuilder(),
        stabilizer=EventStabilizer.from_config(stabilizer_cfg),
        aggregator=SceneAggregator(),
        arbitrator=Arbitrator(),
        arbitration_runtime=ArbitrationRuntime(arbitrator=Arbitrator()),
        executor=BehaviorExecutor(ResourceManager()),
        event_priorities=_resolve_event_priorities(dict(arbitration_cfg.event_priorities)),
    )

    if app_cfg.runtime.mock_drivers:
        sources = SourceBundle(
            camera=SyntheticCameraSource(),
            microphone=SyntheticMicrophoneSource(),
        )
    else:
        microphone_source, mic_warning = build_live_microphone_source(
            **microphone_source_options_from_detector_cfg(detector_cfg)
        )
        if mic_warning:
            print(f"[warn] {mic_warning}")
        sources = SourceBundle(
            camera=CameraSource(
                device_index=args.camera_device_index,
                read_timeout_s=_camera_read_timeout_s(args.camera_read_timeout_ms),
            ),
            microphone=microphone_source,
        )

    loop = LiveLoop(registry=registry, source_bundle=sources, dependencies=dependencies)
    started = monotonic()
    ended = started + max(1, args.duration_sec)
    execution_events: list[tuple[float, str]] = []
    empty_iterations = 0
    iterations = 0
    camera_packets = 0
    microphone_packets = 0

    try:
        loop.start()
        while monotonic() < ended:
            iter_started = monotonic()
            result = loop.run_once()
            iterations += 1
            if "camera" in result.collected_frames.packets:
                camera_packets += 1
            if "microphone" in result.collected_frames.packets:
                microphone_packets += 1
            if not result.execution_results:
                empty_iterations += 1
            for execution in result.execution_results:
                execution_events.append((monotonic(), execution.behavior_id))

            elapsed = monotonic() - iter_started
            sleep(max(0.0, args.poll_interval - elapsed))
    finally:
        loop.stop()

    duration = max(1.0, monotonic() - started)
    executions_per_min = (len(execution_events) / duration) * 60.0
    silence_ratio = empty_iterations / max(1, iterations)

    max_streak = 0
    current_streak = 0
    previous_behavior = None
    for _, behavior in execution_events:
        if behavior == previous_behavior:
            current_streak += 1
        else:
            current_streak = 1
            previous_behavior = behavior
        max_streak = max(max_streak, current_streak)

    max_repeat_10s = 0
    per_behavior_times: defaultdict[str, list[float]] = defaultdict(list)
    for timestamp, behavior in execution_events:
        timestamps = per_behavior_times[behavior]
        timestamps.append(timestamp)
        cutoff = timestamp - 10.0
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)
        max_repeat_10s = max(max_repeat_10s, len(timestamps))

    print("=== UX Validation Summary ===")
    print(f"duration_sec={duration:.2f}")
    print(f"iterations={iterations}")
    print(f"executions={len(execution_events)}")
    print(f"camera_packets={camera_packets}")
    print(f"microphone_packets={microphone_packets}")
    print(f"camera_read_timeout_ms={args.camera_read_timeout_ms}")
    print(f"executions_per_min={executions_per_min:.2f}")
    print(f"silence_ratio={silence_ratio:.2f}")
    print(f"max_repeat_streak={max_streak}")
    print(f"max_repeat_within_10s={max_repeat_10s}")

    failures: list[str] = []
    if max_streak > args.max_repeat_streak:
        failures.append(
            f"repeat streak {max_streak} exceeds limit {args.max_repeat_streak}"
        )
    if max_repeat_10s > args.max_repeat_within_10s:
        failures.append(
            f"repeat within 10s {max_repeat_10s} exceeds limit {args.max_repeat_within_10s}"
        )
    if not app_cfg.runtime.mock_drivers and camera_packets < args.min_camera_packets:
        failures.append(
            f"camera packets {camera_packets} below minimum {args.min_camera_packets}"
        )
    if not app_cfg.runtime.mock_drivers and microphone_packets < args.min_microphone_packets:
        failures.append(
            f"microphone packets {microphone_packets} below minimum {args.min_microphone_packets}"
        )

    if failures:
        print("UX VALIDATION FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("UX VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
