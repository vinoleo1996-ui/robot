from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import time
from typing import Any
from uuid import uuid4

try:
    import cv2
except Exception:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore

try:
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None  # type: ignore


_DATA_URL_RE = re.compile(r"^data:image/(?P<ext>[a-zA-Z0-9.+-]+);base64,(?P<data>.+)$")


@dataclass
class FaceProfile:
    face_id: str
    name: str
    description: str
    image_path: str
    embedding: list[float]
    bbox: list[int]
    created_at: float

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.face_id,
            "name": self.name,
            "description": self.description,
            "image_path": self.image_path,
            "created_at": self.created_at,
        }


class LocalFaceRegistry:
    """Local face library persisted on disk and mirrored into the runtime detector."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.images_dir = self.base_dir / "images"
        self.index_path = self.base_dir / "index.json"
        self._lock = Lock()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self._profiles: dict[str, FaceProfile] = {}
        self._load()

    def _load(self) -> None:
        if not self.index_path.exists():
            self._profiles = {}
            return
        raw = json.loads(self.index_path.read_text(encoding="utf-8") or "{}")
        items = raw.get("profiles", []) if isinstance(raw, dict) else []
        profiles: dict[str, FaceProfile] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            face_id = str(item.get("face_id") or item.get("id") or "").strip()
            if not face_id:
                continue
            profiles[face_id] = FaceProfile(
                face_id=face_id,
                name=str(item.get("name") or face_id),
                description=str(item.get("description") or ""),
                image_path=str(item.get("image_path") or ""),
                embedding=[float(value) for value in list(item.get("embedding") or [])],
                bbox=[int(value) for value in list(item.get("bbox") or [])[:4]],
                created_at=float(item.get("created_at") or time()),
            )
        self._profiles = profiles

    def _save(self) -> None:
        payload = {
            "profiles": [
                {
                    "face_id": item.face_id,
                    "name": item.name,
                    "description": item.description,
                    "image_path": item.image_path,
                    "embedding": item.embedding,
                    "bbox": item.bbox,
                    "created_at": item.created_at,
                }
                for item in sorted(self._profiles.values(), key=lambda value: value.created_at, reverse=True)
            ]
        }
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._lock:
            return [item.public_dict() for item in sorted(self._profiles.values(), key=lambda value: value.created_at, reverse=True)]

    def count(self) -> int:
        with self._lock:
            return len(self._profiles)

    def image_file(self, face_id: str) -> Path | None:
        with self._lock:
            profile = self._profiles.get(face_id)
            if profile is None:
                return None
            path = Path(profile.image_path)
            return path if path.exists() else None

    def sync_detector(self, detector: Any) -> int:
        if detector is None:
            return 0
        with self._lock:
            embeddings = {item.face_id: item.embedding for item in self._profiles.values()}
        if hasattr(detector, "set_known_faces"):
            detector.set_known_faces(embeddings)
        else:
            if hasattr(detector, "clear_known_faces"):
                detector.clear_known_faces()
            for face_id, embedding in embeddings.items():
                detector.add_known_face(face_id, embedding)
        return len(embeddings)

    def register_face(self, *, name: str, description: str, image_data_url: str, detector: Any) -> dict[str, Any]:
        if cv2 is None or np is None:
            raise RuntimeError("OpenCV / numpy unavailable for face upload")
        if detector is None:
            raise RuntimeError("face detector unavailable")
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("name is required")
        normalized_description = str(description or "").strip()
        image_bytes, extension = self._decode_image_data_url(image_data_url)
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("failed to decode uploaded image")

        embedding, bbox = detector.extract_reference_embedding(image)
        face_id = self._make_face_id(normalized_name)
        image_path = self.images_dir / f"{face_id}.{extension}"
        image_path.write_bytes(image_bytes)

        profile = FaceProfile(
            face_id=face_id,
            name=normalized_name,
            description=normalized_description,
            image_path=str(image_path),
            embedding=[float(value) for value in list(embedding)],
            bbox=[int(value) for value in list(bbox)[:4]],
            created_at=time(),
        )
        with self._lock:
            self._profiles[face_id] = profile
            self._save()
        self.sync_detector(detector)
        return profile.public_dict()

    def delete_face(self, face_id: str, detector: Any | None = None) -> bool:
        removed: FaceProfile | None = None
        with self._lock:
            removed = self._profiles.pop(face_id, None)
            if removed is None:
                return False
            self._save()
        if removed.image_path:
            try:
                Path(removed.image_path).unlink(missing_ok=True)
            except Exception:
                pass
        if detector is not None:
            self.sync_detector(detector)
        return True

    @staticmethod
    def _decode_image_data_url(value: str) -> tuple[bytes, str]:
        match = _DATA_URL_RE.match(str(value or "").strip())
        if match is None:
            raise ValueError("expected image data URL")
        extension = str(match.group("ext") or "jpg").lower()
        if extension == "jpeg":
            extension = "jpg"
        data = match.group("data")
        return base64.b64decode(data), extension

    def _make_face_id(self, name: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
        prefix = normalized or "face"
        candidate = prefix
        with self._lock:
            if candidate not in self._profiles:
                return candidate
        return f"{prefix}-{uuid4().hex[:8]}"
