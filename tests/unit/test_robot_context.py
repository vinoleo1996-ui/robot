from robot_life.common.robot_context import RobotContextStore


class _Execution:
    def __init__(self, behavior_id: str, status: str, target_id: str | None = None, ended_at: float = 1.0) -> None:
        self.behavior_id = behavior_id
        self.status = status
        self.target_id = target_id
        self.ended_at = ended_at


def test_robot_context_store_tracks_active_target_and_recent_interactions() -> None:
    store = RobotContextStore(mode="demo")
    store.sync(
        interaction_snapshot={"target_id": "person_track_001"},
        active_execution=_Execution("perform_greeting", "running", target_id="person_track_001"),
        execution_results=[_Execution("perform_attention", "finished", target_id="person_track_001", ended_at=0.5)],
    )

    snapshot = store.snapshot()
    assert snapshot["mode"] == "demo"
    assert snapshot["current_interaction_target"] == "person_track_001"
    assert snapshot["active_behavior_id"] == "perform_greeting"
    assert snapshot["speaking"] is True
    assert snapshot["moving"] is True
    assert snapshot["recent_interactions"][0]["behavior_id"] == "perform_attention"
