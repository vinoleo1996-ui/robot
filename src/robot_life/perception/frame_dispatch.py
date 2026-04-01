from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover - optional runtime dependency
    import cv2
except Exception:  # pragma: no cover - optional runtime dependency
    cv2 = None

try:  # pragma: no cover - optional runtime dependency
    import numpy as np
except Exception:  # pragma: no cover - optional runtime dependency
    np = None


@dataclass
class CameraFrameDispatch:
    """Centralized camera frame cache shared across perception pipelines."""

    frame_seq: int
    collected_at: float
    _bgr: Any
    _rgb: Any = None
    _rgba: Any = None
    _gray: Any = None

    @property
    def bgr(self) -> Any:
        return self._bgr

    @property
    def shape(self) -> Any:
        return getattr(self._bgr, "shape", None)

    def rgb(self) -> Any:
        if self._rgb is None:
            if cv2 is None:
                raise RuntimeError("opencv-python is required for RGB conversion")
            self._rgb = cv2.cvtColor(self._bgr, cv2.COLOR_BGR2RGB)
        return self._rgb

    def rgba(self) -> Any:
        if self._rgba is None:
            if cv2 is None:
                raise RuntimeError("opencv-python is required for RGBA conversion")
            self._rgba = cv2.cvtColor(self._bgr, cv2.COLOR_BGR2RGBA)
        return self._rgba

    def gray(self) -> Any:
        if self._gray is None:
            if cv2 is None:
                raise RuntimeError("opencv-python is required for grayscale conversion")
            self._gray = cv2.cvtColor(self._bgr, cv2.COLOR_BGR2GRAY)
        return self._gray


def build_camera_dispatch(frame: Any, *, frame_seq: int, collected_at: float) -> CameraFrameDispatch | Any:
    """Build a dispatch frame when dependencies and shape are valid, else passthrough."""
    if np is None:
        return frame
    if isinstance(frame, np.ndarray):
        bgr = frame
        if bgr.ndim != 3 or bgr.shape[2] < 3:
            return frame
        if bgr.dtype == np.uint8 and bgr.shape[2] == 3 and bool(getattr(bgr.flags, "c_contiguous", False)):
            return CameraFrameDispatch(
                frame_seq=max(0, int(frame_seq)),
                collected_at=float(collected_at),
                _bgr=bgr,
            )
    try:
        bgr = np.asarray(frame, dtype=np.uint8)
    except Exception:
        return frame
    if bgr.ndim != 3 or bgr.shape[2] < 3:
        return frame
    if bgr.shape[2] == 3 and bgr.dtype == np.uint8 and bool(getattr(bgr.flags, "c_contiguous", False)):
        resolved = bgr
    else:
        resolved = np.ascontiguousarray(bgr[:, :, :3], dtype=np.uint8)
    return CameraFrameDispatch(
        frame_seq=max(0, int(frame_seq)),
        collected_at=float(collected_at),
        _bgr=resolved,
    )


def as_bgr_frame(frame: Any) -> Any:
    if isinstance(frame, CameraFrameDispatch):
        return frame.bgr
    return frame


def as_rgb_frame(frame: Any) -> Any:
    if isinstance(frame, CameraFrameDispatch):
        return frame.rgb()
    if cv2 is None:
        raise RuntimeError("opencv-python is required for RGB conversion")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def as_rgba_frame(frame: Any) -> Any:
    if isinstance(frame, CameraFrameDispatch):
        return frame.rgba()
    if cv2 is None:
        raise RuntimeError("opencv-python is required for RGBA conversion")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)


def as_gray_frame(frame: Any) -> Any:
    if isinstance(frame, CameraFrameDispatch):
        return frame.gray()
    if cv2 is None:
        raise RuntimeError("opencv-python is required for grayscale conversion")
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def frame_seq_of(frame: Any) -> int | None:
    if isinstance(frame, CameraFrameDispatch):
        return frame.frame_seq
    return None
