from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{SRC}{os.pathsep}{pythonpath}" if pythonpath else str(SRC)
    )
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def test_compileall_smoke() -> None:
    result = _run([sys.executable, "-m", "compileall", "-q", "src"])
    assert result.returncode == 0, result.stderr


def test_cli_doctor_smoke() -> None:
    result = _run([sys.executable, "-m", "robot_life.app", "doctor"])
    assert result.returncode == 0, result.stderr
    assert "Robot Life Desktop MVP" in result.stdout


def test_cli_detector_status_smoke() -> None:
    result = _run([sys.executable, "-m", "robot_life.app", "detector-status"])
    assert result.returncode == 0, result.stderr
    assert "Detector Status" in result.stdout


def test_cli_run_live_smoke() -> None:
    result = _run([sys.executable, "-m", "robot_life.app", "run-live", "--iterations", "2"])
    assert result.returncode == 0, result.stderr
    assert "Live runtime finished" in result.stdout


def test_validate_4090_script_smoke() -> None:
    result = _run(
        [
            sys.executable,
            "scripts/validate/validate_4090.py",
            "--smoke",
            "--iterations",
            "5",
            "--latency-budget-ms",
            "2000",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "VALIDATION PASSED" in result.stdout


def test_validate_ux_script_smoke() -> None:
    result = _run(
        [
            sys.executable,
            "scripts/validate/validate_ux.py",
            "--duration-sec",
            "2",
            "--max-repeat-streak",
            "100",
            "--max-repeat-within-10s",
            "100",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "UX VALIDATION PASSED" in result.stdout


def test_mock_profile_smoke_entrypoint() -> None:
    result = _run(
        [
            "bash",
            "scripts/validate/smoke_mock_profile.sh",
            "--commands",
            "doctor,detector-status",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "PROFILE SMOKE PASSED: mock" in result.stdout


def test_local_mac_profile_smoke_entrypoint() -> None:
    result = _run(
        [
            "bash",
            "scripts/validate/smoke_local_mac_profile.sh",
            "--commands",
            "doctor,detector-status",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "PROFILE SMOKE PASSED: local_mac" in result.stdout


def test_local_mac_lite_profile_smoke_entrypoint() -> None:
    result = _run(
        [
            "bash",
            "scripts/validate/smoke_local_mac_lite_profile.sh",
            "--commands",
            "doctor,detector-status",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "PROFILE SMOKE PASSED: local_mac_lite" in result.stdout


def test_local_mac_realtime_profile_smoke_entrypoint() -> None:
    result = _run(
        [
            "bash",
            "scripts/validate/smoke_local_mac_realtime_profile.sh",
            "--commands",
            "doctor,detector-status",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "PROFILE SMOKE PASSED: local_mac_realtime" in result.stdout


def test_desktop_4090_profile_smoke_entrypoint() -> None:
    result = _run(
        [
            "bash",
            "scripts/validate/smoke_desktop_4090_profile.sh",
            "--commands",
            "doctor,detector-status",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "PROFILE SMOKE PASSED: desktop_4090" in result.stdout
