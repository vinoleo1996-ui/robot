"""InsightFace-based face detection and recognition."""

from __future__ import annotations

import logging
import time
from typing import Any

from robot_life.common.cuda_runtime import ensure_cuda_runtime_loaded
from robot_life.common.schemas import DetectionResult
from robot_life.common.tracing import new_trace_id
from robot_life.perception.base import DetectorBase, PipelineBase, PipelineSpec
from robot_life.perception.frame_dispatch import as_bgr_frame

try:
    import insightface
except ImportError:
    insightface = None  # Handle gracefully if not installed

logger = logging.getLogger(__name__)


class InsightFaceFaceDetector(DetectorBase):
    """
    Face detection and recognition using InsightFace.
    
    Detects: face presence, familiar vs stranger
    """

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("insightface_face", "camera", config)
        self._analysis = None
        self._detector = None
        self._recognizer = None
        self._db_embeddings = {}  # Known face embeddings
        self._recognition_threshold = self.config.get("recognition_threshold", 0.6)

    def initialize(self) -> None:
        """Load InsightFace models."""
        if insightface is None:
            raise RuntimeError("insightface not installed. Install with: pip install insightface")

        gpu_device = int(self.config.get("gpu_device", 0))
        require_gpu = bool(self.config.get("require_gpu", False))
        provider_list = self._resolve_provider_list()
        det_thresh = float(self.config.get("det_thresh", 0.5))
        det_size = self.config.get("det_size", (640, 640))
        if isinstance(det_size, (list, tuple)) and len(det_size) == 2:
            det_size = (int(det_size[0]), int(det_size[1]))
        else:
            det_size = (640, 640)

        if gpu_device >= 0:
            loaded, failed = ensure_cuda_runtime_loaded()
            logger.debug(
                "InsightFace CUDA bootstrap loaded=%d failed=%d providers=%s",
                loaded,
                failed,
                provider_list,
            )

        # Preferred path (works with insightface 0.2.x and 0.7.x).
        if hasattr(insightface, "app") and hasattr(insightface.app, "FaceAnalysis"):
            model_name = str(self.config.get("model_name", "buffalo_l"))
            model_root = str(self.config.get("model_root", "~/.insightface/models"))
            self._analysis = insightface.app.FaceAnalysis(name=model_name, root=model_root)
            self._analysis.prepare(ctx_id=gpu_device, det_thresh=det_thresh, det_size=det_size)
            self._apply_runtime_providers(provider_list, require_gpu=require_gpu, gpu_device=gpu_device)
            self._initialized = True
            return

        # Legacy fallback path.
        self._detector = insightface.model_zoo.get_model("detection")
        if self._detector is None:
            raise RuntimeError("insightface detector model unavailable")
        self._detector.prepare(ctx_id=gpu_device)

        self._recognizer = insightface.model_zoo.get_model("recognition")
        if self._recognizer is not None:
            self._recognizer.prepare(ctx_id=gpu_device)

        self._apply_runtime_providers(provider_list, require_gpu=require_gpu, gpu_device=gpu_device)
        self._initialized = True

    def process(self, frame: Any) -> list[DetectionResult]:
        """
        Process frame and detect/recognize faces.
        
        Args:
            frame: OpenCV image array (BGR)
            
        Returns:
            List of DetectionResult for face detections
        """
        if not self._initialized:
            return []
        frame_bgr = as_bgr_frame(frame)
        if frame_bgr is None or not hasattr(frame_bgr, "shape"):
            return []

        results = []

        try:
            # FaceAnalysis path
            if self._analysis is not None:
                faces = self._analysis.get(frame_bgr)
                for idx, face in enumerate(faces or []):
                    bbox_obj = getattr(face, "bbox", None)
                    if bbox_obj is None:
                        continue
                    bbox = bbox_obj.astype(int)
                    confidence = float(getattr(face, "det_score", 0.7))
                    embedding = getattr(face, "embedding", None)
                    is_familiar = False
                    target_id = None

                    if embedding is not None:
                        is_familiar = self._match_embedding(embedding)
                        if is_familiar:
                            target_id = self._get_most_similar_id(embedding)

                    event_type = "familiar_face" if is_familiar else "stranger_face"
                    detection = DetectionResult(
                        trace_id=new_trace_id(),
                        source="camera",
                        detector="insightface_face",
                        event_type=event_type,
                        timestamp=time.time(),
                        confidence=confidence,
                        payload={
                            "bbox": bbox.tolist(),
                            "is_familiar": is_familiar,
                            "target_id": target_id or f"unknown_{idx}",
                            "face_area_ratio": self._compute_face_area(frame_bgr, bbox.tolist()),
                            "capture_frame_seq": (
                                frame.frame_seq if hasattr(frame, "frame_seq") else None
                            ),
                        },
                    )
                    results.append(detection)
                return results

            if self._detector is None:
                return []

            # Legacy model_zoo path
            faces = self._detector.detect(frame_bgr, threshold=self.config.get("det_thresh", 0.5))

            if faces is None or len(faces) == 0:
                return []

            # Process each detected face
            for face in faces:
                bbox = face.bbox.astype(int)
                confidence = float(face.det_score)

                # Try to recognize face if confidence is high enough
                is_familiar = False
                target_id = None

                if confidence > 0.7 and self._recognizer is not None:
                    try:
                        # Get face embedding
                        self._recognizer.get_feat(frame_bgr, face)
                        embedding = face.embedding

                        # Compare with known faces
                        is_similar = self._match_embedding(embedding)
                        if is_similar:
                            is_familiar = True
                            target_id = self._get_most_similar_id(embedding)
                    except Exception:
                        pass

                event_type = "familiar_face" if is_familiar else "stranger_face"

                detection = DetectionResult(
                    trace_id=new_trace_id(),
                    source="camera",
                    detector="insightface_face",
                    event_type=event_type,
                    timestamp=0,
                    confidence=confidence,
                    payload={
                        "bbox": bbox.tolist(),
                        "is_familiar": is_familiar,
                        "target_id": target_id or "unknown",
                        "face_area_ratio": self._compute_face_area(frame_bgr, bbox),
                        "capture_frame_seq": (
                            frame.frame_seq if hasattr(frame, "frame_seq") else None
                        ),
                    },
                )
                results.append(detection)

        except Exception as e:
            logger.error("InsightFaceFaceDetector error: %s", e)

        return results

    def add_known_face(self, face_id: str, embedding: Any) -> None:
        """Register a known face."""
        self._db_embeddings[face_id] = embedding

    def _match_embedding(self, embedding: Any) -> bool:
        """Check if embedding matches any known face."""
        if not self._db_embeddings:
            return False

        max_sim = 0
        for db_embedding in self._db_embeddings.values():
            sim = self._cosine_similarity(embedding, db_embedding)
            if sim > self._recognition_threshold:
                return True
            max_sim = max(max_sim, sim)

        return False

    def _get_most_similar_id(self, embedding: Any) -> str | None:
        """Get most similar known face ID."""
        best_id = None
        best_sim = 0

        for face_id, db_embedding in self._db_embeddings.items():
            sim = self._cosine_similarity(embedding, db_embedding)
            if sim > best_sim:
                best_sim = sim
                best_id = face_id

        return best_id if best_sim > self._recognition_threshold else None

    @staticmethod
    def _cosine_similarity(a: Any, b: Any) -> float:
        """Compute cosine similarity between two vectors."""
        import numpy as np
        a = np.array(a, dtype=np.float32)
        b = np.array(b, dtype=np.float32)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-6))

    @staticmethod
    def _compute_face_area(frame: Any, bbox: list) -> float:
        """Compute face area ratio in image."""
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        face_area = (x2 - x1) * (y2 - y1)
        img_area = h * w
        return float(face_area / img_area) if img_area > 0 else 0.0

    def close(self) -> None:
        """Cleanup detector resources."""
        self._analysis = None
        self._detector = None
        self._recognizer = None
        self._initialized = False

    def _resolve_provider_list(self) -> list[str]:
        configured = self.config.get("providers")
        if isinstance(configured, list):
            providers = [str(item).strip() for item in configured if str(item).strip()]
            if providers:
                return providers
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def _apply_runtime_providers(self, providers: list[str], *, require_gpu: bool, gpu_device: int) -> None:
        sessions = self._collect_onnx_sessions()
        if not sessions:
            if require_gpu and gpu_device >= 0:
                raise RuntimeError("InsightFace ONNX sessions unavailable; cannot enforce GPU provider")
            return

        for session in sessions:
            try:
                session.set_providers(providers)
            except Exception as exc:
                if require_gpu and gpu_device >= 0:
                    raise RuntimeError(f"Failed to set InsightFace providers={providers}: {exc}") from exc
                logger.warning("InsightFace provider override failed: %s", exc)

            if require_gpu and gpu_device >= 0:
                active = list(session.get_providers())
                if "CUDAExecutionProvider" not in active:
                    raise RuntimeError(
                        f"InsightFace GPU required but CUDAExecutionProvider inactive: active={active}"
                    )

    def _collect_onnx_sessions(self) -> list[Any]:
        sessions: list[Any] = []
        if self._analysis is not None:
            models = getattr(self._analysis, "models", {})
            if isinstance(models, dict):
                for model in models.values():
                    session = getattr(model, "session", None)
                    if session is not None:
                        sessions.append(session)
            return sessions

        for model in (self._detector, self._recognizer):
            session = getattr(model, "session", None)
            if session is not None:
                sessions.append(session)
        return sessions


class InsightFacePipeline(PipelineBase):
    """Pipeline combining InsightFace detections with face analysis."""

    def __init__(self, spec: PipelineSpec | None = None, config: dict[str, Any] | None = None):
        if spec is None:
            spec = PipelineSpec(name="face", source="camera", sample_rate_hz=10)
        super().__init__(spec)
        self._face_detector = InsightFaceFaceDetector(config or {})

    def initialize(self) -> None:
        """Initialize face pipeline."""
        self._face_detector.initialize()
        self._running = True

    def process(self, frame: Any) -> list[DetectionResult]:
        """Process frame through face detection."""
        if not self._running:
            return []
        return self._face_detector.process(frame)

    def add_reference_face(self, face_id: str, embedding: Any) -> None:
        """Add reference face for recognition."""
        self._face_detector.add_known_face(face_id, embedding)

    def close(self) -> None:
        """Shutdown pipeline."""
        self._face_detector.close()
        self._running = False
