from pathlib import Path

from robot_life.common.config import load_slow_scene_config
from robot_life.slow_scene.service import SlowSceneService, _is_gguf_model_path

ROOT = Path(__file__).resolve().parents[2]


def test_load_slow_scene_config_with_qwen_fields() -> None:
    config = load_slow_scene_config(ROOT / "configs" / "slow_scene" / "default.yaml")
    assert config.queue_size == 8
    assert config.request_timeout_ms == 8000
    assert config.dedup_time_bucket_s == 2.0
    assert config.use_qwen is True
    assert config.model_path == str(ROOT / "models" / "qwen" / "Qwen-2B-gguf")
    assert config.adapter_config["device"] == "cuda"
    assert config.adapter_config["n_ctx"] == 4096
    assert config.adapter_config["max_new_tokens"] == 704
    assert config.adapter_config["enable_continuation"] is True
    assert config.adapter_config["temperature"] == 0.0
    assert config.adapter_config["sample_interval_s"] == 5.0


def test_slow_scene_service_respects_queue_capacity() -> None:
    config = load_slow_scene_config(ROOT / "configs" / "slow_scene" / "default.yaml")
    service = SlowSceneService(use_qwen=False, config=config)
    try:
        health = service.health()
        assert health.queue_capacity == config.queue_size
    finally:
        service.close()


def test_is_gguf_model_path_supports_file_and_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "model.gguf"
    file_path.write_bytes(b"gguf")
    assert _is_gguf_model_path(str(file_path)) is True

    model_dir = tmp_path / "gguf_dir"
    model_dir.mkdir()
    (model_dir / "qwen-model.gguf").write_bytes(b"gguf")
    assert _is_gguf_model_path(str(model_dir)) is True

    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    assert _is_gguf_model_path(str(empty_dir)) is False
