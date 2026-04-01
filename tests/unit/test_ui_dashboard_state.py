from __future__ import annotations

import threading
from types import SimpleNamespace

from robot_life.common.schemas import (
    ArbitrationResult,
    DecisionMode,
    DetectionResult,
    EventPriority,
    ExecutionResult,
    SceneCandidate,
    StableEvent,
    new_id,
    now_mono,
)
from robot_life.runtime.live_loop import CollectedFrames, LiveLoopResult
from robot_life.runtime.sources import FramePacket, SourceBundle, SyntheticCameraSource, SyntheticMicrophoneSource
from robot_life.runtime import ui_demo as ui_demo_module
from robot_life.runtime.ui_demo import DashboardState, _apply_runtime_tuning, build_dashboard_html
from robot_life.common.config import StabilizerEventOverride


class _InstrumentedCameraSource(SyntheticCameraSource):
    def snapshot_health(self) -> dict[str, object]:
        return {
            "source_kind": "mock",
            "backend": "AVFOUNDATION",
            "total_failures": 3,
            "recovery_count": 1,
            "last_frame_at": now_mono(),
        }


class _FakePipeline:
    def __init__(self, *, enabled: bool = True, detector: object | None = None) -> None:
        self.spec = type("Spec", (), {"enabled": enabled})()
        self._detector = detector


class _FakeAudioDetector:
    def __init__(self) -> None:
        self._rms_threshold = 0.15
        self._db_threshold = -18.0
        self._panns_confidence_threshold = 0.28
        self._vad_threshold = 0.5

    def update_thresholds(
        self,
        *,
        rms_threshold: float | None = None,
        db_threshold: float | None = None,
        panns_confidence_threshold: float | None = None,
        vad_threshold: float | None = None,
    ) -> dict[str, float | None]:
        if rms_threshold is not None:
            self._rms_threshold = rms_threshold
        if db_threshold is not None:
            self._db_threshold = db_threshold
        if panns_confidence_threshold is not None:
            self._panns_confidence_threshold = panns_confidence_threshold
        if vad_threshold is not None:
            self._vad_threshold = vad_threshold
        return {
            "rms_threshold": self._rms_threshold,
            "db_threshold": self._db_threshold,
            "panns_confidence_threshold": self._panns_confidence_threshold,
            "vad_threshold": self._vad_threshold,
        }


class _FakeMotionDetector:
    def __init__(self) -> None:
        self._threshold = 22
        self._min_area_ratio = 0.03

    def update_thresholds(
        self,
        *,
        pixel_threshold: float | None = None,
        min_area_ratio: float | None = None,
    ) -> dict[str, float]:
        if pixel_threshold is not None:
            self._threshold = int(pixel_threshold)
        if min_area_ratio is not None:
            self._min_area_ratio = float(min_area_ratio)
        return {
            "pixel_threshold": float(self._threshold),
            "min_area_ratio": float(self._min_area_ratio),
        }


class _FakeStabilizer:
    def __init__(self) -> None:
        self._event_overrides = {
            "familiar_face_detected": StabilizerEventOverride(hysteresis_threshold=0.58),
            "stranger_face_detected": StabilizerEventOverride(hysteresis_threshold=0.58),
            "gesture_detected": StabilizerEventOverride(hysteresis_threshold=0.68, cooldown_ms=2200),
            "gaze_sustained_detected": StabilizerEventOverride(hysteresis_threshold=0.60),
        }

    def snapshot_stats(self) -> dict[str, object]:
        return {"totals": {"input": 0, "emitted": 0, "pass_rate": 0.0}}

    def update_event_override(self, event_type: str, **kwargs: object) -> dict[str, object]:
        override = self._event_overrides.get(event_type, StabilizerEventOverride())
        payload = override.model_dump(exclude_none=True)
        payload.update({key: value for key, value in kwargs.items() if value is not None})
        self._event_overrides[event_type] = StabilizerEventOverride.model_validate(payload)
        return self._event_overrides[event_type].model_dump(exclude_none=True)


class _FakeAggregator:
    def __init__(self) -> None:
        self.min_single_signal_score = 0.45

    def update_runtime_tuning(self, *, min_single_signal_score: float | None = None, memory_window_s: float | None = None) -> dict[str, float]:
        if min_single_signal_score is not None:
            self.min_single_signal_score = float(min_single_signal_score)
        return {"min_single_signal_score": self.min_single_signal_score, "memory_window_s": 3.0}


class _FakeArbitrator:
    def __init__(self) -> None:
        self._scene_rules = {"gesture_bond_scene": {"priority": "P1"}}

    def update_scene_priority(self, scene_type: str, priority: object) -> str:
        value = f"P{int(priority)}"
        self._scene_rules[scene_type] = {"priority": value}
        return value


class _FakeRegistry:
    def __init__(self) -> None:
        self.scales: dict[str, float] = {}
        self.audio_detector = _FakeAudioDetector()
        self.motion_detector = _FakeMotionDetector()

    def list_pipelines(self) -> list[str]:
        return ["face", "audio", "motion"]

    def get_pipeline(self, name: str) -> _FakePipeline | None:
        if name == "audio":
            return _FakePipeline(enabled=True, detector=self.audio_detector)
        if name == "motion":
            return _FakePipeline(enabled=True, detector=self.motion_detector)
        return _FakePipeline(enabled=True)

    def snapshot_pipeline_statuses(self) -> dict[str, dict[str, object]]:
        return {
            "face": {
                "enabled": True,
                "status": "ready",
                "implementation": "SingleDetectorPipeline",
                "reason": "",
            },
            "audio": {
                "enabled": True,
                "status": "degraded",
                "implementation": "NoOpPipeline",
                "reason": "sounddevice unavailable",
            },
        }

    def set_runtime_scale(self, pipeline_name: str, scale: float) -> None:
        self.scales[pipeline_name] = scale


class _FakeLoop:
    def __init__(self) -> None:
        camera = _InstrumentedCameraSource()
        microphone = SyntheticMicrophoneSource()
        camera.open()
        microphone.open()
        self.registry = _FakeRegistry()
        self.source_bundle = SourceBundle(camera=camera, microphone=microphone)
        self.dependencies = type(
            "Deps",
            (),
            {
                "stabilizer": _FakeStabilizer(),
                "aggregator": _FakeAggregator(),
                "arbitrator": _FakeArbitrator(),
            },
        )()
        self.fast_path_budget_ms = 35.0
        self.async_perception_result_max_age_ms = 140.0
        self.async_perception_result_max_frame_lag = 3

    def snapshot_life_state(self) -> dict[str, object]:
        return {
            "interaction": {"state": "INTERACTION", "transition_count": 2},
            "decay": {"strength": 0.7, "use_voice": False, "degrade_applied": True},
            "robot_context": {"mode": "demo", "do_not_disturb": False, "current_interaction_target": "u1"},
        }


class _FakeDashboardLoop:
    def __init__(self) -> None:
        self.dependencies = type("Deps", (), {"slow_scene": None})()
        self.start_thread: str | None = None
        self.run_thread: str | None = None
        self.stop_calls = 0

    def start(self) -> None:
        self.start_thread = threading.current_thread().name

    def run_once(self) -> LiveLoopResult:
        self.run_thread = threading.current_thread().name
        raise RuntimeError("boom")

    def stop(self) -> None:
        self.stop_calls += 1


class _FakeDashboardServer:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.timeout = 0.0
        self.serve_thread: str | None = None
        self.shutdown_called = False
        self.closed = False

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        self.serve_thread = threading.current_thread().name

    def shutdown(self) -> None:
        self.shutdown_called = True

    def server_close(self) -> None:
        self.closed = True


def test_dashboard_state_records_runtime_iteration() -> None:
    detection = DetectionResult.synthetic(
        detector="motion",
        event_type="motion_detected",
        confidence=0.88,
        payload={"target_id": "u1"},
    )
    stable = StableEvent(
        stable_event_id=new_id(),
        base_event_id=new_id(),
        trace_id=detection.trace_id,
        event_type="motion_detected",
        priority=EventPriority.P3,
        valid_until_monotonic=now_mono() + 2.0,
        stabilized_by=["debounce"],
    )
    scene = SceneCandidate(
        scene_id=new_id(),
        trace_id=detection.trace_id,
        scene_type="ambient_tracking_scene",
        based_on_events=[stable.stable_event_id],
        score_hint=0.56,
        valid_until_monotonic=now_mono() + 2.0,
        payload={"scene_path": "social"},
    )
    arbitration = ArbitrationResult(
        decision_id=new_id(),
        trace_id=detection.trace_id,
        target_behavior="perform_tracking",
        priority=EventPriority.P3,
        mode=DecisionMode.EXECUTE,
        required_resources=["HeadMotion"],
        optional_resources=[],
        degraded_behavior=None,
        resume_previous=True,
        reason="scene rule matched",
    )
    execution = ExecutionResult(
        execution_id=new_id(),
        trace_id=detection.trace_id,
        behavior_id="perform_tracking",
        status="finished",
        interrupted=False,
        degraded=False,
        started_at=1.0,
        ended_at=1.1,
    )
    result = LiveLoopResult(
        collected_frames=CollectedFrames(
            packets={
                "camera": FramePacket(source="camera", payload={"frame": 1}),
                "microphone": FramePacket(source="microphone", payload={"audio": 1}),
            }
        ),
        detections=[detection],
        stable_events=[stable],
        scene_candidates=[scene],
        arbitration_results=[arbitration],
        execution_results=[execution],
        scene_batches={"social": [scene], "safety": []},
    )
    state = DashboardState(
        mode="live",
        current_profile="local_mac_fast_reaction_lite",
        detector_profile="local_mac_fast_reaction_lite",
        current_stabilizer="local_mac_fast_reaction",
        max_history=16,
        max_rows=8,
    )
    state.record_iteration(result, latency_ms=24.0)
    state.update_observability(_FakeLoop(), min_interval_s=0.0)
    snapshot = state.snapshot()
    public_snapshot = state.public_snapshot()

    assert snapshot["mode"] == "live"
    assert snapshot["current_profile"] == "local_mac_fast_reaction_lite"
    assert snapshot["detector_profile"] == "local_mac_fast_reaction_lite"
    assert snapshot["current_stabilizer"] == "local_mac_fast_reaction"
    assert snapshot["iterations"] == 1
    assert snapshot["camera_packets"] == 1
    assert snapshot["microphone_packets"] == 1
    assert snapshot["total_detections"] == 1
    assert snapshot["total_stable_events"] == 1
    assert snapshot["total_executions"] == 1
    assert snapshot["latest_detections"][0]["event_type"].startswith("motion_detected")
    assert snapshot["latest_arbitrations"][0]["target_behavior"] == "环境跟随观察"
    assert snapshot["latest_executions"][0]["status"] == "已完成"
    assert "latest_reaction" in snapshot
    assert "detected_event" in snapshot["latest_reaction"]
    assert "arbitration_logic" in snapshot["latest_reaction"]
    assert "executed_event" in snapshot["latest_reaction"]
    assert "robot_response" in snapshot["latest_reaction"]
    assert "route_summary" in snapshot["latest_reaction"]
    assert "has_camera_frame" in snapshot
    assert "stabilizer" in snapshot
    assert "resources" in snapshot
    assert "slow_scene" in snapshot
    assert "fast_reaction" in snapshot
    assert snapshot["life_state"]["interaction"]["state"] == "INTERACTION"
    assert snapshot["life_state"]["decay"]["degrade_applied"] is True
    assert snapshot["life_state"]["robot_context"]["mode"] == "demo"
    assert "slow_reaction" in snapshot
    assert snapshot["pipeline_statuses"][0]["status"] == "ready"
    assert snapshot["pipeline_statuses"][1]["status"] == "degraded"
    assert "pipeline_monitors" in snapshot
    assert "scene_routes" in snapshot
    assert snapshot["scene_routes"][0]["path"] == "safety"
    assert snapshot["scene_routes"][1]["path"] == "social"
    assert snapshot["scene_routes"][1]["latest_scene"] == "环境观察场景"
    assert "event_transitions" in snapshot
    assert snapshot["event_transitions"][0]["path"] == "social"
    assert snapshot["reaction_hold_seconds"] >= 0.5
    assert snapshot["fast_path_budget_ms"] == 35.0
    assert snapshot["async_perception_result_max_age_ms"] == 140.0
    assert snapshot["latest_reaction_age_ms"] is not None
    assert snapshot["source_health"][0]["name"] == "camera"
    assert snapshot["source_health"][0]["mode"] == "mock"
    assert snapshot["source_health"][0]["last_read_ok"] is True
    assert snapshot["source_health"][0]["backend"] == "AVFOUNDATION"
    assert snapshot["source_health"][0]["recovery_count"] == 1
    assert snapshot["source_health"][0]["last_frame_age_ms"] is not None
    assert public_snapshot["mode"] == "live"
    assert public_snapshot["latest_reaction"]["robot_response"]
    assert {item["name"] for item in public_snapshot["pipelines"]} == {"face", "audio", "motion"}
    assert public_snapshot["sources"][0]["name"] == "camera"
    assert "fast_reaction" not in public_snapshot
    assert "slow_scene" not in public_snapshot


def test_dashboard_public_snapshot_exposes_startup_state() -> None:
    state = DashboardState(mode="live", current_profile="local_mac")

    initial = state.public_snapshot()
    assert initial["startup_state"] == "booting"

    state.set_startup_state("initializing", "opening_sources_and_pipelines")
    snapshot = state.public_snapshot()
    assert snapshot["startup_state"] == "initializing"
    assert snapshot["startup_message"] == "opening_sources_and_pipelines"
    assert snapshot["startup_elapsed_ms"] is not None


def test_dashboard_html_contains_required_panels() -> None:
    html = build_dashboard_html(refresh_ms=400)
    assert "机器人快反应实时面板" in html
    assert "/api/state" in html
    assert "/api/state_full" in html
    assert "核心指标" in html
    assert "最终场景输出" in html
    assert "实时摄像头" in html
    assert "五路感知状态" in html
    assert "实时事件流" in html
    assert "scene-react" in html
    assert "camera-preview" in html
    assert "pipeline-list" in html


def test_microphone_health_not_marked_idle_when_packet_is_recent() -> None:
    state = DashboardState(
        mode="live",
        current_profile="local_mac_fast_reaction_lite",
        detector_profile="local_mac_fast_reaction_lite",
        current_stabilizer="local_mac_fast_reaction",
        max_history=16,
        max_rows=8,
    )
    first = LiveLoopResult(
        collected_frames=CollectedFrames(
            packets={
                "camera": FramePacket(source="camera", payload={"frame": 1}),
                "microphone": FramePacket(source="microphone", payload={"audio": 1}),
            }
        ),
    )
    second = LiveLoopResult(
        collected_frames=CollectedFrames(
            packets={
                "camera": FramePacket(source="camera", payload={"frame": 2}),
            }
        ),
    )
    state.record_iteration(first, latency_ms=5.0)
    state.record_iteration(second, latency_ms=6.0)
    snapshot = state.snapshot()

    mic = next(item for item in snapshot["source_health"] if item["name"] == "microphone")
    assert mic["last_read_ok"] is True


def test_dashboard_state_reaction_hold_seconds_can_be_overridden_by_env(monkeypatch) -> None:
    monkeypatch.setenv("ROBOT_LIFE_REACTION_HOLD_S", "2.5")
    state = DashboardState(mode="live")
    assert state.reaction_hold_seconds == 2.5


def test_dashboard_runtime_tuning_updates_loop_state() -> None:
    state = DashboardState(mode="live")
    loop = _FakeLoop()

    applied = _apply_runtime_tuning(
        state,
        loop,
        {
            "reaction_hold_seconds": 1.5,
            "fast_path_budget_ms": 18.0,
            "async_perception_result_max_age_ms": 90.0,
            "audio_rms_threshold": 0.33,
            "audio_db_threshold": -12.0,
            "gesture_scene_priority": 2,
            "scene_min_single_signal_score": 0.62,
            "face_hysteresis_threshold": 0.72,
            "gesture_hysteresis_threshold": 0.81,
            "gesture_cooldown_ms": 3200,
            "gaze_hysteresis_threshold": 0.74,
            "audio_panns_threshold": 0.41,
            "audio_vad_threshold": 0.67,
            "motion_pixel_threshold": 31,
            "motion_min_area_ratio": 0.07,
            "pipeline_runtime_scale": {"face": 0.5},
        },
    )

    assert applied["reaction_hold_seconds"] == 1.5
    assert applied["fast_path_budget_ms"] == 18.0
    assert applied["async_perception_result_max_age_ms"] == 90.0
    assert applied["rms_threshold"] == 0.33
    assert applied["db_threshold"] == -12.0
    assert applied["gesture_scene_priority"] == "P2"
    assert applied["scene_min_single_signal_score"] == 0.62
    assert applied["face_hysteresis_threshold"] == 0.72
    assert applied["gesture_hysteresis_threshold"] == 0.81
    assert applied["gesture_cooldown_ms"] == 3200
    assert applied["gaze_hysteresis_threshold"] == 0.74
    assert applied["panns_confidence_threshold"] == 0.41
    assert applied["vad_threshold"] == 0.67
    assert applied["pixel_threshold"] == 31.0
    assert applied["min_area_ratio"] == 0.07
    assert loop.fast_path_budget_ms == 18.0
    assert loop.async_perception_result_max_age_ms == 90.0
    assert loop.registry.scales["face"] == 0.5
    assert loop.registry.audio_detector._rms_threshold == 0.33
    assert loop.registry.audio_detector._db_threshold == -12.0
    assert loop.registry.audio_detector._panns_confidence_threshold == 0.41
    assert loop.registry.audio_detector._vad_threshold == 0.67
    assert loop.registry.motion_detector._threshold == 31
    assert loop.registry.motion_detector._min_area_ratio == 0.07
    assert loop.dependencies.aggregator.min_single_signal_score == 0.62


def test_public_snapshot_uses_cached_resource_metrics(monkeypatch) -> None:
    state = DashboardState(mode="live")
    loop = _FakeLoop()

    monkeypatch.setattr(ui_demo_module.psutil, "cpu_percent", lambda: 17.5)
    monkeypatch.setattr(ui_demo_module.psutil, "virtual_memory", lambda: SimpleNamespace(percent=33.0))
    state.update_observability(loop, min_interval_s=0.0)

    monkeypatch.setattr(
        ui_demo_module.psutil,
        "cpu_percent",
        lambda: (_ for _ in ()).throw(AssertionError("cpu_percent should not be called in public_snapshot")),
    )
    monkeypatch.setattr(
        ui_demo_module.psutil,
        "virtual_memory",
        lambda: (_ for _ in ()).throw(AssertionError("virtual_memory should not be called in public_snapshot")),
    )

    public_snapshot = state.public_snapshot()

    assert public_snapshot["cpu_percent"] == 17.5
    assert public_snapshot["mem_percent"] == 33.0


def test_preview_worker_encodes_cached_camera_jpeg(monkeypatch) -> None:
    state = DashboardState(mode="live")
    render_calls: list[tuple[bool, int]] = []

    def _fake_render(frame: object, detections: list[object], *, annotate: bool = True, max_width: int = 480, jpeg_quality: int = 68) -> bytes:
        render_calls.append((annotate, len(detections)))
        return b"jpeg-bytes"

    monkeypatch.setattr(ui_demo_module, "_render_camera_preview", _fake_render)

    result = LiveLoopResult(
        collected_frames=CollectedFrames(
            packets={"camera": FramePacket(source="camera", payload={"frame": 1})},
            frames={"camera": {"frame": 1}},
        ),
        detections=[DetectionResult.synthetic(detector="face", event_type="familiar_face_detected", confidence=0.9)],
    )

    state.record_iteration(result, latency_ms=8.0)
    assert len(render_calls) == 0

    drained = state._drain_preview_requests_once()
    payload = state.camera_jpeg()

    assert drained is True
    assert payload == b"jpeg-bytes"
    assert len(render_calls) == 2
    assert render_calls[0] == (True, 1)
    assert render_calls[1] == (False, 0)


def test_ui_dashboard_runs_live_loop_on_main_thread(monkeypatch) -> None:
    servers: list[_FakeDashboardServer] = []

    def _fake_server_factory(*args: object, **kwargs: object) -> _FakeDashboardServer:
        server = _FakeDashboardServer(*args, **kwargs)
        servers.append(server)
        return server

    monkeypatch.setattr(ui_demo_module, "ThreadingHTTPServer", _fake_server_factory)
    loop = _FakeDashboardLoop()

    ui_demo_module.run_ui_dashboard(
        loop=loop,
        mode="live",
        host="127.0.0.1",
        port=0,
        refresh_ms=200,
        poll_interval_s=0.0,
    )

    assert loop.start_thread == threading.current_thread().name
    assert loop.run_thread == threading.current_thread().name
    assert loop.stop_calls == 1
    assert len(servers) == 1
    assert servers[0].serve_thread is not None
    assert servers[0].serve_thread != loop.run_thread
    assert servers[0].shutdown_called is True
    assert servers[0].closed is True
