from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from robot_life.common.payload_contracts import ScenePayloadAccessor
from robot_life.common.schemas import SceneCandidate

_SOCIAL_SCENE_TYPES = {
    "attention_scene",
    "stranger_attention_scene",
    "greeting_scene",
    "gesture_bond_scene",
    "ambient_tracking_scene",
}

_SAFETY_SCENE_TYPES = {"safety_alert_scene"}


@dataclass(frozen=True)
class TargetGovernanceDecision:
    owner_target_id: str | None
    accepted: list[SceneCandidate]
    suppressed: list[SceneCandidate]
    reason: str
    switched: bool


class TargetGovernor:
    """Govern multi-target ownership to keep social interaction stable."""

    def __init__(
        self,
        *,
        switch_margin: float = 0.15,
        owner_stale_after_s: float = 2.8,
        owner_min_hold_s: float = 2.4,
    ) -> None:
        self.switch_margin = max(0.0, float(switch_margin))
        self.owner_stale_after_s = max(0.1, float(owner_stale_after_s))
        self.owner_min_hold_s = max(0.1, float(owner_min_hold_s))
        self._owner_target_id: str | None = None
        self._owner_seen_at = 0.0
        self._owner_locked_at = 0.0

    @property
    def owner_target_id(self) -> str | None:
        return self._owner_target_id

    def snapshot(self) -> dict[str, Any]:
        return {
            "owner_target_id": self._owner_target_id,
            "owner_seen_at": self._owner_seen_at,
            "owner_age_ms": round(max(0.0, (monotonic() - self._owner_seen_at) * 1000.0), 3)
            if self._owner_seen_at
            else None,
            "owner_lock_age_ms": round(max(0.0, (monotonic() - self._owner_locked_at) * 1000.0), 3)
            if self._owner_locked_at
            else None,
            "switch_margin": self.switch_margin,
            "owner_stale_after_s": self.owner_stale_after_s,
            "owner_min_hold_s": self.owner_min_hold_s,
        }

    def govern(
        self,
        scenes: list[SceneCandidate],
        *,
        active_target_id: str | None,
        interaction_snapshot: dict[str, Any] | None,
    ) -> TargetGovernanceDecision:
        if not scenes:
            return TargetGovernanceDecision(
                owner_target_id=self._owner_target_id,
                accepted=[],
                suppressed=[],
                reason="no_scenes",
                switched=False,
            )

        interaction_snapshot = interaction_snapshot or {}
        hinted_target = _normalized_target(active_target_id) or _normalized_target(interaction_snapshot.get("target_id"))
        social_scenes = [scene for scene in scenes if _is_social_scene(scene)]
        if not social_scenes:
            self._release_if_stale()
            return TargetGovernanceDecision(
                owner_target_id=self._owner_target_id,
                accepted=list(scenes),
                suppressed=[],
                reason="no_social_scene",
                switched=False,
            )

        best_social = max(social_scenes, key=_scene_rank)
        owner_target = hinted_target or self._owner_target_id or best_social.target_id
        owner_scene = _best_scene_for_target(social_scenes, owner_target)
        best_target = _normalized_target(best_social.target_id)
        switched = False
        reason = "sticky_owner"
        now = monotonic()
        owner_stale = bool(self._owner_seen_at and (now - self._owner_seen_at) > self.owner_stale_after_s)
        owner_locked_recently = bool(
            self._owner_locked_at and (now - self._owner_locked_at) < self.owner_min_hold_s
        )

        if owner_scene is None:
            if self._owner_target_id and not owner_stale:
                owner_target = self._owner_target_id
                reason = "hold_missing_owner"
            else:
                owner_target = best_target
                owner_scene = best_social
                switched = owner_target != self._owner_target_id
                reason = "adopt_best_target"
        elif best_target and best_target != owner_target:
            owner_score = _scene_rank(owner_scene)[0]
            challenger_score = _scene_rank(best_social)[0]
            if owner_stale:
                owner_target = best_target
                owner_scene = best_social
                switched = owner_target != self._owner_target_id
                reason = "switch_stale_owner"
            elif not owner_locked_recently and challenger_score >= owner_score + self.switch_margin:
                owner_target = best_target
                owner_scene = best_social
                switched = owner_target != self._owner_target_id
                reason = "switch_higher_priority_target"

        accepted: list[SceneCandidate] = []
        suppressed: list[SceneCandidate] = []
        for scene in scenes:
            if scene.scene_type in _SAFETY_SCENE_TYPES or not _is_social_scene(scene):
                accepted.append(_mark_scene(scene, owner_target, accepted=True, reason="pass_through"))
                continue
            if _normalized_target(scene.target_id) == owner_target:
                accepted.append(_mark_scene(scene, owner_target, accepted=True, reason=reason))
            else:
                suppressed.append(_mark_scene(scene, owner_target, accepted=False, reason="ownership_filtered"))

        if owner_target is not None:
            if owner_target != self._owner_target_id:
                self._owner_locked_at = now
            self._owner_target_id = owner_target
            if owner_scene is not None:
                self._owner_seen_at = now
        else:
            self._release_if_stale(force=True)

        return TargetGovernanceDecision(
            owner_target_id=owner_target,
            accepted=accepted,
            suppressed=suppressed,
            reason=reason,
            switched=switched,
        )

    def _release_if_stale(self, *, force: bool = False) -> None:
        if self._owner_target_id is None:
            return
        if force or (self._owner_seen_at and (monotonic() - self._owner_seen_at) > self.owner_stale_after_s):
            self._owner_target_id = None
            self._owner_seen_at = 0.0
            self._owner_locked_at = 0.0


def _is_social_scene(scene: SceneCandidate) -> bool:
    if scene.scene_type in _SAFETY_SCENE_TYPES:
        return False
    if scene.scene_type in _SOCIAL_SCENE_TYPES:
        return True
    accessor = ScenePayloadAccessor.from_scene(scene)
    return accessor.scene_path == "social"


def _best_scene_for_target(scenes: list[SceneCandidate], target_id: str | None) -> SceneCandidate | None:
    normalized = _normalized_target(target_id)
    if normalized is None:
        return None
    candidates = [scene for scene in scenes if _normalized_target(scene.target_id) == normalized]
    if not candidates:
        return None
    return max(candidates, key=_scene_rank)


def _scene_rank(scene: SceneCandidate) -> tuple[float, float]:
    accessor = ScenePayloadAccessor.from_scene(scene)
    engagement_score = accessor.engagement_score
    return (float(scene.score_hint), float(engagement_score) if engagement_score is not None else float(scene.score_hint))


def _normalized_target(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mark_scene(scene: SceneCandidate, owner_target_id: str | None, *, accepted: bool, reason: str) -> SceneCandidate:
    payload = dict(scene.payload if isinstance(scene.payload, dict) else {})
    payload["ownership_target_id"] = owner_target_id
    payload["ownership_status"] = "accepted" if accepted else "suppressed"
    payload["ownership_reason"] = reason
    scene.payload = payload
    return scene
