from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import logging
import multiprocessing as mp
from multiprocessing import shared_memory as mp_shared_memory
import os
import queue as stdlib_queue
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
import math
import shutil
import subprocess
import sys
import threading
from time import monotonic
from typing import Any, Deque, Mapping, Optional, Union

try:
    import numpy as _np
except ImportError:  # pragma: no cover - optional dependency
    _np = None


logger = logging.getLogger(__name__)

_DEFAULT_CAMERA_SHARED_FRAME_BYTES = 1920 * 1080 * 3


def _camera_read_worker_count() -> int:
    default_workers = max(1, min(4, int(os.cpu_count() or 2)))
    raw_value = os.getenv("ROBOT_LIFE_CAMERA_READ_WORKERS")
    if raw_value not in {None, ""}:
        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            logger.warning("invalid ROBOT_LIFE_CAMERA_READ_WORKERS=%r; fallback=%s", raw_value, default_workers)
    if sys.platform == "darwin":
        # AVFoundation capture can segfault when cv2.VideoCapture.read() runs from
        # a Python worker thread. Keep macOS camera reads on the caller thread.
        return 0
    return default_workers


def _camera_shared_frame_capacity_bytes(width: int | None, height: int | None) -> int:
    if width is not None and height is not None and width > 0 and height > 0:
        estimated = int(width) * int(height) * 3
        return max(estimated + (64 * 1024), estimated)
    return _DEFAULT_CAMERA_SHARED_FRAME_BYTES


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _score_input_device_name(name: str) -> int:
    normalized = str(name).strip().lower()
    if not normalized:
        return -100

    score = 0
    builtin_tokens = (
        "macbook pro",
        "macbook air",
        "built-in",
        "builtin",
        "内建",
        "內建",
    )
    virtual_tokens = (
        "zoom",
        "wemeet",
        "lark",
        "loopback",
        "blackhole",
        "aggregate",
        "virtual",
        "continuity",
    )
    bluetooth_tokens = ("airpods", "bluetooth", "beats")

    if "mic" in normalized or "microphone" in normalized or "麦克风" in normalized:
        score += 8
    if any(token in normalized for token in builtin_tokens):
        score += 100
    if any(token in normalized for token in virtual_tokens):
        score -= 60
    if any(token in normalized for token in bluetooth_tokens):
        score -= 25
    return score


def _select_preferred_input_index(
    devices: list[dict[str, Any]],
    *,
    default_input_index: int | None,
    prefer_builtin: bool,
) -> int | None:
    if default_input_index is not None and default_input_index >= 0:
        return default_input_index

    best_index: int | None = None
    best_score: int | None = None
    for index, info in enumerate(devices):
        if not isinstance(info, dict):
            continue
        if int(info.get("max_input_channels", 0)) <= 0:
            continue
        name = str(info.get("name", "")).strip()
        score = _score_input_device_name(name)
        if not prefer_builtin:
            score = max(score, 0)
        if best_score is None or score > best_score:
            best_index = index
            best_score = score
    return best_index


def microphone_source_options_from_detector_cfg(detector_cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(detector_cfg, Mapping):
        return {}
    detector_global = detector_cfg.get("detector_global", {})
    if not isinstance(detector_global, Mapping):
        return {}

    resolved: dict[str, Any] = {
        "prefer_builtin": _coerce_bool(
            detector_global.get("microphone_prefer_builtin"),
            default=sys.platform == "darwin",
        )
    }
    value = detector_global.get("microphone_preferred_device")
    if value not in {None, ""}:
        resolved["preferred_device"] = value
    for key in ("microphone_sample_rate", "microphone_channels", "microphone_blocksize", "microphone_max_buffer_packets"):
        raw_value = detector_global.get(key)
        if raw_value in {None, ""}:
            continue
        try:
            resolved[key.removeprefix("microphone_")] = int(raw_value)
        except (TypeError, ValueError):
            logger.warning("ignoring invalid detector_global.%s=%r", key, raw_value)
    return resolved


@dataclass
class FramePacket:
    """Container for a single source sample."""

    source: str
    payload: Any
    timestamp_monotonic: float = field(default_factory=monotonic)
    frame_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LiveMicrophoneProbe:
    source: FrameSource
    mode: str
    backend: str
    warning: str | None = None
    input_device_count: int = 0
    default_input_index: int | None = None
    selected_device: Any = None
    selected_device_name: str | None = None
    input_device_names: list[str] = field(default_factory=list)
    arecord_available: bool = False


class FrameSource(ABC):
    """Abstract source used by the live runtime."""

    def __init__(self, source_name: str) -> None:
        self.source_name = source_name
        self._opened = False

    @property
    def is_open(self) -> bool:
        return self._opened

    @abstractmethod
    def open(self) -> None:
        """Open the source."""

    @abstractmethod
    def read(self) -> FramePacket | None:
        """Read one packet from the source."""

    @abstractmethod
    def close(self) -> None:
        """Close the source."""

    def recover(self) -> bool:
        """Best-effort recovery hook used by the runtime on read/open failures."""
        try:
            self.close()
        except Exception:  # pragma: no cover - defensive cleanup
            logger.exception("source close failed during recovery: %s", self.source_name)
        try:
            self.open()
        except Exception:
            logger.exception("source recovery failed: %s", self.source_name)
            self._opened = False
            return False
        return True


class CameraSource(FrameSource):
    """OpenCV-backed camera source with lazy dependency loading."""

    _shared_executor: ThreadPoolExecutor | None = None
    _shared_executor_ref_count = 0
    _shared_executor_lock = threading.Lock()
    _shared_executor_workers = _camera_read_worker_count()

    def __init__(
        self,
        device_index: int = 0,
        *,
        source_name: str = "camera",
        backend: int | None = None,
        width: int | None = None,
        height: int | None = None,
        read_timeout_s: float = 0.12,
    ) -> None:
        super().__init__(source_name=source_name)
        self.device_index = device_index
        self.backend = backend
        self.width = width
        self.height = height
        self.read_timeout_s = max(0.02, float(read_timeout_s))
        self._capture: Any = None
        self._frame_index = 0
        self._read_failures = 0
        self.max_read_failures = 3
        self.recovery_cooldown_s = 1.5
        self._read_executor: ThreadPoolExecutor | None = None
        self._last_frame_at: float | None = None
        self._last_failure_at: float | None = None
        self._last_recovery_at: float | None = None
        self._recovery_count = 0
        self._total_failures = 0
        self._backend_name = "default"
        self._read_future: Future[tuple[bool, Any]] | None = None
        self.timeout_warning_interval_s = 2.0
        self._last_timeout_warning_at = 0.0

    @classmethod
    def _acquire_shared_executor(cls) -> ThreadPoolExecutor:
        if cls._shared_executor_workers <= 0:
            raise RuntimeError("camera read executor disabled")
        with cls._shared_executor_lock:
            if cls._shared_executor is None:
                cls._shared_executor = ThreadPoolExecutor(
                    max_workers=cls._shared_executor_workers,
                    thread_name_prefix="camera-read",
                )
            cls._shared_executor_ref_count += 1
            return cls._shared_executor

    @classmethod
    def _release_shared_executor(cls, executor: ThreadPoolExecutor | None) -> None:
        if executor is None:
            return
        with cls._shared_executor_lock:
            if executor is not cls._shared_executor:
                return
            cls._shared_executor_ref_count = max(0, cls._shared_executor_ref_count - 1)
            if cls._shared_executor_ref_count == 0 and cls._shared_executor is not None:
                cls._shared_executor.shutdown(wait=False, cancel_futures=True)
                cls._shared_executor = None

    def _should_emit_timeout_warning(self) -> bool:
        now = monotonic()
        if (now - self._last_timeout_warning_at) >= self.timeout_warning_interval_s:
            self._last_timeout_warning_at = now
            return True
        return False

    def _open_capture(self, cv2: Any, backend: int | None) -> Any:
        if backend is None:
            return cv2.VideoCapture(self.device_index)
        return cv2.VideoCapture(self.device_index, backend)

    def open(self) -> None:
        try:
            import cv2
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("opencv-python is required for CameraSource") from exc

        preferred_backend = self.backend
        if preferred_backend is None and sys.platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
            preferred_backend = int(cv2.CAP_AVFOUNDATION)

        capture = self._open_capture(cv2, preferred_backend)
        if not capture.isOpened() and preferred_backend is not None:
            capture.release()
            capture = self._open_capture(cv2, None)

        if not capture.isOpened():
            raise RuntimeError(f"Failed to open camera device {self.device_index}")

        if self.width:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
        if self.height:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            try:
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1.0)
            except Exception:
                logger.debug("failed to set camera buffer size", exc_info=True)

        self._capture = capture
        self._opened = True
        self._read_failures = 0
        self._last_failure_at = None
        self._read_future = None
        if hasattr(capture, "getBackendName"):
            try:
                self._backend_name = str(capture.getBackendName() or self._backend_name)
            except Exception:
                self._backend_name = "default"
        if self._read_executor is None and self._shared_executor_workers > 0:
            self._read_executor = self._acquire_shared_executor()

    def _read_once(self) -> tuple[bool, Any]:
        if self._capture is None:
            return False, None

        executor = self._read_executor
        if executor is None:
            try:
                return self._capture.read()
            except Exception:
                return False, None

        if self._read_future is None:
            self._read_future = executor.submit(self._capture.read)
        future = self._read_future
        try:
            result = future.result(timeout=self.read_timeout_s)
            self._read_future = None
            return result
        except FutureTimeoutError:
            if self._should_emit_timeout_warning():
                logger.warning(
                    "camera read timed out after %.2fs (device=%s)",
                    self.read_timeout_s,
                    self.device_index,
                )
            return False, None
        except Exception:
            self._read_future = None
            return False, None

    def read(self) -> FramePacket | None:
        if not self._opened or self._capture is None:
            return None

        ok, frame = self._read_once()
        if not ok:
            self._read_failures += 1
            self._total_failures += 1
            self._last_failure_at = monotonic()
            if self._read_failures >= self.max_read_failures:
                can_recover = (
                    self._last_recovery_at is None
                    or (monotonic() - self._last_recovery_at) >= self.recovery_cooldown_s
                )
                if can_recover:
                    logger.warning(
                        "camera read failed %s times, attempting recovery (device=%s)",
                        self._read_failures,
                        self.device_index,
                    )
                    self._read_failures = 0
                    self._recovery_count += 1
                    self._last_recovery_at = monotonic()
                    self.recover()
            return None

        self._read_failures = 0
        self._frame_index += 1
        self._last_frame_at = monotonic()
        return FramePacket(
            source=self.source_name,
            payload=frame,
            frame_index=self._frame_index,
            metadata={
                "source_kind": "camera",
                "device_index": self.device_index,
                "camera_backend": self._backend_name,
            },
        )

    def close(self) -> None:
        if self._read_future is not None:
            self._read_future.cancel()
            self._read_future = None
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        if self._read_executor is not None:
            self._release_shared_executor(self._read_executor)
            self._read_executor = None
        self._opened = False

    def snapshot_health(self) -> dict[str, Any]:
        return {
            "device_index": self.device_index,
            "read_timeout_s": self.read_timeout_s,
            "read_failures": self._read_failures,
            "total_failures": self._total_failures,
            "recovery_count": self._recovery_count,
            "last_frame_at": self._last_frame_at,
            "last_failure_at": self._last_failure_at,
            "last_recovery_at": self._last_recovery_at,
            "backend": self._backend_name,
        }


def _camera_process_worker(
    *,
    device_index: int,
    backend: int | None,
    width: int | None,
    height: int | None,
    shared_memory_name: str,
    shared_frame_capacity: int,
    shared_frame_lock: Any,
    frame_queue: Any,
    stop_event: Any,
) -> None:
    try:
        import cv2
    except ImportError:
        return

    try:
        shared_frame = mp_shared_memory.SharedMemory(name=shared_memory_name)
    except Exception:
        return

    preferred_backend = backend
    if preferred_backend is None and sys.platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
        preferred_backend = int(cv2.CAP_AVFOUNDATION)

    def _open_capture(selected_backend: int | None):
        if selected_backend is None:
            return cv2.VideoCapture(device_index)
        return cv2.VideoCapture(device_index, selected_backend)

    capture = _open_capture(preferred_backend)
    if not capture.isOpened() and preferred_backend is not None:
        capture.release()
        capture = _open_capture(None)
    if not capture.isOpened():
        capture.release()
        return

    if width:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
    if height:
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1.0)
        except Exception:
            pass

    backend_name = "default"
    if hasattr(capture, "getBackendName"):
        try:
            backend_name = str(capture.getBackendName() or backend_name)
        except Exception:
            backend_name = "default"

    frame_index = 0
    try:
        while not stop_event.is_set():
            try:
                ok, frame = capture.read()
            except Exception:
                ok, frame = False, None
            if not ok:
                continue
            if _np is None:
                continue
            frame_array = _np.asarray(frame, dtype=_np.uint8)
            if frame_array.ndim != 3:
                continue
            frame_array = _np.ascontiguousarray(frame_array)
            frame_bytes = int(frame_array.nbytes)
            if frame_bytes <= 0 or frame_bytes > shared_frame_capacity:
                continue
            frame_index += 1
            payload = {
                "frame_index": frame_index,
                "captured_at": monotonic(),
                "backend": backend_name,
                "shape": tuple(int(dim) for dim in frame_array.shape),
                "dtype": str(frame_array.dtype),
                "frame_bytes": frame_bytes,
            }
            with shared_frame_lock:
                shared_frame.buf[:frame_bytes] = frame_array.reshape(-1).view(_np.uint8)
            while not stop_event.is_set():
                try:
                    frame_queue.put_nowait(payload)
                    break
                except stdlib_queue.Full:
                    try:
                        frame_queue.get_nowait()
                    except stdlib_queue.Empty:
                        break
    finally:
        capture.release()
        try:
            shared_frame.close()
        except Exception:
            pass


class ProcessCameraSource(FrameSource):
    """Camera source that owns OpenCV capture inside a child process."""

    def __init__(
        self,
        device_index: int = 0,
        *,
        source_name: str = "camera",
        backend: int | None = None,
        width: int | None = None,
        height: int | None = None,
        read_timeout_s: float = 0.12,
        queue_size: int = 2,
    ) -> None:
        super().__init__(source_name=source_name)
        self.device_index = int(device_index)
        self.backend = backend
        self.width = width
        self.height = height
        self.read_timeout_s = max(0.02, float(read_timeout_s))
        self.queue_size = max(1, int(queue_size))
        self._ctx = mp.get_context("spawn")
        self._frame_queue: Any = None
        self._stop_event: Any = None
        self._shared_frame_lock: Any = None
        self._shared_frame: mp_shared_memory.SharedMemory | None = None
        self._shared_frame_capacity = _camera_shared_frame_capacity_bytes(width, height)
        self._process: mp.Process | None = None
        self._backend_name = "process"
        self._frame_index = 0
        self._last_frame_at: float | None = None
        self._opened_at: float = 0.0
        self._last_recovery_at: float | None = None
        self._total_failures = 0
        self._recovery_count = 0
        self.recovery_cooldown_s = 1.5

    def open(self) -> None:
        if self._opened:
            return
        self._shared_frame = mp_shared_memory.SharedMemory(create=True, size=self._shared_frame_capacity)
        self._frame_queue = self._ctx.Queue(maxsize=self.queue_size)
        self._stop_event = self._ctx.Event()
        self._shared_frame_lock = self._ctx.Lock()
        self._process = self._ctx.Process(
            target=_camera_process_worker,
            kwargs={
                "device_index": self.device_index,
                "backend": self.backend,
                "width": self.width,
                "height": self.height,
                "shared_memory_name": self._shared_frame.name,
                "shared_frame_capacity": self._shared_frame_capacity,
                "shared_frame_lock": self._shared_frame_lock,
                "frame_queue": self._frame_queue,
                "stop_event": self._stop_event,
            },
            daemon=True,
            name=f"camera-process-{self.device_index}",
        )
        self._process.start()
        self._opened_at = monotonic()
        self._opened = True

    @property
    def _idle_recover_s(self) -> float:
        return max(0.5, self.read_timeout_s * 4.0)

    def _should_attempt_recovery(self, *, now: float, process_alive: bool) -> bool:
        if self._last_recovery_at is not None and (now - self._last_recovery_at) < self.recovery_cooldown_s:
            return False
        if not process_alive:
            return True
        last_frame_at = self._last_frame_at
        if last_frame_at is not None:
            return (now - last_frame_at) >= self._idle_recover_s
        return (now - self._opened_at) >= self._idle_recover_s

    def read(self) -> FramePacket | None:
        if not self._opened:
            return None
        latest: dict[str, Any] | None = None
        frame_queue = self._frame_queue
        if frame_queue is None:
            return None
        while True:
            try:
                latest = frame_queue.get_nowait()
            except stdlib_queue.Empty:
                break
            except Exception:
                self._total_failures += 1
                break
        if latest is None:
            now = monotonic()
            process = self._process
            process_alive = bool(process is not None and process.is_alive())
            if not process_alive:
                self._total_failures += 1
            if self._should_attempt_recovery(now=now, process_alive=process_alive):
                self._last_recovery_at = now
                self.recover()
            return None
        self._frame_index = int(latest.get("frame_index", self._frame_index + 1) or 0)
        self._last_frame_at = monotonic()
        self._backend_name = str(latest.get("backend") or self._backend_name)
        payload = None
        if _np is not None and self._shared_frame is not None:
            shape = latest.get("shape")
            frame_bytes = int(latest.get("frame_bytes", 0) or 0)
            if isinstance(shape, (tuple, list)) and len(shape) == 3 and frame_bytes > 0:
                try:
                    height, width, channels = (int(shape[0]), int(shape[1]), int(shape[2]))
                    if height > 0 and width > 0 and channels > 0:
                        with self._shared_frame_lock:
                            view = _np.ndarray(
                                (height, width, channels),
                                dtype=_np.uint8,
                                buffer=self._shared_frame.buf,
                                strides=(width * channels, channels, 1),
                            )
                            payload = view.copy()
                except Exception:
                    payload = None
        return FramePacket(
            source=self.source_name,
            payload=payload,
            frame_index=self._frame_index,
            metadata={
                "source_kind": "camera",
                "device_index": self.device_index,
                "camera_backend": self._backend_name,
                "camera_transport": "process_shared_memory",
            },
        )

    def close(self) -> None:
        stop_event = self._stop_event
        process = self._process
        shared_frame = self._shared_frame
        self._stop_event = None
        self._process = None
        self._shared_frame = None
        if stop_event is not None:
            stop_event.set()
        if process is not None and process.is_alive():
            process.join(timeout=2.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
        self._frame_queue = None
        self._shared_frame_lock = None
        if shared_frame is not None:
            try:
                shared_frame.close()
            except Exception:
                logger.warning("failed to close camera shared memory device=%s", self.device_index)
            try:
                shared_frame.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                logger.warning("failed to unlink camera shared memory device=%s", self.device_index)
        self._opened = False

    def recover(self) -> bool:
        self._recovery_count += 1
        return super().recover()

    def snapshot_health(self) -> dict[str, Any]:
        process = self._process
        return {
            "device_index": self.device_index,
            "read_timeout_s": self.read_timeout_s,
            "read_failures": 0,
            "total_failures": self._total_failures,
            "recovery_count": self._recovery_count,
            "last_frame_at": self._last_frame_at,
            "last_recovery_at": self._last_recovery_at,
            "backend": self._backend_name,
            "transport": "process_shared_memory",
            "process_alive": bool(process is not None and process.is_alive()),
            "shared_frame_capacity": self._shared_frame_capacity,
        }


class SyntheticCameraSource(FrameSource):
    """Synthetic frame source for local mock-driver development."""

    def __init__(self, *, source_name: str = "camera") -> None:
        super().__init__(source_name=source_name)
        self._frame_index = 0

    def open(self) -> None:
        self._opened = True

    def read(self) -> FramePacket | None:
        if not self._opened:
            return None
        self._frame_index += 1
        return FramePacket(
            source=self.source_name,
            payload={"synthetic_frame": True, "frame_index": self._frame_index},
            frame_index=self._frame_index,
        )

    def close(self) -> None:
        self._opened = False


class SyntheticMicrophoneSource(FrameSource):
    """Synthetic microphone source for local mock-driver development."""

    def __init__(self, *, source_name: str = "microphone") -> None:
        super().__init__(source_name=source_name)
        self._frame_index = 0

    def open(self) -> None:
        self._opened = True

    def read(self) -> FramePacket | None:
        if not self._opened:
            return None
        self._frame_index += 1
        return FramePacket(
            source=self.source_name,
            payload={"synthetic_audio": True, "frame_index": self._frame_index},
            frame_index=self._frame_index,
        )

    def close(self) -> None:
        self._opened = False


class MicrophoneSource(FrameSource):
    """Microphone abstraction that can be backed by a future hardware adapter."""

    def __init__(self, *, source_name: str = "microphone") -> None:
        super().__init__(source_name=source_name)
        self._buffer: Deque[FramePacket] = deque()
        self._frame_index = 0

    def open(self) -> None:
        self._opened = True

    def push(self, payload: Any, metadata: dict[str, Any] | None = None) -> None:
        """Inject a sample into the source buffer."""
        self._frame_index += 1
        self._buffer.append(
            FramePacket(
                source=self.source_name,
                payload=payload,
                frame_index=self._frame_index,
                metadata=metadata or {},
            )
        )

    def read(self) -> FramePacket | None:
        if not self._opened:
            return None
        if not self._buffer:
            return None
        return self._buffer.popleft()

    def close(self) -> None:
        self._buffer.clear()
        self._opened = False

    def snapshot_health(self) -> dict[str, Any]:
        return {
            "source_kind": "microphone",
            "mode": "fallback",
            "backend": "silent",
            "status": "silent_fallback",
            "buffer_depth": len(self._buffer),
        }


class SoundDeviceMicrophoneSource(FrameSource):
    """Real microphone source backed by sounddevice InputStream."""

    def __init__(
        self,
        *,
        source_name: str = "microphone",
        device: Any = None,
        sample_rate: int = 16_000,
        channels: int = 1,
        blocksize: int = 1024,
        max_buffer_packets: int = 32,
    ) -> None:
        super().__init__(source_name=source_name)
        self.device = device
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.blocksize = int(blocksize)
        self._frame_index = 0
        self._stream: Any = None
        self._buffer: Deque[FramePacket] = deque(maxlen=max(1, int(max_buffer_packets)))
        self._dropped_packets = 0
        self._last_rms: float | None = None
        self._last_db: float | None = None
        self._last_packet_at: float | None = None

    @property
    def max_buffer_packets(self) -> int:
        return self._buffer.maxlen or 1

    def _enqueue_packet(self, packet: FramePacket) -> None:
        if len(self._buffer) >= self.max_buffer_packets:
            self._dropped_packets += 1
            self._buffer.popleft()
        self._buffer.append(packet)

    def open(self) -> None:
        try:
            import sounddevice as sd  # type: ignore
        except Exception as exc:
            raise RuntimeError("sounddevice is required for SoundDeviceMicrophoneSource") from exc

        def _callback(indata, frames, time_info, status) -> None:
            self._frame_index += 1
            payload = indata.copy()
            metadata = {"frames": int(frames), "status": str(status) if status else ""}
            rms, db = self._compute_level(payload)
            if rms is not None:
                self._last_rms = rms
                self._last_db = db
                self._last_packet_at = monotonic()
            self._enqueue_packet(
                FramePacket(
                    source=self.source_name,
                    payload=payload,
                    frame_index=self._frame_index,
                    metadata=metadata,
                )
            )

        self._stream = sd.InputStream(
            device=self.device,
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=self.blocksize,
            dtype="float32",
            callback=_callback,
        )
        self._stream.start()
        self._opened = True

    def read(self) -> FramePacket | None:
        if not self._opened:
            return None
        if not self._buffer:
            return None
        return self._buffer.popleft()

    def close(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                logger.warning("failed to stop microphone stream %s", self.source_name)
            try:
                stream.close()
            except Exception:
                logger.warning("failed to close microphone stream %s", self.source_name)
        self._buffer.clear()
        self._opened = False
        self._last_rms = None
        self._last_db = None
        self._last_packet_at = None

    @staticmethod
    def _compute_level(samples: Any) -> tuple[float | None, float | None]:
        try:
            if _np is not None:
                array = _np.asarray(samples, dtype=_np.float64).reshape(-1)
                if array.size == 0:
                    return None, None
                rms = float(_np.sqrt(_np.mean(_np.square(array))))
                db = float(20.0 * math.log10(max(rms, 1e-12)))
                return rms, db
            values = [float(item) for item in samples]
            if not values:
                return None, None
            rms = math.sqrt(sum(item * item for item in values) / len(values))
            db = 20.0 * math.log10(max(rms, 1e-12))
            return float(rms), float(db)
        except Exception:
            return None, None

    def snapshot_health(self) -> dict[str, Any]:
        return {
            "source_kind": "sounddevice",
            "mode": "real",
            "backend": "sounddevice",
            "status": "ready" if self._opened else "closed",
            "buffer_depth": len(self._buffer),
            "max_buffer_packets": self.max_buffer_packets,
            "dropped_packets": self._dropped_packets,
            "device": None if self.device is None else str(self.device),
            "audio_rms": None if self._last_rms is None else round(float(self._last_rms), 6),
            "audio_db": None if self._last_db is None else round(float(self._last_db), 2),
            "last_packet_age_ms": (
                None if self._last_packet_at is None else round((monotonic() - self._last_packet_at) * 1000.0, 2)
            ),
        }


class ArecordMicrophoneSource(FrameSource):
    """Real microphone source backed by `arecord` and ALSA/PulseAudio."""

    def __init__(
        self,
        *,
        source_name: str = "microphone",
        device: str = "default",
        sample_rate: int = 16_000,
        channels: int = 1,
        chunk_frames: int = 1024,
        max_buffer_packets: int = 32,
    ) -> None:
        super().__init__(source_name=source_name)
        self.device = str(device)
        self.sample_rate = int(sample_rate)
        self.channels = max(1, int(channels))
        self.chunk_frames = max(64, int(chunk_frames))
        self._frame_index = 0
        self._buffer: Deque[FramePacket] = deque(maxlen=max(1, int(max_buffer_packets)))
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def open(self) -> None:
        if shutil.which("arecord") is None:
            raise RuntimeError("arecord is required for ArecordMicrophoneSource")

        if self._opened:
            return

        cmd = [
            "arecord",
            "-q",
            "-D",
            self.device,
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            str(self.channels),
            "-t",
            "raw",
        ]
        self._stop_event.clear()
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if self._process.stdout is None:
            raise RuntimeError("arecord stdout pipe unavailable")
        self._opened = True
        self._reader_thread = threading.Thread(target=self._reader_loop, name="arecord-mic", daemon=True)
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        bytes_per_sample = 2
        frame_bytes = self.chunk_frames * self.channels * bytes_per_sample
        while not self._stop_event.is_set():
            try:
                raw = process.stdout.read(frame_bytes)
            except Exception:
                break
            if not raw:
                break
            audio = self._decode_audio(raw)
            if audio is None:
                continue
            self._frame_index += 1
            self._buffer.append(
                FramePacket(
                    source=self.source_name,
                    payload={
                        "audio": audio,
                        "sample_rate": self.sample_rate,
                        "channels": self.channels,
                        "device": self.device,
                        "source_kind": "arecord",
                    },
                    frame_index=self._frame_index,
                    metadata={"raw_bytes": len(raw)},
                )
            )

    def _decode_audio(self, raw: bytes) -> Any | None:
        if not raw:
            return None
        if _np is None:
            return None
        try:
            audio = _np.frombuffer(raw, dtype=_np.int16).astype(_np.float32)
            if audio.size == 0:
                return None
            audio = audio / 32768.0
            return audio.reshape(-1)
        except Exception:
            return None

    def read(self) -> FramePacket | None:
        if not self._opened:
            return None
        if not self._buffer:
            return None
        return self._buffer.popleft()

    def close(self) -> None:
        self._stop_event.set()
        process = self._process
        self._process = None
        if process is not None:
            try:
                process.terminate()
            except Exception:
                logger.warning("failed to terminate arecord process %s", self.source_name)
            try:
                process.wait(timeout=1.0)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    logger.warning("failed to kill arecord process %s", self.source_name)
        thread = self._reader_thread
        self._reader_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._buffer.clear()
        self._opened = False

    def snapshot_health(self) -> dict[str, Any]:
        return {
            "source_kind": "arecord",
            "mode": "real",
            "backend": "arecord",
            "status": "ready" if self._opened else "closed",
            "buffer_depth": len(self._buffer),
            "device": self.device,
        }


@dataclass
class SourceBundle:
    """Convenience wrapper for a set of sources."""

    camera: FrameSource | None = None
    microphone: FrameSource | None = None

    def open_all(self) -> None:
        for source in self.iter_sources():
            try:
                source.open()
            except Exception as exc:
                logger.warning("failed to open source %s: %s", source.source_name, exc)

    def close_all(self) -> None:
        for source in self.iter_sources():
            try:
                source.close()
            except Exception as exc:
                logger.warning("failed to close source %s: %s", source.source_name, exc)

    def iter_sources(self) -> list[FrameSource]:
        sources: list[FrameSource] = []
        if self.camera is not None:
            sources.append(self.camera)
        if self.microphone is not None:
            sources.append(self.microphone)
        return sources

    def read_packets(self) -> dict[str, FramePacket]:
        packets: dict[str, FramePacket] = {}
        for source in self.iter_sources():
            try:
                packet = source.read()
            except Exception as exc:
                logger.warning("source read failed for %s: %s", source.source_name, exc)
                source.recover()
                continue
            if packet is not None:
                packets[source.source_name] = packet
        return packets

    def read_payloads(self) -> dict[str, Any]:
        return {name: packet.payload for name, packet in self.read_packets().items()}

    def snapshot_health(self) -> dict[str, Any]:
        health: dict[str, Any] = {}
        for source in self.iter_sources():
            snapshot_fn = getattr(source, "snapshot_health", None)
            if callable(snapshot_fn):
                try:
                    health[source.source_name] = snapshot_fn()
                except Exception as exc:
                    health[source.source_name] = {"snapshot_error": str(exc)}
        return health


def probe_live_microphone_source(
    *,
    arecord_device: str = "default",
    preferred_device: Any = None,
    prefer_builtin: bool = sys.platform == "darwin",
    sample_rate: int = 16_000,
    channels: int = 1,
    blocksize: int = 1024,
    max_buffer_packets: int = 32,
) -> LiveMicrophoneProbe:
    """Probe microphone availability and choose the best source for this machine."""
    reason: str | None = None
    default_input_index: int | None = None
    input_device_count = 0
    selected_device: Any = None
    selected_device_name: str | None = None
    input_device_names: list[str] = []
    arecord_available = shutil.which("arecord") is not None
    try:
        import sounddevice  # noqa: F401

        try:
            import sounddevice as sd  # type: ignore

            devices = sd.query_devices()
        except Exception as exc:
            reason = f"sounddevice 不可用 ({exc}); "
        else:
            requested_device: Any = preferred_device
            if requested_device in {None, ""}:
                requested_device = os.environ.get("ROBOT_LIFE_MIC_DEVICE")
            if isinstance(requested_device, str):
                requested_device = requested_device.strip()
                if requested_device.lower() in {"", "auto", "default"}:
                    requested_device = None

            default_config = getattr(sd, "default", None)
            raw_default_device = getattr(default_config, "device", default_config)
            if isinstance(raw_default_device, (list, tuple)) and raw_default_device:
                try:
                    default_input_index = int(raw_default_device[0])
                except (TypeError, ValueError):
                    default_input_index = None
            elif isinstance(raw_default_device, int):
                default_input_index = raw_default_device

            usable_input_index: int | None = None
            try:
                normalized_devices = list(devices)
            except Exception:
                normalized_devices = []
            input_device_names = [
                str(info.get("name", "")).strip()
                for info in normalized_devices
                if isinstance(info, dict) and int(info.get("max_input_channels", 0)) > 0
            ]
            input_device_count = sum(
                1
                for info in normalized_devices
                if isinstance(info, dict) and int(info.get("max_input_channels", 0)) > 0
            )

            if requested_device is not None:
                requested_index: int | None = None
                if isinstance(requested_device, int):
                    requested_index = requested_device
                elif isinstance(requested_device, str):
                    try:
                        requested_index = int(requested_device)
                    except (TypeError, ValueError):
                        requested_index = None

                if requested_index is not None and requested_index >= 0:
                    try:
                        requested_info = sd.query_devices(requested_index, "input")
                    except Exception:
                        requested_info = None
                    if isinstance(requested_info, dict) and int(requested_info.get("max_input_channels", 0)) > 0:
                        usable_input_index = requested_index
                    else:
                        reason = f"指定麦克风设备 {requested_device} 不可用; "
                elif isinstance(requested_device, str):
                    requested_text = requested_device.lower()
                    for index, info in enumerate(normalized_devices):
                        if not isinstance(info, dict):
                            continue
                        if int(info.get("max_input_channels", 0)) <= 0:
                            continue
                        name = str(info.get("name", "")).lower()
                        if requested_text in name:
                            usable_input_index = index
                            break
                    if usable_input_index is None:
                        reason = f"未找到匹配麦克风设备名: {requested_device}; "

            if usable_input_index is None and default_input_index is not None and default_input_index >= 0:
                try:
                    default_info = sd.query_devices(default_input_index, "input")
                except Exception:
                    default_info = None
                if isinstance(default_info, dict) and int(default_info.get("max_input_channels", 0)) > 0:
                    usable_input_index = default_input_index

            if usable_input_index is None:
                usable_input_index = _select_preferred_input_index(
                    normalized_devices,
                    default_input_index=default_input_index,
                    prefer_builtin=prefer_builtin,
                )

            if usable_input_index is not None:
                selected_device = usable_input_index
                try:
                    selected_info = sd.query_devices(usable_input_index, "input")
                except Exception:
                    selected_info = None
                if isinstance(selected_info, dict):
                    selected_device_name = str(selected_info.get("name", "")).strip() or None
                return LiveMicrophoneProbe(
                    source=SoundDeviceMicrophoneSource(
                        device=usable_input_index,
                        sample_rate=sample_rate,
                        channels=channels,
                        blocksize=blocksize,
                        max_buffer_packets=max_buffer_packets,
                    ),
                    mode="real",
                    backend="sounddevice",
                    warning=None,
                    input_device_count=input_device_count,
                    default_input_index=default_input_index,
                    selected_device=selected_device,
                    selected_device_name=selected_device_name,
                    input_device_names=input_device_names,
                    arecord_available=arecord_available,
                )
            reason = "sounddevice 未发现可用输入设备; "
    except Exception as exc:
        reason = f"sounddevice 不可用 ({exc}); "

    if arecord_available:
        return LiveMicrophoneProbe(
            source=ArecordMicrophoneSource(device=arecord_device),
            mode="real",
            backend="arecord",
            warning=f"{reason}已切换到 arecord 真实麦克风模式",
            input_device_count=input_device_count,
            default_input_index=default_input_index,
            selected_device=arecord_device,
            selected_device_name=f"arecord:{arecord_device}",
            input_device_names=input_device_names,
            arecord_available=True,
        )

    if sys.platform == "darwin":
        fallback_warning = (
            f"{reason}当前已切换到静音麦克风模式；"
            "请检查“系统设置 -> 隐私与安全性 -> 麦克风”以及系统默认输入设备。"
        )
    else:
        fallback_warning = f"{reason}未找到 arecord，已切换到静音麦克风模式"
    return LiveMicrophoneProbe(
        source=MicrophoneSource(),
        mode="fallback",
        backend="silent",
        warning=fallback_warning,
        input_device_count=input_device_count,
        default_input_index=default_input_index,
        selected_device_name=selected_device_name,
        input_device_names=input_device_names,
        arecord_available=arecord_available,
    )


def build_live_microphone_source(
    *,
    arecord_device: str = "default",
    preferred_device: Any = None,
    prefer_builtin: bool = sys.platform == "darwin",
    sample_rate: int = 16_000,
    channels: int = 1,
    blocksize: int = 1024,
    max_buffer_packets: int = 32,
) -> tuple[FrameSource, str | None]:
    """Choose the best available live microphone source for this machine."""
    probe = probe_live_microphone_source(
        arecord_device=arecord_device,
        preferred_device=preferred_device,
        prefer_builtin=prefer_builtin,
        sample_rate=sample_rate,
        channels=channels,
        blocksize=blocksize,
        max_buffer_packets=max_buffer_packets,
    )
    return probe.source, probe.warning


def build_live_camera_source(
    *,
    device_index: int = 0,
    read_timeout_s: float = 0.12,
    backend: int | None = None,
    width: int | None = None,
    height: int | None = None,
) -> FrameSource:
    raw_prefer_process = os.getenv("ROBOT_LIFE_CAMERA_PROCESS_CAPTURE")
    prefer_process = sys.platform == "darwin"
    if raw_prefer_process not in {None, ""}:
        prefer_process = _coerce_bool(raw_prefer_process, default=prefer_process)
    if prefer_process:
        return ProcessCameraSource(
            device_index=device_index,
            backend=backend,
            width=width,
            height=height,
            read_timeout_s=read_timeout_s,
        )
    return CameraSource(
        device_index=device_index,
        backend=backend,
        width=width,
        height=height,
        read_timeout_s=read_timeout_s,
    )
