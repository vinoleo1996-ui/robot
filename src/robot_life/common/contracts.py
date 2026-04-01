from __future__ import annotations

from typing import Final

from robot_life.common.schemas import EventPriority


# Canonical event identifiers after event-engine normalization.
EVENT_FAMILIAR_FACE_DETECTED: Final[str] = "familiar_face_detected"
EVENT_STRANGER_FACE_DETECTED: Final[str] = "stranger_face_detected"
EVENT_GESTURE_DETECTED: Final[str] = "gesture_detected"
EVENT_GAZE_SUSTAINED_DETECTED: Final[str] = "gaze_sustained_detected"
EVENT_LOUD_SOUND_DETECTED: Final[str] = "loud_sound_detected"
EVENT_COLLISION_WARNING_DETECTED: Final[str] = "collision_warning_detected"
EVENT_EMERGENCY_STOP_DETECTED: Final[str] = "emergency_stop_detected"
EVENT_MOTION_DETECTED: Final[str] = "motion_detected"

EVENT_TYPES: Final[set[str]] = {
    EVENT_FAMILIAR_FACE_DETECTED,
    EVENT_STRANGER_FACE_DETECTED,
    EVENT_GESTURE_DETECTED,
    EVENT_GAZE_SUSTAINED_DETECTED,
    EVENT_LOUD_SOUND_DETECTED,
    EVENT_COLLISION_WARNING_DETECTED,
    EVENT_EMERGENCY_STOP_DETECTED,
    EVENT_MOTION_DETECTED,
}

DEFAULT_EVENT_PRIORITIES: Final[dict[str, EventPriority]] = {
    EVENT_COLLISION_WARNING_DETECTED: EventPriority.P0,
    EVENT_EMERGENCY_STOP_DETECTED: EventPriority.P0,
    EVENT_LOUD_SOUND_DETECTED: EventPriority.P0,
    EVENT_FAMILIAR_FACE_DETECTED: EventPriority.P1,
    EVENT_GESTURE_DETECTED: EventPriority.P1,
    EVENT_STRANGER_FACE_DETECTED: EventPriority.P2,
    EVENT_GAZE_SUSTAINED_DETECTED: EventPriority.P2,
    EVENT_MOTION_DETECTED: EventPriority.P3,
}

# Canonical scene identifiers produced by scene aggregation.
SCENE_GREETING: Final[str] = "greeting_scene"
SCENE_ATTENTION: Final[str] = "attention_scene"
SCENE_STRANGER_ATTENTION: Final[str] = "stranger_attention_scene"
SCENE_SAFETY_ALERT: Final[str] = "safety_alert_scene"
SCENE_GESTURE_BOND: Final[str] = "gesture_bond_scene"
SCENE_AMBIENT_TRACKING: Final[str] = "ambient_tracking_scene"

SCENE_TYPES: Final[set[str]] = {
    SCENE_GREETING,
    SCENE_ATTENTION,
    SCENE_STRANGER_ATTENTION,
    SCENE_SAFETY_ALERT,
    SCENE_GESTURE_BOND,
    SCENE_AMBIENT_TRACKING,
}

# Canonical behavior identifiers dispatched by arbitrator.
BEHAVIOR_PERFORM_GREETING: Final[str] = "perform_greeting"
BEHAVIOR_GREETING_VISUAL_ONLY: Final[str] = "greeting_visual_only"
BEHAVIOR_PERFORM_ATTENTION: Final[str] = "perform_attention"
BEHAVIOR_ATTENTION_MINIMAL: Final[str] = "attention_minimal"
BEHAVIOR_PERFORM_GESTURE_RESPONSE: Final[str] = "perform_gesture_response"
BEHAVIOR_GESTURE_VISUAL_ONLY: Final[str] = "gesture_visual_only"
BEHAVIOR_PERFORM_SAFETY_ALERT: Final[str] = "perform_safety_alert"
BEHAVIOR_PERFORM_TRACKING: Final[str] = "perform_tracking"

BEHAVIOR_IDS: Final[set[str]] = {
    BEHAVIOR_PERFORM_GREETING,
    BEHAVIOR_GREETING_VISUAL_ONLY,
    BEHAVIOR_PERFORM_ATTENTION,
    BEHAVIOR_ATTENTION_MINIMAL,
    BEHAVIOR_PERFORM_GESTURE_RESPONSE,
    BEHAVIOR_GESTURE_VISUAL_ONLY,
    BEHAVIOR_PERFORM_SAFETY_ALERT,
    BEHAVIOR_PERFORM_TRACKING,
}


def is_known_event_type(event_type: str) -> bool:
    return event_type in EVENT_TYPES


def is_known_scene_type(scene_type: str) -> bool:
    return scene_type in SCENE_TYPES


def is_known_behavior_id(behavior_id: str) -> bool:
    return behavior_id in BEHAVIOR_IDS


def canonical_event_detected(event_type: str) -> str:
    normalized = str(event_type or "").strip().lower().removesuffix("_detected")
    if normalized.startswith("gesture_") or normalized in {"hand_wave", "wave"}:
        return EVENT_GESTURE_DETECTED
    if normalized in {"gaze_hold", "gaze_sustained", "gaze_fixation"}:
        return EVENT_GAZE_SUSTAINED_DETECTED
    return f"{normalized}_detected" if normalized else ""


def default_event_priority(event_type: str) -> EventPriority:
    return DEFAULT_EVENT_PRIORITIES.get(canonical_event_detected(event_type), EventPriority.P2)


def priority_rank(priority: EventPriority) -> int:
    """Shared priority ranking: P0=0 (highest) to P3=3 (lowest).

    This is the single source of truth for priority ordering,
    replacing duplicate implementations in arbitrator, live_loop,
    arbitration_runtime, and safety_guard.
    """
    return {
        EventPriority.P0: 0,
        EventPriority.P1: 1,
        EventPriority.P2: 2,
        EventPriority.P3: 3,
    }.get(priority, 99)
