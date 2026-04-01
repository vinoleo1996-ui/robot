from pathlib import Path

from robot_life.common.config import load_arbitration_config
from robot_life.common.schemas import DecisionMode, EventPriority
from robot_life.event_engine.arbitrator import Arbitrator


ROOT = Path(__file__).resolve().parents[2]


def _scene(scene_type: str, trace_id: str = "trace_1", score_hint: float = 1.0) -> object:
    return type(
        "Scene",
        (),
        {"scene_type": scene_type, "trace_id": trace_id, "score_hint": score_hint},
    )()


def test_arbitrator_loads_default_arbitration_config() -> None:
    config = load_arbitration_config(ROOT / "configs" / "arbitration" / "default.yaml")
    arbitrator = Arbitrator(config=config)

    greeting = arbitrator.decide(_scene("greeting_scene"))
    assert greeting.target_behavior == "perform_greeting"
    assert greeting.priority == EventPriority.P1
    assert greeting.required_resources == ["HeadMotion", "FaceExpression"]
    assert greeting.optional_resources == ["AudioOut"]
    assert greeting.mode == DecisionMode.EXECUTE

    safety = arbitrator.decide(_scene("safety_alert_scene"), current_priority=EventPriority.P2)
    assert safety.mode == DecisionMode.HARD_INTERRUPT
    assert safety.priority == EventPriority.P0
    assert safety.resume_previous is False


def test_arbitrator_honors_configured_priority_policies(tmp_path: Path) -> None:
    arbitration_config = tmp_path / "arbitration.yaml"
    arbitration_config.write_text(
        """
arbitration:
  priorities:
    P1:
      interrupt: soft
      queue_timeout_ms: 1234
  scene_behaviors:
    custom_scene:
      target_behavior: perform_custom
      priority: P1
      required_resources: [HeadMotion]
      optional_resources: [AudioOut]
      degraded_behavior: custom_visual_only
      resume_previous: true
""".strip(),
        encoding="utf-8",
    )

    arbitrator = Arbitrator(config=load_arbitration_config(arbitration_config))
    decision = arbitrator.decide(_scene("custom_scene"), current_priority=EventPriority.P2)

    assert decision.mode == DecisionMode.SOFT_INTERRUPT
    assert decision.target_behavior == "perform_custom"
    assert arbitrator.queue_timeout_ms(EventPriority.P1) == 1234


def test_arbitrator_default_constructor_remains_available() -> None:
    arbitrator = Arbitrator()

    decision = arbitrator.decide(_scene("greeting_scene"))
    assert decision.target_behavior == "perform_greeting"
    assert decision.priority == EventPriority.P1
