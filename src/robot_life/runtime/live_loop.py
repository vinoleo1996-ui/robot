from __future__ import annotations

from dataclasses import replace
import logging
from queue import Empty as QueueEmpty, Full as QueueFull, Queue
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any, Mapping

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.decay_tracker import BehaviorDecayTracker
from robot_life.common.robot_context import RobotContextStore
from robot_life.common.state_machine import InteractionStateMachine
from robot_life.common.contracts import canonical_event_detected, priority_rank
from robot_life.common.schemas import DecisionMode, DetectionResult, EventPriority, SceneCandidate
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.arbitration_runtime import ArbitrationBatchOutcome, ArbitrationRuntime
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.cooldown_manager import CooldownManager
from robot_life.event_engine.entity_tracker import EntityTracker
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.event_engine.temporal_event_layer import TemporalEventLayer
from robot_life.perception.frame_dispatch import build_camera_dispatch, frame_seq_of
from robot_life.common.payload_contracts import ArbitrationTracePayload, DetectionPayloadAccessor
from robot_life.runtime.execution_manager import ExecutionManager
from robot_life.runtime.health_monitor import RuntimeHealthMonitor
from robot_life.runtime.life_state import build_life_state_snapshot
from robot_life.runtime.load_shedder import ResourceLoadShedder
from robot_life.runtime.long_task_coordinator import LongTaskCoordinator
from robot_life.runtime.scene_coordinator import SceneCoordinator
from robot_life.runtime.scene_ops import scene_priority
from robot_life.runtime.sources import FramePacket, SourceBundle
from robot_life.runtime.target_governor import TargetGovernor
from robot_life.runtime.telemetry import NullTelemetrySink, TelemetrySink, emit_stage_trace, telemetry_snapshot


_BEHAVIOR_SCENE_TYPE_MAP = {
    "perform_greeting": "greeting_scene",
    "greeting_visual_only": "greeting_scene",
    "perform_attention": "attention_scene",
    "attention_minimal": "attention_scene",
    "perform_gesture_response": "gesture_bond_scene",
    "gesture_visual_only": "gesture_bond_scene",
    "perform_safety_alert": "safety_alert_scene",
    "perform_tracking": "ambient_tracking_scene",
}


logger = logging.getLogger(__name__)


@dataclass
class CollectedFrames:
    """Snapshot of the latest source samples."""

    packets: dict[str, FramePacket] = field(default_factory=dict)
    frames: dict[str, Any] = field(default_factory=dict)
    collected_at: float = field(default_factory=monotonic)
    frame_seq: int = 0


@dataclass
class LiveLoopDependencies:
    """Optional event-engine components wired into the live loop."""

    builder: EventBuilder | None = None
    stabilizer: EventStabilizer | None = None
    aggregator: SceneAggregator | None = None
    arbitrator: Arbitrator | None = None
    arbitration_runtime: ArbitrationRuntime | None = None
    executor: BehaviorExecutor | None = None
    cooldown_manager: CooldownManager | None = None
    decay_tracker: BehaviorDecayTracker | None = None
    interaction_state_machine: InteractionStateMachine | None = None
    robot_context_store: RobotContextStore | None = None
    entity_tracker: EntityTracker | None = None
    temporal_event_layer: TemporalEventLayer | None = None
    slow_scene: Any | None = None
    telemetry: TelemetrySink | None = None
    event_priorities: Mapping[str, EventPriority] | None = None


@dataclass
class LiveLoopResult:
    """Result bundle produced by one live-loop iteration."""

    collected_frames: CollectedFrames
    detections: list[DetectionResult] = field(default_factory=list)
    raw_events: list[Any] = field(default_factory=list)
    stable_events: list[Any] = field(default_factory=list)
    scene_candidates: list[Any] = field(default_factory=list)
    arbitration_results: list[Any] = field(default_factory=list)
    execution_results: list[Any] = field(default_factory=list)
    slow_scene_results: list[Any] = field(default_factory=list)
    pipeline_outputs: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    scene_batches: dict[str, list[Any]] = field(default_factory=dict)


@dataclass
class PendingDetection:
    sequence_id: int
    pipeline_name: str
    detection: DetectionResult
    priority: EventPriority
    defer_count: int = 0
    was_pending: bool = False


@dataclass
class _AsyncExecutionResult:
    decision: Any
    execution: Any
    resumed_decisions: list[Any]
    started_at: float
    ended_at: float


@dataclass
class _AsyncPerceptionResult:
    collected_frames: CollectedFrames
    pipeline_outputs: list[tuple[str, dict[str, Any]]]
    started_at: float
    ended_at: float


@dataclass
class _AsyncWorkerStatus:
    name: str
    last_heartbeat_at: float | None = None
    consecutive_failures: int = 0
    total_failures: int = 0
    last_error: str | None = None
    last_error_at: float | None = None
    restart_count: int = 0
    last_restart_at: float = 0.0
    reported_failure_total: int = 0
    dead_since_reported: bool = False


def collect_frames(source_bundle: SourceBundle, *, registry: Any | None = None) -> CollectedFrames:
    """Collect the latest packets and payloads from the configured sources."""
    collected_at = monotonic()
    packets = source_bundle.read_packets()
    frames = {source_name: packet.payload for source_name, packet in packets.items()}
    frame_seq = 0
    for packet in packets.values():
        try:
            frame_seq = max(frame_seq, int(getattr(packet, "frame_index", 0)))
        except (TypeError, ValueError):
            continue
    camera_packet = packets.get("camera")
    if camera_packet is not None:
        should_wrap_camera = True
        if registry is not None and hasattr(registry, "scheduled_sources"):
            try:
                should_wrap_camera = "camera" in set(registry.scheduled_sources(frames))
            except Exception:
                should_wrap_camera = True
        if should_wrap_camera:
            frames["camera"] = build_camera_dispatch(
                camera_packet.payload,
                frame_seq=int(getattr(camera_packet, "frame_index", frame_seq) or frame_seq),
                collected_at=collected_at,
            )
    return CollectedFrames(
        packets=packets,
        frames=frames,
        collected_at=collected_at,
        frame_seq=frame_seq,
    )


def infer_event_priority(detection: DetectionResult) -> EventPriority:
    """Best-effort priority inference until detector configs are fully wired in."""
    payload_priority = DetectionPayloadAccessor.from_detection(detection).priority
    if isinstance(payload_priority, EventPriority):
        return payload_priority
    if isinstance(payload_priority, str):
        try:
            return EventPriority[payload_priority]
        except KeyError:
            pass

    event_type = detection.event_type.lower()
    if any(token in event_type for token in ("collision", "emergency", "alarm", "safety", "loud_sound")):
        return EventPriority.P0
    if any(token in event_type for token in ("gesture", "touch", "wake")):
        return EventPriority.P1
    if any(token in event_type for token in ("face", "gaze", "attention")):
        return EventPriority.P2
    if "motion" in event_type:
        return EventPriority.P3
    return EventPriority.P2


def _canonical_priority_key(event_type: str) -> str:
    return canonical_event_detected(event_type)


def resolve_event_priority(
    detection: DetectionResult,
    configured_priorities: Mapping[str, EventPriority] | None = None,
) -> EventPriority:
    if configured_priorities:
        configured = configured_priorities.get(_canonical_priority_key(detection.event_type))
        if configured is not None:
            return configured
    return infer_event_priority(detection)


class LiveLoop:
    """Runnable live-runtime skeleton for camera and microphone sources."""

    def __init__(
        self,
        registry: Any,
        source_bundle: SourceBundle,
        dependencies: LiveLoopDependencies | None = None,
        *,
        telemetry: TelemetrySink | None = None,
        enable_slow_scene: bool = False,
        arbitration_batch_window_ms: int = 40,
        fast_path_budget_ms: float = 35.0,
        fast_path_pending_limit: int = 64,
        max_scenes_per_cycle: int = 4,
        max_queued_exec_per_cycle: int = 3,
        queue_drain_latency_budget_ms: float = 100.0,
        queue_drain_pending_threshold: int = 4,
        queue_drain_exec_time_budget_ms: float = 12.0,
        async_perception_enabled: bool = False,
        async_perception_queue_limit: int = 4,
        async_perception_result_max_age_ms: float = 140.0,
        async_perception_result_max_frame_lag: int = 3,
        async_executor_enabled: bool = False,
        async_executor_queue_limit: int = 64,
        async_capture_enabled: bool = False,
        async_capture_queue_limit: int = 2,
    ) -> None:
        self.registry = registry
        self.source_bundle = source_bundle
        self.dependencies = dependencies or LiveLoopDependencies()
        if self.dependencies.interaction_state_machine is None:
            self.dependencies.interaction_state_machine = InteractionStateMachine()
        if self.dependencies.robot_context_store is None:
            self.dependencies.robot_context_store = RobotContextStore()
        if self.dependencies.entity_tracker is None:
            self.dependencies.entity_tracker = EntityTracker()
        if self.dependencies.temporal_event_layer is None:
            self.dependencies.temporal_event_layer = TemporalEventLayer()
        self.telemetry = telemetry or self.dependencies.telemetry or NullTelemetrySink()
        self.enable_slow_scene = enable_slow_scene
        self.arbitration_batch_window_ms = max(1, int(arbitration_batch_window_ms))
        self.fast_path_budget_ms = max(1.0, float(fast_path_budget_ms))
        self.fast_path_pending_limit = max(1, int(fast_path_pending_limit))
        self.max_scenes_per_cycle = max(1, int(max_scenes_per_cycle))
        self.max_queued_exec_per_cycle = max(1, int(max_queued_exec_per_cycle))
        self.queue_drain_latency_budget_ms = max(10.0, float(queue_drain_latency_budget_ms))
        self.queue_drain_pending_threshold = max(1, int(queue_drain_pending_threshold))
        self.queue_drain_exec_time_budget_ms = max(1.0, float(queue_drain_exec_time_budget_ms))
        self.async_perception_enabled = bool(async_perception_enabled)
        self.async_perception_queue_limit = max(1, int(async_perception_queue_limit))
        self.async_perception_result_max_age_ms = max(0.0, float(async_perception_result_max_age_ms))
        self.async_perception_result_max_frame_lag = max(0, int(async_perception_result_max_frame_lag))
        self.async_executor_enabled = bool(async_executor_enabled)
        self.async_executor_queue_limit = max(1, int(async_executor_queue_limit))
        self.async_capture_enabled = bool(async_capture_enabled)
        self.async_capture_queue_limit = max(1, int(async_capture_queue_limit))
        self._running = False
        self._slow_scene_pending: dict[str, SceneCandidate] = {}
        self._last_slow_scene_submit_at = 0.0
        self._last_slow_scene_submit_at_by_target: dict[str, float] = {}
        self._last_cycle_latency_ms = 0.0
        self._queue_pressure_streak = 0
        self._load_shed_mode = "normal"
        self._load_shed_active = False
        self._load_shed_pipeline_scales: dict[str, float] = {}
        self._slow_scene_base_force_sample: bool | None = None
        self._slow_scene_base_sample_interval_s: float | None = None
        self._load_shed_targets: tuple[str, ...] = ("face", "gaze", "motion")
        self._load_shed_light_scale = 0.5
        self._load_shed_strong_scale = 0.33
        self._load_shed_light_interval_s = 8.0
        self._load_shed_strong_interval_s = 12.0
        self._pending_detections: list[PendingDetection] = []
        self._pending_detection_sequence = 0
        self._perception_thread: Thread | None = None
        self._perception_stop_event = Event()
        self._perception_inbox: Queue[CollectedFrames] | None = None
        self._perception_outbox: Queue[_AsyncPerceptionResult] | None = None
        self._async_perception_stale_dropped = 0
        self._async_perception_frame_lag_dropped = 0
        self._async_perception_last_result_age_ms = 0.0
        self._capture_thread: Thread | None = None
        self._capture_stop_event = Event()
        self._capture_outbox: Queue[CollectedFrames] | None = None
        self._executor_thread: Thread | None = None
        self._executor_stop_event = Event()
        self._executor_inbox: Queue[Any] | None = None
        self._executor_outbox: Queue[_AsyncExecutionResult] | None = None
        self._interaction_snapshot: dict[str, Any] = self.dependencies.interaction_state_machine.snapshot()
        self._decay_snapshot: dict[str, Any] = {}
        self._health_monitor = RuntimeHealthMonitor()
        self._target_governor = TargetGovernor()
        self._long_task_coordinator = LongTaskCoordinator()
        self._resource_load_shedder = ResourceLoadShedder(
            queue_drain_latency_budget_ms=self.queue_drain_latency_budget_ms,
            queue_drain_pending_threshold=self.queue_drain_pending_threshold,
            target_pipelines=self._load_shed_targets,
            light_scale=self._load_shed_light_scale,
            strong_scale=self._load_shed_strong_scale,
            light_interval_s=self._load_shed_light_interval_s,
            strong_interval_s=self._load_shed_strong_interval_s,
        )
        self._scene_coordinator = SceneCoordinator(
            telemetry=self.telemetry,
            cooldown_manager=self.dependencies.cooldown_manager,
            interaction_state_machine=self.dependencies.interaction_state_machine,
            robot_context_store=self.dependencies.robot_context_store,
            arbitration_batch_window_ms=self.arbitration_batch_window_ms,
            max_scenes_per_cycle=self.max_scenes_per_cycle,
            submit_batch_without_runtime=self._submit_batch_without_runtime,
            record_batch_outcome=self._record_batch_outcome,
            target_governor=self._target_governor,
        )
        self._execution_manager = ExecutionManager(
            telemetry=self.telemetry,
            cooldown_manager=self.dependencies.cooldown_manager,
            record_decay_execution=self._record_decay_execution,
            behavior_to_scene_type=self._behavior_to_scene_type,
            async_executor_enabled=self.async_executor_enabled,
        )
        self._pending_priority_boost_every = 2
        self._pending_max_priority_boost = 3
        self._async_worker_restart_min_interval_s = 1.0
        self._async_worker_status_lock = Lock()
        self._async_worker_status = {
            name: _AsyncWorkerStatus(name=name) for name in ("capture", "perception", "executor")
        }

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Open sources and initialize all registered pipelines."""
        self.source_bundle.open_all()
        if hasattr(self.registry, "initialize_all"):
            self.registry.initialize_all()
        self._start_async_capture()
        self._start_async_perception()
        self._start_async_executor()
        self._running = True

    def stop(self) -> None:
        """Stop the loop and close all sources/pipelines."""
        self._running = False
        self._stop_async_perception()
        self._stop_async_capture()
        self._stop_async_executor()
        if hasattr(self.registry, "close_all"):
            self.registry.close_all()
        self.source_bundle.close_all()

    def run_once(self) -> LiveLoopResult:
        """Process one snapshot from all live sources."""
        cycle_started_at = monotonic()
        self._poll_async_worker_health()
        collected, pipeline_outputs, pipeline_started_at, pipeline_ended_at, pipeline_mode = self._collect_and_process_pipelines()
        result = LiveLoopResult(collected_frames=collected, pipeline_outputs=pipeline_outputs)
        emit_stage_trace(
            self.telemetry,
            trace_id=f"loop-{int(pipeline_started_at * 1000)}",
            stage="pipeline_registry",
            payload={
                "output_count": len(pipeline_outputs),
                "frame_sources": list(collected.frames.keys()),
                "mode": pipeline_mode,
            },
            started_at=pipeline_started_at,
            ended_at=pipeline_ended_at,
        )
        self._emit_source_health_trace(cycle_started_at)

        builder = self.dependencies.builder
        stabilizer = self.dependencies.stabilizer
        aggregator = self.dependencies.aggregator
        temporal_event_layer = self.dependencies.temporal_event_layer
        arbitrator = self.dependencies.arbitrator
        arbitration_runtime = self.dependencies.arbitration_runtime
        executor = self.dependencies.executor
        slow_scene = self.dependencies.slow_scene

        if self.enable_slow_scene and slow_scene is not None:
            ready_results = self._drain_ready_slow_scene_results(slow_scene)
            for _base_scene, scene_json in ready_results:
                result.slow_scene_results.append(scene_json)
                emit_stage_trace(
                    self.telemetry,
                    _base_scene.trace_id,
                    "slow_scene",
                    payload={"scene_type": scene_json.scene_type, "confidence": scene_json.confidence},
                    started_at=monotonic(),
                    ended_at=monotonic(),
                )
        self._execution_manager.drain_async_results(
            result,
            arbitration_runtime=arbitration_runtime,
            outbox=self._executor_outbox,
            executor=executor,
        )

        fast_path_started_at = monotonic()
        work_items = self._build_detection_work_items(collected, pipeline_outputs)
        processed_detection_count = 0
        deferred_due_to_budget = 0
        dropped_due_to_pending_limit = 0

        for index, work_item in enumerate(work_items):
            elapsed_fast_path_ms = (monotonic() - fast_path_started_at) * 1000.0
            if elapsed_fast_path_ms >= self.fast_path_budget_ms:
                deferred_due_to_budget = len(work_items) - index
                dropped_due_to_pending_limit = self._stash_pending_detections(work_items[index:])
                break

            detection = work_item.detection
            pipeline_name = work_item.pipeline_name
            priority = work_item.priority
            processed_detection_count += 1

            detection_started_at = monotonic()
            result.detections.append(detection)
            emit_stage_trace(
                self.telemetry,
                detection.trace_id,
                f"{pipeline_name}:detection",
                payload={"event_type": detection.event_type, "confidence": detection.confidence},
                started_at=detection_started_at,
                ended_at=monotonic(),
            )

            if builder is None or stabilizer is None:
                continue

            build_started_at = monotonic()
            raw_event = builder.build(
                detection,
                priority=priority,
            )
            result.raw_events.append(raw_event)
            emit_stage_trace(
                self.telemetry,
                raw_event.trace_id,
                "event_builder",
                payload={"event_type": raw_event.event_type, "priority": raw_event.priority.value},
                started_at=build_started_at,
                ended_at=monotonic(),
            )

            stabilizer_started_at = monotonic()
            stable_event = stabilizer.process(raw_event)
            if stable_event is None:
                emit_stage_trace(
                    self.telemetry,
                    raw_event.trace_id,
                    "event_stabilizer",
                    status="filtered",
                    payload={"event_type": raw_event.event_type},
                    started_at=stabilizer_started_at,
                    ended_at=monotonic(),
                )
                continue

            temporal_events = [stable_event]
            if temporal_event_layer is not None:
                temporal_events = temporal_event_layer.process(stable_event)

            for temporal_event in temporal_events:
                result.stable_events.append(temporal_event)
                stage_name = "temporal_event_layer" if temporal_event is not stable_event else "event_stabilizer"
                emit_stage_trace(
                    self.telemetry,
                    temporal_event.trace_id,
                    stage_name,
                    payload={"event_type": temporal_event.event_type, "stabilized_by": temporal_event.stabilized_by},
                    started_at=stabilizer_started_at,
                    ended_at=monotonic(),
                )

                if aggregator is None:
                    continue

                aggregate_started_at = monotonic()
                scene = aggregator.aggregate(temporal_event)
                if scene is None:
                    emit_stage_trace(
                        self.telemetry,
                        temporal_event.trace_id,
                        "scene_aggregator",
                        status="filtered_by_aggregator",
                        payload={"event_type": temporal_event.event_type},
                        started_at=aggregate_started_at,
                        ended_at=monotonic(),
                    )
                    continue
                result.scene_candidates.append(scene)
                emit_stage_trace(
                    self.telemetry,
                    scene.trace_id,
                    "scene_aggregator",
                    payload={"scene_type": scene.scene_type, "score_hint": scene.score_hint},
                    started_at=aggregate_started_at,
                    ended_at=monotonic(),
                )

        emit_stage_trace(
            self.telemetry,
            trace_id=f"loop-{int(cycle_started_at * 1000)}",
            stage="fast_path_budget",
            payload={
                "fast_path_budget_ms": round(self.fast_path_budget_ms, 3),
                "fast_path_processed_detections": processed_detection_count,
                "fast_path_deferred_detections": deferred_due_to_budget,
                "fast_path_pending_backlog": len(self._pending_detections),
                "fast_path_dropped_due_to_pending_limit": dropped_due_to_pending_limit,
            },
            started_at=fast_path_started_at,
            ended_at=monotonic(),
        )

        if result.scene_candidates and (arbitrator is not None or arbitration_runtime is not None):
            self._scene_coordinator.process_batch(
                result,
                collected=collected,
                interaction_snapshot=self._interaction_snapshot,
                arbitrator=arbitrator,
                arbitration_runtime=arbitration_runtime,
                executor=executor,
                slow_scene=slow_scene,
            )

        queue_drain_stats = self._drain_queued_decisions(
            result,
            arbitration_runtime=arbitration_runtime,
            executor=executor,
        )
        self._execution_manager.tick_active(
            result,
            arbitration_runtime=arbitration_runtime,
            executor=executor,
        )
        cycle_latency_ms = (monotonic() - cycle_started_at) * 1000.0
        self._update_queue_pressure_state(
            cycle_latency_ms,
            queue_pending=int(queue_drain_stats["queue_pending_after"]),
        )
        load_shed_stats = self._apply_load_shed_controls(
            queue_pending=int(queue_drain_stats["queue_pending_after"]),
            cycle_latency_ms=cycle_latency_ms,
            slow_scene=slow_scene,
        )
        queue_drain_stats.update(load_shed_stats)
        emit_stage_trace(
            self.telemetry,
            trace_id=f"loop-{int(cycle_started_at * 1000)}",
            stage="queue_drain",
            payload=queue_drain_stats,
            started_at=cycle_started_at,
            ended_at=monotonic(),
        )
        emit_stage_trace(
            self.telemetry,
            trace_id=f"loop-{int(cycle_started_at * 1000)}",
            stage="load_shed",
            payload=load_shed_stats,
            started_at=cycle_started_at,
            ended_at=monotonic(),
        )
        self._update_life_state(result)
        self._update_robot_context(result)
        emit_stage_trace(
            self.telemetry,
            trace_id=f"loop-health-summary-{int(cycle_started_at * 1000)}",
            stage="runtime_health",
            payload=self._health_monitor.snapshot(),
            started_at=cycle_started_at,
            ended_at=monotonic(),
        )

        return result

    def _mark_async_worker_heartbeat(self, worker_name: str) -> None:
        with self._async_worker_status_lock:
            status = self._async_worker_status[worker_name]
            status.last_heartbeat_at = monotonic()
            status.consecutive_failures = 0
            status.last_error = None
            status.dead_since_reported = False

    def _mark_async_worker_failure(self, worker_name: str, exc: Exception) -> None:
        with self._async_worker_status_lock:
            status = self._async_worker_status[worker_name]
            status.total_failures += 1
            status.consecutive_failures += 1
            status.last_error = f"{type(exc).__name__}: {exc}"
            status.last_error_at = monotonic()

    def _snapshot_async_worker_status(self) -> dict[str, dict[str, Any]]:
        with self._async_worker_status_lock:
            return {
                name: {
                    "last_heartbeat_at": status.last_heartbeat_at,
                    "consecutive_failures": status.consecutive_failures,
                    "total_failures": status.total_failures,
                    "last_error": status.last_error,
                    "last_error_at": status.last_error_at,
                    "restart_count": status.restart_count,
                    "last_restart_at": status.last_restart_at,
                }
                for name, status in self._async_worker_status.items()
            }

    def _restart_async_worker(self, worker_name: str) -> None:
        if worker_name == "capture":
            self._stop_async_capture()
            self._start_async_capture()
        elif worker_name == "perception":
            self._stop_async_perception()
            self._start_async_perception()
        elif worker_name == "executor":
            self._stop_async_executor()
            self._start_async_executor()

    def _poll_async_worker_health(self) -> None:
        worker_configs = {
            "capture": (self.async_capture_enabled, self._capture_thread, self._capture_stop_event, "async_capture"),
            "perception": (self.async_perception_enabled, self._perception_thread, self._perception_stop_event, "async_perception"),
            "executor": (self.async_executor_enabled, self._executor_thread, self._executor_stop_event, "async_executor"),
        }
        now = monotonic()
        for worker_name, (enabled, thread, stop_event, stage_name) in worker_configs.items():
            if not enabled:
                continue
            with self._async_worker_status_lock:
                status = self._async_worker_status[worker_name]
                failure_delta = status.total_failures - status.reported_failure_total
                if failure_delta > 0:
                    status.reported_failure_total = status.total_failures
                    worker_payload = {
                        "worker": worker_name,
                        "consecutive_failures": status.consecutive_failures,
                        "total_failures": status.total_failures,
                        "last_error": status.last_error,
                        "last_error_at": status.last_error_at,
                        "restart_count": status.restart_count,
                    }
                else:
                    worker_payload = None
                dead = thread is not None and not thread.is_alive() and not stop_event.is_set()
                can_restart = dead and (now - status.last_restart_at) >= self._async_worker_restart_min_interval_s
            if failure_delta > 0:
                for _ in range(failure_delta):
                    self._health_monitor.record_stage_failure(stage_name)
                emit_stage_trace(
                    self.telemetry,
                    trace_id=f"{worker_name}-failure-{int(now * 1000)}",
                    stage="async_worker",
                    status="failed",
                    payload=worker_payload,
                    started_at=now,
                    ended_at=monotonic(),
                )
            elif thread is not None and thread.is_alive():
                self._health_monitor.record_stage_success(stage_name)

            if not dead:
                with self._async_worker_status_lock:
                    self._async_worker_status[worker_name].dead_since_reported = False
                continue

            dead_payload = self._snapshot_async_worker_status().get(worker_name, {})
            first_dead_report = False
            with self._async_worker_status_lock:
                status = self._async_worker_status[worker_name]
                if not status.dead_since_reported:
                    status.dead_since_reported = True
                    first_dead_report = True
            if first_dead_report:
                self._health_monitor.record_stage_failure(stage_name)
                emit_stage_trace(
                    self.telemetry,
                    trace_id=f"{worker_name}-dead-{int(now * 1000)}",
                    stage="async_worker",
                    status="dead",
                    payload={"worker": worker_name, **dead_payload},
                    started_at=now,
                    ended_at=monotonic(),
                )
            if can_restart:
                self._restart_async_worker(worker_name)
                restart_at = monotonic()
                with self._async_worker_status_lock:
                    status = self._async_worker_status[worker_name]
                    status.restart_count += 1
                    status.last_restart_at = restart_at
                    status.dead_since_reported = False
                emit_stage_trace(
                    self.telemetry,
                    trace_id=f"{worker_name}-restart-{int(restart_at * 1000)}",
                    stage="async_worker",
                    status="restarting",
                    payload={"worker": worker_name},
                    started_at=restart_at,
                    ended_at=monotonic(),
                )

    def _pending_priority_boost(self, item: PendingDetection) -> int:
        return min(self._pending_max_priority_boost, item.defer_count // self._pending_priority_boost_every)

    def _pending_processing_sort_key(self, item: PendingDetection) -> tuple[int, int]:
        return (max(0, priority_rank(item.priority) - self._pending_priority_boost(item)), item.sequence_id)

    def _pending_backlog_sort_key(self, item: PendingDetection) -> tuple[int, int, int, int]:
        return (0 if item.was_pending else 1, max(0, priority_rank(item.priority) - self._pending_priority_boost(item)), -item.defer_count, item.sequence_id)

    def _collect_and_process_pipelines(
        self,
    ) -> tuple[CollectedFrames, list[tuple[str, dict[str, Any]]], float, float, str]:
        collected, capture_mode = self._collect_frames_for_cycle()
        if not collected.frames and capture_mode != "capture_sync":
            now = monotonic()
            return collected, [], now, now, f"{capture_mode}:no_frame"
        if not self.async_perception_enabled or self._perception_inbox is None or self._perception_outbox is None:
            started_at = monotonic()
            pipeline_outputs = self.registry.process_all(collected.frames)
            ended_at = monotonic()
            return collected, pipeline_outputs, started_at, ended_at, f"{capture_mode}:sync"

        self._submit_async_perception(collected)
        latest = self._drain_async_perception_results()
        if latest is None:
            now = monotonic()
            return collected, [], now, now, f"{capture_mode}:async_pending"
        result_age_ms = max(0.0, (monotonic() - latest.collected_frames.collected_at) * 1000.0)
        self._async_perception_last_result_age_ms = result_age_ms
        if (
            self.async_perception_result_max_age_ms > 0.0
            and result_age_ms > self.async_perception_result_max_age_ms
        ):
            self._async_perception_stale_dropped += 1
            logger.warning(
                "drop stale async perception result age=%.2fms threshold=%.2fms dropped=%s",
                result_age_ms,
                self.async_perception_result_max_age_ms,
                self._async_perception_stale_dropped,
            )
            now = monotonic()
            return collected, [], now, now, f"{capture_mode}:async_stale_drop"
        if (
            self.async_perception_result_max_frame_lag > 0
            and not self.async_capture_enabled
            and collected.frame_seq > 0
            and latest.collected_frames.frame_seq > 0
        ):
            frame_lag = max(0, int(collected.frame_seq - latest.collected_frames.frame_seq))
            if frame_lag > self.async_perception_result_max_frame_lag:
                self._async_perception_frame_lag_dropped += 1
                logger.warning(
                    "drop async perception result due to frame lag=%s threshold=%s dropped=%s",
                    frame_lag,
                    self.async_perception_result_max_frame_lag,
                    self._async_perception_frame_lag_dropped,
                )
                now = monotonic()
                return collected, [], now, now, f"{capture_mode}:async_frame_lag_drop"
        return (
            latest.collected_frames,
            latest.pipeline_outputs,
            latest.started_at,
            latest.ended_at,
            f"{capture_mode}:async_ready",
        )

    def _collect_frames_for_cycle(self) -> tuple[CollectedFrames, str]:
        if not self.async_capture_enabled or self._capture_outbox is None:
            return collect_frames(self.source_bundle, registry=self.registry), "capture_sync"
        latest = self._drain_async_capture_results()
        if latest is not None:
            return latest, "capture_async_ready"
        return CollectedFrames(collected_at=monotonic()), "capture_async_pending"

    def _start_async_capture(self) -> None:
        if not self.async_capture_enabled:
            return
        if self._capture_thread is not None and self._capture_thread.is_alive():
            return
        self._capture_stop_event.clear()
        self._capture_outbox = Queue(maxsize=self.async_capture_queue_limit)
        self._capture_thread = Thread(
            target=self._async_capture_worker,
            name="source-capture-async",
            daemon=True,
        )
        self._capture_thread.start()

    def _stop_async_capture(self) -> None:
        self._capture_stop_event.set()
        thread = self._capture_thread
        self._capture_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._capture_outbox = None

    def _async_capture_worker(self) -> None:
        outbox = self._capture_outbox
        if outbox is None:
            return
        while not self._capture_stop_event.is_set():
            try:
                collected = collect_frames(self.source_bundle, registry=self.registry)
            except Exception as exc:  # pragma: no cover - runtime guard
                self._mark_async_worker_failure("capture", exc)
                logger.exception("async capture worker failed: %s", exc)
                continue

            self._mark_async_worker_heartbeat("capture")
            if not collected.frames:
                continue
            try:
                outbox.put_nowait(collected)
            except QueueFull:
                try:
                    outbox.get_nowait()
                except QueueEmpty:
                    pass
                try:
                    outbox.put_nowait(collected)
                except QueueFull:
                    logger.warning("async capture outbox full, dropping newest frame snapshot")

    def _drain_async_capture_results(self) -> CollectedFrames | None:
        outbox = self._capture_outbox
        if outbox is None:
            return None
        latest: CollectedFrames | None = None
        while True:
            try:
                latest = outbox.get_nowait()
                outbox.task_done()
            except QueueEmpty:
                break
        return latest

    def _start_async_perception(self) -> None:
        if not self.async_perception_enabled:
            return
        if self._perception_thread is not None and self._perception_thread.is_alive():
            return
        self._perception_stop_event.clear()
        self._perception_inbox = Queue(maxsize=self.async_perception_queue_limit)
        self._perception_outbox = Queue(maxsize=self.async_perception_queue_limit * 2)
        self._perception_thread = Thread(
            target=self._async_perception_worker,
            name="pipeline-registry-async",
            daemon=True,
        )
        self._perception_thread.start()

    def _stop_async_perception(self) -> None:
        self._perception_stop_event.set()
        thread = self._perception_thread
        self._perception_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._perception_inbox = None
        self._perception_outbox = None

    def _async_perception_worker(self) -> None:
        inbox = self._perception_inbox
        outbox = self._perception_outbox
        if inbox is None or outbox is None:
            return
        while not self._perception_stop_event.is_set():
            try:
                collected = inbox.get(timeout=0.1)
            except QueueEmpty:
                continue
            started_at = monotonic()
            try:
                pipeline_outputs = self.registry.process_all(collected.frames)
            except Exception as exc:  # pragma: no cover - runtime guard
                self._mark_async_worker_failure("perception", exc)
                logger.exception("async perception worker failed: %s", exc)
                pipeline_outputs = []
            else:
                self._mark_async_worker_heartbeat("perception")
            ended_at = monotonic()
            payload = _AsyncPerceptionResult(
                collected_frames=collected,
                pipeline_outputs=pipeline_outputs,
                started_at=started_at,
                ended_at=ended_at,
            )
            try:
                outbox.put_nowait(payload)
            except QueueFull:
                try:
                    outbox.get_nowait()
                except QueueEmpty:
                    pass
                try:
                    outbox.put_nowait(payload)
                except QueueFull:
                    logger.warning("async perception outbox full, dropping newest result")
            finally:
                inbox.task_done()

    def _submit_async_perception(self, collected: CollectedFrames) -> None:
        inbox = self._perception_inbox
        if inbox is None:
            return
        try:
            inbox.put_nowait(collected)
            return
        except QueueFull:
            pass
        try:
            _ = inbox.get_nowait()
            inbox.task_done()
        except QueueEmpty:
            return
        try:
            inbox.put_nowait(collected)
        except QueueFull:
            logger.warning("async perception inbox full, drop collected frame")

    def _drain_async_perception_results(self) -> _AsyncPerceptionResult | None:
        outbox = self._perception_outbox
        if outbox is None:
            return None
        latest: _AsyncPerceptionResult | None = None
        while True:
            try:
                latest = outbox.get_nowait()
                outbox.task_done()
            except QueueEmpty:
                break
        return latest

    def _build_detection_work_items(
        self,
        collected: CollectedFrames,
        pipeline_outputs: list[tuple[str, dict[str, Any]]],
    ) -> list[PendingDetection]:
        work_items = list(self._pending_detections)
        self._pending_detections = []
        camera_frame = collected.frames.get("camera")
        camera_shape = getattr(camera_frame, "shape", None)
        frame_shape: tuple[int, int] | None = None
        if isinstance(camera_shape, tuple) and len(camera_shape) >= 2:
            try:
                frame_shape = (int(camera_shape[0]), int(camera_shape[1]))
            except (TypeError, ValueError):
                frame_shape = None

        raw_items: list[tuple[str, DetectionResult]] = []
        for pipeline_name, payload in pipeline_outputs:
            detections = payload.get("detections", []) or []
            for detection in detections:
                if not isinstance(detection, DetectionResult):
                    continue
                accessor = DetectionPayloadAccessor.from_detection(detection)
                camera_frame = collected.frames.get("camera")
                camera_seq = frame_seq_of(camera_frame)
                detection.payload = accessor.apply_ingestion_defaults(
                    frame_seq=collected.frame_seq,
                    collected_at=collected.collected_at,
                    ingested_at=monotonic(),
                    source_latency_ms=(monotonic() - collected.collected_at) * 1000.0,
                    camera_frame_seq=camera_seq,
                    frame_shape=frame_shape,
                )
                raw_items.append((pipeline_name, detection))

        entity_tracker = self.dependencies.entity_tracker
        if entity_tracker is not None and raw_items:
            raw_items = entity_tracker.associate_batch(raw_items, frame_shape=frame_shape)

        for pipeline_name, detection in raw_items:
            work_items.append(
                PendingDetection(
                    sequence_id=self._next_pending_detection_sequence(),
                    pipeline_name=pipeline_name,
                    detection=detection,
                    priority=resolve_event_priority(
                        detection,
                        self.dependencies.event_priorities,
                    ),
                    was_pending=False,
                )
            )

        work_items.sort(key=self._pending_processing_sort_key)
        return work_items

    def _stash_pending_detections(self, work_items: list[PendingDetection]) -> int:
        if not work_items:
            self._pending_detections = []
            return 0

        for item in work_items:
            item.defer_count += 1
        kept = sorted(work_items, key=self._pending_backlog_sort_key)[: self.fast_path_pending_limit]
        for item in kept:
            item.was_pending = True
        kept.sort(key=lambda item: item.sequence_id)
        self._pending_detections = kept
        return max(0, len(work_items) - len(kept))

    def _next_pending_detection_sequence(self) -> int:
        sequence_id = self._pending_detection_sequence
        self._pending_detection_sequence += 1
        return sequence_id

    def run_forever(
        self,
        *,
        poll_interval_s: float = 1.0 / 30.0,
        stop_event: Event | None = None,
        max_iterations: int | None = None,
    ) -> list[LiveLoopResult]:
        """Run the loop until stopped or iteration budget is exhausted."""
        if not self._running:
            self.start()

        results: list[LiveLoopResult] = []
        iteration = 0

        try:
            while self._running:
                if stop_event is not None and stop_event.is_set():
                    break
                if max_iterations is not None and iteration >= max_iterations:
                    break

                started_at = monotonic()
                try:
                    results.append(self.run_once())
                    self._health_monitor.record_stage_success("live_loop")
                except Exception as exc:  # pragma: no cover - runtime safety net
                    self._health_monitor.record_stage_failure("live_loop")
                    logger.exception("live loop iteration failed: %s", exc)
                finally:
                    iteration += 1
                    elapsed = monotonic() - started_at
                    sleep(max(0.0, poll_interval_s - elapsed))
        finally:
            self.stop()

        return results

    def _submit_or_query_slow_scene(
        self,
        slow_scene: Any,
        scene: Any,
        collected: CollectedFrames,
        *,
        decision_mode: Any | None = None,
        arbitration_outcome: str | None = None,
    ) -> Any | None:
        return self._long_task_coordinator.submit_or_query(
            slow_scene,
            scene,
            collected,
            decision_mode=decision_mode,
            arbitration_outcome=arbitration_outcome,
        )

    def _drain_ready_slow_scene_results(self, slow_scene: Any) -> list[tuple[SceneCandidate, Any]]:
        before = self._long_task_coordinator.stale_dropped
        ready = self._long_task_coordinator.drain_ready_results(slow_scene)
        stale_delta = self._long_task_coordinator.stale_dropped - before
        if stale_delta > 0:
            self._health_monitor.record_long_task_stale_drop(stale_delta)
            emit_stage_trace(
                self.telemetry,
                trace_id=f"long-task-stale-{int(monotonic() * 1000)}",
                stage="long_task_stale",
                status="dropped",
                payload={"count": stale_delta, "snapshot": self._long_task_coordinator.snapshot()},
                started_at=monotonic(),
                ended_at=monotonic(),
            )
        else:
            self._health_monitor.record_long_task_healthy()
        return ready

    def _drain_queued_decisions(
        self,
        result: LiveLoopResult,
        *,
        arbitration_runtime: ArbitrationRuntime | None,
        executor: BehaviorExecutor | None,
    ) -> dict[str, Any]:
        if arbitration_runtime is None:
            return {
                "queue_drain_budget": 0,
                "queue_drain_executed": 0,
                "queue_drain_deferred": 0,
                "queue_pending_before": 0,
                "queue_pending_after": 0,
                "queue_pressure_streak": self._queue_pressure_streak,
                "last_cycle_latency_ms": round(self._last_cycle_latency_ms, 3),
            }

        pending_before = arbitration_runtime.pending()
        if executor is None:
            return {
                "queue_drain_budget": 0,
                "queue_drain_executed": 0,
                "queue_drain_deferred": pending_before,
                "queue_pending_before": pending_before,
                "queue_pending_after": pending_before,
                "queue_pressure_streak": self._queue_pressure_streak,
                "last_cycle_latency_ms": round(self._last_cycle_latency_ms, 3),
            }

        budget = self._resolve_queue_drain_budget(pending_before)
        executed = 0
        queue_drain_started_at = monotonic()
        hit_exec_time_budget = False

        while executed < budget:
            elapsed_ms = (monotonic() - queue_drain_started_at) * 1000.0
            if elapsed_ms >= self.queue_drain_exec_time_budget_ms:
                hit_exec_time_budget = True
                break
            queued = arbitration_runtime.complete_active()
            if queued is None:
                break
            self._record_executed_decision(
                result,
                queued,
                scene=None,
                arbitration_runtime=arbitration_runtime,
                executor=executor,
            )
            executed += 1

        pending_after = arbitration_runtime.pending()
        deferred = pending_after
        return {
            "queue_drain_budget": budget,
            "queue_drain_executed": executed,
            "queue_drain_deferred": deferred,
            "queue_pending_before": pending_before,
            "queue_pending_after": pending_after,
            "queue_pressure_streak": self._queue_pressure_streak,
            "last_cycle_latency_ms": round(self._last_cycle_latency_ms, 3),
            "queue_drain_duration_ms": round((monotonic() - queue_drain_started_at) * 1000.0, 3),
            "queue_drain_exec_time_budget_ms": round(self.queue_drain_exec_time_budget_ms, 3),
            "queue_drain_hit_exec_time_budget": hit_exec_time_budget,
        }

    def _resolve_queue_drain_budget(self, queue_pending: int) -> int:
        if queue_pending <= 0:
            return 0

        budget = self.max_queued_exec_per_cycle
        if self._queue_pressure_streak >= 2 or queue_pending >= self.queue_drain_pending_threshold * 2:
            budget -= 2
        elif self._queue_pressure_streak >= 1 or queue_pending >= self.queue_drain_pending_threshold:
            budget -= 1
        return max(1, min(self.max_queued_exec_per_cycle, budget))

    def _update_queue_pressure_state(self, cycle_latency_ms: float, *, queue_pending: int) -> None:
        self._last_cycle_latency_ms = float(cycle_latency_ms)
        pressure = (
            cycle_latency_ms > self.queue_drain_latency_budget_ms
            or queue_pending >= self.queue_drain_pending_threshold
        )
        if pressure:
            self._queue_pressure_streak += 1
        else:
            self._queue_pressure_streak = 0

    def _apply_load_shed_controls(
        self,
        *,
        queue_pending: int,
        cycle_latency_ms: float,
        slow_scene: Any | None,
    ) -> dict[str, Any]:
        payload = self._resource_load_shedder.apply(
            queue_pending=queue_pending,
            cycle_latency_ms=cycle_latency_ms,
            queue_pressure_streak=self._queue_pressure_streak,
            registry=self.registry,
            task_service=slow_scene,
            interaction_intent=self._interaction_snapshot.get("intent"),
        )
        self._load_shed_mode = self._resource_load_shedder.mode
        self._load_shed_active = self._resource_load_shedder.active
        self._load_shed_pipeline_scales = dict(self._resource_load_shedder.pipeline_scales)
        return payload

    def _resolve_load_shed_mode(
        self,
        *,
        queue_pending: int,
        cycle_latency_ms: float,
    ) -> tuple[str, list[str]]:
        reasons: list[str] = []
        latency_pressure = cycle_latency_ms > self.queue_drain_latency_budget_ms
        queue_pressure = queue_pending >= self.queue_drain_pending_threshold
        streak_pressure = self._queue_pressure_streak >= 1

        if latency_pressure:
            reasons.append("latency")
        if queue_pressure:
            reasons.append("queue_depth")
        if streak_pressure:
            reasons.append("streak")

        if (
            self._queue_pressure_streak >= 2
            or queue_pending >= self.queue_drain_pending_threshold * 2
            or cycle_latency_ms >= self.queue_drain_latency_budget_ms * 1.5
        ):
            return "strong", reasons or ["pressure"]
        if latency_pressure or queue_pressure or streak_pressure:
            return "light", reasons or ["pressure"]
        return "normal", []

    def _load_shed_pipeline_scales_for_mode(self, mode: str) -> dict[str, float]:
        if mode == "strong":
            scale = self._load_shed_strong_scale
        elif mode == "light":
            scale = self._load_shed_light_scale
        else:
            scale = 1.0
        return {pipeline_name: scale for pipeline_name in self._load_shed_targets}

    def _apply_pipeline_runtime_scales(self, scales: dict[str, float]) -> None:
        if hasattr(self.registry, "set_runtime_scales"):
            self.registry.set_runtime_scales(scales)
            return
        if hasattr(self.registry, "set_runtime_scale"):
            for pipeline_name, scale in scales.items():
                self.registry.set_runtime_scale(pipeline_name, scale)

    def _apply_slow_scene_load_shed(self, slow_scene: Any | None, mode: str) -> dict[str, Any]:
        if slow_scene is None:
            return {
                "slow_scene_force_sample": None,
                "slow_scene_sample_interval_s": None,
            }

        if self._slow_scene_base_force_sample is None and hasattr(slow_scene, "force_sample"):
            self._slow_scene_base_force_sample = bool(getattr(slow_scene, "force_sample", False))
        if self._slow_scene_base_sample_interval_s is None and hasattr(slow_scene, "sample_interval_s"):
            self._slow_scene_base_sample_interval_s = float(getattr(slow_scene, "sample_interval_s", 0.0))

        base_force_sample = self._slow_scene_base_force_sample
        base_interval_s = self._slow_scene_base_sample_interval_s

        if mode == "normal":
            if base_force_sample is not None and hasattr(slow_scene, "force_sample"):
                slow_scene.force_sample = base_force_sample
            if base_interval_s is not None and hasattr(slow_scene, "sample_interval_s"):
                slow_scene.sample_interval_s = base_interval_s
        else:
            if hasattr(slow_scene, "force_sample"):
                slow_scene.force_sample = False
            if hasattr(slow_scene, "sample_interval_s"):
                conservative_interval_s = self._load_shed_light_interval_s
                if mode == "strong":
                    conservative_interval_s = self._load_shed_strong_interval_s
                if base_interval_s is not None:
                    conservative_interval_s = max(base_interval_s * (2.0 if mode == "strong" else 1.5), conservative_interval_s)
                slow_scene.sample_interval_s = conservative_interval_s

        return {
            "slow_scene_force_sample": getattr(slow_scene, "force_sample", None),
            "slow_scene_sample_interval_s": getattr(slow_scene, "sample_interval_s", None),
        }

    def _submit_batch_without_runtime(
        self,
        scenes: list[SceneCandidate],
        arbitrator: Arbitrator | None,
    ) -> list[ArbitrationBatchOutcome]:
        if arbitrator is None:
            return []

        current_priority: EventPriority | None = None
        ordered_scenes = sorted(
            enumerate(scenes),
            key=lambda item: (priority_rank(scene_priority(item[1], arbitrator)), item[0]),
        )

        outcomes: list[ArbitrationBatchOutcome] = []
        for _index, scene in ordered_scenes:
            decision = arbitrator.decide(scene, current_priority=current_priority)
            executed = decision.mode != DecisionMode.DROP
            outcomes.append(
                ArbitrationBatchOutcome(
                    scene=scene,
                    decision=decision,
                    outcome="executed" if executed else "dropped",
                    executed=executed,
                )
            )
            if executed:
                current_priority = decision.priority
        return outcomes

    def _record_batch_outcome(
        self,
        result: LiveLoopResult,
        *,
        outcome: ArbitrationBatchOutcome,
        collected: CollectedFrames,
        arbitration_runtime: ArbitrationRuntime | None,
        executor: BehaviorExecutor | None,
        slow_scene: Any | None,
    ) -> bool:
        arbitration_started_at = monotonic()
        if not outcome.executed:
            self._emit_arbitration_trace(
                outcome.decision,
                status=outcome.outcome,
                queue_pending=arbitration_runtime.pending() if arbitration_runtime is not None else 0,
                started_at=arbitration_started_at,
            )
            self._maybe_emit_slow_scene(
                result,
                slow_scene=slow_scene,
                scene=outcome.scene,
                collected=collected,
                decision_mode=outcome.decision.mode,
                arbitration_outcome=outcome.outcome,
            )
            return False

        if self._health_monitor.safe_idle_recommended and outcome.scene.scene_type != "safety_alert_scene":
            self._emit_arbitration_trace(
                outcome.decision,
                status="suppressed_safe_idle",
                queue_pending=arbitration_runtime.pending() if arbitration_runtime is not None else 0,
                started_at=arbitration_started_at,
            )
            return False

        self._record_executed_decision(
            result,
            outcome.decision,
            scene=outcome.scene,
            arbitration_runtime=arbitration_runtime,
            executor=executor,
            started_at=arbitration_started_at,
        )
        self._maybe_emit_slow_scene(
            result,
            slow_scene=slow_scene,
            scene=outcome.scene,
            collected=collected,
            decision_mode=outcome.decision.mode,
            arbitration_outcome=outcome.outcome,
        )
        return True

    def _record_executed_decision(
        self,
        result: LiveLoopResult,
        decision: Any,
        *,
        scene: SceneCandidate | None,
        arbitration_runtime: ArbitrationRuntime | None,
        executor: BehaviorExecutor | None,
        started_at: float | None = None,
    ) -> None:
        decision = self._apply_behavior_decay_policy(decision, scene=scene)
        arbitration_started_at = started_at if started_at is not None else monotonic()
        result.arbitration_results.append(decision)
        self._emit_arbitration_trace(
            decision,
            status="ok",
            queue_pending=arbitration_runtime.pending() if arbitration_runtime is not None else 0,
            started_at=arbitration_started_at,
        )

        self._execution_manager.dispatch_decision(
            result,
            decision,
            arbitration_runtime=arbitration_runtime,
            executor=executor,
            executor_inbox=self._executor_inbox,
            executor_outbox=self._executor_outbox,
        )

    def _start_async_executor(self) -> None:
        if not self.async_executor_enabled:
            return
        executor = self.dependencies.executor
        if executor is None:
            return
        if bool(getattr(executor, "tick_execution_enabled", False)):
            logger.warning("async executor disabled because tick_execution is enabled")
            return
        if self._executor_thread is not None and self._executor_thread.is_alive():
            return
        self._executor_stop_event.clear()
        self._executor_inbox = Queue(maxsize=self.async_executor_queue_limit)
        self._executor_outbox = Queue(maxsize=self.async_executor_queue_limit * 2)
        self._executor_thread = Thread(
            target=self._execution_manager.async_worker,
            kwargs={
                "executor": executor,
                "inbox": self._executor_inbox,
                "outbox": self._executor_outbox,
                "stop_event": self._executor_stop_event,
                "on_failure": lambda exc: self._mark_async_worker_failure("executor", exc),
                "on_success": lambda: self._mark_async_worker_heartbeat("executor"),
            },
            name="behavior-executor-async",
            daemon=True,
        )
        self._executor_thread.start()

    def _stop_async_executor(self) -> None:
        self._executor_stop_event.set()
        thread = self._executor_thread
        self._executor_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._executor_inbox = None
        self._executor_outbox = None

    def _async_executor_worker(self, executor: BehaviorExecutor) -> None:
        self._execution_manager.async_worker(
            executor,
            inbox=self._executor_inbox,
            outbox=self._executor_outbox,
            stop_event=self._executor_stop_event,
        )

    def _emit_arbitration_trace(
        self,
        decision: Any,
        *,
        status: str,
        queue_pending: int,
        started_at: float,
    ) -> None:
        emit_stage_trace(
            self.telemetry,
            decision.trace_id,
            "arbitrator",
            status=status,
            payload=ArbitrationTracePayload.from_decision(decision, queue_pending=queue_pending).to_dict(),
            started_at=started_at,
            ended_at=monotonic(),
        )

    def _apply_behavior_decay_policy(
        self,
        decision: Any,
        *,
        scene: SceneCandidate | None = None,
    ) -> Any:
        decay_tracker = self.dependencies.decay_tracker
        if decay_tracker is None:
            return decision

        scene_type = scene.scene_type if scene is not None else (decision.scene_type or self._behavior_to_scene_type(decision.target_behavior))
        target_id = getattr(scene, "target_id", None) if scene is not None else decision.target_id
        strength, use_voice = decay_tracker.evaluate(scene_type, target_id)
        degrade_applied = False
        adjusted_decision = decision
        if not use_voice and decision.degraded_behavior and decision.mode in {
            DecisionMode.EXECUTE,
            DecisionMode.SOFT_INTERRUPT,
            DecisionMode.DEGRADE_AND_EXECUTE,
        }:
            adjusted_decision = replace(
                decision,
                mode=DecisionMode.DEGRADE_AND_EXECUTE,
                reason=f"{decision.reason}|decay_silent:{strength:.2f}",
            )
            degrade_applied = True

        self._decay_snapshot = {
            "scene_type": scene_type,
            "target_id": target_id,
            "strength": round(float(strength), 3),
            "use_voice": bool(use_voice),
            "degrade_applied": degrade_applied,
        }
        return adjusted_decision

    def _record_decay_execution(self, execution: Any) -> None:
        decay_tracker = self.dependencies.decay_tracker
        if decay_tracker is None:
            return
        if execution.status not in {"finished", "degraded"}:
            return
        scene_type = execution.scene_type or self._behavior_to_scene_type(execution.behavior_id)
        decay_tracker.record(scene_type, execution.target_id)

    def _update_life_state(self, result: LiveLoopResult) -> None:
        state_machine = self.dependencies.interaction_state_machine
        if state_machine is None:
            return

        state_machine.tick()
        snapshot = build_life_state_snapshot(result)

        if snapshot.has_p0_event:
            state_machine.on_safety_event(reason="p0_stable_event")
        elif snapshot.has_safety_scene:
            state_machine.on_safety_event(reason="safety_scene")
        elif state_machine.current_state.name == "SAFETY_OVERRIDE":
            state_machine.on_safety_resolved(reason="safety_clear")
        elif snapshot.has_attention_lost:
            state_machine.on_attention_lost(target_id=snapshot.mutual_target_id, reason="attention_lost")
        elif snapshot.social_execution is not None:
            state_machine.on_interaction_started(
                target_id=snapshot.social_execution.target_id or snapshot.latest_target_id,
                reason=f"behavior_executed:{snapshot.social_execution.behavior_id}",
            )
        elif snapshot.has_engagement_scene:
            state_machine.on_engagement_bid(target_id=snapshot.engagement_target_id, reason="engagement_scene")
        elif snapshot.has_mutual_attention_signal:
            state_machine.on_mutual_attention(target_id=snapshot.mutual_target_id, reason="mutual_attention_signal")
        elif snapshot.has_notice_signal:
            state_machine.on_notice_human(target_id=snapshot.noticed_target_id, reason="noticed_signal")

        self._interaction_snapshot = state_machine.snapshot()
        self._interaction_snapshot["latest_scene_type"] = getattr(snapshot.latest_scene, "scene_type", None)
        self._interaction_snapshot["latest_target_id"] = snapshot.latest_target_id
        self._interaction_snapshot["latest_scene_path"] = snapshot.latest_scene_path or None
        self._interaction_snapshot["latest_interaction_state"] = snapshot.latest_interaction_state or None
        self._interaction_snapshot["latest_engagement_score"] = (
            round(float(snapshot.latest_engagement_score), 3)
            if snapshot.latest_engagement_score is not None
            else None
        )
        self._interaction_snapshot["latest_scene_epoch"] = getattr(snapshot.latest_scene, "scene_epoch", None)
        emit_stage_trace(
            self.telemetry,
            trace_id=f"loop-life-{int(monotonic() * 1000)}",
            stage="interaction_state",
            payload={
                "interaction": dict(self._interaction_snapshot),
                "decay": dict(self._decay_snapshot),
            },
            started_at=monotonic(),
            ended_at=monotonic(),
        )

    def _update_robot_context(self, result: LiveLoopResult) -> None:
        robot_context_store = self.dependencies.robot_context_store
        executor = self.dependencies.executor
        if robot_context_store is None:
            return
        active_execution = executor.get_current_execution() if executor is not None else None
        robot_context_store.sync(
            interaction_snapshot=self._interaction_snapshot,
            active_execution=active_execution,
            execution_results=result.execution_results,
        )
        for execution in result.execution_results:
            self._health_monitor.record_execution(execution)

    def _emit_source_health_trace(self, cycle_started_at: float) -> None:
        snapshot_fn = getattr(self.source_bundle, "snapshot_health", None)
        if not callable(snapshot_fn):
            return
        try:
            source_health = snapshot_fn()
        except Exception:
            source_health = {}
        for source_name, snapshot in source_health.items():
            if isinstance(snapshot, dict):
                self._health_monitor.record_source_health(source_name, snapshot)
        emit_stage_trace(
            self.telemetry,
            trace_id=f"loop-health-{int(cycle_started_at * 1000)}",
            stage="source_health",
            payload={"sources": source_health, "workers": self._snapshot_async_worker_status()},
            started_at=cycle_started_at,
            ended_at=monotonic(),
        )
        emit_stage_trace(
            self.telemetry,
            trace_id=f"loop-health-summary-{int(cycle_started_at * 1000)}",
            stage="runtime_health",
            payload=self._health_monitor.snapshot(),
            started_at=cycle_started_at,
            ended_at=monotonic(),
        )

    def snapshot_life_state(self) -> dict[str, Any]:
        tracker_snapshot: dict[str, Any] = {}
        entity_tracker = self.dependencies.entity_tracker
        if entity_tracker is not None:
            try:
                tracker_snapshot = entity_tracker.snapshot()
            except Exception:
                tracker_snapshot = {}
        temporal_snapshot: dict[str, Any] = {}
        temporal_event_layer = self.dependencies.temporal_event_layer
        if temporal_event_layer is not None:
            try:
                temporal_snapshot = temporal_event_layer.snapshot()
            except Exception:
                temporal_snapshot = {}
        robot_context_snapshot: dict[str, Any] = {}
        robot_context_store = self.dependencies.robot_context_store
        if robot_context_store is not None:
            try:
                robot_context_snapshot = robot_context_store.snapshot()
            except Exception:
                robot_context_snapshot = {}
        return {
            "interaction": dict(self._interaction_snapshot),
            "decay": dict(self._decay_snapshot),
            "entity_tracker": tracker_snapshot,
            "temporal_events": temporal_snapshot,
            "robot_context": robot_context_snapshot,
            "target_governor": self._target_governor.snapshot(),
            "long_task": self._long_task_coordinator.snapshot(),
            "health": self._health_monitor.snapshot(),
            "workers": self._snapshot_async_worker_status(),
            "telemetry": telemetry_snapshot(self.telemetry),
        }

    def _maybe_emit_slow_scene(
        self,
        result: LiveLoopResult,
        *,
        slow_scene: Any | None,
        scene: SceneCandidate,
        collected: CollectedFrames,
        decision_mode: Any | None,
        arbitration_outcome: str,
    ) -> None:
        if not self.enable_slow_scene or slow_scene is None:
            return

        slow_started_at = monotonic()
        scene_json = self._submit_or_query_slow_scene(
            slow_scene,
            scene,
            collected,
            decision_mode=decision_mode,
            arbitration_outcome=arbitration_outcome,
        )
        if scene_json is None:
            return

        result.slow_scene_results.append(scene_json)
        emit_stage_trace(
            self.telemetry,
            scene.trace_id,
            "slow_scene",
            payload={"scene_type": scene_json.scene_type, "confidence": scene_json.confidence},
            started_at=slow_started_at,
            ended_at=monotonic(),
        )

    @staticmethod
    def _behavior_to_scene_type(behavior_id: str) -> str:
        """Best-effort reverse mapping from behavior_id to scene_type for cooldown tracking."""
        return _BEHAVIOR_SCENE_TYPE_MAP.get(behavior_id, behavior_id)


def _latest_target_id_from_events(
    events: list[Any],
    *,
    preferred_event_types: set[str],
) -> str | None:
    for event in reversed(events):
        if getattr(event, "event_type", None) not in preferred_event_types:
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue
        accessor = DetectionPayloadAccessor(payload)
        if accessor.target_id:
            return accessor.target_id
    return None
