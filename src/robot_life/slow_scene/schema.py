from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from math import floor
from time import monotonic, time
from typing import Any
from uuid import uuid4

from robot_life.common.schemas import EventPriority, SceneCandidate, SceneJson


class SlowSceneStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    DROPPED = "DROPPED"


def build_slow_scene_dedup_key(
    scene: SceneCandidate,
    *,
    bucket_seconds: float = 2.0,
    at_monotonic: float | None = None,
) -> str:
    """Build a stable dedup key for slow-scene requests.

    The key intentionally favors target + scene type so repeated updates for the
    same target collapse, even when scene_id changes on every frame.
    A time bucket is included so stale old events do not permanently collapse
    future requests.
    """
    target_key = (
        scene.target_id.strip()
        if isinstance(scene.target_id, str) and scene.target_id.strip()
        else "__global__"
    )
    resolved_bucket_seconds = max(0.25, float(bucket_seconds))
    current_mono = at_monotonic if at_monotonic is not None else monotonic()
    bucket_index = int(floor(current_mono / resolved_bucket_seconds))
    return f"target_id={target_key}|scene_type={scene.scene_type}|bucket={bucket_index}"


@dataclass
class SlowSceneRequest:
    request_id: str
    trace_id: str
    scene_id: str
    scene_type: str
    target_id: str | None
    priority: EventPriority
    submitted_at: float
    deadline_mono: float
    timeout_ms: int
    dedup_key: str
    scene: SceneCandidate
    image: Any | None = None
    context: str | None = None
    frame_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_scene(
        cls,
        scene: SceneCandidate,
        *,
        priority: EventPriority = EventPriority.P2,
        timeout_ms: int = 5_000,
        dedup_bucket_s: float = 2.0,
        dedup_at_monotonic: float | None = None,
        image: Any | None = None,
        context: str | None = None,
        frame_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> "SlowSceneRequest":
        now = monotonic()
        return cls(
            request_id=request_id or f"slow_{uuid4()}",
            trace_id=scene.trace_id,
            scene_id=scene.scene_id,
            scene_type=scene.scene_type,
            target_id=scene.target_id,
            priority=priority,
            submitted_at=time(),
            deadline_mono=now + (timeout_ms / 1000.0),
            timeout_ms=timeout_ms,
            dedup_key=build_slow_scene_dedup_key(
                scene,
                bucket_seconds=dedup_bucket_s,
                at_monotonic=dedup_at_monotonic,
            ),
            scene=scene,
            image=image,
            context=context,
            frame_ids=list(frame_ids or []),
            metadata=dict(metadata or {}),
        )


@dataclass
class SlowSceneResult:
    request_id: str
    trace_id: str
    scene_id: str
    scene_type: str
    target_id: str | None
    status: SlowSceneStatus
    scene_json: SceneJson
    submitted_at: float
    started_at: float
    ended_at: float
    model_latency_ms: float
    timeout_flag: bool
    error_code: str | None = None
    error_message: str | None = None
    frame_ids: list[str] = field(default_factory=list)
    source: str = "slow_scene"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_request(
        cls,
        request: SlowSceneRequest,
        scene_json: SceneJson,
        *,
        status: SlowSceneStatus,
        started_at: float,
        ended_at: float,
        timeout_flag: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> "SlowSceneResult":
        return cls(
            request_id=request.request_id,
            trace_id=request.trace_id,
            scene_id=request.scene_id,
            scene_type=request.scene_type,
            target_id=request.target_id,
            status=status,
            scene_json=scene_json,
            submitted_at=request.submitted_at,
            started_at=started_at,
            ended_at=ended_at,
            model_latency_ms=max(0.0, (ended_at - started_at) * 1000),
            timeout_flag=timeout_flag,
            error_code=error_code,
            error_message=error_message,
            frame_ids=list(request.frame_ids),
            metadata=dict(request.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass
class SlowSceneHealth:
    ready: bool
    worker_alive: bool
    queue_depth: int
    queue_capacity: int
    pending_requests: int
    completed_requests: int
    dropped_requests: int
    cancelled_requests: int
    timed_out_requests: int
    adapter_ready: bool
    last_error: str | None = None
    last_request_id: str | None = None
    last_result_id: str | None = None
    last_scene_id: str | None = None
    average_latency_ms: float = 0.0
    degraded_mode: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return payload
