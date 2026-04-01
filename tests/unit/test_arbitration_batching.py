from __future__ import annotations

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.common.schemas import DetectionResult, EventPriority
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.decision_queue import DecisionQueue
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime import LiveLoop, LiveLoopDependencies, SourceBundle, SyntheticCameraSource, SyntheticMicrophoneSource


class _Clock:
    def __init__(self, start: float = 100.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance_ms(self, delta_ms: int) -> None:
        self.value += delta_ms / 1000.0


class _FixedRegistry:
    def initialize_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def process_all(self, _frames):
        return [
            (
                "face",
                {
                    "detections": [
                        DetectionResult.synthetic(
                            detector="face",
                            event_type="familiar_face",
                            confidence=0.93,
                            payload={"target_id": "user-1"},
                        )
                    ]
                },
            ),
            (
                "audio",
                {
                    "detections": [
                        DetectionResult.synthetic(
                            detector="audio",
                            event_type="loud_sound",
                            confidence=0.98,
                        )
                    ]
                },
            ),
        ]


def _scene(scene_type: str, trace_id: str, target_id: str | None = None):
    return type(
        "Scene",
        (),
        {
            "scene_type": scene_type,
            "trace_id": trace_id,
            "score_hint": 0.92,
            "target_id": target_id,
        },
    )()


def test_live_loop_batches_same_cycle_before_executing() -> None:
    runtime = ArbitrationRuntime(arbitrator=Arbitrator())
    loop = LiveLoop(
        registry=_FixedRegistry(),
        source_bundle=SourceBundle(
            camera=SyntheticCameraSource(),
            microphone=SyntheticMicrophoneSource(),
        ),
        dependencies=LiveLoopDependencies(
            builder=EventBuilder(),
            stabilizer=EventStabilizer(
                debounce_count=1,
                cooldown_ms=0,
                hysteresis_threshold=0.0,
                dedup_window_ms=0,
            ),
            aggregator=SceneAggregator(),
            arbitrator=Arbitrator(),
            arbitration_runtime=runtime,
            executor=BehaviorExecutor(ResourceManager()),
        ),
        arbitration_batch_window_ms=45,
    )

    results = loop.run_forever(max_iterations=1)
    executions = [execution.behavior_id for execution in results[0].execution_results]
    priorities = [decision.priority for decision in results[0].arbitration_results]

    assert loop.arbitration_batch_window_ms == 45
    # Safety execution gates social in the same cycle: attention is suppressed.
    assert executions[:1] == ["perform_safety_alert"]
    assert priorities[:1] == [EventPriority.P0]


def test_p1_queue_preserves_arrival_order(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("robot_life.event_engine.arbitration_runtime.monotonic", clock)
    monkeypatch.setattr("robot_life.event_engine.decision_queue.now_mono", clock)

    runtime = ArbitrationRuntime(
        arbitrator=Arbitrator(),
        queue=DecisionQueue(),
        batch_window_ms=40,
        p1_queue_limit=3,
    )

    assert runtime.submit(_scene("greeting_scene", "trace-1", "user-1")) is not None
    assert runtime.submit(_scene("gesture_bond_scene", "trace-2", "user-2")) is None
    assert runtime.submit(_scene("greeting_scene", "trace-3", "user-3")) is None
    assert runtime.pending() == 2

    drained_first = runtime.complete_active()
    drained_second = runtime.complete_active()

    assert drained_first is not None
    assert drained_second is not None
    assert drained_first.target_behavior == "perform_gesture_response"
    assert drained_second.trace_id == "trace-3"


def test_p1_duplicates_refresh_existing_queue_item_instead_of_dropping(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("robot_life.event_engine.arbitration_runtime.monotonic", clock)
    monkeypatch.setattr("robot_life.event_engine.decision_queue.now_mono", clock)

    runtime = ArbitrationRuntime(
        arbitrator=Arbitrator(),
        queue=DecisionQueue(),
        batch_window_ms=40,
        p1_queue_limit=2,
    )

    assert runtime.submit(_scene("greeting_scene", "trace-1", "user-1")) is not None
    assert runtime.submit(_scene("greeting_scene", "trace-2", "user-1")) is None
    assert runtime.last_outcome == "debounced"
    assert runtime.pending() == 0

    clock.advance_ms(45)
    assert runtime.submit(_scene("greeting_scene", "trace-3", "user-1")) is None
    assert runtime.last_outcome == "queued"
    assert runtime.pending() == 1

    drained = runtime.complete_active()

    assert drained is not None
    assert drained.trace_id == "trace-3"


def test_p1_same_key_is_debounced_within_batch_window(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("robot_life.event_engine.arbitration_runtime.monotonic", clock)
    monkeypatch.setattr("robot_life.event_engine.decision_queue.now_mono", clock)

    runtime = ArbitrationRuntime(
        arbitrator=Arbitrator(),
        queue=DecisionQueue(),
        batch_window_ms=40,
        p1_queue_limit=2,
    )

    assert runtime.submit(_scene("greeting_scene", "trace-1", "user-1")) is not None
    assert runtime.pending() == 0

    clock.advance_ms(10)
    assert runtime.submit(_scene("greeting_scene", "trace-2", "user-1")) is None
    assert runtime.last_outcome == "debounced"
    assert runtime.pending() == 0

    clock.advance_ms(45)
    assert runtime.submit(_scene("greeting_scene", "trace-3", "user-1")) is None
    assert runtime.last_outcome == "queued"
    assert runtime.pending() == 1


def test_p1_queue_evicts_oldest_item_when_limit_reached(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("robot_life.event_engine.arbitration_runtime.monotonic", clock)
    monkeypatch.setattr("robot_life.event_engine.decision_queue.now_mono", clock)

    runtime = ArbitrationRuntime(
        arbitrator=Arbitrator(),
        queue=DecisionQueue(),
        batch_window_ms=40,
        p1_queue_limit=2,
    )

    assert runtime.submit(_scene("greeting_scene", "trace-1", "user-1")) is not None

    clock.advance_ms(10)
    assert runtime.submit(_scene("greeting_scene", "trace-2", "user-2")) is None
    assert runtime.pending() == 1

    clock.advance_ms(10)
    assert runtime.submit(_scene("greeting_scene", "trace-3", "user-3")) is None
    assert runtime.pending() == 2

    clock.advance_ms(10)
    assert runtime.submit(_scene("greeting_scene", "trace-4", "user-4")) is None
    assert runtime.last_outcome == "queued"
    assert runtime.pending() == 2

    drained_first = runtime.complete_active()
    drained_second = runtime.complete_active()

    assert drained_first is not None
    assert drained_second is not None
    assert drained_first.trace_id == "trace-3"
    assert drained_second.trace_id == "trace-4"


def test_p1_queue_evicts_dominant_target_to_preserve_target_fairness(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("robot_life.event_engine.arbitration_runtime.monotonic", clock)
    monkeypatch.setattr("robot_life.event_engine.decision_queue.now_mono", clock)

    runtime = ArbitrationRuntime(
        arbitrator=Arbitrator(),
        queue=DecisionQueue(),
        batch_window_ms=40,
        p1_queue_limit=2,
    )

    assert runtime.submit(_scene("greeting_scene", "trace-1", "user-0")) is not None

    clock.advance_ms(50)
    assert runtime.submit(_scene("greeting_scene", "trace-2", "user-1")) is None
    assert runtime.pending() == 1

    clock.advance_ms(50)
    assert runtime.submit(_scene("gesture_bond_scene", "trace-3", "user-1")) is None
    assert runtime.pending() == 2

    clock.advance_ms(50)
    assert runtime.submit(_scene("greeting_scene", "trace-4", "user-2")) is None
    assert runtime.pending() == 2

    drained_first = runtime.complete_active()
    drained_second = runtime.complete_active()

    assert drained_first is not None
    assert drained_second is not None
    assert {drained_first.trace_id, drained_second.trace_id} == {"trace-3", "trace-4"}


def test_p2_duplicates_refresh_existing_queue_item(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("robot_life.event_engine.arbitration_runtime.monotonic", clock)
    monkeypatch.setattr("robot_life.event_engine.decision_queue.now_mono", clock)

    runtime = ArbitrationRuntime(
        arbitrator=Arbitrator(),
        queue=DecisionQueue(),
        batch_window_ms=40,
        p2_queue_limit=2,
    )

    assert runtime.submit(_scene("attention_scene", "trace-1", "user-1")) is not None
    assert runtime.submit(_scene("attention_scene", "trace-2", "user-1")) is None
    assert runtime.last_outcome == "debounced"
    assert runtime.pending() == 0

    clock.advance_ms(90)
    assert runtime.submit(_scene("attention_scene", "trace-3", "user-1")) is None
    assert runtime.last_outcome == "queued"
    assert runtime.pending() == 1

    drained = runtime.complete_active()
    assert drained is not None
    assert drained.trace_id == "trace-3"


def test_p2_starvation_promotes_waiting_item_before_newer_queue_entries(monkeypatch) -> None:
    clock = _Clock()
    monkeypatch.setattr("robot_life.event_engine.arbitration_runtime.monotonic", clock)
    monkeypatch.setattr("robot_life.event_engine.decision_queue.now_mono", clock)

    runtime = ArbitrationRuntime(
        arbitrator=Arbitrator(),
        queue=DecisionQueue(),
        batch_window_ms=40,
        p1_queue_limit=2,
        p2_queue_limit=2,
        starvation_after_ms=500,
    )

    assert runtime.submit(_scene("greeting_scene", "trace-1", "user-1")) is not None

    clock.advance_ms(60)
    assert runtime.submit(_scene("attention_scene", "trace-2", "user-2")) is None
    assert runtime.pending() == 1

    clock.advance_ms(600)
    assert runtime.submit(_scene("gesture_bond_scene", "trace-3", "user-3")) is None
    assert runtime.pending() == 2

    drained = runtime.complete_active()

    assert drained is not None
    assert drained.trace_id == "trace-2"


def test_submit_batch_multi_trigger_preserves_priority_order_and_queue_fairness() -> None:
    runtime = ArbitrationRuntime(
        arbitrator=Arbitrator(),
        queue=DecisionQueue(),
        batch_window_ms=40,
        p1_queue_limit=2,
        p2_queue_limit=2,
    )

    outcomes = runtime.submit_batch(
        [
            _scene("attention_scene", "trace-p2", "user-2"),
            _scene("ambient_tracking_scene", "trace-p3", "user-3"),
            _scene("gesture_bond_scene", "trace-p1b", "user-1b"),
            _scene("greeting_scene", "trace-p1a", "user-1a"),
        ]
    )

    assert [(outcome.decision.priority, outcome.outcome) for outcome in outcomes] == [
        (EventPriority.P1, "executed"),
        (EventPriority.P1, "queued"),
        (EventPriority.P2, "queued"),
        (EventPriority.P3, "queued"),
    ]

    drained = [runtime.complete_active(), runtime.complete_active(), runtime.complete_active()]

    assert [decision.target_behavior for decision in drained if decision is not None] == [
        "perform_greeting",
        "perform_attention",
        "perform_tracking",
    ]
