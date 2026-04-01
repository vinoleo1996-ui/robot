from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from robot_life.common.contracts import (
    SCENE_AMBIENT_TRACKING,
    SCENE_ATTENTION,
    SCENE_GESTURE_BOND,
    SCENE_GREETING,
    SCENE_SAFETY_ALERT,
    SCENE_STRANGER_ATTENTION,
    priority_rank,
)
from robot_life.common.payload_contracts import ScenePayloadAccessor
from robot_life.common.schemas import DecisionMode, EventPriority, SceneCandidate


@dataclass(frozen=True)
class PolicyDecision:
    priority: EventPriority
    mode: DecisionMode
    response_level: str
    reason: str


class PolicyLayer:
    """Decides whether and how strongly the system should respond."""

    def __init__(
        self,
        *,
        degrade_score_threshold: float,
        priority_policies: dict[EventPriority, tuple[str, int]],
    ) -> None:
        self.degrade_score_threshold = float(degrade_score_threshold)
        self._priority_policies = dict(priority_policies)

    def evaluate(
        self,
        scene: SceneCandidate,
        *,
        rule: dict[str, Any],
        current_priority: EventPriority | None,
    ) -> PolicyDecision:
        priority = rule["priority"]
        if self._is_context_suppressed(scene, priority=priority):
            return PolicyDecision(
                priority=priority,
                mode=DecisionMode.DROP,
                response_level="suppressed",
                reason=f"policy:suppressed|scene:{scene.scene_type}",
            )
        response_level = self._resolve_response_level(scene)
        mode = self._resolve_mode(
            incoming_priority=priority,
            current_priority=current_priority,
            hard_interrupt=bool(rule.get("hard_interrupt", False)),
        )
        mode = self._apply_degrade_policy(
            mode=mode,
            degraded_behavior=rule.get("degraded_behavior"),
            scene_score=getattr(scene, "score_hint", 1.0),
        )
        return PolicyDecision(
            priority=priority,
            mode=mode,
            response_level=response_level,
            reason=f"policy:{response_level}|scene:{scene.scene_type}",
        )

    def queue_timeout_ms(self, priority: EventPriority) -> int:
        return self._priority_policies.get(priority, ("queue", 5_000))[1]

    def _resolve_mode(
        self,
        *,
        incoming_priority: EventPriority,
        current_priority: EventPriority | None,
        hard_interrupt: bool,
    ) -> DecisionMode:
        if current_priority is None:
            return DecisionMode.EXECUTE

        incoming_rank = priority_rank(incoming_priority)
        current_rank = priority_rank(current_priority)

        if incoming_rank < current_rank:
            interrupt_policy = self._priority_policies.get(incoming_priority, ("queue", 5_000))[0]
            if hard_interrupt or interrupt_policy == "immediate":
                return DecisionMode.HARD_INTERRUPT
            if interrupt_policy == "soft":
                return DecisionMode.SOFT_INTERRUPT
            return DecisionMode.EXECUTE

        if incoming_priority == current_priority:
            if incoming_priority == EventPriority.P3:
                return DecisionMode.DROP
            return DecisionMode.QUEUE

        if incoming_priority == EventPriority.P3:
            return DecisionMode.DROP

        return DecisionMode.QUEUE

    def _apply_degrade_policy(
        self,
        *,
        mode: DecisionMode,
        degraded_behavior: str | None,
        scene_score: float,
    ) -> DecisionMode:
        if degraded_behavior is None:
            return mode
        if mode not in {DecisionMode.EXECUTE, DecisionMode.SOFT_INTERRUPT}:
            return mode
        if scene_score >= self.degrade_score_threshold:
            return mode
        return DecisionMode.DEGRADE_AND_EXECUTE

    @staticmethod
    def _resolve_response_level(scene: SceneCandidate) -> str:
        engagement = _scene_engagement_score(scene)
        interaction_state = (_scene_interaction_state(scene) or "").strip().lower()
        scene_type = str(scene.scene_type)

        if scene_type == SCENE_SAFETY_ALERT:
            return "urgent"
        if scene_type == SCENE_AMBIENT_TRACKING:
            return "ambient"
        if scene_type in {SCENE_GREETING, SCENE_GESTURE_BOND}:
            if interaction_state in {"engaging", "ongoing_interaction"}:
                return "full"
            if engagement is not None and engagement >= 0.72:
                return "full"
            return "acknowledge"
        if scene_type in {SCENE_ATTENTION, SCENE_STRANGER_ATTENTION}:
            if interaction_state in {"mutual_attention", "engaging", "ongoing_interaction"}:
                return "full"
            if engagement is not None and engagement >= 0.68:
                return "full"
            return "observe"
        return "full"

    @classmethod
    def _is_context_suppressed(
        cls,
        scene: SceneCandidate,
        *,
        priority: EventPriority,
    ) -> bool:
        if priority in {EventPriority.P0, EventPriority.P1}:
            return False
        payload = _scene_payload(scene)
        if payload.robot_do_not_disturb:
            return True
        return (payload.robot_mode or "").strip().lower() == "sleep"


def _scene_payload(scene: SceneCandidate) -> ScenePayloadAccessor:
    return ScenePayloadAccessor.from_scene(scene)


def _scene_engagement_score(scene: SceneCandidate) -> float | None:
    accessor = _scene_payload(scene)
    return accessor.engagement_score if accessor.engagement_score is not None else getattr(scene, "score_hint", None)


def _scene_interaction_state(scene: SceneCandidate) -> str | None:
    return _scene_payload(scene).interaction_state
