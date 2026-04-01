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


def test_validate_camera_only_script_smoke_passes_in_mock_mode() -> None:
    result = _run(
        [
            sys.executable,
            "scripts/validate/validate_camera_only.py",
            "--mock-drivers",
            "--iterations",
            "5",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_validate_camera_only_script_returns_fail_when_packets_are_insufficient() -> None:
    result = _run(
        [
            sys.executable,
            "scripts/validate/validate_camera_only.py",
            "--mock-drivers",
            "--iterations",
            "3",
            "--min-camera-packets",
            "999",
        ]
    )
    assert result.returncode == 1
    assert "FAIL" in result.stdout


def test_validate_camera_only_script_accepts_camera_threshold_flags() -> None:
    result = _run(
        [
            sys.executable,
            "scripts/validate/validate_camera_only.py",
            "--mock-drivers",
            "--iterations",
            "3",
            "--max-camera-recoveries",
            "0",
            "--max-camera-failures",
            "0",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout
