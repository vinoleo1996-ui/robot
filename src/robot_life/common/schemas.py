from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic, time
from uuid import uuid4

from robot_life.common.tracing import new_trace_id


class EventPriority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class DecisionMode(str, Enum):
    EXECUTE = "EXECUTE"
    SOFT_INTERRUPT = "SOFT_INTERRUPT"
    HARD_INTERRUPT = "HARD_INTERRUPT"
    DEGRADE_AND_EXECUTE = "DEGRADE_AND_EXECUTE"
    QUEUE = "QUEUE"
    DROP = "DROP"


@dataclass
class DetectionResult:
    trace_id: str
    source: str
    detector: str
    event_type: str
    timestamp: float
    confidence: float
    payload: dict = field(default_factory=dict)

    @classmethod
    def synthetic(
        cls,
        detector: str,
        event_type: str,
        confidence: float,
        payload: dict | None = None,
    ) -> "DetectionResult":
        return cls(
            trace_id=new_trace_id(),
            source="synthetic",
            detector=detector,
            event_type=event_type,
            timestamp=time(),
            confidence=confidence,
            payload=payload or {},
        )


@dataclass
class RawEvent:
    event_id: str
    trace_id: str
    event_type: str
    priority: EventPriority
    timestamp_monotonic: float
    confidence: float
    source: str
    ttl_ms: int
    cooldown_key: str
    payload: dict = field(default_factory=dict)


@dataclass
class StableEvent:
    stable_event_id: str
    base_event_id: str
    trace_id: str
    event_type: str
    priority: EventPriority
    valid_until_monotonic: float
    stabilized_by: list[str]
    payload: dict = field(default_factory=dict)


@dataclass
class SceneCandidate:
    scene_id: str
    trace_id: str
    scene_type: str
    based_on_events: list[str]
    score_hint: float
    valid_until_monotonic: float
    target_id: str | None = None
    interaction_episode_id: str | None = None
    scene_epoch: str | None = None
    primary_target_id: str | None = None
    related_entity_ids: list[str] = field(default_factory=list)
    payload: dict = field(default_factory=dict)


@dataclass
class ArbitrationResult:
    decision_id: str
    trace_id: str
    target_behavior: str
    priority: EventPriority
    mode: DecisionMode
    required_resources: list[str]
    optional_resources: list[str]
    degraded_behavior: str | None
    resume_previous: bool
    reason: str
    target_id: str | None = None
    scene_type: str | None = None
    engagement_score: float | None = None
    scene_path: str | None = None
    interaction_state: str | None = None
    interaction_episode_id: str | None = None
    scene_epoch: str | None = None
    decision_epoch: str | None = None


@dataclass
class ResourceGrant:
    grant_id: str
    trace_id: str
    decision_id: str
    granted: bool
    granted_resources: list[str]
    denied_resources: list[str]
    reason: str


@dataclass
class ExecutionResult:
    execution_id: str
    trace_id: str
    behavior_id: str
    status: str
    interrupted: bool
    degraded: bool
    started_at: float
    ended_at: float
    target_id: str | None = None
    scene_type: str | None = None
    engagement_score: float | None = None
    scene_path: str | None = None
    interaction_state: str | None = None
    interaction_episode_id: str | None = None
    scene_epoch: str | None = None
    decision_epoch: str | None = None


@dataclass
class DecisionQueueItem:
    queue_id: str
    enqueued_at_monotonic: float
    valid_until_monotonic: float
    decision: ArbitrationResult


@dataclass
class SceneJson:
    scene_type: str
    confidence: float
    involved_targets: list[str]
    emotion_hint: str
    urgency_hint: str
    recommended_strategy: str
    escalate_to_cloud: bool


def new_id() -> str:
    return str(uuid4())


def now_mono() -> float:
    return monotonic()
