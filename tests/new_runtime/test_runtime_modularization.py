from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from robot_life.common.schemas import SceneCandidate
from robot_life.runtime.load_shedder import ResourceLoadShedder
from robot_life.runtime.long_task_coordinator import LongTaskCoordinator


class _FakeRegistry:
    def __init__(self) -> None:
        self.scales = None

    def set_runtime_scales(self, scales):
        self.scales = dict(scales)


class _FakeTaskService:
    def __init__(self) -> None:
        self.force_sample = True
        self.sample_interval_s = 1.0


@dataclass
class _FakeStatus:
    value: str


@dataclass
class _FakeSceneJson:
    scene_type: str
    confidence: float


@dataclass
class _FakeResult:
    status: _FakeStatus
    scene_json: _FakeSceneJson


class _FakeLongTaskService:
    def __init__(self) -> None:
        self.force_sample = False
        self.sample_interval_s = 0.0
        self.request_timeout_ms = 1234
        self.submitted: dict[str, SceneCandidate] = {}
        self.submit_metadata: dict[str, dict | None] = {}
        self.results: dict[str, _FakeResult | None] = {}
        self._next_id = 0

    def capture_frame(self, frame, *, source: str, metadata: dict):
        return (frame, source, metadata)

    def should_trigger(self, scene, *, decision_mode=None, arbitration_outcome=None):
        return True

    def submit(self, scene, *, image=None, timeout_ms: int = 0, metadata=None):
        self._next_id += 1
        request_id = f"req-{self._next_id}"
        self.submitted[request_id] = scene
        self.submit_metadata[request_id] = dict(metadata or {})
        self.results[request_id] = None
        return request_id

    def get_request_state(self, request_id: str):
        return "PENDING" if self.results[request_id] is None else "FINISHED"

    def query(self, *, request_id: str):
        return self.results[request_id]


def test_load_shedder_scales_registry_and_long_task_service() -> None:
    registry = _FakeRegistry()
    task = _FakeTaskService()
    shedder = ResourceLoadShedder(
        queue_drain_latency_budget_ms=100.0,
        queue_drain_pending_threshold=4,
    )

    normal = shedder.apply(
        queue_pending=0,
        cycle_latency_ms=20.0,
        queue_pressure_streak=0,
        registry=registry,
        task_service=task,
    )
    assert normal["load_shed_mode"] == "normal"
    assert registry.scales == {"face": 1.0, "gaze": 1.0, "motion": 1.0}
    assert task.force_sample is True
    assert task.sample_interval_s == 1.0

    strong = shedder.apply(
        queue_pending=8,
        cycle_latency_ms=180.0,
        queue_pressure_streak=2,
        registry=registry,
        task_service=task,
    )
    assert strong["load_shed_mode"] == "strong"
    assert registry.scales == {"face": 0.33, "gaze": 0.33, "motion": 0.33}
    assert task.force_sample is False
    assert task.sample_interval_s >= 12.0


def test_long_task_coordinator_submits_and_drains_ready_results() -> None:
    service = _FakeLongTaskService()
    coordinator = LongTaskCoordinator()
    scene = SceneCandidate(
        scene_id="scene-1",
        trace_id="trace-1",
        scene_type="attention_scene",
        based_on_events=["evt-1"],
        score_hint=0.4,
        valid_until_monotonic=100.0,
        target_id="alice",
    )
    collected = SimpleNamespace(
        packets={
            "camera": SimpleNamespace(payload=b"img", frame_index=7),
        }
    )

    maybe_result = coordinator.submit_or_query(service, scene, collected, arbitration_outcome="queued")
    assert maybe_result is None
    assert service.submitted

    ready = coordinator.drain_ready_results(service)
    assert ready == []

    request_id = next(iter(service.submitted))
    assert service.submit_metadata[request_id]["arbitration_outcome"] == "queued"
    service.results[request_id] = _FakeResult(
        status=_FakeStatus("FINISHED"),
        scene_json=_FakeSceneJson(scene_type="attention_scene", confidence=0.91),
    )
    ready = coordinator.drain_ready_results(service)
    assert len(ready) == 1
    base_scene, scene_json = ready[0]
    assert base_scene.scene_id == "scene-1"
    assert scene_json.scene_type == "attention_scene"
