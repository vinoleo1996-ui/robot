from __future__ import annotations

from robot_life.common.schemas import DecisionMode, EventPriority, SceneCandidate
from robot_life.runtime.scene_ops import scene_priority, set_scene_priority


class _CountingArbitrator:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, scene: SceneCandidate, current_priority: EventPriority | None = None):
        self.calls += 1
        return type(
            "Decision",
            (),
            {
                "priority": EventPriority.P1 if scene.scene_type == "greeting_scene" else EventPriority.P2,
                "mode": DecisionMode.EXECUTE,
            },
        )()


def test_scene_priority_uses_cached_payload_value_before_arbitrator() -> None:
    scene = SceneCandidate(
        scene_id="scene-1",
        trace_id="trace-1",
        scene_type="greeting_scene",
        based_on_events=[],
        score_hint=0.8,
        valid_until_monotonic=10.0,
        payload={"priority": "P1"},
    )
    arbitrator = _CountingArbitrator()

    priority = scene_priority(scene, arbitrator)

    assert priority == EventPriority.P1
    assert arbitrator.calls == 0


def test_set_scene_priority_persists_priority_for_future_lookups() -> None:
    scene = SceneCandidate(
        scene_id="scene-2",
        trace_id="trace-2",
        scene_type="attention_scene",
        based_on_events=[],
        score_hint=0.6,
        valid_until_monotonic=10.0,
    )
    arbitrator = _CountingArbitrator()

    set_scene_priority(scene, EventPriority.P2)
    first = scene_priority(scene, arbitrator)
    second = scene_priority(scene, arbitrator)

    assert first == EventPriority.P2
    assert second == EventPriority.P2
    assert arbitrator.calls == 0
