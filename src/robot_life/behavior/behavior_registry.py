from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from robot_life.common.contracts import (
    BEHAVIOR_ATTENTION_MINIMAL,
    BEHAVIOR_GREETING_VISUAL_ONLY,
    BEHAVIOR_GESTURE_VISUAL_ONLY,
    BEHAVIOR_PERFORM_ATTENTION,
    BEHAVIOR_PERFORM_GREETING,
    BEHAVIOR_PERFORM_GESTURE_RESPONSE,
    BEHAVIOR_PERFORM_SAFETY_ALERT,
    BEHAVIOR_PERFORM_TRACKING,
)


@dataclass
class BehaviorTemplate:
    behavior_id: str
    nodes: list[str]
    resumable: bool = True
    optional_speech: bool = False
    metadata: dict[str, str] = field(default_factory=dict)
    tree: dict[str, Any] | None = None


class BehaviorRegistry:
    """Maps behavior identifiers to executable behavior-tree templates."""

    def __init__(self):
        self._templates: dict[str, BehaviorTemplate] = {
            BEHAVIOR_PERFORM_GREETING: BehaviorTemplate(
                behavior_id=BEHAVIOR_PERFORM_GREETING,
                nodes=[
                    "guard_scene_validity",
                    "state_greet",
                    "act_nonverbal",
                    "act_speech_optional",
                    "state_recover",
                    "release",
                ],
                resumable=True,
                optional_speech=True,
            ),
            BEHAVIOR_GREETING_VISUAL_ONLY: BehaviorTemplate(
                behavior_id=BEHAVIOR_GREETING_VISUAL_ONLY,
                nodes=["guard_scene_validity", "state_greet", "act_nonverbal", "state_recover", "release"],
                resumable=True,
            ),
            BEHAVIOR_PERFORM_ATTENTION: BehaviorTemplate(
                behavior_id=BEHAVIOR_PERFORM_ATTENTION,
                nodes=[
                    "guard_scene_validity",
                    "state_attention",
                    "state_observe",
                    "act_nonverbal",
                    "state_recover",
                    "release",
                ],
                resumable=True,
            ),
            BEHAVIOR_ATTENTION_MINIMAL: BehaviorTemplate(
                behavior_id=BEHAVIOR_ATTENTION_MINIMAL,
                nodes=["state_attention", "act_nonverbal", "state_recover", "release"],
                resumable=True,
            ),
            BEHAVIOR_PERFORM_GESTURE_RESPONSE: BehaviorTemplate(
                behavior_id=BEHAVIOR_PERFORM_GESTURE_RESPONSE,
                nodes=[
                    "guard_scene_validity",
                    "state_greet",
                    "state_observe",
                    "act_nonverbal",
                    "act_speech_optional",
                    "state_recover",
                    "release",
                ],
                resumable=True,
                optional_speech=True,
            ),
            BEHAVIOR_GESTURE_VISUAL_ONLY: BehaviorTemplate(
                behavior_id=BEHAVIOR_GESTURE_VISUAL_ONLY,
                nodes=["guard_scene_validity", "state_greet", "act_nonverbal", "state_recover", "release"],
                resumable=True,
            ),
            BEHAVIOR_PERFORM_SAFETY_ALERT: BehaviorTemplate(
                behavior_id=BEHAVIOR_PERFORM_SAFETY_ALERT,
                nodes=[
                    "guard_scene_validity",
                    "state_alert",
                    "act_nonverbal",
                    "act_speech_optional",
                    "state_recover",
                    "release",
                ],
                resumable=False,
                optional_speech=True,
            ),
            BEHAVIOR_PERFORM_TRACKING: BehaviorTemplate(
                behavior_id=BEHAVIOR_PERFORM_TRACKING,
                nodes=[
                    "state_observe",
                    "act_nonverbal",
                    "monitor_preemption",
                    "state_idle",
                    "release",
                ],
                resumable=True,
            ),
        }

    def get(self, behavior_id: str) -> BehaviorTemplate:
        if behavior_id in self._templates:
            return self._templates[behavior_id]

        return BehaviorTemplate(
            behavior_id=behavior_id,
            nodes=["state_observe", "act_nonverbal", "state_idle", "release"],
            resumable=True,
        )
