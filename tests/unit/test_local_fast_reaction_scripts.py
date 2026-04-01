from __future__ import annotations

from pathlib import Path
import os
import socket
import subprocess
import sys

from scripts.validate.preflight_local_fast_reaction import _camera_issue, _microphone_issue


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _run(
    args: list[str],
    timeout: int = 60,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{SRC}{os.pathsep}{pythonpath}" if pythonpath else str(SRC)
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _ui_demo_available() -> bool:
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
    except PermissionError:
        return False
    except OSError:
        return False
    return True


def test_camera_permission_issue_provides_mac_hint() -> None:
    issue = _camera_issue("camera probe failed: OpenCV: not authorized to capture video")
    assert issue.scope == "camera"
    assert issue.code == "permission_denied"
    assert issue.mock_compatible is True
    assert "隐私与安全性 -> 相机" in issue.hint


def test_microphone_no_device_issue_is_mock_compatible() -> None:
    issue = _microphone_issue("no input microphone device detected")
    assert issue.scope == "microphone"
    assert issue.code == "no_input_device"
    assert issue.mock_compatible is True
    assert "--mock-if-unavailable" in issue.hint


def test_launcher_usage_mentions_mock_flags() -> None:
    result = _run(["bash", "scripts/launch/run_ui_local_fast_reaction.sh", "invalid"])
    assert result.returncode == 1
    combined = f"{result.stdout}\n{result.stderr}"
    assert "--mock-if-unavailable" in combined
    assert "--skip-preflight" in combined
    assert "--ci-mock" in combined
    assert "--foreground" in combined
    assert "--hybrid" in combined
    assert "--lite" in combined
    assert "--realtime" in combined


def test_launcher_status_and_stop_track_real_child_pid() -> None:
    if not _ui_demo_available():
        return
    env = {
        "HOST": "127.0.0.1",
        "PORT": "8876",
        "STARTUP_STABILITY_WAIT_S": "1",
    }
    _run(["bash", "scripts/launch/run_ui_local_fast_reaction.sh", "stop"], extra_env=env)
    try:
        start = _run(
            ["bash", "scripts/launch/run_ui_local_fast_reaction.sh", "start", "--ci-mock", "--hybrid"],
            timeout=90,
            extra_env=env,
        )
        assert start.returncode == 0, start.stderr
        assert "started ui-demo local fast-reaction" in start.stdout

        status = _run(
            ["bash", "scripts/launch/run_ui_local_fast_reaction.sh", "status"],
            extra_env=env,
        )
        combined = f"{status.stdout}\n{status.stderr}"
        assert "status: running pid=" in combined
        assert "health: mode=mock" in combined
    finally:
        stop = _run(
            ["bash", "scripts/launch/run_ui_local_fast_reaction.sh", "stop"],
            extra_env=env,
        )
        assert stop.returncode == 0


def test_mac_demo_entrypoints_launch_expected_profiles() -> None:
    if not _ui_demo_available():
        return
    env = {
        "AUTO_OPEN_BROWSER": "0",
        "HOST": "127.0.0.1",
        "PORT": "8897",
        "STARTUP_STABILITY_WAIT_S": "1",
    }
    scripts = [
        ("run_demo_mac.sh", "profile=local_mac"),
        ("run_demo_mac_full_gpu.sh", "profile=local_mac_full_gpu"),
    ]

    for script_name, expected_profile in scripts:
        _run(
            ["bash", "scripts/launch/run_ui_local_fast_reaction.sh", "stop"],
            extra_env=env,
        )
        try:
            result = _run(["bash", script_name, "--ci-mock"], timeout=90, extra_env=env)
            combined = f"{result.stdout}\n{result.stderr}"
            assert result.returncode == 0, combined
            assert "UI address: http://127.0.0.1:8897" in combined
            assert expected_profile in combined
        finally:
            stop = _run(
                ["bash", "scripts/launch/run_ui_local_fast_reaction.sh", "stop"],
                extra_env=env,
            )
            assert stop.returncode == 0
