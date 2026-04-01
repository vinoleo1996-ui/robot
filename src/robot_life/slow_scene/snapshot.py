from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from time import monotonic
from typing import Any
from uuid import uuid4

from robot_life.common.schemas import EventPriority, SceneCandidate
from robot_life.slow_scene.schema import SlowSceneRequest


@dataclass
class FrameSample:
    frame_id: str
    source: str
    captured_at: float
    frame: Any
    metadata: dict[str, Any] = field(default_factory=dict)


class SlowSceneSnapshotBuffer:
    """Ring buffer for recent frames and lightweight scene context."""

    def __init__(self, max_frames: int = 8, max_age_seconds: float = 3.0):
        self._max_frames = max(1, max_frames)
        self._max_age_seconds = max_age_seconds
        self._frames: deque[FrameSample] = deque(maxlen=self._max_frames)

    def capture_frame(
        self,
        frame: Any,
        *,
        source: str = "camera",
        frame_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        captured_at: float | None = None,
    ) -> str:
        sample = FrameSample(
            frame_id=frame_id or f"frame_{uuid4()}",
            source=source,
            captured_at=captured_at if captured_at is not None else monotonic(),
            frame=frame,
            metadata=dict(metadata or {}),
        )
        self._frames.append(sample)
        self._purge_stale()
        return sample.frame_id

    def latest_frame(self) -> FrameSample | None:
        self._purge_stale()
        if not self._frames:
            return None
        return self._frames[-1]

    def recent_frames(self, limit: int = 3) -> list[FrameSample]:
        self._purge_stale()
        if limit <= 0:
            return []
        return list(self._frames)[-limit:]

    def build_context(
        self,
        scene: SceneCandidate,
        *,
        extra_context: str | None = None,
        recent_events: list[dict[str, Any]] | None = None,
    ) -> str:
        frame_ids = [sample.frame_id for sample in self.recent_frames()]
        chunks = [
            f"scene_type={scene.scene_type}",
            f"scene_score={scene.score_hint:.3f}",
            f"scene_id={scene.scene_id}",
        ]
        if scene.target_id:
            chunks.append(f"target_id={scene.target_id}")
        if frame_ids:
            chunks.append(f"frame_ids={','.join(frame_ids)}")
        if recent_events:
            chunks.append(f"recent_events={recent_events}")
        if extra_context:
            chunks.append(f"context={extra_context}")
        return " | ".join(chunks)

    def build_request(
        self,
        scene: SceneCandidate,
        *,
        priority: EventPriority = EventPriority.P2,
        timeout_ms: int = 5_000,
        dedup_bucket_s: float = 2.0,
        image: Any | None = None,
        context: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SlowSceneRequest:
        latest = self.latest_frame()
        frame_ids = [sample.frame_id for sample in self.recent_frames()]
        resolved_image = image if image is not None else (latest.frame if latest else None)
        resolved_context = context or self.build_context(scene)
        return SlowSceneRequest.from_scene(
            scene,
            priority=priority,
            timeout_ms=timeout_ms,
            dedup_bucket_s=dedup_bucket_s,
            image=resolved_image,
            context=resolved_context,
            frame_ids=frame_ids,
            metadata=metadata,
        )

    def _purge_stale(self) -> None:
        if self._max_age_seconds <= 0:
            return
        threshold = monotonic() - self._max_age_seconds
        while self._frames and self._frames[0].captured_at < threshold:
            self._frames.popleft()
