"""OpenCV-based lightweight motion detector."""

from __future__ import annotations

import logging
from time import monotonic, time
from typing import Any

import numpy as np

try:  # pragma: no cover - optional runtime dependency
    import cv2
except Exception:  # pragma: no cover - optional runtime dependency
    cv2 = None

from robot_life.common.schemas import DetectionResult
from robot_life.common.tracing import new_trace_id
from robot_life.perception.base import DetectorBase
from robot_life.perception.frame_dispatch import as_bgr_frame, as_gray_frame

try:  # pragma: no cover - optional runtime dependency
    from ultralytics import YOLO
except Exception:  # pragma: no cover - optional runtime dependency
    YOLO = None

try:  # pragma: no cover - optional runtime dependency
    import torch
except Exception:  # pragma: no cover - optional runtime dependency
    torch = None

logger = logging.getLogger(__name__)


class OpenCVMotionDetector(DetectorBase):
    """Frame-diff motion detector for real-time MVP validation."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(name="opencv_motion", source="camera", config=config)
        self._previous_gray: np.ndarray | None = None
        self._threshold = int(self.config.get("pixel_threshold", 25))
        self._blur_kernel = int(self.config.get("blur_kernel", 5))
        self._min_area_ratio = float(self.config.get("min_area_ratio", 0.02))
        self._min_object_area_ratio = float(self.config.get("min_object_area_ratio", self._min_area_ratio))
        self._max_object_area_ratio = float(self.config.get("max_object_area_ratio", 1.0))
        self._max_aspect_ratio = float(self.config.get("max_aspect_ratio", 99.0))
        self._dilate_iterations = max(0, int(self.config.get("dilate_iterations", 1)))
        self._cooldown_s = float(self.config.get("motion_cooldown_sec", 0.5))
        self._suppress_human_motion = bool(self.config.get("suppress_human_motion", False))
        self._human_overlap_iou = float(self.config.get("human_overlap_iou", 0.2))
        self._human_detect_interval_frames = max(1, int(self.config.get("human_detect_interval_frames", 4)))
        self._human_detect_scale = float(self.config.get("human_detect_scale", 0.6))
        self._human_min_weight = float(self.config.get("human_min_weight", 0.2))
        self._motion_scale = min(max(float(self.config.get("motion_scale", 1.0)), 0.1), 1.0)
        self._last_emit_mono = 0.0
        self._frame_counter = 0
        self._human_boxes: list[tuple[int, int, int, int]] = []
        self._hog_person_detector = None

    def initialize(self) -> None:
        if bool(self.config.get("require_gpu", False)):
            raise RuntimeError(
                "OpenCVMotionDetector is CPU-only. "
                "Use detector_type=yolo* with YOLOMotionDetector for GPU motion inference."
            )
        if cv2 is None:
            raise RuntimeError("opencv-python is required for OpenCVMotionDetector")
        if self._suppress_human_motion:
            try:
                detector = cv2.HOGDescriptor()
                detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
                self._hog_person_detector = detector
            except Exception as exc:  # pragma: no cover - environment dependent
                logger.warning("opencv people detector unavailable; disable suppress_human_motion: %s", exc)
                self._hog_person_detector = None
                self._suppress_human_motion = False
        self._previous_gray = None
        self._last_emit_mono = 0.0
        self._frame_counter = 0
        self._human_boxes = []
        self._initialized = True

    def process(self, frame: Any) -> list[DetectionResult]:
        if not self._initialized:
            return []
        frame_bgr = as_bgr_frame(frame)
        if frame_bgr is None or not hasattr(frame_bgr, "shape"):
            return []
        frame_height, frame_width = frame_bgr.shape[:2]

        self._frame_counter += 1
        gray = as_gray_frame(frame)
        motion_scale = self._motion_scale
        if motion_scale < 1.0:
            gray = cv2.resize(gray, dsize=None, fx=motion_scale, fy=motion_scale, interpolation=cv2.INTER_AREA)
        kernel_size = max(1, self._blur_kernel)
        if kernel_size % 2 == 0:
            kernel_size += 1
        gray = cv2.GaussianBlur(gray, (kernel_size, kernel_size), 0)

        previous = self._previous_gray
        self._previous_gray = gray
        if previous is None:
            return []

        delta = cv2.absdiff(previous, gray)
        _, motion_mask = cv2.threshold(delta, self._threshold, 255, cv2.THRESH_BINARY)
        total_pixels = int(motion_mask.size) or 1
        if self._dilate_iterations > 0:
            motion_mask = cv2.dilate(motion_mask, None, iterations=self._dilate_iterations)

        if self._suppress_human_motion and self._hog_person_detector is not None:
            if (
                not self._human_boxes
                or (self._frame_counter % self._human_detect_interval_frames) == 0
            ):
                self._human_boxes = self._detect_human_boxes(frame_bgr)

        contours, _ = cv2.findContours(motion_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        selected_boxes: list[list[int]] = []
        selected_pixels = 0
        inverse_scale = 1.0 / motion_scale if motion_scale > 0 else 1.0
        for contour in contours:
            contour_area = float(cv2.contourArea(contour))
            if contour_area <= 0.0:
                continue
            contour_ratio = contour_area / total_pixels
            if contour_ratio < self._min_object_area_ratio:
                continue
            if contour_ratio > self._max_object_area_ratio:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w <= 0 or h <= 0:
                continue
            aspect_ratio = h / max(1.0, float(w))
            if aspect_ratio > self._max_aspect_ratio:
                continue
            motion_box = (
                int(round(float(x) * inverse_scale)),
                int(round(float(y) * inverse_scale)),
                max(1, int(round(float(w) * inverse_scale))),
                max(1, int(round(float(h) * inverse_scale))),
            )
            if self._is_human_overlap(motion_box):
                continue
            selected_pixels += int(contour_area)
            x1 = max(0, min(frame_width, motion_box[0]))
            y1 = max(0, min(frame_height, motion_box[1]))
            x2 = max(x1 + 1, min(frame_width, motion_box[0] + motion_box[2]))
            y2 = max(y1 + 1, min(frame_height, motion_box[1] + motion_box[3]))
            selected_boxes.append([x1, y1, x2, y2])

        if selected_pixels <= 0:
            return []
        area_ratio = selected_pixels / total_pixels

        now_mono = monotonic()
        if area_ratio < self._min_area_ratio:
            return []
        if now_mono - self._last_emit_mono < self._cooldown_s:
            return []

        self._last_emit_mono = now_mono
        return [
            DetectionResult(
                trace_id=new_trace_id(),
                source="camera",
                detector=self.name,
                event_type="motion",
                timestamp=time(),
                confidence=min(1.0, area_ratio * 4.0),
                payload={
                    "motion_area_ratio": area_ratio,
                    "motion_pixels": selected_pixels,
                    "motion_boxes": selected_boxes,
                    "motion_box_count": len(selected_boxes),
                    "threshold": self._threshold,
                    "suppress_human_motion": self._suppress_human_motion,
                },
            )
        ]

    def close(self) -> None:
        self._previous_gray = None
        self._human_boxes = []
        self._hog_person_detector = None
        self._initialized = False

    def update_thresholds(
        self,
        *,
        pixel_threshold: float | None = None,
        min_area_ratio: float | None = None,
        motion_cooldown_sec: float | None = None,
    ) -> dict[str, float]:
        if pixel_threshold is not None:
            self._threshold = max(1, int(round(float(pixel_threshold))))
        if min_area_ratio is not None:
            resolved = min(max(0.0, float(min_area_ratio)), 1.0)
            self._min_area_ratio = resolved
            self._min_object_area_ratio = min(self._min_object_area_ratio, resolved) if self._min_object_area_ratio > resolved else resolved
        if motion_cooldown_sec is not None:
            self._cooldown_s = max(0.0, float(motion_cooldown_sec))
        return {
            "pixel_threshold": float(self._threshold),
            "min_area_ratio": float(self._min_area_ratio),
            "motion_cooldown_sec": float(self._cooldown_s),
        }

    def _detect_human_boxes(self, frame: Any) -> list[tuple[int, int, int, int]]:
        if self._hog_person_detector is None:
            return []
        try:
            scale = self._human_detect_scale
            if scale <= 0.0 or scale >= 1.0:
                resized = frame
                inv_scale = 1.0
            else:
                resized = cv2.resize(frame, dsize=None, fx=scale, fy=scale)
                inv_scale = 1.0 / scale
            boxes, weights = self._hog_person_detector.detectMultiScale(
                resized,
                winStride=(8, 8),
                padding=(8, 8),
                scale=1.05,
            )
        except Exception:
            return []
        if len(boxes) == 0:
            return []

        output: list[tuple[int, int, int, int]] = []
        for idx, (x, y, w, h) in enumerate(boxes):
            weight = float(weights[idx]) if idx < len(weights) else 1.0
            if weight < self._human_min_weight:
                continue
            output.append(
                (
                    int(float(x) * inv_scale),
                    int(float(y) * inv_scale),
                    int(float(w) * inv_scale),
                    int(float(h) * inv_scale),
                )
            )
        return output

    @staticmethod
    def _bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ax2, ay2 = ax + aw, ay + ah
        bx2, by2 = bx + bw, by + bh

        inter_x1 = max(ax, bx)
        inter_y1 = max(ay, by)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
            return 0.0
        inter_area = float((inter_x2 - inter_x1) * (inter_y2 - inter_y1))
        a_area = float(max(1, aw * ah))
        b_area = float(max(1, bw * bh))
        return inter_area / max(1.0, a_area + b_area - inter_area)

    def _is_human_overlap(self, motion_box: tuple[int, int, int, int]) -> bool:
        if not self._suppress_human_motion:
            return False
        if not self._human_boxes:
            return False
        mx, my, mw, mh = motion_box
        center = (mx + mw // 2, my + mh // 2)
        for human in self._human_boxes:
            hx, hy, hw, hh = human
            if hx <= center[0] <= hx + hw and hy <= center[1] <= hy + hh:
                return True
            if self._bbox_iou(motion_box, human) >= self._human_overlap_iou:
                return True
        return False


class YOLOMotionDetector(DetectorBase):
    """YOLO-based motion/person activity detector with CUDA support."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(name="yolo_motion", source="camera", config=config)
        self._model = None
        self._model_path = str(self.config.get("model_path", "models/yolo/yolov8n.pt"))
        self._conf_threshold = float(self.config.get("conf_threshold", 0.35))
        self._iou_threshold = float(self.config.get("iou_threshold", 0.45))
        raw_classes = self.config.get("classes", [0])
        self._classes = [int(item) for item in raw_classes] if isinstance(raw_classes, list) else [0]
        self._device = str(
            self.config.get("device", "cuda:0" if torch is not None and torch.cuda.is_available() else "cpu")
        )
        self._require_gpu = bool(self.config.get("require_gpu", False))
        self._allow_cuda_fallback = bool(self.config.get("allow_cuda_fallback", True))
        self._cooldown_s = float(self.config.get("motion_cooldown_sec", 0.3))
        default_half = self._device.startswith("cuda")
        self._half = bool(self.config.get("half", default_half))
        self._imgsz = self._coerce_positive_int(self.config.get("imgsz"), default=640)
        self._max_det = self._coerce_positive_int(self.config.get("max_det"), default=5)
        self._last_emit_mono = 0.0
        self._cuda_fallback_triggered = False

    def initialize(self) -> None:
        if YOLO is None:
            raise RuntimeError("ultralytics is not installed. Install with: pip install ultralytics")

        using_cuda = self._device.startswith("cuda")
        if self._require_gpu and (torch is None or not torch.cuda.is_available() or not using_cuda):
            raise RuntimeError(
                f"YOLO motion detector requires GPU but device={self._device}, cuda_available="
                f"{False if torch is None else torch.cuda.is_available()}"
            )

        self._model = YOLO(self._model_path)
        if using_cuda:
            self._model.to(self._device)
        self._last_emit_mono = 0.0
        self._initialized = True

    def process(self, frame: Any) -> list[DetectionResult]:
        if not self._initialized or self._model is None:
            return []
        frame_bgr = as_bgr_frame(frame)
        if frame_bgr is None or not hasattr(frame_bgr, "shape"):
            return []

        try:
            predictions = self._predict(frame_bgr)
        except Exception as exc:
            if self._handle_cuda_runtime_error(exc):
                try:
                    predictions = self._predict(frame_bgr)
                except Exception as retry_exc:
                    logger.error("YOLO motion inference failed after CPU fallback: %s", retry_exc)
                    return []
            else:
                logger.error("YOLO motion inference failed: %s", exc)
                return []

        if not predictions:
            return []
        boxes = getattr(predictions[0], "boxes", None)
        if boxes is None or len(boxes) == 0:
            return []

        now_mono = monotonic()
        if now_mono - self._last_emit_mono < self._cooldown_s:
            return []
        self._last_emit_mono = now_mono

        confidences = boxes.conf.detach().cpu().numpy().tolist() if hasattr(boxes, "conf") else [0.5]
        max_conf = float(max(confidences)) if confidences else 0.5
        xyxy = boxes.xyxy.detach().cpu().numpy().tolist() if hasattr(boxes, "xyxy") else []

        return [
            DetectionResult(
                trace_id=new_trace_id(),
                source=self.source,
                detector=self.name,
                event_type="motion",
                timestamp=time(),
                confidence=max_conf,
                payload={
                    "motion_boxes": xyxy,
                    "count": len(xyxy),
                    "backend": "yolo",
                    "device": self._device,
                },
            )
        ]

    def _predict(self, frame: Any) -> Any:
        return self._model.predict(
            source=frame,
            conf=self._conf_threshold,
            iou=self._iou_threshold,
            classes=self._classes,
            device=self._device,
            imgsz=self._imgsz,
            max_det=self._max_det,
            half=self._half and self._device.startswith("cuda"),
            verbose=False,
        )

    @staticmethod
    def _coerce_positive_int(value: Any, *, default: int) -> int:
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            return default
        return resolved if resolved > 0 else default

    def _handle_cuda_runtime_error(self, exc: Exception) -> bool:
        if self._require_gpu:
            return False
        if not self._allow_cuda_fallback:
            return False
        if not isinstance(exc, Exception):
            return False
        if not self._device.startswith("cuda"):
            return False

        message = str(exc).lower()
        if "cuda" not in message:
            return False

        try:
            if torch is not None and torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
        except Exception:
            pass

        self._device = "cpu"
        if self._model is not None:
            try:
                self._model.to("cpu")
            except Exception:
                pass
        if not self._cuda_fallback_triggered:
            logger.warning("YOLO motion encountered CUDA runtime error. Fallback to CPU for stability.")
            self._cuda_fallback_triggered = True
        return True

    def close(self) -> None:
        self._model = None
        self._initialized = False
