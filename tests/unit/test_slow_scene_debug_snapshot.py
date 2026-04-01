from robot_life.common.config import SlowSceneConfig
from robot_life.common.schemas import SceneCandidate, new_id, now_mono
from robot_life.slow_scene.service import SlowSceneService


def test_slow_scene_debug_snapshot_exposes_io_fields() -> None:
    service = SlowSceneService(
        use_qwen=False,
        config=SlowSceneConfig(
            use_qwen=False,
            queue_size=2,
            request_timeout_ms=500,
        ),
    )
    scene = SceneCandidate(
        scene_id=new_id(),
        trace_id=new_id(),
        scene_type="attention_scene",
        based_on_events=[],
        score_hint=0.4,
        valid_until_monotonic=now_mono() + 1.0,
    )
    request_id = service.submit(scene, context="unit-test")
    snapshot = service.debug_snapshot()
    service.cancel(request_id)
    service.close()

    assert snapshot["use_qwen_requested"] is False
    assert "health" in snapshot
    assert snapshot["last_submit"]["scene_type"] == "attention_scene"


def test_slow_scene_prefers_gguf_adapter_when_model_path_points_to_gguf(tmp_path, monkeypatch) -> None:
    from robot_life.perception.adapters.gguf_qwen_adapter import GGUFQwenVLAdapter

    def _fake_initialize(self) -> None:
        self._initialized = True

    monkeypatch.setattr(GGUFQwenVLAdapter, "initialize", _fake_initialize)

    model_dir = tmp_path / "qwen_gguf"
    model_dir.mkdir()
    (model_dir / "Qwen3.5-4B-BF16.gguf").write_bytes(b"gguf")
    (model_dir / "mmproj-BF16.gguf").write_bytes(b"gguf")

    service = SlowSceneService(
        use_qwen=True,
        config=SlowSceneConfig(
            use_qwen=True,
            model_path=str(model_dir),
            queue_size=2,
            request_timeout_ms=500,
        ),
    )
    snapshot = service.debug_snapshot()
    service.close()

    assert snapshot["use_qwen_requested"] is True
    assert snapshot["adapter_type"] == "GGUFQwenVLAdapter"
