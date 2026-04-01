from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
from threading import RLock
from time import monotonic
from typing import Any

from robot_life.perception.base import DetectorBase, PipelineBase, PipelineSpec

logger = logging.getLogger(__name__)

DEFAULT_PIPELINES = [
    PipelineSpec(name="face", source="camera", sample_rate_hz=10),
    PipelineSpec(name="gesture", source="camera", sample_rate_hz=15),
    PipelineSpec(name="gaze", source="camera", sample_rate_hz=10),
    PipelineSpec(name="audio", source="microphone", sample_rate_hz=31.25),
    PipelineSpec(name="motion", source="camera", sample_rate_hz=30),
]


class DetectorRegistry:
    """
    Registry for detector implementations.
    Allows registration and retrieval of detector classes.
    """

    def __init__(self):
        self._detectors: dict[str, type[DetectorBase]] = {}

    def register(self, detector_type: str, detector_class: type[DetectorBase]) -> None:
        """
        Register a detector class.
        
        Args:
            detector_type: Unique identifier (e.g., "face_insightface", "gesture_mediapipe")
            detector_class: Detector class (subclass of DetectorBase)
        """
        self._detectors[detector_type] = detector_class

    def get(self, detector_type: str) -> type[DetectorBase] | None:
        """Get detector class by type."""
        return self._detectors.get(detector_type)

    def list_detectors(self) -> list[str]:
        """List all registered detector types."""
        return list(self._detectors.keys())


class PipelineRegistry:
    """
    Registry for perception pipelines.
    Manages pipeline instances and their detectors.
    """

    def __init__(self):
        self._lock = RLock()
        self._pipelines: dict[str, PipelineBase] = {}
        self._detector_registry = DetectorRegistry()
        self._pipeline_last_processed_at: dict[str, float] = {}
        self._pipeline_runtime_scale: dict[str, float] = {}
        self._pipeline_last_duration_ms: dict[str, float] = {}
        self._pipeline_budget_skips: dict[str, int] = {}
        self._cycle_budget_ms: float | None = None
        self._pipeline_init_status: dict[str, str] = {}
        self._pipeline_failure_reason: dict[str, str] = {}
        self._process_workers: int = 1
        self._process_executor: ThreadPoolExecutor | None = None
        self._init_workers: int = max(1, min(4, int(os.cpu_count() or 2)))

    def register_detector_class(
        self, detector_type: str, detector_class: type[DetectorBase]
    ) -> None:
        """Register a detector class to the detector registry."""
        with self._lock:
            self._detector_registry.register(detector_type, detector_class)

    def register_pipeline(self, pipeline_name: str, pipeline: PipelineBase) -> None:
        """
        Register a pipeline instance.
        
        Args:
            pipeline_name: Unique identifier (e.g., "face_pipeline", "gesture_pipeline")
            pipeline: Pipeline instance
        """
        with self._lock:
            self._pipelines[pipeline_name] = pipeline
            self._pipeline_last_processed_at.pop(pipeline_name, None)
            self._pipeline_runtime_scale[pipeline_name] = 1.0
            self._pipeline_last_duration_ms[pipeline_name] = 0.0
            self._pipeline_budget_skips[pipeline_name] = 0
            self._pipeline_init_status[pipeline_name] = "pending"
            self._pipeline_failure_reason[pipeline_name] = str(getattr(pipeline, "reason", "") or "")

    def get_pipeline(self, pipeline_name: str) -> PipelineBase | None:
        """Get pipeline instance by name."""
        with self._lock:
            return self._pipelines.get(pipeline_name)

    def list_pipelines(self) -> list[str]:
        """List all registered pipeline names."""
        with self._lock:
            return list(self._pipelines.keys())

    def initialize_all(self) -> None:
        """Initialize all registered pipelines."""
        with self._lock:
            pipeline_items = list(self._pipelines.items())
            for pipeline_name, pipeline in pipeline_items:
                if pipeline.spec.enabled:
                    self._pipeline_init_status[pipeline_name] = "initializing"
                    self._pipeline_failure_reason[pipeline_name] = ""
                else:
                    self._pipeline_init_status[pipeline_name] = "disabled"
                    self._pipeline_failure_reason[pipeline_name] = str(getattr(pipeline, "reason", "") or "")

        enabled_items = [
            (pipeline_name, pipeline)
            for pipeline_name, pipeline in pipeline_items
            if pipeline.spec.enabled
        ]
        if not enabled_items:
            return

        worker_count = max(1, min(self._init_workers, len(enabled_items)))
        if worker_count <= 1:
            for pipeline_name, pipeline in pipeline_items:
                self._initialize_pipeline(pipeline_name, pipeline)
            return

        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="pipeline-init",
        ) as executor:
            futures = {
                executor.submit(self._initialize_pipeline, pipeline_name, pipeline): pipeline_name
                for pipeline_name, pipeline in pipeline_items
            }
            for future in as_completed(futures):
                future.result()

    def _initialize_pipeline(self, pipeline_name: str, pipeline: PipelineBase) -> None:
        if not pipeline.spec.enabled:
            with self._lock:
                self._pipeline_init_status[pipeline_name] = "disabled"
                self._pipeline_failure_reason[pipeline_name] = str(getattr(pipeline, "reason", "") or "")
            return

        try:
            pipeline.initialize()
        except Exception as exc:
            logger.warning("pipeline init failed for %s: %s", pipeline_name, exc)
            pipeline.spec.enabled = False
            with self._lock:
                self._pipeline_init_status[pipeline_name] = "failed"
                self._pipeline_failure_reason[pipeline_name] = f"{type(exc).__name__}: {exc}"
            return

        degraded_reason = str(getattr(pipeline, "reason", "") or "")
        with self._lock:
            if degraded_reason:
                self._pipeline_init_status[pipeline_name] = "degraded"
                self._pipeline_failure_reason[pipeline_name] = degraded_reason
            else:
                self._pipeline_init_status[pipeline_name] = "ready"
                self._pipeline_failure_reason[pipeline_name] = ""

    def scheduled_sources(self, frames: dict[str, Any]) -> set[str]:
        """Return which sources will actually be consumed this cycle."""
        return {
            str(entry.get("source", ""))
            for entry in self._prepare_process_entries(frames)
            if entry.get("source")
        }

    def close_all(self) -> None:
        """Shutdown all pipelines."""
        with self._lock:
            pipelines = list(self._pipelines.values())
            self._shutdown_process_executor_locked()
        for pipeline in pipelines:
            pipeline.close()

    def set_runtime_scale(self, pipeline_name: str, scale: float) -> None:
        """Set a runtime sampling multiplier for a pipeline."""
        with self._lock:
            if pipeline_name not in self._pipelines:
                return
            self._pipeline_runtime_scale[pipeline_name] = max(0.0, float(scale))

    def set_runtime_scales(self, scales: dict[str, float]) -> None:
        """Bulk update runtime sampling multipliers."""
        for pipeline_name, scale in scales.items():
            self.set_runtime_scale(pipeline_name, scale)

    def reset_runtime_scales(self) -> None:
        """Restore all runtime sampling multipliers to their default value."""
        with self._lock:
            for pipeline_name in self._pipelines:
                self._pipeline_runtime_scale[pipeline_name] = 1.0

    def get_runtime_scale(self, pipeline_name: str) -> float:
        """Return the effective runtime sampling multiplier for a pipeline."""
        with self._lock:
            return float(self._pipeline_runtime_scale.get(pipeline_name, 1.0))

    def set_cycle_budget_ms(self, budget_ms: float | None) -> None:
        with self._lock:
            if budget_ms is None:
                self._cycle_budget_ms = None
                return
            resolved = float(budget_ms)
            self._cycle_budget_ms = resolved if resolved > 0 else None

    def get_cycle_budget_ms(self) -> float | None:
        with self._lock:
            return self._cycle_budget_ms

    def set_processing_workers(self, workers: int | None) -> None:
        """Set worker count for pipeline processing. `1` keeps serial behavior."""
        resolved = 1
        if workers is not None:
            try:
                resolved = max(1, int(workers))
            except (TypeError, ValueError):
                resolved = 1
        with self._lock:
            if resolved == self._process_workers:
                return
            self._process_workers = resolved
            self._shutdown_process_executor_locked()

    def get_processing_workers(self) -> int:
        with self._lock:
            return self._process_workers

    def _ensure_process_executor_locked(self) -> ThreadPoolExecutor | None:
        if self._process_workers <= 1:
            return None
        if self._process_executor is None:
            self._process_executor = ThreadPoolExecutor(
                max_workers=self._process_workers,
                thread_name_prefix="pipeline-process",
            )
        return self._process_executor

    def _shutdown_process_executor_locked(self) -> None:
        executor = self._process_executor
        self._process_executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def snapshot_runtime_stats(self) -> dict[str, dict[str, float | int | None]]:
        snapshot: dict[str, dict[str, float | int | None]] = {}
        with self._lock:
            for pipeline_name, pipeline in self._pipelines.items():
                snapshot[pipeline_name] = {
                    "sample_rate_hz": pipeline.spec.sample_rate_hz,
                    "runtime_budget_ms": pipeline.spec.runtime_budget_ms,
                    "last_duration_ms": self._pipeline_last_duration_ms.get(pipeline_name),
                    "runtime_scale": self._pipeline_runtime_scale.get(pipeline_name, 1.0),
                    "budget_skips": self._pipeline_budget_skips.get(pipeline_name, 0),
                }
        return snapshot

    def snapshot_pipeline_statuses(self) -> dict[str, dict[str, str | bool]]:
        snapshot: dict[str, dict[str, str | bool]] = {}
        with self._lock:
            for pipeline_name, pipeline in self._pipelines.items():
                snapshot[pipeline_name] = {
                    "enabled": bool(pipeline.spec.enabled),
                    "implementation": type(pipeline).__name__,
                    "init_status": self._pipeline_init_status.get(pipeline_name, "pending"),
                    "reason": self._pipeline_failure_reason.get(pipeline_name, ""),
                }
        return snapshot

    def process_all(self, frames: dict[str, Any]) -> list[tuple[str, dict]]:
        """
        Process input frames through all pipelines.
        
        Args:
            frames: Dict mapping source type to frame data
                   (e.g., {"camera": image_array, "microphone": audio_chunk})
        
        Returns:
            List of (pipeline_name, detection_results_dict) tuples
        """
        entries = self._prepare_process_entries(frames)
        if not entries:
            return []
        with self._lock:
            workers = self._process_workers
        if workers <= 1 or len(entries) <= 1:
            return [self._process_entry(entry) for entry in entries]
        return self._process_entries_parallel(entries)

    def _prepare_process_entries(self, frames: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            pipeline_items = list(self._pipelines.items())
            cycle_budget_ms = self._cycle_budget_ms
        entries: list[dict[str, Any]] = []
        reserved_budget_ms = 0.0
        for pipeline_name, pipeline in pipeline_items:
            if not pipeline.spec.enabled:
                continue

            source = pipeline.spec.source
            if source not in frames:
                continue

            sample_rate_hz = pipeline.spec.sample_rate_hz
            sample_now: float | None = None
            if sample_rate_hz is not None and sample_rate_hz > 0:
                sample_now = monotonic()
                with self._lock:
                    scale = self._pipeline_runtime_scale.get(pipeline_name, 1.0)
                    last_processed_at = self._pipeline_last_processed_at.get(pipeline_name)
                effective_sample_rate_hz = float(sample_rate_hz) * max(0.0, float(scale))
                if effective_sample_rate_hz <= 0:
                    continue
                min_interval_s = 1.0 / effective_sample_rate_hz
                if last_processed_at is not None and (sample_now - last_processed_at) < min_interval_s:
                    continue

            reservation_ms = self._resolve_pipeline_reservation_ms(pipeline_name, pipeline)
            if cycle_budget_ms is not None and reservation_ms > 0 and (reserved_budget_ms + reservation_ms) > cycle_budget_ms:
                with self._lock:
                    self._pipeline_budget_skips[pipeline_name] = self._pipeline_budget_skips.get(pipeline_name, 0) + 1
                logger.debug(
                    "skip pipeline=%s due to cycle budget reserved=%.3f next=%.3f budget=%.3f",
                    pipeline_name,
                    reserved_budget_ms,
                    reservation_ms,
                    cycle_budget_ms,
                )
                continue

            entries.append(
                {
                    "pipeline_name": pipeline_name,
                    "pipeline": pipeline,
                    "source": source,
                    "frame": frames[source],
                    "sample_rate_hz": sample_rate_hz,
                    "sample_now": sample_now,
                }
            )
            reserved_budget_ms += reservation_ms
        return entries

    def _process_entry(self, entry: dict[str, Any]) -> tuple[str, dict]:
        pipeline_name = str(entry["pipeline_name"])
        pipeline = entry["pipeline"]
        sample_rate_hz = entry.get("sample_rate_hz")
        sample_now = entry.get("sample_now")
        frame = entry.get("frame")

        started_at = monotonic()
        detections = pipeline.process(frame)
        duration_ms = (monotonic() - started_at) * 1000.0

        with self._lock:
            self._pipeline_last_duration_ms[pipeline_name] = duration_ms
            if sample_rate_hz is not None and sample_rate_hz > 0 and sample_now is not None:
                self._pipeline_last_processed_at[pipeline_name] = float(sample_now)

        if pipeline.spec.runtime_budget_ms is not None and duration_ms > pipeline.spec.runtime_budget_ms:
            logger.warning(
                "pipeline=%s exceeded runtime budget %.2fms > %.2fms",
                pipeline_name,
                duration_ms,
                pipeline.spec.runtime_budget_ms,
            )
        return (pipeline_name, {"detections": detections})

    def _process_entries_parallel(self, entries: list[dict[str, Any]]) -> list[tuple[str, dict]]:
        with self._lock:
            executor = self._ensure_process_executor_locked()
        if executor is None:
            return [self._process_entry(entry) for entry in entries]

        futures = {
            executor.submit(self._process_entry, entry): index
            for index, entry in enumerate(entries)
        }
        ordered_results: dict[int, tuple[str, dict]] = {}
        for future in as_completed(futures):
            index = futures[future]
            ordered_results[index] = future.result()
        return [ordered_results[index] for index in sorted(ordered_results)]

    def _resolve_pipeline_reservation_ms(self, pipeline_name: str, pipeline: PipelineBase) -> float:
        configured_budget_ms = pipeline.spec.runtime_budget_ms
        with self._lock:
            observed_budget_ms = self._pipeline_last_duration_ms.get(pipeline_name, 0.0)
        if configured_budget_ms is not None and configured_budget_ms > 0:
            # Keep reservation stable across cycles: runtime outliers should not permanently
            # starve a pipeline under a fixed cycle budget.
            return float(configured_budget_ms)
        if observed_budget_ms is not None and observed_budget_ms > 0:
            return float(observed_budget_ms)
        return 0.0


# Global instance
_default_registry = PipelineRegistry()
