from __future__ import annotations

from pathlib import Path

from robot_life.behavior.decay_tracker import BehaviorDecayTracker
from robot_life.behavior.behavior_registry import BehaviorRegistry
from robot_life.behavior.bt_nodes import run_node
from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.common.config import load_behavior_config
from robot_life.common.state_machine import InteractionStateMachine, InteractionState
from robot_life.common.schemas import ArbitrationResult, DecisionMode, EventPriority
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.decision_queue import DecisionQueue

ROOT = Path(__file__).resolve().parents[2]


def _decision(
    *,
    decision_id: str,
    trace_id: str,
    behavior: str,
    priority: EventPriority,
    mode: DecisionMode,
    resume_previous: bool = True,
    degraded_behavior: str | None = None,
) -> ArbitrationResult:
    return ArbitrationResult(
        decision_id=decision_id,
        trace_id=trace_id,
        target_behavior=behavior,
        priority=priority,
        mode=mode,
        required_resources=["HeadMotion"],
        optional_resources=["FaceExpression"],
        degraded_behavior=degraded_behavior,
        resume_previous=resume_previous,
        reason="test",
    )


def test_arbitrator_resolves_interrupt_modes() -> None:
    arbitrator = Arbitrator()
    scene = type("Scene", (), {"scene_type": "safety_alert_scene", "trace_id": "trace_1"})()

    decision = arbitrator.decide(scene, current_priority=EventPriority.P2)
    assert decision.mode == DecisionMode.HARD_INTERRUPT


def test_arbitrator_degrades_low_score_scene() -> None:
    arbitrator = Arbitrator(degrade_score_threshold=0.6)
    scene = type(
        "Scene",
        (),
        {"scene_type": "greeting_scene", "trace_id": "trace_1", "score_hint": 0.2},
    )()
    decision = arbitrator.decide(scene, current_priority=None)
    assert decision.mode == DecisionMode.DEGRADE_AND_EXECUTE


def test_arbitrator_propagates_scene_context_into_decision() -> None:
    arbitrator = Arbitrator()
    scene = type(
        "Scene",
        (),
        {
            "scene_type": "stranger_attention_scene",
            "trace_id": "trace_ctx",
            "target_id": "user-7",
            "score_hint": 0.76,
            "payload": {
                "scene_path": "social",
                "interaction_state": "mutual_attention",
                "engagement_score": 0.76,
            },
        },
    )()
    decision = arbitrator.decide(scene, current_priority=None)
    assert decision.target_behavior == "perform_attention"
    assert decision.scene_type == "stranger_attention_scene"
    assert decision.target_id == "user-7"
    assert decision.scene_path == "social"
    assert decision.interaction_state == "mutual_attention"
    assert decision.engagement_score == 0.76


def test_decision_queue_orders_by_priority() -> None:
    queue = DecisionQueue()
    low = ArbitrationResult(
        decision_id="d1",
        trace_id="t1",
        target_behavior="perform_tracking",
        priority=EventPriority.P3,
        mode=DecisionMode.DROP,
        required_resources=[],
        optional_resources=[],
        degraded_behavior=None,
        resume_previous=True,
        reason="ambient",
    )
    high = ArbitrationResult(
        decision_id="d2",
        trace_id="t2",
        target_behavior="perform_safety_alert",
        priority=EventPriority.P0,
        mode=DecisionMode.HARD_INTERRUPT,
        required_resources=["AudioOut"],
        optional_resources=[],
        degraded_behavior=None,
        resume_previous=False,
        reason="alert",
    )

    assert queue.enqueue(low) is not None
    assert queue.enqueue(high) is not None
    assert queue.pop_next().decision_id == "d2"
    assert queue.pop_next().decision_id == "d1"


def test_arbitration_runtime_queues_and_drains() -> None:
    runtime = ArbitrationRuntime(arbitrator=Arbitrator())
    greeting_scene = type(
        "Scene",
        (),
        {"scene_type": "greeting_scene", "trace_id": "trace_1", "score_hint": 0.9},
    )()
    attention_scene = type(
        "Scene",
        (),
        {"scene_type": "attention_scene", "trace_id": "trace_2", "score_hint": 0.8},
    )()
    safety_scene = type(
        "Scene",
        (),
        {"scene_type": "safety_alert_scene", "trace_id": "trace_3", "score_hint": 0.9},
    )()

    first = runtime.submit(greeting_scene)
    assert first is not None
    assert first.priority == EventPriority.P1

    queued = runtime.submit(attention_scene)
    assert queued is None
    assert runtime.last_outcome == "queued"
    assert runtime.pending() == 1

    preempt = runtime.submit(safety_scene)
    assert preempt is not None
    assert preempt.mode == DecisionMode.HARD_INTERRUPT
    assert preempt.priority == EventPriority.P0
    assert runtime.last_outcome == "executed"

    drained = runtime.complete_active()
    assert drained is not None
    assert drained.mode == DecisionMode.EXECUTE
    assert drained.priority == EventPriority.P2


def test_executor_can_run_degraded_behavior() -> None:
    executor = BehaviorExecutor(ResourceManager())
    decision = ArbitrationResult(
        decision_id="d3",
        trace_id="t3",
        target_behavior="perform_greeting",
        priority=EventPriority.P1,
        mode=DecisionMode.DEGRADE_AND_EXECUTE,
        required_resources=["HeadMotion", "FaceExpression"],
        optional_resources=["AudioOut"],
        degraded_behavior="greeting_visual_only",
        resume_previous=True,
        reason="force_degrade",
    )

    execution = executor.execute(decision)
    assert execution.status == "finished"
    assert execution.degraded is True
    assert execution.behavior_id == "greeting_visual_only"


def test_executor_soft_interrupt_generates_resume_decision() -> None:
    executor = BehaviorExecutor(ResourceManager())
    baseline = _decision(
        decision_id="d-base",
        trace_id="t-base",
        behavior="perform_tracking",
        priority=EventPriority.P3,
        mode=DecisionMode.EXECUTE,
    )
    interrupting = _decision(
        decision_id="d-int",
        trace_id="t-int",
        behavior="perform_greeting",
        priority=EventPriority.P1,
        mode=DecisionMode.SOFT_INTERRUPT,
        resume_previous=True,
    )

    _ = executor.execute(baseline)
    _ = executor.execute(interrupting)

    resumed = executor.pop_resume_decision()
    assert resumed is not None
    assert resumed.target_behavior == "perform_tracking"
    assert resumed.mode == DecisionMode.EXECUTE
    assert resumed.resume_previous is False
    assert "resume_after_soft_interrupt" in resumed.reason
    assert executor.pop_resume_decision() is None


def test_executor_hard_interrupt_without_resume_discards_previous() -> None:
    executor = BehaviorExecutor(ResourceManager())
    baseline = _decision(
        decision_id="d-base",
        trace_id="t-base",
        behavior="perform_tracking",
        priority=EventPriority.P3,
        mode=DecisionMode.EXECUTE,
    )
    interrupting = _decision(
        decision_id="d-int",
        trace_id="t-int",
        behavior="perform_safety_alert",
        priority=EventPriority.P0,
        mode=DecisionMode.HARD_INTERRUPT,
        resume_previous=False,
    )

    _ = executor.execute(baseline)
    _ = executor.execute(interrupting)

    assert executor.pop_resume_decision() is None


def test_load_behavior_config_supports_both_shapes() -> None:
    nested = load_behavior_config(ROOT / "configs" / "behavior" / "default.yaml")
    flat = load_behavior_config(ROOT / "configs" / "behavior" / "behavior.default.yaml")

    assert "HeadMotion" in nested.resources.required_default
    assert "AudioOut" in nested.resources.optional_default
    assert "AudioOut" in flat.resources.available


def test_behavior_registry_covers_minimal_state_set() -> None:
    registry = BehaviorRegistry()
    expected_states = {
        "state_idle",
        "state_greet",
        "state_attention",
        "state_alert",
        "state_observe",
        "state_recover",
    }
    all_nodes = set()
    for behavior_id in (
        "perform_greeting",
        "perform_attention",
        "perform_safety_alert",
        "perform_tracking",
    ):
        all_nodes.update(registry.get(behavior_id).nodes)

    assert expected_states.issubset(all_nodes)


def test_behavior_state_nodes_execute_successfully() -> None:
    for node_name in (
        "state_idle",
        "state_greet",
        "state_attention",
        "state_alert",
        "state_observe",
        "state_recover",
    ):
        result = run_node(node_name=node_name, behavior_id="perform_greeting", degraded=False)
        assert result.status == "success"


def test_behavior_decay_tracker_reduces_strength_with_repetition() -> None:
    tracker = BehaviorDecayTracker(max_decay_count=3, min_strength=0.4, silent_probability_base=0.0)

    first_strength, _ = tracker.evaluate("greeting_scene", "user_1")
    tracker.record("greeting_scene", "user_1")
    second_strength, _ = tracker.evaluate("greeting_scene", "user_1")
    tracker.record("greeting_scene", "user_1")
    third_strength, _ = tracker.evaluate("greeting_scene", "user_1")

    assert first_strength > second_strength > third_strength
    assert third_strength >= 0.4


def test_interaction_state_machine_transitions_through_core_states() -> None:
    machine = InteractionStateMachine()

    assert machine.current_state == InteractionState.IDLE
    machine.on_notice_human(target_id="person_track_001")
    assert machine.current_state == InteractionState.NOTICED_HUMAN
    machine.on_mutual_attention(target_id="person_track_001")
    assert machine.current_state == InteractionState.MUTUAL_ATTENTION
    machine.on_engagement_bid(target_id="person_track_001")
    assert machine.current_state == InteractionState.ENGAGING
    machine.on_interaction_started(target_id="person_track_001")
    assert machine.current_state == InteractionState.ONGOING_INTERACTION
    assert machine.current_target_id == "person_track_001"
    machine.on_safety_event(reason="test_safety")
    assert machine.current_state == InteractionState.SAFETY_OVERRIDE
    machine.on_safety_resolved(reason="resolved")
    assert machine.current_state == InteractionState.RECOVERY


def test_interaction_state_machine_attention_loss_enters_recovery() -> None:
    machine = InteractionStateMachine()
    machine.on_notice_human(target_id="person_track_002")
    machine.on_mutual_attention(target_id="person_track_002")
    machine.on_attention_lost(target_id="person_track_002")

    snapshot = machine.snapshot()
    assert machine.current_state == InteractionState.RECOVERY
    assert snapshot["target_id"] == "person_track_002"
    assert snapshot["last_reason"] == "attention_lost"


def test_behavior_executor_history_is_bounded() -> None:
    executor = BehaviorExecutor()

    for index in range(700):
        executor._behavior_history.append(  # noqa: SLF001
            type(
                "Execution",
                (),
                {
                    "execution_id": f"exec-{index}",
                    "trace_id": f"trace-{index}",
                    "behavior_id": "perform_attention",
                    "status": "completed",
                    "interrupted": False,
                    "degraded": False,
                    "started_at": 0.0,
                    "ended_at": 0.0,
                },
            )()
        )
    snapshot = executor.get_debug_snapshot()
    assert snapshot["history_size"] == 512


def test_behavior_executor_tick_mode_can_step_and_finish() -> None:
    executor = BehaviorExecutor(tick_execution=True, tick_max_nodes=1)
    decision = _decision(
        decision_id="d-tick",
        trace_id="t-tick",
        behavior="perform_greeting",
        priority=EventPriority.P1,
        mode=DecisionMode.EXECUTE,
    )

    first = executor.execute(decision)
    assert first.status == "running"

    finished = None
    for _ in range(8):
        finished = executor.tick_active()
        if finished is not None:
            break

    assert finished is not None
    assert finished.status == "finished"
