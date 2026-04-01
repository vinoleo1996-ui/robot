from robot_life.behavior.resources import ResourceManager
from robot_life.common.schemas import DetectionResult, EventPriority, StableEvent
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer


def test_detection_to_raw_event() -> None:
    """Test detection to raw event conversion."""
    detection = DetectionResult.synthetic(
        detector="face_pipeline",
        event_type="familiar_face",
        confidence=0.9,
        payload={"target_id": "user_1"},
    )
    raw_event = EventBuilder().build(detection, priority=EventPriority.P2)

    assert raw_event.trace_id == detection.trace_id
    assert raw_event.priority == EventPriority.P2
    assert raw_event.cooldown_key == "familiar_face:user_1"


def test_stabilizer_debounce() -> None:
    """Test debounce filtering."""
    stabilizer = EventStabilizer(debounce_count=2, debounce_window_ms=500)
    builder = EventBuilder()

    detection1 = DetectionResult.synthetic(
        detector="face",
        event_type="familiar_face",
        confidence=0.9,
        payload={"target_id": "user_1"},
    )
    raw_event1 = builder.build(detection1, priority=EventPriority.P2)

    # First event should not pass debounce (need 2 confirmations)
    stable1 = stabilizer.process(raw_event1)
    assert stable1 is None, "First event should not pass debounce"

    # Second same event within window should pass
    detection2 = DetectionResult.synthetic(
        detector="face",
        event_type="familiar_face",
        confidence=0.92,
        payload={"target_id": "user_1"},
    )
    raw_event2 = builder.build(detection2, priority=EventPriority.P2)
    stable2 = stabilizer.process(raw_event2)
    assert stable2 is not None, "Second event should pass debounce"
    assert "debounce" in stable2.stabilized_by


def test_stabilizer_cooldown() -> None:
    """Test cooldown enforcement."""
    stabilizer = EventStabilizer(
        debounce_count=1, debounce_window_ms=100, cooldown_ms=500
    )
    builder = EventBuilder()

    detection = DetectionResult.synthetic(
        detector="face",
        event_type="familiar_face",
        confidence=0.9,
        payload={"target_id": "user_1"},
    )

    # First event passes (no cooldown yet)
    raw_event1 = builder.build(detection, priority=EventPriority.P2)
    stable1 = stabilizer.process(raw_event1)
    assert stable1 is not None

    # Immediate second event should be blocked by cooldown
    raw_event2 = builder.build(detection, priority=EventPriority.P2)
    stable2 = stabilizer.process(raw_event2)
    assert stable2 is None, "Immediate second event should be blocked by cooldown"


def test_stabilizer_hysteresis() -> None:
    """Test hysteresis to prevent boundary oscillation."""
    stabilizer = EventStabilizer(
        debounce_count=1,
        debounce_window_ms=100,
        cooldown_ms=100,
        hysteresis_threshold=0.7,
    )
    builder = EventBuilder()

    # High confidence event passes
    detection_high = DetectionResult.synthetic(
        detector="face",
        event_type="familiar_face",
        confidence=0.9,
        payload={"target_id": "user_1"},
    )
    raw_event_high = builder.build(detection_high, priority=EventPriority.P2)
    stable_high = stabilizer.process(raw_event_high)
    assert stable_high is not None

    # Low confidence event should fail hysteresis
    stabilizer.reset()  # Reset for clean test
    detection_low = DetectionResult.synthetic(
        detector="face",
        event_type="familiar_face",
        confidence=0.5,
        payload={"target_id": "user_1"},
    )
    raw_event_low = builder.build(detection_low, priority=EventPriority.P2)
    stable_low = stabilizer.process(raw_event_low)
    assert stable_low is None, "Low confidence event should fail hysteresis check"


def test_stabilizer_dedup() -> None:
    """Test deduplication."""
    stabilizer = EventStabilizer(debounce_count=1, debounce_window_ms=100)
    builder = EventBuilder()

    detection = DetectionResult.synthetic(
        detector="face",
        event_type="familiar_face",
        confidence=0.9,
        payload={"target_id": "user_1"},
    )

    raw_event1 = builder.build(detection, priority=EventPriority.P2)
    stable1 = stabilizer.process(raw_event1)
    assert stable1 is not None
    assert "dedup" in stable1.stabilized_by

    # Exact duplicate within window should be rejected
    raw_event2 = builder.build(detection, priority=EventPriority.P2)
    stable2 = stabilizer.process(raw_event2)
    assert stable2 is None, "Duplicate event should be rejected"


def test_stabilizer_dedup_complex_payload() -> None:
    """Complex payloads (lists/dicts) should dedup without raising hash errors."""
    stabilizer = EventStabilizer(debounce_count=1, debounce_window_ms=100, cooldown_ms=0)
    builder = EventBuilder()

    detection = DetectionResult.synthetic(
        detector="gesture",
        event_type="gesture_open_palm",
        confidence=0.92,
        payload={"hand_bbox": [0.1, 0.2, 0.5, 0.8], "meta": {"hand": "left"}},
    )

    first = stabilizer.process(builder.build(detection, priority=EventPriority.P2))
    second = stabilizer.process(builder.build(detection, priority=EventPriority.P2))
    assert first is not None
    assert second is None


def test_builder_normalizes_gesture_event_type() -> None:
    """Detailed gesture events should normalize to canonical gesture_detected."""
    detection = DetectionResult.synthetic(
        detector="gesture",
        event_type="gesture_open_palm",
        confidence=0.88,
        payload={"hand_index": 0},
    )
    raw_event = EventBuilder().build(detection, priority=EventPriority.P2)

    assert raw_event.event_type == "gesture_detected"
    assert raw_event.cooldown_key == "gesture:gesture"
    assert raw_event.payload["raw_event_type"] == "gesture_open_palm"
    assert raw_event.payload["event_confidence"] == 0.88


def test_scene_aggregator_scene_mapping_and_priority_score() -> None:
    """Scene type and score should reflect event semantics and priority."""
    aggregator = SceneAggregator()
    high = StableEvent(
        stable_event_id="s1",
        base_event_id="e1",
        trace_id="t1",
        event_type="familiar_face_detected",
        priority=EventPriority.P0,
        valid_until_monotonic=0.0,
        stabilized_by=["debounce"],
        payload={"event_confidence": 0.8},
    )
    low = StableEvent(
        stable_event_id="s2",
        base_event_id="e2",
        trace_id="t2",
        event_type="familiar_face_detected",
        priority=EventPriority.P3,
        valid_until_monotonic=0.0,
        stabilized_by=["debounce"],
        payload={"event_confidence": 0.8},
    )

    high_scene = aggregator.aggregate(high)
    low_scene = aggregator.aggregate(low)
    # Single familiar_face without gaze fusion maps to attention_scene.
    # greeting_scene requires familiar_face + gaze signal fusion.
    assert high_scene.scene_type == "attention_scene"
    assert high_scene.score_hint > low_scene.score_hint


def test_scene_aggregator_fuses_familiar_face_and_gaze() -> None:
    aggregator = SceneAggregator()
    face_event = StableEvent(
        stable_event_id="s1",
        base_event_id="e_face",
        trace_id="t1",
        event_type="familiar_face_detected",
        priority=EventPriority.P2,
        valid_until_monotonic=10_000_000.0,
        stabilized_by=["debounce"],
        payload={"target_id": "user_1", "event_confidence": 0.9},
    )
    gaze_event = StableEvent(
        stable_event_id="s2",
        base_event_id="e_gaze",
        trace_id="t1",
        event_type="gaze_sustained_detected",
        priority=EventPriority.P2,
        valid_until_monotonic=10_000_001.0,
        stabilized_by=["debounce"],
        payload={"target_id": "user_1", "event_confidence": 0.85},
    )

    aggregator.aggregate(face_event)
    scene = aggregator.aggregate(gaze_event)
    assert scene.scene_type == "greeting_scene"
    assert set(scene.based_on_events) == {"e_face", "e_gaze"}


def test_scene_aggregator_fuses_loud_sound_and_motion_to_safety() -> None:
    aggregator = SceneAggregator()
    loud = StableEvent(
        stable_event_id="s1",
        base_event_id="e_loud",
        trace_id="t1",
        event_type="loud_sound_detected",
        priority=EventPriority.P0,
        valid_until_monotonic=10_000_000.0,
        stabilized_by=["debounce"],
        payload={"event_confidence": 0.88},
    )
    motion = StableEvent(
        stable_event_id="s2",
        base_event_id="e_motion",
        trace_id="t1",
        event_type="motion_detected",
        priority=EventPriority.P3,
        valid_until_monotonic=10_000_001.0,
        stabilized_by=["debounce"],
        payload={"event_confidence": 0.7},
    )

    aggregator.aggregate(loud)
    scene = aggregator.aggregate(motion)
    assert scene.scene_type == "safety_alert_scene"
    assert set(scene.based_on_events) == {"e_loud", "e_motion"}


def test_scene_aggregator_caps_target_memory_growth() -> None:
    aggregator = SceneAggregator(max_targets=2)
    for index in range(3):
        event = StableEvent(
            stable_event_id=f"s{index}",
            base_event_id=f"e{index}",
            trace_id=f"t{index}",
            event_type="familiar_face_detected",
            priority=EventPriority.P2,
            valid_until_monotonic=10_000_000.0 + index,
            stabilized_by=["debounce"],
            payload={"target_id": f"user_{index}", "event_confidence": 0.8},
        )
        aggregator.aggregate(event)

    non_global_targets = [key for key in aggregator._memory if key != "__global__"]  # noqa: SLF001
    assert len(non_global_targets) == 2
    assert aggregator._target_evictions == 1  # noqa: SLF001


def test_resource_manager_exclusive() -> None:
    """Test exclusive resource allocation."""
    manager = ResourceManager()

    # First behavior gets exclusive resource
    grant1 = manager.request_grant(
        trace_id="trace_1",
        decision_id="decision_1",
        behavior_id="greeting",
        required_resources=["AudioOut"],
        optional_resources=[],
        priority=2,
        duration_ms=5000,
    )
    assert grant1.granted, "First behavior should get AudioOut"

    # Second behavior with lower priority should be denied
    grant2 = manager.request_grant(
        trace_id="trace_2",
        decision_id="decision_2",
        behavior_id="ambient",
        required_resources=["AudioOut"],
        optional_resources=[],
        priority=1,
        duration_ms=5000,
    )
    assert not grant2.granted, "Lower priority should be denied exclusive resource"

    # Higher priority behavior should preempt
    grant3 = manager.request_grant(
        trace_id="trace_3",
        decision_id="decision_3",
        behavior_id="alert",
        required_resources=["AudioOut"],
        optional_resources=[],
        priority=3,
        duration_ms=5000,
    )
    assert grant3.granted, "Higher priority should preempt exclusive resource"


def test_resource_manager_release_grant() -> None:
    """Releasing a grant should free owned resources immediately."""
    manager = ResourceManager()
    grant = manager.request_grant(
        trace_id="trace_1",
        decision_id="decision_1",
        behavior_id="greeting",
        required_resources=["AudioOut"],
        optional_resources=[],
        priority=3,
        duration_ms=5000,
    )
    assert grant.granted
    assert "P0" in manager.get_resource_status()["AudioOut"]

    manager.release_grant(grant.grant_id)
    assert manager.get_resource_status()["AudioOut"] == "free"


def test_resource_manager_shared_ownership_tracking() -> None:
    """Shared resources should track multiple owners and release independently."""
    manager = ResourceManager()
    grant1 = manager.request_grant(
        trace_id="trace_1",
        decision_id="decision_1",
        behavior_id="attention",
        required_resources=["HeadMotion"],
        optional_resources=[],
        priority=2,
        duration_ms=5000,
    )
    grant2 = manager.request_grant(
        trace_id="trace_2",
        decision_id="decision_2",
        behavior_id="tracking",
        required_resources=["HeadMotion"],
        optional_resources=[],
        priority=1,
        duration_ms=5000,
    )

    assert grant1.granted
    assert grant2.granted
    status = manager.get_resource_status()["HeadMotion"]
    assert status.startswith("shared_by_")
    assert "attention" in status
    assert "tracking" in status

    manager.release_grant(grant1.grant_id)
    status_after = manager.get_resource_status()["HeadMotion"]
    assert "attention" not in status_after
    assert "tracking" in status_after
