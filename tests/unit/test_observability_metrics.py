from robot_life.behavior.resources import ResourceManager
from robot_life.common.schemas import DetectionResult, EventPriority
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.stabilizer import EventStabilizer


def test_stabilizer_snapshot_stats_contains_reason_counters() -> None:
    builder = EventBuilder()
    stabilizer = EventStabilizer(
        debounce_count=2,
        debounce_window_ms=500,
        cooldown_ms=0,
        hysteresis_threshold=0.0,
        dedup_window_ms=0,
    )
    detection = DetectionResult.synthetic(
        detector="face",
        event_type="familiar_face",
        confidence=0.92,
        payload={"target_id": "u1"},
    )

    first = stabilizer.process(builder.build(detection, priority=EventPriority.P2))
    second = stabilizer.process(builder.build(detection, priority=EventPriority.P2))
    stats = stabilizer.snapshot_stats()

    assert first is None
    assert second is not None
    assert stats["totals"]["input"] == 2
    assert stats["totals"]["emitted"] == 1
    assert stats["totals"]["filtered_debounce"] == 1
    assert "familiar_face_detected" in stats["by_event"]


def test_resource_manager_snapshot_tracks_preemptions() -> None:
    manager = ResourceManager()
    low = manager.request_grant(
        trace_id="t1",
        decision_id="d1",
        behavior_id="low_priority_audio",
        required_resources=["AudioOut"],
        optional_resources=[],
        priority=1,
        duration_ms=5000,
    )
    high = manager.request_grant(
        trace_id="t2",
        decision_id="d2",
        behavior_id="high_priority_audio",
        required_resources=["AudioOut"],
        optional_resources=[],
        priority=3,
        duration_ms=5000,
    )
    snapshot = manager.debug_snapshot()

    assert low.granted is True
    assert high.granted is True
    assert snapshot["stats"]["preemptions"] >= 1
    assert snapshot["owners"]["AudioOut"][0]["behavior_id"] == "high_priority_audio"


def test_arbitration_runtime_snapshot_tracks_outcomes() -> None:
    runtime = ArbitrationRuntime(arbitrator=Arbitrator())
    greeting_scene = type(
        "Scene",
        (),
        {"scene_type": "greeting_scene", "trace_id": "trace_1", "score_hint": 0.9},
    )()
    attention_scene = type(
        "Scene",
        (),
        {"scene_type": "attention_scene", "trace_id": "trace_2", "score_hint": 0.8},
    )()

    assert runtime.submit(greeting_scene) is not None
    assert runtime.submit(attention_scene) is None
    snapshot = runtime.snapshot_stats()

    assert snapshot["outcomes"]["executed"] >= 1
    assert snapshot["outcomes"]["queued"] >= 1
    assert snapshot["pending_queue"] >= 1
    assert snapshot["pending_by_priority"]["P2"] >= 1
    assert snapshot["pending_by_priority"]["P1"] == 0
