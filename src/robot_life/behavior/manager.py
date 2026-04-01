from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from robot_life.event_engine.policy_layer import PolicyDecision


@dataclass(frozen=True)
class BehaviorPlan:
    target_behavior: str
    degraded_behavior: str | None
    required_resources: list[str]
    optional_resources: list[str]
    resume_previous: bool
    reason: str


class BehaviorManager:
    """Maps policy-approved scenes into concrete behavior plans."""

    def plan(
        self,
        scene: Any,
        *,
        rule: dict[str, Any],
        policy: PolicyDecision,
    ) -> BehaviorPlan:
        target_behavior = str(rule["target_behavior"])
        degraded_behavior = rule.get("degraded_behavior")
        required_resources = list(rule.get("required_resources", []))
        optional_resources = list(rule.get("optional_resources", []))
        resume_previous = bool(rule.get("resume_previous", True))
        return BehaviorPlan(
            target_behavior=target_behavior,
            degraded_behavior=degraded_behavior,
            required_resources=required_resources,
            optional_resources=optional_resources,
            resume_previous=resume_previous,
            reason=f"behavior_plan:{policy.response_level}:{getattr(scene, 'scene_type', 'unknown')}",
        )
