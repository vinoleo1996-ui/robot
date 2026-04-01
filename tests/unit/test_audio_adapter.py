import logging

from robot_life.perception.adapters.audio_adapter import RMSLoudSoundDetector


def test_silence_does_not_trigger_loud_sound() -> None:
    detector = RMSLoudSoundDetector(config={"rms_threshold": 0.2, "cooldown_s": 0.0})
    detector.initialize()

    detections = detector.process([0.0] * 256)

    assert detections == []


def test_loud_sound_triggers_detection() -> None:
    detector = RMSLoudSoundDetector(config={"rms_threshold": 0.2, "cooldown_s": 0.0})
    detector.initialize()

    detections = detector.process([0.5, -0.5] * 128)

    assert len(detections) == 1
    detection = detections[0]
    assert detection.event_type == "loud_sound"
    assert detection.detector == "rms_audio"
    assert detection.payload["rms"] >= 0.2


def test_cooldown_blocks_immediate_repeat_trigger() -> None:
    detector = RMSLoudSoundDetector(config={"rms_threshold": 0.1, "cooldown_s": 10.0})
    detector.initialize()

    audio_chunk = [1.0] * 128
    first = detector.process(audio_chunk)
    second = detector.process(audio_chunk)

    assert len(first) == 1
    assert second == []

    detector._last_trigger_monotonic -= 11.0
    third = detector.process(audio_chunk)
    assert len(third) == 1


def test_legacy_config_keys_are_supported() -> None:
    detector = RMSLoudSoundDetector(
        config={
            "energy_threshold_db": -20,
            "global_cooldown_sec": 0.0,
            "frame_length": 0.01,
            "sample_rate": 16000,
        }
    )
    detector.initialize()
    detections = detector.process([0.9] * 400)
    assert len(detections) == 1


def test_positive_db_threshold_falls_back_to_rms_threshold(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        detector = RMSLoudSoundDetector(
            config={
                "rms_threshold": 0.1,
                "energy_threshold_db": 68,
                "cooldown_s": 0.0,
            }
        )
    detector.initialize()
    detections = detector.process([0.5, -0.5] * 128)
    assert len(detections) == 1
    assert detections[0].payload["db_threshold"] is None
    assert "db_threshold=68.0 is above 0 dBFS" in caplog.text


def test_threshold_mode_any_can_trigger_with_db_only() -> None:
    detector = RMSLoudSoundDetector(
        config={
            "rms_threshold": 0.2,  # intentionally high
            "energy_threshold_db": -20,  # easier to satisfy
            "threshold_mode": "any",
            "cooldown_s": 0.0,
        }
    )
    detector.initialize()
    # RMS ~0.11 (<0.2) but db ~-19 dB (>= -20)
    detections = detector.process([0.11, -0.11] * 256)
    assert len(detections) == 1


def test_threshold_mode_all_requires_both_thresholds() -> None:
    detector = RMSLoudSoundDetector(
        config={
            "rms_threshold": 0.2,  # intentionally high
            "energy_threshold_db": -20,  # easier to satisfy
            "threshold_mode": "all",
            "cooldown_s": 0.0,
        }
    )
    detector.initialize()
    detections = detector.process([0.11, -0.11] * 256)
    assert detections == []


def test_relative_threshold_can_trigger_when_absolute_threshold_is_not_met() -> None:
    detector = RMSLoudSoundDetector(
        config={
            "rms_threshold": 0.30,
            "energy_threshold_db": -8,
            "threshold_mode": "all",
            "relative_multiplier": 2.2,
            "relative_min_rms": 0.03,
            "baseline_alpha": 0.4,
            "cooldown_s": 0.0,
        }
    )
    detector.initialize()

    first = detector.process([0.02, -0.02] * 256)
    second = detector.process([0.06, -0.06] * 256)

    assert first == []
    assert len(second) == 1
    assert second[0].payload["relative_triggered"] is True
    assert second[0].payload["threshold_mode"] == "all"


def test_relative_threshold_respects_min_rms_guard() -> None:
    detector = RMSLoudSoundDetector(
        config={
            "rms_threshold": 0.5,
            "energy_threshold_db": -2,
            "threshold_mode": "all",
            "relative_multiplier": 1.5,
            "relative_min_rms": 0.03,
            "baseline_alpha": 0.5,
            "cooldown_s": 0.0,
        }
    )
    detector.initialize()

    detector.process([0.001, -0.001] * 256)
    detections = detector.process([0.002, -0.002] * 256)

    assert detections == []


def test_runtime_threshold_update_changes_detector_sensitivity() -> None:
    detector = RMSLoudSoundDetector(config={"rms_threshold": 0.1, "energy_threshold_db": -20, "cooldown_s": 0.0})
    detector.initialize()

    first = detector.process([0.12, -0.12] * 256)
    updated = detector.update_thresholds(rms_threshold=0.2, db_threshold=-12.0)
    second = detector.process([0.12, -0.12] * 256)

    assert len(first) == 1
    assert updated["rms_threshold"] == 0.2
    assert updated["db_threshold"] == -12.0
    assert detector.config["rms_threshold"] == 0.2
    assert detector.config["db_threshold"] == -12.0
    assert detector.config["energy_threshold_db"] == -12.0
    assert second == []
