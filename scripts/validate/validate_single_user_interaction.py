#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
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
    CameraSource,
    LiveLoop,
    LiveLoopDependencies,
    SourceBundle,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
    build_live_microphone_source,
    build_pipeline_registry,
    load_detector_config,
    microphone_source_options_from_detector_cfg,
)


@dataclass(frozen=True)
class InteractionPhase:
    key: str
    title: str
    expected_family: str
    instruction: str


PHASES: tuple[InteractionPhase, ...] = (
    InteractionPhase(
        key="approach",
        title="靠近机器人",
        expected_family="face",
        instruction="请在镜头前靠近并保持正脸 3-5 秒。",
    ),
    InteractionPhase(
        key="gaze",
        title="持续注视",
        expected_family="gaze",
        instruction="请持续注视镜头/机器人 3-5 秒，避免大幅移动。",
    ),
    InteractionPhase(
        key="wave",
        title="挥手招呼",
        expected_family="gesture",
        instruction="请在镜头内做明显挥手动作 3-5 秒。",
    ),
    InteractionPhase(
        key="ambient_motion",
        title="环境运动",
        expected_family="motion",
        instruction="请让画面中出现快速移动的小目标（例如手持物体左右晃动）。",
    ),
    InteractionPhase(
        key="loud_sound",
        title="声音刺激",
        expected_family="audio",
        instruction="请在麦克风附近拍手或发出短促大声响。",
    ),
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


def _family_for_behavior(behavior_id: str) -> str | None:
    mapping = {
        "perform_greeting": "face",
        "perform_attention": "gaze",
        "perform_gesture_response": "gesture",
        "perform_tracking": "motion",
        "perform_safety_alert": "audio",
    }
    return mapping.get(str(behavior_id))


def build_phase_coverage_report(phase_rows: list[dict[str, object]]) -> dict[str, object]:
    total = len(phase_rows)
    passed = sum(1 for row in phase_rows if bool(row.get("passed")))
    coverage = (passed / total) if total > 0 else 0.0
    return {
        "total_phases": total,
        "passed_phases": passed,
        "coverage_ratio": round(coverage, 4),
        "coverage_percent": round(coverage * 100.0, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run guided single-user local fast-reaction validation and output coverage report."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_path("configs", "runtime", "local", "local_mac_fast_reaction_realtime.yaml"),
    )
    parser.add_argument(
        "--detectors",
        type=Path,
        default=_default_path("configs", "detectors", "local", "local_mac_fast_reaction_realtime.yaml"),
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
    parser.add_argument("--duration-per-phase-sec", type=int, default=10)
    parser.add_argument("--poll-interval", type=float, default=1.0 / 30.0)
    parser.add_argument("--camera-device-index", type=int, default=0)
    parser.add_argument(
        "--strict-camera-index",
        action="store_true",
        help="Do not remap camera index; fail fast when requested index is unavailable.",
    )
    parser.add_argument("--camera-read-timeout-ms", type=int, default=120)
    parser.add_argument(
        "--mock-if-unavailable",
        action="store_true",
        help="Fallback to mock camera/microphone when real devices are unavailable.",
    )
    parser.add_argument("--min-coverage", type=float, default=0.8)
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

    camera_actual: int | str = "mock"
    if app_cfg.runtime.mock_drivers:
        loop.source_bundle = SourceBundle(
            camera=SyntheticCameraSource(),
            microphone=SyntheticMicrophoneSource(),
        )
    else:
        try:
            camera_actual, usable_devices = _resolve_camera_device(
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
                camera_actual = "mock"
            else:
                print(f"[error] 摄像头不可用：{exc}")
                return 1
        else:
            if camera_actual != args.camera_device_index:
                print(
                    f"[info] 请求摄像头索引 {args.camera_device_index} 不可用，已自动切换到 {camera_actual}。"
                    f" 可用索引: {usable_devices}"
                )
            microphone_source, mic_warning = build_live_microphone_source(
                **microphone_source_options_from_detector_cfg(detector_cfg)
            )
            if mic_warning:
                print(f"[info] {mic_warning}")
            loop.source_bundle = SourceBundle(
                camera=CameraSource(
                    device_index=camera_actual,
                    read_timeout_s=_camera_read_timeout_s(args.camera_read_timeout_ms),
                ),
                microphone=microphone_source,
            )

    phase_rows: list[dict[str, object]] = []
    started_at = monotonic()

    try:
        loop.start()
        print("=== Single User Interaction Validation ===")
        print(f"camera_device(requested)={args.camera_device_index}")
        print(f"camera_device(actual)={camera_actual}")
        print(f"phase_count={len(PHASES)}")
        print(f"duration_per_phase_sec={max(1, args.duration_per_phase_sec)}")

        for index, phase in enumerate(PHASES, start=1):
            print(f"\n[{index}/{len(PHASES)}] {phase.title}")
            print(f"  指引: {phase.instruction}")
            phase_started = monotonic()
            phase_deadline = phase_started + max(1, args.duration_per_phase_sec)
            row = {
                "phase": phase.key,
                "title": phase.title,
                "expected_family": phase.expected_family,
                "detections": 0,
                "stable_events": 0,
                "executions": 0,
                "passed": False,
            }
            while monotonic() < phase_deadline:
                result = loop.run_once()
                for detection in result.detections:
                    if _family_for_event(detection.event_type) == phase.expected_family:
                        row["detections"] = int(row["detections"]) + 1
                for stable_event in result.stable_events:
                    if _family_for_event(stable_event.event_type) == phase.expected_family:
                        row["stable_events"] = int(row["stable_events"]) + 1
                for execution in result.execution_results:
                    if _family_for_behavior(execution.behavior_id) == phase.expected_family:
                        row["executions"] = int(row["executions"]) + 1
                sleep(max(0.0, args.poll_interval))

            row["passed"] = (
                int(row["detections"]) > 0
                or int(row["stable_events"]) > 0
                or int(row["executions"]) > 0
            )
            row["elapsed_sec"] = round(monotonic() - phase_started, 3)
            phase_rows.append(row)

            status = "PASS" if row["passed"] else "MISS"
            print(
                f"  {status} detections={row['detections']} "
                f"stable_events={row['stable_events']} executions={row['executions']}"
            )
    finally:
        loop.stop()

    coverage = build_phase_coverage_report(phase_rows)
    total_elapsed = monotonic() - started_at
    print("\n=== Single User Interaction Coverage ===")
    print(
        f"coverage={coverage['coverage_percent']}% "
        f"({coverage['passed_phases']}/{coverage['total_phases']})"
    )

    report = {
        "camera_device": {"requested": args.camera_device_index, "actual": camera_actual},
        "duration_per_phase_sec": max(1, args.duration_per_phase_sec),
        "elapsed_sec": round(total_elapsed, 3),
        "phases": phase_rows,
        "coverage": coverage,
    }
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"report_json={args.report_json}")

    if float(coverage["coverage_ratio"]) < max(0.0, min(1.0, float(args.min_coverage))):
        print(f"result=FAIL min_coverage={args.min_coverage}")
        return 2
    print(f"result=PASS min_coverage={args.min_coverage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
