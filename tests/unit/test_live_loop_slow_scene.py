from __future__ import annotations

from dataclasses import dataclass

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.common.config import SlowSceneConfig
from robot_life.common.schemas import EventPriority, SceneCandidate, SceneJson
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime import (
    LiveLoop,
    LiveLoopDependencies,
    SourceBundle,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
    build_pipeline_registry,
)
from robot_life.slow_scene.service import SlowSceneService


@dataclass
class _Status:
    value: str


@dataclass
class _SlowResult:
    scene_json: SceneJson
    status: _Status


class _FakeSlowScene:
    request_timeout_ms = 200

    def __init__(self) -> None:
        self._submit_count = 0
        self._poll_count: dict[str, int] = {}

    def capture_frame(self, *_args, **_kwargs) -> None:
        return None

    def should_trigger(self, *_args, **_kwargs) -> bool:
        return True

    def submit(self, scene, **_kwargs) -> str:
        self._submit_count += 1
        request_id = f"req_{self._submit_count}"
        self._poll_count[request_id] = 0
        return request_id

    def query(self, request_id: str):
        if request_id not in self._poll_count:
            return None
        self._poll_count[request_id] += 1
        if self._poll_count[request_id] < 2:
            return None
        return _SlowResult(
            scene_json=SceneJson(
                scene_type="safety_alert_scene",
                confidence=0.95,
                involved_targets=[],
                emotion_hint="alert",
                urgency_hint="high",
                recommended_strategy="immediate_action",
                escalate_to_cloud=True,
            ),
            status=_Status("COMPLETED"),
        )


class _StateOnlySlowScene:
    request_timeout_ms = 200
    sample_interval_s = 5.0
    force_sample = False

    def __init__(self) -> None:
        self._counter = 0
        self._states: dict[str, str] = {}

    def capture_frame(self, *_args, **_kwargs) -> None:
        return None

    def should_trigger(self, *_args, **_kwargs) -> bool:
        return True

    def submit(self, *_args, **_kwargs) -> str:
        self._counter += 1
        request_id = f"req_{self._counter}"
        self._states[request_id] = "DROPPED"
        return request_id

    def query(self, *_args, **_kwargs):
        return None

    def get_request_state(self, request_id: str) -> str | None:
        return self._states.get(request_id)


def _scene(score: float) -> SceneCandidate:
    return SceneCandidate(
        scene_id="s1",
        trace_id="t1",
        scene_type="greeting_scene",
        based_on_events=["e1"],
        score_hint=score,
        valid_until_monotonic=999999.0,
        target_id="user_1",
        payload={},
    )


def test_slow_scene_trigger_policy_uncertain_and_conflict() -> None:
    service = SlowSceneService(
        use_qwen=False,
        config=SlowSceneConfig(trigger_min_score=0.8, use_qwen=False),
    )
    try:
        assert service.should_trigger(_scene(0.5), arbitration_outcome="executed") is True
        assert service.should_trigger(_scene(0.95), arbitration_outcome="queued") is True
        assert service.should_trigger(_scene(0.95), decision_mode="DROP") is True
        assert service.should_trigger(_scene(0.95), arbitration_outcome="executed") is False
    finally:
        service.close()


def test_live_loop_keeps_slow_scene_as_json_sidecar() -> None:
    registry = build_pipeline_registry(
        enabled_pipelines=["gesture"],
        detector_cfg={},
        mock_drivers=True,
    )
    dependencies = LiveLoopDependencies(
        builder=EventBuilder(),
        stabilizer=EventStabilizer(
            debounce_count=1,
            cooldown_ms=0,
            hysteresis_threshold=0.0,
            dedup_window_ms=0,
        ),
        aggregator=SceneAggregator(),
        arbitrator=Arbitrator(),
        arbitration_runtime=ArbitrationRuntime(arbitrator=Arbitrator()),
        executor=BehaviorExecutor(ResourceManager()),
        slow_scene=_FakeSlowScene(),
    )
    loop = LiveLoop(
        registry=registry,
        source_bundle=SourceBundle(
            camera=SyntheticCameraSource(),
            microphone=SyntheticMicrophoneSource(),
        ),
        dependencies=dependencies,
        enable_slow_scene=True,
    )

    results = loop.run_forever(max_iterations=6)
    behaviors = [execution.behavior_id for item in results for execution in item.execution_results]
    slow_scene_count = sum(len(item.slow_scene_results) for item in results)

    assert "perform_gesture_response" in behaviors
    assert "perform_safety_alert" not in behaviors
    assert slow_scene_count > 0


def test_live_loop_slow_scene_sample_interval_is_scoped_per_target() -> None:
    loop = LiveLoop(
        registry=build_pipeline_registry(enabled_pipelines=[], detector_cfg={}, mock_drivers=True),
        source_bundle=SourceBundle(
            camera=SyntheticCameraSource(),
            microphone=SyntheticMicrophoneSource(),
        ),
        dependencies=LiveLoopDependencies(),
        enable_slow_scene=True,
    )
    slow_scene = _FakeSlowScene()
    collected = loop.run_once().collected_frames

    scene_a = SceneCandidate(
        scene_id="scene-a",
        trace_id="trace-a",
        scene_type="attention_scene",
        based_on_events=[],
        score_hint=0.5,
        valid_until_monotonic=999999.0,
        target_id="user-a",
        payload={},
    )
    scene_b = SceneCandidate(
        scene_id="scene-b",
        trace_id="trace-b",
        scene_type="attention_scene",
        based_on_events=[],
        score_hint=0.5,
        valid_until_monotonic=999999.0,
        target_id="user-b",
        payload={},
    )

    loop._submit_or_query_slow_scene(slow_scene, scene_a, collected)  # noqa: SLF001
    loop._submit_or_query_slow_scene(slow_scene, scene_b, collected)  # noqa: SLF001

    assert len(loop._slow_scene_pending) == 2  # noqa: SLF001


def test_live_loop_prunes_terminal_slow_scene_requests_without_result() -> None:
    loop = LiveLoop(
        registry=build_pipeline_registry(enabled_pipelines=[], detector_cfg={}, mock_drivers=True),
        source_bundle=SourceBundle(
            camera=SyntheticCameraSource(),
            microphone=SyntheticMicrophoneSource(),
        ),
        dependencies=LiveLoopDependencies(),
        enable_slow_scene=True,
    )
    slow_scene = _StateOnlySlowScene()
    collected = loop.run_once().collected_frames
    scene = _scene(0.5)

    loop._submit_or_query_slow_scene(slow_scene, scene, collected)  # noqa: SLF001
    assert len(loop._slow_scene_pending) == 0  # noqa: SLF001
