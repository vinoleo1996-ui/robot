from __future__ import annotations

from typing import Any

from robot_life.common.interaction_intent import intent_from_snapshot
from robot_life.common.payload_contracts import ScenePayloadAccessor
from robot_life.common.schemas import EventPriority, SceneCandidate


def _related_entity_ids(payload: dict[str, Any], target_id: str | None) -> list[str]:
    related: list[str] = []
    if target_id:
        related.append(str(target_id))
    accessor = ScenePayloadAccessor(payload)
    related.extend(accessor.involved_targets)
    dedup: list[str] = []
    seen: set[str] = set()
    for item in related:
        if item in seen:
            continue
        seen.add(item)
        dedup.append(item)
    return dedup


def enrich_scene_candidate(
    scene: SceneCandidate,
    *,
    frame_seq: int,
    collected_at: float,
    interaction_snapshot: dict[str, Any] | None,
    robot_context: dict[str, Any] | None,
    priority: EventPriority,
    active_behavior_id: str | None,
    robot_busy: bool,
) -> SceneCandidate:
    payload = dict(scene.payload if isinstance(scene.payload, dict) else {})
    accessor = ScenePayloadAccessor(payload)
    interaction_snapshot = interaction_snapshot or {}
    robot_context = robot_context or {}
    episode_id = str(interaction_snapshot.get("episode_id") or "").strip() or None
    primary_target_id = scene.target_id or accessor.target_id or interaction_snapshot.get("target_id")
    if primary_target_id is not None:
        primary_target_id = str(primary_target_id)

    related_entity_ids = _related_entity_ids(payload, primary_target_id)
    scene.primary_target_id = primary_target_id
    scene.related_entity_ids = related_entity_ids
    scene.interaction_episode_id = episode_id
    scene.scene_epoch = f"{frame_seq}:{episode_id or 'global'}:{scene.scene_type}:{primary_target_id or 'none'}"

    scene.payload = accessor.ensure_defaults(
        primary_target_id=primary_target_id,
        related_entity_ids=related_entity_ids,
        interaction_episode_id=episode_id,
        scene_epoch=scene.scene_epoch,
        source_frame_seq=frame_seq,
        source_collected_at=collected_at,
        priority=priority.value,
        robot_mode=robot_context.get("mode"),
        robot_do_not_disturb=robot_context.get("do_not_disturb"),
        robot_busy=robot_busy,
        robot_active_behavior_id=active_behavior_id,
        robot_current_target_id=interaction_snapshot.get("target_id") or interaction_snapshot.get("latest_target_id"),
        interaction_intent=intent_from_snapshot(interaction_snapshot),
    )
    return scene
