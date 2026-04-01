from __future__ import annotations

import numpy as np

from robot_life.common.schemas import DetectionResult
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime.live_loop import LiveLoop, LiveLoopDependencies
from robot_life.runtime.sources import FramePacket


class _FakeSourceBundle:
    def __init__(self) -> None:
        self._frame_index = 0

    def open_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def read_packets(self) -> dict[str, FramePacket]:
        self._frame_index += 1
        frame = np.zeros((8, 8, 3), dtype=np.uint8)
        return {
            'camera': FramePacket(source='camera', payload=frame, frame_index=self._frame_index),
        }


class _FakeRegistry:
    def initialize_all(self) -> None:
        return None

    def close_all(self) -> None:
        return None

    def process_all(self, frames: dict[str, object]):
        assert 'camera' in frames
        return [
            (
                'face',
                {
                    'detections': [
                        DetectionResult.synthetic(
                            detector='face',
                            event_type='familiar_face_detected',
                            confidence=0.95,
                            payload={'target_id': 'alice'},
                        )
                    ]
                },
            )
        ]


def _build_loop() -> LiveLoop:
    deps = LiveLoopDependencies(
        builder=EventBuilder(),
        stabilizer=EventStabilizer(debounce_count=1, cooldown_ms=0, dedup_window_ms=0),
        aggregator=SceneAggregator(min_single_signal_score=0.1),
        arbitrator=Arbitrator(),
    )
    return LiveLoop(
        registry=_FakeRegistry(),
        source_bundle=_FakeSourceBundle(),
        dependencies=deps,
        max_scenes_per_cycle=4,
    )


def test_live_loop_carries_consistency_metadata_across_cycles() -> None:
    loop = _build_loop()

    first = loop.run_once()
    assert loop.snapshot_life_state()['interaction']['episode_id'] == 'episode-1'
    assert first.detections[0].payload['frame_seq'] == 1
    assert 'source_latency_ms' in first.detections[0].payload

    second = loop.run_once()
    assert second.scene_candidates, 'expected enriched scene candidates on second cycle'
    scene = second.scene_candidates[0]
    decision = second.arbitration_results[0]

    assert scene.interaction_episode_id == 'episode-1'
    assert scene.scene_epoch is not None
    assert scene.payload['primary_target_id'] == scene.primary_target_id
    assert scene.primary_target_id is not None
    assert scene.payload['interaction_episode_id'] == 'episode-1'
    assert decision.target_id == scene.primary_target_id
    assert scene.payload['source_frame_seq'] == 2
    assert scene.payload['interaction_intent'] in {'ack_presence', 'establish_attention'}
    assert decision.interaction_episode_id == 'episode-1'
    assert decision.scene_epoch == scene.scene_epoch
    assert decision.decision_epoch is not None
