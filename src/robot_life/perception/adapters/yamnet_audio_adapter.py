"""YAMNet Audio classification adapter based on ONNXRuntime."""

from __future__ import annotations

import logging
from time import monotonic, time
from typing import Any
import numpy as np

from robot_life.common.schemas import DetectionResult
from robot_life.common.tracing import new_trace_id
from robot_life.perception.base import DetectorBase

logger = logging.getLogger(__name__)

try:
    import onnxruntime as ort
except ImportError:
    ort = None

try:
    import librosa
except ImportError:
    librosa = None


# Core YAMNet Classes (Sample)
# 0: Speech, 22: Crying baby, 49: Alarm clock, 73: Dog, 137: Cat, 270: Doorbell, 387: Glass breaking
YAMNET_CLASSES = {
    0: "Speech",
    22: "Crying baby",
    49: "Alarm clock",
    73: "Dog",
    137: "Cat",
    270: "Doorbell",
    387: "Glass breaking",
    394: "Siren",
    494: "Silence"
}


class YAMNetAudioDetector(DetectorBase):
    """Detects audio semantics using YAMNet via ONNX."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("yamnet_audio", "microphone", config)
        self._model_path = str(self.config.get("model_path", "models/audio/yamnet.onnx"))
        self._confidence_threshold = float(self.config.get("confidence_threshold", 0.3))
        self._cooldown_s = float(self.config.get("cooldown_s", 1.0))
        self._sample_rate = 16000
        self._min_samples = 15600  # 0.975 seconds at 16kHz
        
        self._target_classes = self.config.get("target_classes", [22, 270, 387, 0])
        self._last_trigger_monotonic = 0.0
        self._session = None

    def initialize(self) -> None:
        if ort is None or librosa is None:
            raise RuntimeError("onnxruntime and librosa are required for YAMNet.")
            
        try:
            self._session = ort.InferenceSession(
                self._model_path,
                providers=["CPUExecutionProvider"]
            )
            self._input_name = self._session.get_inputs()[0].name
            input_shape = self._session.get_inputs()[0].shape
            
            # If shape is [None, 96, 64], model expects log-mel spectrogram
            # If shape is [None], model expects raw waveform
            self._expects_spectrogram = (len(input_shape) == 3 or (len(input_shape) == 4))
            self._initialized = True
        except Exception as e:
            logger.warning(f"Failed to load YAMNet ONNX model at {self._model_path}: {e}")
            self._initialized = False

    def process(self, frame_data: Any) -> list[DetectionResult]:
        if not self._initialized or self._session is None:
            return []

        # frame_data is expected to be a numpy array of audio samples
        # Extractor logic (resample to 16k mono if needed)
        samples = np.array(frame_data, dtype=np.float32).flatten()
        if len(samples) < self._min_samples:
            return []

        # Ensure we only take the exact required amount or trim
        samples = samples[-self._min_samples:]
        
        if self._expects_spectrogram:
            # 1. Compute melspectrogram (window=25ms, hop=10ms, 64 bins, 16kHz)
            # librosa defaults: n_fft=400 (25ms), hop_length=160 (10ms)
            mel = librosa.feature.melspectrogram(
                y=samples, sr=self._sample_rate, n_fft=400, hop_length=160,
                n_mels=64, fmin=125, fmax=7500, power=1.0, center=False
            )
            # 2. Log scaling
            log_mel = np.log(mel + 0.001).T  # Shape: [96, 64]
            input_data = np.expand_dims(log_mel, axis=0).astype(np.float32)
        else:
            input_data = samples.astype(np.float32)
            if len(self._session.get_inputs()[0].shape) > 1:
               input_data = np.expand_dims(input_data, axis=0)

        outputs = self._session.run(None, {self._input_name: input_data})
        scores = outputs[0][0]  # First output, first batch element -> [521] array
        
        top_class_id = int(np.argmax(scores))
        top_score = float(scores[top_class_id])
        
        if top_score < self._confidence_threshold:
            return []
            
        now = monotonic()
        if (now - self._last_trigger_monotonic) < self._cooldown_s:
            return []

        # Is it a class we care about?
        if top_class_id not in self._target_classes and "all" not in self._target_classes:
            return []

        self._last_trigger_monotonic = now
        class_name = YAMNET_CLASSES.get(top_class_id, f"Class_{top_class_id}")
        
        event_type = "attention_audio"
        # Map specific dangerous/alarming sounds to loud_sound for hard interrupt
        if top_class_id in [387, 49]: # Glass breaking, Alarm
            event_type = "loud_sound"

        return [
            DetectionResult(
                trace_id=new_trace_id(),
                source=self.source,
                detector=self.name,
                event_type=event_type,
                timestamp=time(),
                confidence=top_score,
                payload={
                    "class_id": top_class_id,
                    "class_name": class_name,
                    "is_safety_critical": event_type == "loud_sound"
                },
            )
        ]

    def close(self) -> None:
        self._session = None
        self._initialized = False
