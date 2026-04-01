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


def test_validate_microphone_only_script_reports_summary() -> None:
    result = _run([sys.executable, "scripts/validate/validate_microphone_only.py"])
    assert result.returncode == 0, result.stderr
    assert "Microphone Validation Summary" in result.stdout
    assert "mode=" in result.stdout
    assert "backend=" in result.stdout
    assert "PASS" in result.stdout
