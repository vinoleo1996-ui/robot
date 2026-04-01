from pathlib import Path

from robot_life.common.config import load_arbitration_config
from robot_life.common.contracts import EVENT_TYPES
from robot_life.common.schemas import DetectionResult, EventPriority
from robot_life.runtime.live_loop import _canonical_priority_key, resolve_event_priority


ROOT = Path(__file__).resolve().parents[2]


def _detection(event_type: str) -> DetectionResult:
    return DetectionResult.synthetic(
        detector="test",
        event_type=event_type,
        confidence=0.9,
        payload={},
    )


def test_priority_key_normalizes_detailed_gesture_events() -> None:
    assert _canonical_priority_key("gesture_open_palm") == "gesture_detected"


def test_priority_key_normalizes_gaze_aliases() -> None:
    assert _canonical_priority_key("gaze_hold") == "gaze_sustained_detected"
    assert _canonical_priority_key("gaze_sustained") == "gaze_sustained_detected"


def test_resolve_event_priority_prefers_configured_mapping() -> None:
    resolved = resolve_event_priority(
        _detection("motion"),
        {"motion_detected": EventPriority.P1},
    )
    assert resolved == EventPriority.P1


def test_resolve_event_priority_falls_back_to_builtin_heuristic() -> None:
    resolved = resolve_event_priority(_detection("loud_sound"), {})
    assert resolved == EventPriority.P0


def test_default_arbitration_config_covers_all_known_event_types() -> None:
    config = load_arbitration_config(ROOT / "configs" / "arbitration" / "default.yaml")
    assert EVENT_TYPES.issubset(set(config.event_priorities))
