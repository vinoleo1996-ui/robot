"""Slow thinking scene understanding service."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from threading import Lock
from typing import Any

from robot_life.common.config import SlowSceneConfig
from robot_life.common.schemas import DecisionMode, EventPriority, SceneCandidate, SceneJson
from robot_life.slow_scene.queue import SlowSceneQueue
from robot_life.slow_scene.schema import (
    SlowSceneHealth,
    SlowSceneRequest,
    SlowSceneResult,
    SlowSceneStatus,
)
from robot_life.slow_scene.snapshot import SlowSceneSnapshotBuffer
from robot_life.slow_scene.worker import SlowSceneWorker


def _is_gguf_model_path(model_path: str) -> bool:
    path = Path(model_path)
    if path.suffix.lower() == ".gguf":
        return True
    if not path.exists() or not path.is_dir():
        return False
    return any(item.is_file() and item.suffix.lower() == ".gguf" for item in path.iterdir())


class SlowSceneService:
    """
    Slow scene understanding service using multimodal model (Qwen).
    
    Runs asynchronously to avoid blocking main event loop.
    Generates structured Scene JSON for cloud LLM integration.
    """

    def __init__(
        self,
        model_adapter: Any | None = None,
        use_qwen: bool = True,
        config: SlowSceneConfig | None = None,
    ):
        """
        Initialize slow scene service.
        
        Args:
            model_adapter: Optional external model adapter
            use_qwen: Whether to use Qwen VL adapter
        """
        self._config = config or SlowSceneConfig()
        self._adapter = model_adapter
        self._use_qwen = use_qwen and self._config.use_qwen
        self._logger = logging.getLogger(__name__)
        self.request_timeout_ms = self._config.request_timeout_ms
        self.trigger_min_score = self._config.trigger_min_score
        self.dedup_time_bucket_s = max(0.25, float(self._config.dedup_time_bucket_s))
        self.sample_interval_s = float(self._config.adapter_config.get("sample_interval_s", 1.0))
        self.force_sample = bool(self._config.adapter_config.get("force_sample", True))

        # Lazy load Qwen if requested
        if self._use_qwen and model_adapter is None:
            try:
                if _is_gguf_model_path(self._config.model_path):
                    from robot_life.perception.adapters.gguf_qwen_adapter import GGUFQwenVLAdapter

                    self._adapter = GGUFQwenVLAdapter(
                        model_path=self._config.model_path,
                        config=self._config.adapter_config,
                    )
                    self._logger.info("Initialized GGUF Qwen adapter for slow thinking")
                else:
                    from robot_life.perception.adapters.qwen_adapter import QwenVLAdapter

                    self._adapter = QwenVLAdapter(
                        model_path=self._config.model_path,
                        config=self._config.adapter_config,
                    )
                    self._logger.info("Initialized transformers Qwen VL adapter for slow thinking")
            except ImportError:
                self._logger.warning("Qwen not available, using fallback")
                self._adapter = None
            except Exception as e:
                self._logger.warning(f"Failed to load Qwen: {e}, using fallback")
                self._adapter = None

        self._snapshot = SlowSceneSnapshotBuffer()
        self._queue = SlowSceneQueue(maxsize=self._config.queue_size)
        self._worker = SlowSceneWorker(queue=self._queue, snapshot=self._snapshot, adapter=self._adapter)
        self._worker.start()
        self._state_lock = Lock()
        self._pending_by_target: dict[str, list[str]] = {}
        self._pending_by_dedup_key: dict[str, list[str]] = {}
        self._request_target_key: dict[str, str | None] = {}
        self._request_dedup_key: dict[str, str] = {}
        self._last_submit_payload: dict[str, Any] | None = None
        self._last_result_payload: dict[str, Any] | None = None
        self._adapter_bootstrapped = False

    def initialize(self) -> None:
        """Ensure the background worker is ready without blocking the caller."""
        self._worker.start()

    def capture_frame(
        self,
        frame: Any,
        *,
        source: str = "camera",
        frame_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a frame in the local slow-scene snapshot buffer."""
        return self._snapshot.capture_frame(
            frame,
            source=source,
            frame_id=frame_id,
            metadata=metadata,
        )

    def submit(
        self,
        scene: SceneCandidate,
        *,
        image: Any | None = None,
        context: str | None = None,
        priority: EventPriority = EventPriority.P2,
        timeout_ms: int = 5_000,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Submit a slow-scene job without blocking the caller.

        If `image` is omitted, the newest cached frame is used when available.
        """
        if image is not None:
            self.capture_frame(image, metadata={"scene_id": scene.scene_id, "scene_type": scene.scene_type})

        request = self._snapshot.build_request(
            scene,
            priority=priority,
            timeout_ms=timeout_ms,
            dedup_bucket_s=self.dedup_time_bucket_s,
            image=image,
            context=context,
            metadata=metadata,
        )
        target_key = self._target_key_for_request(request)

        with self._state_lock:
            self._reconcile_tracked_requests_locked()
            same_key_victims = list(self._pending_by_dedup_key.get(request.dedup_key, []))
            for request_id in same_key_victims:
                self._cancel_pending_request_locked(request_id)

        request_id = self._worker.submit(request)
        state = self._worker.get_request_state(request_id)

        with self._state_lock:
            if state == SlowSceneStatus.PENDING:
                self._register_pending_request_locked(request)
            if state != SlowSceneStatus.DROPPED and target_key is not None:
                self._enforce_target_limit_locked(target_key, keep_request_id=request_id)
            self._last_submit_payload = {
                "scene_id": request.scene_id,
                "scene_type": request.scene_type,
                "target_id": request.target_id,
                "priority": request.priority.value,
                "timeout_ms": request.timeout_ms,
                "context": context,
                "has_image": image is not None,
                "dedup_key": request.dedup_key,
                "accepted": state != SlowSceneStatus.DROPPED,
                "request_state": state.value if state is not None else None,
                "pending_for_target": (
                    len(self._pending_by_target.get(target_key, [])) if target_key is not None else 0
                ),
            }
        return request_id

    def submit_scene(
        self,
        scene: SceneCandidate,
        *,
        image: Any | None = None,
        context: str | None = None,
        priority: EventPriority = EventPriority.P2,
        timeout_ms: int = 5_000,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Compatibility alias for submit()."""
        return self.submit(
            scene,
            image=image,
            context=context,
            priority=priority,
            timeout_ms=timeout_ms,
            metadata=metadata,
        )

    def query(
        self,
        request_id: str | None = None,
        *,
        scene_id: str | None = None,
    ) -> SlowSceneResult | None:
        """Query the latest completed slow-scene result."""
        result = self._worker.query(request_id=request_id, scene_id=scene_id)
        if result is not None:
            scene_json = result.scene_json
            self._last_result_payload = {
                "request_id": result.request_id,
                "scene_id": result.scene_id,
                "scene_type": result.scene_type,
                "status": result.status.value,
                "model_latency_ms": result.model_latency_ms,
                "timeout_flag": result.timeout_flag,
                "scene_json": {
                    "scene_type": scene_json.scene_type,
                    "confidence": scene_json.confidence,
                    "involved_targets": list(scene_json.involved_targets),
                    "emotion_hint": scene_json.emotion_hint,
                    "urgency_hint": scene_json.urgency_hint,
                    "recommended_strategy": scene_json.recommended_strategy,
                    "escalate_to_cloud": scene_json.escalate_to_cloud,
                },
            }
        return result

    def get_request_state(self, request_id: str) -> str | None:
        """Read back the current state of a slow-scene request."""
        state = self._worker.get_request_state(request_id)
        return state.value if state is not None else None

    def cancel(self, request_id: str) -> bool:
        """Cancel a queued or in-flight slow-scene request."""
        return self._worker.cancel(request_id)

    def health(self) -> SlowSceneHealth:
        """Return worker and queue health information."""
        return self._worker.health()

    def should_trigger(
        self,
        scene: SceneCandidate,
        *,
        decision_mode: DecisionMode | str | None = None,
        arbitration_outcome: str | None = None,
    ) -> bool:
        """
        Trigger policy: only uncertain/conflict scenes should go to slow brain.

        - uncertain: score below configured threshold
        - conflict: arbitration queued/dropped/degraded
        """
        if scene.score_hint < self.trigger_min_score:
            return True

        if arbitration_outcome in {"queued", "dropped"}:
            return True

        if decision_mode in {DecisionMode.DROP, DecisionMode.DEGRADE_AND_EXECUTE}:
            return True

        if isinstance(decision_mode, str):
            normalized = decision_mode.strip().upper()
            if normalized in {"DROP", "DEGRADE_AND_EXECUTE"}:
                return True

        return False

    def stop(self) -> None:
        """Stop the background worker."""
        self._worker.stop()

    def build_scene_json(
        self,
        scene: SceneCandidate,
        image: Any | None = None,
        context: str | None = None,
    ) -> SceneJson:
        """
        Build structured Scene JSON from scene candidate.
        
        Uses Qwen model if available for intelligent understanding,
        otherwise falls back to simple heuristics.
        
        Args:
            scene: SceneCandidate to understand
            image: Optional image for multimodal understanding
            context: Optional text context
            
        Returns:
            SceneJson for cloud LLM integration
        """
        # If Qwen adapter available and image provided, use it directly.
        # This keeps the legacy synchronous path working for demo usage.
        if self._adapter and image is not None:
            try:
                self._ensure_adapter_ready()
                return self._adapter.understand_scene(
                    image,
                    context,
                    timeout_ms=int(self.request_timeout_ms),
                )
            except Exception as e:
                self._logger.warning(f"Qwen understanding failed: {e}, using fallback")

        # Fallback: simple rule-based understanding
        return self._fallback_scene_json(scene)

    @staticmethod
    def _fallback_scene_json(scene: SceneCandidate) -> SceneJson:
        """Generate scene JSON using rule-based approach."""
        scene_type = scene.scene_type

        # Map scene type to recommendations
        scene_config = {
            "greeting_scene": {
                "emotion_hint": "happy_attention",
                "urgency_hint": "medium",
                "recommended_strategy": "verbal_greeting",
                "escalate": scene.score_hint >= 0.8,
            },
            "attention_scene": {
                "emotion_hint": "curious",
                "urgency_hint": "low",
                "recommended_strategy": "nonverbal_first",
                "escalate": scene.score_hint >= 0.75,
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
                "escalate": scene.score_hint >= 0.8,
            },
            "ambient_tracking_scene": {
                "emotion_hint": "neutral",
                "urgency_hint": "low",
                "recommended_strategy": "passive_monitoring",
                "escalate": False,
            },
        }

        config = scene_config.get(scene_type, scene_config["ambient_tracking_scene"])

        involved_targets = [scene.target_id] if scene.target_id else []

        return SceneJson(
            scene_type=scene_type,
            confidence=scene.score_hint,
            involved_targets=involved_targets,
            emotion_hint=config["emotion_hint"],
            urgency_hint=config["urgency_hint"],
            recommended_strategy=config["recommended_strategy"],
            escalate_to_cloud=config["escalate"],
        )

    def query_latest_scene_json(self, scene_id: str) -> SceneJson | None:
        """Compatibility helper for callers that only want the underlying SceneJson."""
        result = self.query(scene_id=scene_id)
        return result.scene_json if result is not None else None

    async def understand_scene_async(
        self,
        scene: SceneCandidate,
        image: Any | None = None,
        context: str | None = None,
    ) -> SceneJson:
        """Compatibility async wrapper that keeps the caller off the main thread."""
        if image is None:
            return self.build_scene_json(scene, image, context)
        return await asyncio.to_thread(self.build_scene_json, scene, image, context)

    def close(self) -> None:
        """Cleanup resources."""
        if self._adapter and hasattr(self._adapter, "close"):
            self._adapter.close()
        self._worker.stop()

    def _target_key_for_request(self, request: SlowSceneRequest) -> str | None:
        if request.target_id is None:
            return None
        target_key = request.target_id.strip()
        return target_key or None

    def _reconcile_tracked_requests_locked(self) -> None:
        tracked_request_ids = list(self._request_target_key.keys())
        for request_id in tracked_request_ids:
            state = self._worker.get_request_state(request_id)
            if state == SlowSceneStatus.PENDING:
                continue
            self._remove_request_tracking_locked(request_id)

    def _register_pending_request_locked(self, request: SlowSceneRequest) -> None:
        target_key = self._target_key_for_request(request)
        self._request_target_key[request.request_id] = target_key
        self._request_dedup_key[request.request_id] = request.dedup_key

        dedup_pending = self._pending_by_dedup_key.setdefault(request.dedup_key, [])
        dedup_pending.append(request.request_id)

        if target_key is not None:
            target_pending = self._pending_by_target.setdefault(target_key, [])
            target_pending.append(request.request_id)

    def _remove_request_tracking_locked(self, request_id: str) -> None:
        target_key = self._request_target_key.pop(request_id, None)
        dedup_key = self._request_dedup_key.pop(request_id, None)

        if target_key is not None:
            target_pending = self._pending_by_target.get(target_key)
            if target_pending is not None:
                self._pending_by_target[target_key] = [item for item in target_pending if item != request_id]
                if not self._pending_by_target[target_key]:
                    self._pending_by_target.pop(target_key, None)

        if dedup_key is not None:
            dedup_pending = self._pending_by_dedup_key.get(dedup_key)
            if dedup_pending is not None:
                self._pending_by_dedup_key[dedup_key] = [item for item in dedup_pending if item != request_id]
                if not self._pending_by_dedup_key[dedup_key]:
                    self._pending_by_dedup_key.pop(dedup_key, None)

    def _cancel_pending_request_locked(self, request_id: str) -> bool:
        state = self._worker.get_request_state(request_id)
        if state != SlowSceneStatus.PENDING:
            self._remove_request_tracking_locked(request_id)
            return False

        cancelled = self._worker.cancel(request_id)
        self._remove_request_tracking_locked(request_id)
        return cancelled

    def _enforce_target_limit_locked(self, target_key: str, *, keep_request_id: str) -> None:
        limit = max(1, int(self._config.max_pending_per_target))
        target_pending = self._pending_by_target.get(target_key, [])
        while len(target_pending) > limit:
            victim_id = target_pending[0]
            if victim_id == keep_request_id and len(target_pending) == 1:
                break
            if victim_id == keep_request_id:
                target_pending.append(target_pending.pop(0))
                continue
            self._cancel_pending_request_locked(victim_id)
            target_pending = self._pending_by_target.get(target_key, [])

    def _ensure_adapter_ready(self) -> None:
        adapter = self._adapter
        if adapter is None or not hasattr(adapter, "initialize"):
            return
        if self._is_adapter_ready(adapter):
            self._adapter_bootstrapped = True
            return
        if self._adapter_bootstrapped and not hasattr(adapter, "is_ready"):
            return
        adapter.initialize()
        self._adapter_bootstrapped = True

    @staticmethod
    def _is_adapter_ready(adapter: Any) -> bool:
        if hasattr(adapter, "is_ready"):
            try:
                return bool(adapter.is_ready())
            except Exception:
                return False
        initialized = getattr(adapter, "_initialized", None)
        if initialized is not None:
            return bool(initialized)
        model = getattr(adapter, "_model", None)
        processor = getattr(adapter, "_processor", None)
        llm = getattr(adapter, "_llm", None)
        return llm is not None or (model is not None and processor is not None)

    def debug_snapshot(self) -> dict[str, Any]:
        health = self.health()
        adapter_debug = None
        if self._adapter is not None and hasattr(self._adapter, "debug_last_io"):
            try:
                adapter_debug = self._adapter.debug_last_io()
            except Exception:
                adapter_debug = None

        return {
            "use_qwen_requested": bool(self._use_qwen),
            "adapter_loaded": self._adapter is not None,
            "adapter_type": type(self._adapter).__name__ if self._adapter is not None else None,
            "health": health.to_dict() if hasattr(health, "to_dict") else {},
            "last_submit": self._last_submit_payload,
            "last_result": self._last_result_payload,
            "adapter_debug": adapter_debug,
        }
