from robot_life.common.contracts import (
    BEHAVIOR_IDS,
    DEFAULT_EVENT_PRIORITIES,
    EVENT_TYPES,
    SCENE_STRANGER_ATTENTION,
    SCENE_TYPES,
    canonical_event_detected,
    default_event_priority,
    is_known_behavior_id,
    is_known_event_type,
    is_known_scene_type,
    priority_rank,
)
from robot_life.common.schemas import EventPriority, StableEvent
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator


def test_contract_sets_are_non_empty() -> None:
    assert EVENT_TYPES
    assert SCENE_TYPES
    assert BEHAVIOR_IDS
    assert DEFAULT_EVENT_PRIORITIES


def test_contract_helpers() -> None:
    assert is_known_event_type("gesture_detected")
    assert not is_known_event_type("unknown_event")
    assert is_known_scene_type("greeting_scene")
    assert not is_known_scene_type("unknown_scene")
    assert is_known_behavior_id("perform_greeting")
    assert not is_known_behavior_id("perform_unknown")


def test_contract_priority_helpers_are_canonical() -> None:
    assert canonical_event_detected("gesture_open_palm") == "gesture_detected"
    assert canonical_event_detected("gaze_hold") == "gaze_sustained_detected"
    assert default_event_priority("familiar_face") == EventPriority.P1
    assert default_event_priority("familiar_face_detected") == EventPriority.P1
    assert priority_rank(EventPriority.P0) < priority_rank(EventPriority.P2)


def test_aggregator_produces_known_scene_types() -> None:
    scene = SceneAggregator().aggregate(
        StableEvent(
            stable_event_id="s1",
            base_event_id="e1",
            trace_id="t1",
            event_type="familiar_face_detected",
            priority=EventPriority.P2,
            valid_until_monotonic=1.0,
            stabilized_by=["debounce"],
            payload={},
        )
    )
    assert scene.scene_type in SCENE_TYPES


def test_aggregator_emits_stranger_attention_scene_for_stranger_signals() -> None:
    aggregator = SceneAggregator()
    stranger_scene = aggregator.aggregate(
        StableEvent(
            stable_event_id="s-stranger",
            base_event_id="e-stranger",
            trace_id="t-stranger",
            event_type="stranger_face_detected",
            priority=EventPriority.P2,
            valid_until_monotonic=1.0,
            stabilized_by=["debounce"],
            payload={"target_id": "user-1"},
        )
    )
    assert stranger_scene is not None
    assert stranger_scene.scene_type == SCENE_STRANGER_ATTENTION


def test_aggregator_annotates_interaction_context_and_downgrades_single_familiar_face() -> None:
    aggregator = SceneAggregator()
    scene = aggregator.aggregate(
        StableEvent(
            stable_event_id="s-familiar",
            base_event_id="e-familiar",
            trace_id="t-familiar",
            event_type="familiar_face_detected",
            priority=EventPriority.P1,
            valid_until_monotonic=1.0,
            stabilized_by=["debounce"],
            payload={"target_id": "user-42"},
        )
    )
    assert scene is not None
    assert scene.scene_type == "attention_scene"
    assert scene.payload["scene_path"] == "social"
    assert scene.payload["interaction_state"] == "noticed_human"
    assert scene.payload["engagement_score"] > 0.0


def test_arbitrator_produces_known_behavior_ids() -> None:
    decision = Arbitrator().decide(
        type("Scene", (), {"scene_type": "greeting_scene", "trace_id": "trace_1"})()
    )
    assert decision.target_behavior in BEHAVIOR_IDS


def test_event_builder_default_priority_matches_contract_default() -> None:
    detection = type(
        "Detection",
        (),
        {
            "trace_id": "t1",
            "event_type": "familiar_face",
            "payload": {},
            "confidence": 0.95,
            "detector": "test",
        },
    )()
    raw_event = EventBuilder().build(detection)
    assert raw_event.event_type == "familiar_face_detected"
    assert raw_event.priority == EventPriority.P1
