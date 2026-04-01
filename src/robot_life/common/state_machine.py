# Interaction State Machine (table-driven MVP)

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from time import monotonic
from typing import Any

from robot_life.common.interaction_intent import intent_for_state

logger = logging.getLogger(__name__)


class InteractionState(Enum):
    """Core interaction states per SDD §3.2."""

    IDLE = auto()
    NOTICED_HUMAN = auto()
    MUTUAL_ATTENTION = auto()
    ENGAGING = auto()
    ONGOING_INTERACTION = auto()
    RECOVERY = auto()
    SAFETY_OVERRIDE = auto()


class InteractionEvent(Enum):
    NOTICE_HUMAN = auto()
    MUTUAL_ATTENTION = auto()
    ENGAGEMENT_BID = auto()
    INTERACTION_STARTED = auto()
    INTERACTION_FINISHED = auto()
    ATTENTION_LOST = auto()
    SAFETY_EVENT = auto()
    SAFETY_RESOLVED = auto()


_ACTIVE_INTERACTION_STATES = {
    InteractionState.NOTICED_HUMAN,
    InteractionState.MUTUAL_ATTENTION,
    InteractionState.ENGAGING,
    InteractionState.ONGOING_INTERACTION,
}


_INTERACTION_TRANSITION_TABLE: dict[InteractionEvent, dict[InteractionState, InteractionState]] = {
    InteractionEvent.NOTICE_HUMAN: {
        InteractionState.IDLE: InteractionState.NOTICED_HUMAN,
        InteractionState.RECOVERY: InteractionState.NOTICED_HUMAN,
        InteractionState.NOTICED_HUMAN: InteractionState.NOTICED_HUMAN,
    },
    InteractionEvent.MUTUAL_ATTENTION: {
        InteractionState.IDLE: InteractionState.MUTUAL_ATTENTION,
        InteractionState.RECOVERY: InteractionState.MUTUAL_ATTENTION,
        InteractionState.NOTICED_HUMAN: InteractionState.MUTUAL_ATTENTION,
        InteractionState.MUTUAL_ATTENTION: InteractionState.MUTUAL_ATTENTION,
    },
    InteractionEvent.ENGAGEMENT_BID: {
        InteractionState.IDLE: InteractionState.ENGAGING,
        InteractionState.RECOVERY: InteractionState.ENGAGING,
        InteractionState.NOTICED_HUMAN: InteractionState.ENGAGING,
        InteractionState.MUTUAL_ATTENTION: InteractionState.ENGAGING,
        InteractionState.ENGAGING: InteractionState.ENGAGING,
    },
    InteractionEvent.INTERACTION_STARTED: {
        InteractionState.IDLE: InteractionState.ONGOING_INTERACTION,
        InteractionState.RECOVERY: InteractionState.ONGOING_INTERACTION,
        InteractionState.NOTICED_HUMAN: InteractionState.ONGOING_INTERACTION,
        InteractionState.MUTUAL_ATTENTION: InteractionState.ONGOING_INTERACTION,
        InteractionState.ENGAGING: InteractionState.ONGOING_INTERACTION,
        InteractionState.ONGOING_INTERACTION: InteractionState.ONGOING_INTERACTION,
    },
    InteractionEvent.INTERACTION_FINISHED: {
        InteractionState.ONGOING_INTERACTION: InteractionState.RECOVERY,
    },
    InteractionEvent.ATTENTION_LOST: {
        InteractionState.NOTICED_HUMAN: InteractionState.RECOVERY,
        InteractionState.MUTUAL_ATTENTION: InteractionState.RECOVERY,
        InteractionState.ENGAGING: InteractionState.RECOVERY,
        InteractionState.ONGOING_INTERACTION: InteractionState.RECOVERY,
    },
    InteractionEvent.SAFETY_EVENT: {
        InteractionState.IDLE: InteractionState.SAFETY_OVERRIDE,
        InteractionState.NOTICED_HUMAN: InteractionState.SAFETY_OVERRIDE,
        InteractionState.MUTUAL_ATTENTION: InteractionState.SAFETY_OVERRIDE,
        InteractionState.ENGAGING: InteractionState.SAFETY_OVERRIDE,
        InteractionState.ONGOING_INTERACTION: InteractionState.SAFETY_OVERRIDE,
        InteractionState.RECOVERY: InteractionState.SAFETY_OVERRIDE,
        InteractionState.SAFETY_OVERRIDE: InteractionState.SAFETY_OVERRIDE,
    },
    InteractionEvent.SAFETY_RESOLVED: {
        InteractionState.SAFETY_OVERRIDE: InteractionState.RECOVERY,
    },
}

_TIMEOUT_TRANSITIONS: dict[InteractionState, tuple[float, InteractionState, str]] = {
    InteractionState.NOTICED_HUMAN: (5.0, InteractionState.IDLE, "noticed_timeout"),
    InteractionState.MUTUAL_ATTENTION: (6.0, InteractionState.RECOVERY, "mutual_attention_timeout"),
    InteractionState.ENGAGING: (8.0, InteractionState.RECOVERY, "engaging_timeout"),
    InteractionState.ONGOING_INTERACTION: (30.0, InteractionState.RECOVERY, "interaction_timeout"),
    InteractionState.RECOVERY: (3.0, InteractionState.IDLE, "recovery_timeout"),
    InteractionState.SAFETY_OVERRIDE: (10.0, InteractionState.RECOVERY, "safety_timeout"),
}


@dataclass(frozen=True)
class TransitionDecision:
    event: str
    source: str
    target: str | None
    allowed: bool


class InteractionStateMachine:
    """Finite state machine governing high-level robot interaction mode.

    The FSM is intentionally lightweight but now uses an explicit transition
    table instead of hard-coded branch logic, making future state growth more
    maintainable and auditable.
    """

    TIMEOUT_NOTICED_S = _TIMEOUT_TRANSITIONS[InteractionState.NOTICED_HUMAN][0]
    TIMEOUT_MUTUAL_ATTENTION_S = _TIMEOUT_TRANSITIONS[InteractionState.MUTUAL_ATTENTION][0]
    TIMEOUT_ENGAGING_S = _TIMEOUT_TRANSITIONS[InteractionState.ENGAGING][0]
    TIMEOUT_ONGOING_S = _TIMEOUT_TRANSITIONS[InteractionState.ONGOING_INTERACTION][0]
    TIMEOUT_RECOVERY_S = _TIMEOUT_TRANSITIONS[InteractionState.RECOVERY][0]
    TIMEOUT_SAFETY_S = _TIMEOUT_TRANSITIONS[InteractionState.SAFETY_OVERRIDE][0]

    def __init__(self) -> None:
        self._state = InteractionState.IDLE
        self._entered_at = monotonic()
        self._transition_count = 0
        self._episode_counter = 0
        self._previous_state: InteractionState | None = None
        self._safety_resume_state: InteractionState | None = None
        self._current_target_id: str | None = None
        self._interaction_episode_id: str | None = None
        self._last_reason: str | None = None

    @property
    def current_state(self) -> InteractionState:
        return self._state

    @property
    def time_in_state_s(self) -> float:
        return monotonic() - self._entered_at

    @property
    def transition_count(self) -> int:
        return self._transition_count

    @property
    def current_target_id(self) -> str | None:
        return self._current_target_id

    @property
    def interaction_episode_id(self) -> str | None:
        return self._interaction_episode_id

    @property
    def current_intent(self) -> str:
        return intent_for_state(self._state.name)

    @property
    def transition_table(self) -> dict[str, dict[str, str]]:
        return {
            event.name: {state.name: target.name for state, target in transitions.items()}
            for event, transitions in _INTERACTION_TRANSITION_TABLE.items()
        }

    def can_apply(self, event: InteractionEvent) -> bool:
        return self._state in _INTERACTION_TRANSITION_TABLE.get(event, {})

    def on_notice_human(self, *, target_id: str | None = None, reason: str = "notice_human") -> InteractionState:
        return self._apply_event(InteractionEvent.NOTICE_HUMAN, target_id=target_id, reason=reason)

    def on_mutual_attention(
        self,
        *,
        target_id: str | None = None,
        reason: str = "mutual_attention",
    ) -> InteractionState:
        return self._apply_event(InteractionEvent.MUTUAL_ATTENTION, target_id=target_id, reason=reason)

    def on_engagement_bid(
        self,
        *,
        target_id: str | None = None,
        reason: str = "engagement_bid",
    ) -> InteractionState:
        return self._apply_event(InteractionEvent.ENGAGEMENT_BID, target_id=target_id, reason=reason)

    def on_interaction_started(
        self,
        *,
        target_id: str | None = None,
        reason: str = "interaction_started",
    ) -> InteractionState:
        if self._state == InteractionState.SAFETY_OVERRIDE:
            return self._state
        return self._apply_event(InteractionEvent.INTERACTION_STARTED, target_id=target_id, reason=reason)

    def on_interaction_finished(self, *, reason: str = "interaction_finished") -> InteractionState:
        return self._apply_event(
            InteractionEvent.INTERACTION_FINISHED,
            target_id=self._current_target_id,
            reason=reason,
        )

    def on_attention_lost(
        self,
        *,
        target_id: str | None = None,
        reason: str = "attention_lost",
    ) -> InteractionState:
        return self._apply_event(
            InteractionEvent.ATTENTION_LOST,
            target_id=target_id or self._current_target_id,
            reason=reason,
        )

    def on_weak_signal(self, *, target_id: str | None = None, reason: str = "weak_signal") -> InteractionState:
        return self.on_notice_human(target_id=target_id, reason=reason)

    def on_confirmed_engagement(
        self,
        *,
        target_id: str | None = None,
        reason: str = "confirmed_engagement",
    ) -> InteractionState:
        return self.on_engagement_bid(target_id=target_id, reason=reason)

    def on_disengage(self, *, target_id: str | None = None, reason: str = "disengage") -> InteractionState:
        return self.on_attention_lost(target_id=target_id, reason=reason)

    def on_safety_event(self, *, reason: str = "safety_event") -> InteractionState:
        if self._state != InteractionState.SAFETY_OVERRIDE:
            self._previous_state = self._state
            self._safety_resume_state = self._state
        return self._apply_event(InteractionEvent.SAFETY_EVENT, target_id=self._current_target_id, reason=reason)

    def on_safety_resolved(self, *, reason: str = "safety_resolved") -> InteractionState:
        if self._state == InteractionState.SAFETY_OVERRIDE:
            target_state = self._safety_resume_state or self._previous_state or InteractionState.RECOVERY
            if target_state == InteractionState.SAFETY_OVERRIDE:
                target_state = InteractionState.RECOVERY
            target_id = self._current_target_id if target_state != InteractionState.IDLE else None
            self._transition(target_state, target_id=target_id, reason=reason)
            self._safety_resume_state = None
            return self._state
        return self._apply_event(InteractionEvent.SAFETY_RESOLVED, target_id=self._current_target_id, reason=reason)

    def transition_decision(self, event: InteractionEvent) -> TransitionDecision:
        if event == InteractionEvent.SAFETY_RESOLVED and self._state == InteractionState.SAFETY_OVERRIDE:
            target = self._safety_resume_state or self._previous_state or InteractionState.RECOVERY
            if target == InteractionState.SAFETY_OVERRIDE:
                target = InteractionState.RECOVERY
        else:
            target = _INTERACTION_TRANSITION_TABLE.get(event, {}).get(self._state)
        return TransitionDecision(
            event=event.name,
            source=self._state.name,
            target=target.name if target is not None else None,
            allowed=target is not None,
        )

    def tick(self) -> InteractionState:
        timeout_rule = _TIMEOUT_TRANSITIONS.get(self._state)
        if timeout_rule is None:
            return self._state
        timeout_s, target_state, reason = timeout_rule
        if self.time_in_state_s > timeout_s:
            target_id = self._current_target_id if target_state != InteractionState.IDLE else None
            self._transition(target_state, target_id=target_id, reason=reason)
        return self._state

    def reset(self) -> None:
        self._state = InteractionState.IDLE
        self._entered_at = monotonic()
        self._transition_count = 0
        self._episode_counter = 0
        self._previous_state = None
        self._safety_resume_state = None
        self._current_target_id = None
        self._interaction_episode_id = None
        self._last_reason = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._state.name,
            "time_in_state_s": round(self.time_in_state_s, 2),
            "transition_count": self._transition_count,
            "previous_state": self._previous_state.name if self._previous_state else None,
            "safety_resume_state": self._safety_resume_state.name if self._safety_resume_state else None,
            "target_id": self._current_target_id,
            "episode_id": self._interaction_episode_id,
            "intent": self.current_intent,
            "last_reason": self._last_reason,
        }

    def _apply_event(
        self,
        event: InteractionEvent,
        *,
        target_id: str | None,
        reason: str,
    ) -> InteractionState:
        next_state = _INTERACTION_TRANSITION_TABLE.get(event, {}).get(self._state)
        if next_state is None:
            return self._state
        self._transition(next_state, target_id=target_id, reason=reason)
        return self._state

    def _refresh(self, *, target_id: str | None, reason: str) -> None:
        if target_id:
            self._current_target_id = target_id
        self._entered_at = monotonic()
        self._last_reason = reason

    def _transition(
        self,
        new_state: InteractionState,
        *,
        target_id: str | None,
        reason: str,
    ) -> None:
        old = self._state
        if old == new_state:
            self._refresh(target_id=target_id, reason=reason)
            return
        self._previous_state = old
        self._state = new_state
        self._entered_at = monotonic()
        self._transition_count += 1
        if new_state in _ACTIVE_INTERACTION_STATES and old in {InteractionState.IDLE, InteractionState.RECOVERY}:
            self._episode_counter += 1
            self._interaction_episode_id = f"episode-{self._episode_counter}"
        elif new_state == InteractionState.IDLE:
            self._interaction_episode_id = None
        self._current_target_id = target_id
        self._last_reason = reason
        logger.debug(
            "state_machine: %s → %s (transition #%d, target=%s, reason=%s)",
            old.name,
            new_state.name,
            self._transition_count,
            self._current_target_id,
            self._last_reason,
        )
