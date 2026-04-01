from __future__ import annotations
from robot_life.common.contracts import canonical_event_detected, default_event_priority
from robot_life.common.payload_contracts import DetectionPayloadAccessor
from robot_life.common.schemas import DetectionResult, EventPriority, RawEvent, new_id, now_mono


class EventBuilder:
    """Convert detector outputs into normalized raw events.

    When ``event_priorities`` is provided, the builder automatically
    resolves the priority from the event type, eliminating the need
    for callers to hardcode it.
    """

    def __init__(
        self,
        event_priorities: dict[str, EventPriority] | None = None,
    ) -> None:
        self.event_priorities: dict[str, EventPriority] = dict(event_priorities or {})

    def build(
        self,
        detection: DetectionResult,
        priority: EventPriority | None = None,
        ttl_ms: int = 3_000,
    ) -> RawEvent:
        canonical_event_type = self._canonical_event_type(detection.event_type)
        canonical_detected_type = f"{canonical_event_type}_detected"

        # Auto-resolve priority from mapping if not explicitly passed.
        resolved_priority = priority
        if resolved_priority is None:
            resolved_priority = self.event_priorities.get(canonical_detected_type)
        if resolved_priority is None:
            resolved_priority = self.event_priorities.get(canonical_event_type)
        if resolved_priority is None:
            resolved_priority = default_event_priority(canonical_detected_type)

        accessor = DetectionPayloadAccessor.from_detection(detection)
        cooldown_target = accessor.target_id or canonical_event_type
        payload = accessor.to_dict()
        payload.setdefault("event_confidence", detection.confidence)
        payload.setdefault("raw_event_type", detection.event_type)

        return RawEvent(
            event_id=new_id(),
            trace_id=detection.trace_id,
            event_type=f"{canonical_event_type}_detected",
            priority=resolved_priority,
            timestamp_monotonic=now_mono(),
            confidence=detection.confidence,
            source=detection.detector,
            ttl_ms=ttl_ms,
            cooldown_key=f"{canonical_event_type}:{cooldown_target}",
            payload=payload,
        )

    @staticmethod
    def _canonical_event_type(event_type: str) -> str:
        """Normalize detector-level event names into canonical pipeline events."""
        normalized = canonical_event_detected(event_type)
        return normalized.removesuffix("_detected")
