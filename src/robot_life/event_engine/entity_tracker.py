from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot
from time import monotonic
from typing import Any

from robot_life.common.payload_contracts import DetectionPayloadAccessor
from robot_life.common.schemas import DetectionResult


def _looks_like_ephemeral_target(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return True
    return normalized.startswith(("unknown", "mock_user", "user_", "track_", "person_track_", "object_track_"))


@dataclass
class EntityTrack:
    track_id: str
    track_kind: str
    bbox_norm: tuple[float, float, float, float] | None
    created_at: float
    last_seen_at: float
    detection_count: int = 1
    last_detector: str = ""
    last_event_type: str = ""
    identity_hint: str | None = None
    modalities: set[str] = field(default_factory=set)
    source_detectors: set[str] = field(default_factory=set)


class EntityTracker:
    """Lightweight cross-modal entity association for live interaction loops."""

    def __init__(
        self,
        *,
        person_ttl_s: float = 1.5,
        object_ttl_s: float = 1.0,
        iou_threshold: float = 0.18,
        center_threshold: float = 0.22,
        gesture_person_threshold: float = 0.35,
    ) -> None:
        self.person_ttl_s = max(0.1, float(person_ttl_s))
        self.object_ttl_s = max(0.1, float(object_ttl_s))
        self.iou_threshold = float(iou_threshold)
        self.center_threshold = float(center_threshold)
        self.gesture_person_threshold = float(gesture_person_threshold)
        self._tracks: dict[str, EntityTrack] = {}
        self._next_person_id = 1
        self._next_object_id = 1

    def associate_batch(
        self,
        items: list[tuple[str, DetectionResult]],
        *,
        frame_shape: tuple[int, int] | None = None,
    ) -> list[tuple[str, DetectionResult]]:
        now = monotonic()
        self._prune(now)
        associated: list[tuple[str, DetectionResult]] = []
        for pipeline_name, detection in items:
            payload = detection.payload if isinstance(detection.payload, dict) else {}
            accessor = DetectionPayloadAccessor(payload)
            modality = self._infer_modality(pipeline_name, detection)
            original_target_id = accessor.target_id
            identity_hint = None if _looks_like_ephemeral_target(original_target_id) else str(original_target_id)
            bbox_norm = self._extract_bbox_norm(payload, frame_shape=frame_shape)
            track = self._resolve_track(
                modality=modality,
                bbox_norm=bbox_norm,
                identity_hint=identity_hint,
                now=now,
            )
            track.last_seen_at = now
            track.detection_count += 1
            track.last_detector = detection.detector
            track.last_event_type = detection.event_type
            track.modalities.add(modality)
            track.source_detectors.add(detection.detector)
            if bbox_norm is not None:
                track.bbox_norm = bbox_norm
            if identity_hint:
                track.identity_hint = identity_hint

            updated_payload = dict(payload)
            if original_target_id is not None:
                updated_payload.setdefault("identity_target_id", original_target_id)
            updated_payload["target_id"] = track.track_id
            updated_payload["track_id"] = track.track_id
            updated_payload["track_kind"] = track.track_kind
            updated_payload["track_detection_count"] = track.detection_count
            updated_payload["track_modalities"] = sorted(track.modalities)
            if track.identity_hint is not None:
                updated_payload["identity_hint"] = track.identity_hint
            detection.payload = updated_payload
            associated.append((pipeline_name, detection))
        return associated

    def snapshot(self) -> dict[str, Any]:
        now = monotonic()
        self._prune(now)
        ordered = sorted(self._tracks.values(), key=lambda item: (item.track_kind, item.track_id))
        return {
            "active_track_count": len(ordered),
            "tracks": [
                {
                    "track_id": item.track_id,
                    "track_kind": item.track_kind,
                    "last_event_type": item.last_event_type,
                    "last_detector": item.last_detector,
                    "identity_hint": item.identity_hint,
                    "detection_count": item.detection_count,
                    "age_ms": round((now - item.last_seen_at) * 1000.0, 2),
                    "modalities": sorted(item.modalities),
                }
                for item in ordered[:16]
            ],
        }

    def _resolve_track(
        self,
        *,
        modality: str,
        bbox_norm: tuple[float, float, float, float] | None,
        identity_hint: str | None,
        now: float,
    ) -> EntityTrack:
        if modality in {"face", "gaze", "gesture"}:
            track = self._match_person_track(bbox_norm=bbox_norm, identity_hint=identity_hint, modality=modality, now=now)
            if track is not None:
                return track
            return self._create_track(track_kind="person", bbox_norm=bbox_norm, identity_hint=identity_hint, now=now)
        if modality == "motion":
            track = self._match_object_track(bbox_norm=bbox_norm, now=now)
            if track is not None:
                return track
            return self._create_track(track_kind="object", bbox_norm=bbox_norm, identity_hint=None, now=now)
        return self._create_track(track_kind="global", bbox_norm=None, identity_hint=identity_hint, now=now)

    def _match_person_track(
        self,
        *,
        bbox_norm: tuple[float, float, float, float] | None,
        identity_hint: str | None,
        modality: str,
        now: float,
    ) -> EntityTrack | None:
        candidates = [
            item for item in self._tracks.values()
            if item.track_kind == "person" and (now - item.last_seen_at) <= self.person_ttl_s
        ]
        if not candidates:
            return None
        if identity_hint:
            for item in candidates:
                if item.identity_hint == identity_hint:
                    return item
            return None
        if bbox_norm is None:
            if len(candidates) == 1:
                return candidates[0]
            return max(candidates, key=lambda item: item.last_seen_at, default=None)

        threshold = self.gesture_person_threshold if modality == "gesture" else self.center_threshold
        scored: list[tuple[float, EntityTrack]] = []
        for item in candidates:
            if item.bbox_norm is None:
                continue
            iou = _bbox_iou(item.bbox_norm, bbox_norm)
            center_distance = _center_distance(item.bbox_norm, bbox_norm)
            if iou >= self.iou_threshold:
                scored.append((iou + 1.0, item))
                continue
            if center_distance <= threshold:
                scored.append((1.0 - center_distance, item))
        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[0][1]

    def _match_object_track(
        self,
        *,
        bbox_norm: tuple[float, float, float, float] | None,
        now: float,
    ) -> EntityTrack | None:
        if bbox_norm is None:
            return None
        candidates = [
            item for item in self._tracks.values()
            if item.track_kind == "object" and (now - item.last_seen_at) <= self.object_ttl_s and item.bbox_norm is not None
        ]
        if not candidates:
            return None
        scored: list[tuple[float, EntityTrack]] = []
        for item in candidates:
            iou = _bbox_iou(item.bbox_norm or bbox_norm, bbox_norm)
            center_distance = _center_distance(item.bbox_norm or bbox_norm, bbox_norm)
            if iou >= self.iou_threshold or center_distance <= self.center_threshold:
                scored.append((max(iou, 1.0 - center_distance), item))
        if not scored:
            return None
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[0][1]

    def _create_track(
        self,
        *,
        track_kind: str,
        bbox_norm: tuple[float, float, float, float] | None,
        identity_hint: str | None,
        now: float,
    ) -> EntityTrack:
        if track_kind == "person":
            track_id = f"person_track_{self._next_person_id:03d}"
            self._next_person_id += 1
        elif track_kind == "object":
            track_id = f"object_track_{self._next_object_id:03d}"
            self._next_object_id += 1
        else:
            track_id = f"{track_kind}_track"
        track = EntityTrack(
            track_id=track_id,
            track_kind=track_kind,
            bbox_norm=bbox_norm,
            created_at=now,
            last_seen_at=now,
            detection_count=0,
            identity_hint=identity_hint,
        )
        self._tracks[track_id] = track
        return track

    def _prune(self, now: float) -> None:
        stale: list[str] = []
        for track_id, item in self._tracks.items():
            ttl_s = self.person_ttl_s if item.track_kind == "person" else self.object_ttl_s
            if item.track_kind == "global":
                ttl_s = 0.5
            if (now - item.last_seen_at) > ttl_s:
                stale.append(track_id)
        for track_id in stale:
            self._tracks.pop(track_id, None)

    @staticmethod
    def _infer_modality(pipeline_name: str, detection: DetectionResult) -> str:
        normalized_pipeline = str(pipeline_name or "").lower()
        normalized_detector = str(detection.detector or "").lower()
        normalized_event = str(detection.event_type or "").lower()
        if "face" in normalized_pipeline or "face" in normalized_detector or "face" in normalized_event:
            return "face"
        if "gaze" in normalized_pipeline or "gaze" in normalized_detector or "gaze" in normalized_event:
            return "gaze"
        if "gesture" in normalized_pipeline or "gesture" in normalized_detector or "gesture" in normalized_event:
            return "gesture"
        if "motion" in normalized_pipeline or "motion" in normalized_detector or "motion" in normalized_event:
            return "motion"
        if "audio" in normalized_pipeline or "audio" in normalized_detector or "sound" in normalized_event:
            return "audio"
        return normalized_pipeline or "unknown"

    def _extract_bbox_norm(
        self,
        payload: dict[str, Any],
        *,
        frame_shape: tuple[int, int] | None,
    ) -> tuple[float, float, float, float] | None:
        bbox = DetectionPayloadAccessor(payload).bbox
        if isinstance(bbox, list) and len(bbox) >= 4:
            return _normalize_bbox(bbox[:4], frame_shape=frame_shape)
        hand_bbox = DetectionPayloadAccessor(payload).hand_bbox
        if isinstance(hand_bbox, list) and len(hand_bbox) >= 4:
            return _normalize_bbox(hand_bbox[:4], frame_shape=frame_shape)
        motion_boxes = DetectionPayloadAccessor(payload).motion_boxes
        if isinstance(motion_boxes, list) and motion_boxes:
            largest = max(
                [box for box in motion_boxes if isinstance(box, list) and len(box) >= 4],
                key=lambda box: max(0.0, float(box[2]) - float(box[0])) * max(0.0, float(box[3]) - float(box[1])),
                default=None,
            )
            if largest is not None:
                return _normalize_bbox(largest[:4], frame_shape=frame_shape)
        return None


def _normalize_bbox(
    box: list[Any],
    *,
    frame_shape: tuple[int, int] | None,
) -> tuple[float, float, float, float] | None:
    try:
        x1, y1, x2, y2 = [float(value) for value in box[:4]]
    except (TypeError, ValueError):
        return None

    if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
        nx1, ny1, nx2, ny2 = x1, y1, x2, y2
    elif frame_shape is not None:
        height, width = frame_shape
        if width <= 0 or height <= 0:
            return None
        nx1, ny1, nx2, ny2 = x1 / float(width), y1 / float(height), x2 / float(width), y2 / float(height)
    else:
        return None

    nx1, nx2 = sorted((max(0.0, min(1.0, nx1)), max(0.0, min(1.0, nx2))))
    ny1, ny2 = sorted((max(0.0, min(1.0, ny1)), max(0.0, min(1.0, ny2))))
    if nx2 <= nx1 or ny2 <= ny1:
        return None
    return (nx1, ny1, nx2, ny2)


def _center_distance(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax = (a[0] + a[2]) / 2.0
    ay = (a[1] + a[3]) / 2.0
    bx = (b[0] + b[2]) / 2.0
    by = (b[1] + b[3]) / 2.0
    return hypot(ax - bx, ay - by)


def _bbox_iou(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    area_a = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / max(1e-6, area_a + area_b - inter)
