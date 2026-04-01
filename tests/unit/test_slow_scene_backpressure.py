from __future__ import annotations

from threading import Event
from time import monotonic

from robot_life.common.config import SlowSceneConfig
from robot_life.common.schemas import SceneCandidate, SceneJson
from robot_life.slow_scene.schema import SlowSceneRequest
from robot_life.slow_scene.service import SlowSceneService


class _BlockedAdapter:
    def __init__(self, gate: Event) -> None:
        self._gate = gate
        self._initialized = False

    def initialize(self) -> None:
        self._gate.wait(timeout=5.0)
        self._initialized = True

    def understand_scene(self, image, context, timeout_ms=5000):
        return SceneJson(
            scene_type="attention_scene",
            confidence=0.9,
            involved_targets=["user_1"],
            emotion_hint="curious",
            urgency_hint="low",
            recommended_strategy="nonverbal_first",
            escalate_to_cloud=False,
        )


def _scene(scene_id: str, scene_type: str, target_id: str | None) -> SceneCandidate:
    return SceneCandidate(
        scene_id=scene_id,
        trace_id=f"trace-{scene_id}",
        scene_type=scene_type,
        based_on_events=[],
        score_hint=0.5,
        valid_until_monotonic=monotonic() + 10.0,
        target_id=target_id,
        payload={},
    )


def test_slow_scene_dedup_key_follows_target_and_scene_type() -> None:
    first = SlowSceneRequest.from_scene(
        _scene("scene-a", "attention_scene", "user_1"),
        dedup_bucket_s=2.0,
        dedup_at_monotonic=10.1,
    )
    second = SlowSceneRequest.from_scene(
        _scene("scene-b", "attention_scene", "user_1"),
        dedup_bucket_s=2.0,
        dedup_at_monotonic=11.9,
    )
    third = SlowSceneRequest.from_scene(
        _scene("scene-c", "greeting_scene", "user_1"),
        dedup_bucket_s=2.0,
        dedup_at_monotonic=11.9,
    )
    fourth = SlowSceneRequest.from_scene(
        _scene("scene-d", "attention_scene", "user_1"),
        dedup_bucket_s=2.0,
        dedup_at_monotonic=12.1,
    )

    assert first.dedup_key == second.dedup_key
    assert first.dedup_key != third.dedup_key
    assert first.dedup_key != fourth.dedup_key
    assert "scene-a" not in first.dedup_key
    assert "scene-b" not in second.dedup_key


def test_slow_scene_caps_pending_per_target_without_stale_pending() -> None:
    gate = Event()
    service = SlowSceneService(
        model_adapter=_BlockedAdapter(gate),
        use_qwen=False,
        config=SlowSceneConfig(
            use_qwen=False,
            queue_size=4,
            request_timeout_ms=1_000,
            max_pending_per_target=1,
        ),
    )

    scene_1 = _scene("scene-1", "attention_scene", "user_1")
    scene_2 = _scene("scene-2", "greeting_scene", "user_1")

    try:
        request_1 = service.submit(scene_1, context="first")
        request_2 = service.submit(scene_2, context="second")

        assert service.get_request_state(request_1) == "CANCELLED"
        assert service.get_request_state(request_2) == "PENDING"

        health = service.health()
        assert health.pending_requests == 1
        assert health.dropped_requests == 0
    finally:
        gate.set()
        service.close()
