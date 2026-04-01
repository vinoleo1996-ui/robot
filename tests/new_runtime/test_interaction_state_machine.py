from robot_life.common.state_machine import InteractionStateMachine


def test_state_machine_assigns_episode_and_intent() -> None:
    sm = InteractionStateMachine()
    assert sm.snapshot()['episode_id'] is None
    assert sm.snapshot()['intent'] == 'idle_scan'

    sm.on_notice_human(target_id='alice', reason='face_detected')
    first = sm.snapshot()
    assert first['state'] == 'NOTICED_HUMAN'
    assert first['target_id'] == 'alice'
    assert first['episode_id'] == 'episode-1'
    assert first['intent'] == 'ack_presence'

    sm.on_mutual_attention(target_id='alice')
    second = sm.snapshot()
    assert second['episode_id'] == 'episode-1'
    assert second['intent'] == 'establish_attention'

    sm.on_attention_lost(target_id='alice')
    sm.tick()
    sm.reset()
    assert sm.snapshot()['episode_id'] is None
    assert sm.snapshot()['intent'] == 'idle_scan'


def test_state_machine_starts_new_episode_after_recovery() -> None:
    sm = InteractionStateMachine()
    sm.on_notice_human(target_id='alice')
    first_episode = sm.snapshot()['episode_id']
    sm.on_attention_lost(target_id='alice')
    sm._transition(sm.current_state.IDLE, target_id=None, reason='test_idle')
    sm.on_notice_human(target_id='bob')
    assert sm.snapshot()['episode_id'] != first_episode
    assert sm.snapshot()['target_id'] == 'bob'
