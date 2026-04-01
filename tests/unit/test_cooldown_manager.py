from robot_life.common.schemas import EventPriority
from robot_life.event_engine.cooldown_manager import CooldownManager


def test_p0_bypasses_outer_cooldown_layers() -> None:
    manager = CooldownManager(global_cooldown_s=10.0, scene_cooldowns={"safety_alert_scene": 30.0})
    manager.record_execution("safety_alert_scene", target_id=None)

    allowed, reason = manager.check("safety_alert_scene", target_id=None, priority=EventPriority.P0)

    assert allowed is True
    assert reason == "ok"


def test_non_p0_still_obeys_scene_cooldown() -> None:
    manager = CooldownManager(global_cooldown_s=0.0, scene_cooldowns={"attention_scene": 5.0})
    manager.record_execution("attention_scene", target_id=None)

    allowed, reason = manager.check("attention_scene", target_id=None, priority=EventPriority.P2)

    assert allowed is False
    assert reason.startswith("scene_cooldown:attention_scene:")


def test_active_target_suppresses_weak_social_bids_from_other_targets() -> None:
    manager = CooldownManager(global_cooldown_s=0.0)

    allowed, reason = manager.check(
        "attention_scene",
        target_id="user-b",
        priority=EventPriority.P2,
        active_target_id="user-a",
    )

    assert allowed is False
    assert reason == "context_suppression:active_target:user-a"


def test_saturation_suppresses_repeated_low_priority_social_triggers() -> None:
    manager = CooldownManager(global_cooldown_s=0.0, saturation_window_s=30.0, saturation_limit=2)
    manager.record_execution("attention_scene", target_id="user-a")
    manager.record_execution("gesture_bond_scene", target_id="user-a")

    allowed, reason = manager.check("ambient_tracking_scene", target_id="user-a", priority=EventPriority.P3)

    assert allowed is False
    assert reason == "saturation:2_within_30s"


def test_robot_busy_suppresses_low_priority_social_trigger() -> None:
    manager = CooldownManager(global_cooldown_s=0.0)

    allowed, reason = manager.check(
        "attention_scene",
        target_id="user-a",
        priority=EventPriority.P2,
        robot_busy=True,
        active_behavior_id="perform_greeting",
    )

    assert allowed is False
    assert reason == "context_suppression:robot_busy:perform_greeting"
