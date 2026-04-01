from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from robot_life.common.contracts import priority_rank
from robot_life.common.schemas import ArbitrationResult, DecisionMode, EventPriority, SceneCandidate
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.decision_queue import DecisionQueue


@dataclass
class ArbitrationBatchOutcome:
    """Per-scene result produced by batch arbitration."""

    scene: SceneCandidate
    decision: ArbitrationResult
    outcome: str
    executed: bool


class ArbitrationRuntime:
    """
    Stateful arbitration coordinator.

    Handles preemption, queueing, dropping, and draining queued decisions.
    """

    def __init__(
        self,
        arbitrator: Arbitrator | None = None,
        queue: DecisionQueue | None = None,
        *,
        batch_window_ms: int = 40,
        p1_queue_limit: int = 3,
        p2_queue_limit: int = 4,
        starvation_after_ms: int = 1_500,
    ) -> None:
        self.arbitrator = arbitrator or Arbitrator()
        self.queue = queue if queue is not None else DecisionQueue()
        self.batch_window_ms = max(1, int(batch_window_ms))
        self.p1_queue_limit = max(1, int(p1_queue_limit))
        self.p2_queue_limit = max(1, int(p2_queue_limit))
        self.starvation_after_ms = max(0, int(starvation_after_ms))
        self._active_priority: EventPriority | None = None
        self._active_decision_key: str | None = None
        self._last_outcome = "idle"
        self._last_decision: ArbitrationResult | None = None
        self._decision_keys: dict[str, str] = {}
        self._recent_p1_keys: dict[str, float] = {}
        self._recent_p2_keys: dict[str, float] = {}
        self._outcome_counts: dict[str, int] = {
            "idle": 0,
            "executed": 0,
            "queued": 0,
            "debounced": 0,
            "dropped": 0,
            "dequeued": 0,
        }

    @property
    def active_priority(self) -> EventPriority | None:
        return self._active_priority

    def submit(
        self,
        scene: SceneCandidate,
        *,
        current_priority: EventPriority | None = None,
        batch_window_ms: int | None = None,
    ) -> ArbitrationResult | None:
        outcome = self._submit_scene(
            scene,
            current_priority=current_priority,
            batch_window_ms=batch_window_ms,
        )
        if outcome.executed:
            return outcome.decision
        return None

    def submit_batch(
        self,
        scenes: list[SceneCandidate],
        *,
        current_priority: EventPriority | None = None,
        batch_window_ms: int | None = None,
    ) -> list[ArbitrationBatchOutcome]:
        if not scenes:
            return []

        ordered_scenes = sorted(
            enumerate(scenes),
            key=lambda item: (
                priority_rank(self._base_priority(item[1])),
                item[0],
            ),
        )

        outcomes: list[ArbitrationBatchOutcome] = []
        simulated_priority = current_priority if current_priority is not None else self._active_priority
        for _index, scene in ordered_scenes:
            outcome = self._submit_scene(
                scene,
                current_priority=simulated_priority,
                batch_window_ms=batch_window_ms,
            )
            outcomes.append(outcome)
            if outcome.executed:
                simulated_priority = outcome.decision.priority
        return outcomes

    def complete_active(self) -> ArbitrationResult | None:
        self._active_priority = None
        queued = self.queue.pop_starved_oldest(
            starvation_after_ms=self.starvation_after_ms,
            priorities={EventPriority.P2, EventPriority.P3},
            now=self._now(),
        )
        if queued is None:
            queued = self.queue.pop_next()
        self._active_decision_key = None
        if queued is None:
            return None
        promoted = ArbitrationResult(
            decision_id=queued.decision_id,
            trace_id=queued.trace_id,
            target_behavior=queued.target_behavior,
            priority=queued.priority,
            mode=DecisionMode.EXECUTE,
            required_resources=queued.required_resources,
            optional_resources=queued.optional_resources,
            degraded_behavior=queued.degraded_behavior,
            resume_previous=queued.resume_previous,
            reason=f"dequeued: {queued.reason}",
        )
        self._active_priority = promoted.priority
        self._active_decision_key = self._decision_keys.get(promoted.decision_id)
        self._last_decision = promoted
        self._last_outcome = "dequeued"
        self._outcome_counts["dequeued"] += 1
        return promoted

    def clear(self) -> None:
        self._active_priority = None
        self._active_decision_key = None
        self._decision_keys.clear()
        self._recent_p1_keys.clear()
        self._recent_p2_keys.clear()
        self.queue.clear()

    def pending(self) -> int:
        return len(self.queue)

    @property
    def last_outcome(self) -> str:
        return self._last_outcome

    @property
    def last_decision(self) -> ArbitrationResult | None:
        return self._last_decision

    def snapshot_stats(self) -> dict:
        decision = self._last_decision
        decision_payload = None
        if decision is not None:
            decision_payload = {
                "decision_id": decision.decision_id,
                "target_behavior": decision.target_behavior,
                "priority": decision.priority.value,
                "mode": decision.mode.value,
                "reason": decision.reason,
            }

        pending_by_priority = {
            EventPriority.P1.value: self.queue.count(EventPriority.P1),
            EventPriority.P2.value: self.queue.count(EventPriority.P2),
            EventPriority.P3.value: self.queue.count(EventPriority.P3),
        }

        return {
            "active_priority": self._active_priority.value if self._active_priority is not None else None,
            "pending_queue": self.pending(),
            "pending_by_priority": pending_by_priority,
            "last_outcome": self._last_outcome,
            "outcomes": dict(self._outcome_counts),
            "last_decision": decision_payload,
        }

    def _submit_scene(
        self,
        scene: SceneCandidate,
        *,
        current_priority: EventPriority | None,
        batch_window_ms: int | None,
    ) -> ArbitrationBatchOutcome:
        active_priority = current_priority if current_priority is not None else self._active_priority
        decision = self.arbitrator.decide(scene, current_priority=active_priority)
        self._last_decision = decision

        if decision.mode in {DecisionMode.DROP, DecisionMode.QUEUE}:
            if self._should_enqueue_with_replace(decision):
                outcome = self._enqueue_with_replace(scene, decision, batch_window_ms=batch_window_ms)
                if outcome in {"queued", "debounced"}:
                    self._record_outcome(outcome)
                    return ArbitrationBatchOutcome(
                        scene=scene,
                        decision=decision,
                        outcome=outcome,
                        executed=False,
                    )
            elif decision.mode == DecisionMode.QUEUE or self.arbitrator.should_enqueue(decision):
                queued = self.queue.enqueue(
                    decision,
                    timeout_ms=self.arbitrator.queue_timeout_ms(decision.priority),
                )
                if queued is not None:
                    self._record_outcome("queued")
                    return ArbitrationBatchOutcome(scene=scene, decision=decision, outcome="queued", executed=False)

            terminal_outcome = "dropped" if decision.mode == DecisionMode.DROP else "debounced"
            self._record_outcome(terminal_outcome)
            return ArbitrationBatchOutcome(scene=scene, decision=decision, outcome=terminal_outcome, executed=False)

        self._active_priority = decision.priority
        self._active_decision_key = self._decision_key(scene, decision)
        self._remember_decision_key(decision, self._active_decision_key)
        if decision.priority in {EventPriority.P1, EventPriority.P2} and self._active_decision_key is not None:
            now = self._now()
            self._recent_key_store(decision.priority)[self._active_decision_key] = now
            self._prune_recent_keys(decision.priority, now, batch_window_ms=batch_window_ms)
        self._record_outcome("executed")
        return ArbitrationBatchOutcome(scene=scene, decision=decision, outcome="executed", executed=True)

    def _enqueue_with_replace(
        self,
        scene: SceneCandidate,
        decision: ArbitrationResult,
        *,
        batch_window_ms: int | None,
    ) -> str:
        key = self._decision_key(scene, decision)
        now = self._now()
        recent_keys = self._recent_key_store(decision.priority)
        self._prune_recent_keys(decision.priority, now, batch_window_ms=batch_window_ms)

        queued_count = self.queue.count(decision.priority)
        queue_limit = self._queue_limit(decision.priority)
        if queued_count >= queue_limit and (key is None or not self.queue.has_replace_key(key)):
            self._evict_for_fairness(decision.priority, incoming_key=key)

        debounce_window_ms = self._resolved_batch_window_ms(batch_window_ms, priority=decision.priority)
        if key is not None:
            last_seen = recent_keys.get(key)
            if last_seen is not None and (now - last_seen) < (debounce_window_ms / 1000):
                if not self.queue.has_replace_key(key):
                    self._remember_decision_key(decision, key)
                    recent_keys[key] = now
                    return "debounced"
                queued = self.queue.enqueue(
                    decision,
                    timeout_ms=self.arbitrator.queue_timeout_ms(decision.priority),
                    replace_key=key,
                    debounce_window_ms=debounce_window_ms,
                )
                if queued is not None:
                    self._remember_decision_key(decision, key)
                    recent_keys[key] = now
                    return "queued"

                self._remember_decision_key(decision, key)
                recent_keys[key] = now
                return "debounced"

        queued = self.queue.enqueue(
            decision,
            timeout_ms=self.arbitrator.queue_timeout_ms(decision.priority),
            replace_key=key,
            debounce_window_ms=debounce_window_ms,
        )
        if queued is None:
            if key is not None:
                recent_keys[key] = now
            return "debounced" if key is not None else "dropped"

        self._remember_decision_key(decision, key)
        if key is not None:
            recent_keys[key] = now
        return "queued"

    def _should_enqueue_with_replace(self, decision: ArbitrationResult) -> bool:
        return decision.mode in {DecisionMode.DROP, DecisionMode.QUEUE} and decision.priority in {
            EventPriority.P1,
            EventPriority.P2,
        }

    def _resolved_batch_window_ms(self, batch_window_ms: int | None, *, priority: EventPriority) -> int:
        base_window_ms = self.batch_window_ms if batch_window_ms is None else max(1, int(batch_window_ms))
        if priority == EventPriority.P2:
            return max(base_window_ms * 2, 80)
        return base_window_ms

    def _queue_limit(self, priority: EventPriority) -> int:
        if priority == EventPriority.P1:
            return self.p1_queue_limit
        if priority == EventPriority.P2:
            return self.p2_queue_limit
        return max(self.p1_queue_limit, self.p2_queue_limit)

    def _prune_recent_keys(self, priority: EventPriority, now: float, *, batch_window_ms: int | None) -> None:
        ttl = self._resolved_batch_window_ms(batch_window_ms, priority=priority) / 1000
        recent_keys = self._recent_key_store(priority)
        stale_keys = [key for key, seen_at in recent_keys.items() if (now - seen_at) > ttl]
        for key in stale_keys:
            recent_keys.pop(key, None)

    def _recent_key_store(self, priority: EventPriority) -> dict[str, float]:
        if priority == EventPriority.P2:
            return self._recent_p2_keys
        return self._recent_p1_keys

    def _evict_for_fairness(self, priority: EventPriority, *, incoming_key: str | None) -> None:
        if incoming_key is None:
            self.queue.drop_oldest(priority)
            return

        queued_items = self.queue.items(priority)
        if not queued_items:
            return

        incoming_target = self._target_from_key(incoming_key)
        candidate_items: list[tuple[object, str]] = []
        per_target_counts: dict[str, int] = {}
        for item in queued_items:
            queued_key = self.queue.replace_key_for(item)
            if queued_key is None:
                continue
            target_id = self._target_from_key(queued_key)
            per_target_counts[target_id] = per_target_counts.get(target_id, 0) + 1
            candidate_items.append((item, target_id))

        if not candidate_items:
            self.queue.drop_oldest(priority)
            return

        preferred_target = incoming_target
        if per_target_counts.get(preferred_target, 0) <= 0:
            preferred_target = max(
                per_target_counts,
                key=lambda target_id: (
                    per_target_counts[target_id],
                    1 if target_id == self._target_from_key(self._active_decision_key) else 0,
                ),
            )

        for item, target_id in candidate_items:
            if target_id != preferred_target:
                continue
            self.queue.drop_queue_id(item.queue_id)
            return

        self.queue.drop_oldest(priority)

    def _remember_decision_key(self, decision: ArbitrationResult, key: str | None) -> None:
        if key is not None:
            self._decision_keys[decision.decision_id] = key

    def _decision_key(self, scene: SceneCandidate, decision: ArbitrationResult) -> str | None:
        if decision.priority not in {EventPriority.P1, EventPriority.P2}:
            return None
        target_id = getattr(scene, "target_id", None) or "any"
        return f"{scene.scene_type}:{target_id}:{decision.target_behavior}"

    @staticmethod
    def _target_from_key(key: str | None) -> str:
        if not key:
            return "any"
        parts = key.split(":", 2)
        if len(parts) < 2:
            return "any"
        return parts[1] or "any"

    def _base_priority(self, scene: SceneCandidate) -> EventPriority:
        return self.arbitrator.decide(scene, current_priority=None).priority

    def _record_outcome(self, outcome: str) -> None:
        self._last_outcome = outcome
        if outcome in self._outcome_counts:
            self._outcome_counts[outcome] += 1

    def _now(self) -> float:
        return monotonic()
