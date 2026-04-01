from pathlib import Path

from robot_life.common.config import (
    StabilizerConfig,
    StabilizerEventOverride,
    load_stabilizer_config,
)
from robot_life.common.schemas import DetectionResult, EventPriority
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.stabilizer import EventStabilizer

ROOT = Path(__file__).resolve().parents[2]


def test_load_stabilizer_config_with_event_overrides() -> None:
    config = load_stabilizer_config(ROOT / "configs" / "stabilizer" / "default.yaml")
    assert config.debounce_count == 2
    assert config.dedup_window_ms == 500
    assert config.event_overrides["familiar_face_detected"].debounce_count == 3
    assert config.event_overrides["gaze_sustained_detected"].ttl_ms == 2000
    assert config.event_overrides["motion_detected"].debounce_count == 1


def test_event_override_applies_debounce_count() -> None:
    config = load_stabilizer_config(ROOT / "configs" / "stabilizer" / "default.yaml")
    stabilizer = EventStabilizer.from_config(config)
    builder = EventBuilder()

    face_detection = DetectionResult.synthetic(
        detector="face",
        event_type="familiar_face",
        confidence=0.92,
        payload={"target_id": "user_1"},
    )
    motion_detection = DetectionResult.synthetic(
        detector="motion",
        event_type="motion",
        confidence=0.9,
        payload={"target_id": "zone_1"},
    )

    assert stabilizer.process(builder.build(face_detection, priority=EventPriority.P2)) is None
    assert stabilizer.process(builder.build(face_detection, priority=EventPriority.P2)) is None
    assert stabilizer.process(builder.build(face_detection, priority=EventPriority.P2)) is not None

    assert stabilizer.process(builder.build(motion_detection, priority=EventPriority.P3)) is not None


def test_event_override_ttl_and_dedup_windows() -> None:
    config = StabilizerConfig(
        debounce_count=1,
        cooldown_ms=0,
        dedup_window_ms=500,
        hysteresis_threshold=0.0,
        event_overrides={
            "gesture_detected": StabilizerEventOverride(ttl_ms=1, dedup_window_ms=0),
        },
    )
    stabilizer = EventStabilizer.from_config(config)
    builder = EventBuilder()
    detection = DetectionResult.synthetic(
        detector="gesture",
        event_type="gesture_open_palm",
        confidence=0.9,
        payload={"target_id": "user_1"},
    )

    expired = builder.build(detection, priority=EventPriority.P1)
    expired.timestamp_monotonic -= 0.01
    assert stabilizer.process(expired) is None

    first = stabilizer.process(builder.build(detection, priority=EventPriority.P1))
    second = stabilizer.process(builder.build(detection, priority=EventPriority.P1))
    assert first is not None
    assert second is not None


def test_local_fast_reaction_stabilizer_is_distinct_from_4090() -> None:
    local_config = load_stabilizer_config(
        ROOT / "configs" / "stabilizer" / "local" / "local_mac_fast_reaction.yaml"
    )
    desktop_config = load_stabilizer_config(ROOT / "configs" / "stabilizer" / "desktop_4090_stable.yaml")

    assert local_config.debounce_count == 2
    assert local_config.cooldown_ms == 900
    assert local_config.event_overrides["motion_detected"].debounce_count == 2
    assert local_config.event_overrides["familiar_face_detected"].cooldown_ms == 1800
    assert local_config.event_overrides["gesture_detected"].debounce_count == 3
    assert local_config.event_overrides["gesture_detected"].cooldown_ms == 2200
    assert local_config.event_overrides["gesture_detected"].hysteresis_threshold == 0.68
    assert local_config != desktop_config


def test_stabilizer_runtime_override_update_is_applied() -> None:
    stabilizer = EventStabilizer(
        debounce_count=1,
        cooldown_ms=0,
        hysteresis_threshold=0.5,
        dedup_window_ms=0,
    )

    applied = stabilizer.update_event_override(
        "gesture_detected",
        cooldown_ms=2100,
        debounce_count=3,
        hysteresis_threshold=0.77,
    )
    snapshot = stabilizer.snapshot_config()

    assert applied["cooldown_ms"] == 2100
    assert applied["debounce_count"] == 3
    assert applied["hysteresis_threshold"] == 0.77
    assert snapshot["event_overrides"]["gesture_detected"]["cooldown_ms"] == 2100
