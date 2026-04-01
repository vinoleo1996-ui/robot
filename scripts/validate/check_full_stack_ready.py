#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from robot_life.profiles import get_profile_spec, launcher_profile_choices


def _launch_cmd(profile: str, *, mock_if_unavailable: bool) -> list[str]:
    cmd = ["./scripts/launch/run_ui_local_fast_reaction.sh", "start", f"--{profile}"]
    if mock_if_unavailable:
        cmd.append("--mock-if-unavailable")
    return cmd


def _stop_cmd() -> list[str]:
    return ["./scripts/launch/run_ui_local_fast_reaction.sh", "stop"]


def _fetch_state(url: str, timeout_s: float = 1.0) -> dict[str, Any] | None:
    try:
        with urlopen(url, timeout=timeout_s) as response:
            if response.status != 200:
                return None
            payload = response.read().decode("utf-8")
    except (URLError, TimeoutError):
        return None
    except Exception:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def evaluate_pipeline_status(
    pipelines: list[dict[str, Any]],
    *,
    required: tuple[str, ...],
    allow_degraded: bool = False,
) -> tuple[bool, list[str]]:
    allowed_statuses = {"ready"}
    if allow_degraded:
        allowed_statuses.add("degraded")
    by_name: dict[str, dict[str, Any]] = {}
    for item in pipelines:
        name = str(item.get("name", "")).strip()
        if name:
            by_name[name] = item

    issues: list[str] = []
    for name in required:
        payload = by_name.get(name)
        if payload is None:
            issues.append(f"pipeline={name} missing")
            continue
        enabled = bool(payload.get("enabled", False))
        status = str(payload.get("status", "")).strip().lower()
        reason = str(payload.get("reason", "")).strip()
        if not enabled:
            issues.append(f"pipeline={name} not enabled")
        if status not in allowed_statuses:
            if reason:
                issues.append(f"pipeline={name} status={status} reason={reason}")
            else:
                issues.append(f"pipeline={name} status={status}")
    return (len(issues) == 0, issues)


def _run_command(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode, output


def main() -> int:
    parser = argparse.ArgumentParser(description="Start local fast-reaction UI and verify five pipelines are ready.")
    parser.add_argument("--profile", choices=list(launcher_profile_choices()), default="realtime")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--timeout-sec", type=float, default=35.0)
    parser.add_argument("--poll-interval-sec", type=float, default=1.0)
    parser.add_argument("--mock-if-unavailable", action="store_true")
    parser.add_argument("--allow-degraded", action="store_true")
    parser.add_argument("--no-start", action="store_true", help="Only check currently running UI state.")
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="Do not stop ui-demo after verification.",
    )
    args = parser.parse_args()

    started_by_script = False
    if not args.no_start:
        cmd = _launch_cmd(args.profile, mock_if_unavailable=bool(args.mock_if_unavailable))
        rc, output = _run_command(cmd)
        if output:
            print(output)
        if rc != 0:
            print("FAIL")
            print("reason=start_failed")
            return rc
        started_by_script = True

    state_url = f"http://{args.host}:{args.port}/api/state"
    deadline = time.monotonic() + max(2.0, float(args.timeout_sec))
    state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        state = _fetch_state(state_url)
        if state is not None:
            break
        time.sleep(max(0.2, float(args.poll_interval_sec)))

    if state is None:
        print("FAIL")
        print("reason=state_unavailable")
        if started_by_script and not args.keep_running:
            _run_command(_stop_cmd())
        return 1

    fast_reaction = state.get("fast_reaction", {})
    pipelines = []
    if isinstance(fast_reaction, dict):
        raw = fast_reaction.get("pipelines", [])
        if isinstance(raw, list):
            pipelines = [item for item in raw if isinstance(item, dict)]

    required_pipelines = get_profile_spec(args.profile).required_pipelines
    ok, issues = evaluate_pipeline_status(
        pipelines,
        required=required_pipelines,
        allow_degraded=bool(args.allow_degraded),
    )

    print("=== Full Stack Ready Summary ===")
    print(f"profile={args.profile}")
    print(f"url=http://{args.host}:{args.port}")
    print(f"mode={state.get('mode', '-')}")
    for item in pipelines:
        name = str(item.get("name", "-"))
        enabled = bool(item.get("enabled", False))
        status = str(item.get("status", "-"))
        reason = str(item.get("reason", "")).strip()
        compute_target = str(item.get("compute_target", "-"))
        line = f"pipeline={name} enabled={enabled} status={status} compute={compute_target}"
        if reason:
            line += f" reason={reason}"
        print(line)

    if issues:
        print("FAIL")
        for issue in issues:
            print(f"- {issue}")
        if started_by_script and not args.keep_running:
            _run_command(_stop_cmd())
        return 1

    print("PASS")
    if started_by_script and not args.keep_running:
        _run_command(_stop_cmd())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
