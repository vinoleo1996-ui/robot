from __future__ import annotations

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.common.schemas import DetectionResult
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.entity_tracker import EntityTracker
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime import (
    LiveLoop,
    LiveLoopDependencies,
    SourceBundle,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
)


def test_entity_tracker_associates_social_modalities_and_separates_motion() -> None:
    tracker = EntityTracker()
    items = [
        (
            "face",
            DetectionResult.synthetic(
                detector="mediapipe_face",
                event_type="stranger_face",
                confidence=0.82,
                payload={"bbox": [10, 10, 40, 40], "target_id": "unknown_0"},
            ),
        ),
        (
            "gaze",
            DetectionResult.synthetic(
                detector="mediapipe_gaze",
                event_type="gaze_sustained",
                confidence=0.8,
                payload={},
            ),
        ),
        (
            "gesture",
            DetectionResult.synthetic(
                detector="mediapipe_gesture",
                event_type="gesture_open_palm",
                confidence=0.77,
                payload={"hand_bbox": [0.08, 0.08, 0.28, 0.42]},
            ),
        ),
        (
            "motion",
            DetectionResult.synthetic(
                detector="opencv_motion",
                event_type="motion",
                confidence=0.55,
                payload={"motion_boxes": [[70, 70, 95, 95]]},
            ),
        ),
    ]

    associated = tracker.associate_batch(items, frame_shape=(100, 100))
    face_target = associated[0][1].payload["target_id"]
    gaze_target = associated[1][1].payload["target_id"]
    gesture_target = associated[2][1].payload["target_id"]
    motion_target = associated[3][1].payload["target_id"]

    assert face_target.startswith("person_track_")
    assert face_target == gaze_target == gesture_target
    assert motion_target.startswith("object_track_")
    assert motion_target != face_target
    assert associated[0][1].payload["identity_target_id"] == "unknown_0"
    snapshot = tracker.snapshot()
    assert snapshot["active_track_count"] >= 2


def test_entity_tracker_preserves_distinct_explicit_identity_targets_without_bbox() -> None:
    tracker = EntityTracker()
    associated = tracker.associate_batch(
        [
            (
                "face",
                DetectionResult.synthetic(
                    detector="mediapipe_face",
                    event_type="familiar_face",
                    confidence=0.9,
                    payload={"target_id": "user-1"},
                ),
            ),
            (
                "face",
                DetectionResult.synthetic(
                    detector="mediapipe_face",
                    event_type="familiar_face",
                    confidence=0.91,
                    payload={"target_id": "user-2"},
                ),
            ),
        ],
    )

    first_target = associated[0][1].payload["target_id"]
    second_target = associated[1][1].payload["target_id"]
    assert first_target.startswith("person_track_")
    assert second_target.startswith("person_track_")
    assert first_target != second_target
    assert associated[0][1].payload["identity_hint"] == "user-1"
    assert associated[1][1].payload["identity_hint"] == "user-2"


class _TrackingRegistry:
    def initialize_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def process_all(self, _frames):
        return [
            (
                "face",
                {
                    "detections": [
                        DetectionResult.synthetic(
                            detector="mediapipe_face",
                            event_type="familiar_face",
                            confidence=0.91,
                            payload={"bbox": [10, 10, 45, 50], "target_id": "unknown_0"},
                        )
                    ]
                },
            ),
            (
                "gaze",
                {
                    "detections": [
                        DetectionResult.synthetic(
                            detector="mediapipe_gaze",
                            event_type="gaze_sustained",
                            confidence=0.84,
                            payload={},
                        )
                    ]
                },
            ),
        ]


def test_live_loop_propagates_track_id_into_scene_decision_and_execution() -> None:
    loop = LiveLoop(
        registry=_TrackingRegistry(),
        source_bundle=SourceBundle(
            camera=SyntheticCameraSource(),
            microphone=SyntheticMicrophoneSource(),
        ),
        dependencies=LiveLoopDependencies(
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
            entity_tracker=EntityTracker(),
        ),
    )

    result = loop.run_forever(max_iterations=1)[0]

    detection_targets = {item.payload.get("target_id") for item in result.detections}
    assert len(detection_targets) == 1
    tracked_target = next(iter(detection_targets))
    assert tracked_target.startswith("person_track_")
    assert result.scene_candidates[0].target_id == tracked_target
    assert result.arbitration_results[0].target_id == tracked_target
    assert result.execution_results[0].target_id == tracked_target
    life_state = loop.snapshot_life_state()
    assert life_state["entity_tracker"]["active_track_count"] >= 1
