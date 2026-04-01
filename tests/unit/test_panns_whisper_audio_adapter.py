from __future__ import annotations

from pathlib import Path

import numpy as np

from robot_life.common.schemas import DetectionResult
from robot_life.perception.adapters.panns_whisper_audio_adapter import (
    PANNSWhisperAudioDetector,
    _extract_audio_samples,
)


def test_extract_audio_samples_supports_dict_payload() -> None:
    samples = _extract_audio_samples({"audio": [0.1, -0.2, 0.3]})
    assert samples is not None
    assert samples.shape == (3,)


def test_panns_whisper_audio_detector_buffers_until_window_is_ready() -> None:
    detector = PANNSWhisperAudioDetector(
        {
            "sample_rate": 16000,
            "analysis_window_s": 1.0,
            "classification_cooldown_s": 0.0,
            "speech_cooldown_s": 0.0,
        }
    )
    detector._initialized = True
    detector._panns_model = object()
    detector._classify_audio = lambda samples: DetectionResult.synthetic(  # type: ignore[method-assign]
        detector="panns_whisper_audio",
        event_type="attention_audio",
        confidence=0.88,
        payload={"samples": int(samples.shape[0])},
    )
    detector._has_speech = lambda samples: False  # type: ignore[method-assign]
    detector._transcribe_audio = lambda samples: None  # type: ignore[method-assign]

    assert detector.process({"audio": np.ones(4000, dtype=np.float32)}) == []
    detections = detector.process({"audio": np.ones(12000, dtype=np.float32)})

    assert len(detections) == 1
    assert detections[0].event_type == "attention_audio"
    assert detections[0].payload["samples"] == 16000


def test_panns_whisper_audio_detector_emits_transcription_when_speech_is_present() -> None:
    detector = PANNSWhisperAudioDetector(
        {
            "sample_rate": 16000,
            "analysis_window_s": 1.0,
            "classification_cooldown_s": 0.0,
            "speech_cooldown_s": 0.0,
        }
    )
    detector._initialized = True
    detector._panns_model = object()
    detector._whisper_model = object()
    detector._classify_audio = lambda samples: DetectionResult.synthetic(  # type: ignore[method-assign]
        detector="panns_whisper_audio",
        event_type="loud_sound",
        confidence=0.93,
    )
    detector._has_speech = lambda samples: True  # type: ignore[method-assign]
    detector._transcribe_audio = lambda samples: DetectionResult.synthetic(  # type: ignore[method-assign]
        detector="whisper_asr",
        event_type="speech_detected",
        confidence=0.71,
        payload={"text": "你好"},
    )

    detections = detector.process({"audio": np.ones(16000, dtype=np.float32)})

    assert [item.event_type for item in detections] == ["loud_sound", "speech_detected"]
    assert detections[1].payload["text"] == "你好"


def test_panns_whisper_audio_detector_ring_buffer_keeps_latest_window() -> None:
    detector = PANNSWhisperAudioDetector(
        {
            "sample_rate": 10,
            "analysis_window_s": 0.4,
            "buffer_window_s": 1.0,
        }
    )

    detector._append_audio(np.array([1, 2, 3, 4], dtype=np.float32))
    detector._append_audio(np.array([5, 6, 7, 8, 9, 10], dtype=np.float32))
    detector._append_audio(np.array([11, 12], dtype=np.float32))

    window = detector._current_analysis_window()

    assert detector._audio_buffer.shape == (10,)
    assert detector._audio_buffer_count == 10
    assert window is not None
    assert np.array_equal(window, np.array([9, 10, 11, 12], dtype=np.float32))


def test_ensure_file_redownloads_existing_asset_when_validation_fails(tmp_path: Path) -> None:
    detector = PANNSWhisperAudioDetector()
    target = tmp_path / "asset.bin"
    target.write_bytes(b"stale-binary")

    validation_calls: list[bytes] = []

    def _validator(path: Path) -> bool:
        payload = path.read_bytes()
        validation_calls.append(payload)
        return payload == b"fresh-binary"

    def _download(url: str, path: Path, *, min_size_bytes: int) -> None:
        path.write_bytes(b"fresh-binary")

    detector._download_file_atomic = _download  # type: ignore[method-assign]

    resolved = detector._ensure_file(
        target,
        url="https://example.invalid/asset.bin",
        min_size_bytes=4,
        validator=_validator,
    )

    assert resolved == target
    assert target.read_bytes() == b"fresh-binary"
    assert validation_calls == [b"stale-binary", b"fresh-binary"]


def test_is_valid_panns_checkpoint_rejects_size_mismatch(tmp_path: Path) -> None:
    detector = PANNSWhisperAudioDetector()
    detector._torch = object()
    checkpoint = tmp_path / "checkpoint.pth"
    checkpoint.write_bytes(b"x" * 32)

    assert detector._is_valid_panns_checkpoint(checkpoint) is False


def test_ensure_panns_runtime_labels_copies_local_labels_to_home_cache(tmp_path: Path, monkeypatch) -> None:
    detector = PANNSWhisperAudioDetector()
    fake_home = tmp_path / "home"
    labels_path = tmp_path / "labels.csv"
    labels_path.write_text("index,mid,display_name\n0,/m/test,Speech\n", encoding="utf-8")
    monkeypatch.setattr(
        "robot_life.perception.adapters.panns_whisper_audio_adapter.Path.home",
        classmethod(lambda cls: fake_home),
    )

    detector._ensure_panns_runtime_labels(labels_path)

    runtime_copy = fake_home / "panns_data" / "class_labels_indices.csv"
    assert runtime_copy.read_text(encoding="utf-8") == labels_path.read_text(encoding="utf-8")
