from __future__ import annotations
from robot_life.behavior.manager import BehaviorManager
from robot_life.common.config import ArbitrationConfig, SceneBehaviorConfig
from robot_life.common.payload_contracts import ScenePayloadAccessor
from robot_life.common.schemas import (
    ArbitrationResult,
    DecisionMode,
    EventPriority,
    SceneCandidate,
    new_id,
)
from robot_life.common.contracts import (
    BEHAVIOR_ATTENTION_MINIMAL,
    BEHAVIOR_GREETING_VISUAL_ONLY,
    BEHAVIOR_GESTURE_VISUAL_ONLY,
    BEHAVIOR_PERFORM_ATTENTION,
    BEHAVIOR_PERFORM_GREETING,
    BEHAVIOR_PERFORM_GESTURE_RESPONSE,
    BEHAVIOR_PERFORM_SAFETY_ALERT,
    BEHAVIOR_PERFORM_TRACKING,
    SCENE_AMBIENT_TRACKING,
    SCENE_ATTENTION,
    SCENE_GESTURE_BOND,
    SCENE_GREETING,
    SCENE_SAFETY_ALERT,
    SCENE_STRANGER_ATTENTION,
)
from robot_life.event_engine.policy_layer import PolicyLayer


class Arbitrator:
    """Rule-first arbitrator scaffold."""

    _SCENE_RULES: dict[str, dict] = {
        SCENE_GREETING: {
            "target_behavior": BEHAVIOR_PERFORM_GREETING,
            "priority": EventPriority.P1,
            "required_resources": ["HeadMotion", "FaceExpression"],
            "optional_resources": ["AudioOut"],
            "degraded_behavior": BEHAVIOR_GREETING_VISUAL_ONLY,
            "resume_previous": True,
        },
        SCENE_ATTENTION: {
            "target_behavior": BEHAVIOR_PERFORM_ATTENTION,
            "priority": EventPriority.P2,
            "required_resources": ["HeadMotion"],
            "optional_resources": ["FaceExpression", "AudioOut"],
            "degraded_behavior": BEHAVIOR_ATTENTION_MINIMAL,
            "resume_previous": True,
        },
        SCENE_STRANGER_ATTENTION: {
            "target_behavior": BEHAVIOR_PERFORM_ATTENTION,
            "priority": EventPriority.P2,
            "required_resources": ["HeadMotion"],
            "optional_resources": ["FaceExpression", "AudioOut"],
            "degraded_behavior": BEHAVIOR_ATTENTION_MINIMAL,
            "resume_previous": True,
        },
        SCENE_SAFETY_ALERT: {
            "target_behavior": BEHAVIOR_PERFORM_SAFETY_ALERT,
            "priority": EventPriority.P0,
            "required_resources": ["AudioOut"],
            "optional_resources": ["HeadMotion", "FaceExpression"],
            "degraded_behavior": None,
            "resume_previous": False,
            "hard_interrupt": True,
        },
        SCENE_GESTURE_BOND: {
            "target_behavior": BEHAVIOR_PERFORM_GESTURE_RESPONSE,
            "priority": EventPriority.P1,
            "required_resources": ["FaceExpression"],
            "optional_resources": ["HeadMotion", "AudioOut"],
            "degraded_behavior": BEHAVIOR_GESTURE_VISUAL_ONLY,
            "resume_previous": True,
        },
        SCENE_AMBIENT_TRACKING: {
            "target_behavior": BEHAVIOR_PERFORM_TRACKING,
            "priority": EventPriority.P3,
            "required_resources": [],
            "optional_resources": ["HeadMotion"],
            "degraded_behavior": None,
            "resume_previous": True,
        },
    }

    _PRIORITY_POLICIES: dict[EventPriority, tuple[str, int]] = {
        EventPriority.P0: ("immediate", 0),
        EventPriority.P1: ("soft", 5_000),
        EventPriority.P2: ("queue", 10_000),
        EventPriority.P3: ("never", 15_000),
    }

    def __init__(
        self,
        degrade_score_threshold: float = 0.55,
        config: ArbitrationConfig | None = None,
    ) -> None:
        self.degrade_score_threshold = float(degrade_score_threshold)
        self._scene_rules = self._build_scene_rules(config)
        self._priority_policies = self._build_priority_policies(config)
        self.policy_layer = PolicyLayer(
            degrade_score_threshold=self.degrade_score_threshold,
            priority_policies=self._priority_policies,
        )
        self.behavior_manager = BehaviorManager()

    def decide(
        self,
        scene: SceneCandidate,
        current_priority: EventPriority | None = None,
    ) -> ArbitrationResult:
        rule = self._scene_rules.get(scene.scene_type)
        if rule is None:
            behavior = f"perform_{scene.scene_type}"
            rule = {
                "target_behavior": behavior,
                "priority": EventPriority.P2,
                "required_resources": ["HeadMotion", "FaceExpression"],
                "optional_resources": ["AudioOut"],
                "degraded_behavior": f"{behavior}_visual_only",
                "resume_previous": True,
                "hard_interrupt": False,
            }
        policy = self.policy_layer.evaluate(
            scene,
            rule=rule,
            current_priority=current_priority,
        )
        plan = self.behavior_manager.plan(
            scene,
            rule=rule,
            policy=policy,
        )

        return ArbitrationResult(
            decision_id=new_id(),
            trace_id=scene.trace_id,
            target_behavior=plan.target_behavior,
            priority=policy.priority,
            mode=policy.mode,
            required_resources=plan.required_resources,
            optional_resources=plan.optional_resources,
            degraded_behavior=plan.degraded_behavior,
            resume_previous=plan.resume_previous,
            reason=f"{policy.reason}|{plan.reason}",
            target_id=getattr(scene, "target_id", None),
            scene_type=getattr(scene, "scene_type", None),
            engagement_score=_scene_engagement_score(scene),
            scene_path=_scene_path(scene),
            interaction_state=_scene_interaction_state(scene),
            interaction_episode_id=getattr(scene, "interaction_episode_id", None),
            scene_epoch=getattr(scene, "scene_epoch", None),
            decision_epoch=f"{getattr(scene, 'scene_epoch', None) or 'scene'}:{policy.priority.value}:{plan.target_behavior}",
        )

    def queue_timeout_ms(self, priority: EventPriority) -> int:
        return self.policy_layer.queue_timeout_ms(priority)

    def should_enqueue(self, decision: ArbitrationResult) -> bool:
        return decision.mode == DecisionMode.DROP and decision.priority in {EventPriority.P2, EventPriority.P3}

    def update_scene_priority(self, scene_type: str, priority: EventPriority | str | int | float) -> str | None:
        resolved = self._coerce_runtime_priority(priority)
        if resolved is None:
            return None
        scene_key = str(scene_type or "").strip()
        if not scene_key:
            return None
        rule = dict(self._scene_rules.get(scene_key, {}))
        if not rule:
            decision = self.decide(
                type("Scene", (), {"scene_type": scene_key, "trace_id": "runtime_tuning", "score_hint": 1.0})(),
                current_priority=None,
            )
            rule = {
                "target_behavior": decision.target_behavior,
                "priority": decision.priority,
                "required_resources": list(decision.required_resources),
                "optional_resources": list(decision.optional_resources),
                "degraded_behavior": decision.degraded_behavior,
                "resume_previous": bool(decision.resume_previous),
                "hard_interrupt": decision.mode == DecisionMode.HARD_INTERRUPT,
            }
        rule["priority"] = resolved
        self._scene_rules[scene_key] = rule
        return resolved.value

    @classmethod
    def _build_scene_rules(cls, config: ArbitrationConfig | None) -> dict[str, dict]:
        scene_rules = {name: dict(rule) for name, rule in cls._SCENE_RULES.items()}
        if config is None:
            return scene_rules

        for scene_type, scene_config in config.scene_behaviors.items():
            scene_rules[scene_type] = cls._scene_rule_from_config(scene_config)
        return scene_rules

    @classmethod
    def _build_priority_policies(
        cls,
        config: ArbitrationConfig | None,
    ) -> dict[EventPriority, tuple[str, int]]:
        priority_policies = dict(cls._PRIORITY_POLICIES)
        if config is None:
            return priority_policies

        for priority_name, policy in config.priorities.items():
            priority = cls._coerce_priority(priority_name)
            if priority is None:
                continue
            priority_policies[priority] = (
                str(policy.interrupt),
                int(policy.queue_timeout_ms),
            )
        return priority_policies

    @staticmethod
    def _coerce_priority(value: str) -> EventPriority | None:
        try:
            return EventPriority(value)
        except ValueError:
            return None

    @staticmethod
    def _coerce_runtime_priority(value: EventPriority | str | int | float) -> EventPriority | None:
        if isinstance(value, EventPriority):
            return value
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in {"0", "1", "2", "3"}:
                normalized = f"P{normalized}"
            return Arbitrator._coerce_priority(normalized)
        if isinstance(value, (int, float)):
            rank = int(value)
            if 0 <= rank <= 3:
                return Arbitrator._coerce_priority(f"P{rank}")
        return None

    @classmethod
    def _scene_rule_from_config(cls, scene_config: SceneBehaviorConfig) -> dict:
        priority = cls._coerce_priority(scene_config.priority) or EventPriority.P2
        return {
            "target_behavior": scene_config.target_behavior,
            "priority": priority,
            "required_resources": list(scene_config.required_resources),
            "optional_resources": list(scene_config.optional_resources),
            "degraded_behavior": scene_config.degraded_behavior,
            "resume_previous": bool(scene_config.resume_previous),
            "hard_interrupt": bool(scene_config.hard_interrupt),
        }


def _scene_payload(scene: SceneCandidate) -> ScenePayloadAccessor:
    return ScenePayloadAccessor.from_scene(scene)


def _scene_engagement_score(scene: SceneCandidate) -> float | None:
    accessor = _scene_payload(scene)
    return accessor.engagement_score if accessor.engagement_score is not None else getattr(scene, "score_hint", None)


def _scene_path(scene: SceneCandidate) -> str | None:
    return _scene_payload(scene).scene_path


def _scene_interaction_state(scene: SceneCandidate) -> str | None:
    return _scene_payload(scene).interaction_state
