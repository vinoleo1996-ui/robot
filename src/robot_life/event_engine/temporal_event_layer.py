from __future__ import annotations

from dataclasses import replace
from time import monotonic

from robot_life.common.payload_contracts import DetectionPayloadAccessor
from robot_life.common.schemas import StableEvent, new_id


class TemporalEventLayer:
    """Derive short-horizon temporal interaction events from stable detector events."""

    def __init__(
        self,
        *,
        gaze_hold_ttl_s: float = 2.5,
        attention_memory_ttl_s: float = 3.0,
    ) -> None:
        self.gaze_hold_ttl_s = max(0.5, float(gaze_hold_ttl_s))
        self.attention_memory_ttl_s = max(0.5, float(attention_memory_ttl_s))
        self._active_gaze_targets: dict[str, float] = {}
        self._active_attention_targets: dict[str, float] = {}

    def process(self, stable_event: StableEvent) -> list[StableEvent]:
        now = monotonic()
        self._prune(now)

        emitted = [stable_event]
        target_id = _target_id_from_payload(stable_event.payload)

        if stable_event.event_type in {"familiar_face_detected", "stranger_face_detected"} and target_id:
            self._active_attention_targets[target_id] = now

        if stable_event.event_type == "gaze_sustained_detected" and target_id:
            derived_type = "gaze_hold_start_detected"
            if target_id in self._active_gaze_targets:
                derived_type = "gaze_hold_active_detected"
            self._active_gaze_targets[target_id] = now
            self._active_attention_targets[target_id] = now
            emitted.append(self._derive(stable_event, event_type=derived_type, now=now))

        elif stable_event.event_type == "gaze_away_detected" and target_id:
            if target_id in self._active_gaze_targets:
                self._active_gaze_targets.pop(target_id, None)
                emitted.append(self._derive(stable_event, event_type="gaze_hold_end_detected", now=now))
                emitted.append(self._derive(stable_event, event_type="attention_lost_detected", now=now))

        elif stable_event.event_type == "gesture_detected":
            accessor = DetectionPayloadAccessor(stable_event.payload if isinstance(stable_event.payload, dict) else {})
            gesture_name = (accessor.gesture_name or "").strip().lower()
            raw_event_type = (accessor.raw_event_type or "").strip().lower()
            if (
                gesture_name in {"open_palm", "waving"}
                or raw_event_type in {"gesture_open_palm", "gesture_waving"}
                or "wave" in raw_event_type
            ):
                emitted.append(self._derive(stable_event, event_type="wave_detected", now=now))

        return emitted

    def snapshot(self) -> dict[str, object]:
        now = monotonic()
        self._prune(now)
        return {
            "active_gaze_targets": sorted(self._active_gaze_targets.keys()),
            "active_attention_targets": sorted(self._active_attention_targets.keys()),
        }

    def _prune(self, now: float) -> None:
        stale_gaze = [
            target_id
            for target_id, seen_at in self._active_gaze_targets.items()
            if (now - seen_at) > self.gaze_hold_ttl_s
        ]
        for target_id in stale_gaze:
            self._active_gaze_targets.pop(target_id, None)

        stale_attention = [
            target_id
            for target_id, seen_at in self._active_attention_targets.items()
            if (now - seen_at) > self.attention_memory_ttl_s
        ]
        for target_id in stale_attention:
            self._active_attention_targets.pop(target_id, None)

    @staticmethod
    def _derive(stable_event: StableEvent, *, event_type: str, now: float) -> StableEvent:
        payload = dict(stable_event.payload)
        payload["derived_from_event_type"] = stable_event.event_type
        payload["derived_temporal_event"] = event_type
        return replace(
            stable_event,
            stable_event_id=new_id(),
            event_type=event_type,
            valid_until_monotonic=max(stable_event.valid_until_monotonic, now + 0.8),
            stabilized_by=list(stable_event.stabilized_by) + ["temporal_event_layer"],
            payload=payload,
        )


def _target_id_from_payload(payload: dict) -> str | None:
    return DetectionPayloadAccessor(payload).target_id
