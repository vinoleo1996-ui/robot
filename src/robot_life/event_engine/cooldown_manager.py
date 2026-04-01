# 三层冷却架构

from __future__ import annotations

from collections import deque
from time import monotonic

from robot_life.common.schemas import EventPriority


# Default scene-level cooldown periods (seconds).
_DEFAULT_SCENE_COOLDOWNS: dict[str, float] = {
    "greeting_scene": 1800.0,       # 30 minutes
    "attention_scene": 300.0,       # 5 minutes
    "gesture_bond_scene": 10.0,     # 10 seconds
    "ambient_tracking_scene": 5.0,  # 5 seconds
    "safety_alert_scene": 30.0,     # 5s hard + 30s repeat
}


class CooldownManager:
    """Three-layer cooldown: global → scene → event.

    Layer 1 – **Global cooldown**: After *any* behavior executes, suppress
              new P2/P3 events for ``global_cooldown_s`` seconds.  P0/P1
              events bypass this layer entirely.

    Layer 2 – **Scene cooldown**: Per (scene_type, target_id) cooldown.
              The same scene for the same target is suppressed for a
              configurable duration after the last execution.

    Layer 3 – **Event cooldown**: Handled by the existing
              ``EventStabilizer.cooldown_s`` and is not duplicated here.
    """

    def __init__(
        self,
        *,
        global_cooldown_s: float = 3.0,
        scene_cooldowns: dict[str, float] | None = None,
        saturation_window_s: float = 20.0,
        saturation_limit: int = 3,
    ) -> None:
        self.global_cooldown_s = max(0.0, float(global_cooldown_s))
        self.scene_cooldowns: dict[str, float] = dict(
            scene_cooldowns if scene_cooldowns is not None else _DEFAULT_SCENE_COOLDOWNS
        )
        self.saturation_window_s = max(1.0, float(saturation_window_s))
        self.saturation_limit = max(1, int(saturation_limit))

        # Internal state
        self._last_execution_at: float = 0.0
        # (scene_type, target_id) -> last execution timestamp
        self._scene_last_at: dict[tuple[str, str], float] = {}
        self._proactive_history: deque[tuple[float, str, str]] = deque()
        # GC
        self._gc_last_at: float = 0.0
        self._gc_interval_s: float = 30.0

    # ── Public API ──────────────────────────────────────────────

    def check(
        self,
        scene_type: str,
        target_id: str | None,
        priority: EventPriority,
        *,
        active_target_id: str | None = None,
        active_behavior_id: str | None = None,
        robot_busy: bool = False,
    ) -> tuple[bool, str]:
        """Return ``(allowed, reason)``.

        Returns ``(True, "ok")`` if the scene may proceed, or
        ``(False, reason)`` if it is suppressed by a cooldown layer.
        """
        now = monotonic()
        self._gc_stale(now)

        # P0 safety events must never be suppressed by outer cooldown layers.
        # Their repetition is already bounded by detector/stabilizer cooldown.
        if priority == EventPriority.P0:
            return True, "ok"

        if self._should_suppress_for_active_target(
            scene_type,
            target_id=target_id,
            priority=priority,
            active_target_id=active_target_id,
        ):
            active_key = active_target_id or "__any__"
            return False, f"context_suppression:active_target:{active_key}"

        if robot_busy and priority in {EventPriority.P2, EventPriority.P3}:
            behavior_key = active_behavior_id or "busy"
            return False, f"context_suppression:robot_busy:{behavior_key}"

        if self._is_saturated(priority=priority, scene_type=scene_type, now=now):
            return False, f"saturation:{self.saturation_limit}_within_{int(self.saturation_window_s)}s"

        # Layer 1: global cooldown (bypass for P0 / P1)
        if priority not in {EventPriority.P0, EventPriority.P1}:
            if self._last_execution_at > 0:
                elapsed = now - self._last_execution_at
                if elapsed < self.global_cooldown_s:
                    remaining_ms = int((self.global_cooldown_s - elapsed) * 1000)
                    return False, f"global_cooldown:{remaining_ms}ms_remaining"

        # Layer 2: scene cooldown
        scene_cd = self.scene_cooldowns.get(scene_type, 0.0)
        if scene_cd > 0:
            key = (scene_type, target_id or "__any__")
            last = self._scene_last_at.get(key, 0.0)
            if last > 0:
                elapsed = now - last
                if elapsed < scene_cd:
                    remaining_ms = int((scene_cd - elapsed) * 1000)
                    return False, f"scene_cooldown:{scene_type}:{remaining_ms}ms_remaining"

        return True, "ok"

    def record_execution(
        self,
        scene_type: str,
        target_id: str | None,
        *,
        behavior_id: str | None = None,
    ) -> None:
        """Record that a behavior was executed for cooldown tracking."""
        now = monotonic()
        self._last_execution_at = now
        key = (scene_type, target_id or "__any__")
        self._scene_last_at[key] = now
        if self._is_proactive_scene(scene_type):
            self._proactive_history.append((now, scene_type, target_id or "__any__"))
            self._gc_proactive_history(now)

    def reset(self) -> None:
        """Clear all cooldown state."""
        self._last_execution_at = 0.0
        self._scene_last_at.clear()
        self._proactive_history.clear()

    def snapshot(self) -> dict:
        now = monotonic()
        self._gc_proactive_history(now)
        global_remaining = max(0.0, self.global_cooldown_s - (now - self._last_execution_at)) if self._last_execution_at > 0 else 0.0
        scene_remaining: dict[str, float] = {}
        for (scene_type, target_id), last_at in self._scene_last_at.items():
            cd = self.scene_cooldowns.get(scene_type, 0.0)
            remaining = max(0.0, cd - (now - last_at))
            if remaining > 0:
                scene_remaining[f"{scene_type}:{target_id}"] = round(remaining, 2)
        return {
            "global_remaining_s": round(global_remaining, 2),
            "scene_remaining": scene_remaining,
            "tracked_scenes": len(self._scene_last_at),
            "saturation_window_s": round(self.saturation_window_s, 2),
            "saturation_limit": self.saturation_limit,
            "recent_proactive_executions": len(self._proactive_history),
        }

    # ── Internal ────────────────────────────────────────────────

    def _gc_stale(self, now: float) -> None:
        elapsed = now - self._gc_last_at if self._gc_last_at > 0 else float("inf")
        if elapsed < self._gc_interval_s:
            return
        self._gc_last_at = now
        stale = [
            key for key, last_at in self._scene_last_at.items()
            if (now - last_at) > self.scene_cooldowns.get(key[0], 60.0) * 2
        ]
        for key in stale:
            self._scene_last_at.pop(key, None)
        self._gc_proactive_history(now)

    def _gc_proactive_history(self, now: float) -> None:
        while self._proactive_history and (now - self._proactive_history[0][0]) > self.saturation_window_s:
            self._proactive_history.popleft()

    def _is_saturated(
        self,
        *,
        priority: EventPriority,
        scene_type: str,
        now: float,
    ) -> bool:
        if priority in {EventPriority.P0, EventPriority.P1}:
            return False
        if not self._is_proactive_scene(scene_type):
            return False
        self._gc_proactive_history(now)
        return len(self._proactive_history) >= self.saturation_limit

    @staticmethod
    def _is_proactive_scene(scene_type: str) -> bool:
        return scene_type in {
            "greeting_scene",
            "attention_scene",
            "gesture_bond_scene",
            "ambient_tracking_scene",
            "stranger_attention_scene",
        }

    @classmethod
    def _should_suppress_for_active_target(
        cls,
        scene_type: str,
        *,
        target_id: str | None,
        priority: EventPriority,
        active_target_id: str | None,
    ) -> bool:
        if priority in {EventPriority.P0, EventPriority.P1}:
            return False
        if not cls._is_proactive_scene(scene_type):
            return False
        if not active_target_id or not target_id:
            return False
        return active_target_id != target_id
