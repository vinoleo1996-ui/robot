from __future__ import annotations

from time import monotonic
from typing import Any, Callable

from robot_life.runtime.telemetry import emit_stage_trace


ExecutionRecorder = Callable[[Any], None]
BehaviorSceneResolver = Callable[[str], str]


def finalize_execution(
    *,
    execution: Any,
    telemetry: Any,
    result: Any,
    stage_name: str,
    started_at: float,
    ended_at: float | None = None,
    async_mode: bool = False,
    tick_mode: bool = False,
    record_decay_execution: ExecutionRecorder,
    cooldown_manager: Any | None,
    behavior_to_scene_type: BehaviorSceneResolver,
) -> None:
    result.execution_results.append(execution)
    record_decay_execution(execution)
    if cooldown_manager is not None and execution.status in {"finished", "degraded"}:
        scene_type = execution.scene_type or behavior_to_scene_type(execution.behavior_id)
        cooldown_manager.record_execution(scene_type, target_id=execution.target_id)
    emit_stage_trace(
        telemetry,
        execution.trace_id,
        stage_name,
        payload={
            "behavior_id": execution.behavior_id,
            "status": execution.status,
            "degraded": execution.degraded,
            "interrupted": execution.interrupted,
            "async": async_mode,
            "tick_mode": tick_mode,
            "interaction_episode_id": getattr(execution, "interaction_episode_id", None),
            "scene_epoch": getattr(execution, "scene_epoch", None),
            "decision_epoch": getattr(execution, "decision_epoch", None),
        },
        started_at=started_at,
        ended_at=ended_at if ended_at is not None else monotonic(),
    )


def enqueue_resumed_decision(*, arbitration_runtime: Any | None, telemetry: Any, resumed: Any) -> bool:
    if arbitration_runtime is None:
        return False
    enqueued = arbitration_runtime.queue.enqueue(
        resumed,
        timeout_ms=arbitration_runtime.arbitrator.queue_timeout_ms(resumed.priority),
    )
    emit_stage_trace(
        telemetry,
        resumed.trace_id,
        "resume_enqueue",
        status="queued" if enqueued is not None else "dropped",
        payload={
            "target_behavior": resumed.target_behavior,
            "priority": resumed.priority.value,
            "reason": resumed.reason,
            "interaction_episode_id": getattr(resumed, "interaction_episode_id", None),
            "scene_epoch": getattr(resumed, "scene_epoch", None),
            "decision_epoch": getattr(resumed, "decision_epoch", None),
        },
        started_at=monotonic(),
        ended_at=monotonic(),
    )
    return enqueued is not None
