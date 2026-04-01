from __future__ import annotations

from types import SimpleNamespace

from robot_life.common.schemas import SceneCandidate
from robot_life.runtime.scene_coordinator import SceneCoordinator
from robot_life.runtime.target_governor import TargetGovernor


class _FakeCooldownManager:
    def check(self, *args, **kwargs):
        return True, None


class _FakeContextStore:
    def snapshot(self):
        return {"mode": "demo", "do_not_disturb": False}


class _FakeStateMachine:
    def __init__(self, target_id=None):
        self.current_target_id = target_id


class _FakeExecutor:
    tick_execution_enabled = False

    def get_current_execution(self):
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


def test_target_governor_keeps_sticky_owner_when_scores_are_close() -> None:
    recorded: list[tuple[str, str]] = []

    def submit_batch_without_runtime(scenes, arbitrator):
        return []

    def record_batch_outcome(*args, **kwargs):
        return False

    coordinator = SceneCoordinator(
        telemetry=SimpleNamespace(emit=lambda trace: None),
        cooldown_manager=_FakeCooldownManager(),
        interaction_state_machine=_FakeStateMachine(target_id="alice"),
        robot_context_store=_FakeContextStore(),
        arbitration_batch_window_ms=40,
        max_scenes_per_cycle=4,
        submit_batch_without_runtime=submit_batch_without_runtime,
        record_batch_outcome=record_batch_outcome,
        target_governor=TargetGovernor(switch_margin=0.2),
    )
    result = SimpleNamespace(
        scene_candidates=[
            _scene("attention_scene", "alice", 0.72, "trace-a"),
            _scene("attention_scene", "bob", 0.79, "trace-b"),
        ],
        scene_batches={},
        arbitration_results=[],
    )
    collected = SimpleNamespace(frame_seq=7, collected_at=10.0)

    coordinator.process_batch(
        result,
        collected=collected,
        interaction_snapshot={"episode_id": "episode-1", "target_id": "alice", "state": "ENGAGING"},
        arbitrator=None,
        arbitration_runtime=None,
        executor=_FakeExecutor(),
        slow_scene=None,
    )

    assert len(result.scene_candidates) == 1
    assert result.scene_candidates[0].target_id == "alice"
    assert result.scene_candidates[0].payload["ownership_status"] == "accepted"


def test_target_governor_switches_owner_when_new_target_is_much_stronger() -> None:
    governor = TargetGovernor(switch_margin=0.05)
    governor.govern([_scene("attention_scene", "alice", 0.6, "trace-a")], active_target_id="alice", interaction_snapshot={})
    decision = governor.govern(
        [
            _scene("attention_scene", "alice", 0.6, "trace-a2"),
            _scene("attention_scene", "bob", 0.9, "trace-b"),
        ],
        active_target_id="alice",
        interaction_snapshot={"target_id": "alice"},
    )
    assert decision.owner_target_id == "bob"
    assert decision.switched is True
    assert any(scene.target_id == "bob" for scene in decision.accepted)
