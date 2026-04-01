from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from robot_life.common.payload_contracts import SlowTaskMetadata
from robot_life.common.schemas import SceneCandidate


@dataclass
class _PendingTask:
    scene: SceneCandidate
    submitted_at: float
    timeout_ms: int


class LongTaskCoordinator:
    """Generic coordinator for long-running scene/task services.

    The service can be slow-scene today and another long-running perception
    or world-model task tomorrow. LiveLoop only interacts with this adapter.
    """

    def __init__(self, *, stale_timeout_factor: float = 2.0) -> None:
        self._pending: dict[str, _PendingTask] = {}
        self._last_submit_at = 0.0
        self._last_submit_at_by_target: dict[str, float] = {}
        self._stale_timeout_factor = max(1.0, float(stale_timeout_factor))
        self._stale_dropped = 0

    def submit_or_query(
        self,
        service: Any,
        scene: Any,
        collected: Any,
        *,
        decision_mode: Any | None = None,
        arbitration_outcome: str | None = None,
    ) -> Any | None:
        task_metadata = SlowTaskMetadata.from_scene_and_collected(
            scene,
            collected,
            decision_mode=decision_mode,
            arbitration_outcome=arbitration_outcome,
        )
        sample_interval_s = float(getattr(service, "sample_interval_s", 1.0))
        target_key = getattr(scene, "target_id", None) or getattr(scene, "scene_type", "__global__")
        last_submit_at = self._last_submit_at_by_target.get(target_key, 0.0)
        if sample_interval_s > 0 and (monotonic() - last_submit_at) < sample_interval_s:
            return None

        should_trigger = getattr(scene, "score_hint", 0.0) < 0.8
        if hasattr(service, "should_trigger"):
            should_trigger = service.should_trigger(
                scene,
                decision_mode=decision_mode,
                arbitration_outcome=arbitration_outcome,
            )

        force_sample = bool(getattr(service, "force_sample", True))
        if not should_trigger and not force_sample:
            return None

        task_metadata_dict = task_metadata.to_dict()
        camera_packet = collected.packets.get("camera")
        if camera_packet is not None and hasattr(service, "capture_frame"):
            service.capture_frame(
                camera_packet.payload,
                source="camera",
                metadata=task_metadata_dict,
            )

        timeout_ms = int(getattr(service, "request_timeout_ms", 5_000))
        image = camera_packet.payload if camera_packet is not None else None

        request_id = self._submit_request(
            service,
            scene,
            image=image,
            timeout_ms=timeout_ms,
            metadata=task_metadata_dict,
        )
        if request_id is not None:
            request_state = service.get_request_state(request_id) if hasattr(service, "get_request_state") else None
            if request_state in {None, "PENDING", "RUNNING"}:
                self._pending[request_id] = _PendingTask(
                    scene=scene,
                    submitted_at=monotonic(),
                    timeout_ms=timeout_ms,
                )
            submitted_at = monotonic()
            self._last_submit_at = submitted_at
            self._last_submit_at_by_target[target_key] = submitted_at
            return None

        if hasattr(service, "build_scene_json"):
            submitted_at = monotonic()
            self._last_submit_at = submitted_at
            self._last_submit_at_by_target[target_key] = submitted_at
            return service.build_scene_json(scene, image=image)

        return None

    def drain_ready_results(self, service: Any) -> list[tuple[SceneCandidate, Any]]:
        if not hasattr(service, "query"):
            return []

        ready: list[tuple[SceneCandidate, Any]] = []
        for request_id, pending in list(self._pending.items()):
            slow_result = service.query(request_id=request_id)
            if slow_result is None:
                if self._is_stale(request_id, pending, service):
                    self._drop_stale_request(request_id, service)
                    continue
                if hasattr(service, "get_request_state"):
                    state = service.get_request_state(request_id)
                    if state not in {None, "PENDING", "RUNNING"}:
                        self._pending.pop(request_id, None)
                continue

            status = getattr(slow_result, "status", None)
            status_value = status.value if hasattr(status, "value") else str(status)
            if status_value in {"PENDING", "RUNNING"}:
                if self._is_stale(request_id, pending, service):
                    self._drop_stale_request(request_id, service)
                continue

            self._pending.pop(request_id, None)
            ready.append((pending.scene, slow_result.scene_json))
        return ready

    def snapshot(self) -> dict[str, Any]:
        ages_ms = [max(0.0, (monotonic() - item.submitted_at) * 1000.0) for item in self._pending.values()]
        return {
            "pending_count": len(self._pending),
            "stale_dropped": self._stale_dropped,
            "oldest_pending_ms": round(max(ages_ms), 3) if ages_ms else None,
        }

    @property
    def stale_dropped(self) -> int:
        return self._stale_dropped

    def _is_stale(self, request_id: str, pending: _PendingTask, service: Any) -> bool:
        timeout_ms = max(1, int(pending.timeout_ms * self._stale_timeout_factor))
        age_ms = (monotonic() - pending.submitted_at) * 1000.0
        return age_ms > timeout_ms

    def _drop_stale_request(self, request_id: str, service: Any) -> None:
        self._pending.pop(request_id, None)
        self._stale_dropped += 1
        cancel = getattr(service, "cancel", None)
        if callable(cancel):
            try:
                cancel(request_id)
            except Exception:
                return

    @staticmethod
    def _submit_request(
        service: Any,
        scene: Any,
        *,
        image: Any | None,
        timeout_ms: int,
        metadata: dict[str, Any] | None,
    ) -> str | None:
        if hasattr(service, "submit"):
            return service.submit(scene, image=image, timeout_ms=timeout_ms, metadata=metadata)
        if hasattr(service, "submit_scene"):
            request_id = service.submit_scene(scene, image=image, timeout_ms=timeout_ms, metadata=metadata)
            return request_id if isinstance(request_id, str) else None
        return None
