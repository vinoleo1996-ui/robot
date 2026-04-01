from robot_life.behavior.manager import BehaviorManager
from robot_life.event_engine.policy_layer import PolicyDecision
from robot_life.common.schemas import DecisionMode, EventPriority, SceneCandidate


def _scene(scene_type: str) -> SceneCandidate:
    return SceneCandidate(
        scene_id="scene-1",
        trace_id="trace-1",
        scene_type=scene_type,
        based_on_events=[],
        score_hint=1.0,
        valid_until_monotonic=1.0,
    )


def test_behavior_manager_preserves_default_scene_plan() -> None:
    manager = BehaviorManager()
    plan = manager.plan(
        _scene("greeting_scene"),
        rule={
            "target_behavior": "perform_greeting",
            "degraded_behavior": "greeting_visual_only",
            "required_resources": ["HeadMotion", "FaceExpression"],
            "optional_resources": ["AudioOut"],
            "resume_previous": True,
        },
        policy=PolicyDecision(
            priority=EventPriority.P1,
            mode=DecisionMode.EXECUTE,
            response_level="full",
            reason="policy:full",
        ),
    )

    assert plan.target_behavior == "perform_greeting"
    assert plan.degraded_behavior == "greeting_visual_only"
    assert plan.required_resources == ["HeadMotion", "FaceExpression"]
    assert plan.optional_resources == ["AudioOut"]
    assert plan.resume_previous is True


def test_behavior_manager_preserves_custom_scene_override() -> None:
    manager = BehaviorManager()
    plan = manager.plan(
        _scene("custom_scene"),
        rule={
            "target_behavior": "perform_custom",
            "degraded_behavior": "custom_visual_only",
            "required_resources": ["HeadMotion"],
            "optional_resources": ["AudioOut"],
            "resume_previous": False,
        },
        policy=PolicyDecision(
            priority=EventPriority.P1,
            mode=DecisionMode.SOFT_INTERRUPT,
            response_level="acknowledge",
            reason="policy:acknowledge",
        ),
    )

    assert plan.target_behavior == "perform_custom"
    assert plan.degraded_behavior == "custom_visual_only"
    assert plan.resume_previous is False
