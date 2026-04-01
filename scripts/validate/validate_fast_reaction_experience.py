#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import monotonic, sleep

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.behavior.safety_guard import BehaviorSafetyGuard
from robot_life.cli_shared import _build_arbitration_runtime, _resolve_camera_device, _resolve_event_priorities
from robot_life.common.config import (
    load_app_config,
    load_arbitration_config,
    load_safety_config,
    load_stabilizer_config,
)
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime import (
    LiveLoop,
    LiveLoopDependencies,
    SourceBundle,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
    build_live_camera_source,
    build_live_microphone_source,
    build_pipeline_registry,
    load_detector_config,
    microphone_source_options_from_detector_cfg,
)


def _default_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def _camera_read_timeout_s(timeout_ms: int) -> float:
    return max(20, int(timeout_ms)) / 1000.0


def _family_for_event(event_type: str) -> str | None:
    normalized = str(event_type or "").lower()
    if "gesture" in normalized:
        return "gesture"
    if "gaze" in normalized:
        return "gaze"
    if "motion" in normalized:
        return "motion"
    if "loud_sound" in normalized or "audio" in normalized:
        return "audio"
    if "face" in normalized or normalized in {"familiar_face", "stranger_face"}:
        return "face"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a manual fast-reaction experience validation with local camera and microphone."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_path("configs", "runtime", "local", "local_mac_fast_reaction.yaml"),
    )
    parser.add_argument(
        "--detectors",
        type=Path,
        default=_default_path("configs", "detectors", "local", "local_mac_fast_reaction.yaml"),
    )
    parser.add_argument(
        "--arbitration-config",
        type=Path,
        default=_default_path("configs", "arbitration", "default.yaml"),
    )
    parser.add_argument(
        "--stabilizer",
        type=Path,
        default=_default_path("configs", "stabilizer", "local", "local_mac_fast_reaction.yaml"),
    )
    parser.add_argument(
        "--safety-config",
        type=Path,
        default=_default_path("configs", "safety", "default.yaml"),
    )
    parser.add_argument("--duration-sec", type=int, default=30)
    parser.add_argument("--poll-interval", type=float, default=1.0 / 30.0)
    parser.add_argument("--camera-device-index", type=int, default=0)
    parser.add_argument(
        "--strict-camera-index",
        action="store_true",
        help="Do not remap camera index; fail fast when requested index is unavailable.",
    )
    parser.add_argument("--camera-read-timeout-ms", type=int, default=80)
    parser.add_argument(
        "--mock-if-unavailable",
        action="store_true",
        help="Fallback to mock camera/microphone when real devices are unavailable.",
    )
    parser.add_argument("--report-json", type=Path, default=None)
    args = parser.parse_args()

    app_cfg = load_app_config(args.config)
    detector_cfg = load_detector_config(args.detectors)
    arbitration_cfg = load_arbitration_config(args.arbitration_config)
    stabilizer_cfg = load_stabilizer_config(args.stabilizer)
    safety_cfg = load_safety_config(args.safety_config)

    registry = build_pipeline_registry(
        app_cfg.runtime.enabled_pipelines,
        detector_cfg,
        mock_drivers=app_cfg.runtime.mock_drivers,
    )
    arbitrator = Arbitrator(config=arbitration_cfg)
    runtime = _build_arbitration_runtime(arbitrator, arbitration_cfg)
    loop = LiveLoop(
        registry=registry,
        source_bundle=SourceBundle(),
        dependencies=LiveLoopDependencies(
            builder=EventBuilder(event_priorities=_resolve_event_priorities(arbitration_cfg)),
            stabilizer=EventStabilizer.from_config(stabilizer_cfg),
            aggregator=SceneAggregator(),
            arbitrator=arbitrator,
            arbitration_runtime=runtime,
            executor=BehaviorExecutor(
                ResourceManager(),
                safety_guard=BehaviorSafetyGuard.from_config(safety_cfg),
            ),
            event_priorities=_resolve_event_priorities(arbitration_cfg),
        ),
        fast_path_budget_ms=app_cfg.runtime.fast_path_budget_ms,
        fast_path_pending_limit=app_cfg.runtime.fast_path_pending_limit,
        max_scenes_per_cycle=app_cfg.runtime.max_scenes_per_cycle,
        async_perception_enabled=app_cfg.runtime.async_perception_enabled,
        async_perception_queue_limit=app_cfg.runtime.async_perception_queue_limit,
        async_perception_result_max_age_ms=app_cfg.runtime.async_perception_result_max_age_ms,
        async_executor_enabled=app_cfg.runtime.async_executor_enabled,
        async_executor_queue_limit=app_cfg.runtime.async_executor_queue_limit,
        async_capture_enabled=app_cfg.runtime.async_capture_enabled,
        async_capture_queue_limit=app_cfg.runtime.async_capture_queue_limit,
        enable_slow_scene=False,
    )

    actual_camera = None
    if app_cfg.runtime.mock_drivers:
        loop.source_bundle = SourceBundle(
            camera=SyntheticCameraSource(),
            microphone=SyntheticMicrophoneSource(),
        )
    else:
        try:
            actual_camera, usable_devices = _resolve_camera_device(
                args.camera_device_index,
                allow_remap=not args.strict_camera_index,
            )
        except RuntimeError as exc:
            if args.mock_if_unavailable:
                print(f"[warn] 摄像头不可用，自动切到 mock: {exc}")
                loop.registry = build_pipeline_registry(
                    app_cfg.runtime.enabled_pipelines,
                    detector_cfg,
                    mock_drivers=True,
                )
                loop.source_bundle = SourceBundle(
                    camera=SyntheticCameraSource(),
                    microphone=SyntheticMicrophoneSource(),
                )
                actual_camera = None
            else:
                print(f"[error] 摄像头不可用：{exc}")
                print("[hint] 请先关闭正在占用摄像头的 UI / benchmark / soak 进程，再重试该脚本。")
                return 1
        else:
            if actual_camera != args.camera_device_index:
                print(
                    f"[info] 请求摄像头索引 {args.camera_device_index} 不可用，已自动切换到 {actual_camera}。"
                    f" 可用索引: {usable_devices}"
                )
            microphone_source, mic_warning = build_live_microphone_source(
                **microphone_source_options_from_detector_cfg(detector_cfg)
            )
            if mic_warning:
                print(f"[info] {mic_warning}")
            loop.source_bundle = SourceBundle(
                camera=build_live_camera_source(
                    device_index=actual_camera,
                    read_timeout_s=_camera_read_timeout_s(args.camera_read_timeout_ms),
                ),
                microphone=microphone_source,
            )

    families = ("face", "gaze", "gesture", "motion", "audio")
    observed = {family: {"detections": 0, "stable_events": 0, "executions": 0} for family in families}
    behaviors: dict[str, int] = {}
    scenes: dict[str, int] = {}

    started_at = monotonic()
    deadline = started_at + max(1, args.duration_sec)
    iterations = 0

    try:
        loop.start()
        while monotonic() < deadline:
            result = loop.run_once()
            iterations += 1

            for detection in result.detections:
                family = _family_for_event(detection.event_type)
                if family is not None:
                    observed[family]["detections"] += 1

            for stable_event in result.stable_events:
                family = _family_for_event(stable_event.event_type)
                if family is not None:
                    observed[family]["stable_events"] += 1

            for scene in result.scene_candidates:
                scenes[scene.scene_type] = scenes.get(scene.scene_type, 0) + 1

            for execution in result.execution_results:
                behaviors[execution.behavior_id] = behaviors.get(execution.behavior_id, 0) + 1
                if execution.behavior_id == "perform_greeting":
                    observed["face"]["executions"] += 1
                elif execution.behavior_id == "perform_attention":
                    observed["gaze"]["executions"] += 1
                elif execution.behavior_id == "perform_gesture_response":
                    observed["gesture"]["executions"] += 1
                elif execution.behavior_id == "perform_tracking":
                    observed["motion"]["executions"] += 1
                elif execution.behavior_id == "perform_safety_alert":
                    observed["audio"]["executions"] += 1

            sleep(max(0.0, args.poll_interval))
    finally:
        loop.stop()

    duration_sec = max(0.0, monotonic() - started_at)
    estimated_loop_fps = (iterations / duration_sec) if duration_sec > 0 else 0.0
    passed_families = [
        family
        for family, counters in observed.items()
        if counters["detections"] > 0 or counters["stable_events"] > 0 or counters["executions"] > 0
    ]

    print("=== Fast Reaction Experience Summary ===")
    print(f"iterations={iterations}")
    print(f"duration_sec={duration_sec:.2f}")
    print(f"estimated_loop_fps={estimated_loop_fps:.2f}")
    print(f"camera_device(requested)={args.camera_device_index}")
    print(f"camera_device(actual)={actual_camera if actual_camera is not None else 'mock'}")
    for family in families:
        counters = observed[family]
        status = "PASS" if family in passed_families else "MISS"
        print(
            f"{family}={status} detections={counters['detections']} "
            f"stable_events={counters['stable_events']} executions={counters['executions']}"
        )
    print(f"scenes={json.dumps(scenes, ensure_ascii=False, sort_keys=True)}")
    print(f"behaviors={json.dumps(behaviors, ensure_ascii=False, sort_keys=True)}")

    report = {
        "iterations": iterations,
        "duration_sec": round(duration_sec, 3),
        "estimated_loop_fps": round(estimated_loop_fps, 3),
        "camera_device": {
            "requested": args.camera_device_index,
            "actual": actual_camera,
        },
        "families": observed,
        "scenes": scenes,
        "behaviors": behaviors,
        "passed_families": passed_families,
    }
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
