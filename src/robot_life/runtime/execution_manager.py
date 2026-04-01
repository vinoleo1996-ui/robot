from __future__ import annotations

import logging
from dataclasses import dataclass
from queue import Empty as QueueEmpty, Full as QueueFull
from threading import Event
from time import monotonic
from typing import Any, Callable

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.common.payload_contracts import ArbitrationTracePayload
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.runtime.execution_support import enqueue_resumed_decision, finalize_execution
from robot_life.runtime.telemetry import emit_stage_trace

logger = logging.getLogger(__name__)


@dataclass
class AsyncExecutionDrainItem:
    decision: Any
    execution: Any
    resumed_decisions: list[Any]
    started_at: float
    ended_at: float


ExecutionRecorder = Callable[[Any], None]
BehaviorSceneResolver = Callable[[str], str]


class ExecutionManager:
    def __init__(
        self,
        *,
        telemetry: Any,
        cooldown_manager: Any | None,
        record_decay_execution: ExecutionRecorder,
        behavior_to_scene_type: BehaviorSceneResolver,
        async_executor_enabled: bool,
    ) -> None:
        self.telemetry = telemetry
        self.cooldown_manager = cooldown_manager
        self.record_decay_execution = record_decay_execution
        self.behavior_to_scene_type = behavior_to_scene_type
        self.async_executor_enabled = bool(async_executor_enabled)

    def dispatch_decision(
        self,
        result: Any,
        decision: Any,
        *,
        arbitration_runtime: ArbitrationRuntime | None,
        executor: BehaviorExecutor | None,
        executor_inbox: Any | None,
        executor_outbox: Any | None,
    ) -> None:
        if executor is None:
            return
        if (
            self.async_executor_enabled
            and executor_inbox is not None
            and executor_outbox is not None
            and not bool(getattr(executor, "tick_execution_enabled", False))
        ):
            try:
                executor_inbox.put_nowait(decision)
            except QueueFull:
                logger.warning("async executor queue full, fallback to inline execution")
                self.execute_inline(
                    result,
                    decision,
                    arbitration_runtime=arbitration_runtime,
                    executor=executor,
                )
            else:
                emit_stage_trace(
                    self.telemetry,
                    decision.trace_id,
                    "behavior_executor_async",
                    status="queued",
                    payload=ArbitrationTracePayload.from_decision(decision).to_dict(),
                    started_at=monotonic(),
                    ended_at=monotonic(),
                )
            return
        self.execute_inline(
            result,
            decision,
            arbitration_runtime=arbitration_runtime,
            executor=executor,
        )

    def execute_inline(
        self,
        result: Any,
        decision: Any,
        *,
        arbitration_runtime: ArbitrationRuntime | None,
        executor: BehaviorExecutor,
    ) -> None:
        executor_started_at = monotonic()
        execution = executor.execute(decision)
        if execution.status == "running":
            emit_stage_trace(
                self.telemetry,
                decision.trace_id,
                "behavior_executor",
                status="running",
                payload={
                    "behavior_id": decision.target_behavior,
                    "status": execution.status,
                    "degraded": execution.degraded,
                    "interrupted": execution.interrupted,
                },
                started_at=executor_started_at,
                ended_at=monotonic(),
            )
            return
        self.finalize(
            result=result,
            execution=execution,
            started_at=executor_started_at,
            ended_at=monotonic(),
        )
        self.handle_resume(
            result,
            arbitration_runtime=arbitration_runtime,
            executor=executor,
            on_inline_resume=lambda resumed: self.execute_inline(
                result,
                resumed,
                arbitration_runtime=arbitration_runtime,
                executor=executor,
            ),
        )

    def tick_active(
        self,
        result: Any,
        *,
        arbitration_runtime: ArbitrationRuntime | None,
        executor: BehaviorExecutor | None,
    ) -> None:
        if executor is None or self.async_executor_enabled:
            return
        tick_active = getattr(executor, "tick_active", None)
        if not callable(tick_active):
            return
        executor_started_at = monotonic()
        execution = tick_active()
        if execution is None:
            return
        self.finalize(
            result=result,
            execution=execution,
            started_at=executor_started_at,
            ended_at=monotonic(),
            tick_mode=True,
        )
        self.handle_resume(
            result,
            arbitration_runtime=arbitration_runtime,
            executor=executor,
            on_inline_resume=lambda resumed: self.execute_inline(
                result,
                resumed,
                arbitration_runtime=arbitration_runtime,
                executor=executor,
            ),
        )

    def drain_async_results(
        self,
        result: Any,
        *,
        arbitration_runtime: ArbitrationRuntime | None,
        outbox: Any | None,
        executor: BehaviorExecutor | None = None,
    ) -> None:
        if not self.async_executor_enabled or outbox is None:
            return
        while True:
            try:
                item = outbox.get_nowait()
            except QueueEmpty:
                break
            self.finalize(
                result=result,
                execution=item.execution,
                started_at=item.started_at,
                ended_at=item.ended_at,
                async_mode=True,
            )
            for resumed in item.resumed_decisions:
                if arbitration_runtime is None:
                    if executor is not None:
                        self.execute_inline(
                            result,
                            resumed,
                            arbitration_runtime=None,
                            executor=executor,
                        )
                    continue
                enqueue_resumed_decision(
                    arbitration_runtime=arbitration_runtime,
                    telemetry=self.telemetry,
                    resumed=resumed,
                )
            outbox.task_done()

    def handle_resume(
        self,
        result: Any,
        *,
        arbitration_runtime: ArbitrationRuntime | None,
        executor: BehaviorExecutor,
        on_inline_resume: Callable[[Any], None] | None = None,
    ) -> None:
        pop_resume = getattr(executor, "pop_resume_decision", None)
        if not callable(pop_resume):
            return
        while True:
            resumed = pop_resume()
            if resumed is None:
                break
            if arbitration_runtime is not None:
                enqueue_resumed_decision(
                    arbitration_runtime=arbitration_runtime,
                    telemetry=self.telemetry,
                    resumed=resumed,
                )
                continue
            if on_inline_resume is not None:
                on_inline_resume(resumed)

    def finalize(
        self,
        *,
        result: Any,
        execution: Any,
        started_at: float,
        ended_at: float,
        async_mode: bool = False,
        tick_mode: bool = False,
    ) -> None:
        finalize_execution(
            execution=execution,
            telemetry=self.telemetry,
            result=result,
            stage_name="behavior_executor",
            started_at=started_at,
            ended_at=ended_at,
            async_mode=async_mode,
            tick_mode=tick_mode,
            record_decay_execution=self.record_decay_execution,
            cooldown_manager=self.cooldown_manager,
            behavior_to_scene_type=self.behavior_to_scene_type,
        )

    @staticmethod
    def async_worker(
        executor: BehaviorExecutor,
        *,
        inbox: Any,
        outbox: Any,
        stop_event: Event,
        on_failure: Callable[[Exception], None] | None = None,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        while not stop_event.is_set():
            try:
                decision = inbox.get(timeout=0.1)
            except QueueEmpty:
                continue
            try:
                started_at = monotonic()
                execution = executor.execute(decision)
                ended_at = monotonic()
                resumed_decisions: list[Any] = []
                pop_resume = getattr(executor, "pop_resume_decision", None)
                if callable(pop_resume):
                    while True:
                        resumed = pop_resume()
                        if resumed is None:
                            break
                        resumed_decisions.append(resumed)
                drain_item = AsyncExecutionDrainItem(
                    decision=decision,
                    execution=execution,
                    resumed_decisions=resumed_decisions,
                    started_at=started_at,
                    ended_at=ended_at,
                )
                delivered = False
                while not stop_event.is_set() and not delivered:
                    try:
                        outbox.put(drain_item, timeout=0.1)
                    except QueueFull:
                        continue
                    else:
                        delivered = True
                if delivered and on_success is not None:
                    on_success()
                if not delivered:
                    logger.warning("async executor stopping before execution result could be delivered")
            except Exception as exc:  # pragma: no cover
                if on_failure is not None:
                    on_failure(exc)
                logger.exception("async executor worker failed: %s", exc)
            finally:
                inbox.task_done()
