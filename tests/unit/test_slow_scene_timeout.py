from time import sleep, monotonic

from robot_life.common.config import SlowSceneConfig
from robot_life.common.schemas import EventPriority, SceneCandidate, SceneJson
from robot_life.slow_scene.service import SlowSceneService


class _SlowAdapter:
    def initialize(self) -> None:
        return None

    def understand_scene(self, image, context, timeout_ms=5000):
        sleep(0.02)
        return SceneJson(
            scene_type="attention_scene",
            confidence=0.9,
            involved_targets=[],
            emotion_hint="curious",
            urgency_hint="low",
            recommended_strategy="nonverbal_first",
            escalate_to_cloud=False,
        )


class _InitAwareAdapter:
    def __init__(self) -> None:
        self._initialized = False
        self.init_calls = 0

    def initialize(self) -> None:
        self.init_calls += 1
        self._initialized = True

    def understand_scene(self, image, context, timeout_ms=5000):
        return SceneJson(
            scene_type="attention_scene",
            confidence=0.88,
            involved_targets=[],
            emotion_hint="calm",
            urgency_hint="low",
            recommended_strategy="observe",
            escalate_to_cloud=False,
        )


def test_slow_scene_timeout_fallback() -> None:
    config = SlowSceneConfig(
        use_qwen=False,
        queue_size=2,
        request_timeout_ms=1,
        trigger_min_score=0.8,
    )
    service = SlowSceneService(model_adapter=_SlowAdapter(), use_qwen=False, config=config)
    scene = SceneCandidate(
        scene_id="scene_1",
        trace_id="trace_1",
        scene_type="attention_scene",
        based_on_events=["event_1"],
        score_hint=0.5,
        valid_until_monotonic=monotonic() + 5,
        target_id="user_1",
        payload={},
    )

    try:
        request_id = service.submit(scene, image={"frame": 1}, priority=EventPriority.P2, timeout_ms=1)
        deadline = monotonic() + 2
        result = None
        while monotonic() < deadline:
            result = service.query(request_id=request_id)
            if result is not None:
                break
            sleep(0.01)

        assert result is not None
        assert result.status.value == "TIMED_OUT"
        assert result.timeout_flag is True
    finally:
        service.close()


def test_build_scene_json_initializes_adapter_once_for_sync_path() -> None:
    adapter = _InitAwareAdapter()
    service = SlowSceneService(
        model_adapter=adapter,
        use_qwen=False,
        config=SlowSceneConfig(use_qwen=False),
    )
    scene = SceneCandidate(
        scene_id="scene_2",
        trace_id="trace_2",
        scene_type="attention_scene",
        based_on_events=["event_2"],
        score_hint=0.6,
        valid_until_monotonic=monotonic() + 5,
        target_id=None,
        payload={},
    )

    try:
        first = service.build_scene_json(scene, image={"frame": 1}, context="sync-1")
        second = service.build_scene_json(scene, image={"frame": 2}, context="sync-2")
        assert first.scene_type == "attention_scene"
        assert second.scene_type == "attention_scene"
        assert adapter.init_calls == 1
    finally:
        service.close()
