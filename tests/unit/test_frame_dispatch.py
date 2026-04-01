from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from robot_life.perception.frame_dispatch import CameraFrameDispatch, build_camera_dispatch
from robot_life.runtime.live_loop import collect_frames
from robot_life.runtime.sources import FramePacket


def test_camera_frame_dispatch_caches_preprocessing_views() -> None:
    frame = np.zeros((24, 32, 3), dtype=np.uint8)
    dispatch = build_camera_dispatch(frame, frame_seq=7, collected_at=12.3)
    assert isinstance(dispatch, CameraFrameDispatch)
    assert dispatch.frame_seq == 7
    assert dispatch.collected_at == 12.3

    rgb1 = dispatch.rgb()
    rgb2 = dispatch.rgb()
    gray1 = dispatch.gray()
    gray2 = dispatch.gray()

    assert rgb1 is rgb2
    assert gray1 is gray2
    assert rgb1.shape == frame.shape
    assert gray1.shape == frame.shape[:2]


def test_camera_frame_dispatch_reuses_contiguous_bgr_frame_without_copy() -> None:
    frame = np.zeros((12, 16, 3), dtype=np.uint8)

    dispatch = build_camera_dispatch(frame, frame_seq=3, collected_at=1.2)

    assert isinstance(dispatch, CameraFrameDispatch)
    assert dispatch.bgr is frame


def test_collect_frames_skips_camera_dispatch_when_registry_wont_consume_camera() -> None:
    frame = np.zeros((12, 16, 3), dtype=np.uint8)

    class _FakeSourceBundle:
        def read_packets(self):
            return {
                "camera": FramePacket(source="camera", payload=frame, frame_index=9),
            }

    class _FakeRegistry:
        def scheduled_sources(self, _frames):
            return {"microphone"}

    collected = collect_frames(_FakeSourceBundle(), registry=_FakeRegistry())

    assert collected.frames["camera"] is frame
