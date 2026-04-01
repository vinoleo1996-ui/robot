from __future__ import annotations

from queue import Queue
from threading import Event
from types import SimpleNamespace

from robot_life.common.schemas import (
    ArbitrationResult,
    DecisionMode,
    EventPriority,
    ExecutionResult,
    SceneCandidate,
)
from robot_life.runtime.execution_manager import AsyncExecutionDrainItem, ExecutionManager
from robot_life.runtime.scene_coordinator import SceneCoordinator


class _FakeCooldownManager:
    def check(self, *args, **kwargs):
        return True, None


class _FakeContextStore:
    def snapshot(self):
        return {"mode": "demo", "do_not_disturb": False}


class _FakeStateMachine:
    current_target_id = None


class _FakeExecutor:
    tick_execution_enabled = False

    def __init__(self):
        self.executed = []

    def get_current_execution(self):
        return None

    def execute(self, decision):
        self.executed.append(decision.target_behavior)
        return ExecutionResult(
            execution_id="exec-1",
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


def _scene(scene_type: str, target_id: str, score: float, trace_id: str) -> SceneCandidate:
    return SceneCandidate(
        scene_id=f"scene:{scene_type}:{target_id}",
        trace_id=trace_id,
        scene_type=scene_type,
        based_on_events=["evt-1"],
        score_hint=score,
        valid_until_monotonic=100.0,
        target_id=target_id,
        payload={"scene_path": "social", "interaction_state": "ENGAGING", "engagement_score": score},
    )


def _decision_from_scene(scene: SceneCandidate) -> ArbitrationResult:
    return ArbitrationResult(
        decision_id=f"decision:{scene.scene_id}",
        trace_id=scene.trace_id,
        target_behavior="perform_greeting",
        priority=EventPriority.P1,
        mode=DecisionMode.EXECUTE,
        required_resources=["motion"],
        optional_resources=[],
        degraded_behavior=None,
        resume_previous=False,
        reason="scene_match",
        target_id=scene.target_id,
        scene_type=scene.scene_type,
        engagement_score=scene.score_hint,
        scene_path="social",
        interaction_state="engaging",
        interaction_episode_id=scene.interaction_episode_id,
        scene_epoch=scene.scene_epoch,
        decision_epoch=f"decision-epoch:{scene.scene_id}",
    )


def test_scene_coordinator_processes_batches_through_callback() -> None:
    seen = []

    def submit_batch_without_runtime(scenes, arbitrator):
        return [SimpleNamespace(scene=scene, decision=_decision_from_scene(scene), outcome="executed", executed=True) for scene in scenes]

    def record_batch_outcome(result, *, outcome, collected, arbitration_runtime, executor, slow_scene):
        seen.append((outcome.scene.scene_id, outcome.decision.target_behavior))
        result.arbitration_results.append(outcome.decision)
        return True

    coordinator = SceneCoordinator(
        telemetry=SimpleNamespace(emit=lambda trace: None),
        cooldown_manager=_FakeCooldownManager(),
        interaction_state_machine=_FakeStateMachine(),
        robot_context_store=_FakeContextStore(),
        arbitration_batch_window_ms=40,
        max_scenes_per_cycle=4,
        submit_batch_without_runtime=submit_batch_without_runtime,
        record_batch_outcome=record_batch_outcome,
    )
    result = SimpleNamespace(scene_candidates=[_scene("attention_scene", "alice", 0.7, "trace-1")], scene_batches={}, arbitration_results=[])
    collected = SimpleNamespace(frame_seq=7, collected_at=10.0)
    coordinator.process_batch(
        result,
        collected=collected,
        interaction_snapshot={"episode_id": "episode-1", "target_id": "alice", "state": "NOTICED_HUMAN"},
        arbitrator=None,
        arbitration_runtime=None,
        executor=_FakeExecutor(),
        slow_scene=None,
    )
    assert seen == [("scene:attention_scene:alice", "perform_greeting")]
    assert result.scene_batches["social"]
    assert result.scene_candidates[0].scene_epoch is not None


def test_execution_manager_dispatches_and_drains_results() -> None:
    manager = ExecutionManager(
        telemetry=SimpleNamespace(emit=lambda trace: None),
        cooldown_manager=None,
        record_decay_execution=lambda execution: None,
        behavior_to_scene_type=lambda behavior_id: "attention_scene",
        async_executor_enabled=True,
    )
    result = SimpleNamespace(execution_results=[])
    decision = _decision_from_scene(_scene("attention_scene", "alice", 0.7, "trace-2"))
    executor = _FakeExecutor()
    inbox = Queue()
    outbox = Queue()

    manager.dispatch_decision(
        result,
        decision,
        arbitration_runtime=None,
        executor=executor,
        executor_inbox=inbox,
        executor_outbox=outbox,
    )
    queued = inbox.get_nowait()
    assert queued.trace_id == decision.trace_id

    outbox.put_nowait(
        AsyncExecutionDrainItem(
            decision=decision,
            execution=executor.execute(decision),
            resumed_decisions=[],
            started_at=1.0,
            ended_at=2.0,
        )
    )
    manager.drain_async_results(result, arbitration_runtime=None, outbox=outbox)
    assert result.execution_results[0].behavior_id == "perform_greeting"

