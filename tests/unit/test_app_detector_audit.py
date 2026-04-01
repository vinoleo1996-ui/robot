from robot_life.app import _audit_detector_model_paths


def test_detector_model_audit_flags_placeholder_paths() -> None:
    errors, warnings = _audit_detector_model_paths(
        {
            "detectors": {
                "face": {
                    "enabled": True,
                    "model_path": "NA",
                }
            }
        },
        enabled_pipelines=["face"],
    )
    assert warnings == []
    assert len(errors) == 1
    assert "placeholder" in errors[0]


def test_detector_model_audit_accepts_builtin_and_autodownload_models() -> None:
    errors, warnings = _audit_detector_model_paths(
        {
            "detectors": {
                "audio": {
                    "enabled": True,
                    "model_path": "builtin:robot_life/rms_loud_sound_v1",
                },
                "motion": {
                    "enabled": True,
                    "model_path": "yolov8n.pt",
                },
            }
        },
        enabled_pipelines=["audio", "motion"],
    )
    assert errors == []
    assert len(warnings) == 1
    assert "auto-download" in warnings[0]
