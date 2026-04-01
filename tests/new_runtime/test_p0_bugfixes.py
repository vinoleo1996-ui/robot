from __future__ import annotations

import time
from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace

from robot_life.common.schemas import ArbitrationResult, DecisionMode, EventPriority, ExecutionResult, SceneCandidate
from robot_life.common.state_machine import InteractionEvent, InteractionState, InteractionStateMachine
from robot_life.runtime.execution_manager import AsyncExecutionDrainItem, ExecutionManager
from robot_life.runtime.health_monitor import RuntimeHealthMonitor
from robot_life.runtime.long_task_coordinator import LongTaskCoordinator
from robot_life.runtime.telemetry import AggregatingTelemetrySink, InMemoryTelemetrySink, StageTrace


class _FakeExecutor:
    tick_execution_enabled = False

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, decision):
        self.executed.append(decision.target_behavior)
        return ExecutionResult(
            execution_id=f"exec-{len(self.executed)}",
            trace_id=decision.trace_id,
            behavior_id=decision.target_behavior,
            status="finished",
            interrupted=False,
            degraded=False,
            started_at=1.0,
            ended_at=2.0,
            target_id=decision.target_id,
            scene_type=decision.scene_type,
            interaction_episode_id=decision.interaction_episode_id,
            scene_epoch=decision.scene_epoch,
            decision_epoch=decision.decision_epoch,
        )

    def pop_resume_decision(self):
        return None


class _CaptureAwareSlowService:
    sample_interval_s = 10.0
    force_sample = True
    request_timeout_ms = 10

    def __init__(self) -> None:
        self.capture_calls = 0

    def capture_frame(self, frame, *, source: str, metadata: dict):
        self.capture_calls += 1

    def should_trigger(self, scene, *, decision_mode=None, arbitration_outcome=None):
        return True

    def submit(self, scene, *, image=None, timeout_ms: int = 0, metadata=None):
        return None



def _decision(behavior_id: str, trace_id: str = "trace-1") -> ArbitrationResult:
    return ArbitrationResult(
        decision_id=f"decision-{behavior_id}",
        trace_id=trace_id,
        target_behavior=behavior_id,
        priority=EventPriority.P1,
        mode=DecisionMode.EXECUTE,
        required_resources=["motion"],
        optional_resources=[],
        degraded_behavior=None,
        resume_previous=False,
        reason="test",
        target_id="alice",
        scene_type="attention_scene",
        interaction_episode_id="episode-1",
        scene_epoch="scene-epoch-1",
        decision_epoch=f"decision-epoch-{behavior_id}",
    )



def test_async_worker_delivers_result_after_temporary_outbox_pressure() -> None:
    manager = ExecutionManager(
        telemetry=SimpleNamespace(emit=lambda trace: None),
        cooldown_manager=None,
        record_decay_execution=lambda execution: None,
        behavior_to_scene_type=lambda behavior_id: "attention_scene",
        async_executor_enabled=True,
    )
    executor = _FakeExecutor()
    inbox: Queue = Queue()
    outbox: Queue = Queue(maxsize=1)
    stop_event = Event()
    sentinel = object()
    outbox.put_nowait(sentinel)
    decision = _decision("perform_greeting", trace_id="trace-async")
    inbox.put_nowait(decision)

    worker = Thread(
        target=manager.async_worker,
        kwargs={"executor": executor, "inbox": inbox, "outbox": outbox, "stop_event": stop_event},
        daemon=True,
    )
    worker.start()
    time.sleep(0.15)
    assert outbox.qsize() == 1
    assert outbox.get_nowait() is sentinel

    deadline = time.time() + 1.0
    delivered = None
    while time.time() < deadline:
        if not outbox.empty():
            delivered = outbox.get_nowait()
            break
        time.sleep(0.02)

    stop_event.set()
    worker.join(timeout=1.0)

    assert isinstance(delivered, AsyncExecutionDrainItem)
    assert delivered.execution.behavior_id == "perform_greeting"





class _ResumeExecutor(_FakeExecutor):
    def __init__(self, resumed_decision):
        super().__init__()
        self._resume_once = resumed_decision

    def pop_resume_decision(self):
        decision = self._resume_once
        self._resume_once = None
        return decision


def test_execute_inline_replays_resume_without_runtime() -> None:
    manager = ExecutionManager(
        telemetry=SimpleNamespace(emit=lambda trace: None),
        cooldown_manager=None,
        record_decay_execution=lambda execution: None,
        behavior_to_scene_type=lambda behavior_id: "attention_scene",
        async_executor_enabled=False,
    )
    resumed = _decision("perform_attention", trace_id="trace-resume")
    executor = _ResumeExecutor(resumed)
    initial = _decision("perform_greeting", trace_id="trace-start")
    result = SimpleNamespace(execution_results=[])

    manager.execute_inline(result, initial, arbitration_runtime=None, executor=executor)

    assert [item.behavior_id for item in result.execution_results] == ["perform_greeting", "perform_attention"]
    assert executor.executed == ["perform_greeting", "perform_attention"]
def test_drain_async_results_executes_resumed_decisions_without_runtime() -> None:
    manager = ExecutionManager(
        telemetry=SimpleNamespace(emit=lambda trace: None),
        cooldown_manager=None,
        record_decay_execution=lambda execution: None,
        behavior_to_scene_type=lambda behavior_id: "attention_scene",
        async_executor_enabled=True,
    )
    executor = _FakeExecutor()
    first = _decision("perform_greeting", trace_id="trace-1")
    resumed = _decision("perform_attention", trace_id="trace-2")
    outbox: Queue = Queue()
    outbox.put_nowait(
        AsyncExecutionDrainItem(
            decision=first,
            execution=executor.execute(first),
            resumed_decisions=[resumed],
            started_at=1.0,
            ended_at=2.0,
        )
    )
    result = SimpleNamespace(execution_results=[])

    manager.drain_async_results(result, arbitration_runtime=None, outbox=outbox, executor=executor)

    assert [item.behavior_id for item in result.execution_results] == ["perform_greeting", "perform_attention"]
    assert executor.executed == ["perform_greeting", "perform_attention"]



def test_health_monitor_ignores_total_failures_and_recovers_long_task_streak() -> None:
    monitor = RuntimeHealthMonitor(degraded_after_failures=3, stale_long_task_limit=2)

    monitor.record_source_health("camera", {"read_failures": 0, "total_failures": 3, "status": "ok"})
    assert monitor.snapshot()["failure_streaks"]["source:camera"] == 0
    assert monitor.degraded is False

    monitor.record_long_task_stale_drop()
    monitor.record_long_task_stale_drop()
    assert monitor.degraded is True
    assert monitor.snapshot()["long_task_stale_streak"] == 2

    monitor.record_long_task_healthy()
    assert monitor.snapshot()["long_task_stale_streak"] == 0
    assert monitor.degraded is False



def test_state_machine_restores_pre_safety_state_when_resolved() -> None:
    sm = InteractionStateMachine()
    sm.on_notice_human(target_id="alice")
    sm.on_mutual_attention(target_id="alice")
    assert sm.current_state == InteractionState.MUTUAL_ATTENTION

    sm.on_safety_event(reason="obstacle")
    assert sm.current_state == InteractionState.SAFETY_OVERRIDE
    decision = sm.transition_decision(InteractionEvent.SAFETY_RESOLVED)
    assert decision.target == "MUTUAL_ATTENTION"

    sm.on_safety_resolved(reason="cleared")
    assert sm.current_state == InteractionState.MUTUAL_ATTENTION
    assert sm.snapshot()["target_id"] == "alice"



def test_long_task_capture_happens_only_after_gating_allows_submission() -> None:
    coordinator = LongTaskCoordinator()
    service = _CaptureAwareSlowService()
    scene = SceneCandidate(
        scene_id="scene-1",
        trace_id="trace-1",
        scene_type="attention_scene",
        based_on_events=["evt-1"],
        score_hint=0.7,
        valid_until_monotonic=100.0,
        target_id="alice",
    )
    collected = SimpleNamespace(packets={"camera": SimpleNamespace(payload=b"img", frame_index=7)}, frame_seq=7, collected_at=1.0)

    coordinator._last_submit_at_by_target["alice"] = time.monotonic()
    assert coordinator.submit_or_query(service, scene, collected) is None
    assert service.capture_calls == 0



def test_telemetry_sinks_bound_buffer_growth() -> None:
    aggregate = AggregatingTelemetrySink(max_traces=3, max_stage_samples=2)
    memory = InMemoryTelemetrySink(max_traces=2)

    for idx in range(5):
        trace = StageTrace(
            trace_id=f"trace-{idx}",
            stage="runtime",
            status="ok",
            started_at=1.0,
            ended_at=1.0 + (idx + 1) * 0.001,
            payload={"index": idx},
        )
        aggregate.emit(trace)
        memory.emit(trace)

    aggregate_snapshot = aggregate.snapshot()
    memory_snapshot = memory.snapshot()
    assert aggregate_snapshot["trace_count"] == 5
    assert aggregate_snapshot["buffered_trace_count"] == 3
    assert memory_snapshot["trace_count"] == 5
    assert memory_snapshot["buffered_trace_count"] == 2
