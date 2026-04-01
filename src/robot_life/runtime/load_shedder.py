from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResourceLoadShedder:
    """Encapsulates runtime load-shedding policy.

    Keeps the mode-resolution and target runtime tuning logic out of the
    live loop so the coordinator only needs to pass current pressure stats.
    """

    queue_drain_latency_budget_ms: float
    queue_drain_pending_threshold: int
    target_pipelines: tuple[str, ...] = ("face", "gaze", "motion")
    light_scale: float = 0.5
    strong_scale: float = 0.33
    light_interval_s: float = 8.0
    strong_interval_s: float = 12.0

    def __post_init__(self) -> None:
        self.mode = "normal"
        self.active = False
        self.pipeline_scales: dict[str, float] = {}
        self._base_force_sample: bool | None = None
        self._base_sample_interval_s: float | None = None

    def apply(
        self,
        *,
        queue_pending: int,
        cycle_latency_ms: float,
        queue_pressure_streak: int,
        registry: Any,
        task_service: Any | None,
        interaction_intent: str | None = None,
    ) -> dict[str, Any]:
        mode, reasons = self.resolve_mode(
            queue_pending=queue_pending,
            cycle_latency_ms=cycle_latency_ms,
            queue_pressure_streak=queue_pressure_streak,
        )
        self.mode = mode
        self.active = mode != "normal"
        pressure_scales = self.pipeline_scales_for_mode(mode)
        intent_scales = self.intent_profile_scales(interaction_intent)
        pipeline_scales = self.merge_pipeline_scales(pressure_scales, intent_scales)
        self.pipeline_scales = dict(pipeline_scales)
        self._apply_pipeline_runtime_scales(registry=registry, scales=pipeline_scales)
        task_controls = self._apply_task_service_load_shed(task_service, mode)
        payload = {
            "load_shed_mode": mode,
            "load_shed_active": self.active,
            "load_shed_reasons": reasons,
            "load_shed_queue_pending": queue_pending,
            "load_shed_cycle_latency_ms": round(float(cycle_latency_ms), 3),
            "load_shed_pipeline_scales": dict(pipeline_scales),
            "intent_profile": interaction_intent,
            "intent_pipeline_scales": dict(intent_scales),
        }
        payload.update(task_controls)
        return payload

    def resolve_mode(
        self,
        *,
        queue_pending: int,
        cycle_latency_ms: float,
        queue_pressure_streak: int,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        latency_pressure = cycle_latency_ms > self.queue_drain_latency_budget_ms
        queue_pressure = queue_pending >= self.queue_drain_pending_threshold
        streak_pressure = queue_pressure_streak >= 1

        if latency_pressure:
            reasons.append("latency")
        if queue_pressure:
            reasons.append("queue_depth")
        if streak_pressure:
            reasons.append("streak")

        if (
            queue_pressure_streak >= 2
            or queue_pending >= self.queue_drain_pending_threshold * 2
            or cycle_latency_ms >= self.queue_drain_latency_budget_ms * 1.5
        ):
            return "strong", reasons or ["pressure"]
        if latency_pressure or queue_pressure or streak_pressure:
            return "light", reasons or ["pressure"]
        return "normal", []


    def intent_profile_scales(self, interaction_intent: str | None) -> dict[str, float]:
        intent = str(interaction_intent or "").strip().lower()
        scales = {pipeline_name: 1.0 for pipeline_name in self.target_pipelines}
        if intent in {"ack_presence", "establish_attention"}:
            scales.update({"face": 1.2, "gaze": 1.25, "motion": 0.8})
        elif intent in {"maintain_engagement", "ongoing_interaction"}:
            scales.update({"face": 1.35, "gaze": 1.35, "motion": 0.65})
        elif intent in {"safety_override", "recover_safely"}:
            scales.update({"face": 0.7, "gaze": 0.8, "motion": 1.4})
        elif intent in {"idle_scan", "observe_ambient"}:
            scales.update({"face": 0.85, "gaze": 0.85, "motion": 1.0})
        return {pipeline_name: float(scales.get(pipeline_name, 1.0)) for pipeline_name in self.target_pipelines}

    @staticmethod
    def merge_pipeline_scales(pressure_scales: dict[str, float], intent_scales: dict[str, float]) -> dict[str, float]:
        names = set(pressure_scales) | set(intent_scales)
        merged: dict[str, float] = {}
        for pipeline_name in names:
            pressure = float(pressure_scales.get(pipeline_name, 1.0))
            intent = float(intent_scales.get(pipeline_name, 1.0))
            merged[pipeline_name] = round(max(0.1, pressure * intent), 3)
        return merged

    def pipeline_scales_for_mode(self, mode: str) -> dict[str, float]:
        if mode == "strong":
            scale = self.strong_scale
        elif mode == "light":
            scale = self.light_scale
        else:
            scale = 1.0
        return {pipeline_name: scale for pipeline_name in self.target_pipelines}

    @staticmethod
    def _apply_pipeline_runtime_scales(*, registry: Any, scales: dict[str, float]) -> None:
        if hasattr(registry, "set_runtime_scales"):
            registry.set_runtime_scales(scales)
            return
        if hasattr(registry, "set_runtime_scale"):
            for pipeline_name, scale in scales.items():
                registry.set_runtime_scale(pipeline_name, scale)

    def _apply_task_service_load_shed(self, task_service: Any | None, mode: str) -> dict[str, Any]:
        if task_service is None:
            return {
                "slow_scene_force_sample": None,
                "slow_scene_sample_interval_s": None,
            }

        if self._base_force_sample is None and hasattr(task_service, "force_sample"):
            self._base_force_sample = bool(getattr(task_service, "force_sample", False))
        if self._base_sample_interval_s is None and hasattr(task_service, "sample_interval_s"):
            self._base_sample_interval_s = float(getattr(task_service, "sample_interval_s", 0.0))

        base_force_sample = self._base_force_sample
        base_interval_s = self._base_sample_interval_s

        if mode == "normal":
            if base_force_sample is not None and hasattr(task_service, "force_sample"):
                task_service.force_sample = base_force_sample
            if base_interval_s is not None and hasattr(task_service, "sample_interval_s"):
                task_service.sample_interval_s = base_interval_s
        else:
            if hasattr(task_service, "force_sample"):
                task_service.force_sample = False
            if hasattr(task_service, "sample_interval_s"):
                conservative_interval_s = self.light_interval_s
                if mode == "strong":
                    conservative_interval_s = self.strong_interval_s
                if base_interval_s is not None:
                    conservative_interval_s = max(
                        base_interval_s * (2.0 if mode == "strong" else 1.5),
                        conservative_interval_s,
                    )
                task_service.sample_interval_s = conservative_interval_s

        return {
            "slow_scene_force_sample": getattr(task_service, "force_sample", None),
            "slow_scene_sample_interval_s": getattr(task_service, "sample_interval_s", None),
        }
