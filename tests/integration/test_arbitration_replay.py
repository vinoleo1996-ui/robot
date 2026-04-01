from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = PROJECT_ROOT / "data" / "scenarios"
REPLAY_SCRIPT = PROJECT_ROOT / "scripts" / "replay_arbitration_scenarios.py"
CANONICAL_SCENARIOS = {
    "greeting_then_gesture": {
        "executed_behaviors": ["perform_greeting", "perform_gesture_response"],
        "pending_queue": 0,
        "last_outcome": "dequeued",
    },
    "gesture_queue": {
        "executed_behaviors": ["perform_greeting"],
        "pending_queue": 1,
        "last_outcome": "queued",
    },
    "attention_soft_interrupt": {
        "executed_behaviors": ["perform_attention", "perform_greeting"],
        "pending_queue": 0,
        "last_outcome": "executed",
    },
    "safety_hard_interrupt": {
        "executed_behaviors": ["perform_attention", "perform_safety_alert"],
        "pending_queue": 0,
        "last_outcome": "executed",
    },
    "motion_p3_background": {
        "executed_behaviors": ["perform_tracking", "perform_greeting"],
        "pending_queue": 0,
        "last_outcome": "executed",
    },
    "replace_debounce_same_target": {
        "executed_behaviors": ["perform_greeting"],
        "pending_queue": 0,
        "last_outcome": "debounced",
    },
    "starvation_queue_promotion": {
        "executed_behaviors": ["perform_greeting", "perform_attention", "perform_tracking"],
        "pending_queue": 0,
        "last_outcome": "dequeued",
    },
    "cooldown_recovery": {
        "executed_behaviors": ["perform_greeting", "perform_greeting"],
        "pending_queue": 0,
        "last_outcome": "executed",
    },
}


def _load_scenario(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload.get("steps")
    assert isinstance(payload["steps"], list)
    return payload


def _scenario_paths() -> list[Path]:
    return sorted(path for path in SCENARIO_DIR.glob("*.json") if path.is_file())


def _run_replay(scenario_path: Path, report_path: Path) -> subprocess.CompletedProcess[str]:
    if not REPLAY_SCRIPT.exists():
        pytest.skip(f"replay script missing: {REPLAY_SCRIPT}")

    cmd = [
        sys.executable,
        str(REPLAY_SCRIPT),
        "--scenario",
        str(scenario_path),
        "--report-json",
        str(report_path),
    ]
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_scenario_pack_has_base_and_boundary_coverage() -> None:
    paths = _scenario_paths()
    assert len(paths) >= 8

    scenario_ids = {path.stem for path in paths}
    assert set(CANONICAL_SCENARIOS).issubset(scenario_ids)

    for scenario_id in CANONICAL_SCENARIOS:
        payload = _load_scenario(SCENARIO_DIR / f"{scenario_id}.json")
        assert payload.get("category") in {"base", "boundary"} or payload.get("name")
        assert payload.get("description")


@pytest.mark.parametrize("scenario_path", _scenario_paths(), ids=lambda path: path.stem)
def test_replay_cli_generates_structured_report_for_all_scenarios(
    tmp_path: Path,
    scenario_path: Path,
) -> None:
    report_path = tmp_path / f"{scenario_path.stem}.report.json"
    result = _run_replay(scenario_path, report_path)

    assert result.returncode == 0, result.stderr or result.stdout
    assert report_path.exists(), result.stdout

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["scenario_name"]
    assert report["scenario_path"].endswith(scenario_path.name)
    assert isinstance(report["steps"], list)
    assert isinstance(report["detections"], list)
    assert isinstance(report["stable_events"], list)
    assert isinstance(report["scenes"], list)
    assert isinstance(report["decisions"], list)
    assert isinstance(report["executions"], list)
    assert "pending_queue" in report
    assert "last_outcome" in report


@pytest.mark.parametrize(
    "scenario_id,expected",
    [
        pytest.param(scenario_id, expected, id=scenario_id)
        for scenario_id, expected in CANONICAL_SCENARIOS.items()
    ],
)
def test_canonical_scenarios_match_expected_behaviors(
    tmp_path: Path,
    scenario_id: str,
    expected: dict[str, object],
) -> None:
    scenario_path = SCENARIO_DIR / f"{scenario_id}.json"
    report_path = tmp_path / f"{scenario_id}.report.json"
    result = _run_replay(scenario_path, report_path)

    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(report_path.read_text(encoding="utf-8"))

    executed_behaviors = [item["behavior_id"] for item in report["executions"]]
    assert executed_behaviors == expected["executed_behaviors"]
    assert report["pending_queue"] == expected["pending_queue"]
    assert report["last_outcome"] == expected["last_outcome"]
