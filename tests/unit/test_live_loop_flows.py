from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
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


def _build_loop(enabled_pipelines: list[str]) -> LiveLoop:
    registry = build_pipeline_registry(
        enabled_pipelines=enabled_pipelines,
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
        arbitration_runtime=ArbitrationRuntime(arbitrator=Arbitrator()),
        executor=BehaviorExecutor(ResourceManager()),
    )
    sources = SourceBundle(
        camera=SyntheticCameraSource(),
        microphone=SyntheticMicrophoneSource(),
    )
    return LiveLoop(registry=registry, source_bundle=sources, dependencies=dependencies)


def test_live_loop_face_gaze_flow_produces_greeting() -> None:
    loop = _build_loop(["face", "gaze"])
    results = loop.run_forever(max_iterations=8)
    scene_types = [scene.scene_type for item in results for scene in item.scene_candidates]
    behaviors = [execution.behavior_id for item in results for execution in item.execution_results]

    assert "greeting_scene" in scene_types
    assert "perform_greeting" in behaviors


def test_live_loop_audio_motion_flow_produces_safety_alert() -> None:
    loop = _build_loop(["audio", "motion"])
    results = loop.run_forever(max_iterations=4)
    scene_types = [scene.scene_type for item in results for scene in item.scene_candidates]
    behaviors = [execution.behavior_id for item in results for execution in item.execution_results]

    assert "safety_alert_scene" in scene_types
    assert "perform_safety_alert" in behaviors


def test_live_loop_updates_interaction_state_to_ongoing_interaction_for_social_execution() -> None:
    loop = _build_loop(["face", "gaze"])
    loop.run_forever(max_iterations=8)
    life_state = loop.snapshot_life_state()

    assert life_state["interaction"]["state"] == "ONGOING_INTERACTION"
    assert life_state["interaction"]["target_id"] is not None
    assert life_state["interaction"]["last_reason"].startswith("behavior_executed:")
