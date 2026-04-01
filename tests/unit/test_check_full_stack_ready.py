from scripts.validate.check_full_stack_ready import evaluate_pipeline_status
from robot_life.profiles import get_profile_spec


def test_evaluate_pipeline_status_passes_when_all_required_ready() -> None:
    pipelines = [
        {"name": "face", "enabled": True, "status": "ready"},
        {"name": "gesture", "enabled": True, "status": "ready"},
        {"name": "gaze", "enabled": True, "status": "ready"},
        {"name": "audio", "enabled": True, "status": "ready"},
        {"name": "motion", "enabled": True, "status": "ready"},
    ]

    ok, issues = evaluate_pipeline_status(
        pipelines,
        required=get_profile_spec("realtime").required_pipelines,
    )

    assert ok is True
    assert issues == []


def test_evaluate_pipeline_status_reports_missing_or_non_ready_pipeline() -> None:
    pipelines = [
        {"name": "face", "enabled": True, "status": "ready"},
        {"name": "gesture", "enabled": False, "status": "ready"},
        {"name": "gaze", "enabled": True, "status": "loading"},
        {"name": "audio", "enabled": True, "status": "degraded", "reason": "backend_missing"},
    ]

    ok, issues = evaluate_pipeline_status(
        pipelines,
        required=get_profile_spec("realtime").required_pipelines,
    )

    assert ok is False
    assert any("pipeline=gesture not enabled" in item for item in issues)
    assert any("pipeline=gaze status=loading" in item for item in issues)
    assert any("pipeline=audio status=degraded reason=backend_missing" in item for item in issues)
    assert any("pipeline=motion missing" in item for item in issues)


def test_evaluate_pipeline_status_allows_degraded_when_requested() -> None:
    pipelines = [
        {"name": "face", "enabled": True, "status": "degraded"},
        {"name": "gesture", "enabled": True, "status": "ready"},
        {"name": "gaze", "enabled": True, "status": "ready"},
        {"name": "audio", "enabled": True, "status": "ready"},
        {"name": "motion", "enabled": True, "status": "ready"},
    ]

    ok, issues = evaluate_pipeline_status(
        pipelines,
        required=get_profile_spec("realtime").required_pipelines,
        allow_degraded=True,
    )

    assert ok is True
    assert issues == []


def test_evaluate_pipeline_status_uses_profile_specific_required_pipelines() -> None:
    pipelines = [
        {"name": "face", "enabled": True, "status": "ready"},
        {"name": "audio", "enabled": True, "status": "ready"},
        {"name": "motion", "enabled": True, "status": "ready"},
    ]

    ok, issues = evaluate_pipeline_status(
        pipelines,
        required=get_profile_spec("lite").required_pipelines,
    )

    assert ok is True
    assert issues == []
