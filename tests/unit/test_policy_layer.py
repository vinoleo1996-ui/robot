from robot_life.common.schemas import DecisionMode, EventPriority, SceneCandidate
from robot_life.event_engine.policy_layer import PolicyLayer


def _scene(
    scene_type: str,
    *,
    score_hint: float = 1.0,
    payload: dict | None = None,
) -> SceneCandidate:
    return SceneCandidate(
        scene_id="scene-1",
        trace_id="trace-1",
        scene_type=scene_type,
        based_on_events=[],
        score_hint=score_hint,
        valid_until_monotonic=1.0,
        payload=payload or {},
    )


def test_policy_layer_marks_safety_as_urgent_and_interrupts() -> None:
    layer = PolicyLayer(
        degrade_score_threshold=0.55,
        priority_policies={
            EventPriority.P0: ("immediate", 0),
            EventPriority.P1: ("soft", 5000),
            EventPriority.P2: ("queue", 10000),
            EventPriority.P3: ("never", 15000),
        },
    )
    decision = layer.evaluate(
        _scene("safety_alert_scene"),
        rule={
            "priority": EventPriority.P0,
            "degraded_behavior": None,
            "hard_interrupt": True,
        },
        current_priority=EventPriority.P2,
    )

    assert decision.response_level == "urgent"
    assert decision.mode == DecisionMode.HARD_INTERRUPT


def test_policy_layer_marks_weak_attention_as_observe() -> None:
    layer = PolicyLayer(
        degrade_score_threshold=0.55,
        priority_policies={
            EventPriority.P0: ("immediate", 0),
            EventPriority.P1: ("soft", 5000),
            EventPriority.P2: ("queue", 10000),
            EventPriority.P3: ("never", 15000),
        },
    )
    decision = layer.evaluate(
        _scene(
            "attention_scene",
            score_hint=0.7,
            payload={"engagement_score": 0.42, "interaction_state": "noticed_human"},
        ),
        rule={
            "priority": EventPriority.P2,
            "degraded_behavior": "attention_minimal",
            "hard_interrupt": False,
        },
        current_priority=None,
    )

    assert decision.response_level == "observe"
    assert decision.mode == DecisionMode.EXECUTE


def test_policy_layer_suppresses_low_priority_social_scene_when_do_not_disturb() -> None:
    layer = PolicyLayer(
        degrade_score_threshold=0.55,
        priority_policies={
            EventPriority.P0: ("immediate", 0),
            EventPriority.P1: ("soft", 5000),
            EventPriority.P2: ("queue", 10000),
            EventPriority.P3: ("never", 15000),
        },
    )
    decision = layer.evaluate(
        _scene(
            "attention_scene",
            payload={"robot_do_not_disturb": True},
        ),
        rule={
            "priority": EventPriority.P2,
            "degraded_behavior": "attention_minimal",
            "hard_interrupt": False,
        },
        current_priority=None,
    )

    assert decision.response_level == "suppressed"
    assert decision.mode == DecisionMode.DROP
