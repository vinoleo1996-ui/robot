#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from robot_life.profiles import get_profile_spec, smoke_profile_choices

def _env() -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{PROJECT_SRC}{os.pathsep}{pythonpath}" if pythonpath else str(PROJECT_SRC)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _pick_free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _ui_demo_available() -> bool:
    try:
        _pick_free_port()
    except PermissionError:
        return False
    except OSError:
        return False
    return True


def _run_step(name: str, args: list[str]) -> None:
    print(f"[smoke] step={name}")
    print(f"[smoke] cmd={' '.join(args)}")
    result = subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=_env(),
        timeout=90,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(f"profile smoke failed at step={name} rc={result.returncode}")


def _command_args(profile_name: str, step: str) -> list[str]:
    spec = get_profile_spec(profile_name)
    runtime_config = spec.smoke_runtime_config or spec.runtime_config
    detector_config = spec.detector_config
    stabilizer_config = spec.stabilizer_config
    base = [
        sys.executable,
        "-m",
        "robot_life.app",
    ]
    if step == "doctor":
        return base + ["doctor", "--config", str(runtime_config)]
    if step == "detector-status":
        return base + [
            "detector-status",
            "--config",
            str(runtime_config),
            "--detectors",
            str(detector_config),
        ]
    if step == "run-live":
        args = base + [
            "run-live",
            "--config",
            str(runtime_config),
            "--detectors",
            str(detector_config),
            "--iterations",
            "2",
        ]
        if stabilizer_config is not None:
            args += ["--stabilizer-config", str(stabilizer_config)]
        return args
    if step == "ui-demo":
        args = base + [
            "ui-demo",
            "--config",
            str(runtime_config),
            "--detectors",
            str(detector_config),
            "--host",
            "127.0.0.1",
            "--port",
            str(_pick_free_port()),
            "--refresh-ms",
            "150",
            "--duration-sec",
            "1",
        ]
        if stabilizer_config is not None:
            args += ["--stabilizer-config", str(stabilizer_config)]
        return args
    raise ValueError(f"unknown step: {step}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run profile-specific CLI smoke suites.")
    parser.add_argument(
        "--profile",
        choices=sorted(smoke_profile_choices()),
        required=True,
        help="Which profile smoke suite to run.",
    )
    parser.add_argument(
        "--commands",
        default="doctor,detector-status,run-live,ui-demo",
        help="Comma-separated steps to run.",
    )
    args = parser.parse_args()

    steps = [item.strip() for item in str(args.commands).split(",") if item.strip()]
    if not steps:
        raise SystemExit("no smoke commands selected")
    spec = get_profile_spec(args.profile)
    runtime_config = spec.smoke_runtime_config or spec.runtime_config

    print(f"[smoke] profile={args.profile}")
    print(f"[smoke] runtime_config={runtime_config}")
    print(f"[smoke] detector_config={spec.detector_config}")

    ui_demo_available = _ui_demo_available()
    for step in steps:
        if step == "ui-demo" and not ui_demo_available:
            print("[smoke] step=ui-demo")
            print("[smoke] skipped=ui-demo reason=tcp_bind_not_permitted")
            continue
        _run_step(step, _command_args(args.profile, step))

    print(f"PROFILE SMOKE PASSED: {args.profile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
