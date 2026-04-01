from pathlib import Path

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.behavior.safety_guard import BehaviorSafetyGuard
from robot_life.common.config import load_safety_config
from robot_life.common.schemas import ArbitrationResult, DecisionMode, EventPriority

ROOT = Path(__file__).resolve().parents[2]


def _decision(
    *,
    decision_id: str,
    trace_id: str,
    behavior: str,
    priority: EventPriority,
    mode: DecisionMode = DecisionMode.EXECUTE,
    resume_previous: bool = True,
    reason: str = "test",
) -> ArbitrationResult:
    return ArbitrationResult(
        decision_id=decision_id,
        trace_id=trace_id,
        target_behavior=behavior,
        priority=priority,
        mode=mode,
        required_resources=["HeadMotion"],
        optional_resources=["FaceExpression"],
        degraded_behavior=None,
        resume_previous=resume_previous,
        reason=reason,
    )


def test_load_safety_config_from_default() -> None:
    config = load_safety_config(ROOT / "configs" / "safety" / "default.yaml")
    assert config.enabled is True
    assert "perform_safety_alert" in config.dangerous_behavior_allowlist
    assert "perform_tracking" in config.behavior_mutex
    assert "perform_greeting" in config.behavior_mutex


def test_safety_guard_blocks_unallowlisted_dangerous_behavior() -> None:
    guard = BehaviorSafetyGuard()
    outcome = guard.evaluate(
        _decision(
            decision_id="d1",
            trace_id="t1",
            behavior="perform_strike_action",
            priority=EventPriority.P2,
        ),
        current_decision=None,
    )
    assert outcome.allowed is False
    assert "dangerous_behavior_not_allowlisted" in outcome.reason


def test_safety_guard_mutex_requires_interrupt_for_equal_priority() -> None:
    guard = BehaviorSafetyGuard()
    current = _decision(
        decision_id="d-current",
        trace_id="t-current",
        behavior="perform_tracking",
        priority=EventPriority.P3,
    )
    blocked = guard.evaluate(
        _decision(
            decision_id="d-next",
            trace_id="t-next",
            behavior="perform_gesture_response",
            priority=EventPriority.P3,
            mode=DecisionMode.EXECUTE,
        ),
        current_decision=current,
    )
    allowed = guard.evaluate(
        _decision(
            decision_id="d-next2",
            trace_id="t-next2",
            behavior="perform_gesture_response",
            priority=EventPriority.P3,
            mode=DecisionMode.SOFT_INTERRUPT,
        ),
        current_decision=current,
    )
    assert blocked.allowed is False
    assert "mutex_conflict_requires_interrupt" in blocked.reason
    assert allowed.allowed is True


def test_behavior_executor_emergency_preempts_and_clears_resume_queue() -> None:
    resource_manager = ResourceManager()
    executor = BehaviorExecutor(resource_manager, safety_guard=BehaviorSafetyGuard())

    baseline = _decision(
        decision_id="d-base",
        trace_id="t-base",
        behavior="perform_tracking",
        priority=EventPriority.P3,
        mode=DecisionMode.EXECUTE,
    )
    soft_interrupt = _decision(
        decision_id="d-soft",
        trace_id="t-soft",
        behavior="perform_greeting",
        priority=EventPriority.P1,
        mode=DecisionMode.SOFT_INTERRUPT,
        resume_previous=True,
    )
    emergency = _decision(
        decision_id="d-estop",
        trace_id="t-estop",
        behavior="perform_safety_alert",
        priority=EventPriority.P0,
        mode=DecisionMode.HARD_INTERRUPT,
        resume_previous=False,
        reason="emergency collision alert",
    )

    _ = executor.execute(baseline)
    _ = executor.execute(soft_interrupt)
    assert executor.get_debug_snapshot()["pending_resume_decisions"] > 0

    # Create one long-lived external grant and verify emergency path clears it.
    external_grant = resource_manager.request_grant(
        trace_id="external-trace",
        decision_id="external-decision",
        behavior_id="external_behavior",
        required_resources=["AudioOut"],
        optional_resources=[],
        priority=1,
        duration_ms=30_000,
    )
    assert external_grant.granted is True
    assert "owned_by" in resource_manager.get_resource_status()["AudioOut"]

    result = executor.execute(emergency)
    assert result.status == "finished"
    assert executor.get_debug_snapshot()["pending_resume_decisions"] == 0
    assert executor.pop_resume_decision() is None
    assert resource_manager.get_resource_status()["AudioOut"] == "free"


def test_behavior_executor_hard_interrupt_without_resume_clears_stale_resume_queue() -> None:
    executor = BehaviorExecutor(ResourceManager(), safety_guard=BehaviorSafetyGuard())

    baseline = _decision(
        decision_id="d-base",
        trace_id="t-base",
        behavior="perform_tracking",
        priority=EventPriority.P3,
        mode=DecisionMode.EXECUTE,
    )
    soft_interrupt = _decision(
        decision_id="d-soft",
        trace_id="t-soft",
        behavior="perform_greeting",
        priority=EventPriority.P1,
        mode=DecisionMode.SOFT_INTERRUPT,
        resume_previous=True,
    )
    hard_interrupt = _decision(
        decision_id="d-hard",
        trace_id="t-hard",
        behavior="perform_attention",
        priority=EventPriority.P1,
        mode=DecisionMode.HARD_INTERRUPT,
        resume_previous=False,
        reason="operator_override",
    )

    _ = executor.execute(baseline)
    _ = executor.execute(soft_interrupt)
    assert executor.get_debug_snapshot()["pending_resume_decisions"] == 1

    _ = executor.execute(hard_interrupt)

    assert executor.get_debug_snapshot()["pending_resume_decisions"] == 0
    assert executor.pop_resume_decision() is None


def test_behavior_executor_finished_behavior_does_not_block_followup_mutex_behavior() -> None:
    executor = BehaviorExecutor(ResourceManager(), safety_guard=BehaviorSafetyGuard())

    first = _decision(
        decision_id="d-first",
        trace_id="t-first",
        behavior="perform_gesture_response",
        priority=EventPriority.P1,
        mode=DecisionMode.EXECUTE,
    )
    second = _decision(
        decision_id="d-second",
        trace_id="t-second",
        behavior="perform_greeting",
        priority=EventPriority.P1,
        mode=DecisionMode.EXECUTE,
    )

    first_result = executor.execute(first)
    second_result = executor.execute(second)

    assert first_result.status == "finished"
    assert second_result.status == "finished"
