from __future__ import annotations

import logging
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any

from robot_life.common.schemas import SceneJson
from robot_life.slow_scene.queue import SlowSceneQueue
from robot_life.slow_scene.schema import (
    SlowSceneHealth,
    SlowSceneRequest,
    SlowSceneResult,
    SlowSceneStatus,
)
from robot_life.slow_scene.snapshot import SlowSceneSnapshotBuffer


class SlowSceneWorker:
    """Background consumer for slow-scene requests."""

    def __init__(
        self,
        *,
        queue: SlowSceneQueue | None = None,
        snapshot: SlowSceneSnapshotBuffer | None = None,
        adapter: Any | None = None,
        max_results: int = 256,
        state_ttl_s: float = 900.0,
        max_latency_samples: int = 512,
    ):
        self._queue = queue if queue is not None else SlowSceneQueue()
        self._snapshot = snapshot if snapshot is not None else SlowSceneSnapshotBuffer()
        self._adapter = adapter
        self._logger = logging.getLogger(__name__)
        self.max_results = max(1, int(max_results))
        self.state_ttl_s = max(0.0, float(state_ttl_s))
        self.max_latency_samples = max(1, int(max_latency_samples))
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._results: dict[str, SlowSceneResult] = {}
        self._latest_by_scene: dict[str, str] = {}
        self._request_state: dict[str, SlowSceneStatus] = {}
        self._cancelled: dict[str, float] = {}
        self._last_error: str | None = None
        self._latencies_ms: list[float] = []
        self._latency_sampled_at: list[float] = []
        self._request_state_updated_at: dict[str, float] = {}
        self._result_stored_at: dict[str, float] = {}
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread = Thread(target=self._run, name="slow-scene-worker", daemon=True)
            self._thread.start()

    def submit(self, request: SlowSceneRequest) -> str:
        self.start()
        accepted = self._queue.put(request)
        with self._lock:
            now = monotonic()
            self._request_state[request.request_id] = SlowSceneStatus.PENDING
            self._request_state_updated_at[request.request_id] = now
            if not accepted:
                self._request_state[request.request_id] = SlowSceneStatus.DROPPED
                self._request_state_updated_at[request.request_id] = now
                self._last_error = "request dropped by bounded queue"
            self._prune_locked(now)
        return request.request_id

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            now = monotonic()
            self._cancelled[request_id] = now
            state = self._request_state.get(request_id)
            if state in {
                SlowSceneStatus.COMPLETED,
                SlowSceneStatus.FAILED,
                SlowSceneStatus.TIMED_OUT,
                SlowSceneStatus.CANCELLED,
                SlowSceneStatus.DROPPED,
            }:
                self._prune_locked(now)
                return False
            self._request_state[request_id] = SlowSceneStatus.CANCELLED
            self._request_state_updated_at[request_id] = now
            self._prune_locked(now)
        return True

    def query(self, request_id: str | None = None, scene_id: str | None = None) -> SlowSceneResult | None:
        with self._lock:
            self._prune_locked()
            if request_id is not None:
                return self._results.get(request_id)
            if scene_id is not None:
                latest_request_id = self._latest_by_scene.get(scene_id)
                if latest_request_id is None:
                    return None
                return self._results.get(latest_request_id)
            if self._results:
                latest_request_id = next(reversed(self._results))
                return self._results[latest_request_id]
        return None

    def get_request_state(self, request_id: str) -> SlowSceneStatus | None:
        with self._lock:
            self._prune_locked()
            return self._request_state.get(request_id)

    def health(self) -> SlowSceneHealth:
        with self._lock:
            self._prune_locked()
            worker_alive = bool(self._thread and self._thread.is_alive())
            queue_depth = len(self._queue)
            average_latency = sum(self._latencies_ms) / len(self._latencies_ms) if self._latencies_ms else 0.0
            adapter_ready = self._is_adapter_ready()
            return SlowSceneHealth(
                ready=self._started,
                worker_alive=worker_alive,
                queue_depth=queue_depth,
                queue_capacity=self._queue.maxsize,
                pending_requests=sum(1 for state in self._request_state.values() if state == SlowSceneStatus.PENDING),
                completed_requests=sum(1 for state in self._request_state.values() if state == SlowSceneStatus.COMPLETED),
                dropped_requests=sum(1 for state in self._request_state.values() if state == SlowSceneStatus.DROPPED),
                cancelled_requests=sum(1 for state in self._request_state.values() if state == SlowSceneStatus.CANCELLED),
                timed_out_requests=sum(1 for state in self._request_state.values() if state == SlowSceneStatus.TIMED_OUT),
                adapter_ready=adapter_ready,
                last_error=self._last_error,
                last_request_id=next(reversed(self._request_state)) if self._request_state else None,
                last_result_id=next(reversed(self._results)) if self._results else None,
                last_scene_id=next(reversed(self._latest_by_scene)) if self._latest_by_scene else None,
                average_latency_ms=average_latency,
                degraded_mode=not adapter_ready,
            )

    def stop(self, *, join: bool = True, timeout: float | None = 1.0) -> None:
        self._stop_event.set()
        self._queue.close()
        if join and self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        self._ensure_adapter()
        while not self._stop_event.is_set():
            request = self._queue.get(timeout=0.2)
            if request is None:
                continue
            self._process_request(request)

    def _process_request(self, request: SlowSceneRequest) -> None:
        start = monotonic()
        if request.request_id in self._cancelled:
            self._store_cancelled(request)
            return

        with self._lock:
            self._request_state[request.request_id] = SlowSceneStatus.RUNNING

        try:
            scene_json = self._infer_scene(request)
            end = monotonic()
            timeout_flag = end > request.deadline_mono
            status = SlowSceneStatus.TIMED_OUT if timeout_flag else SlowSceneStatus.COMPLETED
            if timeout_flag:
                scene_json = self._fallback_scene_json(request)

            result = SlowSceneResult.from_request(
                request,
                scene_json,
                status=status,
                started_at=start,
                ended_at=end,
                timeout_flag=timeout_flag,
                error_code="timeout" if timeout_flag else None,
                error_message="request exceeded deadline" if timeout_flag else None,
            )
            self._store_result(result)
        except Exception as exc:  # pragma: no cover - defensive fallback path
            self._last_error = str(exc)
            end = monotonic()
            result = SlowSceneResult.from_request(
                request,
                self._fallback_scene_json(request),
                status=SlowSceneStatus.FAILED,
                started_at=start,
                ended_at=end,
                timeout_flag=False,
                error_code="worker_error",
                error_message=str(exc),
            )
            self._store_result(result)

    def _infer_scene(self, request: SlowSceneRequest) -> SceneJson:
        if request.request_id in self._cancelled:
            return self._fallback_scene_json(request)

        adapter = self._adapter
        image = request.image
        context = request.context
        if adapter is None:
            return self._fallback_scene_json(request)

        if hasattr(adapter, "initialize") and not self._is_adapter_ready():
            adapter.initialize()

        if image is None:
            latest = self._snapshot.latest_frame()
            image = latest.frame if latest else None
            if latest is not None and not request.frame_ids:
                request.frame_ids = [latest.frame_id]

        if image is None:
            return self._fallback_scene_json(request)

        if hasattr(adapter, "understand_scene"):
            return adapter.understand_scene(image, context, timeout_ms=request.timeout_ms)

        return self._fallback_scene_json(request)

    def _ensure_adapter(self) -> None:
        adapter = self._adapter
        if adapter is None:
            return
        if self._is_adapter_ready():
            return
        if hasattr(adapter, "initialize"):
            try:
                adapter.initialize()
            except Exception as exc:  # pragma: no cover - adapter fallback path
                self._last_error = str(exc)
                self._logger.warning("Slow scene adapter initialization failed: %s", exc)

    def _store_result(self, result: SlowSceneResult) -> None:
        with self._lock:
            now = monotonic()
            self._results[result.request_id] = result
            self._result_stored_at[result.request_id] = now
            self._latest_by_scene[result.scene_id] = result.request_id
            self._request_state[result.request_id] = result.status
            self._request_state_updated_at[result.request_id] = now
            self._latencies_ms.append(result.model_latency_ms)
            self._latency_sampled_at.append(now)
            self._last_error = result.error_message
            self._prune_locked(now)

    def _store_cancelled(self, request: SlowSceneRequest) -> None:
        with self._lock:
            now = monotonic()
            self._request_state[request.request_id] = SlowSceneStatus.CANCELLED
            self._request_state_updated_at[request.request_id] = now
            self._cancelled[request.request_id] = now
            self._prune_locked(now)

    def _fallback_scene_json(self, request: SlowSceneRequest) -> SceneJson:
        scene_type = request.scene.scene_type
        scene_config = {
            "greeting_scene": {
                "emotion_hint": "happy_attention",
                "urgency_hint": "medium",
                "recommended_strategy": "verbal_greeting",
                "escalate": request.scene.score_hint >= 0.8,
            },
            "attention_scene": {
                "emotion_hint": "curious",
                "urgency_hint": "low",
                "recommended_strategy": "nonverbal_first",
                "escalate": request.scene.score_hint >= 0.75,
            },
            "safety_alert_scene": {
                "emotion_hint": "alert",
                "urgency_hint": "high",
                "recommended_strategy": "immediate_action",
                "escalate": True,
            },
            "gesture_bond_scene": {
                "emotion_hint": "happy",
                "urgency_hint": "medium",
                "recommended_strategy": "gesture_response",
                "escalate": request.scene.score_hint >= 0.8,
            },
            "ambient_tracking_scene": {
                "emotion_hint": "neutral",
                "urgency_hint": "low",
                "recommended_strategy": "passive_monitoring",
                "escalate": False,
            },
        }

        config = scene_config.get(scene_type, scene_config["ambient_tracking_scene"])
        involved_targets = [request.scene.target_id] if request.scene.target_id else []
        return SceneJson(
            scene_type=scene_type,
            confidence=request.scene.score_hint,
            involved_targets=involved_targets,
            emotion_hint=config["emotion_hint"],
            urgency_hint=config["urgency_hint"],
            recommended_strategy=config["recommended_strategy"],
            escalate_to_cloud=config["escalate"],
        )

    def _is_adapter_ready(self) -> bool:
        adapter = self._adapter
        if adapter is None:
            return False
        if hasattr(adapter, "is_ready"):
            try:
                return bool(adapter.is_ready())
            except Exception:
                return False
        model = getattr(adapter, "_model", None)
        processor = getattr(adapter, "_processor", None)
        initialized = getattr(adapter, "_initialized", None)
        if initialized is not None:
            return bool(initialized)
        return model is not None and processor is not None

    def _prune_locked(self, now: float | None = None) -> None:
        current = monotonic() if now is None else now
        self._prune_terminal_state_locked(current)
        self._prune_results_locked(current)
        self._prune_cancelled_locked(current)
        self._prune_latency_samples_locked(current)

    def _prune_terminal_state_locked(self, now: float) -> None:
        ttl = self.state_ttl_s
        if ttl > 0:
            expired_request_ids = [
                request_id
                for request_id, state in self._request_state.items()
                if state in {
                    SlowSceneStatus.COMPLETED,
                    SlowSceneStatus.FAILED,
                    SlowSceneStatus.TIMED_OUT,
                    SlowSceneStatus.CANCELLED,
                    SlowSceneStatus.DROPPED,
                }
                and (now - self._request_state_updated_at.get(request_id, now)) > ttl
            ]
            for request_id in expired_request_ids:
                self._drop_request_state_locked(request_id)

        removable_request_ids = [
            request_id
            for request_id, state in self._request_state.items()
            if state in {
                SlowSceneStatus.COMPLETED,
                SlowSceneStatus.FAILED,
                SlowSceneStatus.TIMED_OUT,
                SlowSceneStatus.CANCELLED,
                SlowSceneStatus.DROPPED,
            }
        ]
        excess = len(self._request_state) - self.max_results
        if excess <= 0:
            return

        removable_request_ids.sort(key=lambda request_id: self._request_state_updated_at.get(request_id, 0.0))
        for request_id in removable_request_ids[:excess]:
            self._drop_request_state_locked(request_id)

    def _prune_results_locked(self, now: float) -> None:
        ttl = self.state_ttl_s
        if ttl > 0:
            expired_result_ids = [
                request_id
                for request_id, result in self._results.items()
                if (now - self._result_stored_at.get(request_id, result.ended_at)) > ttl
            ]
            for request_id in expired_result_ids:
                self._drop_result_locked(request_id)

        excess = len(self._results) - self.max_results
        if excess <= 0:
            self._rebuild_latest_scene_index_locked()
            return

        ordered_result_ids = list(self._results.keys())
        for request_id in ordered_result_ids[:excess]:
            self._drop_result_locked(request_id)
        self._rebuild_latest_scene_index_locked()

    def _prune_cancelled_locked(self, now: float) -> None:
        ttl = self.state_ttl_s
        if ttl > 0:
            expired_request_ids = [
                request_id
                for request_id, seen_at in self._cancelled.items()
                if (now - seen_at) > ttl
            ]
            for request_id in expired_request_ids:
                self._cancelled.pop(request_id, None)

        excess = len(self._cancelled) - self.max_results
        if excess <= 0:
            return

        ordered_request_ids = sorted(self._cancelled.items(), key=lambda item: item[1])
        for request_id, _seen_at in ordered_request_ids[:excess]:
            self._cancelled.pop(request_id, None)

    def _prune_latency_samples_locked(self, now: float) -> None:
        ttl = self.state_ttl_s
        if ttl > 0 and self._latency_sampled_at:
            expired_indexes = [
                index
                for index, sampled_at in enumerate(self._latency_sampled_at)
                if (now - sampled_at) > ttl
            ]
            if expired_indexes:
                keep_latencies: list[float] = []
                keep_sampled_at: list[float] = []
                expired = set(expired_indexes)
                for index, (latency, sampled_at) in enumerate(zip(self._latencies_ms, self._latency_sampled_at)):
                    if index in expired:
                        continue
                    keep_latencies.append(latency)
                    keep_sampled_at.append(sampled_at)
                self._latencies_ms = keep_latencies
                self._latency_sampled_at = keep_sampled_at

        excess = len(self._latencies_ms) - self.max_latency_samples
        if excess > 0:
            del self._latencies_ms[:excess]
            del self._latency_sampled_at[:excess]

    def _drop_result_locked(self, request_id: str) -> None:
        result = self._results.pop(request_id, None)
        self._result_stored_at.pop(request_id, None)
        self._request_state.pop(request_id, None)
        self._request_state_updated_at.pop(request_id, None)
        self._cancelled.pop(request_id, None)
        if result is not None and self._latest_by_scene.get(result.scene_id) == request_id:
            self._latest_by_scene.pop(result.scene_id, None)

    def _drop_request_state_locked(self, request_id: str) -> None:
        self._request_state.pop(request_id, None)
        self._request_state_updated_at.pop(request_id, None)
        self._cancelled.pop(request_id, None)

    def _rebuild_latest_scene_index_locked(self) -> None:
        rebuilt: dict[str, str] = {}
        for request_id, result in self._results.items():
            rebuilt[result.scene_id] = request_id
        self._latest_by_scene = rebuilt
