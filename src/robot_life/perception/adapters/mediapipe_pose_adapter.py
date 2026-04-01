from __future__ import annotations
import logging
from collections import deque
from time import monotonic
from typing import Any

import numpy as np

from robot_life.common.schemas import DetectionResult
from robot_life.common.tracing import new_trace_id
from robot_life.perception.base import DetectorBase
from robot_life.perception.frame_dispatch import as_bgr_frame, as_rgb_frame

logger = logging.getLogger(__name__)

try:
    import mediapipe as mp
except ImportError:
    mp = None


class MediaPipePoseDetector(DetectorBase):
    """
    Skeletal pose detection using MediaPipe Pose.
    
    Extracts 33 body landmarks and maintains a short temporal buffer to recognize
    macro-gestures like 'waving' and 'hug'.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("mediapipe_pose", "camera", config)
        self._pose = None
        self._history_len = int(self.config.get("temporal_window", 30))
        # Keep histories for wrists and shoulders
        self._wrist_l_history: deque = deque(maxlen=self._history_len)
        self._wrist_r_history: deque = deque(maxlen=self._history_len)
        
        # 11: left_shoulder, 12: right_shoulder
        # 15: left_wrist, 16: right_wrist
        self._hug_frames_threshold = int(self.config.get("hug_frames", 10))
        self._hug_counter = 0

    def initialize(self) -> None:
        if mp is None:
            raise RuntimeError("mediapipe not installed. Install with: pip install mediapipe")

        mp_pose = mp.solutions.pose
        self._pose = mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,  # 0=lite, 1=full, 2=heavy
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=self.config.get("min_detection_confidence", 0.5),
            min_tracking_confidence=self.config.get("min_tracking_confidence", 0.5),
        )
        self._initialized = True

    def process(self, frame_data: Any) -> list[DetectionResult]:
        if not self._initialized or self._pose is None:
            return []

        frame_bgr = as_bgr_frame(frame_data)
        if frame_bgr is None or not hasattr(frame_bgr, "shape"):
            return []
        # Ensure frame is RGB
        if len(frame_bgr.shape) == 3 and frame_bgr.shape[2] == 3:
            rgb_frame = as_rgb_frame(frame_bgr)
        else:
            rgb_frame = frame_bgr

        results = self._pose.process(rgb_frame)
        if not results.pose_landmarks:
            # Clear history if no person detected
            self._wrist_l_history.clear()
            self._wrist_r_history.clear()
            self._hug_counter = 0
            return []

        landmarks = results.pose_landmarks.landmark
        
        l_shoulder = landmarks[11]
        r_shoulder = landmarks[12]
        l_wrist = landmarks[15]
        r_wrist = landmarks[16]

        # Ensure good visibility
        min_vis = 0.5
        if min(l_shoulder.visibility, r_shoulder.visibility, l_wrist.visibility, r_wrist.visibility) < min_vis:
            self._hug_counter = 0
            return []

        # Update history
        self._wrist_l_history.append((l_wrist.x, l_wrist.y, l_wrist.z))
        self._wrist_r_history.append((r_wrist.x, r_wrist.y, r_wrist.z))

        detections = []

        # 1. Hug Detection (Geometric Rule)
        # Condition: Wrists spread wider than shoulders by a factor, and roughly at shoulder height.
        shoulder_dist = abs(l_shoulder.x - r_shoulder.x)
        wrist_dist = abs(l_wrist.x - r_wrist.x)
        
        # Y axis points down. Shoulders are typically around the same Y.
        avg_shoulder_y = (l_shoulder.y + r_shoulder.y) / 2.0
        
        # Are wrists wide and at chest/shoulder level?
        is_wide = wrist_dist > (shoulder_dist * 1.5)
        is_level_l = abs(l_wrist.y - avg_shoulder_y) < 0.2
        is_level_r = abs(r_wrist.y - avg_shoulder_y) < 0.2

        if is_wide and is_level_l and is_level_r:
            self._hug_counter += 1
            if self._hug_counter >= self._hug_frames_threshold:
                detections.append(
                    DetectionResult(
                        trace_id=new_trace_id(),
                        source="camera",
                        detector=self.name,
                        event_type="gesture_hug",
                        timestamp=monotonic(),
                        confidence=min(1.0, 0.7 + (self._hug_counter * 0.05)),
                        payload={"shoulder_dist": shoulder_dist, "wrist_dist": wrist_dist},
                    )
                )
        else:
            self._hug_counter = max(0, self._hug_counter - 2)

        # 2. Waving Detection (Temporal Rule)
        # Check if either hand is above shoulder and oscillating along X axis
        def check_wave(history, shoulder_y):
            if len(history) < 15:
                return False
            
            # Hand must be above shoulder (Y axis inverted, so Y < shoulder_y)
            recent_y = [p[1] for p in list(history)[-5:]]
            if sum(recent_y) / len(recent_y) > shoulder_y:
                return False
                
            xs = [p[0] for p in history]
            # Count direction changes
            directions = np.diff(xs) > 0
            flips = np.sum(directions[:-1] != directions[1:])
            
            # If oscillating (e.g. at least 3 direction changes in the window) and moves significantly
            max_x, min_x = max(xs), min(xs)
            if flips >= 3 and (max_x - min_x) > 0.05:
                return True
            return False

        if check_wave(self._wrist_l_history, l_shoulder.y) or check_wave(self._wrist_r_history, r_shoulder.y):
            detections.append(
                DetectionResult(
                    trace_id=new_trace_id(),
                    source="camera",
                    detector=self.name,
                    event_type="gesture_waving",
                    timestamp=monotonic(),
                    confidence=0.9,
                    payload={"frames_analyzed": len(self._wrist_l_history)},
                )
            )

        return detections

    def close(self) -> None:
        if self._pose is not None:
            self._pose.close()
        self._initialized = False
