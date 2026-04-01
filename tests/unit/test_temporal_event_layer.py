from __future__ import annotations

from robot_life.common.schemas import EventPriority, StableEvent
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.temporal_event_layer import TemporalEventLayer


def _stable(event_type: str, *, target_id: str | None = None, raw_event_type: str | None = None) -> StableEvent:
    payload: dict[str, object] = {}
    if target_id is not None:
        payload["target_id"] = target_id
    if raw_event_type is not None:
        payload["raw_event_type"] = raw_event_type
    return StableEvent(
        stable_event_id=f"stable-{event_type}",
        base_event_id=f"base-{event_type}",
        trace_id=f"trace-{event_type}",
        event_type=event_type,
        priority=EventPriority.P2,
        valid_until_monotonic=10_000_000.0,
        stabilized_by=["debounce"],
        payload=payload,
    )


def test_temporal_event_layer_derives_gaze_hold_start_and_end() -> None:
    layer = TemporalEventLayer()

    first = layer.process(_stable("gaze_sustained_detected", target_id="person_track_001"))
    second = layer.process(_stable("gaze_away_detected", target_id="person_track_001"))

    assert [item.event_type for item in first] == [
        "gaze_sustained_detected",
        "gaze_hold_start_detected",
    ]
    assert [item.event_type for item in second] == [
        "gaze_away_detected",
        "gaze_hold_end_detected",
        "attention_lost_detected",
    ]


def test_temporal_event_layer_derives_wave_from_open_palm() -> None:
    layer = TemporalEventLayer()
    items = layer.process(
        _stable(
            "gesture_detected",
            target_id="person_track_001",
            raw_event_type="gesture_open_palm",
        )
    )
    assert [item.event_type for item in items] == [
        "gesture_detected",
        "wave_detected",
    ]


def test_scene_aggregator_understands_temporal_events() -> None:
    layer = TemporalEventLayer()
    aggregator = SceneAggregator()

    aggregator.aggregate(_stable("familiar_face_detected", target_id="person_track_001"))
    temporal_events = layer.process(_stable("gaze_sustained_detected", target_id="person_track_001"))
    scene = None
    for item in temporal_events:
        candidate = aggregator.aggregate(item)
        if candidate is not None:
            scene = candidate

    assert scene is not None
    assert scene.scene_type == "greeting_scene"
