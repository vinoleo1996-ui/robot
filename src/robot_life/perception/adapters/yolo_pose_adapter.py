"""YOLO v8 Pose-based gesture and action recognition."""

from __future__ import annotations

import logging
from time import monotonic, time
from typing import Any

import numpy as np

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

try:
    import torch
except ImportError:
    torch = None

from robot_life.common.schemas import DetectionResult
from robot_life.common.tracing import new_trace_id
from robot_life.perception.base import DetectorBase
from robot_life.perception.frame_dispatch import as_bgr_frame

logger = logging.getLogger(__name__)

# Gesture recognition based on hand keypoint patterns
# Format: gesture_name -> list of (keypoint_distance_pairs, threshold)
HAND_KEYPOINTS_INDICES = {
    0: "wrist",
    1: "thumb_cmc", 2: "thumb_mcp", 3: "thumb_ip", 4: "thumb_tip",
    5: "index_mcp", 6: "index_pip", 7: "index_dip", 8: "index_tip",
    9: "middle_mcp", 10: "middle_pip", 11: "middle_dip", 12: "middle_tip",
    13: "ring_mcp", 14: "ring_pip", 15: "ring_dip", 16: "ring_tip",
    17: "pinky_mcp", 18: "pinky_pip", 19: "pinky_dip", 20: "pinky_tip",
}

GESTURE_TEMPLATES = {
    "open_palm": {
        "description": "All fingers extended",
        "check_fn": lambda keypoints: _check_open_palm(keypoints),
        "min_confidence": 0.5,
    },
    "closed_fist": {
        "description": "All fingers curled",
        "check_fn": lambda keypoints: _check_closed_fist(keypoints),
        "min_confidence": 0.5,
    },
    "thumbs_up": {
        "description": "Thumb extended upward",
        "check_fn": lambda keypoints: _check_thumbs_up(keypoints),
        "min_confidence": 0.6,
    },
    "victory": {
        "description": "Index and middle finger extended",
        "check_fn": lambda keypoints: _check_victory(keypoints),
        "min_confidence": 0.5,
    },
    "pointing": {
        "description": "Index finger extended",
        "check_fn": lambda keypoints: _check_pointing(keypoints),
        "min_confidence": 0.5,
    },
}


class YOLOPoseGestureDetector(DetectorBase):
    """
    Hand gesture and pose detection using YOLO v8 Pose.
    
    Supports customizable gesture recognition based on hand keypoints.
    Replaces MediaPipe's 7 fixed gestures with flexible skeleton-based recognition.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("yolo_pose_gesture", "camera", config)
        self._model = None
        self._model_path = str(self.config.get("model_path", "yolov8n-pose.pt"))
        self._conf_threshold = float(self.config.get("conf_threshold", 0.5))
        self._device = str(
            self.config.get("device", "cuda:0" if torch is not None and torch.cuda.is_available() else "cpu")
        )
        self._cooldown_s = float(self.config.get("gesture_cooldown_sec", 0.3))
        self._last_emit_mono = 0.0
        self._custom_gestures = self.config.get("custom_gestures", {})

    def initialize(self) -> None:
        """Load YOLO Pose model."""
        if YOLO is None:
            raise RuntimeError(
                "ultralytics not installed. Install with: pip install ultralytics"
            )

        try:
            logger.info(f"Loading YOLO Pose from {self._model_path}...")
            self._model = YOLO(self._model_path, task="pose")
            self._model.to(self._device)
            self._initialized = True
            logger.info(f"YOLO Pose model loaded on {self._device}")
        except Exception as e:
            logger.error(f"Failed to load YOLO Pose: {e}")
            raise

    def process(self, frame: Any) -> list[DetectionResult]:
        """
        Process frame and detect gestures based on pose keypoints.
        
        Args:
            frame: OpenCV image array (BGR)
            
        Returns:
            List of DetectionResult for detected gestures
        """
        if not self._initialized or self._model is None:
            return []

        frame_bgr = as_bgr_frame(frame)
        if frame_bgr is None or not hasattr(frame_bgr, "shape"):
            return []

        results = []

        try:
            # Run pose detection
            predictions = self._model.predict(
                source=frame_bgr,
                conf=self._conf_threshold,
                verbose=False,
                device=self._device,
            )

            if not predictions or len(predictions) == 0:
                return []

            # Extract keypoints from predictions
            pred = predictions[0]
            if not hasattr(pred, "keypoints") or pred.keypoints is None:
                return []

            keypoints_list = pred.keypoints.xy  # (N, 17, 2) for YOLO-Pose
            confidences = pred.keypoints.conf  # (N, 17)
            boxes = pred.boxes  # Detection boxes

            now_mono = monotonic()
            if now_mono - self._last_emit_mono < self._cooldown_s:
                return []

            # Process each detected person
            for idx, (keypoints, kp_conf) in enumerate(zip(keypoints_list, confidences)):
                if len(keypoints) < 17:
                    continue

                # Try to recognize gestures from keypoints
                recognized_gestures = self._recognize_gestures(keypoints, kp_conf)

                for gesture_name, confidence in recognized_gestures:
                    self._last_emit_mono = now_mono

                    # Get hand bounding box (approximate from keypoints)
                    hand_bbox = self._estimate_hand_bbox(keypoints)

                    detection = DetectionResult(
                        trace_id=new_trace_id(),
                        source="camera",
                        detector="yolo_pose_gesture",
                        event_type=f"gesture_{gesture_name}",
                        timestamp=time(),
                        confidence=float(confidence),
                        payload={
                            "gesture_name": gesture_name,
                            "keypoints": keypoints.tolist() if isinstance(keypoints, np.ndarray) else keypoints,
                            "hand_bbox": hand_bbox,
                            "person_idx": idx,
                        },
                    )
                    results.append(detection)

        except Exception as e:
            logger.error(f"YOLO Pose gesture detection failed: {e}")

        return results

    def _recognize_gestures(
        self, keypoints: np.ndarray, confidences: np.ndarray
    ) -> list[tuple[str, float]]:
        """
        Recognize gestures from hand keypoints.
        
        Args:
            keypoints: Hand keypoints array (21, 2) or (17, 2) for full pose
            confidences: Keypoint confidences
            
        Returns:
            List of recognized (gesture_name, confidence) tuples
        """
        recognized = []

        # Try built-in gesture templates
        for gesture_name, template in GESTURE_TEMPLATES.items():
            try:
                if template["check_fn"](keypoints):
                    # Calculate overall confidence
                    gesture_conf = float(np.mean(confidences[confidences > 0])) if confidences.size > 0 else 0.5
                    if gesture_conf >= template["min_confidence"]:
                        recognized.append((gesture_name, gesture_conf))
            except Exception:
                pass

        # Try custom gestures if provided
        for custom_gesture_name, custom_fn in self._custom_gestures.items():
            try:
                if custom_fn(keypoints):
                    gesture_conf = float(np.mean(confidences[confidences > 0])) if confidences.size > 0 else 0.5
                    recognized.append((custom_gesture_name, gesture_conf))
            except Exception:
                pass

        return recognized

    @staticmethod
    def _estimate_hand_bbox(keypoints: np.ndarray) -> list[float]:
        """Estimate hand bounding box from keypoints."""
        if len(keypoints) == 0:
            return [0, 0, 0, 0]

        x_coords = keypoints[:, 0]
        y_coords = keypoints[:, 1]
        return [
            float(np.min(x_coords)),
            float(np.min(y_coords)),
            float(np.max(x_coords)),
            float(np.max(y_coords)),
        ]

    def close(self) -> None:
        """Cleanup detector resources."""
        self._model = None
        self._initialized = False


def _check_open_palm(keypoints: np.ndarray) -> bool:
    """Check if hand is in open palm position (all fingers extended)."""
    if len(keypoints) < 21:
        return False
    # Simplified: check if fingertips are far from palm center
    palm_center = keypoints[0]  # wrist
    fingertips = [keypoints[4], keypoints[8], keypoints[12], keypoints[16], keypoints[20]]
    distances = [np.linalg.norm(tip - palm_center) for tip in fingertips]
    return all(d > 0.05 for d in distances)  # Threshold: 5% of frame


def _check_closed_fist(keypoints: np.ndarray) -> bool:
    """Check if hand is in closed fist position."""
    if len(keypoints) < 21:
        return False
    palm_center = keypoints[0]
    fingertips = [keypoints[4], keypoints[8], keypoints[12], keypoints[16], keypoints[20]]
    distances = [np.linalg.norm(tip - palm_center) for tip in fingertips]
    return all(d < 0.1 for d in distances)  # Threshold: 10% of frame


def _check_thumbs_up(keypoints: np.ndarray) -> bool:
    """Check if hand shows thumbs up."""
    if len(keypoints) < 21:
        return False
    thumb_tip = keypoints[4]
    thumb_mcp = keypoints[1]
    # Thumb should be higher (smaller y) than wrist
    return thumb_tip[1] < keypoints[0][1] - 0.1


def _check_victory(keypoints: np.ndarray) -> bool:
    """Check if hand shows victory sign (V)."""
    if len(keypoints) < 21:
        return False
    # Index and middle fingers extended
    index_extended = keypoints[8][1] < keypoints[0][1] - 0.1
    middle_extended = keypoints[12][1] < keypoints[0][1] - 0.1
    # Ring and pinky curled
    ring_curled = keypoints[16][1] > keypoints[0][1]
    pinky_curled = keypoints[20][1] > keypoints[0][1]
    return index_extended and middle_extended and ring_curled and pinky_curled


def _check_pointing(keypoints: np.ndarray) -> bool:
    """Check if hand is pointing (index extended, others curled)."""
    if len(keypoints) < 21:
        return False
    index_extended = keypoints[8][1] < keypoints[0][1] - 0.1
    others_curled = all(
        keypoints[i][1] > keypoints[0][1] for i in [4, 12, 16, 20]
    )
    return index_extended and others_curled
