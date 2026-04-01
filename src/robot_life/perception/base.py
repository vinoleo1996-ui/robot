from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from robot_life.common.schemas import DetectionResult


@dataclass
class PipelineSpec:
    """Specification for a perception pipeline."""
    name: str
    source: str
    enabled: bool = True
    sample_rate_hz: float | None = None
    runtime_budget_ms: float | None = None


class DetectorBase(ABC):
    """
    Abstract base class for all detectors (face, gesture, gaze, audio, motion).
    
    Detectors convert raw sensor input into normalized DetectionResult objects.
    """

    def __init__(self, name: str, source: str, config: dict[str, Any] | None = None):
        """
        Initialize detector.
        
        Args:
            name: Human-readable name (e.g., "face_detector", "gesture_recognizer")
            source: Input source type (e.g., "camera", "microphone")
            config: Detector-specific configuration dict
        """
        self.name = name
        self.source = source
        self.config = config or {}
        self._initialized = False

    @abstractmethod
    def initialize(self) -> None:
        """
        Initialize detector resources (load models, open files, etc).
        Called once at startup.
        """
        pass

    @abstractmethod
    def process(self, frame: Any) -> list[DetectionResult]:
        """
        Process input frame and return detection results.
        
        Args:
            frame: Input data (image array, audio chunk, etc)
            
        Returns:
            List of DetectionResult objects (empty if no detections)
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """
        Cleanup detector resources.
        Called once at shutdown.
        """
        pass

    def is_ready(self) -> bool:
        """Check if detector is initialized and ready to process."""
        return self._initialized


class PipelineBase(ABC):
    """
    Abstract base class for perception pipelines.
    
    A pipeline manages one or more detectors and outputs unified DetectionResult.
    """

    def __init__(self, spec: PipelineSpec):
        """
        Initialize pipeline from spec.
        
        Args:
            spec: PipelineSpec with name, source, sample_rate
        """
        self.spec = spec
        self.detectors: dict[str, DetectorBase] = {}
        self._running = False

    def add_detector(self, detector: DetectorBase) -> None:
        """Register a detector to this pipeline."""
        self.detectors[detector.name] = detector

    def remove_detector(self, detector_name: str) -> None:
        """Unregister a detector from this pipeline."""
        self.detectors.pop(detector_name, None)

    @abstractmethod
    def initialize(self) -> None:
        """Initialize pipeline and all its detectors."""
        pass

    @abstractmethod
    def process(self, frame: Any) -> list[DetectionResult]:
        """
        Process input frame through all detectors in pipeline.
        
        Returns:
            Aggregated DetectionResult list from all detectors
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Shutdown pipeline and all detectors."""
        pass

    def is_running(self) -> bool:
        """Check if pipeline is currently running."""
        return self._running
