from __future__ import annotations

from robot_life.common.schemas import SceneCandidate, SceneJson
from robot_life.slow_scene.schema import SlowSceneRequest, SlowSceneResult, SlowSceneStatus
from robot_life.slow_scene.worker import SlowSceneWorker


class _Clock:
    def __init__(self, start: float = 100.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _scene(scene_id: str, scene_type: str = "attention_scene", target_id: str | None = "user_1") -> SceneCandidate:
    return SceneCandidate(
        scene_id=scene_id,
        trace_id=f"trace-{scene_id}",
        scene_type=scene_type,
        based_on_events=[],
        score_hint=0.8,
        valid_until_monotonic=999999.0,
        target_id=target_id,
        payload={},
    )


def _result_for(scene: SceneCandidate, request_id: str, *, latency_ms: float = 10.0) -> SlowSceneResult:
    request = SlowSceneRequest.from_scene(
        scene,
        request_id=request_id,
        timeout_ms=1000,
        dedup_at_monotonic=100.0,
    )
    return SlowSceneResult.from_request(
        request,
        SceneJson(
            scene_type=scene.scene_type,
            confidence=scene.score_hint,
            involved_targets=[scene.target_id] if scene.target_id else [],
            emotion_hint="curious",
            urgency_hint="low",
            recommended_strategy="nonverbal_first",
            escalate_to_cloud=False,
        ),
        status=SlowSceneStatus.COMPLETED,
        started_at=100.0,
        ended_at=100.0 + (latency_ms / 1000.0),
    )


def test_slow_scene_worker_retains_only_bounded_recent_state(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("robot_life.slow_scene.worker.monotonic", clock)

    worker = SlowSceneWorker(
        adapter=None,
        max_results=3,
        state_ttl_s=10.0,
        max_latency_samples=3,
    )

    try:
        for index in range(5):
            scene = _scene("scene-shared", target_id="user_1")
            request_id = f"req-{index}"
            result = _result_for(scene, request_id, latency_ms=5.0 + index)
            worker._store_result(result)
            clock.advance(1.0)

        assert len(worker._results) == 3
        assert len(worker._request_state) == 3
        assert len(worker._request_state_updated_at) == 3
        assert len(worker._latest_by_scene) == 1
        assert len(worker._latencies_ms) == 3

        latest = worker.query(scene_id="scene-shared")
        assert latest is not None
        assert latest.request_id == "req-4"

        clock.advance(11.0)
        health = worker.health()

        assert health.completed_requests == 0
        assert health.pending_requests == 0
        assert health.queue_depth >= 0
        assert len(worker._results) == 0
        assert len(worker._request_state) == 0
        assert len(worker._latest_by_scene) == 0
        assert len(worker._cancelled) == 0
        assert len(worker._latencies_ms) == 0
    finally:
        worker.stop(join=False)


def test_slow_scene_worker_prunes_cancelled_state(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("robot_life.slow_scene.worker.monotonic", clock)

    worker = SlowSceneWorker(adapter=None, max_results=3, state_ttl_s=10.0, max_latency_samples=3)

    try:
        for index in range(5):
            assert worker.cancel(f"cancel-{index}") is True
            clock.advance(0.5)

        assert len(worker._cancelled) == 3
        assert len(worker._request_state) == 3

        clock.advance(11.0)
        _ = worker.health()

        assert len(worker._cancelled) == 0
        assert len(worker._request_state) == 0
    finally:
        worker.stop(join=False)
