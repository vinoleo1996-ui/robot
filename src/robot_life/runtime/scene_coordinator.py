from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.common.robot_context import RobotContextStore
from robot_life.common.schemas import EventPriority, SceneCandidate
from robot_life.common.state_machine import InteractionStateMachine
from robot_life.event_engine.arbitration_runtime import ArbitrationBatchOutcome, ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.cooldown_manager import CooldownManager
from robot_life.runtime.scene_context import enrich_scene_candidate
from robot_life.runtime.scene_ops import coalesce_scene_candidates, partition_scene_candidates_by_path, scene_priority, set_scene_priority
from robot_life.runtime.target_governor import TargetGovernor
from robot_life.runtime.telemetry import emit_stage_trace


BatchSubmitter = Callable[[list[SceneCandidate], Arbitrator | None], list[ArbitrationBatchOutcome]]
OutcomeRecorder = Callable[..., bool]


@dataclass
class SceneCoordinator:
    telemetry: Any
    cooldown_manager: CooldownManager | None
    interaction_state_machine: InteractionStateMachine | None
    robot_context_store: RobotContextStore | None
    arbitration_batch_window_ms: int
    max_scenes_per_cycle: int
    submit_batch_without_runtime: BatchSubmitter
    record_batch_outcome: OutcomeRecorder
    target_governor: TargetGovernor | None = None

    def process_batch(
        self,
        result: Any,
        *,
        collected: Any,
        interaction_snapshot: dict[str, Any],
        arbitrator: Arbitrator | None,
        arbitration_runtime: ArbitrationRuntime | None,
        executor: BehaviorExecutor | None,
        slow_scene: Any | None,
    ) -> None:
        resolved_arbitrator = arbitrator or (arbitration_runtime.arbitrator if arbitration_runtime else None)
        scenes = coalesce_scene_candidates(
            result.scene_candidates,
            arbitrator=resolved_arbitrator,
            max_scenes_per_cycle=self.max_scenes_per_cycle,
        )
        scenes = self._enrich_and_filter_scenes(
            scenes,
            collected=collected,
            interaction_snapshot=interaction_snapshot,
            resolved_arbitrator=resolved_arbitrator,
            executor=executor,
        )
        scenes = self._govern_targets(
            scenes,
            interaction_snapshot=interaction_snapshot,
        )
        partitioned = partition_scene_candidates_by_path(scenes)
        ordered_scene_candidates = partitioned["safety"] + partitioned["social"]
        result.scene_candidates = ordered_scene_candidates
        result.scene_batches = {
            "safety": list(partitioned["safety"]),
            "social": list(partitioned["social"]),
        }

        executed_safety = False
        for path_name in ("safety", "social"):
            path_scenes = partitioned[path_name]
            if not path_scenes:
                continue
            if path_name == "social" and executed_safety:
                for scene in path_scenes:
                    emit_stage_trace(
                        self.telemetry,
                        scene.trace_id,
                        "scene_route",
                        status="suppressed_by_safety",
                        payload={"scene_type": scene.scene_type, "scene_path": path_name},
                        started_at=monotonic(),
                        ended_at=monotonic(),
                    )
                continue

            for scene in path_scenes:
                emit_stage_trace(
                    self.telemetry,
                    scene.trace_id,
                    "scene_route",
                    payload={"scene_type": scene.scene_type, "scene_path": path_name},
                    started_at=monotonic(),
                    ended_at=monotonic(),
                )

            if arbitration_runtime is not None:
                outcomes = arbitration_runtime.submit_batch(
                    path_scenes,
                    batch_window_ms=self.arbitration_batch_window_ms,
                )
            else:
                outcomes = self.submit_batch_without_runtime(path_scenes, resolved_arbitrator)

            for outcome in outcomes:
                executed = self.record_batch_outcome(
                    result,
                    outcome=outcome,
                    collected=collected,
                    arbitration_runtime=arbitration_runtime,
                    executor=executor,
                    slow_scene=slow_scene,
                )
                if path_name == "safety" and executed:
                    executed_safety = True


    def _govern_targets(
        self,
        scenes: list[SceneCandidate],
        *,
        interaction_snapshot: dict[str, Any],
    ) -> list[SceneCandidate]:
        governor = self.target_governor
        if governor is None:
            return scenes
        state_machine = self.interaction_state_machine
        active_target_id = state_machine.current_target_id if state_machine is not None else None
        decision = governor.govern(
            scenes,
            active_target_id=active_target_id,
            interaction_snapshot=interaction_snapshot,
        )
        for scene in decision.suppressed:
            emit_stage_trace(
                self.telemetry,
                scene.trace_id,
                "target_governance",
                status="suppressed",
                payload={
                    "scene_type": scene.scene_type,
                    "target_id": scene.target_id,
                    "owner_target_id": decision.owner_target_id,
                    "reason": decision.reason,
                },
                started_at=monotonic(),
                ended_at=monotonic(),
            )
        for scene in decision.accepted:
            emit_stage_trace(
                self.telemetry,
                scene.trace_id,
                "target_governance",
                status="accepted",
                payload={
                    "scene_type": scene.scene_type,
                    "target_id": scene.target_id,
                    "owner_target_id": decision.owner_target_id,
                    "reason": decision.reason,
                    "switched": decision.switched,
                },
                started_at=monotonic(),
                ended_at=monotonic(),
            )
        return decision.accepted

    def _enrich_and_filter_scenes(
        self,
        scenes: list[SceneCandidate],
        *,
        collected: Any,
        interaction_snapshot: dict[str, Any],
        resolved_arbitrator: Arbitrator | None,
        executor: BehaviorExecutor | None,
    ) -> list[SceneCandidate]:
        state_machine = self.interaction_state_machine
        active_target_id = state_machine.current_target_id if state_machine is not None else None
        active_execution = executor.get_current_execution() if executor is not None else None
        active_behavior_id = getattr(active_execution, "behavior_id", None)
        robot_busy = bool(active_execution is not None and getattr(active_execution, "status", None) == "running")
        robot_context = self.robot_context_store.snapshot() if self.robot_context_store is not None else {}

        enriched_scenes: list[SceneCandidate] = []
        for scene in scenes:
            priority = scene_priority(scene, resolved_arbitrator)
            enriched = enrich_scene_candidate(
                scene,
                frame_seq=collected.frame_seq,
                collected_at=collected.collected_at,
                interaction_snapshot=interaction_snapshot,
                robot_context=robot_context,
                priority=priority,
                active_behavior_id=active_behavior_id,
                robot_busy=robot_busy,
            )
            enriched = set_scene_priority(enriched, priority)
            if self._passes_cooldown(
                enriched,
                priority=priority,
                active_target_id=active_target_id,
                active_behavior_id=active_behavior_id,
                robot_busy=robot_busy,
            ):
                enriched_scenes.append(enriched)
        return enriched_scenes

    def _passes_cooldown(
        self,
        scene: SceneCandidate,
        *,
        priority: EventPriority,
        active_target_id: str | None,
        active_behavior_id: str | None,
        robot_busy: bool,
    ) -> bool:
        cooldown_mgr = self.cooldown_manager
        if cooldown_mgr is None:
            return True
        allowed, reason = cooldown_mgr.check(
            scene.scene_type,
            scene.target_id,
            priority,
            active_target_id=active_target_id,
            active_behavior_id=active_behavior_id,
            robot_busy=robot_busy,
        )
        if allowed:
            return True
        emit_stage_trace(
            self.telemetry,
            scene.trace_id,
            "cooldown_filter",
            status="suppressed",
            payload={"scene_type": scene.scene_type, "reason": reason},
            started_at=monotonic(),
            ended_at=monotonic(),
        )
        return False
