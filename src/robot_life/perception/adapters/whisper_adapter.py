"""Whisper-based speech-to-text recognition for real-time audio understanding."""

from __future__ import annotations

import logging
from time import time
from typing import Any

from robot_life.common.schemas import DetectionResult
from robot_life.common.tracing import new_trace_id
from robot_life.perception.base import DetectorBase

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

logger = logging.getLogger(__name__)


class WhisperASRDetector(DetectorBase):
    """
    Speech-to-text detection using OpenAI Whisper.
    
    Replaces RMS/dB energy detection with actual language understanding.
    Supports 99 languages and outputs structured speech events.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("whisper_asr", "microphone", config)
        self._model = None
        self._model_variant = str(self.config.get("model_variant", "small"))
        # tiny: 39M (1GB), small: 244M (2GB), medium: 769M (4GB), large: 1.5B (10GB)
        self._device = str(self.config.get("device", "cuda"))
        self._compute_type = str(self.config.get("compute_type", "float16"))
        self._language_detection = bool(self.config.get("language_detection", True))
        self._task = str(self.config.get("task", "transcribe"))  # or "translate"
        self._beam_size = int(self.config.get("beam_size", 3))
        self._temperature = float(self.config.get("temperature", 0.2))
        self._require_gpu = bool(self.config.get("require_gpu", False))

    def initialize(self) -> None:
        """Load Whisper model."""
        if WhisperModel is None:
            raise RuntimeError(
                "faster-whisper not installed. Install with: "
                "pip install faster-whisper"
            )

        try:
            logger.info(f"Loading Whisper {self._model_variant} on {self._device}...")
            self._model = WhisperModel(
                self._model_variant,
                device=self._device,
                compute_type=self._compute_type,
                language="zh" if not self._language_detection else None,  # Default to Chinese
            )
            self._initialized = True
            logger.info(
                f"Whisper {self._model_variant} loaded on {self._device} "
                f"({self._compute_type})"
            )
        except Exception as e:
            logger.error(f"Failed to load Whisper: {e}")
            raise

    def process(self, frame: Any) -> list[DetectionResult]:
        """
        Process audio frame and recognize speech.
        
        Args:
            frame: Audio data (dict with 'audio' key or numpy array)
            
        Returns:
            List of DetectionResult for speech recognition
        """
        if not self._initialized or self._model is None:
            return []

        if frame is None:
            return []

        # Extract audio samples from frame
        audio_data = self._extract_audio(frame)
        if audio_data is None or len(audio_data) == 0:
            return []

        # Check minimum audio length (0.5 seconds at 16kHz = 8000 samples)
        if len(audio_data) < 8000:
            return []

        results = []

        try:
            # Run speech recognition
            segments, info = self._model.transcribe(
                audio_data,
                language="zh" if not self._language_detection else None,
                task=self._task,
                beam_size=self._beam_size,
                temperature=self._temperature,
            )

            # Convert segments to detection results
            for segment in segments:
                text = segment.text.strip()
                if not text:  # Skip empty segments
                    continue

                confidence = segment.confidence
                language = getattr(info, "language", "unknown")

                detection = DetectionResult(
                    trace_id=new_trace_id(),
                    source="microphone",
                    detector="whisper_asr",
                    event_type="speech_detected",
                    timestamp=time(),
                    confidence=float(confidence),
                    payload={
                        "text": text,
                        "language": language,
                        "duration_s": segment.end - segment.start,
                        "start_ms": int(segment.start * 1000),
                        "end_ms": int(segment.end * 1000),
                        "no_speech_prob": float(
                            getattr(info, "no_speech_prob", 0.0)
                        ),
                    },
                )
                results.append(detection)

        except Exception as e:
            logger.error(f"Whisper recognition failed: {e}")

        return results

    def close(self) -> None:
        """Cleanup detector resources."""
        self._model = None
        self._initialized = False

    @staticmethod
    def _extract_audio(frame: Any) -> Any | None:
        """Extract audio samples from frame dict or array."""
        import numpy as np

        if isinstance(frame, dict):
            for key in ("audio", "samples", "chunk", "data"):
                if key in frame:
                    candidate = frame[key]
                    break
            else:
                return None
        else:
            candidate = frame

        try:
            if isinstance(candidate, np.ndarray):
                return np.asarray(candidate, dtype=np.float32).flatten()
            elif isinstance(candidate, (list, tuple)):
                return np.asarray(candidate, dtype=np.float32).flatten()
        except Exception:
            pass

        return None
