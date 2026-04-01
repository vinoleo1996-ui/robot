from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Any


@dataclass(frozen=True)
class RecentInteraction:
    behavior_id: str
    target_id: str | None
    ended_at: float
    status: str


class RobotContextStore:
    """Stores lightweight robot-side context for arbitration and observability."""

    def __init__(
        self,
        *,
        mode: str = "demo",
        do_not_disturb: bool = False,
        battery_level: float | None = None,
        max_recent_interactions: int = 8,
    ) -> None:
        self.mode = str(mode)
        self.do_not_disturb = bool(do_not_disturb)
        self.battery_level = battery_level
        self.speaking = False
        self.listening = False
        self.moving = False
        self.active_behavior_id: str | None = None
        self.active_behavior_status: str | None = None
        self.current_interaction_target: str | None = None
        self.current_interaction_episode_id: str | None = None
        self.current_intent: str | None = None
        self.updated_at = monotonic()
        self._recent_interactions: deque[RecentInteraction] = deque(maxlen=max(1, int(max_recent_interactions)))

    def set_mode(self, mode: str) -> None:
        self.mode = str(mode)
        self.updated_at = monotonic()

    def set_do_not_disturb(self, enabled: bool) -> None:
        self.do_not_disturb = bool(enabled)
        self.updated_at = monotonic()

    def sync(
        self,
        *,
        interaction_snapshot: dict[str, Any] | None,
        active_execution: Any | None,
        execution_results: list[Any],
    ) -> None:
        interaction_snapshot = interaction_snapshot or {}
        active_target = interaction_snapshot.get("target_id") or interaction_snapshot.get("latest_target_id")
        self.current_interaction_target = str(active_target) if active_target else None
        episode_id = interaction_snapshot.get("episode_id")
        self.current_interaction_episode_id = str(episode_id) if episode_id else None
        intent = interaction_snapshot.get("intent")
        self.current_intent = str(intent) if intent else None

        if active_execution is None:
            self.active_behavior_id = None
            self.active_behavior_status = None
            self.speaking = False
            self.moving = False
        else:
            self.active_behavior_id = getattr(active_execution, "behavior_id", None)
            self.active_behavior_status = getattr(active_execution, "status", None)
            active_behavior = str(self.active_behavior_id or "")
            self.speaking = active_behavior.startswith("perform_greeting") or active_behavior.startswith("perform_safety_alert")
            self.moving = active_behavior.startswith("perform_")

        for execution in execution_results:
            status = getattr(execution, "status", None)
            if status not in {"finished", "degraded"}:
                continue
            self._recent_interactions.append(
                RecentInteraction(
                    behavior_id=str(getattr(execution, "behavior_id", "")),
                    target_id=getattr(execution, "target_id", None),
                    ended_at=float(getattr(execution, "ended_at", monotonic())),
                    status=str(status),
                )
            )
        self.updated_at = monotonic()

    def snapshot(self) -> dict[str, Any]:
        now = monotonic()
        return {
            "mode": self.mode,
            "do_not_disturb": self.do_not_disturb,
            "battery_level": self.battery_level,
            "speaking": self.speaking,
            "listening": self.listening,
            "moving": self.moving,
            "active_behavior_id": self.active_behavior_id,
            "active_behavior_status": self.active_behavior_status,
            "current_interaction_target": self.current_interaction_target,
            "current_interaction_episode_id": self.current_interaction_episode_id,
            "current_intent": self.current_intent,
            "recent_interactions": [
                {
                    "behavior_id": item.behavior_id,
                    "target_id": item.target_id,
                    "ended_at": item.ended_at,
                    "status": item.status,
                    "age_ms": round((now - item.ended_at) * 1000.0, 2),
                }
                for item in list(self._recent_interactions)
            ],
        }
