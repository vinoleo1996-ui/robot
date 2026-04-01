from __future__ import annotations

import numpy as np

from robot_life.common.schemas import DetectionResult
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime import AggregatingTelemetrySink, InMemoryTelemetrySink, MultiTelemetrySink
from robot_life.runtime.live_loop import LiveLoop, LiveLoopDependencies
from robot_life.runtime.load_shedder import ResourceLoadShedder
from robot_life.runtime.sources import FramePacket


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
        return {
            "camera": FramePacket(source="camera", payload=frame, frame_index=self._frame_index),
        }

    def snapshot_health(self) -> dict[str, object]:
        return {"camera": {"read_failures": 0, "total_failures": 0, "status": "ok"}}


class _FakeRegistry:
    def __init__(self) -> None:
        self.runtime_scales: dict[str, float] = {}

    def initialize_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def process_all(self, frames: dict[str, object]):
        assert "camera" in frames
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

    def set_runtime_scales(self, scales: dict[str, float]) -> None:
        self.runtime_scales = dict(scales)


class _FakeSlowScene:
    force_sample = True
    sample_interval_s = 1.0


def _build_loop(*, telemetry) -> LiveLoop:
    deps = LiveLoopDependencies(
        builder=EventBuilder(),
        stabilizer=EventStabilizer(debounce_count=1, cooldown_ms=0, dedup_window_ms=0),
        aggregator=SceneAggregator(min_single_signal_score=0.1),
        arbitrator=Arbitrator(),
        telemetry=telemetry,
    )
    return LiveLoop(
        registry=_FakeRegistry(),
        source_bundle=_FakeSourceBundle(),
        dependencies=deps,
        telemetry=telemetry,
        max_scenes_per_cycle=4,
    )


def test_aggregating_telemetry_sink_collects_runtime_stages() -> None:
    aggregate = AggregatingTelemetrySink()
    memory = InMemoryTelemetrySink()
    telemetry = MultiTelemetrySink(aggregate, memory)
    loop = _build_loop(telemetry=telemetry)

    result = loop.run_once()

    assert result.scene_candidates
    snapshot = aggregate.snapshot()
    stages = snapshot["stages"]
    assert "pipeline_registry" in stages
    assert "source_health" in stages
    assert "runtime_health" in stages
    assert "interaction_state" in stages


def test_load_shedder_blends_intent_profile_with_pressure_controls() -> None:
    registry = _FakeRegistry()
    slow_scene = _FakeSlowScene()
    shedder = ResourceLoadShedder(
        queue_drain_latency_budget_ms=100.0,
        queue_drain_pending_threshold=4,
    )
    payload = shedder.apply(
        queue_pending=5,
        cycle_latency_ms=160.0,
        queue_pressure_streak=2,
        registry=registry,
        task_service=slow_scene,
        interaction_intent="maintain_engagement",
    )

    assert payload["load_shed_mode"] == "strong"
    assert payload["intent_profile"] == "maintain_engagement"
    assert registry.runtime_scales["face"] > registry.runtime_scales["motion"]
    assert slow_scene.force_sample is False
    assert slow_scene.sample_interval_s >= shedder.strong_interval_s
