"""MediaPipe-based detectors for gesture and gaze."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

try:  # pragma: no cover - optional runtime dependency
    import cv2
except Exception:  # pragma: no cover - optional runtime dependency
    cv2 = None

from robot_life.common.schemas import DetectionResult
from robot_life.common.tracing import new_trace_id
from robot_life.perception.base import DetectorBase, PipelineBase, PipelineSpec
from robot_life.perception.frame_dispatch import as_bgr_frame, as_rgb_frame, as_rgba_frame

try:
    import mediapipe as mp
except ImportError:
    mp = None  # Handle gracefully if not installed

logger = logging.getLogger(__name__)


def _ensure_cv2_available(adapter_name: str) -> None:
    if cv2 is None:
        raise RuntimeError(f"opencv-python is required for {adapter_name}")


def _to_mediapipe_image(frame: Any, *, use_gpu: bool) -> Any:
    """Convert OpenCV BGR frame into a MediaPipe Image with stable memory layout."""
    if mp is None:
        raise RuntimeError("mediapipe not installed")

    frame_u8 = np.asarray(as_bgr_frame(frame), dtype=np.uint8)
    if frame_u8.ndim != 3 or frame_u8.shape[2] < 3:
        raise ValueError(f"unsupported frame shape for mediapipe: {getattr(frame_u8, 'shape', None)}")

    if use_gpu:
        # On macOS Metal delegate, SRGBA is more robust than SRGB for GPU conversion.
        rgba_frame = as_rgba_frame(frame_u8)
        rgba_frame = np.ascontiguousarray(rgba_frame, dtype=np.uint8)
        return mp.Image(image_format=mp.ImageFormat.SRGBA, data=rgba_frame)

    rgb_frame = as_rgb_frame(frame_u8)
    rgb_frame = np.ascontiguousarray(rgb_frame, dtype=np.uint8)
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)


class MediaPipeGestureDetector(DetectorBase):
    """
    Hand gesture detection using MediaPipe Gesture Recognizer.
    
    Detects hand gestures like: Open_Palm, Closed_Fist, Pointing_Up, Victory, etc.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("mediapipe_gesture", "camera", config)
        self._recognizer = None
        self._using_gpu = False
        self._gesture_map = {
            "OPEN_PALM": "open_palm",
            "CLOSED_FIST": "closed_fist",
            "POINTING_UP": "pointing_up",
            "VICTORY": "victory",
            "LOVE": "love",
            "THUMB_UP": "thumb_up",
            "THUMB_DOWN": "thumb_down",
        }

    def initialize(self) -> None:
        """Load MediaPipe Gesture Recognizer model."""
        if mp is None:
            raise RuntimeError("mediapipe not installed. Install with: pip install mediapipe")
        _ensure_cv2_available("MediaPipeGestureDetector")
        model_path = str(self.config.get("model_path", "")).strip()
        if not model_path:
            raise RuntimeError(
                "mediapipe gesture model_path missing; point detectors.gesture.model_path to a .task file"
            )

        BaseOptions = mp.tasks.BaseOptions
        GestureRecognizer = mp.tasks.vision.GestureRecognizer
        GestureRecognizerOptions = mp.tasks.vision.GestureRecognizerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        use_gpu = bool(self.config.get("use_gpu", self.config.get("enable_gpu", True)))
        require_gpu = bool(self.config.get("require_gpu", False))
        delegate_enum = getattr(BaseOptions, "Delegate", None)
        using_gpu = False

        def _create_recognizer(delegate: Any | None) -> Any:
            base_options_kwargs = {"model_asset_path": model_path}
            if delegate is not None:
                base_options_kwargs["delegate"] = delegate
            options = GestureRecognizerOptions(
                base_options=BaseOptions(**base_options_kwargs),
                running_mode=VisionRunningMode.IMAGE,
                num_hands=self.config.get("num_hands", 2),
                min_hand_detection_confidence=self.config.get("min_detection_confidence", 0.5),
                min_hand_presence_confidence=self.config.get("min_presence_confidence", 0.5),
                min_tracking_confidence=self.config.get("min_tracking_confidence", 0.5),
            )
            return GestureRecognizer.create_from_options(options)

        if use_gpu and delegate_enum is not None:
            try:
                self._recognizer = _create_recognizer(delegate_enum.GPU)
                using_gpu = True
            except Exception as exc:
                if require_gpu:
                    raise RuntimeError(f"MediaPipe gesture GPU initialization failed: {exc}") from exc
                logger.warning("MediaPipe gesture GPU init failed, fallback to CPU: %s", exc)
                cpu_delegate = delegate_enum.CPU if delegate_enum is not None else None
                self._recognizer = _create_recognizer(cpu_delegate)
        else:
            cpu_delegate = delegate_enum.CPU if delegate_enum is not None else None
            self._recognizer = _create_recognizer(cpu_delegate)

        self._using_gpu = using_gpu
        logger.info("pipeline=gesture mediapipe_delegate=%s", "gpu" if using_gpu else "cpu")
        self._initialized = True

    def process(self, frame: Any) -> list[DetectionResult]:
        """
        Process frame and detect hand gestures.
        
        Args:
            frame: OpenCV image array (BGR, 3 channels)
            
        Returns:
            List of DetectionResult for each detected gesture
        """
        if not self._initialized or self._recognizer is None:
            return []

        results = []

        try:
            # Create MediaPipe Image (GPU path prefers SRGBA on macOS Metal).
            Image = _to_mediapipe_image(frame, use_gpu=self._using_gpu)

            # Run gesture recognition
            recognition_result = self._recognizer.recognize(Image)

            # Process each detected hand/gesture
            if recognition_result.gestures:
                for gesture_list, hand_landmark in zip(
                    recognition_result.gestures, recognition_result.hand_landmarks
                ):
                    if gesture_list:
                        top_gesture = gesture_list[0]
                        gesture_name = self._gesture_map.get(
                            top_gesture.category_name, top_gesture.category_name
                        )
                        confidence = top_gesture.score

                        # Get hand bounding box from landmarks
                        x_coords = [lm.x for lm in hand_landmark]
                        y_coords = [lm.y for lm in hand_landmark]
                        bbox = [min(x_coords), min(y_coords), max(x_coords), max(y_coords)]

                        detection = DetectionResult(
                            trace_id=new_trace_id(),
                            source="camera",
                            detector="mediapipe_gesture",
                            event_type=f"gesture_{gesture_name}",
                            timestamp=0,  # Will be set by caller
                            confidence=float(confidence),
                            payload={
                                "gesture_name": gesture_name,
                                "hand_bbox": bbox,
                                "hand_index": len(results),
                            },
                        )
                        results.append(detection)

        except Exception as e:
            logger.error("MediaPipeGestureDetector error: %s", e)

        return results

    def close(self) -> None:
        """Cleanup detector resources."""
        if self._recognizer:
            self._recognizer = None
        self._initialized = False


class MediaPipeFaceDetector(DetectorBase):
    """Face detector fallback based on MediaPipe FaceLandmarker."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("mediapipe_face", "camera", config)
        self._face_landmarker = None
        self._using_gpu = False

    def initialize(self) -> None:
        if mp is None:
            raise RuntimeError("mediapipe not installed")
        _ensure_cv2_available("MediaPipeFaceDetector")
        model_path = str(self.config.get("model_path", "")).strip()
        if not model_path:
            raise RuntimeError(
                "mediapipe face model_path missing; point detectors.face.fallback_model_path to a .task file"
            )

        BaseOptions = mp.tasks.BaseOptions
        FaceLandmarker = mp.tasks.vision.FaceLandmarker
        FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        use_gpu = bool(self.config.get("use_gpu", self.config.get("enable_gpu", True)))
        require_gpu = bool(self.config.get("require_gpu", False))
        delegate_enum = getattr(BaseOptions, "Delegate", None)
        using_gpu = False

        def _create_face_landmarker(delegate: Any | None) -> Any:
            base_options_kwargs = {"model_asset_path": model_path}
            if delegate is not None:
                base_options_kwargs["delegate"] = delegate
            options = FaceLandmarkerOptions(
                base_options=BaseOptions(**base_options_kwargs),
                running_mode=VisionRunningMode.IMAGE,
                num_faces=int(self.config.get("max_faces", 2)),
                min_face_detection_confidence=float(self.config.get("min_detection_confidence", 0.5)),
                min_face_presence_confidence=float(self.config.get("min_presence_confidence", 0.5)),
                min_tracking_confidence=float(self.config.get("min_tracking_confidence", 0.5)),
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
            )
            return FaceLandmarker.create_from_options(options)

        if use_gpu and delegate_enum is not None:
            try:
                self._face_landmarker = _create_face_landmarker(delegate_enum.GPU)
                using_gpu = True
            except Exception as exc:
                if require_gpu:
                    raise RuntimeError(f"MediaPipe face GPU initialization failed: {exc}") from exc
                logger.warning("MediaPipe face GPU init failed, fallback to CPU: %s", exc)
                cpu_delegate = delegate_enum.CPU if delegate_enum is not None else None
                self._face_landmarker = _create_face_landmarker(cpu_delegate)
        else:
            cpu_delegate = delegate_enum.CPU if delegate_enum is not None else None
            self._face_landmarker = _create_face_landmarker(cpu_delegate)

        self._using_gpu = using_gpu
        logger.info("pipeline=face mediapipe_delegate=%s", "gpu" if using_gpu else "cpu")
        self._initialized = True

    def process(self, frame: Any) -> list[DetectionResult]:
        if not self._initialized or self._face_landmarker is None:
            return []
        frame_bgr = as_bgr_frame(frame)
        if frame_bgr is None or not hasattr(frame_bgr, "shape"):
            return []

        try:
            h, w = frame_bgr.shape[:2]
            image = _to_mediapipe_image(frame_bgr, use_gpu=self._using_gpu)
            result = self._face_landmarker.detect(image)
        except Exception as exc:
            logger.error("MediaPipeFaceDetector error: %s", exc)
            return []

        detections: list[DetectionResult] = []
        for idx, face_landmarks in enumerate(getattr(result, "face_landmarks", [])):
            if not face_landmarks:
                continue
            xs = [float(lm.x) for lm in face_landmarks]
            ys = [float(lm.y) for lm in face_landmarks]
            x1 = max(0.0, min(xs))
            y1 = max(0.0, min(ys))
            x2 = min(1.0, max(xs))
            y2 = min(1.0, max(ys))
            bbox = [int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)]
            area_ratio = max(0.0, (x2 - x1) * (y2 - y1))
            confidence = min(1.0, 0.5 + area_ratio * 2.0)
            detections.append(
                DetectionResult(
                    trace_id=new_trace_id(),
                    source="camera",
                    detector=self.name,
                    event_type="stranger_face",
                    timestamp=0,
                    confidence=float(confidence),
                    payload={
                        "bbox": bbox,
                        "target_id": f"unknown_{idx}",
                        "is_familiar": False,
                        "face_area_ratio": float(area_ratio),
                    },
                )
            )
        return detections

    def close(self) -> None:
        self._face_landmarker = None
        self._initialized = False


class MediaPipeGazePipeline(PipelineBase):
    """
    Gaze detection using MediaPipe Face Mesh and Eye Iris landmark.
    
    Detects: is_looking_at_camera, gaze_direction, eye_openness
    """

    def __init__(self, spec: PipelineSpec | None = None, config: dict[str, Any] | None = None):
        if spec is None:
            spec = PipelineSpec(name="gaze", source="camera", sample_rate_hz=10)
        super().__init__(spec)
        self._config = config or {}
        self._face_landmarker = None
        self._eyes_open_threshold = 0.15  # Threshold for eye openness
        self._using_gpu = False

    def initialize(self) -> None:
        """Load MediaPipe Face Landmarker model."""
        if mp is None:
            raise RuntimeError("mediapipe not installed")
        _ensure_cv2_available("MediaPipeGazePipeline")
        model_path = str(self._config.get("model_path", "")).strip()
        if not model_path:
            raise RuntimeError(
                "mediapipe gaze model_path missing; point detectors.gaze.model_path to a .task file"
            )

        BaseOptions = mp.tasks.BaseOptions
        FaceLandmarker = mp.tasks.vision.FaceLandmarker
        FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode

        use_gpu = bool(self._config.get("use_gpu", self._config.get("enable_gpu", True)))
        require_gpu = bool(self._config.get("require_gpu", False))
        delegate_enum = getattr(BaseOptions, "Delegate", None)
        using_gpu = False

        def _create_face_landmarker(delegate: Any | None) -> Any:
            base_options_kwargs = {"model_asset_path": model_path}
            if delegate is not None:
                base_options_kwargs["delegate"] = delegate
            options = FaceLandmarkerOptions(
                base_options=BaseOptions(**base_options_kwargs),
                running_mode=VisionRunningMode.IMAGE,
                num_faces=int(self._config.get("max_faces", 1)),
                min_face_detection_confidence=float(self._config.get("min_detection_confidence", 0.5)),
                min_face_presence_confidence=float(self._config.get("min_presence_confidence", 0.5)),
                min_tracking_confidence=float(self._config.get("min_tracking_confidence", 0.5)),
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
            )
            return FaceLandmarker.create_from_options(options)

        if use_gpu and delegate_enum is not None:
            try:
                self._face_landmarker = _create_face_landmarker(delegate_enum.GPU)
                using_gpu = True
            except Exception as exc:
                if require_gpu:
                    raise RuntimeError(f"MediaPipe gaze GPU initialization failed: {exc}") from exc
                logger.warning("MediaPipe gaze GPU init failed, fallback to CPU: %s", exc)
                cpu_delegate = delegate_enum.CPU if delegate_enum is not None else None
                self._face_landmarker = _create_face_landmarker(cpu_delegate)
        else:
            cpu_delegate = delegate_enum.CPU if delegate_enum is not None else None
            self._face_landmarker = _create_face_landmarker(cpu_delegate)

        self._using_gpu = using_gpu
        logger.info("pipeline=gaze mediapipe_delegate=%s", "gpu" if using_gpu else "cpu")
        self._running = True

    def process(self, frame: Any) -> list[DetectionResult]:
        """
        Process frame and detect gaze.
        
        Args:
            frame: OpenCV image array
            
        Returns:
            List of DetectionResult for gaze detections
        """
        if not self._running or self._face_landmarker is None:
            return []

        results = []

        try:
            Image = _to_mediapipe_image(frame, use_gpu=self._using_gpu)

            face_landmarker_result = self._face_landmarker.detect(Image)

            # Process each detected face
            for face_landmarks in face_landmarker_result.face_landmarks:
                # Landmarks 33-42 are iris/pupil landmarks
                # Check if eyes are open and looking at camera
                is_looking = self._check_gaze_at_camera(face_landmarks)

                detection = DetectionResult(
                    trace_id=new_trace_id(),
                    source="camera",
                    detector="mediapipe_gaze",
                    event_type="gaze_sustained" if is_looking else "gaze_away",
                    timestamp=0,
                    confidence=0.8 if is_looking else 0.7,
                    payload={
                        "is_looking_at_camera": is_looking,
                        "face_landmarks_count": len(face_landmarks),
                    },
                )
                results.append(detection)

        except Exception as e:
            logger.error("MediaPipeGazePipeline error: %s", e)

        return results

    def close(self) -> None:
        """Cleanup resources."""
        self._face_landmarker = None
        self._running = False

    @staticmethod
    def _check_gaze_at_camera(landmarks: list) -> bool:
        """
        Check if person is looking at camera based on iris landmarks.
        
        Simple heuristic: if iris is roughly centered in eye, looking at camera.
        """
        try:
            # Prefer iris indices when available (478-point mesh).
            if len(landmarks) >= 477:
                left_iris = landmarks[468:472]
                right_iris = landmarks[473:477]
                left_x = np.mean([lm.x for lm in left_iris])
                right_x = np.mean([lm.x for lm in right_iris])
                return 0.3 < left_x < 0.7 and 0.3 < right_x < 0.7

            # Fallback for reduced landmark sets: estimate frontal gaze via nose midpoint.
            left_eye = landmarks[33]
            right_eye = landmarks[263]
            nose_tip = landmarks[1]
            eye_span = max(abs(float(right_eye.x) - float(left_eye.x)), 1e-6)
            nose_ratio = (float(nose_tip.x) - float(left_eye.x)) / eye_span
            return 0.35 <= nose_ratio <= 0.65
        except (IndexError, AttributeError):
            return False
