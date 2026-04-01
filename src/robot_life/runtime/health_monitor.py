from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any


@dataclass
class RuntimeHealthMonitor:
    """Track degraded mode and safe-idle fallback signals for the runtime."""

    degraded_after_failures: int = 3
    stale_long_task_limit: int = 2
    blocked_execution_limit: int = 2
    _failure_streaks: dict[str, int] = field(default_factory=dict)
    _source_health: dict[str, dict[str, Any]] = field(default_factory=dict)
    _executor_status_counts: dict[str, int] = field(default_factory=dict)
    _long_task_stale_drops: int = 0
    _long_task_stale_streak: int = 0
    _last_updated_at: float = field(default_factory=monotonic)

    def record_source_health(self, source_name: str, snapshot: dict[str, Any]) -> None:
        self._source_health[source_name] = dict(snapshot)
        self._last_updated_at = monotonic()
        raw_streak = snapshot.get("consecutive_failures", snapshot.get("read_failures", 0))
        try:
            consecutive_failures = max(0, int(raw_streak or 0))
        except (TypeError, ValueError):
            consecutive_failures = 0
        self._failure_streaks[f"source:{source_name}"] = consecutive_failures

    def record_stage_failure(self, stage: str) -> None:
        key = f"stage:{stage}"
        self._failure_streaks[key] = self._failure_streaks.get(key, 0) + 1
        self._last_updated_at = monotonic()

    def record_stage_success(self, stage: str) -> None:
        self._failure_streaks[f"stage:{stage}"] = 0
        self._last_updated_at = monotonic()

    def record_execution(self, execution: Any) -> None:
        status = str(getattr(execution, "status", "unknown") or "unknown")
        self._executor_status_counts[status] = self._executor_status_counts.get(status, 0) + 1
        if status in {"failed", "blocked"}:
            self._failure_streaks["executor"] = self._failure_streaks.get("executor", 0) + 1
        else:
            self._failure_streaks["executor"] = 0
        self._last_updated_at = monotonic()

    def record_long_task_stale_drop(self, count: int = 1) -> None:
        increment = max(0, int(count))
        self._long_task_stale_drops += increment
        self._long_task_stale_streak += increment
        self._failure_streaks["long_task"] = self._long_task_stale_streak
        self._last_updated_at = monotonic()

    def record_long_task_healthy(self) -> None:
        self._long_task_stale_streak = 0
        self._failure_streaks["long_task"] = 0
        self._last_updated_at = monotonic()

    @property
    def degraded(self) -> bool:
        if self._long_task_stale_streak >= self.stale_long_task_limit:
            return True
        if self._failure_streaks.get("executor", 0) >= self.blocked_execution_limit:
            return True
        return any(count >= self.degraded_after_failures for count in self._failure_streaks.values())

    @property
    def safe_idle_recommended(self) -> bool:
        return self.degraded and self._failure_streaks.get("executor", 0) >= self.blocked_execution_limit

    def snapshot(self) -> dict[str, Any]:
        return {
            "degraded": self.degraded,
            "safe_idle_recommended": self.safe_idle_recommended,
            "failure_streaks": dict(self._failure_streaks),
            "source_health": {name: dict(snapshot) for name, snapshot in self._source_health.items()},
            "executor_status_counts": dict(self._executor_status_counts),
            "long_task_stale_drops": self._long_task_stale_drops,
            "long_task_stale_drops_total": self._long_task_stale_drops,
            "long_task_stale_streak": self._long_task_stale_streak,
            "last_updated_at": self._last_updated_at,
        }
