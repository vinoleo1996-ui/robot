import numpy as np
import pytest

pytest.importorskip("cv2")

from robot_life.perception.adapters.motion_adapter import OpenCVMotionDetector, YOLOMotionDetector


def _blank_frame(value: int = 0) -> np.ndarray:
    return np.full((64, 64, 3), value, dtype=np.uint8)


def test_motion_detector_no_emit_on_first_frame() -> None:
    detector = OpenCVMotionDetector()
    detector.initialize()
    result = detector.process(_blank_frame(0))
    assert result == []


def test_motion_detector_emits_when_frame_changes() -> None:
    detector = OpenCVMotionDetector(
        config={"min_area_ratio": 0.01, "pixel_threshold": 5, "motion_cooldown_sec": 0.0}
    )
    detector.initialize()
    detector.process(_blank_frame(0))
    result = detector.process(_blank_frame(255))
    assert len(result) == 1
    assert result[0].event_type == "motion"
    assert result[0].payload["motion_area_ratio"] > 0.01


def test_motion_detector_respects_cooldown() -> None:
    detector = OpenCVMotionDetector(
        config={"min_area_ratio": 0.01, "pixel_threshold": 5, "motion_cooldown_sec": 10.0}
    )
    detector.initialize()
    detector.process(_blank_frame(0))
    first = detector.process(_blank_frame(255))
    second = detector.process(_blank_frame(0))
    assert len(first) == 1
    assert second == []


def test_motion_detector_filters_oversized_regions() -> None:
    detector = OpenCVMotionDetector(
        config={
            "min_area_ratio": 0.01,
            "min_object_area_ratio": 0.01,
            "max_object_area_ratio": 0.2,
            "pixel_threshold": 5,
            "motion_cooldown_sec": 0.0,
        }
    )
    detector.initialize()
    detector.process(_blank_frame(0))
    result = detector.process(_blank_frame(255))
    assert result == []


def test_motion_detector_suppresses_human_overlap_regions() -> None:
    detector = OpenCVMotionDetector(
        config={
            "min_area_ratio": 0.01,
            "min_object_area_ratio": 0.01,
            "max_object_area_ratio": 1.0,
            "pixel_threshold": 5,
            "motion_cooldown_sec": 0.0,
            "suppress_human_motion": True,
            "human_detect_interval_frames": 99,
        }
    )
    detector.initialize()
    detector.process(_blank_frame(0))
    detector._human_boxes = [(0, 0, 64, 64)]  # noqa: SLF001 - force deterministic overlap gate
    result = detector.process(_blank_frame(255))
    assert result == []


def test_motion_detector_downscale_preserves_original_box_coordinates() -> None:
    detector = OpenCVMotionDetector(
        config={
            "min_area_ratio": 0.001,
            "min_object_area_ratio": 0.001,
            "pixel_threshold": 5,
            "motion_cooldown_sec": 0.0,
            "motion_scale": 0.5,
            "blur_kernel": 1,
            "dilate_iterations": 0,
        }
    )
    detector.initialize()
    first = np.zeros((80, 80, 3), dtype=np.uint8)
    second = np.zeros((80, 80, 3), dtype=np.uint8)
    second[20:60, 20:60] = 255

    detector.process(first)
    result = detector.process(second)

    assert len(result) == 1
    x1, y1, x2, y2 = result[0].payload["motion_boxes"][0]
    assert x1 <= 20 <= x2
    assert y1 <= 20 <= y2
    assert x2 >= 59
    assert y2 >= 59


def test_opencv_motion_detector_rejects_gpu_requirement() -> None:
    detector = OpenCVMotionDetector(config={"require_gpu": True})
    with pytest.raises(RuntimeError):
        detector.initialize()


def test_yolo_motion_detector_falls_back_to_cpu_on_cuda_runtime_error() -> None:
    class _DummyModel:
        def __init__(self) -> None:
            self.last_device = "cuda:0"

        def to(self, device: str) -> None:
            self.last_device = device

    detector = YOLOMotionDetector(
        config={"device": "cuda:0", "require_gpu": False, "allow_cuda_fallback": True}
    )
    detector._model = _DummyModel()
    detector._initialized = True

    handled = detector._handle_cuda_runtime_error(  # noqa: SLF001 - unit test on internal safeguard
        RuntimeError("CUDA error: operation not permitted when stream is capturing")
    )
    assert handled is True
    assert detector._device == "cpu"
    assert detector._model.last_device == "cpu"


def test_yolo_motion_detector_predict_respects_perf_tuning_args() -> None:
    class _DummyModel:
        def __init__(self) -> None:
            self.kwargs = None

        def predict(self, **kwargs):
            self.kwargs = kwargs
            return []

    detector = YOLOMotionDetector(
        config={
            "device": "cuda:0",
            "imgsz": 512,
            "max_det": 3,
            "half": True,
        }
    )
    detector._model = _DummyModel()
    detector._initialized = True
    detector._predict(_blank_frame(0))  # noqa: SLF001 - unit test on internal call contract

    assert detector._model.kwargs is not None
    assert detector._model.kwargs["imgsz"] == 512
    assert detector._model.kwargs["max_det"] == 3
    assert detector._model.kwargs["half"] is True
