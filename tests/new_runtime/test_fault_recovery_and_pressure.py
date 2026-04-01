from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.common.schemas import DetectionResult, ExecutionResult
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime.health_monitor import RuntimeHealthMonitor
from robot_life.runtime.live_loop import LiveLoop, LiveLoopDependencies
from robot_life.runtime.long_task_coordinator import LongTaskCoordinator
from robot_life.runtime.sources import FramePacket
from robot_life.runtime.telemetry import AggregatingTelemetrySink


class _FakeSlowService:
    request_timeout_ms = 5
    sample_interval_s = 0.0
    force_sample = True

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def submit(self, scene, image=None, timeout_ms=0, metadata=None):
        return "req-1"

    def query(self, request_id: str):
        return None

    def get_request_state(self, request_id: str):
        return "PENDING"

    def cancel(self, request_id: str) -> None:
        self.cancelled.append(request_id)


class _FakeSourceBundle:
    def __init__(self) -> None:
        self._frame_index = 0

    def open_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def read_packets(self) -> dict[str, FramePacket]:
        self._frame_index += 1
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        return {"camera": FramePacket(source="camera", payload=frame, frame_index=self._frame_index)}

    def snapshot_health(self) -> dict[str, object]:
        return {"camera": {"read_failures": 0, "total_failures": 0, "status": "ok"}}


class _FakeRegistry:
    def initialize_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def process_all(self, frames: dict[str, object]):
        return [
            (
                "face",
                {
                    "detections": [
                        DetectionResult.synthetic(
                            detector="face",
                            event_type="familiar_face_detected",
                            confidence=0.95,
                            payload={"target_id": "alice"},
                        )
                    ]
                },
            )
        ]


class _FakeExecutor(BehaviorExecutor):
    def execute(self, decision, duration_ms: int = 5000):  # type: ignore[override]
        return ExecutionResult(
            execution_id="exec-1",
            trace_id=decision.trace_id,
            behavior_id=decision.target_behavior,
            status="finished",
            interrupted=False,
            degraded=False,
            started_at=1.0,
            ended_at=2.0,
            target_id=decision.target_id,
            scene_type=decision.scene_type,
            interaction_episode_id=decision.interaction_episode_id,
            scene_epoch=decision.scene_epoch,
            decision_epoch=decision.decision_epoch,
        )


def test_long_task_coordinator_drops_stale_pending_requests() -> None:
    coordinator = LongTaskCoordinator(stale_timeout_factor=1.0)
    service = _FakeSlowService()
    scene = SimpleNamespace(
        scene_type="attention_scene",
        scene_id="scene-1",
        trace_id="trace-1",
        target_id="alice",
        primary_target_id="alice",
        related_entity_ids=["alice"],
        interaction_episode_id="episode-1",
        scene_epoch="1:episode-1:attention_scene:alice",
        score_hint=0.4,
        payload={"interaction_intent": "ack_presence"},
    )
    collected = SimpleNamespace(
        frame_seq=1,
        collected_at=1.0,
        packets={"camera": SimpleNamespace(payload=np.zeros((2, 2, 3), dtype=np.uint8), frame_index=1)},
    )
    coordinator.submit_or_query(service, scene, collected)
    pending = next(iter(coordinator._pending.values()))
    pending.submitted_at -= 1.0
    ready = coordinator.drain_ready_results(service)
    assert ready == []
    assert coordinator.stale_dropped == 1
    assert service.cancelled == ["req-1"]


def test_runtime_health_monitor_recommends_safe_idle_after_repeated_execution_failures() -> None:
    monitor = RuntimeHealthMonitor(blocked_execution_limit=2)
    failed = SimpleNamespace(status="blocked")
    monitor.record_execution(failed)
    monitor.record_execution(failed)
    snapshot = monitor.snapshot()
    assert snapshot["degraded"] is True
    assert snapshot["safe_idle_recommended"] is True


def test_live_loop_suppresses_social_execution_when_health_requires_safe_idle() -> None:
    telemetry = AggregatingTelemetrySink()
    deps = LiveLoopDependencies(
        builder=EventBuilder(),
        stabilizer=EventStabilizer(debounce_count=1, cooldown_ms=0, dedup_window_ms=0),
        aggregator=SceneAggregator(min_single_signal_score=0.1),
        arbitrator=Arbitrator(),
        executor=_FakeExecutor(),
        telemetry=telemetry,
    )
    loop = LiveLoop(
        registry=_FakeRegistry(),
        source_bundle=_FakeSourceBundle(),
        dependencies=deps,
        telemetry=telemetry,
        max_scenes_per_cycle=4,
    )
    loop._health_monitor.record_execution(SimpleNamespace(status="blocked"))
    loop._health_monitor.record_execution(SimpleNamespace(status="blocked"))

    result = loop.run_once()

    assert result.scene_candidates
    assert result.execution_results == []
    runtime_health = telemetry.snapshot()["stages"]["runtime_health"]["last_payload"]
    assert runtime_health["safe_idle_recommended"] is True
