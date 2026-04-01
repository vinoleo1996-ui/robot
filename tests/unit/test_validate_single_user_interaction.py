from scripts.validate.validate_single_user_interaction import build_phase_coverage_report


def test_build_phase_coverage_report_counts_passed_rows() -> None:
    report = build_phase_coverage_report(
        [
            {"phase": "approach", "passed": True},
            {"phase": "gaze", "passed": False},
            {"phase": "wave", "passed": True},
            {"phase": "ambient_motion", "passed": False},
            {"phase": "loud_sound", "passed": True},
        ]
    )

    assert report["total_phases"] == 5
    assert report["passed_phases"] == 3
    assert report["coverage_ratio"] == 0.6
    assert report["coverage_percent"] == 60.0


def test_build_phase_coverage_report_handles_empty_rows() -> None:
    report = build_phase_coverage_report([])
    assert report["total_phases"] == 0
    assert report["passed_phases"] == 0
    assert report["coverage_ratio"] == 0.0
    assert report["coverage_percent"] == 0.0
