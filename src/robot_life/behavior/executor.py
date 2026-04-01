from __future__ import annotations
from collections import deque
import logging
from time import time

from robot_life.behavior.behavior_registry import BehaviorRegistry
from robot_life.behavior.bt_runtime import BehaviorRuntime
from robot_life.behavior.resources import ResourceManager
from robot_life.behavior.safety_guard import BehaviorSafetyGuard
from robot_life.common.schemas import ArbitrationResult, DecisionMode, EventPriority, ExecutionResult, new_id

logger = logging.getLogger(__name__)

_BEHAVIOR_HISTORY_LIMIT = 512


class BehaviorExecutor:
    """
    Executes behaviors based on arbitration results.
    
    Responsibilities:
    - Request resource grants
    - Execute behavior tree (placeholder for BehaviorTree.CPP)
    - Handle interruption and resumption
    - Support degraded execution
    """

    def __init__(
        self,
        resource_manager: ResourceManager | None = None,
        *,
        safety_guard: BehaviorSafetyGuard | None = None,
        tick_execution: bool = False,
        tick_max_nodes: int = 0,
    ):
        """
        Initialize executor with optional resource manager.
        
        Args:
            resource_manager: ResourceManager instance, creates if None
        """
        self._resource_manager = resource_manager or ResourceManager()
        self._runtime = BehaviorRuntime()
        self._registry = BehaviorRegistry()
        self._safety_guard = safety_guard or BehaviorSafetyGuard()
        self._current_execution: dict[str, ExecutionResult] = {}
        self._behavior_history = deque(maxlen=_BEHAVIOR_HISTORY_LIMIT)  # For resumption/debug visibility
        self._last_decision: ArbitrationResult | None = None
        self._pending_resume_decisions: list[ArbitrationResult] = []
        self._active_grant_id: str | None = None
        self._tick_execution = bool(tick_execution)
        self._tick_max_nodes = max(1, int(tick_max_nodes)) if tick_execution else 0

    def execute(
        self,
        decision: ArbitrationResult,
        duration_ms: int = 5000,
    ) -> ExecutionResult:
        """
        Execute behavior based on arbitration decision.
        
        Args:
            decision: ArbitrationResult from arbitrator
            duration_ms: Expected behavior duration
            
        Returns:
            ExecutionResult with status and outcome
        """
        started_at = time()

        current_active = self._runtime.active_behavior()
        current_decision = self._last_decision if current_active is not None else None
        safety = self._safety_guard.evaluate(decision, current_decision=current_decision)
        if safety.estop_required:
            self.interrupt_current(DecisionMode.HARD_INTERRUPT)
            self._pending_resume_decisions.clear()
            self._resource_manager.force_release_all()
            logger.warning("Emergency stop preemption engaged: %s", safety.reason)
        if not safety.allowed:
            logger.warning("Behavior blocked by safety guard: %s", safety.reason)
            execution = ExecutionResult(
                execution_id=new_id(),
                trace_id=decision.trace_id,
                behavior_id=decision.target_behavior,
                status="blocked",
                interrupted=False,
                degraded=False,
                started_at=started_at,
                ended_at=time(),
                target_id=decision.target_id,
                scene_type=decision.scene_type,
                engagement_score=decision.engagement_score,
                scene_path=decision.scene_path,
                interaction_state=decision.interaction_state,
                interaction_episode_id=decision.interaction_episode_id,
                scene_epoch=decision.scene_epoch,
                decision_epoch=decision.decision_epoch,
            )
            self._behavior_history.append(execution)
            return execution

        # Step 1: Request resource grant
        resource_grant = self._resource_manager.request_grant(
            trace_id=decision.trace_id,
            decision_id=decision.decision_id,
            behavior_id=decision.target_behavior,
            required_resources=decision.required_resources,
            optional_resources=decision.optional_resources,
            priority=self._priority_to_int(decision.priority),
            duration_ms=duration_ms,
        )

        # Step 2: Decide execution path based on resource grant and decision mode
        can_fallback_to_degraded = bool(
            decision.degraded_behavior and len(resource_grant.granted_resources) >= len(decision.required_resources)
        )

        if (
            not resource_grant.granted
            and decision.required_resources
            and not can_fallback_to_degraded
        ):
            # Cannot execute without required resources
            execution = ExecutionResult(
                execution_id=new_id(),
                trace_id=decision.trace_id,
                behavior_id=decision.target_behavior,
                status="failed",
                interrupted=False,
                degraded=False,
                started_at=started_at,
                ended_at=time(),
                target_id=decision.target_id,
                scene_type=decision.scene_type,
                engagement_score=decision.engagement_score,
                scene_path=decision.scene_path,
                interaction_state=decision.interaction_state,
                interaction_episode_id=decision.interaction_episode_id,
                scene_epoch=decision.scene_epoch,
                decision_epoch=decision.decision_epoch,
            )
            self._behavior_history.append(execution)
            return execution

        # Step 3: Check if we should degrade or execute fully
        resume_candidate = None
        if decision.mode in {DecisionMode.SOFT_INTERRUPT, DecisionMode.HARD_INTERRUPT}:
            resume_candidate = self._capture_resume_candidate(decision)
            interrupted = self.interrupt_current(decision.mode)
            if interrupted:
                self._behavior_history.append(interrupted)
            if decision.mode == DecisionMode.HARD_INTERRUPT and not decision.resume_previous:
                self._pending_resume_decisions.clear()

        if (not resource_grant.granted or decision.mode == DecisionMode.DEGRADE_AND_EXECUTE) and decision.degraded_behavior:
            # Execute degraded version
            execution = self._execute_behavior(
                decision=decision,
                behavior_name=decision.degraded_behavior,
                granted_resources=resource_grant.granted_resources,
                is_degraded=True,
                grant_id=resource_grant.grant_id,
                started_at=started_at,
            )
        else:
            # Execute full behavior
            execution = self._execute_behavior(
                decision=decision,
                behavior_name=decision.target_behavior,
                granted_resources=resource_grant.granted_resources,
                is_degraded=False,
                grant_id=resource_grant.grant_id,
                started_at=started_at,
            )

        self._behavior_history.append(execution)
        self._last_decision = decision
        if resume_candidate is not None:
            self._pending_resume_decisions.append(
                ArbitrationResult(
                    decision_id=new_id(),
                    trace_id=resume_candidate.trace_id,
                    target_behavior=resume_candidate.target_behavior,
                    priority=resume_candidate.priority,
                    mode=DecisionMode.EXECUTE,
                    required_resources=list(resume_candidate.required_resources),
                    optional_resources=list(resume_candidate.optional_resources),
                    degraded_behavior=resume_candidate.degraded_behavior,
                    resume_previous=False,
                    reason=f"resume_after_{decision.mode.value.lower()}:{decision.target_behavior}",
                    target_id=resume_candidate.target_id,
                    scene_type=resume_candidate.scene_type,
                    engagement_score=resume_candidate.engagement_score,
                    scene_path=resume_candidate.scene_path,
                    interaction_state=resume_candidate.interaction_state,
                    interaction_episode_id=resume_candidate.interaction_episode_id,
                    scene_epoch=resume_candidate.scene_epoch,
                    decision_epoch=resume_candidate.decision_epoch,
                )
            )
        return execution

    def _execute_behavior(
        self,
        decision: ArbitrationResult,
        behavior_name: str,
        granted_resources: list[str],
        is_degraded: bool,
        grant_id: str,
        started_at: float,
    ) -> ExecutionResult:
        """
        Internal: Execute a specific behavior.
        
        Placeholder for BehaviorTree.CPP integration.
        """
        template = self._registry.get(behavior_name)
        if self._tick_execution:
            active = self._runtime.active_behavior()
            if active is None:
                self._runtime.start(
                    trace_id=decision.trace_id,
                    template=template,
                    grant_id=grant_id,
                    degraded=is_degraded,
                    mode=decision.mode,
                    started_at=started_at,
                )
                self._active_grant_id = grant_id
            execution = self._runtime.tick(max_nodes=self._tick_max_nodes)
            if execution is None:
                active_after_tick = self._runtime.active_behavior()
                return ExecutionResult(
                    execution_id=(active_after_tick.execution_id if active_after_tick is not None else new_id()),
                    trace_id=decision.trace_id,
                    behavior_id=behavior_name,
                    status="running",
                    interrupted=False,
                    degraded=is_degraded,
                    started_at=started_at,
                    ended_at=time(),
                    target_id=decision.target_id,
                    scene_type=decision.scene_type,
                    engagement_score=decision.engagement_score,
                    scene_path=decision.scene_path,
                    interaction_state=decision.interaction_state,
                    interaction_episode_id=decision.interaction_episode_id,
                    scene_epoch=decision.scene_epoch,
                    decision_epoch=decision.decision_epoch,
                )
        else:
            execution = self._runtime.run_to_completion(
                trace_id=decision.trace_id,
                template=template,
                grant_id=grant_id,
                degraded=is_degraded,
                mode=decision.mode,
                started_at=started_at,
            )

        execution.target_id = decision.target_id
        execution.scene_type = decision.scene_type
        execution.engagement_score = decision.engagement_score
        execution.scene_path = decision.scene_path
        execution.interaction_state = decision.interaction_state
        execution.interaction_episode_id = decision.interaction_episode_id
        execution.scene_epoch = decision.scene_epoch
        execution.decision_epoch = decision.decision_epoch
        self._current_execution = {}

        # Release resource grant after execution
        if self._active_grant_id:
            self._resource_manager.release_grant(self._active_grant_id)
            self._active_grant_id = None
        else:
            self._resource_manager.release_grant(grant_id)

        return execution

    def interrupt_current(self, mode: DecisionMode = DecisionMode.SOFT_INTERRUPT) -> ExecutionResult | None:
        """
        Interrupt currently executing behavior.
        
        Returns:
            ExecutionResult if interrupted successfully
        """
        interrupted = self._runtime.interrupt(mode)
        if self._active_grant_id:
            self._resource_manager.release_grant(self._active_grant_id)
            self._active_grant_id = None
        self._current_execution = {}
        return interrupted

    def tick_active(self) -> ExecutionResult | None:
        """Advance current active behavior by one tick when tick mode is enabled."""
        if not self._tick_execution:
            return None
        execution = self._runtime.tick(max_nodes=self._tick_max_nodes)
        if execution is None:
            return None
        if self._active_grant_id:
            self._resource_manager.release_grant(self._active_grant_id)
            self._active_grant_id = None
        self._behavior_history.append(execution)
        return execution

    @property
    def tick_execution_enabled(self) -> bool:
        return self._tick_execution

    def resume_previous(self) -> ArbitrationResult | None:
        """
        Return next resumable decision captured during interrupt handling.

        Returns:
            ArbitrationResult if available, None otherwise
        """
        return self.pop_resume_decision()

    def pop_resume_decision(self) -> ArbitrationResult | None:
        """Pop next pending resume decision generated by interrupt handling."""
        if not self._pending_resume_decisions:
            return None
        return self._pending_resume_decisions.pop(0)

    def get_current_execution(self) -> ExecutionResult | None:
        """Get currently executing behavior."""
        if self._current_execution:
            return list(self._current_execution.values())[0]
        active = self._runtime.active_behavior()
        if active is not None:
            return ExecutionResult(
                execution_id=active.execution_id,
                trace_id=active.trace_id,
                behavior_id=active.behavior_id,
                status=active.status,
                interrupted=False,
                degraded=active.degraded,
                started_at=active.started_at,
                ended_at=active.started_at,
            )
        return None

    def get_resource_status(self) -> dict[str, str]:
        """Get current resource allocation status."""
        return self._resource_manager.get_resource_status()

    def get_debug_snapshot(self) -> dict:
        active = self._runtime.active_behavior()
        active_payload = None
        if active is not None:
            active_payload = {
                "execution_id": active.execution_id,
                "trace_id": active.trace_id,
                "behavior_id": active.behavior_id,
                "status": active.status,
                "degraded": active.degraded,
                "started_at": active.started_at,
            }

        return {
            "active_behavior": active_payload,
            "history_size": len(self._behavior_history),
            "pending_resume_decisions": len(self._pending_resume_decisions),
            "tick_execution": self._tick_execution,
            "tick_max_nodes": self._tick_max_nodes,
            "resources": self._resource_manager.debug_snapshot(),
        }

    def _capture_resume_candidate(self, decision: ArbitrationResult) -> ArbitrationResult | None:
        """Capture previous decision as resumable victim for interrupt paths."""
        if not decision.resume_previous:
            return None
        candidate = self._last_decision
        if candidate is None:
            return None
        if candidate.target_behavior == decision.target_behavior:
            return None
        if not self._registry.get(candidate.target_behavior).resumable:
            return None
        return candidate

    @staticmethod
    def _priority_to_int(priority_str: str | EventPriority) -> int:
        """Convert priority string (P0-P3) to integer for resource arbitration.
        P0 (highest) -> 3, P1 -> 2, P2 -> 1, P3 (lowest) -> 0.
        Higher value = higher priority for preemption.
        """
        normalized = priority_str.value if isinstance(priority_str, EventPriority) else str(priority_str or "")
        try:
            # Reverse mapping: P0->3, P1->2, P2->1, P3->0
            priority_num = int(normalized[1])  # "P2" -> 2
            return 3 - priority_num  # Invert: 2 -> 1, 0 -> 3
        except (IndexError, ValueError, TypeError):
            return 1  # Default to P2 (middle)
