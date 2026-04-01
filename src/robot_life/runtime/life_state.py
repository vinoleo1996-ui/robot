from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from robot_life.common.payload_contracts import DetectionPayloadAccessor, ScenePayloadAccessor
from robot_life.common.schemas import EventPriority

SOCIAL_BEHAVIORS = {
    "perform_greeting",
    "greeting_visual_only",
    "perform_attention",
    "attention_minimal",
    "perform_gesture_response",
    "gesture_visual_only",
}
NOTICE_EVENTS = {"familiar_face_detected", "stranger_face_detected", "motion_detected"}
MUTUAL_EVENTS = {"gaze_hold_start_detected", "gaze_sustained_detected"}
ENGAGEMENT_EVENTS = {"wave_detected", "gesture_detected"}
SAFETY_SCENES = {"safety_alert_scene"}
ATTENTION_SCENES = {"attention_scene", "stranger_attention_scene"}
ENGAGEMENT_SCENES = {"greeting_scene", "gesture_bond_scene"}
NOTICED_SCENES = {"ambient_tracking_scene", "attention_scene", "stranger_attention_scene"}


@dataclass
class LifeStateSnapshot:
    latest_scene: Any | None
    latest_scene_payload: dict[str, Any]
    latest_interaction_state: str
    latest_scene_path: str
    latest_target_id: str | None
    latest_engagement_score: Any
    stable_event_types: set[str]
    social_execution: Any | None
    noticed_target_id: str | None
    mutual_target_id: str | None
    engagement_target_id: str | None
    has_p0_event: bool
    has_safety_scene: bool
    has_attention_lost: bool
    has_engagement_scene: bool
    has_mutual_attention_signal: bool
    has_notice_signal: bool


def latest_target_id_from_events(events: list[Any], *, preferred_event_types: set[str]) -> str | None:
    for event in reversed(events):
        if getattr(event, "event_type", None) not in preferred_event_types:
            continue
        payload = getattr(event, "payload", None)
        accessor = DetectionPayloadAccessor(payload if isinstance(payload, dict) else {})
        if accessor.target_id:
            return accessor.target_id
    return None


def build_life_state_snapshot(result: Any) -> LifeStateSnapshot:
    latest_scene = result.scene_candidates[-1] if result.scene_candidates else None
    latest_scene_payload = latest_scene.payload if latest_scene is not None and isinstance(latest_scene.payload, dict) else {}
    latest_scene_accessor = ScenePayloadAccessor(latest_scene_payload)
    latest_interaction_state = latest_scene_accessor.interaction_state or ""
    latest_scene_path = latest_scene_accessor.scene_path or ""
    latest_target_id = getattr(latest_scene, "target_id", None) if latest_scene is not None else None
    latest_engagement_score = latest_scene_accessor.engagement_score
    stable_event_types = {event.event_type for event in result.stable_events}
    social_execution = next((execution for execution in result.execution_results if execution.behavior_id in SOCIAL_BEHAVIORS), None)
    noticed_target_id = latest_target_id_from_events(result.stable_events, preferred_event_types=NOTICE_EVENTS) or latest_target_id
    mutual_target_id = latest_target_id_from_events(result.stable_events, preferred_event_types=MUTUAL_EVENTS) or latest_target_id
    engagement_target_id = latest_target_id_from_events(result.stable_events, preferred_event_types=ENGAGEMENT_EVENTS) or latest_target_id
    has_p0_event = any(event.priority == EventPriority.P0 for event in result.stable_events)
    has_safety_scene = any(scene.scene_type in SAFETY_SCENES for scene in result.scene_candidates)
    has_attention_lost = "attention_lost_detected" in stable_event_types or "gaze_hold_end_detected" in stable_event_types
    has_engagement_scene = any(scene.scene_type in ENGAGEMENT_SCENES for scene in result.scene_candidates) or "wave_detected" in stable_event_types
    has_mutual_attention_signal = (
        latest_interaction_state in {"engaging", "mutual_attention"}
        or any(scene.scene_type in ATTENTION_SCENES for scene in result.scene_candidates)
        or bool(MUTUAL_EVENTS & stable_event_types)
    )
    has_notice_signal = (
        any(scene.scene_type in NOTICED_SCENES for scene in result.scene_candidates)
        or bool(NOTICE_EVENTS & stable_event_types)
    )
    return LifeStateSnapshot(
        latest_scene=latest_scene,
        latest_scene_payload=latest_scene_payload,
        latest_interaction_state=latest_interaction_state,
        latest_scene_path=latest_scene_path,
        latest_target_id=latest_target_id,
        latest_engagement_score=latest_engagement_score,
        stable_event_types=stable_event_types,
        social_execution=social_execution,
        noticed_target_id=noticed_target_id,
        mutual_target_id=mutual_target_id,
        engagement_target_id=engagement_target_id,
        has_p0_event=has_p0_event,
        has_safety_scene=has_safety_scene,
        has_attention_lost=has_attention_lost,
        has_engagement_scene=has_engagement_scene,
        has_mutual_attention_signal=has_mutual_attention_signal,
        has_notice_signal=has_notice_signal,
    )
