from __future__ import annotations

from typing import Any

from robot_life.common.contracts import priority_rank
from robot_life.common.payload_contracts import ScenePayloadAccessor
from robot_life.common.schemas import EventPriority, SceneCandidate
from robot_life.event_engine.arbitrator import Arbitrator

_SCENE_PRIORITY_KEY = "_scene_priority"


def scene_payload(scene: SceneCandidate) -> dict[str, Any]:
    payload = getattr(scene, "payload", None)
    return payload if isinstance(payload, dict) else {}


def scene_path(scene: SceneCandidate) -> str:
    return ScenePayloadAccessor.from_scene(scene).scene_path or ""


def scene_priority(scene: SceneCandidate, arbitrator: Arbitrator | None) -> EventPriority:
    payload = scene_payload(scene)
    cached = payload.get(_SCENE_PRIORITY_KEY) or payload.get("priority")
    if isinstance(cached, EventPriority):
        return cached
    if isinstance(cached, str):
        try:
            return EventPriority(cached)
        except ValueError:
            pass
    if arbitrator is None:
        return EventPriority.P2
    priority = arbitrator.decide(scene, current_priority=None).priority
    payload[_SCENE_PRIORITY_KEY] = priority.value
    scene.payload = payload
    return priority


def set_scene_priority(scene: SceneCandidate, priority: EventPriority) -> SceneCandidate:
    payload = scene_payload(scene)
    payload[_SCENE_PRIORITY_KEY] = priority.value
    payload["priority"] = priority.value
    scene.payload = payload
    return scene


def coalesce_scene_candidates(
    scenes: list[SceneCandidate],
    *,
    arbitrator: Arbitrator | None,
    max_scenes_per_cycle: int,
) -> list[SceneCandidate]:
    if not scenes:
        return []

    coalesced: dict[tuple[str, str | None], SceneCandidate] = {}
    for scene in scenes:
        key = (scene.scene_type, scene.target_id)
        existing = coalesced.get(key)
        if existing is None:
            coalesced[key] = scene
            continue

        better = scene if scene.score_hint >= existing.score_hint else existing
        merged_events = list(dict.fromkeys(existing.based_on_events + scene.based_on_events))
        merged_payload = dict(scene_payload(existing))
        merged_payload.update(scene_payload(scene))
        better.payload = merged_payload
        better.based_on_events = merged_events
        better.valid_until_monotonic = max(existing.valid_until_monotonic, scene.valid_until_monotonic)
        if getattr(better, "primary_target_id", None) is None:
            better.primary_target_id = getattr(existing, "primary_target_id", None) or getattr(scene, "primary_target_id", None)
        related = list(dict.fromkeys(list(getattr(existing, "related_entity_ids", []) or []) + list(getattr(scene, "related_entity_ids", []) or [])))
        better.related_entity_ids = related
        better.interaction_episode_id = getattr(better, "interaction_episode_id", None) or getattr(existing, "interaction_episode_id", None) or getattr(scene, "interaction_episode_id", None)
        better.scene_epoch = getattr(better, "scene_epoch", None) or getattr(existing, "scene_epoch", None) or getattr(scene, "scene_epoch", None)
        coalesced[key] = better

    ordered = sorted(
        coalesced.values(),
        key=lambda item: (priority_rank(scene_priority(item, arbitrator)), -float(item.score_hint)),
    )
    filtered: list[SceneCandidate] = []
    filtered_event_sets: list[set[str]] = []
    filtered_paths: list[str] = []
    filtered_targets: list[str | None] = []
    for scene in ordered:
        current_events = set(scene.based_on_events)
        current_path = scene_path(scene)
        dominated = False
        for index, existing_target in enumerate(filtered_targets):
            if existing_target != scene.target_id:
                continue
            existing_path = filtered_paths[index]
            if current_path and existing_path and current_path != existing_path:
                continue
            if current_events.issubset(filtered_event_sets[index]):
                dominated = True
                break
        if dominated:
            continue
        filtered.append(scene)
        filtered_event_sets.append(current_events)
        filtered_paths.append(current_path)
        filtered_targets.append(scene.target_id)

    return filtered[: max_scenes_per_cycle]


def partition_scene_candidates_by_path(scenes: list[SceneCandidate]) -> dict[str, list[SceneCandidate]]:
    batches: dict[str, list[SceneCandidate]] = {"safety": [], "social": []}
    for scene in scenes:
        if scene_path(scene) == "safety" or scene.scene_type == "safety_alert_scene":
            batches["safety"].append(scene)
        else:
            batches["social"].append(scene)
    return batches
