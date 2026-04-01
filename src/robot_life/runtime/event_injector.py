from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from time import time
from typing import Any, Mapping

import yaml

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.behavior.safety_guard import BehaviorSafetyGuard
from robot_life.common.config import ArbitrationConfig, SafetyConfig, StabilizerConfig
from robot_life.common.schemas import (
    ArbitrationResult,
    DecisionMode,
    DetectionResult,
    EventPriority,
    SceneCandidate,
    StableEvent,
    new_id,
)
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer


@dataclass
class ReplayClock:
    current_s: float = 100.0

    def now(self) -> float:
        return self.current_s

    def advance_ms(self, delta_ms: int) -> None:
        self.current_s += max(0, int(delta_ms)) / 1000.0


@dataclass
class ReplayStepResult:
    index: int
    step_type: str
    trace_id: str | None
    outcome: str
    detail: dict[str, Any]


@dataclass
class ReplayReport:
    scenario_name: str
    scenario_path: str
    steps: list[ReplayStepResult]
    detections: list[dict[str, Any]]
    raw_events: list[dict[str, Any]]
    stable_events: list[dict[str, Any]]
    scenes: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    executions: list[dict[str, Any]]
    pending_queue: int
    last_outcome: str
    clock_s: float


def load_replay_scenario(path: str | Path) -> dict[str, Any]:
    scenario_path = Path(path)
    content = scenario_path.read_text(encoding="utf-8")
    if scenario_path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(content) or {}
    else:
        payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError(f"Scenario must be a mapping: {scenario_path}")
    return payload


def normalize_replay_scenario(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _normalize_scenario_payload(payload)


def validate_replay_scenario(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    normalized_payload = _normalize_scenario_payload(payload)
    steps = normalized_payload.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["scenario.steps must be a non-empty list"]

    allowed_types = {"detection", "stable_event", "scene", "control"}
    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, Mapping):
            errors.append(f"steps[{index}] must be a mapping")
            continue
        step_type = str(raw_step.get("type", "")).strip()
        if step_type not in allowed_types:
            errors.append(f"steps[{index}] invalid type={step_type!r}")
            continue
        if step_type == "detection":
            for key in ("event_type", "detector"):
                if not str(raw_step.get(key, "")).strip():
                    errors.append(f"steps[{index}] missing {key} for detection step")
        elif step_type == "stable_event":
            if not str(raw_step.get("event_type", "")).strip():
                errors.append(f"steps[{index}] missing event_type for stable_event step")
        elif step_type == "scene":
            if not str(raw_step.get("scene_type", "")).strip():
                errors.append(f"steps[{index}] missing scene_type for scene step")
        elif step_type == "control":
            if str(raw_step.get("action", "")).strip() not in {"advance_ms", "complete_active", "drain_queue"}:
                errors.append(f"steps[{index}] invalid control action={raw_step.get('action')!r}")
    return errors


class EventReplayRunner:
    def __init__(
        self,
        *,
        arbitration_config: ArbitrationConfig,
        stabilizer_config: StabilizerConfig,
        safety_config: SafetyConfig,
        start_clock_s: float = 100.0,
    ) -> None:
        self.clock = ReplayClock(current_s=float(start_clock_s))
        self.builder = EventBuilder()
        self.stabilizer = EventStabilizer.from_config(stabilizer_config)
        self.aggregator = SceneAggregator()
        self.arbitrator = Arbitrator(config=arbitration_config)
        self.runtime = ArbitrationRuntime(
            arbitrator=self.arbitrator,
            batch_window_ms=max(1, int(arbitration_config.queue.get("batch_window_ms", 40))),
            p1_queue_limit=max(1, int(arbitration_config.queue.get("p1_queue_limit", 3))),
            p2_queue_limit=max(1, int(arbitration_config.queue.get("p2_queue_limit", 4))),
            starvation_after_ms=max(0, int(arbitration_config.queue.get("starvation_after_ms", 1_500))),
        )
        self.executor = BehaviorExecutor(
            ResourceManager(),
            safety_guard=BehaviorSafetyGuard.from_config(safety_config),
        )

    def run_scenario(
        self,
        payload: Mapping[str, Any],
        *,
        scenario_path: str | Path,
    ) -> ReplayReport:
        normalized_payload = _normalize_scenario_payload(payload)
        errors = validate_replay_scenario(normalized_payload)
        if errors:
            raise ValueError("; ".join(errors))

        scenario_name = str(
            normalized_payload.get("name")
            or normalized_payload.get("scenario_id")
            or Path(scenario_path).stem
        )
        steps: list[ReplayStepResult] = []
        detections: list[dict[str, Any]] = []
        raw_events: list[dict[str, Any]] = []
        stable_events: list[dict[str, Any]] = []
        scenes: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        executions: list[dict[str, Any]] = []

        with _patched_replay_clock(self.clock):
            for index, raw_step in enumerate(normalized_payload["steps"], start=1):
                step = dict(raw_step)
                delay_ms = max(0, int(step.pop("delay_ms", 0)))
                if delay_ms:
                    self.clock.advance_ms(delay_ms)
                step_type = str(step.get("type"))
                if step_type == "detection":
                    step_result = self._handle_detection_step(index, step, detections, raw_events, stable_events, scenes, decisions, executions)
                elif step_type == "stable_event":
                    step_result = self._handle_stable_event_step(index, step, stable_events, scenes, decisions, executions)
                elif step_type == "scene":
                    step_result = self._handle_scene_step(index, step, scenes, decisions, executions)
                else:
                    step_result = self._handle_control_step(index, step, decisions, executions)
                steps.append(step_result)

        return ReplayReport(
            scenario_name=scenario_name,
            scenario_path=str(Path(scenario_path)),
            steps=steps,
            detections=detections,
            raw_events=raw_events,
            stable_events=stable_events,
            scenes=scenes,
            decisions=decisions,
            executions=executions,
            pending_queue=self.runtime.pending(),
            last_outcome=self.runtime.last_outcome,
            clock_s=self.clock.now(),
        )

    def _handle_detection_step(
        self,
        index: int,
        step: dict[str, Any],
        detections: list[dict[str, Any]],
        raw_events: list[dict[str, Any]],
        stable_events: list[dict[str, Any]],
        scenes: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        executions: list[dict[str, Any]],
    ) -> ReplayStepResult:
        detection = DetectionResult(
            trace_id=str(step.get("trace_id") or new_id()),
            source=str(step.get("source") or "scenario"),
            detector=str(step.get("detector")),
            event_type=str(step.get("event_type")),
            timestamp=float(step.get("timestamp", time())),
            confidence=float(step.get("confidence", 0.9)),
            payload=dict(step.get("payload") or {}),
        )
        detections.append(_serialize(detection))

        priority = _coerce_priority(step.get("priority"))
        raw_event = self.builder.build(
            detection,
            priority=priority,
            ttl_ms=max(1, int(step.get("ttl_ms", 3_000))),
        )
        raw_events.append(_serialize(raw_event))

        stable_event = self.stabilizer.process(raw_event)
        if stable_event is None:
            return ReplayStepResult(
                index=index,
                step_type="detection",
                trace_id=detection.trace_id,
                outcome="filtered_before_stable",
                detail={"event_type": detection.event_type},
            )

        stable_events.append(_serialize(stable_event))
        scene = self.aggregator.aggregate(stable_event)
        if scene is None:
            return ReplayStepResult(
                index=index,
                step_type="detection",
                trace_id=detection.trace_id,
                outcome="no_scene",
                detail={"stable_event_type": stable_event.event_type},
            )

        scenes.append(_serialize(scene))
        decision_outcome = self._submit_scene(scene, decisions=decisions, executions=executions)
        return ReplayStepResult(
            index=index,
            step_type="detection",
            trace_id=detection.trace_id,
            outcome=decision_outcome["outcome"],
            detail={"scene_type": scene.scene_type},
        )

    def _handle_stable_event_step(
        self,
        index: int,
        step: dict[str, Any],
        stable_events: list[dict[str, Any]],
        scenes: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        executions: list[dict[str, Any]],
    ) -> ReplayStepResult:
        priority = _coerce_priority(step.get("priority")) or EventPriority.P2
        trace_id = str(step.get("trace_id") or new_id())
        stable_event = StableEvent(
            stable_event_id=str(step.get("stable_event_id") or new_id()),
            base_event_id=str(step.get("base_event_id") or new_id()),
            trace_id=trace_id,
            event_type=str(step.get("event_type")),
            priority=priority,
            valid_until_monotonic=self.clock.now() + (max(1, int(step.get("valid_for_ms", 3_000))) / 1000.0),
            stabilized_by=list(step.get("stabilized_by") or ["replay"]),
            payload=dict(step.get("payload") or {}),
        )
        stable_events.append(_serialize(stable_event))
        scene = self.aggregator.aggregate(stable_event)
        if scene is None:
            return ReplayStepResult(
                index=index,
                step_type="stable_event",
                trace_id=trace_id,
                outcome="no_scene",
                detail={"event_type": stable_event.event_type},
            )

        scenes.append(_serialize(scene))
        decision_outcome = self._submit_scene(scene, decisions=decisions, executions=executions)
        return ReplayStepResult(
            index=index,
            step_type="stable_event",
            trace_id=trace_id,
            outcome=decision_outcome["outcome"],
            detail={"scene_type": scene.scene_type},
        )

    def _handle_scene_step(
        self,
        index: int,
        step: dict[str, Any],
        scenes: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        executions: list[dict[str, Any]],
    ) -> ReplayStepResult:
        trace_id = str(step.get("trace_id") or new_id())
        scene = SceneCandidate(
            scene_id=str(step.get("scene_id") or new_id()),
            trace_id=trace_id,
            scene_type=str(step.get("scene_type")),
            based_on_events=list(step.get("based_on_events") or []),
            score_hint=float(step.get("score_hint", 0.9)),
            valid_until_monotonic=self.clock.now() + (max(1, int(step.get("valid_for_ms", 3_000))) / 1000.0),
            target_id=step.get("target_id"),
            payload=dict(step.get("payload") or {}),
        )
        scenes.append(_serialize(scene))
        decision_outcome = self._submit_scene(scene, decisions=decisions, executions=executions)
        return ReplayStepResult(
            index=index,
            step_type="scene",
            trace_id=trace_id,
            outcome=decision_outcome["outcome"],
            detail={"scene_type": scene.scene_type},
        )

    def _handle_control_step(
        self,
        index: int,
        step: dict[str, Any],
        decisions: list[dict[str, Any]],
        executions: list[dict[str, Any]],
    ) -> ReplayStepResult:
        action = str(step.get("action"))
        if action == "advance_ms":
            delta_ms = max(0, int(step.get("ms", 0)))
            self.clock.advance_ms(delta_ms)
            return ReplayStepResult(
                index=index,
                step_type="control",
                trace_id=None,
                outcome="advanced",
                detail={"ms": delta_ms},
            )

        if action == "complete_active":
            drained = self.runtime.complete_active()
            if drained is None:
                return ReplayStepResult(index=index, step_type="control", trace_id=None, outcome="idle", detail={})
            decisions.append(_serialize_decision(drained, "dequeued", executed=True))
            execution = self.executor.execute(drained)
            executions.append(_serialize(execution))
            return ReplayStepResult(
                index=index,
                step_type="control",
                trace_id=drained.trace_id,
                outcome="dequeued",
                detail={"behavior_id": execution.behavior_id},
            )

        if action == "drain_queue":
            drained_count = 0
            while True:
                drained = self.runtime.complete_active()
                if drained is None:
                    break
                drained_count += 1
                decisions.append(_serialize_decision(drained, "dequeued", executed=True))
                execution = self.executor.execute(drained)
                executions.append(_serialize(execution))
            return ReplayStepResult(
                index=index,
                step_type="control",
                trace_id=None,
                outcome="drained",
                detail={"count": drained_count},
            )

        raise ValueError(f"Unsupported control action: {action}")

    def _submit_scene(
        self,
        scene: SceneCandidate,
        *,
        decisions: list[dict[str, Any]],
        executions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        decision = self.runtime.submit(scene)
        outcome = self.runtime.last_outcome
        if decision is None:
            current = self.runtime.last_decision
            if current is not None:
                decisions.append(_serialize_decision(current, outcome, executed=False))
            return {"outcome": outcome}

        decisions.append(_serialize_decision(decision, outcome, executed=True))
        execution = self.executor.execute(decision)
        executions.append(_serialize(execution))
        return {"outcome": outcome}


def _coerce_priority(value: Any) -> EventPriority | None:
    if value is None:
        return None
    if isinstance(value, EventPriority):
        return value
    try:
        return EventPriority(str(value))
    except ValueError:
        return None


def _serialize(value: Any) -> Any:
    if isinstance(value, EventPriority):
        return value.value
    if isinstance(value, DecisionMode):
        return value.value
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    return value


def _serialize_decision(decision: ArbitrationResult, outcome: str, *, executed: bool) -> dict[str, Any]:
    payload = _serialize(decision)
    payload["outcome"] = outcome
    payload["executed"] = executed
    return payload


def _normalize_scenario_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    steps = normalized.get("steps")
    if not isinstance(steps, list):
        return normalized
    normalized["steps"] = [_normalize_step(step) for step in steps]
    if not normalized.get("name"):
        normalized["name"] = normalized.get("scenario_id") or normalized.get("title")
    return normalized


def _normalize_step(step: Any) -> dict[str, Any]:
    if not isinstance(step, Mapping):
        return {"type": ""}

    normalized = dict(step)
    step_type = str(normalized.get("type") or normalized.get("kind") or "").strip()
    normalized["type"] = step_type
    normalized.pop("kind", None)

    if step_type == "detection":
        payload = dict(normalized.get("payload") or {})
        if normalized.get("target_id") is not None and "target_id" not in payload:
            payload["target_id"] = normalized.get("target_id")
        if normalized.get("score_hint") is not None and "score_hint" not in payload:
            payload["score_hint"] = normalized.get("score_hint")
        normalized["payload"] = payload
        normalized.setdefault("detector", f"scenario_{normalized.get('event_type', 'detector')}")

    if step_type in {"stable_event", "scene"}:
        payload = dict(normalized.get("payload") or {})
        if normalized.get("target_id") is not None and "target_id" not in payload:
            payload["target_id"] = normalized.get("target_id")
        if normalized.get("score_hint") is not None and "score_hint" not in payload:
            payload["score_hint"] = normalized.get("score_hint")
        normalized["payload"] = payload

    if step_type == "control" and "ms" not in normalized and normalized.get("delay_ms") is not None:
        normalized["ms"] = normalized.get("delay_ms")

    return normalized


@contextmanager
def _patched_replay_clock(clock: ReplayClock):
    import robot_life.event_engine.arbitration_runtime as arbitration_runtime_module
    import robot_life.event_engine.builder as builder_module
    import robot_life.event_engine.decision_queue as decision_queue_module
    import robot_life.event_engine.scene_aggregator as scene_aggregator_module
    import robot_life.event_engine.stabilizer as stabilizer_module

    originals = {
        "builder_now_mono": builder_module.now_mono,
        "stabilizer_now_mono": stabilizer_module.now_mono,
        "scene_aggregator_now_mono": scene_aggregator_module.now_mono,
        "decision_queue_now_mono": decision_queue_module.now_mono,
        "arbitration_runtime_monotonic": arbitration_runtime_module.monotonic,
    }
    builder_module.now_mono = clock.now
    stabilizer_module.now_mono = clock.now
    scene_aggregator_module.now_mono = clock.now
    decision_queue_module.now_mono = clock.now
    arbitration_runtime_module.monotonic = clock.now
    try:
        yield
    finally:
        builder_module.now_mono = originals["builder_now_mono"]
        stabilizer_module.now_mono = originals["stabilizer_now_mono"]
        scene_aggregator_module.now_mono = originals["scene_aggregator_now_mono"]
        decision_queue_module.now_mono = originals["decision_queue_now_mono"]
        arbitration_runtime_module.monotonic = originals["arbitration_runtime_monotonic"]
