from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

import yaml

from robot_life.common.schemas import DetectionResult
from robot_life.perception.base import DetectorBase, PipelineBase, PipelineSpec
from robot_life.perception.registry import DEFAULT_PIPELINES, PipelineRegistry


logger = logging.getLogger(__name__)
REALTIME_GPU_PIPELINES = {"face", "gesture", "gaze", "motion"}


def _log_optional_backend_failure(pipeline_name: str, stage: str, exc: Exception) -> None:
    logger.warning(
        "pipeline=%s optional backend failed during %s: %s: %s",
        pipeline_name,
        stage,
        type(exc).__name__,
        exc,
    )


def _project_root_from_config_path(path: Path) -> Path:
    resolved = path.resolve()
    for parent in resolved.parents:
        if parent.name == "configs":
            return parent.parent
    return resolved.parent


def _looks_like_local_path(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if stripped.startswith(("/", ".", "~")):
        return True
    if stripped.startswith(("configs/", "data/", "logs/", "models/")):
        return True
    return bool(Path(stripped).suffix)


def _resolve_local_path(value: str, *, config_path: Path) -> str:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    return str((_project_root_from_config_path(config_path) / candidate).resolve())


def _resolve_detector_paths(payload: dict[str, Any], *, config_path: Path) -> dict[str, Any]:
    detectors = payload.get("detectors", {})
    if not isinstance(detectors, Mapping):
        return payload

    resolved_payload = dict(payload)
    resolved_detectors: dict[str, Any] = {}
    for name, detector in detectors.items():
        if not isinstance(detector, Mapping):
            resolved_detectors[name] = detector
            continue

        resolved_detector = dict(detector)
        for key in ("model_path", "fallback_model_path"):
            raw_value = resolved_detector.get(key)
            if isinstance(raw_value, str) and _looks_like_local_path(raw_value):
                resolved_detector[key] = _resolve_local_path(raw_value, config_path=config_path)
        resolved_detectors[name] = resolved_detector

    resolved_payload["detectors"] = resolved_detectors
    return resolved_payload


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _normalize_providers(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    providers = [str(item).strip() for item in raw if str(item).strip()]
    if not providers:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    dedup: list[str] = []
    seen: set[str] = set()
    for provider in providers:
        if provider in seen:
            continue
        seen.add(provider)
        dedup.append(provider)
    if "CUDAExecutionProvider" in dedup:
        dedup = ["CUDAExecutionProvider"] + [item for item in dedup if item != "CUDAExecutionProvider"]
    if "CPUExecutionProvider" not in dedup:
        dedup.append("CPUExecutionProvider")
    return dedup


def _apply_gpu_policy(spec: PipelineSpec, config: dict[str, Any]) -> dict[str, Any]:
    """Normalize GPU policy so runtime behavior is explicit and non-silent."""
    resolved = dict(config)
    require_gpu = _coerce_bool(
        resolved.get("require_gpu"),
        default=spec.name in REALTIME_GPU_PIPELINES,
    )
    allow_cpu_fallback = _coerce_bool(
        resolved.get("allow_cpu_fallback"),
        default=not require_gpu,
    )

    if require_gpu and allow_cpu_fallback:
        logger.warning(
            "pipeline=%s configured require_gpu=true with allow_cpu_fallback=true; forcing fallback off",
            spec.name,
        )
        allow_cpu_fallback = False

    resolved["require_gpu"] = require_gpu
    resolved["allow_cpu_fallback"] = allow_cpu_fallback

    if spec.name in {"face", "motion"}:
        providers = _normalize_providers(resolved.get("providers"))
        if require_gpu and "CUDAExecutionProvider" not in providers:
            providers.insert(0, "CUDAExecutionProvider")
        resolved["providers"] = providers

    if spec.name in {"face", "gesture", "gaze"} and require_gpu:
        resolved["use_gpu"] = True

    if spec.name == "motion":
        resolved["allow_cuda_fallback"] = allow_cpu_fallback
        device = str(resolved.get("device", "cuda:0" if require_gpu else "cpu")).strip().lower()
        if require_gpu and not device.startswith("cuda"):
            logger.warning("pipeline=motion require_gpu=true but device=%s; overriding to cuda:0", device)
            device = "cuda:0"
        resolved["device"] = device

    if spec.name == "audio" and require_gpu:
        resolved.setdefault("panns_device", "auto")
        resolved.setdefault("whisper_device", "auto")

    if spec.name in REALTIME_GPU_PIPELINES or spec.name == "audio":
        logger.info(
            "gpu_policy pipeline=%s require_gpu=%s allow_cpu_fallback=%s providers=%s device=%s",
            spec.name,
            resolved.get("require_gpu"),
            resolved.get("allow_cpu_fallback"),
            resolved.get("providers"),
            resolved.get("device"),
        )
    return resolved


class NoOpPipeline(PipelineBase):
    """Pipeline placeholder used when a backend is not available yet."""

    def __init__(self, spec: PipelineSpec, reason: str = "backend_unavailable") -> None:
        super().__init__(spec)
        self.reason = reason

    def initialize(self) -> None:
        self._running = True

    def process(self, frame: Any) -> list[Any]:
        return []

    def close(self) -> None:
        self._running = False


class SingleDetectorPipeline(PipelineBase):
    """Wrap a single detector instance so it can be scheduled as a pipeline."""

    def __init__(self, spec: PipelineSpec, detector: DetectorBase) -> None:
        super().__init__(spec)
        self._detector = detector

    def initialize(self) -> None:
        if not self._detector.is_ready():
            self._detector.initialize()
        self._running = True

    def process(self, frame: Any) -> list[Any]:
        if not self._running:
            return []
        return self._detector.process(frame)

    def close(self) -> None:
        self._detector.close()
        self._running = False


class MockEventPipeline(PipelineBase):
    """Synthetic pipeline used for mock-driver live loop verification."""

    def __init__(self, spec: PipelineSpec, detector: str, event_type: str, confidence: float = 0.9) -> None:
        super().__init__(spec)
        self._detector = detector
        self._event_type = event_type
        self._confidence = confidence
        self._frame_index = 0

    def initialize(self) -> None:
        self._running = True

    def process(self, frame: Any) -> list[Any]:
        if not self._running:
            return []
        self._frame_index += 1
        if self._frame_index % 2 == 1:
            return []

        payload: dict[str, Any] = {"mock_driver": True, "frame_index": self._frame_index}
        if self.spec.name in {"face", "gaze", "gesture"}:
            payload["target_id"] = "mock_user"
        return [
            DetectionResult.synthetic(
                detector=self._detector,
                event_type=self._event_type,
                confidence=self._confidence,
                payload=payload,
            )
        ]

    def close(self) -> None:
        self._running = False


def load_detector_config(path: str | Path | None) -> dict[str, Any]:
    """Load detector configuration from YAML, returning an empty config on failure."""
    if path is None:
        return {}

    config_path = Path(path)
    if not config_path.exists():
        logger.warning("Detector config not found: %s", config_path)
        return {}

    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping config in {config_path}")
    return _resolve_detector_paths(payload, config_path=config_path)


def build_pipeline_registry(
    enabled_pipelines: list[str] | None = None,
    detector_cfg: Mapping[str, Any] | None = None,
    *,
    mock_drivers: bool = False,
) -> PipelineRegistry:
    """Build a registry with best-effort backend selection and graceful fallbacks."""
    registry = PipelineRegistry()
    detector_cfg = detector_cfg or {}
    enabled_set = set(enabled_pipelines) if enabled_pipelines is not None else None

    for spec in DEFAULT_PIPELINES:
        if enabled_set is not None and spec.name not in enabled_set:
            continue

        pipeline_cfg = _get_pipeline_cfg(detector_cfg, spec.name)
        effective_spec = _apply_pipeline_spec_overrides(spec, pipeline_cfg)
        pipeline = _build_pipeline(effective_spec, detector_cfg, mock_drivers=mock_drivers)
        registry.register_pipeline(spec.name, pipeline)

    detector_global = detector_cfg.get("detector_global", {}) if isinstance(detector_cfg, Mapping) else {}
    if isinstance(detector_global, Mapping):
        raw_cycle_budget = detector_global.get("fast_cycle_budget_ms")
        if raw_cycle_budget is not None:
            try:
                registry.set_cycle_budget_ms(float(raw_cycle_budget))
            except (TypeError, ValueError):
                logger.warning("invalid detector_global.fast_cycle_budget_ms=%r", raw_cycle_budget)
        raw_parallel_workers = detector_global.get("fast_parallel_workers")
        if raw_parallel_workers is not None:
            try:
                registry.set_processing_workers(int(raw_parallel_workers))
            except (TypeError, ValueError):
                logger.warning("invalid detector_global.fast_parallel_workers=%r", raw_parallel_workers)

    return registry


def _apply_pipeline_spec_overrides(
    spec: PipelineSpec,
    pipeline_cfg: Mapping[str, Any],
) -> PipelineSpec:
    """Allow detector config to override scheduling-related pipeline spec fields."""
    raw_sample_rate = pipeline_cfg.get("sample_rate_hz")
    resolved_sample_rate: float | None = spec.sample_rate_hz
    if raw_sample_rate is not None:
        try:
            sample_rate = float(raw_sample_rate)
            resolved_sample_rate = sample_rate if sample_rate > 0 else None
        except (TypeError, ValueError):
            logger.warning(
                "invalid sample_rate_hz=%r for pipeline=%s; keeping default=%s",
                raw_sample_rate,
                spec.name,
                spec.sample_rate_hz,
            )
            resolved_sample_rate = spec.sample_rate_hz

    raw_runtime_budget = pipeline_cfg.get("runtime_budget_ms")
    resolved_runtime_budget: float | None = spec.runtime_budget_ms
    if raw_runtime_budget is not None:
        try:
            runtime_budget = float(raw_runtime_budget)
            resolved_runtime_budget = runtime_budget if runtime_budget > 0 else None
        except (TypeError, ValueError):
            logger.warning(
                "invalid runtime_budget_ms=%r for pipeline=%s; keeping default=%s",
                raw_runtime_budget,
                spec.name,
                spec.runtime_budget_ms,
            )
            resolved_runtime_budget = spec.runtime_budget_ms

    return PipelineSpec(
        name=spec.name,
        source=spec.source,
        enabled=spec.enabled,
        sample_rate_hz=resolved_sample_rate,
        runtime_budget_ms=resolved_runtime_budget,
    )


def _build_pipeline(
    spec: PipelineSpec,
    detector_cfg: Mapping[str, Any],
    *,
    mock_drivers: bool = False,
) -> PipelineBase:
    if mock_drivers:
        return _build_mock_pipeline(spec)

    pipeline_cfg = _get_pipeline_cfg(detector_cfg, spec.name)
    if not _is_enabled(pipeline_cfg):
        disabled_spec = PipelineSpec(
            name=spec.name,
            source=spec.source,
            enabled=False,
            sample_rate_hz=spec.sample_rate_hz,
            runtime_budget_ms=spec.runtime_budget_ms,
        )
        return NoOpPipeline(disabled_spec, reason="disabled_by_config")

    backend = str(
        pipeline_cfg.get("detector_type")
        or pipeline_cfg.get("backend")
        or pipeline_cfg.get("name")
        or spec.name
    )
    config = _extract_nested_config(pipeline_cfg)
    config = _apply_gpu_policy(spec, config)

    if spec.name == "face":
        pipeline = _try_build_insightface_pipeline(spec, config, backend)
        if isinstance(pipeline, NoOpPipeline) and pipeline.reason in {
            "insightface_import_failed",
            "insightface_dependency_missing",
            "insightface_runtime_unavailable",
        }:
            fallback = _try_build_mediapipe_face_pipeline(
                spec,
                config,
                backend,
                allow_insightface_fallback=True,
            )
            if fallback is not None:
                logger.warning(
                    "face pipeline falling back to mediapipe due to insightface unavailability: %s",
                    pipeline.reason,
                )
                return fallback
        if pipeline is not None:
            return pipeline
        pipeline = _try_build_mediapipe_face_pipeline(spec, config, backend)
        if pipeline is not None:
            return pipeline

    if spec.name == "gesture":
        pipeline = _try_build_mediapipe_gesture_pipeline(spec, config, backend)
        if pipeline is not None:
            return pipeline

    if spec.name == "pose":
        pipeline = _try_build_mediapipe_pose_pipeline(spec, config, backend)
        if pipeline is not None:
            return pipeline

    if spec.name == "gaze":
        pipeline = _try_build_mediapipe_gaze_pipeline(spec, config, backend)
        if pipeline is not None:
            return pipeline

    if spec.name == "audio":
        pipeline = _try_build_audio_pipeline(spec, config, backend)
        if pipeline is not None:
            return pipeline

    if spec.name == "motion":
        pipeline = _try_build_motion_pipeline(spec, config, backend)
        if pipeline is not None:
            return pipeline

    if spec.name in {"audio", "motion"}:
        return NoOpPipeline(spec, reason=f"{spec.name}_backend_unavailable")

    return NoOpPipeline(spec, reason=f"unsupported_backend:{backend}")


def _build_mock_pipeline(spec: PipelineSpec) -> PipelineBase:
    if spec.name == "face":
        return MockEventPipeline(spec, detector="mock_face", event_type="familiar_face", confidence=0.92)
    if spec.name == "gesture":
        return MockEventPipeline(spec, detector="mock_gesture", event_type="gesture_open_palm", confidence=0.9)
    if spec.name == "gaze":
        return MockEventPipeline(spec, detector="mock_gaze", event_type="gaze_sustained", confidence=0.88)
    if spec.name == "audio":
        return MockEventPipeline(spec, detector="mock_audio", event_type="loud_sound", confidence=0.82)
    if spec.name == "motion":
        return MockEventPipeline(spec, detector="mock_motion", event_type="motion", confidence=0.8)
    return NoOpPipeline(spec, reason="mock_not_defined")


def _get_pipeline_cfg(detector_cfg: Mapping[str, Any], pipeline_name: str) -> Mapping[str, Any]:
    detectors = detector_cfg.get("detectors", {})
    if isinstance(detectors, Mapping):
        pipeline_cfg = detectors.get(pipeline_name, {})
        if isinstance(pipeline_cfg, Mapping):
            return pipeline_cfg
    return {}


def _extract_nested_config(pipeline_cfg: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    config = pipeline_cfg.get("config", {})
    if isinstance(config, Mapping):
        merged.update(dict(config))

    for key, value in pipeline_cfg.items():
        if key in {"config", "enabled", "detector_type", "backend", "name"}:
            continue
        merged.setdefault(key, value)
    return merged


def _is_enabled(pipeline_cfg: Mapping[str, Any]) -> bool:
    raw = pipeline_cfg.get("enabled", True)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() not in {"0", "false", "off", "no"}
    return bool(raw)


def _try_build_insightface_pipeline(
    spec: PipelineSpec,
    config: dict[str, Any],
    backend: str,
) -> PipelineBase | None:
    if "insightface" not in backend:
        return None

    try:
        from robot_life.perception.adapters import insightface_adapter
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "insightface_import", exc)
        return NoOpPipeline(spec, reason="insightface_import_failed")

    if getattr(insightface_adapter, "insightface", None) is None:
        return NoOpPipeline(spec, reason="insightface_dependency_missing")
    try:
        return insightface_adapter.InsightFacePipeline(spec, config=config)
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "insightface_init", exc)
        return NoOpPipeline(spec, reason="insightface_runtime_unavailable")


def _try_build_mediapipe_face_pipeline(
    spec: PipelineSpec,
    config: dict[str, Any],
    backend: str,
    *,
    allow_insightface_fallback: bool = False,
) -> PipelineBase | None:
    if not allow_insightface_fallback and "mediapipe" not in backend and "face" not in backend:
        return None

    try:
        from robot_life.perception.adapters import mediapipe_adapter
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "mediapipe_face_import", exc)
        return NoOpPipeline(spec, reason="mediapipe_face_import_failed")

    if getattr(mediapipe_adapter, "mp", None) is None:
        return NoOpPipeline(spec, reason="mediapipe_dependency_missing")

    model_path = str(
        config.get("fallback_model_path")
        or config.get("mediapipe_model_path")
        or config.get("model_path", "")
    ).strip()
    if not model_path:
        return NoOpPipeline(spec, reason="mediapipe_face_model_missing")
    if not Path(model_path).exists():
        return NoOpPipeline(spec, reason="mediapipe_face_model_not_found")

    detector_config = dict(config)
    detector_config["model_path"] = model_path
    try:
        detector = mediapipe_adapter.MediaPipeFaceDetector(detector_config)
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "mediapipe_face_init", exc)
        return NoOpPipeline(spec, reason="mediapipe_face_runtime_unavailable")
    return SingleDetectorPipeline(spec, detector)


def _try_build_mediapipe_pose_pipeline(
    spec: PipelineSpec,
    config: dict[str, Any],
    backend: str,
) -> PipelineBase | None:
    if "mediapipe" not in backend and "pose" not in backend:
        return None

    try:
        from robot_life.perception.adapters import mediapipe_pose_adapter
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "mediapipe_pose_import", exc)
        return NoOpPipeline(spec, reason="mediapipe_pose_import_failed")

    if getattr(mediapipe_pose_adapter, "mp", None) is None:
        return NoOpPipeline(spec, reason="mediapipe_dependency_missing")

    try:
        detector = mediapipe_pose_adapter.MediaPipePoseDetector(config)
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "mediapipe_pose_init", exc)
        return NoOpPipeline(spec, reason="mediapipe_pose_runtime_unavailable")
    return SingleDetectorPipeline(spec, detector)

def _try_build_mediapipe_gesture_pipeline(
    spec: PipelineSpec,
    config: dict[str, Any],
    backend: str,
) -> PipelineBase | None:
    if "mediapipe" not in backend and "gesture" not in backend:
        return None

    try:
        from robot_life.perception.adapters import mediapipe_adapter
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "mediapipe_gesture_import", exc)
        return NoOpPipeline(spec, reason="mediapipe_gesture_import_failed")

    if getattr(mediapipe_adapter, "mp", None) is None:
        return NoOpPipeline(spec, reason="mediapipe_dependency_missing")
    model_path = str(config.get("model_path", "")).strip()
    if not model_path:
        return NoOpPipeline(spec, reason="mediapipe_gesture_model_missing")
    if not Path(model_path).exists():
        return NoOpPipeline(spec, reason="mediapipe_gesture_model_not_found")

    try:
        detector = mediapipe_adapter.MediaPipeGestureDetector(config)
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "mediapipe_gesture_init", exc)
        return NoOpPipeline(spec, reason="mediapipe_gesture_runtime_unavailable")
    return SingleDetectorPipeline(spec, detector)


def _try_build_mediapipe_gaze_pipeline(
    spec: PipelineSpec,
    config: dict[str, Any],
    backend: str,
) -> PipelineBase | None:
    if "mediapipe" not in backend and "iris" not in backend and "gaze" not in backend:
        return None

    try:
        from robot_life.perception.adapters import mediapipe_adapter
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "mediapipe_gaze_import", exc)
        return NoOpPipeline(spec, reason="mediapipe_gaze_import_failed")

    if getattr(mediapipe_adapter, "mp", None) is None:
        return NoOpPipeline(spec, reason="mediapipe_dependency_missing")
    model_path = str(config.get("model_path", "")).strip()
    if not model_path:
        return NoOpPipeline(spec, reason="mediapipe_gaze_model_missing")
    if not Path(model_path).exists():
        return NoOpPipeline(spec, reason="mediapipe_gaze_model_not_found")

    try:
        return mediapipe_adapter.MediaPipeGazePipeline(spec, config=config)
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "mediapipe_gaze_init", exc)
        return NoOpPipeline(spec, reason="mediapipe_gaze_runtime_unavailable")


def _try_build_audio_pipeline(
    spec: PipelineSpec,
    config: dict[str, Any],
    backend: str,
) -> PipelineBase | None:
    if not any(token in backend for token in ("yamnet", "rms", "audio", "panns", "whisper")):
        return None

    try:
        from robot_life.perception.adapters.audio_adapter import RMSLoudSoundDetector
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "audio_import", exc)
        return NoOpPipeline(spec, reason="audio_adapter_import_failed")

    if "panns" in backend:
        try:
            from robot_life.perception.adapters.panns_whisper_audio_adapter import PANNSWhisperAudioDetector
        except Exception as exc:
            _log_optional_backend_failure(spec.name, "panns_audio_import", exc)
            return NoOpPipeline(spec, reason="panns_audio_adapter_import_failed")
        try:
            detector = PANNSWhisperAudioDetector(config)
        except Exception as exc:
            _log_optional_backend_failure(spec.name, "panns_audio_init", exc)
            return NoOpPipeline(spec, reason="panns_audio_runtime_unavailable")
    elif "whisper" in backend:
        try:
            from robot_life.perception.adapters.whisper_adapter import WhisperASRDetector
        except Exception as exc:
            _log_optional_backend_failure(spec.name, "whisper_audio_import", exc)
            return NoOpPipeline(spec, reason="whisper_audio_adapter_import_failed")
        try:
            detector = WhisperASRDetector(config)
        except Exception as exc:
            _log_optional_backend_failure(spec.name, "whisper_audio_init", exc)
            return NoOpPipeline(spec, reason="whisper_audio_runtime_unavailable")
    elif "yamnet" in backend:
        model_path = str(config.get("model_path", "")).strip()
        if not model_path or not Path(model_path).exists():
            logger.warning(
                "pipeline=%s yamnet model missing; falling back to RMS loud sound detector",
                spec.name,
            )
            try:
                detector = RMSLoudSoundDetector(config)
            except Exception as exc:
                _log_optional_backend_failure(spec.name, "rms_audio_init", exc)
                return NoOpPipeline(spec, reason="rms_audio_runtime_unavailable")
            return SingleDetectorPipeline(spec, detector)
        try:
            from robot_life.perception.adapters.yamnet_audio_adapter import YAMNetAudioDetector
        except Exception as exc:
            _log_optional_backend_failure(spec.name, "yamnet_audio_import", exc)
            return NoOpPipeline(spec, reason="yamnet_audio_adapter_import_failed")
        try:
            detector = YAMNetAudioDetector(config)
        except Exception as exc:
            _log_optional_backend_failure(spec.name, "yamnet_audio_init", exc)
            return NoOpPipeline(spec, reason="yamnet_audio_runtime_unavailable")
    else:
        try:
            detector = RMSLoudSoundDetector(config)
        except Exception as exc:
            _log_optional_backend_failure(spec.name, "rms_audio_init", exc)
            return NoOpPipeline(spec, reason="rms_audio_runtime_unavailable")
    return SingleDetectorPipeline(spec, detector)


def _try_build_motion_pipeline(
    spec: PipelineSpec,
    config: dict[str, Any],
    backend: str,
) -> PipelineBase | None:
    if not any(token in backend for token in ("motion", "opencv", "yolo", "bytetrack")):
        return None

    try:
        from robot_life.perception.adapters.motion_adapter import OpenCVMotionDetector, YOLOMotionDetector
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "motion_import", exc)
        return NoOpPipeline(spec, reason="motion_adapter_import_failed")

    try:
        if "yolo" in backend or "bytetrack" in backend:
            detector = YOLOMotionDetector(config)
        else:
            detector = OpenCVMotionDetector(config)
    except Exception as exc:
        _log_optional_backend_failure(spec.name, "motion_init", exc)
        return NoOpPipeline(spec, reason="motion_runtime_unavailable")
    return SingleDetectorPipeline(spec, detector)
