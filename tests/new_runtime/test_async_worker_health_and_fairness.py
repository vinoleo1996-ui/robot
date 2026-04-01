from __future__ import annotations

from threading import Event
from types import SimpleNamespace

from robot_life.common.schemas import DetectionResult, EventPriority
from robot_life.runtime.live_loop import LiveLoop, PendingDetection
from robot_life.runtime.telemetry import InMemoryTelemetrySink


class _FakeSourceBundle:
    def open_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def read_packets(self):
        return {}

    def snapshot_health(self):
        return {}


class _FakeRegistry:
    def initialize_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def process_all(self, frames):
        return []


class _DeadThread:
    def __init__(self, *, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _AliveThread(_DeadThread):
    def __init__(self) -> None:
        super().__init__(alive=True)


def _make_loop(**kwargs) -> LiveLoop:
    return LiveLoop(
        registry=_FakeRegistry(),
        source_bundle=_FakeSourceBundle(),
        telemetry=InMemoryTelemetrySink(),
        **kwargs,
    )


def _pending_detection(seq: int, priority: EventPriority) -> PendingDetection:
    return PendingDetection(
        sequence_id=seq,
        pipeline_name="test",
        detection=DetectionResult.synthetic(detector="test", event_type="motion_detected", confidence=0.5),
        priority=priority,
    )


def test_async_worker_failures_are_reported_and_dead_workers_restart() -> None:
    loop = _make_loop(async_capture_enabled=True)
    loop._capture_stop_event = Event()
    loop._capture_thread = _DeadThread(alive=False)
    restarts: list[str] = []
    loop._restart_async_worker = lambda worker_name: restarts.append(worker_name)  # type: ignore[method-assign]

    loop._poll_async_worker_health()

    snapshot = loop.snapshot_life_state()
    assert snapshot["health"]["failure_streaks"]["stage:async_capture"] >= 1
    assert restarts == ["capture"]
    traces = list(loop.telemetry.traces)
    assert any(trace.stage == "async_worker" and trace.status == "dead" for trace in traces)
    assert any(trace.stage == "async_worker" and trace.status == "restarting" for trace in traces)



def test_async_worker_exception_streaks_reset_after_heartbeat() -> None:
    loop = _make_loop(async_perception_enabled=True)
    loop._perception_stop_event = Event()
    loop._perception_thread = _AliveThread()

    loop._mark_async_worker_failure("perception", RuntimeError("boom"))
    loop._poll_async_worker_health()
    assert loop.snapshot_life_state()["health"]["failure_streaks"]["stage:async_perception"] == 1

    loop._mark_async_worker_heartbeat("perception")
    loop._poll_async_worker_health()
    assert loop.snapshot_life_state()["health"]["failure_streaks"]["stage:async_perception"] == 0



def test_pending_detection_backlog_ages_out_of_starvation() -> None:
    loop = _make_loop(fast_path_pending_limit=1)
    low = _pending_detection(1, EventPriority.P3)
    loop._stash_pending_detections([low])

    for idx in range(2, 9):
        high = _pending_detection(idx, EventPriority.P0)
        loop._stash_pending_detections([loop._pending_detections[0], high])

    aged_low = loop._pending_detections[0]
    fresh_high = _pending_detection(100, EventPriority.P0)

    assert aged_low.was_pending is True
    assert aged_low.defer_count >= 6
    assert loop._pending_processing_sort_key(aged_low) < loop._pending_processing_sort_key(fresh_high)
