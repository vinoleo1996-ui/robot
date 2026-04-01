import threading
import time

from robot_life.perception import registry as pipeline_registry_module
from robot_life.perception.base import PipelineBase, PipelineSpec
from robot_life.perception.registry import DEFAULT_PIPELINES
from robot_life.runtime.pipeline_factory import (
    NoOpPipeline,
    SingleDetectorPipeline,
    _apply_gpu_policy,
    _extract_nested_config,
    _try_build_audio_pipeline,
    _try_build_insightface_pipeline,
    _try_build_mediapipe_face_pipeline,
    _try_build_mediapipe_gaze_pipeline,
    _try_build_mediapipe_gesture_pipeline,
    build_pipeline_registry,
)


def test_default_pipelines_match_mainline_fast_reaction_set() -> None:
    assert [spec.name for spec in DEFAULT_PIPELINES] == ["face", "gesture", "gaze", "audio", "motion"]


class _CountingPipeline(PipelineBase):
    def __init__(self, spec: PipelineSpec) -> None:
        super().__init__(spec)
        self.calls = 0

    def initialize(self) -> None:
        self._running = True

    def process(self, frame):
        if not self._running:
            return []
        self.calls += 1
        return [self.calls]

    def close(self) -> None:
        self._running = False


class _FailingInitPipeline(PipelineBase):
    def initialize(self) -> None:
        raise RuntimeError("boom")

    def process(self, frame):
        return []

    def close(self) -> None:
        self._running = False


class _BlockingPipeline(PipelineBase):
    def __init__(self, spec: PipelineSpec, gate: threading.Event) -> None:
        super().__init__(spec)
        self._gate = gate

    def initialize(self) -> None:
        self._running = True

    def process(self, frame):
        self._gate.wait(timeout=1.0)
        return [{"ok": True}]

    def close(self) -> None:
        self._running = False


class _DelayedPipeline(PipelineBase):
    def __init__(self, spec: PipelineSpec, *, delay_s: float, marker: str) -> None:
        super().__init__(spec)
        self._delay_s = delay_s
        self._marker = marker

    def initialize(self) -> None:
        self._running = True

    def process(self, frame):
        time.sleep(self._delay_s)
        return [self._marker]

    def close(self) -> None:
        self._running = False


class _CoordinatedInitPipeline(PipelineBase):
    def __init__(self, spec: PipelineSpec, *, started: threading.Event, gate: threading.Event) -> None:
        super().__init__(spec)
        self._started = started
        self._gate = gate

    def initialize(self) -> None:
        self._running = True
        self._started.set()
        self._gate.wait(timeout=1.0)

    def process(self, frame):
        return []

    def close(self) -> None:
        self._running = False


def test_build_pipeline_registry_respects_enabled_flag() -> None:
    registry = build_pipeline_registry(
        enabled_pipelines=["face"],
        detector_cfg={"detectors": {"face": {"enabled": False}}},
    )
    pipeline = registry.get_pipeline("face")
    assert isinstance(pipeline, NoOpPipeline)
    assert pipeline.reason == "disabled_by_config"
    assert pipeline.spec.enabled is False


def test_build_pipeline_registry_applies_sample_rate_override_from_config() -> None:
    registry = build_pipeline_registry(
        enabled_pipelines=["face"],
        detector_cfg={"detectors": {"face": {"enabled": True, "sample_rate_hz": 5}}},
        mock_drivers=True,
    )
    pipeline = registry.get_pipeline("face")
    assert pipeline is not None
    assert pipeline.spec.sample_rate_hz == 5


def test_build_pipeline_registry_applies_runtime_budget_override_from_config() -> None:
    registry = build_pipeline_registry(
        enabled_pipelines=["face"],
        detector_cfg={"detectors": {"face": {"enabled": True, "runtime_budget_ms": 7.5}}},
        mock_drivers=True,
    )
    pipeline = registry.get_pipeline("face")
    assert pipeline is not None
    assert pipeline.spec.runtime_budget_ms == 7.5


def test_build_pipeline_registry_ignores_invalid_sample_rate_override() -> None:
    registry = build_pipeline_registry(
        enabled_pipelines=["face"],
        detector_cfg={"detectors": {"face": {"enabled": True, "sample_rate_hz": "bad-value"}}},
        mock_drivers=True,
    )
    pipeline = registry.get_pipeline("face")
    assert pipeline is not None
    assert pipeline.spec.sample_rate_hz == 10


def test_build_pipeline_registry_applies_fast_cycle_budget_from_detector_global() -> None:
    registry = build_pipeline_registry(
        enabled_pipelines=["face"],
        detector_cfg={
            "detectors": {"face": {"enabled": True}},
            "detector_global": {"fast_cycle_budget_ms": 24},
        },
        mock_drivers=True,
    )
    assert registry.get_cycle_budget_ms() == 24.0


def test_build_pipeline_registry_applies_fast_parallel_workers_from_detector_global() -> None:
    registry = build_pipeline_registry(
        enabled_pipelines=["face"],
        detector_cfg={
            "detectors": {"face": {"enabled": True}},
            "detector_global": {"fast_parallel_workers": 3},
        },
        mock_drivers=True,
    )
    assert registry.get_processing_workers() == 3


def test_extract_nested_config_merges_top_level_fields() -> None:
    config = _extract_nested_config(
        {
            "detector_type": "insightface",
            "enabled": True,
            "model_path": "/tmp/model.bin",
            "config": {"det_thresh": 0.5},
        }
    )
    assert config["det_thresh"] == 0.5
    assert config["model_path"] == "/tmp/model.bin"


def test_apply_gpu_policy_defaults_to_strict_realtime_pipelines() -> None:
    config = _apply_gpu_policy(PipelineSpec(name="face", source="camera"), {})
    assert config["require_gpu"] is True
    assert config["allow_cpu_fallback"] is False
    assert config["providers"][0] == "CUDAExecutionProvider"
    assert "CPUExecutionProvider" in config["providers"]


def test_apply_gpu_policy_motion_overrides_invalid_gpu_settings() -> None:
    config = _apply_gpu_policy(
        PipelineSpec(name="motion", source="camera"),
        {
            "require_gpu": True,
            "allow_cpu_fallback": True,
            "device": "cpu",
            "providers": ["CPUExecutionProvider"],
        },
    )
    assert config["require_gpu"] is True
    assert config["allow_cpu_fallback"] is False
    assert config["allow_cuda_fallback"] is False
    assert config["device"] == "cuda:0"
    assert config["providers"][0] == "CUDAExecutionProvider"


def test_apply_gpu_policy_audio_keeps_gpu_intent_for_semantic_backend() -> None:
    config = _apply_gpu_policy(
        PipelineSpec(name="audio", source="microphone"),
        {
            "require_gpu": True,
            "allow_cpu_fallback": False,
        },
    )
    assert config["require_gpu"] is True
    assert config["allow_cpu_fallback"] is False
    assert config["panns_device"] == "auto"
    assert config["whisper_device"] == "auto"


def test_insightface_pipeline_falls_back_when_dependency_missing(monkeypatch) -> None:
    from robot_life.perception.adapters import insightface_adapter

    monkeypatch.setattr(insightface_adapter, "insightface", None)
    pipeline = _try_build_insightface_pipeline(
        PipelineSpec(name="face", source="camera"),
        {},
        backend="insightface",
    )
    assert isinstance(pipeline, NoOpPipeline)
    assert pipeline.reason == "insightface_dependency_missing"


def test_insightface_pipeline_falls_back_when_runtime_init_fails(monkeypatch) -> None:
    from robot_life.perception.adapters import insightface_adapter

    class _StubInsightFace:
        __version__ = "0.2.1"

    class _BrokenInsightFacePipeline:
        def __init__(self, spec, config) -> None:
            raise TypeError("broken insightface runtime")

    monkeypatch.setattr(insightface_adapter, "insightface", _StubInsightFace())
    monkeypatch.setattr(insightface_adapter, "InsightFacePipeline", _BrokenInsightFacePipeline)
    pipeline = _try_build_insightface_pipeline(
        PipelineSpec(name="face", source="camera"),
        {},
        backend="insightface",
    )
    assert isinstance(pipeline, NoOpPipeline)
    assert pipeline.reason == "insightface_runtime_unavailable"


def test_mock_drivers_emit_gesture_detections(monkeypatch) -> None:
    registry = build_pipeline_registry(
        enabled_pipelines=["gesture"],
        detector_cfg={"detectors": {"gesture": {"enabled": True}}},
        mock_drivers=True,
    )
    registry.initialize_all()
    clock = iter([100.0, 100.0, 100.01, 100.1, 100.1, 100.11])
    monkeypatch.setattr(pipeline_registry_module, "monotonic", lambda: next(clock))
    first = registry.process_all({"camera": {"frame": 1}})
    second = registry.process_all({"camera": {"frame": 2}})
    registry.close_all()

    assert len(first) == 1
    assert first[0][1]["detections"] == []


def test_try_build_audio_pipeline_supports_panns_whisper_backend(monkeypatch) -> None:
    from robot_life.perception.adapters import panns_whisper_audio_adapter

    class _StubDetector:
        def __init__(self, config) -> None:
            self.config = config

        def is_ready(self) -> bool:
            return False

        def initialize(self) -> None:
            return None

        def process(self, frame):
            return []

        def close(self) -> None:
            return None

    monkeypatch.setattr(panns_whisper_audio_adapter, "PANNSWhisperAudioDetector", _StubDetector)
    pipeline = _try_build_audio_pipeline(
        PipelineSpec(name="audio", source="microphone"),
        {"panns_device": "auto", "whisper_enabled": True},
        backend="panns_whisper",
    )
    assert isinstance(pipeline, SingleDetectorPipeline)


def test_process_all_throttles_by_sample_rate_hz(monkeypatch) -> None:
    registry = pipeline_registry_module.PipelineRegistry()
    pipeline = _CountingPipeline(
        PipelineSpec(name="face", source="camera", sample_rate_hz=10),
    )
    registry.register_pipeline("face", pipeline)
    registry.initialize_all()

    clock = iter([100.0, 100.0, 100.001, 100.02, 100.12, 100.12, 100.121])
    monkeypatch.setattr(pipeline_registry_module, "monotonic", lambda: next(clock))

    first = registry.process_all({"camera": {"frame": 1}})
    second = registry.process_all({"camera": {"frame": 2}})
    third = registry.process_all({"camera": {"frame": 3}})

    registry.close_all()

    assert first == [("face", {"detections": [1]})]
    assert second == []
    assert third == [("face", {"detections": [2]})]
    assert pipeline.calls == 2


def test_process_all_applies_runtime_scale(monkeypatch) -> None:
    registry = pipeline_registry_module.PipelineRegistry()
    pipeline = _CountingPipeline(
        PipelineSpec(name="face", source="camera", sample_rate_hz=10),
    )
    registry.register_pipeline("face", pipeline)
    registry.initialize_all()

    clock = iter([100.0, 100.0, 100.001, 100.1, 100.21, 100.21, 100.211])
    monkeypatch.setattr(pipeline_registry_module, "monotonic", lambda: next(clock))

    first = registry.process_all({"camera": {"frame": 1}})
    registry.set_runtime_scale("face", 0.5)
    second = registry.process_all({"camera": {"frame": 2}})
    registry.set_runtime_scale("face", 1.0)
    third = registry.process_all({"camera": {"frame": 3}})

    registry.close_all()

    assert first == [("face", {"detections": [1]})]
    assert second == []
    assert third == [("face", {"detections": [2]})]
    assert pipeline.calls == 2


def test_process_all_without_sample_rate_keeps_existing_behavior(monkeypatch) -> None:
    registry = pipeline_registry_module.PipelineRegistry()
    pipeline = _CountingPipeline(PipelineSpec(name="face", source="camera"))
    registry.register_pipeline("face", pipeline)
    registry.initialize_all()

    monkeypatch.setattr(pipeline_registry_module, "monotonic", lambda: 200.0)

    first = registry.process_all({"camera": {"frame": 1}})
    second = registry.process_all({"camera": {"frame": 2}})

    registry.close_all()

    assert first == [("face", {"detections": [1]})]
    assert second == [("face", {"detections": [2]})]
    assert pipeline.calls == 2


def test_process_all_skips_pipeline_when_cycle_budget_would_be_exceeded() -> None:
    registry = pipeline_registry_module.PipelineRegistry()
    registry.set_cycle_budget_ms(10)
    first = _CountingPipeline(PipelineSpec(name="face", source="camera", runtime_budget_ms=6))
    second = _CountingPipeline(PipelineSpec(name="gesture", source="camera", runtime_budget_ms=6))
    registry.register_pipeline("face", first)
    registry.register_pipeline("gesture", second)
    registry.initialize_all()

    results = registry.process_all({"camera": {"frame": 1}})

    registry.close_all()

    assert results == [("face", {"detections": [1]})]
    assert first.calls == 1
    assert second.calls == 0
    stats = registry.snapshot_runtime_stats()
    assert stats["gesture"]["budget_skips"] == 1


def test_process_all_parallel_keeps_registration_order() -> None:
    registry = pipeline_registry_module.PipelineRegistry()
    registry.set_processing_workers(2)
    face = _DelayedPipeline(
        PipelineSpec(name="face", source="camera"),
        delay_s=0.03,
        marker="face",
    )
    gesture = _DelayedPipeline(
        PipelineSpec(name="gesture", source="camera"),
        delay_s=0.0,
        marker="gesture",
    )
    registry.register_pipeline("face", face)
    registry.register_pipeline("gesture", gesture)
    registry.initialize_all()

    results = registry.process_all({"camera": {"frame": 1}})

    registry.close_all()

    assert [item[0] for item in results] == ["face", "gesture"]
    assert results[0][1]["detections"] == ["face"]
    assert results[1][1]["detections"] == ["gesture"]


def test_pipeline_registry_initializes_enabled_pipelines_in_parallel() -> None:
    registry = pipeline_registry_module.PipelineRegistry()
    gate = threading.Event()
    face_started = threading.Event()
    gesture_started = threading.Event()
    registry.register_pipeline(
        "face",
        _CoordinatedInitPipeline(
            PipelineSpec(name="face", source="camera"),
            started=face_started,
            gate=gate,
        ),
    )
    registry.register_pipeline(
        "gesture",
        _CoordinatedInitPipeline(
            PipelineSpec(name="gesture", source="camera"),
            started=gesture_started,
            gate=gate,
        ),
    )

    worker = threading.Thread(target=registry.initialize_all, daemon=True)
    worker.start()
    try:
        assert face_started.wait(timeout=0.4)
        assert gesture_started.wait(timeout=0.4)
    finally:
        gate.set()
        worker.join(timeout=1.0)
        registry.close_all()

    statuses = registry.snapshot_pipeline_statuses()
    assert statuses["face"]["init_status"] == "ready"
    assert statuses["gesture"]["init_status"] == "ready"


def test_pipeline_registry_tracks_failed_pipeline_init_reason() -> None:
    registry = pipeline_registry_module.PipelineRegistry()
    registry.register_pipeline("face", _FailingInitPipeline(PipelineSpec(name="face", source="camera")))

    registry.initialize_all()

    status = registry.snapshot_pipeline_statuses()["face"]
    assert status["enabled"] is False
    assert status["init_status"] == "failed"
    assert "RuntimeError: boom" in str(status["reason"])


def test_pipeline_registry_snapshots_are_safe_during_processing() -> None:
    registry = pipeline_registry_module.PipelineRegistry()
    gate = threading.Event()
    pipeline = _BlockingPipeline(PipelineSpec(name="face", source="camera"), gate)
    registry.register_pipeline("face", pipeline)
    registry.initialize_all()

    errors: list[Exception] = []
    worker_done = threading.Event()

    def run_process() -> None:
        try:
            registry.process_all({"camera": {"frame": 1}})
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            worker_done.set()

    worker = threading.Thread(target=run_process)
    worker.start()
    time.sleep(0.05)

    try:
        runtime_stats = registry.snapshot_runtime_stats()
        pipeline_statuses = registry.snapshot_pipeline_statuses()
        registry.set_runtime_scale("face", 0.5)
    finally:
        gate.set()
        worker.join(timeout=1.0)
        registry.close_all()

    assert errors == []
    assert worker_done.is_set()
    assert "face" in runtime_stats
    assert "face" in pipeline_statuses
    assert registry.get_runtime_scale("face") == 0.5


def test_motion_pipeline_builds_from_yolo_backend() -> None:
    registry = build_pipeline_registry(
        enabled_pipelines=["motion"],
        detector_cfg={"detectors": {"motion": {"detector_type": "yolo_bytetrack", "enabled": True}}},
    )
    pipeline = registry.get_pipeline("motion")
    assert isinstance(pipeline, SingleDetectorPipeline)


def test_mediapipe_gesture_pipeline_requires_model_path(monkeypatch) -> None:
    from robot_life.perception.adapters import mediapipe_adapter

    monkeypatch.setattr(mediapipe_adapter, "mp", object())
    pipeline = _try_build_mediapipe_gesture_pipeline(
        PipelineSpec(name="gesture", source="camera"),
        {},
        backend="mediapipe_gesture",
    )
    assert isinstance(pipeline, NoOpPipeline)
    assert pipeline.reason == "mediapipe_gesture_model_missing"


def test_mediapipe_gaze_pipeline_requires_model_path(monkeypatch) -> None:
    from robot_life.perception.adapters import mediapipe_adapter

    monkeypatch.setattr(mediapipe_adapter, "mp", object())
    pipeline = _try_build_mediapipe_gaze_pipeline(
        PipelineSpec(name="gaze", source="camera"),
        {},
        backend="mediapipe_iris",
    )
    assert isinstance(pipeline, NoOpPipeline)
    assert pipeline.reason == "mediapipe_gaze_model_missing"


def test_mediapipe_face_pipeline_requires_model_path(monkeypatch) -> None:
    from robot_life.perception.adapters import mediapipe_adapter

    monkeypatch.setattr(mediapipe_adapter, "mp", object())
    pipeline = _try_build_mediapipe_face_pipeline(
        PipelineSpec(name="face", source="camera"),
        {},
        backend="mediapipe_face",
    )
    assert isinstance(pipeline, NoOpPipeline)
    assert pipeline.reason == "mediapipe_face_model_missing"


def test_face_pipeline_falls_back_to_mediapipe_when_insightface_missing(tmp_path, monkeypatch) -> None:
    from robot_life.perception.adapters import insightface_adapter, mediapipe_adapter

    monkeypatch.setattr(insightface_adapter, "insightface", None)
    monkeypatch.setattr(mediapipe_adapter, "mp", object())
    model_path = tmp_path / "face_landmarker.task"
    model_path.write_bytes(b"task")

    registry = build_pipeline_registry(
        enabled_pipelines=["face"],
        detector_cfg={
            "detectors": {
                "face": {
                    "enabled": True,
                    "detector_type": "insightface",
                    "fallback_model_path": str(model_path),
                }
            }
        },
    )
    pipeline = registry.get_pipeline("face")
    assert isinstance(pipeline, SingleDetectorPipeline)


def test_insightface_pipeline_accepts_legacy_version_if_module_imports(monkeypatch) -> None:
    from robot_life.perception.adapters import insightface_adapter

    class _StubInsightFace:
        __version__ = "0.2.1"

    monkeypatch.setattr(insightface_adapter, "insightface", _StubInsightFace())
    pipeline = _try_build_insightface_pipeline(
        PipelineSpec(name="face", source="camera"),
        {},
        backend="insightface",
    )
    assert type(pipeline).__name__ == "InsightFacePipeline"
