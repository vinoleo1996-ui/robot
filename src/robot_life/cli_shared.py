from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import re
import sys
from time import sleep
from typing import Any, Mapping

from rich.console import Console

from robot_life.common.config import ArbitrationConfig, load_arbitration_config
from robot_life.common.schemas import EventPriority
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.decision_queue import DecisionQueue


console = Console()


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "runtime" / "app.default.yaml"


def _default_detector_config_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "configs"
        / "detectors"
        / "local"
        / "local_mac_companion_demo.yaml"
    )


def _default_slow_scene_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "slow_scene" / "default.yaml"


def _default_stabilizer_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "stabilizer" / "default.yaml"


def _default_arbitration_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "arbitration" / "default.yaml"


def _default_safety_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "safety" / "default.yaml"


def _camera_read_timeout_s(timeout_ms: int) -> float:
    return max(20, int(timeout_ms)) / 1000.0


def _build_arbitrator(arbitration_config: Path | None = None) -> Arbitrator:
    config_path = arbitration_config or _default_arbitration_config_path()
    return Arbitrator(config=load_arbitration_config(config_path))


def _resolve_event_priorities(arbitration_config: ArbitrationConfig) -> dict[str, EventPriority]:
    resolved: dict[str, EventPriority] = {}
    for event_type, priority_name in arbitration_config.event_priorities.items():
        try:
            resolved[str(event_type)] = EventPriority(str(priority_name))
        except ValueError:
            continue
    return resolved


def _build_arbitration_runtime(
    arbitrator: Arbitrator,
    arbitration_config: ArbitrationConfig,
) -> ArbitrationRuntime:
    queue_config = dict(arbitration_config.queue or {})
    queue_max_size = max(1, int(queue_config.get("max_size", 32)))
    queue_timeout_ms = max(0, int(queue_config.get("timeout_ms", 5_000)))
    batch_window_ms = max(1, int(queue_config.get("batch_window_ms", 40)))
    p1_queue_limit = max(1, int(queue_config.get("p1_queue_limit", 3)))
    p2_queue_limit = max(1, int(queue_config.get("p2_queue_limit", 4)))
    starvation_after_ms = max(0, int(queue_config.get("starvation_after_ms", 1_500)))
    runtime_queue = DecisionQueue(default_timeout_ms=queue_timeout_ms, max_size=queue_max_size)
    runtime = ArbitrationRuntime(
        arbitrator=arbitrator,
        queue=runtime_queue,
        batch_window_ms=batch_window_ms,
        p1_queue_limit=p1_queue_limit,
        p2_queue_limit=p2_queue_limit,
        starvation_after_ms=starvation_after_ms,
    )
    return runtime


def _looks_like_placeholder_path(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"na", "n/a", "tbd", "todo", "placeholder", "none", "null", "-"}


def _audit_detector_model_paths(
    detector_cfg: Mapping[str, object],
    *,
    enabled_pipelines: list[str],
) -> tuple[list[str], list[str]]:
    detectors = detector_cfg.get("detectors", {})
    if not isinstance(detectors, Mapping):
        return [], []

    errors: list[str] = []
    warnings: list[str] = []
    enabled = set(enabled_pipelines)
    autoload_models = {
        "yolov8n.pt",
        "yolov8s.pt",
        "yolov8m.pt",
        "yolov8l.pt",
        "yolov8x.pt",
        "yolov8n-pose.pt",
    }

    for pipeline_name, payload in detectors.items():
        if pipeline_name not in enabled:
            continue
        if not isinstance(payload, Mapping):
            continue
        if not bool(payload.get("enabled", True)):
            continue
        model_path = str(payload.get("model_path", "")).strip()
        if not model_path:
            errors.append(f"{pipeline_name}: model_path is empty")
            continue
        if _looks_like_placeholder_path(model_path):
            errors.append(f"{pipeline_name}: placeholder model_path={model_path}")
            continue
        if model_path.startswith("builtin:"):
            continue
        if model_path in autoload_models:
            warnings.append(f"{pipeline_name}: model {model_path} uses auto-download strategy")
            continue
        if not Path(model_path).exists():
            errors.append(f"{pipeline_name}: model path not found: {model_path}")

    return errors, warnings


def _probe_camera_index(index: int) -> bool:
    return _probe_camera_descriptor(index) is not None


def _probe_camera_descriptor(index: int) -> dict[str, Any] | None:
    try:
        import cv2
    except Exception:
        return None

    backend_candidates: list[int | None] = [None]
    if sys.platform == "darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
        backend_candidates.insert(0, int(cv2.CAP_AVFOUNDATION))

    for backend in backend_candidates:
        for attempt in range(3):
            capture = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
            try:
                if not capture.isOpened() and backend is not None:
                    capture.release()
                    capture = cv2.VideoCapture(index)
                if not capture.isOpened():
                    if attempt < 2:
                        sleep(0.1)
                    continue
                if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
                    try:
                        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1.0)
                    except Exception:
                        pass
                ok, frame = capture.read()
                if ok and frame is not None:
                    getter = getattr(capture, "get", None)
                    width = int(
                        getattr(frame, "shape", [0, 0])[1]
                        or (getter(cv2.CAP_PROP_FRAME_WIDTH) if callable(getter) else 0)
                        or 0
                    )
                    height = int(
                        getattr(frame, "shape", [0, 0])[0]
                        or (getter(cv2.CAP_PROP_FRAME_HEIGHT) if callable(getter) else 0)
                        or 0
                    )
                    fps = float((getter(cv2.CAP_PROP_FPS) if callable(getter) else 0.0) or 0.0)
                    backend_name = "default"
                    if hasattr(capture, "getBackendName"):
                        try:
                            backend_name = str(capture.getBackendName() or backend_name)
                        except Exception:
                            backend_name = "default"
                    return {
                        "index": index,
                        "backend": backend,
                        "backend_name": backend_name,
                        "width": width,
                        "height": height,
                        "fps": fps,
                    }
                if attempt < 2:
                    sleep(0.1)
            finally:
                capture.release()
    return None


def _darwin_camera_policy() -> str:
    raw = os.getenv("ROBOT_LIFE_CAMERA_POLICY", "builtin_only" if sys.platform == "darwin" else "any")
    normalized = str(raw).strip().lower()
    return normalized or "any"


def _darwin_builtin_camera_name_score(name: str) -> int:
    normalized = str(name).strip().lower()
    if not normalized:
        return -100
    if any(token in normalized for token in ("iphone", "ipad", "continuity", "的相机", "camera extension")):
        return -100
    score = 0
    if "facetime" in normalized:
        score += 200
    if any(token in normalized for token in ("built-in", "builtin", "内建", "內建", "高清相机", "高清攝像頭")):
        score += 100
    return score


def _darwin_list_video_devices() -> list[dict[str, Any]]:
    try:
        import AVFoundation
        from CoreMedia import CMVideoFormatDescriptionGetDimensions
    except Exception:
        return []

    try:
        devices = AVFoundation.AVCaptureDevice.devicesWithMediaType_(AVFoundation.AVMediaTypeVideo)
    except Exception:
        return []

    results: list[dict[str, Any]] = []
    for device in devices or []:
        name = str(device.localizedName() or "").strip()
        active_size: tuple[int, int] | None = None
        try:
            active_format = device.activeFormat()
            dims = CMVideoFormatDescriptionGetDimensions(active_format.formatDescription())
            active_size = (int(dims.width), int(dims.height))
        except Exception:
            active_size = None

        sizes: set[tuple[int, int]] = set()
        try:
            for fmt in device.formats() or []:
                dims = CMVideoFormatDescriptionGetDimensions(fmt.formatDescription())
                sizes.add((int(dims.width), int(dims.height)))
        except Exception:
            sizes = set()

        results.append(
            {
                "name": name,
                "unique_id": str(device.uniqueID() or "").strip(),
                "active_size": active_size,
                "sizes": sizes,
                "builtin_score": _darwin_builtin_camera_name_score(name),
            }
        )
    return results


def _preferred_darwin_builtin_camera_index(max_probe_index: int = 10) -> int | None:
    devices = [item for item in _darwin_list_video_devices() if int(item.get("builtin_score", -100)) > 0]
    if len(devices) != 1:
        return None

    all_devices = _darwin_list_video_devices()
    if not all_devices:
        return None
    builtin_names = {str(item.get("name", "")).strip() for item in devices}
    builtin_positions = [
        index for index, item in enumerate(all_devices) if str(item.get("name", "")).strip() in builtin_names
    ]
    if len(builtin_positions) != 1:
        return None

    builtin_position = builtin_positions[0]
    # OpenCV's AVFoundation index order on macOS is reversed relative to the
    # AVCaptureDevice enumeration order. Resolve from that order directly so we
    # never have to probe Continuity Camera candidates just to find FaceTime.
    resolved_index = (len(all_devices) - 1) - builtin_position
    if resolved_index < 0:
        return None
    return min(int(max_probe_index), resolved_index)


def _discover_camera_candidates(max_probe_index: int = 10) -> list[int]:
    detected: list[int] = []
    for device in sorted(Path("/dev").glob("video*"), reverse=True):
        match = re.search(r"(\d+)$", device.name)
        if not match:
            continue
        detected.append(int(match.group(1)))

    if detected:
        seen: set[int] = set()
        candidates: list[int] = []
        for index in detected:
            if index not in seen:
                seen.add(index)
                candidates.append(index)
        return candidates

    if sys.platform == "darwin":
        # macOS camera indices are typically a very small contiguous range.
        # Probing 10..0 creates noisy AVFoundation failures and can destabilize
        # real-device startup. Prefer a narrow local scan first.
        upper = min(max_probe_index, 2)
        return list(range(upper, -1, -1))

    return list(range(max_probe_index, -1, -1))


def _resolve_camera_device(
    requested_index: int,
    *,
    max_probe_index: int = 10,
    allow_remap: bool = True,
) -> tuple[int, list[int]]:
    if sys.platform == "darwin" and _darwin_camera_policy() == "builtin_only":
        if requested_index > 0 and _probe_camera_index(requested_index):
            return requested_index, [requested_index]
        preferred_builtin_index = _preferred_darwin_builtin_camera_index(max_probe_index=max_probe_index)
        if preferred_builtin_index is None:
            raise RuntimeError(
                "未能可靠识别 Mac 内建 FaceTime 相机；为避免误连 iPhone 连续互通相机，已拒绝自动启动。"
                "请先断开 Continuity Camera，或显式设置 ROBOT_LIFE_CAMERA_POLICY=any 后再试。"
            )
        if _probe_camera_index(preferred_builtin_index):
            return preferred_builtin_index, [preferred_builtin_index]
        raise RuntimeError(
            f"已识别内建 FaceTime 相机索引为 {preferred_builtin_index}，但当前无法打开。"
            "请检查相机权限和占用状态后重试。"
        )

    probe_order: list[int] = []
    seen: set[int] = set()

    if requested_index >= 0:
        probe_order.append(requested_index)
        seen.add(requested_index)

    for index in _discover_camera_candidates(max_probe_index=max_probe_index):
        if index not in seen:
            seen.add(index)
            probe_order.append(index)

    if requested_index >= 0 and _probe_camera_index(requested_index):
        return requested_index, [requested_index]

    if requested_index >= 0 and not allow_remap:
        if sys.platform == "darwin":
            raise RuntimeError(
                f"请求摄像头索引 {requested_index} 不可用。"
                "请检查“系统设置 -> 隐私与安全性 -> 相机”是否已授权当前终端，"
                "并确认没有其他应用占用摄像头。"
            )
        raise RuntimeError(
            f"请求摄像头索引 {requested_index} 不可用。请检查设备连接、权限和占用状态。"
        )

    for index in probe_order:
        if index == requested_index:
            continue
        if _probe_camera_index(index):
            return index, [index]

    if sys.platform == "darwin":
        raise RuntimeError(
            "未找到可用摄像头设备。请先检查“系统设置 -> 隐私与安全性 -> 相机”权限，"
            "并关闭可能占用摄像头的应用后重试。"
        )
    raise RuntimeError("未找到可用摄像头设备。请确认摄像头已连接，并检查 /dev/video* 权限。")


def _extract_json_payload_from_text(raw_text: str | None) -> dict:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    try:
        from robot_life.perception.adapters.gguf_qwen_adapter import GGUFQwenVLAdapter

        payload = GGUFQwenVLAdapter._extract_first_json_object(text)  # noqa: SLF001
        if payload:
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}
    return {}


def _decision_signature(payload: dict) -> str:
    decision = payload.get("决策信息", {}) if isinstance(payload.get("决策信息"), dict) else {}
    action = payload.get("执行动作", {}) if isinstance(payload.get("执行动作"), dict) else {}
    event = payload.get("事件信息", {}) if isinstance(payload.get("事件信息"), dict) else {}
    people = payload.get("人员信息", [])
    presence = "unknown"
    if isinstance(people, list) and people:
        item = people[0] if isinstance(people[0], dict) else {}
        presence = str(item.get("是否在场", "未知")).strip() or "未知"
    core = {
        "presence": presence,
        "speak": str(decision.get("是否说话", "未知")).strip(),
        "behavior": str(decision.get("交互行为类型", "未知")).strip(),
        "target": str(decision.get("交互目标", "未知")).strip(),
        "risk": str(event.get("风险等级", "未知")).strip(),
        "strategy": str(action.get("后续跟进策略", "未知")).strip(),
    }
    return json.dumps(core, ensure_ascii=False, sort_keys=True)


def _decision_signature_hash(payload: dict) -> str:
    signature = _decision_signature(payload)
    return hashlib.md5(signature.encode("utf-8")).hexdigest()[:8]
