from robot_life.common.schemas import EventPriority, SceneCandidate
from robot_life.runtime.scene_context import enrich_scene_candidate
from robot_life.runtime.scene_ops import coalesce_scene_candidates, partition_scene_candidates_by_path


def _scene(scene_type: str, *, target_id: str | None, score: float, based_on: list[str], payload: dict | None = None) -> SceneCandidate:
    return SceneCandidate(
        scene_id=f'{scene_type}:{target_id}:{score}',
        trace_id=f'trace-{scene_type}-{score}',
        scene_type=scene_type,
        based_on_events=based_on,
        score_hint=score,
        valid_until_monotonic=100.0,
        target_id=target_id,
        payload=payload or {},
    )


def test_enrich_scene_candidate_adds_episode_and_target_metadata() -> None:
    scene = _scene('greeting_scene', target_id='alice', score=0.9, based_on=['e1'], payload={'entity_signals': ['face'], 'scene_path': 'social'})
    enriched = enrich_scene_candidate(
        scene,
        frame_seq=42,
        collected_at=12.5,
        interaction_snapshot={'state': 'NOTICED_HUMAN', 'episode_id': 'episode-7', 'target_id': 'alice'},
        robot_context={'mode': 'demo', 'do_not_disturb': False},
        priority=EventPriority.P1,
        active_behavior_id='perform_greeting',
        robot_busy=True,
    )
    assert enriched.interaction_episode_id == 'episode-7'
    assert enriched.primary_target_id == 'alice'
    assert enriched.related_entity_ids == ['alice']
    assert enriched.scene_epoch.startswith('42:episode-7:greeting_scene')
    assert enriched.payload['interaction_intent'] == 'ack_presence'
    assert enriched.payload['signal_breakdown']['entity'] == ['face']


def test_coalesce_and_partition_scene_candidates_keep_stronger_scene() -> None:
    stronger = _scene('attention_scene', target_id='alice', score=0.9, based_on=['e1', 'e2'], payload={'scene_path': 'social'})
    weaker = _scene('attention_scene', target_id='alice', score=0.5, based_on=['e1'], payload={'scene_path': 'social'})
    safety = _scene('safety_alert_scene', target_id='alice', score=0.7, based_on=['e9'], payload={'scene_path': 'safety'})
    coalesced = coalesce_scene_candidates([weaker, stronger, safety], arbitrator=None, max_scenes_per_cycle=4)
    assert stronger in coalesced
    assert weaker not in coalesced
    batches = partition_scene_candidates_by_path(coalesced)
    assert safety in batches['safety']
    assert stronger in batches['social']
