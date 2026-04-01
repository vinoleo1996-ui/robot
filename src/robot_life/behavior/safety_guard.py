from __future__ import annotations

from dataclasses import dataclass

from robot_life.common.config import SafetyConfig
from robot_life.common.contracts import priority_rank
from robot_life.common.schemas import ArbitrationResult, DecisionMode, EventPriority


@dataclass
class SafetyGuardOutcome:
    allowed: bool
    reason: str
    estop_required: bool = False


class BehaviorSafetyGuard:
    """Runtime safety gate for behavior execution."""

    def __init__(
        self,
        *,
        dangerous_behavior_allowlist: set[str] | None = None,
        dangerous_behavior_tokens: tuple[str, ...] = (
            "swing",
            "strike",
            "throw",
            "kick",
            "slam",
            "dash",
        ),
        emergency_behavior_tokens: tuple[str, ...] = (
            "safety_alert",
            "emergency_stop",
            "estop",
            "e_stop",
            "panic",
        ),
        emergency_reason_tokens: tuple[str, ...] = (
            "emergency",
            "collision",
            "safety",
            "danger",
            "estop",
            "panic",
        ),
        behavior_mutex: dict[str, set[str]] | None = None,
        enabled: bool = True,
    ) -> None:
        self.enabled = bool(enabled)
        self.dangerous_behavior_allowlist = dangerous_behavior_allowlist or {
            "perform_greeting",
            "perform_attention",
            "perform_gesture_response",
            "perform_tracking",
            "perform_safety_alert",
            "greeting_visual_only",
            "attention_minimal",
            "gesture_visual_only",
        }
        self.dangerous_behavior_tokens = tuple(token.lower() for token in dangerous_behavior_tokens)
        self.emergency_behavior_tokens = tuple(token.lower() for token in emergency_behavior_tokens)
        self.emergency_reason_tokens = tuple(token.lower() for token in emergency_reason_tokens)
        self.behavior_mutex = self._normalize_mutex_matrix(behavior_mutex or self._default_mutex())

    @classmethod
    def from_config(cls, config: SafetyConfig) -> "BehaviorSafetyGuard":
        behavior_mutex = {
            behavior: set(conflicts)
            for behavior, conflicts in config.behavior_mutex.items()
        }
        return cls(
            dangerous_behavior_allowlist=set(config.dangerous_behavior_allowlist),
            dangerous_behavior_tokens=tuple(config.dangerous_behavior_tokens),
            emergency_behavior_tokens=tuple(config.emergency_behavior_tokens),
            emergency_reason_tokens=tuple(config.emergency_reason_tokens),
            behavior_mutex=behavior_mutex,
            enabled=bool(config.enabled),
        )

    def evaluate(
        self,
        decision: ArbitrationResult,
        *,
        current_decision: ArbitrationResult | None,
    ) -> SafetyGuardOutcome:
        if not self.enabled:
            return SafetyGuardOutcome(allowed=True, reason="disabled")

        if self._is_emergency_decision(decision):
            return SafetyGuardOutcome(allowed=True, reason="emergency_stop_preempt", estop_required=True)

        behavior = decision.target_behavior.strip()
        normalized_behavior = behavior.lower()
        if self._is_dangerous_behavior(normalized_behavior) and behavior not in self.dangerous_behavior_allowlist:
            return SafetyGuardOutcome(
                allowed=False,
                reason=f"dangerous_behavior_not_allowlisted:{behavior}",
            )

        if current_decision is not None and self._is_mutex_conflict(
            current=current_decision.target_behavior,
            incoming=behavior,
        ):
            if priority_rank(decision.priority) >= priority_rank(current_decision.priority):
                if decision.mode not in {DecisionMode.SOFT_INTERRUPT, DecisionMode.HARD_INTERRUPT}:
                    return SafetyGuardOutcome(
                        allowed=False,
                        reason=(
                            "mutex_conflict_requires_interrupt:"
                            f"{current_decision.target_behavior}->{decision.target_behavior}"
                        ),
                    )

        return SafetyGuardOutcome(allowed=True, reason="ok")

    def _is_dangerous_behavior(self, behavior: str) -> bool:
        return any(token in behavior for token in self.dangerous_behavior_tokens)

    def _is_emergency_decision(self, decision: ArbitrationResult) -> bool:
        behavior = decision.target_behavior.lower()
        reason = decision.reason.lower()
        if decision.priority == EventPriority.P0:
            return True
        return any(token in behavior for token in self.emergency_behavior_tokens) or any(
            token in reason for token in self.emergency_reason_tokens
        )

    def _is_mutex_conflict(self, *, current: str, incoming: str) -> bool:
        current_conflicts = self.behavior_mutex.get(current, set())
        incoming_conflicts = self.behavior_mutex.get(incoming, set())
        return incoming in current_conflicts or current in incoming_conflicts

    @staticmethod
    def _normalize_mutex_matrix(raw: dict[str, set[str]]) -> dict[str, set[str]]:
        normalized: dict[str, set[str]] = {}
        for behavior, conflicts in raw.items():
            normalized.setdefault(behavior, set()).update(conflicts)
            for target in conflicts:
                normalized.setdefault(target, set()).add(behavior)
        return normalized

    @staticmethod
    def _default_mutex() -> dict[str, set[str]]:
        return {
            "perform_safety_alert": {
                "perform_greeting",
                "perform_attention",
                "perform_gesture_response",
                "perform_tracking",
            },
            "perform_greeting": {
                "perform_attention",
                "perform_gesture_response",
                "perform_tracking",
            },
            "perform_attention": {
                "perform_greeting",
                "perform_gesture_response",
                "perform_tracking",
            },
            "perform_gesture_response": {
                "perform_greeting",
                "perform_attention",
                "perform_tracking",
            },
            "perform_tracking": {
                "perform_greeting",
                "perform_attention",
                "perform_gesture_response",
            },
        }
