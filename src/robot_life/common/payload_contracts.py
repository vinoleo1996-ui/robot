from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping


PayloadMapping = Mapping[str, Any]
MutablePayloadMapping = MutableMapping[str, Any]


def _as_mutable_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return dict(payload)
    if isinstance(payload, Mapping):
        return {str(key): value for key, value in payload.items()}
    return {}


def _normalized_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalized_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class DetectionPayloadAccessor:
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_detection(cls, detection: Any) -> "DetectionPayloadAccessor":
        return cls(_as_mutable_payload(getattr(detection, "payload", None)))

    @property
    def target_id(self) -> str | None:
        return _normalized_str(self.payload.get("target_id"))

    @property
    def identity_target_id(self) -> str | None:
        return _normalized_str(self.payload.get("identity_target_id"))

    @property
    def gesture_name(self) -> str | None:
        return _normalized_str(self.payload.get("gesture_name"))

    @property
    def raw_event_type(self) -> str | None:
        return _normalized_str(self.payload.get("raw_event_type"))

    @property
    def event_confidence(self) -> float | None:
        return _normalized_float(self.payload.get("event_confidence"))

    @property
    def priority(self) -> str | None:
        return _normalized_str(self.payload.get("priority"))

    @property
    def bbox(self) -> Any:
        return self.payload.get("bbox")

    @property
    def hand_bbox(self) -> Any:
        return self.payload.get("hand_bbox")

    @property
    def motion_boxes(self) -> Any:
        return self.payload.get("motion_boxes")

    def setdefault(self, key: str, value: Any) -> Any:
        return self.payload.setdefault(key, value)

    def apply_ingestion_defaults(
        self,
        *,
        frame_seq: int,
        collected_at: float,
        ingested_at: float,
        source_latency_ms: float,
        camera_frame_seq: int | None,
        frame_shape: tuple[int, int] | None,
    ) -> dict[str, Any]:
        self.payload.setdefault("frame_seq", int(frame_seq))
        self.payload.setdefault("frame_collected_at", float(collected_at))
        self.payload.setdefault("detection_ingested_at", float(ingested_at))
        self.payload.setdefault("source_latency_ms", round(max(0.0, float(source_latency_ms)), 3))
        if camera_frame_seq is not None:
            self.payload.setdefault("camera_frame_seq", int(camera_frame_seq))
        if frame_shape is not None:
            self.payload.setdefault("frame_height", int(frame_shape[0]))
            self.payload.setdefault("frame_width", int(frame_shape[1]))
        return self.payload

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


@dataclass
class ScenePayloadAccessor:
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_scene(cls, scene: Any) -> "ScenePayloadAccessor":
        return cls(_as_mutable_payload(getattr(scene, "payload", None)))

    @property
    def target_id(self) -> str | None:
        return _normalized_str(self.payload.get("target_id"))

    @property
    def primary_target_id(self) -> str | None:
        return _normalized_str(self.payload.get("primary_target_id"))

    @property
    def interaction_episode_id(self) -> str | None:
        return _normalized_str(self.payload.get("interaction_episode_id"))

    @property
    def scene_epoch(self) -> str | None:
        return _normalized_str(self.payload.get("scene_epoch"))

    @property
    def interaction_state(self) -> str | None:
        raw = _normalized_str(self.payload.get("interaction_state"))
        return raw.lower() if raw is not None else None

    @property
    def scene_path(self) -> str | None:
        raw = _normalized_str(self.payload.get("scene_path"))
        return raw.lower() if raw is not None else None

    @property
    def engagement_score(self) -> float | None:
        return _normalized_float(self.payload.get("engagement_score"))

    @property
    def involved_targets(self) -> list[str]:
        raw = self.payload.get("involved_targets")
        if not isinstance(raw, list):
            return []
        return [value for item in raw if (value := _normalized_str(item)) is not None]

    @property
    def related_entity_ids(self) -> list[str]:
        raw = self.payload.get("related_entity_ids")
        if not isinstance(raw, list):
            return []
        return [value for item in raw if (value := _normalized_str(item)) is not None]

    @property
    def robot_mode(self) -> str | None:
        return _normalized_str(self.payload.get("robot_mode"))

    @property
    def robot_do_not_disturb(self) -> bool:
        return bool(self.payload.get("robot_do_not_disturb"))

    @property
    def source_frame_seq(self) -> int | None:
        raw = self.payload.get("source_frame_seq")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def source_collected_at(self) -> float | None:
        return _normalized_float(self.payload.get("source_collected_at"))

    @property
    def interaction_intent(self) -> str | None:
        return _normalized_str(self.payload.get("interaction_intent"))

    @property
    def signal_breakdown(self) -> dict[str, list[str]]:
        raw = self.payload.get("signal_breakdown")
        if not isinstance(raw, Mapping):
            return {
                "entity": self._normalized_list(self.payload.get("entity_signals")),
                "relation": self._normalized_list(self.payload.get("relation_signals")),
                "event": self._normalized_list(self.payload.get("event_signals")),
                "context": self._normalized_list(self.payload.get("context_signals")),
            }
        return {
            "entity": self._normalized_list(raw.get("entity")),
            "relation": self._normalized_list(raw.get("relation")),
            "event": self._normalized_list(raw.get("event")),
            "context": self._normalized_list(raw.get("context")),
        }

    def setdefault(self, key: str, value: Any) -> Any:
        return self.payload.setdefault(key, value)

    def ensure_defaults(
        self,
        *,
        primary_target_id: str | None,
        related_entity_ids: list[str],
        interaction_episode_id: str | None,
        scene_epoch: str,
        source_frame_seq: int,
        source_collected_at: float,
        priority: str,
        robot_mode: Any,
        robot_do_not_disturb: Any,
        robot_busy: bool,
        robot_active_behavior_id: str | None,
        robot_current_target_id: Any,
        interaction_intent: str,
    ) -> dict[str, Any]:
        self.payload.setdefault("primary_target_id", primary_target_id)
        self.payload.setdefault("related_entity_ids", list(related_entity_ids))
        self.payload.setdefault("interaction_episode_id", interaction_episode_id)
        self.payload.setdefault("scene_epoch", scene_epoch)
        self.payload.setdefault("source_frame_seq", int(source_frame_seq))
        self.payload.setdefault("source_collected_at", float(source_collected_at))
        self.payload.setdefault("priority", priority)
        self.payload.setdefault("robot_mode", robot_mode)
        self.payload.setdefault("robot_do_not_disturb", robot_do_not_disturb)
        self.payload.setdefault("robot_busy", bool(robot_busy))
        self.payload.setdefault("robot_active_behavior_id", robot_active_behavior_id)
        self.payload.setdefault("robot_current_target_id", robot_current_target_id)
        self.payload.setdefault("interaction_intent", interaction_intent)
        self.payload.setdefault("signal_breakdown", self.signal_breakdown)
        return self.payload

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    @staticmethod
    def _normalized_list(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [value for item in raw if (value := _normalized_str(item)) is not None]


@dataclass(frozen=True)
class ArbitrationTracePayload:
    target_behavior: str
    priority: str
    mode: str | None = None
    reason: str | None = None
    queue_pending: int | None = None
    interaction_episode_id: str | None = None
    scene_epoch: str | None = None
    decision_epoch: str | None = None

    @classmethod
    def from_decision(cls, decision: Any, *, queue_pending: int | None = None) -> "ArbitrationTracePayload":
        mode = getattr(decision, "mode", None)
        mode_value = getattr(mode, "value", mode)
        priority = getattr(getattr(decision, "priority", None), "value", getattr(decision, "priority", None))
        return cls(
            target_behavior=str(getattr(decision, "target_behavior", "")),
            priority=str(priority or ""),
            mode=str(mode_value) if mode_value is not None else None,
            reason=_normalized_str(getattr(decision, "reason", None)),
            queue_pending=queue_pending,
            interaction_episode_id=_normalized_str(getattr(decision, "interaction_episode_id", None)),
            scene_epoch=_normalized_str(getattr(decision, "scene_epoch", None)),
            decision_epoch=_normalized_str(getattr(decision, "decision_epoch", None)),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target_behavior": self.target_behavior,
            "priority": self.priority,
        }
        if self.mode is not None:
            payload["mode"] = self.mode
        if self.reason is not None:
            payload["reason"] = self.reason
        if self.queue_pending is not None:
            payload["queue_pending"] = int(self.queue_pending)
        if self.interaction_episode_id is not None:
            payload["interaction_episode_id"] = self.interaction_episode_id
        if self.scene_epoch is not None:
            payload["scene_epoch"] = self.scene_epoch
        if self.decision_epoch is not None:
            payload["decision_epoch"] = self.decision_epoch
        return payload


@dataclass(frozen=True)
class SlowTaskMetadata:
    frame_index: int | None = None
    source_frame_seq: int | None = None
    source_collected_at: float | None = None
    interaction_episode_id: str | None = None
    scene_epoch: str | None = None
    primary_target_id: str | None = None
    related_entity_ids: tuple[str, ...] = ()
    interaction_intent: str | None = None
    decision_mode: str | None = None
    arbitration_outcome: str | None = None
    request_kind: str = "slow_scene"

    @classmethod
    def from_scene_and_collected(
        cls,
        scene: Any,
        collected: Any,
        *,
        decision_mode: Any | None = None,
        arbitration_outcome: str | None = None,
    ) -> "SlowTaskMetadata":
        accessor = ScenePayloadAccessor.from_scene(scene)
        packets = getattr(collected, "packets", {}) or {}
        camera_packet = packets.get("camera") if isinstance(packets, Mapping) else None
        mode_value = getattr(decision_mode, "value", decision_mode)
        return cls(
            frame_index=getattr(camera_packet, "frame_index", None),
            source_frame_seq=getattr(collected, "frame_seq", None) or accessor.source_frame_seq,
            source_collected_at=getattr(collected, "collected_at", None) or accessor.source_collected_at,
            interaction_episode_id=scene.interaction_episode_id or accessor.interaction_episode_id,
            scene_epoch=scene.scene_epoch or accessor.scene_epoch,
            primary_target_id=scene.primary_target_id or accessor.primary_target_id or scene.target_id or accessor.target_id,
            related_entity_ids=tuple(scene.related_entity_ids or accessor.related_entity_ids),
            interaction_intent=accessor.interaction_intent,
            decision_mode=_normalized_str(mode_value),
            arbitration_outcome=_normalized_str(arbitration_outcome),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "request_kind": self.request_kind,
            "related_entity_ids": list(self.related_entity_ids),
        }
        if self.frame_index is not None:
            payload["frame_index"] = int(self.frame_index)
        if self.source_frame_seq is not None:
            payload["source_frame_seq"] = int(self.source_frame_seq)
        if self.source_collected_at is not None:
            payload["source_collected_at"] = float(self.source_collected_at)
        if self.interaction_episode_id is not None:
            payload["interaction_episode_id"] = self.interaction_episode_id
        if self.scene_epoch is not None:
            payload["scene_epoch"] = self.scene_epoch
        if self.primary_target_id is not None:
            payload["primary_target_id"] = self.primary_target_id
        if self.interaction_intent is not None:
            payload["interaction_intent"] = self.interaction_intent
        if self.decision_mode is not None:
            payload["decision_mode"] = self.decision_mode
        if self.arbitration_outcome is not None:
            payload["arbitration_outcome"] = self.arbitration_outcome
        return payload
