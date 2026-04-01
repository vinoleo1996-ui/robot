from __future__ import annotations

from types import SimpleNamespace

from robot_life.common.payload_contracts import (
    ArbitrationTracePayload,
    DetectionPayloadAccessor,
    ScenePayloadAccessor,
    SlowTaskMetadata,
)
from robot_life.common.schemas import SceneCandidate


def test_detection_payload_accessor_applies_ingestion_defaults() -> None:
    accessor = DetectionPayloadAccessor({"target_id": "alice"})
    payload = accessor.apply_ingestion_defaults(
        frame_seq=7,
        collected_at=10.0,
        ingested_at=12.5,
        source_latency_ms=3.4,
        camera_frame_seq=9,
        frame_shape=(480, 640),
    )
    assert payload["frame_seq"] == 7
    assert payload["camera_frame_seq"] == 9
    assert payload["frame_height"] == 480
    assert payload["frame_width"] == 640
    assert accessor.target_id == "alice"


def test_scene_payload_accessor_and_slow_task_metadata_round_trip() -> None:
    scene = SceneCandidate(
        scene_id="scene-1",
        trace_id="trace-1",
        scene_type="attention_scene",
        based_on_events=["evt-1"],
        score_hint=0.7,
        valid_until_monotonic=1.0,
        target_id="alice",
        interaction_episode_id="episode-1",
        scene_epoch="42:episode-1:attention_scene:alice",
        primary_target_id="alice",
        related_entity_ids=["alice", "bob"],
        payload={
            "scene_path": "social",
            "interaction_state": "ENGAGING",
            "engagement_score": 0.88,
            "interaction_intent": "maintain_engagement",
            "source_frame_seq": 42,
            "source_collected_at": 10.0,
            "related_entity_ids": ["alice", "bob"],
        },
    )
    accessor = ScenePayloadAccessor.from_scene(scene)
    assert accessor.scene_path == "social"
    assert accessor.interaction_state == "engaging"
    assert accessor.engagement_score == 0.88

    collected = SimpleNamespace(
        frame_seq=42,
        collected_at=10.0,
        packets={"camera": SimpleNamespace(frame_index=42)},
    )
    metadata = SlowTaskMetadata.from_scene_and_collected(scene, collected, decision_mode="QUEUE", arbitration_outcome="queued")
    payload = metadata.to_dict()
    assert payload["scene_epoch"] == scene.scene_epoch
    assert payload["interaction_episode_id"] == "episode-1"
    assert payload["decision_mode"] == "QUEUE"
    assert payload["arbitration_outcome"] == "queued"


def test_arbitration_trace_payload_builder() -> None:
    decision = SimpleNamespace(
        target_behavior="perform_greeting",
        priority=SimpleNamespace(value="P1"),
        mode=SimpleNamespace(value="EXECUTE"),
        reason="scene_match",
        interaction_episode_id="episode-2",
        scene_epoch="epoch-1",
        decision_epoch="decision-1",
    )
    trace = ArbitrationTracePayload.from_decision(decision, queue_pending=3).to_dict()
    assert trace["target_behavior"] == "perform_greeting"
    assert trace["mode"] == "EXECUTE"
    assert trace["queue_pending"] == 3
    assert trace["interaction_episode_id"] == "episode-2"
