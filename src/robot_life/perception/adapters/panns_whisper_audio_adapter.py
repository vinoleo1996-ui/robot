"""Semantic audio detector using PANNs + Silero VAD + faster-whisper."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
import shutil
from time import monotonic, time
from typing import Any, Callable
from urllib.request import urlopen

import numpy as np

from robot_life.common.schemas import DetectionResult
from robot_life.common.tracing import new_trace_id
from robot_life.perception.base import DetectorBase

logger = logging.getLogger(__name__)

_PANN_LABELS_URL = "https://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv"
_PANN_CHECKPOINT_URL = "https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth?download=1"
_PANN_CHECKPOINT_EXPECTED_BYTES = 327_428_481
_PANN_CHECKPOINT_MIN_BYTES = 320_000_000


def _extract_audio_samples(frame: Any) -> np.ndarray | None:
    candidate = frame
    if isinstance(frame, dict):
        for key in ("audio", "samples", "chunk", "data"):
            if key in frame:
                candidate = frame[key]
                break
        else:
            return None
    try:
        samples = np.asarray(candidate, dtype=np.float32).reshape(-1)
    except Exception:
        return None
    if samples.size == 0:
        return None
    return samples


def _resolve_panns_device(raw_device: str | None) -> str:
    import torch

    device = str(raw_device or "auto").strip().lower()
    if device in {"auto", ""}:
        if bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"
    if device.startswith("mps"):
        if bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if device.startswith("cuda"):
        return "cuda" if torch.cuda.is_available() else "cpu"
    return "cpu"


def _resolve_whisper_device(raw_device: str | None) -> str:
    import torch

    device = str(raw_device or "auto").strip().lower()
    if device in {"auto", ""}:
        return "cuda" if torch.cuda.is_available() else "cpu"
    if device.startswith("cuda"):
        return "cuda" if torch.cuda.is_available() else "cpu"
    return "cpu"


def _normalize_label(label: str) -> str:
    return str(label or "").strip().lower()


def _default_speech_labels() -> set[str]:
    return {
        "speech",
        "conversation",
        "narration, monologue",
        "babbling",
        "child speech, kid speaking",
        "male speech, man speaking",
        "female speech, woman speaking",
    }


def _default_safety_labels() -> set[str]:
    return {
        "alarm",
        "alarm clock",
        "siren",
        "doorbell",
        "crying, sobbing",
        "baby cry, infant cry",
        "glass",
        "glass breaking",
        "breaking",
        "smoke detector, smoke alarm",
        "fire alarm",
    }


class PANNSWhisperAudioDetector(DetectorBase):
    """Combined semantic audio detector for local real-device runtime."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("panns_whisper_audio", "microphone", config)
        self._input_sample_rate = int(self.config.get("sample_rate", 16000))
        self._analysis_window_s = float(self.config.get("analysis_window_s", 1.5))
        self._buffer_window_s = float(self.config.get("buffer_window_s", 4.0))
        self._analysis_window_samples = max(1, int(self._analysis_window_s * self._input_sample_rate))
        self._buffer_max_samples = max(
            self._analysis_window_samples,
            int(self._buffer_window_s * self._input_sample_rate),
        )
        self._panns_confidence_threshold = float(self.config.get("panns_confidence_threshold", 0.28))
        self._panns_top_k = int(self.config.get("panns_top_k", 5))
        self._panns_device = "cpu"
        self._whisper_device = "cpu"
        self._whisper_enabled = bool(self.config.get("whisper_enabled", True))
        self._vad_enabled = bool(self.config.get("vad_enabled", True))
        self._whisper_min_text_length = int(self.config.get("whisper_min_text_length", 2))
        self._whisper_min_confidence = float(self.config.get("whisper_min_confidence", 0.2))
        self._classification_cooldown_s = float(self.config.get("classification_cooldown_s", 0.75))
        self._speech_cooldown_s = float(self.config.get("speech_cooldown_s", 1.75))
        self._vad_threshold = float(self.config.get("vad_threshold", 0.5))
        self._vad_min_speech_duration_ms = int(self.config.get("vad_min_speech_duration_ms", 180))
        self._vad_min_silence_duration_ms = int(self.config.get("vad_min_silence_duration_ms", 120))
        self._speech_labels = {_normalize_label(item) for item in self.config.get("speech_labels", _default_speech_labels())}
        self._safety_labels = {_normalize_label(item) for item in self.config.get("safety_labels", _default_safety_labels())}

        self._audio_buffer = np.zeros((self._buffer_max_samples,), dtype=np.float32)
        self._audio_buffer_count = 0
        self._audio_buffer_write_index = 0
        self._last_classification_at = 0.0
        self._last_speech_at = 0.0
        self._panns_model: Any = None
        self._panns_labels: list[str] = []
        self._vad_model: Any = None
        self._whisper_model: Any = None
        self._librosa: Any = None
        self._torch: Any = None

    def initialize(self) -> None:
        import librosa
        import torch

        self._librosa = librosa
        self._torch = torch

        labels_path = self._ensure_file(
            self.config.get("panns_labels_path", "models/audio/panns/class_labels_indices.csv"),
            url=_PANN_LABELS_URL,
            min_size_bytes=1024,
        )
        checkpoint_path = self._ensure_file(
            self.config.get("panns_checkpoint_path", "models/audio/panns/Cnn14_mAP=0.431.pth"),
            url=_PANN_CHECKPOINT_URL,
            min_size_bytes=int(self.config.get("panns_checkpoint_min_bytes", _PANN_CHECKPOINT_MIN_BYTES)),
            validator=self._is_valid_panns_checkpoint,
        )
        self._panns_labels = self._load_panns_labels(labels_path)
        self._ensure_panns_runtime_labels(labels_path)

        self._panns_device = _resolve_panns_device(self.config.get("panns_device", "auto"))
        self._build_panns_model(checkpoint_path)

        if self._vad_enabled:
            from silero_vad import load_silero_vad

            self._vad_model = load_silero_vad(onnx=False)

        if self._whisper_enabled:
            from faster_whisper import WhisperModel

            self._whisper_device = _resolve_whisper_device(self.config.get("whisper_device", "auto"))
            compute_type = str(
                self.config.get(
                    "whisper_compute_type",
                    "float16" if self._whisper_device == "cuda" else "int8",
                )
            )
            self._whisper_model = WhisperModel(
                str(self.config.get("whisper_model_variant", "tiny")),
                device=self._whisper_device,
                compute_type=compute_type,
            )
        self._initialized = True

    def process(self, frame: Any) -> list[DetectionResult]:
        if not self._initialized or self._panns_model is None:
            return []

        samples = _extract_audio_samples(frame)
        if samples is None:
            return []

        self._append_audio(samples)
        analysis_samples = self._current_analysis_window()
        if analysis_samples is None:
            return []

        results: list[DetectionResult] = []
        now = monotonic()

        if (now - self._last_classification_at) >= self._classification_cooldown_s:
            panns_detection = self._classify_audio(analysis_samples)
            if panns_detection is not None:
                results.append(panns_detection)
                self._last_classification_at = now

        if self._whisper_model is not None and self._has_speech(analysis_samples):
            if (now - self._last_speech_at) >= self._speech_cooldown_s:
                speech_detection = self._transcribe_audio(analysis_samples)
                if speech_detection is not None:
                    results.append(speech_detection)
                    self._last_speech_at = now

        return results

    def close(self) -> None:
        self._audio_buffer = np.zeros((self._buffer_max_samples,), dtype=np.float32)
        self._audio_buffer_count = 0
        self._audio_buffer_write_index = 0
        self._panns_model = None
        self._vad_model = None
        self._whisper_model = None
        self._initialized = False

    def update_thresholds(
        self,
        *,
        panns_confidence_threshold: float | None = None,
        vad_threshold: float | None = None,
        classification_cooldown_s: float | None = None,
        speech_cooldown_s: float | None = None,
    ) -> dict[str, float]:
        if panns_confidence_threshold is not None:
            self._panns_confidence_threshold = min(max(0.0, float(panns_confidence_threshold)), 1.0)
        if vad_threshold is not None:
            self._vad_threshold = min(max(0.0, float(vad_threshold)), 1.0)
        if classification_cooldown_s is not None:
            self._classification_cooldown_s = max(0.0, float(classification_cooldown_s))
        if speech_cooldown_s is not None:
            self._speech_cooldown_s = max(0.0, float(speech_cooldown_s))
        return {
            "panns_confidence_threshold": float(self._panns_confidence_threshold),
            "vad_threshold": float(self._vad_threshold),
            "classification_cooldown_s": float(self._classification_cooldown_s),
            "speech_cooldown_s": float(self._speech_cooldown_s),
        }

    def _ensure_file(
        self,
        raw_path: str | Path,
        *,
        url: str,
        min_size_bytes: int,
        validator: Callable[[Path], bool] | None = None,
    ) -> Path:
        path = Path(str(raw_path)).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size >= min_size_bytes:
            if validator is None or validator(path):
                return path
            logger.warning("asset validation failed for %s; re-downloading", path)
            path.unlink(missing_ok=True)
        logger.info("downloading asset %s -> %s", url, path)
        self._download_file_atomic(url, path, min_size_bytes=min_size_bytes)
        if validator is not None and not validator(path):
            path.unlink(missing_ok=True)
            raise RuntimeError(f"downloaded asset failed validation: {path}")
        return path

    def _download_file_atomic(self, url: str, path: Path, *, min_size_bytes: int) -> None:
        tmp_path = path.with_suffix(f"{path.suffix}.download")
        tmp_path.unlink(missing_ok=True)
        with urlopen(url) as response, tmp_path.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 1024)
        size = tmp_path.stat().st_size
        if size < min_size_bytes:
            tmp_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"downloaded asset is too small: expected >= {min_size_bytes} bytes, got {size} ({path})"
            )
        tmp_path.replace(path)

    def _is_valid_panns_checkpoint(self, path: Path) -> bool:
        expected_size = int(
            self.config.get("panns_checkpoint_expected_bytes", _PANN_CHECKPOINT_EXPECTED_BYTES)
        )
        actual_size = path.stat().st_size
        if expected_size > 0 and actual_size != expected_size:
            logger.warning(
                "PANN checkpoint size mismatch for %s: expected=%s actual=%s",
                path,
                expected_size,
                actual_size,
            )
            return False
        try:
            checkpoint = self._torch.load(path, map_location="cpu")
        except Exception as exc:
            logger.warning("failed to load PANN checkpoint %s: %s: %s", path, type(exc).__name__, exc)
            return False
        return isinstance(checkpoint, dict) and "model" in checkpoint

    def _load_panns_labels(self, path: Path) -> list[str]:
        labels: list[str] = []
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.reader(handle, delimiter=",")
            next(reader, None)
            for row in reader:
                if len(row) >= 3:
                    labels.append(row[2])
        if not labels:
            raise RuntimeError(f"no PANN labels loaded from {path}")
        return labels

    def _ensure_panns_runtime_labels(self, labels_path: Path) -> None:
        runtime_labels_path = Path.home() / "panns_data" / "class_labels_indices.csv"
        runtime_labels_path.parent.mkdir(parents=True, exist_ok=True)
        if runtime_labels_path.exists() and runtime_labels_path.read_bytes() == labels_path.read_bytes():
            return
        shutil.copyfile(labels_path, runtime_labels_path)

    def _build_panns_model(self, checkpoint_path: Path) -> None:
        from panns_inference.models import Cnn14

        model = Cnn14(
            sample_rate=32000,
            window_size=1024,
            hop_size=320,
            mel_bins=64,
            fmin=50,
            fmax=14000,
            classes_num=len(self._panns_labels),
        )
        checkpoint = self._torch.load(checkpoint_path, map_location="cpu")
        model.load_state_dict(checkpoint["model"])
        model.eval()
        model.to(self._panns_device)
        self._panns_model = model

    def _append_audio(self, samples: np.ndarray) -> None:
        samples_view = np.asarray(samples, dtype=np.float32).reshape(-1)
        if samples_view.size <= 0:
            return
        if samples_view.size >= self._buffer_max_samples:
            self._audio_buffer[:] = samples_view[-self._buffer_max_samples:]
            self._audio_buffer_count = self._buffer_max_samples
            self._audio_buffer_write_index = 0
            return

        first_chunk = min(samples_view.size, self._buffer_max_samples - self._audio_buffer_write_index)
        second_chunk = samples_view.size - first_chunk
        end_index = self._audio_buffer_write_index + first_chunk
        self._audio_buffer[self._audio_buffer_write_index:end_index] = samples_view[:first_chunk]
        if second_chunk > 0:
            self._audio_buffer[:second_chunk] = samples_view[first_chunk:]
        self._audio_buffer_write_index = (
            self._audio_buffer_write_index + samples_view.size
        ) % self._buffer_max_samples
        self._audio_buffer_count = min(
            self._buffer_max_samples,
            self._audio_buffer_count + samples_view.size,
        )

    def _current_analysis_window(self) -> np.ndarray | None:
        need = self._analysis_window_samples
        if self._audio_buffer_count < need:
            return None
        end_index = self._audio_buffer_write_index
        start_index = (end_index - need) % self._buffer_max_samples
        if start_index < end_index:
            return self._audio_buffer[start_index:end_index]
        return np.concatenate((self._audio_buffer[start_index:], self._audio_buffer[:end_index]))

    def _classify_audio(self, samples_16k: np.ndarray) -> DetectionResult | None:
        assert self._librosa is not None

        samples_32k = self._librosa.resample(samples_16k, orig_sr=self._input_sample_rate, target_sr=32000)
        waveform = np.expand_dims(samples_32k.astype(np.float32), axis=0)
        tensor = self._torch.tensor(waveform, dtype=self._torch.float32, device=self._panns_device)

        with self._torch.no_grad():
            output = self._panns_model(tensor, None)
        clipwise = output["clipwise_output"].detach().cpu().numpy()[0]
        if clipwise.size == 0:
            return None

        top_indices = np.argsort(clipwise)[::-1][: max(1, self._panns_top_k)]
        top_index = int(top_indices[0])
        top_score = float(clipwise[top_index])
        if top_score < self._panns_confidence_threshold:
            return None

        label = self._panns_labels[top_index]
        normalized_label = _normalize_label(label)
        if normalized_label in self._safety_labels or any(token in normalized_label for token in ("alarm", "siren", "glass", "cry")):
            event_type = "loud_sound"
        else:
            event_type = "attention_audio"

        top_candidates = [
            {
                "label": self._panns_labels[int(index)],
                "score": round(float(clipwise[int(index)]), 4),
            }
            for index in top_indices
        ]
        return DetectionResult(
            trace_id=new_trace_id(),
            source="microphone",
            detector=self.name,
            event_type=event_type,
            timestamp=time(),
            confidence=top_score,
            payload={
                "class_name": label,
                "class_index": top_index,
                "top_candidates": top_candidates,
                "audio_backend": "panns",
                "device": self._panns_device,
            },
        )

    def _has_speech(self, samples_16k: np.ndarray) -> bool:
        if self._vad_model is None:
            return True
        from silero_vad import get_speech_timestamps

        waveform = self._torch.tensor(samples_16k, dtype=self._torch.float32)
        timestamps = get_speech_timestamps(
            waveform,
            self._vad_model,
            threshold=self._vad_threshold,
            sampling_rate=self._input_sample_rate,
            min_speech_duration_ms=self._vad_min_speech_duration_ms,
            min_silence_duration_ms=self._vad_min_silence_duration_ms,
        )
        return bool(timestamps)

    def _transcribe_audio(self, samples_16k: np.ndarray) -> DetectionResult | None:
        segments, info = self._whisper_model.transcribe(
            samples_16k,
            language=self.config.get("whisper_language"),
            task=str(self.config.get("whisper_task", "transcribe")),
            beam_size=int(self.config.get("whisper_beam_size", 1)),
            vad_filter=False,
        )
        text_parts: list[str] = []
        for segment in segments:
            text = str(getattr(segment, "text", "")).strip()
            if text:
                text_parts.append(text)
        text = " ".join(text_parts).strip()
        if len(text) < self._whisper_min_text_length:
            return None
        confidence = max(0.0, min(1.0, 1.0 - float(getattr(info, "no_speech_prob", 0.0))))
        if confidence < self._whisper_min_confidence:
            return None
        return DetectionResult(
            trace_id=new_trace_id(),
            source="microphone",
            detector="whisper_asr",
            event_type="speech_detected",
            timestamp=time(),
            confidence=confidence,
            payload={
                "text": text,
                "language": getattr(info, "language", "unknown"),
                "audio_backend": "faster_whisper",
                "device": self._whisper_device,
            },
        )
