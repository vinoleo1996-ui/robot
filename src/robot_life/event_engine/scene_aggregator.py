from __future__ import annotations

from dataclasses import dataclass

from robot_life.common.contracts import (
    EVENT_COLLISION_WARNING_DETECTED,
    EVENT_EMERGENCY_STOP_DETECTED,
    EVENT_FAMILIAR_FACE_DETECTED,
    EVENT_GAZE_SUSTAINED_DETECTED,
    EVENT_GESTURE_DETECTED,
    EVENT_LOUD_SOUND_DETECTED,
    EVENT_MOTION_DETECTED,
    EVENT_STRANGER_FACE_DETECTED,
    SCENE_AMBIENT_TRACKING,
    SCENE_ATTENTION,
    SCENE_GESTURE_BOND,
    SCENE_GREETING,
    SCENE_SAFETY_ALERT,
    SCENE_STRANGER_ATTENTION,
)
from robot_life.common.payload_contracts import DetectionPayloadAccessor
from robot_life.common.schemas import EventPriority, SceneCandidate, StableEvent, new_id, now_mono


PRIORITY_BIAS = {
    EventPriority.P0: 0.25,
    EventPriority.P1: 0.15,
    EventPriority.P2: 0.08,
    EventPriority.P3: 0.0,
}

GLOBAL_TARGET = "__global__"


@dataclass
class _Signal:
    event_type: str
    base_event_id: str
    score: float
    priority: EventPriority
    observed_at: float
    valid_until: float
    payload: dict


@dataclass(frozen=True)
class _InteractionContext:
    scene_path: str
    interaction_state: str
    engagement_score: float
    entity_signals: list[str]
    relation_signals: list[str]
    event_signals: list[str]
    context_signals: list[str]


class SceneAggregator:
    """Lift stable events into fused scene candidates using short-term signal memory.

    Returns None when a single weak signal is insufficient to form
    a meaningful scene candidate, reducing false triggers.
    """

    def __init__(
        self,
        memory_window_s: float = 3.0,
        min_single_signal_score: float = 0.45,
        max_targets: int = 128,
    ) -> None:
        self.memory_window_s = max(0.5, float(memory_window_s))
        self.min_single_signal_score = float(min_single_signal_score)
        self.max_targets = max(1, int(max_targets))
        self._memory: dict[str, dict[str, _Signal]] = {}
        self._target_evictions = 0

    def aggregate(self, stable_event: StableEvent) -> SceneCandidate | None:
        """Aggregate a stable event into a scene candidate.

        Returns ``None`` when a single weak signal is insufficient to form
        a meaningful scene — this prevents false triggers from isolated
        low-confidence detections.
        """
        now = now_mono()
        target_id = _resolve_target(stable_event.payload)
        target_key = target_id or GLOBAL_TARGET
        self._prune(now)

        signal_valid_until = stable_event.valid_until_monotonic
        if signal_valid_until <= now:
            signal_valid_until = now + 1.0

        signal = _Signal(
            event_type=stable_event.event_type,
            base_event_id=stable_event.base_event_id,
            score=self._compute_score_hint(stable_event),
            priority=stable_event.priority,
            observed_at=now,
            valid_until=signal_valid_until,
            payload=dict(stable_event.payload),
        )
        self._memory.setdefault(target_key, {})[stable_event.event_type] = signal
        self._enforce_target_limit(current_target_key=target_key)

        if stable_event.event_type in {"gaze_hold_end_detected", "attention_lost_detected"}:
            return None

        scene_type, involved = self._fuse(target_key, stable_event.event_type)
        if not involved:
            involved = [signal]
        score_hint = self._fuse_score(involved)
        interaction = self._derive_interaction_context(
            target_key=target_key,
            current_event_type=stable_event.event_type,
            scene_type=scene_type,
        )

        # Gate: single weak signal is not enough to form a scene.
        # P0 safety events and multi-signal fused scenes always pass.
        is_fused = len(involved) >= 2
        is_safety = stable_event.priority == EventPriority.P0
        if not is_fused and not is_safety and score_hint < self.min_single_signal_score:
            return None

        payload = dict(stable_event.payload)
        payload["fused_event_types"] = [item.event_type for item in involved]
        payload["scene_path"] = interaction.scene_path
        payload["interaction_state"] = interaction.interaction_state
        payload["engagement_score"] = interaction.engagement_score
        payload["entity_signals"] = interaction.entity_signals
        payload["relation_signals"] = interaction.relation_signals
        payload["event_signals"] = interaction.event_signals
        payload["context_signals"] = interaction.context_signals

        return SceneCandidate(
            scene_id=new_id(),
            trace_id=stable_event.trace_id,
            scene_type=scene_type,
            based_on_events=[item.base_event_id for item in involved],
            score_hint=score_hint,
            valid_until_monotonic=max(now + 1.0, min(item.valid_until for item in involved)),
            target_id=target_id,
            payload=payload,
        )

    def update_runtime_tuning(
        self,
        *,
        memory_window_s: float | None = None,
        min_single_signal_score: float | None = None,
    ) -> dict[str, float]:
        if memory_window_s is not None:
            self.memory_window_s = max(0.5, float(memory_window_s))
        if min_single_signal_score is not None:
            self.min_single_signal_score = min(max(0.0, float(min_single_signal_score)), 1.0)
        return {
            "memory_window_s": float(self.memory_window_s),
            "min_single_signal_score": float(self.min_single_signal_score),
        }

    def _fuse(self, target_key: str, current_event_type: str) -> tuple[str, list[_Signal]]:
        target_signals = self._memory.get(target_key, {})
        global_signals = self._memory.get(GLOBAL_TARGET, {})

        current = target_signals.get(current_event_type)
        if current is None:
            return SCENE_ATTENTION, []

        if current.event_type in {EVENT_EMERGENCY_STOP_DETECTED, EVENT_COLLISION_WARNING_DETECTED}:
            return SCENE_SAFETY_ALERT, [current]

        # Priority 1: strong safety fusion (loud + motion).
        loud = target_signals.get(EVENT_LOUD_SOUND_DETECTED) or global_signals.get(
            EVENT_LOUD_SOUND_DETECTED
        )
        motion = target_signals.get(EVENT_MOTION_DETECTED) or global_signals.get(EVENT_MOTION_DETECTED)
        if loud is not None and motion is not None:
            return SCENE_SAFETY_ALERT, [loud, motion]
        if current.event_type == EVENT_LOUD_SOUND_DETECTED:
            return SCENE_SAFETY_ALERT, [current]

        # Priority 2: interaction fusion (gesture + gaze, familiar + gaze).
        gaze = target_signals.get(EVENT_GAZE_SUSTAINED_DETECTED)
        familiar = target_signals.get(EVENT_FAMILIAR_FACE_DETECTED)
        stranger = target_signals.get(EVENT_STRANGER_FACE_DETECTED)
        gesture = target_signals.get(EVENT_GESTURE_DETECTED)

        if gesture is not None and gaze is not None:
            return SCENE_GESTURE_BOND, [gesture, gaze]
        wave = target_signals.get("wave_detected")
        gaze_hold_start = target_signals.get("gaze_hold_start_detected")
        if wave is not None and (gaze is not None or gaze_hold_start is not None):
            supporting = gaze if gaze is not None else gaze_hold_start
            assert supporting is not None
            return SCENE_GESTURE_BOND, [wave, supporting]
        if familiar is not None and gaze is not None:
            return SCENE_GREETING, [familiar, gaze]
        if familiar is not None and gaze_hold_start is not None:
            return SCENE_GREETING, [familiar, gaze_hold_start]
        if stranger is not None and gaze is not None:
            return SCENE_STRANGER_ATTENTION, [stranger, gaze]
        if stranger is not None and gaze_hold_start is not None:
            return SCENE_STRANGER_ATTENTION, [stranger, gaze_hold_start]

        # Priority 3: single-signal fallback.
        if current.event_type == EVENT_FAMILIAR_FACE_DETECTED:
            return SCENE_ATTENTION, [current]
        if current.event_type == EVENT_GESTURE_DETECTED:
            return SCENE_GESTURE_BOND, [current]
        if current.event_type == "wave_detected":
            return SCENE_GESTURE_BOND, [current]
        if current.event_type == EVENT_STRANGER_FACE_DETECTED:
            return SCENE_STRANGER_ATTENTION, [current]
        if current.event_type in {EVENT_GAZE_SUSTAINED_DETECTED, "gaze_hold_start_detected"}:
            return SCENE_ATTENTION, [current]
        if current.event_type == EVENT_MOTION_DETECTED:
            return SCENE_AMBIENT_TRACKING, [current]
        return f"{current.event_type.removesuffix('_detected')}_scene", [current]

    def _derive_interaction_context(
        self,
        *,
        target_key: str,
        current_event_type: str,
        scene_type: str,
    ) -> _InteractionContext:
        target_signals = self._memory.get(target_key, {})
        global_signals = self._memory.get(GLOBAL_TARGET, {})

        familiar = target_signals.get(EVENT_FAMILIAR_FACE_DETECTED)
        stranger = target_signals.get(EVENT_STRANGER_FACE_DETECTED)
        gaze = target_signals.get(EVENT_GAZE_SUSTAINED_DETECTED)
        gesture = target_signals.get(EVENT_GESTURE_DETECTED)
        motion = target_signals.get(EVENT_MOTION_DETECTED) or global_signals.get(EVENT_MOTION_DETECTED)
        loud = target_signals.get(EVENT_LOUD_SOUND_DETECTED) or global_signals.get(EVENT_LOUD_SOUND_DETECTED)
        emergency = target_signals.get(EVENT_EMERGENCY_STOP_DETECTED) or global_signals.get(EVENT_EMERGENCY_STOP_DETECTED)
        collision = target_signals.get(EVENT_COLLISION_WARNING_DETECTED) or global_signals.get(EVENT_COLLISION_WARNING_DETECTED)

        entity_signals = [
            signal_name
            for signal_name, signal_value in (
                (EVENT_FAMILIAR_FACE_DETECTED, familiar),
                (EVENT_STRANGER_FACE_DETECTED, stranger),
                (EVENT_MOTION_DETECTED, motion),
            )
            if signal_value is not None
        ]
        relation_signals = [
            signal_name
            for signal_name, signal_value in ((EVENT_GAZE_SUSTAINED_DETECTED, gaze),)
            if signal_value is not None
        ]
        event_signals = [
            signal_name
            for signal_name, signal_value in (
                (EVENT_GESTURE_DETECTED, gesture),
                (EVENT_LOUD_SOUND_DETECTED, loud),
                (EVENT_COLLISION_WARNING_DETECTED, collision),
                (EVENT_EMERGENCY_STOP_DETECTED, emergency),
            )
            if signal_value is not None
        ]
        context_signals: list[str] = []
        if familiar is not None:
            context_signals.append("familiar_person")
        if stranger is not None:
            context_signals.append("stranger_person")

        risk_present = loud is not None or collision is not None or emergency is not None
        social_present = any(item is not None for item in (familiar, stranger, gaze, gesture, motion))
        if risk_present:
            interaction_state = "alert"
        elif gesture is not None and gaze is not None:
            interaction_state = "engaging"
        elif familiar is not None and gaze is not None:
            interaction_state = "engaging"
        elif (familiar is not None or stranger is not None) and gaze is not None:
            interaction_state = "mutual_attention"
        elif social_present:
            interaction_state = "noticed_human"
        else:
            interaction_state = "idle"

        engagement_score = 0.0
        if familiar is not None or stranger is not None:
            engagement_score += 0.35
        if familiar is not None:
            engagement_score += 0.1
        if gaze is not None:
            engagement_score += 0.25
        if gesture is not None:
            engagement_score += 0.25
        if motion is not None:
            engagement_score += 0.1
        if risk_present:
            engagement_score = max(engagement_score, 0.9)
        if current_event_type == EVENT_GAZE_SUSTAINED_DETECTED:
            engagement_score += 0.05

        scene_path = "safety" if scene_type == SCENE_SAFETY_ALERT else "social"
        return _InteractionContext(
            scene_path=scene_path,
            interaction_state=interaction_state,
            engagement_score=min(1.0, round(engagement_score, 3)),
            entity_signals=entity_signals,
            relation_signals=relation_signals,
            event_signals=event_signals,
            context_signals=context_signals,
        )

    def _prune(self, now: float) -> None:
        expire_before = now - self.memory_window_s
        for target_key in list(self._memory.keys()):
            signals = self._memory[target_key]
            for event_type in list(signals.keys()):
                signal = signals[event_type]
                if signal.valid_until < now or signal.observed_at < expire_before:
                    signals.pop(event_type, None)
            if not signals:
                self._memory.pop(target_key, None)

    def _enforce_target_limit(self, *, current_target_key: str) -> None:
        non_global_targets = [key for key in self._memory if key != GLOBAL_TARGET]
        if len(non_global_targets) <= self.max_targets:
            return

        eviction_candidates: list[tuple[float, str]] = []
        for target_key in non_global_targets:
            if target_key == current_target_key:
                continue
            signals = self._memory.get(target_key, {})
            if not signals:
                eviction_candidates.append((float("-inf"), target_key))
                continue
            last_observed = max(signal.observed_at for signal in signals.values())
            eviction_candidates.append((last_observed, target_key))

        if not eviction_candidates and current_target_key != GLOBAL_TARGET:
            self._memory.pop(current_target_key, None)
            self._target_evictions += 1
            return

        _, target_to_evict = min(eviction_candidates, key=lambda item: item[0])
        self._memory.pop(target_to_evict, None)
        self._target_evictions += 1

    @staticmethod
    def _compute_score_hint(stable_event: StableEvent) -> float:
        accessor = DetectionPayloadAccessor(stable_event.payload if isinstance(stable_event.payload, dict) else {})
        raw_base = stable_event.payload.get("score_hint") if isinstance(stable_event.payload, dict) else None
        if raw_base is None:
            raw_base = accessor.event_confidence if accessor.event_confidence is not None else 0.6
        try:
            base_score = float(raw_base)
        except (TypeError, ValueError):
            base_score = 0.6

        base_score = min(max(base_score, 0.0), 1.0)
        priority_bias = PRIORITY_BIAS.get(stable_event.priority, 0.0)
        return min(max((base_score * 0.7) + priority_bias, 0.0), 1.0)

    @staticmethod
    def _fuse_score(signals: list[_Signal]) -> float:
        if not signals:
            return 0.0
        base = sum(item.score for item in signals) / len(signals)
        bonus = 0.05 if len(signals) >= 2 else 0.0
        return min(1.0, base + bonus)


def _resolve_target(payload: dict) -> str | None:
    return DetectionPayloadAccessor(payload).target_id
