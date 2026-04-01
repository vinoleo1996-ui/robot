from robot_life.profiles import get_profile_spec
from robot_life.runtime import load_detector_config


def test_launcher_aliases_resolve_to_same_local_mac_profile() -> None:
    hybrid = get_profile_spec("hybrid")
    full = get_profile_spec("full")

    assert hybrid.key == "local_mac"
    assert full.key == "local_mac"
    assert hybrid.runtime_config == full.runtime_config
    assert hybrid.detector_config == full.detector_config


def test_local_mac_profile_requires_all_five_pipelines() -> None:
    spec = get_profile_spec("local_mac")

    assert spec.required_pipelines == ("face", "gesture", "gaze", "audio", "motion")
    assert spec.default_camera_timeout_ms >= 180
    assert spec.default_refresh_ms >= 200


def test_lite_profile_keeps_its_own_required_pipeline_set() -> None:
    spec = get_profile_spec("lite")

    assert spec.required_pipelines == ("face", "audio", "motion")


def test_local_mac_profile_keeps_face_on_gpu_and_semantic_audio_stable() -> None:
    spec = get_profile_spec("hybrid")
    detector_cfg = load_detector_config(spec.detector_config)

    face_cfg = detector_cfg["detectors"]["face"]["config"]
    audio_cfg = detector_cfg["detectors"]["audio"]

    assert face_cfg["use_gpu"] is True
    assert audio_cfg["detector_type"] == "panns_whisper"
    assert audio_cfg["config"]["panns_device"] == "auto"
    assert audio_cfg["config"]["whisper_enabled"] is False


def test_full_gpu_profile_pins_semantic_audio_to_mps() -> None:
    spec = get_profile_spec("full-gpu")
    detector_cfg = load_detector_config(spec.detector_config)

    audio_cfg = detector_cfg["detectors"]["audio"]

    assert audio_cfg["detector_type"] == "panns_whisper"
    assert audio_cfg["config"]["panns_device"] == "mps"
    assert audio_cfg["config"]["whisper_device"] == "cpu"


def test_local_mac_profiles_reduce_microphone_buffer_depth_for_local_ui_latency() -> None:
    for profile_name in ("hybrid", "full-gpu", "realtime"):
        spec = get_profile_spec(profile_name)
        detector_cfg = load_detector_config(spec.detector_config)

        assert detector_cfg["detector_global"]["microphone_max_buffer_packets"] == 24
