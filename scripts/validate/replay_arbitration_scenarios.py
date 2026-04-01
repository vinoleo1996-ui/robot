#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from robot_life.common.config import load_arbitration_config, load_safety_config, load_stabilizer_config
from robot_life.runtime.event_injector import (
    EventReplayRunner,
    load_replay_scenario,
    normalize_replay_scenario,
    validate_replay_scenario,
)


def _default_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay synthetic arbitration scenarios without requiring live camera or microphone."
    )
    parser.add_argument("--scenario", type=Path, required=True, help="Path to a scenario JSON/YAML file.")
    parser.add_argument(
        "--arbitration-config",
        type=Path,
        default=_default_path("configs", "arbitration", "default.yaml"),
    )
    parser.add_argument(
        "--stabilizer-config",
        type=Path,
        default=_default_path("configs", "stabilizer", "local", "local_mac_fast_reaction.yaml"),
    )
    parser.add_argument(
        "--safety-config",
        type=Path,
        default=_default_path("configs", "safety", "default.yaml"),
    )
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Validate and summarize the scenario without replaying.")
    args = parser.parse_args()

    payload = normalize_replay_scenario(load_replay_scenario(args.scenario))
    validation_errors = validate_replay_scenario(payload)
    if validation_errors:
        print("=== Replay Scenario Validation ===")
        print("FAIL")
        for issue in validation_errors:
            print(f"- {issue}")
        return 1

    if args.dry_run:
        print("=== Replay Scenario Validation ===")
        print("PASS")
        print(f"name={payload.get('name', args.scenario.stem)}")
        print(f"scenario={args.scenario}")
        print(f"step_count={len(payload.get('steps', []))}")
        print(f"step_types={[step.get('type') for step in payload.get('steps', [])]}")
        return 0

    runner = EventReplayRunner(
        arbitration_config=load_arbitration_config(args.arbitration_config),
        stabilizer_config=load_stabilizer_config(args.stabilizer_config),
        safety_config=load_safety_config(args.safety_config),
    )
    report = runner.run_scenario(payload, scenario_path=args.scenario)

    report_payload = {
        "scenario_name": report.scenario_name,
        "scenario_path": report.scenario_path,
        "steps": [step.__dict__ for step in report.steps],
        "detections": report.detections,
        "raw_events": report.raw_events,
        "stable_events": report.stable_events,
        "scenes": report.scenes,
        "decisions": report.decisions,
        "executions": report.executions,
        "pending_queue": report.pending_queue,
        "last_outcome": report.last_outcome,
        "clock_s": report.clock_s,
    }

    print("=== Replay Summary ===")
    print(f"name={report.scenario_name}")
    print(f"scenario={report.scenario_path}")
    print(f"steps={len(report.steps)}")
    print(f"detections={len(report.detections)}")
    print(f"stable_events={len(report.stable_events)}")
    print(f"scenes={len(report.scenes)}")
    print(f"decisions={len(report.decisions)}")
    print(f"executions={len(report.executions)}")
    print(f"pending_queue={report.pending_queue}")
    print(f"last_outcome={report.last_outcome}")
    print(f"executed_behaviors={json.dumps([item['behavior_id'] for item in report.executions], ensure_ascii=False)}")

    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
