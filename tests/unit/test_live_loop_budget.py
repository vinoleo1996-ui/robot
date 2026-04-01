from __future__ import annotations

from time import monotonic, sleep

from robot_life.app import _build_arbitration_runtime
from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.common.config import ArbitrationConfig
from robot_life.common.schemas import (
    ArbitrationResult,
    DecisionMode,
    DetectionResult,
    EventPriority,
    ExecutionResult,
)
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.perception.base import PipelineBase, PipelineSpec
from robot_life.perception.registry import PipelineRegistry
from robot_life.runtime import (
    CollectedFrames,
    LiveLoop,
    LiveLoopDependencies,
    LiveLoopResult,
    SourceBundle,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
)
from robot_life.runtime.telemetry import InMemoryTelemetrySink
from robot_life.runtime.live_loop import PendingDetection


class _BurstRegistry:
    def __init__(self, bursts: list[list[DetectionResult]]) -> None:
        self._bursts = bursts
        self._calls = 0

    def initialize_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def process_all(self, _frames):
        if self._calls >= len(self._bursts):
            return []

        detections = self._bursts[self._calls]
        self._calls += 1
        return [("face", {"detections": detections})]


class _SlowProcessRegistry:
    def __init__(self, delay_s: float = 0.05) -> None:
        self.delay_s = delay_s
        self.calls = 0

    def initialize_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def process_all(self, _frames):
        sleep(self.delay_s)
        self.calls += 1
        return [
            (
                "motion",
                {
                    "detections": [
                        DetectionResult.synthetic(
                            detector="motion",
                            event_type="motion",
                            confidence=0.8,
                            payload={"target_id": "user-1"},
                        )
                    ]
                },
            )
        ]


class _SlowReadCameraSource(SyntheticCameraSource):
    def __init__(self, *, delay_s: float = 0.05, source_name: str = "camera") -> None:
        super().__init__(source_name=source_name)
        self.delay_s = delay_s

    def read(self):
        sleep(self.delay_s)
        return super().read()


class _CountingPipeline(PipelineBase):
    def __init__(self, spec: PipelineSpec) -> None:
        super().__init__(spec)
        self.calls = 0

    def initialize(self) -> None:
        self._running = True

    def process(self, frame):
        if not self._running:
            return []
        self.calls += 1
        return [self.calls]

    def close(self) -> None:
        self._running = False


class _SlowSceneStub:
    def __init__(self) -> None:
        self.force_sample = True
        self.sample_interval_s = 5.0


class _ResumeAwareExecutor:
    def __init__(self, resume_decision: ArbitrationResult | None) -> None:
        self._resume_decision = resume_decision
        self.execute_calls = 0

    def execute(self, decision: ArbitrationResult) -> ExecutionResult:
        self.execute_calls += 1
        return ExecutionResult(
            execution_id=f"exec-{self.execute_calls}",
            trace_id=decision.trace_id,
            behavior_id=decision.target_behavior,
            status="finished",
            interrupted=False,
            degraded=False,
            started_at=0.0,
            ended_at=0.0,
        )

    def pop_resume_decision(self) -> ArbitrationResult | None:
        decision = self._resume_decision
        self._resume_decision = None
        return decision


def _face_detection(target_id: str, *, confidence: float = 0.93) -> DetectionResult:
    return DetectionResult.synthetic(
        detector="face",
        event_type="familiar_face",
        confidence=confidence,
        payload={"target_id": target_id},
    )


def _event_detection(event_type: str, *, target_id: str | None = None, confidence: float = 0.93) -> DetectionResult:
    payload = {}
    if target_id is not None:
        payload["target_id"] = target_id
    return DetectionResult.synthetic(
        detector="test",
        event_type=event_type,
        confidence=confidence,
        payload=payload,
    )


class _StepClock:
    def __init__(self, start: float = 100.0, step_s: float = 0.005) -> None:
        self.value = start - step_s
        self.step_s = step_s

    def __call__(self) -> float:
        self.value += self.step_s
        return self.value


def _build_loop(
    bursts: list[list[DetectionResult]],
    *,
    max_queued_exec_per_cycle: int = 3,
    queue_drain_exec_time_budget_ms: float = 12.0,
) -> tuple[LiveLoop, InMemoryTelemetrySink, ArbitrationRuntime]:
    telemetry = InMemoryTelemetrySink()
    arbitrator = Arbitrator()
    arbitration_runtime = ArbitrationRuntime(arbitrator=arbitrator)
    loop = LiveLoop(
        registry=_BurstRegistry(bursts),
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
            arbitrator=arbitrator,
            arbitration_runtime=arbitration_runtime,
            executor=BehaviorExecutor(ResourceManager()),
            telemetry=telemetry,
        ),
        telemetry=telemetry,
        max_queued_exec_per_cycle=max_queued_exec_per_cycle,
        queue_drain_exec_time_budget_ms=queue_drain_exec_time_budget_ms,
    )
    return loop, telemetry, arbitration_runtime


def _decision(
    *,
    decision_id: str,
    trace_id: str,
    behavior: str,
    priority: EventPriority,
    mode: DecisionMode = DecisionMode.EXECUTE,
) -> ArbitrationResult:
    return ArbitrationResult(
        decision_id=decision_id,
        trace_id=trace_id,
        target_behavior=behavior,
        priority=priority,
        mode=mode,
        required_resources=["HeadMotion"],
        optional_resources=["FaceExpression"],
        degraded_behavior=None,
        resume_previous=False,
        reason="test",
    )


def test_live_loop_queue_budget_preserves_pending_across_cycles() -> None:
    loop, telemetry, runtime = _build_loop(
        [[
            _face_detection("user-1"),
            _face_detection("user-2"),
            _face_detection("user-3"),
        ]],
        max_queued_exec_per_cycle=3,
    )
    loop._queue_pressure_streak = 2
    loop._last_cycle_latency_ms = 150.0

    first = loop.run_once()
    second = loop.run_once()

    queue_traces = [trace for trace in telemetry.traces if trace.stage == "queue_drain"]
    assert len(queue_traces) >= 2
    assert queue_traces[0].payload["queue_drain_budget"] == 1
    assert queue_traces[0].payload["queue_drain_executed"] == 1
    assert queue_traces[0].payload["queue_drain_deferred"] == 1

    assert len(first.execution_results) == 2
    assert len(second.execution_results) == 1
    assert runtime.pending() == 0

    assert queue_traces[1].payload["queue_drain_budget"] == 3
    assert queue_traces[1].payload["queue_drain_executed"] == 1
    assert queue_traces[1].payload["queue_drain_deferred"] == 0


def test_live_loop_queue_budget_recovers_after_pressure_clears() -> None:
    loop, _, _ = _build_loop([], max_queued_exec_per_cycle=3)

    loop._queue_pressure_streak = 2
    assert loop._resolve_queue_drain_budget(2) == 1

    loop._queue_pressure_streak = 0
    assert loop._resolve_queue_drain_budget(1) == 3


def test_live_loop_load_shed_scales_pipelines_and_restores() -> None:
    registry = PipelineRegistry()
    pipeline = _CountingPipeline(PipelineSpec(name="face", source="camera", sample_rate_hz=10))
    registry.register_pipeline("face", pipeline)
    registry.initialize_all()

    loop = LiveLoop(
        registry=registry,
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
            arbitration_runtime=ArbitrationRuntime(arbitrator=Arbitrator()),
            executor=BehaviorExecutor(ResourceManager()),
            slow_scene=_SlowSceneStub(),
        ),
    )

    loop._queue_pressure_streak = 2
    loop._last_cycle_latency_ms = 150.0

    stressed = loop._apply_load_shed_controls(
        queue_pending=5,
        cycle_latency_ms=150.0,
        slow_scene=loop.dependencies.slow_scene,
    )
    assert stressed["load_shed_mode"] == "strong"
    assert registry.get_runtime_scale("face") < 1.0
    assert loop.dependencies.slow_scene.force_sample is False
    assert loop.dependencies.slow_scene.sample_interval_s > 5.0

    loop._queue_pressure_streak = 0
    loop._last_cycle_latency_ms = 20.0
    recovered = loop._apply_load_shed_controls(
        queue_pending=0,
        cycle_latency_ms=20.0,
        slow_scene=loop.dependencies.slow_scene,
    )
    assert recovered["load_shed_mode"] == "normal"
    assert registry.get_runtime_scale("face") == 1.0
    assert loop.dependencies.slow_scene.force_sample is True
    assert loop.dependencies.slow_scene.sample_interval_s == 5.0


def test_build_arbitration_runtime_uses_queue_config() -> None:
    runtime = _build_arbitration_runtime(
        Arbitrator(),
        ArbitrationConfig(
            queue={
                "max_size": 11,
                "timeout_ms": 2500,
                "batch_window_ms": 60,
                "p1_queue_limit": 4,
                "p2_queue_limit": 5,
                "starvation_after_ms": 900,
            }
        ),
    )

    assert runtime.batch_window_ms == 60
    assert runtime.p1_queue_limit == 4
    assert runtime.p2_queue_limit == 5
    assert runtime.starvation_after_ms == 900
    assert runtime.queue._max_size == 11  # noqa: SLF001
    assert runtime.queue._default_timeout_ms == 2500  # noqa: SLF001


def test_live_loop_queue_drain_respects_exec_time_budget(monkeypatch) -> None:
    loop, _, runtime = _build_loop(
        [],
        max_queued_exec_per_cycle=3,
        queue_drain_exec_time_budget_ms=1.0,
    )
    runtime.queue.enqueue(_decision(decision_id="d1", trace_id="t1", behavior="perform_attention", priority=EventPriority.P2))
    runtime.queue.enqueue(_decision(decision_id="d2", trace_id="t2", behavior="perform_tracking", priority=EventPriority.P3))
    result = LiveLoopResult(collected_frames=CollectedFrames())

    clock_values = iter(
        [
            100.0000,  # queue_drain_started_at
            100.0005,  # first elapsed check (allow one execute)
            100.0010,  # arbitration_started_at
            100.0012,  # arbitration trace ended_at
            100.0014,  # executor_started_at
            100.0016,  # executor trace ended_at
            100.0025,  # second elapsed check (hit time budget)
            100.0030,  # queue_drain_duration
        ]
    )
    monkeypatch.setattr("robot_life.runtime.live_loop.monotonic", lambda: next(clock_values))

    stats = loop._drain_queued_decisions(  # noqa: SLF001
        result,
        arbitration_runtime=runtime,
        executor=BehaviorExecutor(ResourceManager()),
    )

    assert stats["queue_drain_executed"] == 1
    assert stats["queue_drain_hit_exec_time_budget"] is True
    assert stats["queue_pending_after"] == 1


def test_live_loop_enqueues_resume_decision_back_to_arbitration_queue() -> None:
    arbitrator = Arbitrator()
    runtime = ArbitrationRuntime(arbitrator=arbitrator)
    resume_decision = ArbitrationResult(
        decision_id="resume-1",
        trace_id="trace-resume",
        target_behavior="perform_tracking",
        priority=EventPriority.P3,
        mode=DecisionMode.EXECUTE,
        required_resources=[],
        optional_resources=["HeadMotion"],
        degraded_behavior=None,
        resume_previous=False,
        reason="resume_after_soft_interrupt:perform_greeting",
    )
    executor = _ResumeAwareExecutor(resume_decision=resume_decision)
    loop = LiveLoop(
        registry=_BurstRegistry([]),
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
            arbitrator=arbitrator,
            arbitration_runtime=runtime,
            executor=executor,
        ),
    )
    result = LiveLoopResult(collected_frames=CollectedFrames())
    decision = ArbitrationResult(
        decision_id="d-main",
        trace_id="trace-main",
        target_behavior="perform_greeting",
        priority=EventPriority.P1,
        mode=DecisionMode.SOFT_INTERRUPT,
        required_resources=["HeadMotion"],
        optional_resources=["FaceExpression"],
        degraded_behavior=None,
        resume_previous=True,
        reason="test",
    )

    loop._record_executed_decision(  # noqa: SLF001
        result,
        decision,
        scene=None,
        arbitration_runtime=runtime,
        executor=executor,
    )

    assert runtime.pending() == 1
    resumed = runtime.complete_active()
    assert resumed is not None
    assert resumed.trace_id == "trace-resume"


def test_live_loop_fast_path_budget_prioritizes_high_priority_and_defers_remaining(monkeypatch) -> None:
    telemetry = InMemoryTelemetrySink()
    arbitrator = Arbitrator()
    runtime = ArbitrationRuntime(arbitrator=arbitrator)
    loop = LiveLoop(
        registry=_BurstRegistry(
            [[
                _event_detection("motion", target_id="user-motion"),
                _event_detection("loud_sound"),
                _event_detection("familiar_face", target_id="user-face"),
            ]]
        ),
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
            arbitrator=arbitrator,
            arbitration_runtime=runtime,
            executor=BehaviorExecutor(ResourceManager()),
            telemetry=telemetry,
        ),
        telemetry=telemetry,
        fast_path_budget_ms=6.0,
    )
    monkeypatch.setattr("robot_life.runtime.live_loop.monotonic", _StepClock())

    first = loop.run_once()
    second = loop.run_once()

    assert first.detections
    assert first.detections[0].event_type == "loud_sound"
    assert len(loop._pending_detections) <= 1  # noqa: SLF001
    assert any(trace.stage == "fast_path_budget" for trace in telemetry.traces)
    assert second.detections
    assert second.detections[0].event_type in {"familiar_face", "motion"}


def test_live_loop_pending_detection_limit_keeps_high_priority_items() -> None:
    loop, _, _ = _build_loop([])
    loop.fast_path_pending_limit = 2

    dropped = loop._stash_pending_detections(  # noqa: SLF001
        [
            PendingDetection(0, "motion", _event_detection("motion"), EventPriority.P3),
            PendingDetection(1, "audio", _event_detection("loud_sound"), EventPriority.P0),
            PendingDetection(2, "face", _event_detection("familiar_face", target_id="user-1"), EventPriority.P2),
        ]
    )

    assert dropped == 1
    assert [item.priority for item in loop._pending_detections] == [EventPriority.P0, EventPriority.P2]  # noqa: SLF001


def test_live_loop_coalesces_duplicate_scene_candidates_within_same_cycle() -> None:
    loop, _, _ = _build_loop(
        [[
            _event_detection("familiar_face", target_id="user-1"),
            _event_detection("gaze_sustained", target_id="user-1"),
        ]]
    )

    result = loop.run_once()

    assert len(result.scene_candidates) == 1
    assert result.scene_candidates[0].scene_type == "greeting_scene"
    assert len(result.scene_candidates[0].based_on_events) == 2


def test_live_loop_limits_scenes_per_cycle_by_priority() -> None:
    loop, _, _ = _build_loop(
        [[
            _event_detection("motion", target_id="user-1"),
            _event_detection("familiar_face", target_id="user-2"),
            _event_detection("gesture_open_palm", target_id="user-3"),
            _event_detection("loud_sound"),
        ]]
    )
    loop.max_scenes_per_cycle = 2

    result = loop.run_once()

    assert len(result.scene_candidates) == 2
    assert result.scene_candidates[0].scene_type == "safety_alert_scene"
    assert {scene.scene_type for scene in result.scene_candidates} <= {
        "safety_alert_scene",
        "greeting_scene",
        "gesture_bond_scene",
    }


def test_live_loop_async_executor_decouples_execution_from_same_cycle() -> None:
    loop, _, _ = _build_loop(
        [[_event_detection("gesture_open_palm", target_id="user-1")], []]
    )
    loop.async_executor_enabled = True
    loop.start()
    try:
        first = loop.run_once()
        assert len(first.arbitration_results) == 1
        assert first.execution_results == []

        sleep(0.05)
        second = loop.run_once()
        assert len(second.execution_results) >= 1
    finally:
        loop.stop()


def test_live_loop_async_perception_decouples_pipeline_process_from_cycle() -> None:
    loop = LiveLoop(
        registry=_SlowProcessRegistry(delay_s=0.05),
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
            arbitration_runtime=ArbitrationRuntime(arbitrator=Arbitrator()),
            executor=BehaviorExecutor(ResourceManager()),
        ),
        async_perception_enabled=True,
    )
    loop.start()
    try:
        started = monotonic()
        first = loop.run_once()
        first_latency_ms = (monotonic() - started) * 1000.0
        assert first_latency_ms < 40.0
        assert first.pipeline_outputs == []

        sleep(0.08)
        second = loop.run_once()
        assert second.pipeline_outputs != []
    finally:
        loop.stop()


def test_live_loop_drops_stale_async_perception_results() -> None:
    loop = LiveLoop(
        registry=_SlowProcessRegistry(delay_s=0.05),
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
            arbitration_runtime=ArbitrationRuntime(arbitrator=Arbitrator()),
            executor=BehaviorExecutor(ResourceManager()),
        ),
        async_perception_enabled=True,
        async_perception_result_max_age_ms=1.0,
    )
    loop.start()
    try:
        first = loop.run_once()
        assert first.pipeline_outputs == []

        sleep(0.08)
        second = loop.run_once()
        assert second.pipeline_outputs == []
        assert loop._async_perception_stale_dropped >= 1
    finally:
        loop.stop()


def test_live_loop_drops_async_perception_results_with_excessive_frame_lag() -> None:
    loop = LiveLoop(
        registry=_SlowProcessRegistry(delay_s=0.05),
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
            arbitration_runtime=ArbitrationRuntime(arbitrator=Arbitrator()),
            executor=BehaviorExecutor(ResourceManager()),
        ),
        async_perception_enabled=True,
        async_perception_result_max_age_ms=9999.0,
        async_perception_result_max_frame_lag=1,
    )
    loop.start()
    try:
        first = loop.run_once()
        assert first.pipeline_outputs == []

        second = loop.run_once()
        assert second.pipeline_outputs == []

        sleep(0.08)
        third = loop.run_once()
        assert third.pipeline_outputs == []
        assert loop._async_perception_frame_lag_dropped >= 1
    finally:
        loop.stop()


def test_live_loop_async_capture_decouples_source_read_from_cycle() -> None:
    loop = LiveLoop(
        registry=_BurstRegistry([]),
        source_bundle=SourceBundle(
            camera=_SlowReadCameraSource(delay_s=0.05),
            microphone=SyntheticMicrophoneSource(),
        ),
        dependencies=LiveLoopDependencies(),
        async_capture_enabled=True,
    )
    loop.start()
    try:
        started = monotonic()
        first = loop.run_once()
        first_latency_ms = (monotonic() - started) * 1000.0
        assert first_latency_ms < 40.0
        assert first.collected_frames.frames == {}

        sleep(0.08)
        second = loop.run_once()
        assert "camera" in second.collected_frames.frames
    finally:
        loop.stop()


def test_live_loop_multi_trigger_conflict_regression_drains_without_starvation() -> None:
    loop, _, runtime = _build_loop(
        [
            [
                _event_detection("motion", target_id="user-motion"),
                _event_detection("familiar_face", target_id="user-face"),
                _event_detection("gesture_open_palm", target_id="user-gesture"),
                _event_detection("gaze_sustained", target_id="user-gaze"),
            ],
            [],
            [],
        ],
        max_queued_exec_per_cycle=1,
    )

    first = loop.run_once()
    second = loop.run_once()
    third = loop.run_once()

    assert [execution.behavior_id for execution in first.execution_results] == [
        "perform_gesture_response",
        "perform_attention",
    ]
    assert [execution.behavior_id for execution in second.execution_results] == [
        "perform_attention",
    ]
    assert [execution.behavior_id for execution in third.execution_results] == [
        "perform_tracking",
    ]
    assert runtime.pending() == 0


def test_live_loop_routes_safety_and_social_batches_separately() -> None:
    loop, _, _ = _build_loop(
        [[
            _event_detection("loud_sound", target_id="user-a"),
            _event_detection("motion", target_id="user-a"),
            _event_detection("familiar_face", target_id="user-a"),
            _event_detection("gaze_sustained", target_id="user-a"),
        ]],
        max_queued_exec_per_cycle=1,
    )

    first = loop.run_once()

    assert [scene.scene_type for scene in first.scene_batches["safety"]] == ["safety_alert_scene"]
    assert [scene.scene_type for scene in first.scene_batches["social"]] == ["greeting_scene"]
    assert [execution.behavior_id for execution in first.execution_results] == ["perform_safety_alert"]
