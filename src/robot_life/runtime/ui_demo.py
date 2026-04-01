from __future__ import annotations

import json
import logging
import os
import psutil
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread
from time import monotonic, strftime
from typing import Any, Deque, Union, Optional
from urllib.parse import urlparse

from robot_life.perception.frame_dispatch import as_bgr_frame
from robot_life.runtime.live_loop import LiveLoop, LiveLoopResult

try:  # pragma: no cover - optional visualization dependency
    import cv2 as _cv2
except Exception:  # pragma: no cover - optional dependency
    _cv2 = None

try:  # pragma: no cover - optional visualization dependency
    import numpy as _np
except Exception:  # pragma: no cover - optional dependency
    _np = None

try:  # pragma: no cover - optional runtime dependency
    import torch as _torch
except Exception:  # pragma: no cover - optional dependency
    _torch = None

try:  # pragma: no cover - optional runtime dependency
    import pynvml as _pynvml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _pynvml = None


logger = logging.getLogger(__name__)


def _round(value: float) -> float:
    return round(float(value), 2)


def _now_label() -> str:
    return strftime("%H:%M:%S")


def _natural_event_name(event_type: str) -> str:
    normalized = str(event_type or "").lower()
    mapping = {
        "familiar_face": "识别到熟悉的人",
        "stranger_face": "识别到陌生人",
        "gaze_sustained": "对方正在注视机器人",
        "gaze_away": "对方目光移开",
        "loud_sound": "检测到较大声响",
        "motion": "检测到明显移动",
        "gesture_open_palm": "手势：张开手掌",
        "gesture_closed_fist": "手势：握拳",
        "gesture_pointing_up": "手势：指向上方",
        "gesture_victory": "手势：比耶",
        "gesture_thumb_up": "手势：点赞",
        "gesture_thumb_down": "手势：倒拇指",
    }
    if normalized in mapping:
        return mapping[normalized]
    if normalized.startswith("gesture_"):
        return f"手势：{normalized.removeprefix('gesture_')}"
    return normalized or "未知事件"


def _natural_scene_name(scene_type: str) -> str:
    normalized = str(scene_type or "").lower()
    mapping = {
        "greeting_scene": "打招呼场景",
        "attention_scene": "关注场景",
        "stranger_attention_scene": "陌生人关注场景",
        "safety_alert_scene": "安全提醒场景",
        "gesture_bond_scene": "手势互动场景",
        "ambient_tracking_scene": "环境观察场景",
    }
    return mapping.get(normalized, normalized or "未知场景")


def _natural_behavior_name(behavior: str) -> str:
    normalized = str(behavior or "").lower()
    mapping = {
        "perform_greeting": "主动问候",
        "perform_attention": "主动关注",
        "perform_safety_alert": "安全提醒",
        "perform_gesture_response": "手势回应",
        "perform_tracking": "环境跟随观察",
        "greeting_visual_only": "视觉问候",
        "attention_minimal": "最小关注响应",
        "gesture_visual_only": "视觉手势回应",
        "greeting_light": "轻量问候",
        "safety_alert": "安全提醒",
        "attention_ping": "主动关注",
        "ambient_track": "环境跟随观察",
        "gesture_response": "手势反馈",
    }
    return mapping.get(normalized, normalized or "待定动作")


def _natural_mode_name(mode: str) -> str:
    normalized = str(mode or "").lower()
    mapping = {
        "execute": "立即执行",
        "queue": "排队等待",
        "drop": "放弃执行",
        "degrade_and_execute": "降级后执行",
        "soft_interrupt": "软打断",
        "hard_interrupt": "硬打断",
    }
    return mapping.get(normalized, normalized or "未知模式")


def _natural_detector_name(detector: str) -> str:
    normalized = str(detector or "").lower()
    mapping = {
        "insightface_face": "人脸识别器",
        "mediapipe_face": "人脸检测器",
        "mediapipe_gesture": "手势识别器",
        "mediapipe_gaze": "注视识别器",
        "mediapipe_iris": "注视识别器",
        "rms_audio": "音频响度检测器",
        "panns_whisper_audio": "语义音频检测器",
        "whisper_asr": "语音识别器",
        "yolo_motion": "运动检测器（YOLO）",
        "opencv_motion": "运动检测器（OpenCV）",
    }
    return mapping.get(normalized, detector or "未知检测器")


def _infer_pipeline_name(*, detector: str | None = None, event_type: str | None = None) -> str:
    normalized_detector = str(detector or "").lower()
    normalized_event = str(event_type or "").lower()
    if any(token in normalized_detector for token in ("face", "insightface")) or "face" in normalized_event:
        return "face"
    if "gesture" in normalized_detector or "gesture" in normalized_event:
        return "gesture"
    if any(token in normalized_detector for token in ("gaze", "iris")) or "gaze" in normalized_event:
        return "gaze"
    if any(token in normalized_detector for token in ("audio", "yamnet", "whisper", "rms")) or any(
        token in normalized_event for token in ("sound", "audio")
    ):
        return "audio"
    if "motion" in normalized_detector or "motion" in normalized_event:
        return "motion"
    return "unknown"


def _short_trace(trace_id: str) -> str:
    value = str(trace_id or "")
    if len(value) <= 8:
        return value or "-"
    return value[-8:]


def _collect_gpu_metrics() -> dict[str, Any]:
    backend = "none"
    gpu_percent: float | None = None
    note = "gpu_unavailable"

    if _torch is not None:
        try:
            if _torch.cuda.is_available():
                backend = "cuda"
                note = "cuda"
                if _pynvml is not None:
                    try:
                        _pynvml.nvmlInit()
                        handle = _pynvml.nvmlDeviceGetHandleByIndex(0)
                        util = _pynvml.nvmlDeviceGetUtilizationRates(handle)
                        gpu_percent = float(getattr(util, "gpu", 0.0))
                        note = "nvml"
                    except Exception:
                        gpu_percent = None
                        note = "cuda_no_nvml"
            elif bool(getattr(_torch.backends, "mps", None)) and _torch.backends.mps.is_available():
                backend = "mps"
                note = "mps_util_not_exposed"
        except Exception:
            backend = "unknown"
            note = "gpu_probe_failed"

    return {"gpu_percent": None if gpu_percent is None else _round(gpu_percent), "gpu_backend": backend, "gpu_note": note}


def _estimate_gpu_percent_from_pipelines(pipeline_statuses: list[dict[str, Any]]) -> float | None:
    """Estimate GPU utilization from pipeline duty cycle when direct metrics are unavailable."""
    duty = 0.0
    has_gpu_pipeline = False
    for item in pipeline_statuses:
        target = str(item.get("compute_target", "")).lower()
        if target not in {"gpu", "gpu+cpu"}:
            continue
        has_gpu_pipeline = True
        duration_ms = item.get("last_duration_ms")
        runtime_budget_ms = item.get("runtime_budget_ms")
        sample_rate_hz = item.get("sample_rate_hz")
        try:
            rate = float(sample_rate_hz)
        except (TypeError, ValueError):
            continue
        if rate <= 0:
            continue
        try:
            duration = float(duration_ms)
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            # Runtime stats may lag at startup on MPS. Use a conservative fraction
            # of budget so the dashboard doesn't stay at N/A forever.
            try:
                budget = float(runtime_budget_ms)
            except (TypeError, ValueError):
                budget = 0.0
            if budget > 0:
                duration = budget * 0.35
        if duration <= 0:
            continue
        duty += duration * rate / 10.0
    if duty <= 0:
        return 5.0 if has_gpu_pipeline else None
    return _round(max(0.0, min(100.0, duty)))


def _infer_pipeline_compute_target(pipeline: dict[str, Any]) -> str:
    implementation = str(pipeline.get("implementation", "")).lower()
    if "mock" in implementation:
        return "mock"
    if "noop" in implementation:
        return "none"

    detector_config = pipeline.get("detector_config", {})
    if not isinstance(detector_config, dict):
        detector_config = {}
    has_use_gpu_flag = "use_gpu" in detector_config or "enable_gpu" in detector_config
    use_gpu = bool(detector_config.get("use_gpu", detector_config.get("enable_gpu", False)))
    require_gpu = bool(detector_config.get("require_gpu", False))
    device = str(detector_config.get("device", "")).lower()
    providers = detector_config.get("providers")
    providers_text = ",".join(str(item).lower() for item in providers) if isinstance(providers, list) else ""
    if require_gpu or use_gpu:
        return "gpu"
    if has_use_gpu_flag and not use_gpu:
        return "cpu"
    if any(token in device for token in ("cuda", "mps", "gpu")):
        return "gpu"
    if "cudaexecutionprovider" in providers_text:
        return "gpu+cpu"
    return "cpu"


def _runtime_compute_target(detector: Any, pipeline_payload: dict[str, Any]) -> tuple[str, str]:
    """Infer actual compute target from initialized detector state when available."""
    if detector is not None and hasattr(detector, "_using_gpu"):
        try:
            using_gpu = bool(getattr(detector, "_using_gpu"))
            return ("gpu" if using_gpu else "cpu"), "runtime_delegate"
        except Exception:
            pass

    if detector is not None:
        raw_device = getattr(detector, "_device", None)
        if raw_device is None:
            raw_device = getattr(detector, "device", None)
        if raw_device not in {None, ""}:
            device_text = str(raw_device).lower()
            if any(token in device_text for token in ("cuda", "mps", "gpu")):
                return "gpu", "runtime_device"
            return "cpu", "runtime_device"

    return _infer_pipeline_compute_target(pipeline_payload), "config_inferred"


def _natural_pipeline_status(status: str) -> str:
    normalized = str(status or "").lower()
    mapping = {
        "ready": "已就绪",
        "degraded": "降级可用",
        "failed": "初始化失败",
        "disabled": "已禁用",
        "loading": "加载中",
        "partial": "部分可用",
        "unavailable": "不可用",
        "empty": "未配置",
    }
    return mapping.get(normalized, status or "未知")


def _natural_source_kind(kind: str) -> str:
    normalized = str(kind or "").lower()
    mapping = {
        "mock": "模拟源",
        "synthetic": "模拟源",
        "camera": "真实摄像头",
        "opencv": "真实摄像头",
        "sounddevice": "真实麦克风",
        "arecord": "真实麦克风",
        "microphone": "静音麦克风",
    }
    return mapping.get(normalized, kind or "未知")


def _natural_compute_target(target: str) -> str:
    normalized = str(target or "").lower()
    mapping = {
        "cpu": "CPU",
        "gpu": "GPU",
        "gpu+cpu": "GPU+CPU",
        "mock": "模拟",
        "none": "未启用",
    }
    return mapping.get(normalized, normalized or "-")


def _source_read_ok(item: dict[str, Any], packet_age_ms: float | None) -> bool:
    if item.get("is_open") is False:
        return False
    if packet_age_ms is None:
        return bool(item.get("last_read_ok", False))
    timeout_s = item.get("read_timeout_s")
    if timeout_s is not None:
        try:
            timeout_ms = max(80.0, float(timeout_s) * 1000.0)
            return packet_age_ms <= timeout_ms * 2.0
        except (TypeError, ValueError):
            pass
    source_kind = str(item.get("source_kind", "")).lower()
    if source_kind in {"sounddevice", "arecord", "microphone"}:
        return packet_age_ms <= 1200.0
    return packet_age_ms <= 800.0


def _natural_strategy_name(strategy: str) -> str:
    normalized = str(strategy or "").lower()
    mapping = {
        "nonverbal_first": "先用非语言反馈",
        "verbal_greeting": "主动语音问候",
        "immediate_action": "立即采取动作",
        "gesture_response": "优先手势回应",
        "passive_monitoring": "继续被动观察",
        "cautious": "保持谨慎",
        "alert": "进入警觉模式",
    }
    return mapping.get(normalized, strategy or "继续观察")


def _natural_emotion_name(emotion: str) -> str:
    normalized = str(emotion or "").lower()
    mapping = {
        "neutral": "平稳",
        "happy": "积极",
        "curious": "好奇",
        "alert": "警觉",
        "unknown": "未知",
        "happy_attention": "积极关注",
    }
    return mapping.get(normalized, emotion or "未知")


def _resolve_audio_detector(loop: LiveLoop) -> Any | None:
    return _resolve_pipeline_detector(loop, "audio")


def _resolve_pipeline_detector(loop: LiveLoop, pipeline_name: str) -> Any | None:
    registry = getattr(loop, "registry", None)
    if registry is None or not hasattr(registry, "get_pipeline"):
        return None
    try:
        pipeline = registry.get_pipeline(pipeline_name)
    except Exception:
        return None
    if pipeline is None:
        return None
    return getattr(pipeline, "_detector", None)


def _resolve_runtime_stabilizer(loop: LiveLoop) -> Any | None:
    return getattr(getattr(loop, "dependencies", None), "stabilizer", None)


def _resolve_runtime_aggregator(loop: LiveLoop) -> Any | None:
    return getattr(getattr(loop, "dependencies", None), "aggregator", None)


def _resolve_runtime_arbitrator(loop: LiveLoop) -> Any | None:
    deps = getattr(loop, "dependencies", None)
    return getattr(deps, "arbitrator", None)


def _event_override_value(stabilizer: Any, event_type: str, field_name: str) -> Any | None:
    if stabilizer is None:
        return None
    overrides = getattr(stabilizer, "_event_overrides", None)
    if not isinstance(overrides, dict):
        return None
    override = overrides.get(event_type)
    if override is None:
        return None
    return getattr(override, field_name, None)


def _priority_rank_value(priority: Any) -> int | None:
    text = str(getattr(priority, "value", priority) or "").strip().upper()
    if len(text) == 2 and text.startswith("P") and text[1].isdigit():
        return int(text[1])
    if text.isdigit():
        return int(text)
    return None


def _natural_urgency_name(urgency: str) -> str:
    normalized = str(urgency or "").lower()
    mapping = {"low": "低", "medium": "中", "high": "高"}
    return mapping.get(normalized, urgency or "低")


def _natural_execution_status(status: str) -> str:
    normalized = str(status or "").lower()
    mapping = {
        "finished": "已完成",
        "queued": "排队中",
        "dropped": "已丢弃",
        "interrupted": "已打断",
        "degraded": "降级执行",
        "failed": "执行失败",
        "skipped": "已跳过",
    }
    return mapping.get(normalized, status or "未知状态")


def _behavior_playbook(behavior: str, *, degraded: bool = False) -> dict[str, str]:
    normalized = str(behavior or "").lower()
    mapping: dict[str, dict[str, str]] = {
        "perform_greeting": {
            "action": "头部转向目标并挥手",
            "expression": "微笑",
            "tts": "你好呀，很高兴见到你。",
        },
        "greeting_visual_only": {
            "action": "挥手示意",
            "expression": "微笑",
            "tts": "（静默，仅视觉反馈）",
        },
        "perform_attention": {
            "action": "头部锁定并轻点头",
            "expression": "专注",
            "tts": "我在这里，你需要我做什么？",
        },
        "attention_minimal": {
            "action": "轻微转头关注",
            "expression": "平稳",
            "tts": "（短句确认）我在听。",
        },
        "perform_gesture_response": {
            "action": "跟随手势方向并做回应动作",
            "expression": "积极",
            "tts": "我看到了你的手势。",
        },
        "gesture_visual_only": {
            "action": "手势镜像反馈",
            "expression": "积极",
            "tts": "（静默，仅视觉反馈）",
        },
        "perform_tracking": {
            "action": "持续跟随移动目标",
            "expression": "观察",
            "tts": "我会持续关注周围动态。",
        },
        "perform_safety_alert": {
            "action": "快速转向异常源并进入警戒姿态",
            "expression": "警觉",
            "tts": "我检测到异常，请注意安全。",
        },
    }
    plan = dict(mapping.get(normalized, {
        "action": _natural_behavior_name(behavior),
        "expression": "平稳",
        "tts": "我会按当前策略继续执行。",
    }))
    if degraded and plan.get("tts") and "静默" not in str(plan.get("tts")):
        plan["tts"] = f"{plan['tts']}（降级模式：缩短播报）"
    return plan


def _extract_audio_levels(payload: Any) -> dict[str, float]:
    if _np is None:
        return {}
    candidate = payload
    if isinstance(payload, dict):
        for key in ("audio", "samples", "chunk", "data"):
            if key in payload:
                candidate = payload[key]
                break
    try:
        array = _np.asarray(candidate, dtype=_np.float64).reshape(-1)
    except Exception:
        return {}
    if array.size <= 0:
        return {}
    rms = float(_np.sqrt(_np.mean(_np.square(array))))
    db = float(20.0 * _np.log10(max(rms, 1e-12)))
    return {"last_audio_rms": _round(rms), "last_audio_db": _round(db)}


def _describe_detection_payload(payload: dict[str, Any]) -> str:
    target_id = payload.get("target_id")
    if target_id:
        return f"目标={target_id}"
    gesture_name = payload.get("gesture_name")
    if gesture_name:
        return f"手势={gesture_name}"
    area_ratio = payload.get("motion_area_ratio")
    if area_ratio is not None:
        try:
            return f"移动强度={float(area_ratio):.3f}"
        except (TypeError, ValueError):
            return "移动强度=未知"
    db = payload.get("db")
    if db is not None:
        try:
            return f"音量={float(db):.1f}dB"
        except (TypeError, ValueError):
            return "音量=未知"
    return "无附加信息"


def _render_camera_preview(
    frame: Any,
    detections: list[Any],
    *,
    annotate: bool = True,
    max_width: int = 480,
    jpeg_quality: int = 68,
) -> bytes | None:
    if _cv2 is None or _np is None:
        return None
    frame_bgr = as_bgr_frame(frame)
    if frame_bgr is None or not hasattr(frame_bgr, "shape"):
        return None
    source_h, source_w = frame_bgr.shape[:2]
    preview = frame_bgr
    if max_width > 0 and source_w > max_width:
        scale = float(max_width) / float(source_w)
        target_h = max(1, int(round(source_h * scale)))
        try:
            preview = _cv2.resize(frame_bgr, (int(max_width), target_h), interpolation=_cv2.INTER_AREA)
        except Exception:
            preview = frame_bgr
    try:
        canvas = preview.copy()
    except Exception:
        return None

    if annotate:
        h, w = canvas.shape[:2]
        scale_x = float(w) / float(source_w) if source_w > 0 else 1.0
        scale_y = float(h) / float(source_h) if source_h > 0 else 1.0
        overlays = detections[-8:]
        for detection in overlays:
            payload = detection.payload if isinstance(getattr(detection, "payload", None), dict) else {}
            label = f"{_natural_event_name(detection.event_type)} {float(getattr(detection, 'confidence', 0.0)):.2f}"
            x1, y1, x2, y2 = 18, 18, 260, 52

            bbox = payload.get("bbox")
            hand_bbox = payload.get("hand_bbox")
            if isinstance(bbox, list) and len(bbox) >= 4:
                try:
                    x1, y1, x2, y2 = [
                        int(float(bbox[0]) * scale_x),
                        int(float(bbox[1]) * scale_y),
                        int(float(bbox[2]) * scale_x),
                        int(float(bbox[3]) * scale_y),
                    ]
                except (TypeError, ValueError):
                    pass
            elif isinstance(hand_bbox, list) and len(hand_bbox) >= 4:
                try:
                    x1 = int(float(hand_bbox[0]) * w)
                    y1 = int(float(hand_bbox[1]) * h)
                    x2 = int(float(hand_bbox[2]) * w)
                    y2 = int(float(hand_bbox[3]) * h)
                except (TypeError, ValueError):
                    pass

            x1 = max(0, min(w - 1, x1))
            y1 = max(0, min(h - 1, y1))
            x2 = max(x1 + 1, min(w, x2))
            y2 = max(y1 + 1, min(h, y2))
            _cv2.rectangle(canvas, (x1, y1), (x2, y2), (35, 215, 255), 2)
            _cv2.putText(
                canvas,
                label,
                (x1, max(14, y1 - 8)),
                _cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (25, 40, 230),
                1,
                _cv2.LINE_AA,
            )

    quality = max(40, min(90, int(jpeg_quality)))
    ok, encoded = _cv2.imencode(".jpg", canvas, [_cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return None
    return encoded.tobytes()


def _sample_runtime_resources(pipeline_statuses: list[dict[str, Any]]) -> dict[str, Any]:
    gpu_metrics = _collect_gpu_metrics()
    gpu_estimated_percent = _estimate_gpu_percent_from_pipelines(pipeline_statuses)
    if gpu_metrics.get("gpu_percent") is None and gpu_estimated_percent is not None:
        if str(gpu_metrics.get("gpu_backend", "")) == "mps":
            gpu_metrics["gpu_note"] = "mps_estimated_from_pipeline_duty"

    enabled_pipelines = [item for item in pipeline_statuses if item.get("enabled")]
    gpu_pipelines = [
        item for item in enabled_pipelines if str(item.get("compute_target", "")).lower() in {"gpu", "gpu+cpu"}
    ]
    gpu_pipeline_ratio = 0.0
    if enabled_pipelines:
        gpu_pipeline_ratio = (len(gpu_pipelines) / len(enabled_pipelines)) * 100.0

    return {
        "cpu_percent": _round(psutil.cpu_percent()),
        "mem_percent": _round(psutil.virtual_memory().percent),
        "gpu_percent": gpu_metrics.get("gpu_percent"),
        "gpu_estimated_percent": gpu_estimated_percent,
        "gpu_backend": gpu_metrics.get("gpu_backend"),
        "gpu_note": gpu_metrics.get("gpu_note"),
        "gpu_pipeline_ratio": _round(gpu_pipeline_ratio),
        "sampled_at": monotonic(),
    }


def _build_reaction(result: LiveLoopResult) -> dict[str, str]:
    detections = result.detections[-3:]
    scenes = result.scene_candidates[-1:]
    decisions = result.arbitration_results[-1:]
    executions = result.execution_results[-1:]
    scene_batches = getattr(result, "scene_batches", {}) if isinstance(getattr(result, "scene_batches", {}), dict) else {}

    saw_text = "当前没有稳定感知结果"
    if detections:
        saw_text = ", ".join(
            f"{_natural_event_name(item.event_type)}（置信度{float(getattr(item, 'confidence', 0.0)):.2f}）"
            for item in detections
        )

    scene_text = _natural_scene_name(scenes[0].scene_type) if scenes else "暂未形成场景"
    decision_text = "暂未决策"
    executed_text = "暂未执行"
    robot_response_text = "继续观察，暂不触发动作"
    action_text = "保持观察"
    expression_text = "平稳"
    tts_text = "（不播报）"
    if scenes:
        payload = scenes[0].payload if isinstance(scenes[0].payload, dict) else {}
        interaction_state = str(payload.get("interaction_state", "")).strip()
        engagement_score = payload.get("engagement_score")
        scene_path = str(payload.get("scene_path", "")).strip()
        details: list[str] = [scene_text]
        if scene_path:
            details.append(f"通路={scene_path}")
        if interaction_state:
            details.append(f"交互态={interaction_state}")
        if engagement_score is not None:
            try:
                details.append(f"参与度={float(engagement_score):.2f}")
            except (TypeError, ValueError):
                pass
        scene_text = "，".join(details)
    if decisions:
        decision = decisions[0]
        decision_bits = [
            _natural_behavior_name(decision.target_behavior),
            _natural_mode_name(decision.mode.value),
        ]
        if decision.scene_type:
            decision_bits.append(_natural_scene_name(decision.scene_type))
        if decision.engagement_score is not None:
            decision_bits.append(f"参与度={float(decision.engagement_score):.2f}")
        if decision.scene_path:
            decision_bits.append(f"通路={decision.scene_path}")
        decision_text = "，".join(decision_bits)
        plan = _behavior_playbook(decision.target_behavior, degraded=decision.mode.value == "degrade_and_execute")
        action_text = plan["action"]
        expression_text = plan["expression"]
        tts_text = plan["tts"]
        robot_response_text = f"准备回应：动作={action_text}，表情={expression_text}，TTS={tts_text}"
    if executions:
        execution = executions[0]
        degraded = "降级执行" if execution.degraded else "正常执行"
        plan = _behavior_playbook(execution.behavior_id, degraded=execution.degraded)
        action_text = plan["action"]
        expression_text = plan["expression"]
        tts_text = plan["tts"]
        executed_bits = [
            _natural_behavior_name(execution.behavior_id),
            execution.status,
            degraded,
        ]
        if execution.scene_type:
            executed_bits.append(_natural_scene_name(execution.scene_type))
        if execution.target_id:
            executed_bits.append(f"目标={execution.target_id}")
        executed_text = "，".join(executed_bits)
        robot_response_text = f"已回应：动作={action_text}，表情={expression_text}，TTS={tts_text}"

    route_bits: list[str] = []
    for path_name in ("safety", "social"):
        path_scenes = scene_batches.get(path_name, [])
        if not path_scenes:
            route_bits.append(f"{path_name}=无")
            continue
        route_bits.append(
            f"{path_name}="
            + " / ".join(_natural_scene_name(getattr(item, "scene_type", "")) for item in path_scenes[:3])
        )
    route_text = "；".join(route_bits) if route_bits else "safety=无；social=无"

    return {
        "saw": saw_text,
        "react": robot_response_text,
        "scene": scene_text,
        "decision": decision_text,
        "detected_event": saw_text,
        "arbitration_logic": decision_text,
        "executed_event": executed_text,
        "robot_response": robot_response_text,
        "action": action_text,
        "expression": expression_text,
        "tts": tts_text,
        "route_summary": route_text,
    }


def _natural_slow_scene_text(scene_json: Any) -> str:
    if scene_json is None:
        return "慢思考暂无输出"
    try:
        scene_name = _natural_scene_name(getattr(scene_json, "scene_type", "") or "")
        confidence = float(getattr(scene_json, "confidence", 0.0))
        emotion = _natural_emotion_name(str(getattr(scene_json, "emotion_hint", "未知")))
        urgency = _natural_urgency_name(str(getattr(scene_json, "urgency_hint", "低")))
        strategy = _natural_strategy_name(str(getattr(scene_json, "recommended_strategy", "继续观察")))
        return (
            f"慢思考判断为“{scene_name}”，置信度{confidence:.2f}，"
            f"情绪线索“{emotion}”，紧急度“{urgency}”，建议“{strategy}”。"
        )
    except Exception:
        return "慢思考输出解析失败"


def _collect_fast_reaction_snapshot(loop: LiveLoop) -> dict[str, Any]:
    registry = getattr(loop, "registry", None)
    if registry is None or not hasattr(registry, "list_pipelines") or not hasattr(registry, "get_pipeline"):
        return {
            "expected": 0,
            "loaded": 0,
            "degraded": 0,
            "failed": 0,
            "progress_percent": 0.0,
            "status": "unavailable",
            "pipelines": [],
        }

    status_snapshot = {}
    if hasattr(registry, "snapshot_pipeline_statuses"):
        try:
            status_snapshot = registry.snapshot_pipeline_statuses()
        except Exception:
            status_snapshot = {}
    runtime_snapshot = {}
    if hasattr(registry, "snapshot_runtime_stats"):
        try:
            runtime_snapshot = registry.snapshot_runtime_stats()
        except Exception:
            runtime_snapshot = {}

    pipelines: list[dict[str, Any]] = []
    for pipeline_name in registry.list_pipelines():
        pipeline = registry.get_pipeline(pipeline_name)
        if pipeline is None:
            continue
        spec = getattr(pipeline, "spec", None)
        pipeline_status = status_snapshot.get(pipeline_name, {}) if isinstance(status_snapshot, dict) else {}
        enabled = bool(pipeline_status.get("enabled", getattr(spec, "enabled", True)))
        reason = str(pipeline_status.get("reason", getattr(pipeline, "reason", "")) or "")
        running = False
        if hasattr(pipeline, "is_running"):
            try:
                running = bool(pipeline.is_running())
            except Exception:
                running = bool(getattr(pipeline, "_running", False))
        else:
            running = bool(getattr(pipeline, "_running", False))

        detector_ready = False
        detector_config: dict[str, Any] = {}
        detector = getattr(pipeline, "_detector", None)
        if detector is not None and hasattr(detector, "is_ready"):
            try:
                detector_ready = bool(detector.is_ready())
            except Exception:
                detector_ready = False
        if detector is not None:
            raw_config = getattr(detector, "config", None)
            if isinstance(raw_config, dict):
                detector_config = {
                    "use_gpu": raw_config.get("use_gpu", raw_config.get("enable_gpu", False)),
                    "require_gpu": raw_config.get("require_gpu", False),
                    "device": raw_config.get("device"),
                    "providers": raw_config.get("providers"),
                    "rms_threshold": raw_config.get("rms_threshold"),
                    "db_threshold": raw_config.get("db_threshold", raw_config.get("energy_threshold_db")),
                }

        status = str(
            pipeline_status.get("status")
            or pipeline_status.get("init_status")
            or ""
        ).strip().lower()
        if not status:
            if not enabled:
                status = "disabled"
            elif reason:
                status = "degraded"
            elif running or detector_ready:
                status = "ready"
            else:
                status = "loading"
        implementation = str(
            pipeline_status.get("implementation")
            or type(pipeline).__name__
            or "unknown"
        )
        runtime_meta = runtime_snapshot.get(pipeline_name, {}) if isinstance(runtime_snapshot, dict) else {}
        loaded = status == "ready"
        pipeline_payload = {
            "name": pipeline_name,
            "enabled": enabled,
            "loaded": loaded,
            "running": running,
            "detector_ready": detector_ready,
            "status": status,
            "implementation": implementation,
            "reason": reason,
            "init_status": str(pipeline_status.get("init_status", "")),
            "runtime_budget_ms": runtime_meta.get("runtime_budget_ms"),
            "last_duration_ms": runtime_meta.get("last_duration_ms"),
            "sample_rate_hz": runtime_meta.get("sample_rate_hz"),
            "budget_skips": runtime_meta.get("budget_skips", 0),
            "detector_config": detector_config,
        }
        pipeline_payload["compute_target"], pipeline_payload["compute_target_source"] = _runtime_compute_target(
            detector,
            pipeline_payload,
        )
        requested_gpu = bool(detector_config.get("use_gpu") or detector_config.get("require_gpu"))
        if requested_gpu and pipeline_payload["compute_target"] == "cpu":
            fallback_reason = "gpu_requested_but_runtime_fallback_cpu"
            if reason:
                if fallback_reason not in reason:
                    pipeline_payload["reason"] = f"{reason};{fallback_reason}"
            else:
                pipeline_payload["reason"] = fallback_reason
        pipeline_payload["compute_target_label"] = _natural_compute_target(str(pipeline_payload["compute_target"]))
        pipelines.append(
            pipeline_payload
        )

    expected = sum(1 for item in pipelines if item["enabled"])
    loaded = sum(1 for item in pipelines if item["enabled"] and item["loaded"])
    degraded = sum(1 for item in pipelines if item["enabled"] and item["status"] == "degraded")
    failed = sum(1 for item in pipelines if item["enabled"] and item["status"] == "failed")
    if expected <= 0:
        progress = 0.0
        status = "empty"
    else:
        progress = (loaded / expected) * 100.0
        if failed > 0:
            status = "degraded"
        elif loaded == expected and degraded == 0:
            status = "ready"
        elif loaded == 0 and degraded == 0:
            status = "loading"
        else:
            status = "partial"
    return {
        "expected": expected,
        "loaded": loaded,
        "degraded": degraded,
        "failed": failed,
        "progress_percent": _round(progress),
        "status": status,
        "pipelines": pipelines[:8],
    }


def _collect_slow_reaction_snapshot(slow_scene_snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(slow_scene_snapshot, dict):
        return {
            "progress_percent": 0.0,
            "status": "unavailable",
            "adapter_loaded": False,
            "worker_alive": False,
            "queue_depth": 0,
        }

    health = slow_scene_snapshot.get("health", {})
    if not isinstance(health, dict):
        health = {}

    adapter_loaded = bool(slow_scene_snapshot.get("adapter_loaded", False))
    adapter_ready = bool(health.get("adapter_ready", False))
    worker_alive = bool(health.get("worker_alive", False))
    ready = bool(health.get("ready", False))
    queue_depth = int(health.get("queue_depth", 0) or 0)
    timed_out = int(health.get("timed_out_requests", 0) or 0)

    score = 0.0
    if adapter_loaded:
        score += 40.0
    if adapter_ready:
        score += 30.0
    if worker_alive and ready:
        score += 30.0

    if score >= 100.0:
        status = "ready"
    elif score <= 0:
        status = "loading"
    else:
        status = "partial"

    return {
        "progress_percent": _round(score),
        "status": status,
        "adapter_loaded": adapter_loaded,
        "adapter_ready": adapter_ready,
        "worker_alive": worker_alive,
        "queue_depth": queue_depth,
        "timed_out_requests": timed_out,
    }


def _infer_packet_source_kind(packet: Any) -> str | None:
    metadata = getattr(packet, "metadata", None)
    if isinstance(metadata, dict):
        raw_kind = metadata.get("source_kind")
        if raw_kind:
            return str(raw_kind)

    payload = getattr(packet, "payload", None)
    if isinstance(payload, dict):
        if payload.get("synthetic_frame") or payload.get("synthetic_audio"):
            return "mock"
        raw_kind = payload.get("source_kind")
        if raw_kind:
            return str(raw_kind)
    return None


def _infer_source_kind(source: Any) -> str:
    class_name = type(source).__name__.lower()
    if "synthetic" in class_name:
        return "mock"
    if "camera" in class_name:
        return "opencv"
    if "sounddevice" in class_name:
        return "sounddevice"
    if "arecord" in class_name:
        return "arecord"
    if "microphone" in class_name:
        return "microphone"
    return class_name or "unknown"


def _build_lightweight_dashboard_html(*, refresh_ms: int) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>机器人快反应实时面板</title>
  <style>
    :root {{
      --bg: #eef2f6;
      --card: rgba(255, 255, 255, 0.92);
      --ink: #172033;
      --muted: #637089;
      --line: #d7deea;
      --good: #178f63;
      --warn: #c97912;
      --bad: #cb4258;
      --accent: #1256d8;
      --shadow: 0 14px 34px rgba(20, 42, 90, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "SF Pro Display", "PingFang SC", "Noto Sans SC", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(18, 86, 216, 0.12), transparent 24%),
        radial-gradient(circle at top right, rgba(255, 156, 87, 0.16), transparent 28%),
        var(--bg);
    }}
    .wrap {{
      width: min(1280px, calc(100vw - 24px));
      margin: 14px auto 20px;
      display: grid;
      gap: 12px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      padding: 10px 2px 2px;
    }}
    .title {{
      margin: 0;
      font-size: clamp(24px, 3vw, 34px);
      font-weight: 760;
      letter-spacing: 0.02em;
    }}
    .subtitle {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 13px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.72);
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      white-space: nowrap;
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(340px, 0.95fr);
      gap: 12px;
    }}
    .stack {{
      display: grid;
      gap: 12px;
    }}
    .card {{
      background: var(--card);
      backdrop-filter: blur(8px);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .section-title {{
      padding: 12px 14px 0;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 700;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
      padding: 0 0 2px;
    }}
    .metric {{
      padding: 14px;
      border-right: 1px solid var(--line);
    }}
    .metric:last-child {{
      border-right: none;
    }}
    .metric-label {{
      font-size: 11px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-size: 28px;
      line-height: 1;
      font-weight: 760;
    }}
    .metric-note {{
      margin-top: 8px;
      font-size: 12px;
      color: var(--muted);
    }}
    .scene-card {{
      padding: 14px;
      display: grid;
      gap: 12px;
    }}
    .scene-main {{
      padding: 14px;
      border-radius: 16px;
      background: linear-gradient(145deg, rgba(18, 86, 216, 0.08), rgba(255, 255, 255, 0.96));
      border: 1px solid rgba(18, 86, 216, 0.12);
    }}
    .scene-k {{
      font-size: 11px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
    }}
    .scene-v {{
      font-size: 24px;
      font-weight: 760;
      line-height: 1.2;
    }}
    .scene-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .scene-box {{
      padding: 12px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.78);
      min-height: 88px;
    }}
    .camera-card {{
      padding: 14px;
      display: grid;
      gap: 12px;
    }}
    .camera-frame {{
      aspect-ratio: 16 / 9;
      border-radius: 16px;
      overflow: hidden;
      border: 1px solid var(--line);
      background: #dfe7f3;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .camera-frame img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}
    .camera-empty {{
      color: var(--muted);
      font-size: 14px;
    }}
    .status-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .mini-card {{
      padding: 12px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.78);
    }}
    .list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }}
    .pipeline-list {{
      padding: 14px;
    }}
    .pipeline-item {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.84);
    }}
    .pipeline-head {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 6px;
      font-weight: 700;
    }}
    .badge {{
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      background: #edf2fb;
      color: #44506b;
    }}
    .badge.good {{ background: #e5f6ee; color: var(--good); }}
    .badge.warn {{ background: #fff3de; color: var(--warn); }}
    .badge.bad {{ background: #ffe6ea; color: var(--bad); }}
    .meta-row {{
      font-size: 12px;
      color: var(--muted);
      line-height: 1.5;
    }}
    .stream-card {{
      padding: 14px;
      min-height: 280px;
    }}
    .stream-item {{
      padding: 10px 12px;
      border-left: 3px solid #cfd8ea;
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.76);
      font-size: 13px;
      line-height: 1.45;
    }}
    .stream-item.good {{ border-left-color: #8bd2b5; }}
    .stream-item.warn {{ border-left-color: #f0c277; }}
    .stream-item.bad {{ border-left-color: #ef9baa; }}
    .tuning-card {{
      padding: 14px;
      display: grid;
      gap: 12px;
    }}
    .tuning-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .tuning-item {{
      padding: 12px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.78);
      display: grid;
      gap: 6px;
      font-size: 13px;
      color: #31405c;
    }}
    .tuning-item input[type="range"] {{
      width: 100%;
    }}
    .tuning-meta {{
      font-size: 12px;
      color: var(--muted);
      line-height: 1.4;
    }}
    .muted {{
      color: var(--muted);
    }}
    .footer-note {{
      padding: 0 2px;
      color: var(--muted);
      font-size: 12px;
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
    }}
    @media (max-width: 1080px) {{
      .grid {{
        grid-template-columns: 1fr;
      }}
      .metrics {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .scene-grid,
      .status-grid,
      .tuning-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1 class="title">机器人快反应实时面板</h1>
        <div class="subtitle" id="meta">正在等待实时状态...</div>
      </div>
      <div class="chip" id="runtime-chip">HTTP /api/state · refresh {max(150, int(refresh_ms))}ms</div>
    </div>

    <section class="card">
      <div class="section-title">核心指标</div>
      <div class="metrics">
        <div class="metric">
          <div class="metric-label">Loop FPS</div>
          <div class="metric-value" id="loop-fps">0.0</div>
          <div class="metric-note">主循环实时帧率</div>
        </div>
        <div class="metric">
          <div class="metric-label">Latency</div>
          <div class="metric-value" id="latency-ms">0ms</div>
          <div class="metric-note">最近一次端到端延迟</div>
        </div>
        <div class="metric">
          <div class="metric-label">CPU</div>
          <div class="metric-value" id="cpu-load">0%</div>
          <div class="metric-note" id="cpu-note">系统 CPU 占用</div>
        </div>
        <div class="metric">
          <div class="metric-label">GPU</div>
          <div class="metric-value" id="gpu-load">-</div>
          <div class="metric-note" id="gpu-note">等待 GPU 数据</div>
        </div>
        <div class="metric">
          <div class="metric-label">Memory</div>
          <div class="metric-value" id="mem-load">0%</div>
          <div class="metric-note">系统内存占用</div>
        </div>
        <div class="metric">
          <div class="metric-label">Iterations</div>
          <div class="metric-value" id="iterations">0</div>
          <div class="metric-note" id="count-note">detections 0 / exec 0</div>
        </div>
      </div>
    </section>

    <div class="grid">
      <div class="stack">
        <section class="card scene-card">
          <div class="section-title">最终场景输出</div>
          <div class="scene-main">
            <div class="scene-k">机器人最终输出</div>
            <div class="scene-v" id="scene-react">等待首个稳定结果...</div>
          </div>
          <div class="scene-grid">
            <div class="scene-box">
              <div class="scene-k">检测到的事件</div>
              <div id="scene-detected">-</div>
            </div>
            <div class="scene-box">
              <div class="scene-k">仲裁决定</div>
              <div id="scene-decision">-</div>
            </div>
            <div class="scene-box">
              <div class="scene-k">执行结果</div>
              <div id="scene-executed">-</div>
            </div>
            <div class="scene-box">
              <div class="scene-k">场景通路</div>
              <div id="scene-route">-</div>
            </div>
          </div>
        </section>

        <section class="card camera-card">
          <div class="section-title">实时摄像头</div>
          <div class="camera-frame">
            <img id="camera-preview" src="/api/camera_fast.jpg" alt="camera-preview" />
            <div class="camera-empty" id="camera-empty" hidden>等待摄像头首帧...</div>
          </div>
          <div class="status-grid">
            <div class="mini-card">
              <div class="scene-k">输入源状态</div>
              <ul class="list" id="source-list">
                <li class="muted">等待来源数据...</li>
              </ul>
            </div>
            <div class="mini-card">
              <div class="scene-k">最近场景与动作</div>
              <ul class="list" id="route-list">
                <li class="muted">等待场景通路数据...</li>
              </ul>
            </div>
          </div>
        </section>
      </div>

      <div class="stack">
        <section class="card pipeline-list">
          <div class="section-title">五路感知状态</div>
          <ul class="list" id="pipeline-list">
            <li class="muted">等待管线状态...</li>
          </ul>
        </section>

        <section class="card stream-card">
          <div class="section-title">实时事件流</div>
          <ul class="list" id="event-list">
            <li class="stream-item">等待实时事件...</li>
          </ul>
        </section>
      </div>
    </div>

    <section class="card tuning-card">
      <div class="section-title">运行态热更新</div>
      <div class="tuning-grid">
        <label class="tuning-item">
          <span>手势场景优先级 <strong id="gesture-priority-slider-value">P1</strong></span>
          <input id="gesture-priority-slider" type="range" min="0" max="3" step="1" value="1" />
          <span class="tuning-meta">越小越优先。想让其它场景更容易出来，先把手势降到 P2/P3。</span>
        </label>
        <label class="tuning-item">
          <span>单信号成场阈值 <strong id="scene-score-slider-value">0.45</strong></span>
          <input id="scene-score-slider" type="range" min="0.20" max="0.95" step="0.01" value="0.45" />
          <span class="tuning-meta">越大越不容易让弱单信号直接成场。</span>
        </label>
        <label class="tuning-item">
          <span>Face 稳态阈值 <strong id="face-threshold-slider-value">0.58</strong></span>
          <input id="face-threshold-slider" type="range" min="0.35" max="0.95" step="0.01" value="0.58" />
          <span class="tuning-meta">同时作用于熟人和陌生人人脸稳态门槛。</span>
        </label>
        <label class="tuning-item">
          <span>Gesture 稳态阈值 <strong id="gesture-threshold-slider-value">0.68</strong></span>
          <input id="gesture-threshold-slider" type="range" min="0.35" max="0.98" step="0.01" value="0.68" />
          <span class="tuning-meta">越大越不容易把误检手势放进场景层。</span>
        </label>
        <label class="tuning-item">
          <span>Gesture 冷却(ms) <strong id="gesture-cooldown-slider-value">2200</strong></span>
          <input id="gesture-cooldown-slider" type="range" min="400" max="5000" step="100" value="2200" />
          <span class="tuning-meta">越大越不容易连发抢占其它场景。</span>
        </label>
        <label class="tuning-item">
          <span>Gaze 稳态阈值 <strong id="gaze-threshold-slider-value">0.60</strong></span>
          <input id="gaze-threshold-slider" type="range" min="0.35" max="0.98" step="0.01" value="0.60" />
          <span class="tuning-meta">控制注视触发的稳态门槛。</span>
        </label>
        <label class="tuning-item">
          <span>Audio 语义阈值 <strong id="audio-semantic-slider-value">0.28</strong></span>
          <input id="audio-semantic-slider" type="range" min="0.05" max="0.95" step="0.01" value="0.28" />
          <span class="tuning-meta">PANNs 语义音频置信度阈值。</span>
        </label>
        <label class="tuning-item">
          <span>Audio VAD 阈值 <strong id="audio-vad-slider-value">0.50</strong></span>
          <input id="audio-vad-slider" type="range" min="0.10" max="0.95" step="0.01" value="0.50" />
          <span class="tuning-meta">控制是否判定有人在说话。</span>
        </label>
        <label class="tuning-item">
          <span>Motion 像素阈值 <strong id="motion-pixel-slider-value">22</strong></span>
          <input id="motion-pixel-slider" type="range" min="8" max="80" step="1" value="22" />
          <span class="tuning-meta">越大越不容易把轻微抖动判成移动。</span>
        </label>
        <label class="tuning-item">
          <span>Motion 面积阈值 <strong id="motion-area-slider-value">0.03</strong></span>
          <input id="motion-area-slider" type="range" min="0.005" max="0.20" step="0.005" value="0.03" />
          <span class="tuning-meta">要求更大区域运动才触发 motion。</span>
        </label>
      </div>
      <div class="tuning-meta" id="tuning-status">等待运行态参数...</div>
    </section>

    <div class="footer-note">
      轻量 UI 默认访问 <a href="/api/state">/api/state</a>。需要完整调试快照时访问 <a href="/api/state_full">/api/state_full</a>。
    </div>
  </div>

  <script>
    const REFRESH_MS = {max(240, int(refresh_ms))};
    const CAMERA_REFRESH_MODULO = Math.max(1, Math.round(1400 / REFRESH_MS));
    let cameraTick = 0;
    let tuningRequestInFlight = false;
    let tuningDirty = false;

    const gesturePrioritySlider = document.getElementById("gesture-priority-slider");
    const sceneScoreSlider = document.getElementById("scene-score-slider");
    const faceThresholdSlider = document.getElementById("face-threshold-slider");
    const gestureThresholdSlider = document.getElementById("gesture-threshold-slider");
    const gestureCooldownSlider = document.getElementById("gesture-cooldown-slider");
    const gazeThresholdSlider = document.getElementById("gaze-threshold-slider");
    const audioSemanticSlider = document.getElementById("audio-semantic-slider");
    const audioVadSlider = document.getElementById("audio-vad-slider");
    const motionPixelSlider = document.getElementById("motion-pixel-slider");
    const motionAreaSlider = document.getElementById("motion-area-slider");
    const gesturePriorityValue = document.getElementById("gesture-priority-slider-value");
    const sceneScoreValue = document.getElementById("scene-score-slider-value");
    const faceThresholdValue = document.getElementById("face-threshold-slider-value");
    const gestureThresholdValue = document.getElementById("gesture-threshold-slider-value");
    const gestureCooldownValue = document.getElementById("gesture-cooldown-slider-value");
    const gazeThresholdValue = document.getElementById("gaze-threshold-slider-value");
    const audioSemanticValue = document.getElementById("audio-semantic-slider-value");
    const audioVadValue = document.getElementById("audio-vad-slider-value");
    const motionPixelValue = document.getElementById("motion-pixel-slider-value");
    const motionAreaValue = document.getElementById("motion-area-slider-value");
    const tuningStatus = document.getElementById("tuning-status");

    function text(id, value) {{
      const node = document.getElementById(id);
      if (node) {{
        node.textContent = value;
      }}
    }}

    function pct(value) {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) {{
        return "-";
      }}
      return `${{Number(value).toFixed(1)}}%`;
    }}

    function ms(value) {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) {{
        return "-";
      }}
      return `${{Number(value).toFixed(1)}}ms`;
    }}

    function short(value) {{
      if (value === null || value === undefined || value === "") {{
        return "-";
      }}
      return String(value);
    }}

    function syncSliderLabels() {{
      if (gesturePriorityValue) gesturePriorityValue.textContent = `P${{Math.round(Number(gesturePrioritySlider?.value || 0))}}`;
      if (sceneScoreValue) sceneScoreValue.textContent = Number(sceneScoreSlider?.value || 0).toFixed(2);
      if (faceThresholdValue) faceThresholdValue.textContent = Number(faceThresholdSlider?.value || 0).toFixed(2);
      if (gestureThresholdValue) gestureThresholdValue.textContent = Number(gestureThresholdSlider?.value || 0).toFixed(2);
      if (gestureCooldownValue) gestureCooldownValue.textContent = String(Math.round(Number(gestureCooldownSlider?.value || 0)));
      if (gazeThresholdValue) gazeThresholdValue.textContent = Number(gazeThresholdSlider?.value || 0).toFixed(2);
      if (audioSemanticValue) audioSemanticValue.textContent = Number(audioSemanticSlider?.value || 0).toFixed(2);
      if (audioVadValue) audioVadValue.textContent = Number(audioVadSlider?.value || 0).toFixed(2);
      if (motionPixelValue) motionPixelValue.textContent = String(Math.round(Number(motionPixelSlider?.value || 0)));
      if (motionAreaValue) motionAreaValue.textContent = Number(motionAreaSlider?.value || 0).toFixed(3);
    }}

    async function pushTuningUpdate() {{
      if (tuningRequestInFlight || !tuningDirty) return;
      tuningRequestInFlight = true;
      tuningDirty = false;
      const payload = {{
        gesture_scene_priority: Number(gesturePrioritySlider?.value || 1),
        scene_min_single_signal_score: Number(sceneScoreSlider?.value || 0.45),
        face_hysteresis_threshold: Number(faceThresholdSlider?.value || 0.58),
        gesture_hysteresis_threshold: Number(gestureThresholdSlider?.value || 0.68),
        gesture_cooldown_ms: Number(gestureCooldownSlider?.value || 2200),
        gaze_hysteresis_threshold: Number(gazeThresholdSlider?.value || 0.60),
        audio_panns_threshold: Number(audioSemanticSlider?.value || 0.28),
        audio_vad_threshold: Number(audioVadSlider?.value || 0.50),
        motion_pixel_threshold: Number(motionPixelSlider?.value || 22),
        motion_min_area_ratio: Number(motionAreaSlider?.value || 0.03),
      }};
      try {{
        const resp = await fetch("/api/tuning", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        if (resp.ok) {{
          if (tuningStatus) tuningStatus.textContent = `最近应用：${{new Date().toLocaleTimeString()}}`;
        }} else {{
          if (tuningStatus) tuningStatus.textContent = `调参失败：HTTP ${{resp.status}}`;
        }}
      }} catch (_err) {{
        if (tuningStatus) tuningStatus.textContent = "调参失败：网络异常";
      }} finally {{
        tuningRequestInFlight = false;
        if (tuningDirty) {{
          setTimeout(pushTuningUpdate, 15);
        }}
      }}
    }}

    function scheduleTuningUpdate() {{
      tuningDirty = true;
      syncSliderLabels();
      if (tuningStatus) tuningStatus.textContent = "正在应用调参...";
      setTimeout(pushTuningUpdate, 80);
    }}

    function badgeClass(status) {{
      const normalized = String(status || "").toLowerCase();
      if (["ready", "running", "真实", "ok"].includes(normalized)) {{
        return "good";
      }}
      if (["failed", "error", "bad"].includes(normalized)) {{
        return "bad";
      }}
      return "warn";
    }}

    function renderPipelines(items) {{
      const root = document.getElementById("pipeline-list");
      if (!items || !items.length) {{
        root.innerHTML = '<li class="muted">等待管线状态...</li>';
        return;
      }}
      root.innerHTML = items.map((item) => {{
        const statusClass = badgeClass(item.status);
        const computeClass = String(item.compute_target || "").toLowerCase().includes("gpu") ? "good" : "warn";
        return `
          <li class="pipeline-item">
            <div>
              <div class="pipeline-head">
                <span>${{short(item.name)}}</span>
                <span class="badge ${{statusClass}}">${{short(item.status_label)}}</span>
                <span class="badge ${{computeClass}}">${{short(item.compute_target_label)}}</span>
              </div>
              <div class="meta-row">budget=${{short(item.runtime_budget_ms)}}ms · last=${{short(item.last_duration_ms)}}ms · hz=${{short(item.sample_rate_hz)}}</div>
              <div class="meta-row">${{short(item.reason)}}</div>
            </div>
            <div class="meta-row">skips=${{short(item.budget_skips)}}</div>
          </li>
        `;
      }}).join("");
    }}

    function renderSources(items) {{
      const root = document.getElementById("source-list");
      if (!items || !items.length) {{
        root.innerHTML = '<li class="muted">等待来源数据...</li>';
        return;
      }}
      root.innerHTML = items.map((item) => {{
        const statusText = item.last_read_ok ? "正常" : "等待中";
        const audioBits = [];
        if (item.last_audio_db !== null && item.last_audio_db !== undefined) {{
          audioBits.push(`db=${{item.last_audio_db}}`);
        }}
        if (item.last_audio_rms !== null && item.last_audio_rms !== undefined) {{
          audioBits.push(`rms=${{item.last_audio_rms}}`);
        }}
        const extra = audioBits.length ? ` · ${{audioBits.join(" ")}}` : "";
        return `<li class="stream-item">
          <strong>${{short(item.name)}}</strong>
          <span class="muted"> · ${{short(item.mode_label)}} · ${{statusText}}</span><br/>
          backend=${{short(item.backend)}} · device=${{short(item.device)}} · age=${{ms(item.last_packet_age_ms)}}${{extra}}
        </li>`;
      }}).join("");
    }}

    function renderRoutes(items) {{
      const root = document.getElementById("route-list");
      if (!items || !items.length) {{
        root.innerHTML = '<li class="muted">等待场景通路数据...</li>';
        return;
      }}
      root.innerHTML = items.map((item) => `
        <li class="stream-item">
          <strong>${{short(item.path)}}</strong>
          <span class="muted"> · ${{short(item.status)}}</span><br/>
          latest=${{short(item.latest_scene)}} · count=${{short(item.count)}}
        </li>
      `).join("");
    }}

    function renderEvents(state) {{
      const root = document.getElementById("event-list");
      const events = [];
      (state.feed || []).forEach((item) => {{
        events.push({{
          time: item.time,
          text: item.text,
          level: item.level || "warn",
        }});
      }});
      (state.latest_detections || []).slice(0, 3).forEach((item) => {{
        events.push({{
          time: item.time,
          text: `检测: ${{short(item.event_type)}}`,
          level: "warn",
        }});
      }});
      if (!events.length) {{
        root.innerHTML = '<li class="stream-item">等待实时事件...</li>';
        return;
      }}
      root.innerHTML = events.slice(0, 10).map((item) => `
        <li class="stream-item ${{badgeClass(item.level)}}">
          <strong>${{short(item.time)}}</strong> ${{short(item.text)}}
        </li>
      `).join("");
    }}

    function updateCamera(hasFrame) {{
      const img = document.getElementById("camera-preview");
      const empty = document.getElementById("camera-empty");
      if (!hasFrame) {{
        img.hidden = true;
        empty.hidden = false;
        return;
      }}
      img.hidden = false;
      empty.hidden = true;
      if ((cameraTick % CAMERA_REFRESH_MODULO) === 0) {{
        img.src = `/api/camera_fast.jpg?ts=${{Date.now()}}`;
      }}
      cameraTick += 1;
    }}

    async function refresh() {{
      try {{
        const res = await fetch("/api/state", {{ cache: "no-store" }});
        if (!res.ok) {{
          throw new Error(`HTTP ${{res.status}}`);
        }}
        const state = await res.json();
        const reaction = state.latest_reaction || {{}};
        const gpuLoad = state.gpu_percent ?? state.gpu_estimated_percent;

        text("meta", `mode=${{short(state.mode)}} · profile=${{short(state.current_profile)}} · stabilizer=${{short(state.current_stabilizer)}}`);
        text("runtime-chip", `HTTP /api/state · refresh ${{REFRESH_MS}}ms · camera=${{state.has_camera_frame ? "live" : "warming"}}`);
        text("loop-fps", Number(state.loop_fps || 0).toFixed(1));
        text("latency-ms", ms(state.last_latency_ms));
        text("cpu-load", pct(state.cpu_percent));
        text("gpu-load", pct(gpuLoad));
        text("mem-load", pct(state.mem_percent));
        text("iterations", short(state.iterations));
        text("cpu-note", `mic=${{short(state.microphone_packets)}} · cam=${{short(state.camera_packets)}}`);
        text("gpu-note", `backend=${{short(state.gpu_backend)}} · ratio=${{pct(state.gpu_pipeline_ratio)}}`);
        text("count-note", `detections ${{short(state.total_detections)}} / exec ${{short(state.total_executions)}}`);

        const gestureScenePriority = Number(state.gesture_scene_priority ?? 1);
        const sceneMinSingleSignalScore = Number(state.scene_min_single_signal_score ?? 0.45);
        const faceThreshold = Number(state.face_hysteresis_threshold ?? 0.58);
        const gestureThreshold = Number(state.gesture_hysteresis_threshold ?? 0.68);
        const gestureCooldownMs = Number(state.gesture_cooldown_ms ?? 2200);
        const gazeThreshold = Number(state.gaze_hysteresis_threshold ?? 0.60);
        const audioSemanticThreshold = Number(state.audio_panns_threshold ?? 0.28);
        const audioVadThreshold = Number(state.audio_vad_threshold ?? 0.50);
        const motionPixelThreshold = Number(state.motion_pixel_threshold ?? 22);
        const motionMinAreaRatio = Number(state.motion_min_area_ratio ?? 0.03);
        if (!tuningDirty && !tuningRequestInFlight) {{
          if (gesturePrioritySlider) gesturePrioritySlider.value = String(Math.round(gestureScenePriority));
          if (sceneScoreSlider) sceneScoreSlider.value = String(sceneMinSingleSignalScore);
          if (faceThresholdSlider) faceThresholdSlider.value = String(faceThreshold);
          if (gestureThresholdSlider) gestureThresholdSlider.value = String(gestureThreshold);
          if (gestureCooldownSlider) gestureCooldownSlider.value = String(Math.round(gestureCooldownMs));
          if (gazeThresholdSlider) gazeThresholdSlider.value = String(gazeThreshold);
          if (audioSemanticSlider) audioSemanticSlider.value = String(audioSemanticThreshold);
          if (audioVadSlider) audioVadSlider.value = String(audioVadThreshold);
          if (motionPixelSlider) motionPixelSlider.value = String(Math.round(motionPixelThreshold));
          if (motionAreaSlider) motionAreaSlider.value = String(motionMinAreaRatio);
          syncSliderLabels();
        }}

        text("scene-react", reaction.robot_response || reaction.react || "等待首个稳定结果...");
        text("scene-detected", reaction.detected_event || reaction.saw || "-");
        text("scene-decision", reaction.arbitration_logic || reaction.decision || "-");
        text("scene-executed", reaction.executed_event || "-");
        text("scene-route", reaction.route_summary || "-");

        renderSources(state.sources || state.source_health || []);
        renderRoutes(state.scene_routes || []);
        renderPipelines(state.pipelines || state.pipeline_statuses || []);
        renderEvents(state);
        updateCamera(Boolean(state.has_camera_frame));
      }} catch (err) {{
        text("meta", `状态读取失败：${{err}}`);
      }} finally {{
        setTimeout(refresh, REFRESH_MS);
      }}
    }}

    [
      gesturePrioritySlider,
      sceneScoreSlider,
      faceThresholdSlider,
      gestureThresholdSlider,
      gestureCooldownSlider,
      gazeThresholdSlider,
      audioSemanticSlider,
      audioVadSlider,
      motionPixelSlider,
      motionAreaSlider,
    ].forEach((slider) => {{
      if (!slider) return;
      slider.addEventListener("input", scheduleTuningUpdate);
      slider.addEventListener("change", scheduleTuningUpdate);
    }});

    syncSliderLabels();
    refresh();
  </script>
</body>
</html>
"""


def build_dashboard_html(*, refresh_ms: int) -> str:
    return _build_lightweight_dashboard_html(refresh_ms=refresh_ms)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>机器人交互MVP 控制台</title>
  <style>
    :root {{
      --bg-a: #f6f8ff;
      --bg-b: #fff6ea;
      --card: #ffffff;
      --ink: #1f2a44;
      --muted: #5b6780;
      --line: #d6deef;
      --accent: #ff7a45;
      --accent-2: #2e8bff;
      --good: #1ea672;
      --warn: #d17c00;
      --bad: #d13f56;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 15% 10%, #ffe5d2 0%, transparent 36%),
        radial-gradient(circle at 85% 5%, #d8ebff 0%, transparent 42%),
        linear-gradient(160deg, var(--bg-a), var(--bg-b));
      min-height: 100vh;
    }}
    .wrap {{
      width: min(1200px, calc(100vw - 24px));
      margin: 18px auto 28px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .title {{
      margin: 0;
      letter-spacing: 0.3px;
      font-size: clamp(22px, 2.2vw, 34px);
      font-weight: 750;
    }}
    .subtitle {{
      color: var(--muted);
      font-size: 13px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 12px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: 0 8px 28px rgba(37, 59, 102, 0.07);
      overflow: hidden;
    }}
    .card h3 {{
      margin: 0;
      padding: 11px 14px;
      font-size: 14px;
      font-weight: 700;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(90deg, #fff, #fbfdff);
    }}
    .stat-grid {{
      grid-column: span 12;
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(10, minmax(0, 1fr));
    }}
    .stat {{
      padding: 12px 14px;
      min-height: 82px;
    }}
    .k {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }}
    .v {{
      font-size: 26px;
      font-weight: 760;
      line-height: 1;
    }}
    .latency {{ color: var(--accent-2); }}
    .ok {{ color: var(--good); }}
    .panel {{
      grid-column: span 6;
      min-height: 260px;
    }}
    .load-panel {{
      grid-column: span 12;
      padding: 12px 14px 14px;
      display: grid;
      gap: 12px;
    }}
    .load-row {{
      display: grid;
      gap: 6px;
    }}
    .load-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 13px;
      color: #33456d;
      font-weight: 650;
    }}
    .load-text {{
      font-size: 12px;
      color: #5b6780;
      font-weight: 600;
    }}
    .bar-track {{
      width: 100%;
      height: 10px;
      border-radius: 999px;
      background: #e9eefb;
      overflow: hidden;
      border: 1px solid #d7def0;
    }}
    .bar-fill {{
      height: 100%;
      width: 0%;
      transition: width 180ms ease;
    }}
    .bar-fast {{
      background: linear-gradient(90deg, #2e8bff, #67b4ff);
    }}
    .bar-slow {{
      background: linear-gradient(90deg, #ff7a45, #ffb07c);
    }}
    .load-meta {{
      font-size: 12px;
      color: #5b6780;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .camera-panel {{
      grid-column: span 12;
      display: grid;
      grid-template-columns: 1.35fr 1fr;
      gap: 10px;
      padding: 10px;
      min-height: 320px;
    }}
    .camera-grid {{
      display: grid;
      grid-template-rows: 1fr 1fr;
      gap: 10px;
    }}
    .camera-box {{
      border: 1px dashed #d7def0;
      border-radius: 12px;
      overflow: hidden;
      background: #f9fbff;
      min-height: 145px;
      display: grid;
      grid-template-rows: auto 1fr;
    }}
    .camera-head {{
      padding: 8px 10px;
      font-size: 12px;
      color: #36517f;
      background: linear-gradient(180deg, #ffffff, #f4f8ff);
      border-bottom: 1px solid #e2e9f8;
      font-weight: 650;
    }}
    .camera-view-wrap {{
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 110px;
    }}
    .camera-box img {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .reaction-box {{
      border: 1px solid #e3e9f8;
      border-radius: 12px;
      padding: 12px;
      background: linear-gradient(180deg, #ffffff, #fbfdff);
      font-size: 13px;
      line-height: 1.45;
    }}
    .table-wrap {{
      max-height: 230px;
      overflow: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    th, td {{
      text-align: left;
      padding: 7px 10px;
      border-bottom: 1px dashed #e4e9f5;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 650;
      position: sticky;
      top: 0;
      background: #fff;
    }}
    .chart {{
      grid-column: span 12;
      padding: 10px 14px 14px;
    }}
    .canvas-box {{
      position: relative;
      height: 160px;
      border: 1px dashed #d7def0;
      border-radius: 12px;
      background: linear-gradient(180deg, #ffffff, #fafcff);
    }}
    #latency-canvas {{
      width: 100%;
      height: 100%;
      display: block;
    }}
    .feed {{
      grid-column: span 12;
      min-height: 160px;
    }}
    .feed-list {{
      list-style: none;
      margin: 0;
      padding: 10px 14px 14px;
      display: grid;
      gap: 6px;
      font-size: 13px;
      color: #33456d;
    }}
    .feed-item {{
      border-left: 3px solid #c5d2ee;
      padding-left: 9px;
      line-height: 1.35;
    }}
    .feed-item.ok {{ border-color: #8fd4bb; }}
    .feed-item.warn {{ border-color: #f6d28f; }}
    .feed-item.bad {{ border-color: #f3a0ad; }}
    .muted {{ color: var(--muted); }}
    .tuning-panel {{
      grid-column: span 12;
      padding: 12px 14px 14px;
      display: grid;
      gap: 10px;
    }}
    .tuning-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .tuning-item {{
      display: grid;
      gap: 6px;
      font-size: 13px;
      color: #3a4a6c;
    }}
    .tuning-item input[type="range"] {{
      width: 100%;
    }}
    .tuning-meta {{
      font-size: 12px;
      color: var(--muted);
    }}
    .slow-only {{ display: none !important; }}
    @media (max-width: 980px) {{
      .stat-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .panel {{ grid-column: span 12; }}
      .camera-panel {{ grid-template-columns: 1fr; }}
      .tuning-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1 class="title">机器人快反应可观测控制台</h1>
      <div class="subtitle" id="meta">正在启动...</div>
    </div>

    <div class="grid">
      <div class="stat-grid">
        <div class="card stat"><div class="k">循环次数</div><div class="v" id="iterations">0</div></div>
        <div class="card stat"><div class="k">主循环 FPS</div><div class="v ok" id="loop-fps">0.00</div></div>
        <div class="card stat"><div class="k">最近时延</div><div class="v latency" id="latency-last">0.00ms</div></div>
        <div class="card stat"><div class="k">感知总数</div><div class="v" id="detections-total">0</div></div>
        <div class="card stat"><div class="k">稳定事件</div><div class="v" id="stable-total">0</div></div>
        <div class="card stat"><div class="k">动作执行</div><div class="v" id="exec-total">0</div></div>
        <div class="card stat"><div class="k">仲裁排队</div><div class="v" id="queue-pending">0</div></div>
        <div class="card stat"><div class="k">抢占次数</div><div class="v" id="preemptions">0</div></div>
        <div class="card stat"><div class="k">GPU 利用率</div><div class="v" id="gpu-load">0%</div></div>
        <div class="card stat"><div class="k">稳定通过率</div><div class="v" id="stabilizer-pass-rate">0%</div></div>
        <div class="card stat"><div class="k">系统 CPU</div><div class="v" id="cpu-load">0%</div></div>
        <div class="card stat"><div class="k">系统内存</div><div class="v" id="mem-load">0%</div></div>
      </div>

      <section class="card load-panel">
        <h3>资源与快反应模型状态</h3>
        <div class="load-row">
          <div class="load-head">
            <span>系统 CPU</span>
            <span class="load-text" id="cpu-load-text">0%</span>
          </div>
          <div class="bar-track"><div id="cpu-load-bar" class="bar-fill bar-fast"></div></div>
          <div class="load-meta" id="cpu-load-meta">系统 CPU 利用率</div>
        </div>
        <div class="load-row">
          <div class="load-head">
            <span>系统内存</span>
            <span class="load-text" id="mem-load-text">0%</span>
          </div>
          <div class="bar-track"><div id="mem-load-bar" class="bar-fill bar-fast"></div></div>
          <div class="load-meta" id="mem-load-meta">系统内存占用率</div>
        </div>
        <div class="load-row">
          <div class="load-head">
            <span>GPU</span>
            <span class="load-text" id="gpu-load-text">N/A</span>
          </div>
          <div class="bar-track"><div id="gpu-load-bar" class="bar-fill bar-slow"></div></div>
          <div class="load-meta" id="gpu-load-meta">等待 GPU 监控数据...</div>
        </div>
        <div class="load-row">
          <div class="load-head">
            <span>快反应模型加载</span>
            <span class="load-text" id="fast-load-text">0% (0/0) -</span>
          </div>
          <div class="bar-track"><div id="fast-load-bar" class="bar-fill bar-fast"></div></div>
          <div class="load-meta" id="fast-load-meta">等待运行时状态...</div>
        </div>
        <div class="load-row slow-only">
          <div class="load-head">
            <span>慢反应模型加载</span>
            <span class="load-text" id="slow-load-text">0% -</span>
          </div>
          <div class="bar-track"><div id="slow-load-bar" class="bar-fill bar-slow"></div></div>
          <div class="load-meta" id="slow-load-meta">等待运行时状态...</div>
        </div>
      </section>

      <section class="card tuning-panel">
        <h3>实时调参（运行态热更新）</h3>
        <div class="tuning-grid">
          <label class="tuning-item">
            <span>手势场景优先级<strong id="gesture-priority-slider-value">1</strong></span>
            <input id="gesture-priority-slider" type="range" min="0" max="3" step="1" value="1" />
            <span class="tuning-meta">数值越小优先级越高。建议先把手势降到 P2 再找体验。</span>
          </label>
          <label class="tuning-item">
            <span>单信号成场阈值<strong id="scene-score-slider-value">0.45</strong></span>
            <input id="scene-score-slider" type="range" min="0.20" max="0.95" step="0.01" value="0.45" />
            <span class="tuning-meta">越大越不容易让孤立弱信号直接形成场景。</span>
          </label>
          <label class="tuning-item">
            <span>Face 稳态阈值<strong id="face-threshold-slider-value">0.58</strong></span>
            <input id="face-threshold-slider" type="range" min="0.35" max="0.95" step="0.01" value="0.58" />
            <span class="tuning-meta">同时作用于熟人/陌生人人脸稳态门槛。</span>
          </label>
          <label class="tuning-item">
            <span>Gesture 稳态阈值<strong id="gesture-threshold-slider-value">0.68</strong></span>
            <input id="gesture-threshold-slider" type="range" min="0.35" max="0.98" step="0.01" value="0.68" />
            <span class="tuning-meta">越大越不容易把误检手势放进场景层。</span>
          </label>
          <label class="tuning-item">
            <span>Gesture 冷却（ms）<strong id="gesture-cooldown-slider-value">2200</strong></span>
            <input id="gesture-cooldown-slider" type="range" min="400" max="5000" step="100" value="2200" />
            <span class="tuning-meta">越大越不容易连发，把其它场景挤掉。</span>
          </label>
          <label class="tuning-item">
            <span>Gaze 稳态阈值<strong id="gaze-threshold-slider-value">0.60</strong></span>
            <input id="gaze-threshold-slider" type="range" min="0.35" max="0.98" step="0.01" value="0.60" />
            <span class="tuning-meta">控制注视触发的稳态门槛。</span>
          </label>
          <label class="tuning-item">
            <span>Audio 语义阈值<strong id="audio-semantic-slider-value">0.28</strong></span>
            <input id="audio-semantic-slider" type="range" min="0.05" max="0.95" step="0.01" value="0.28" />
            <span class="tuning-meta">PANNs 语义音频置信度阈值。</span>
          </label>
          <label class="tuning-item">
            <span>Audio VAD 阈值<strong id="audio-vad-slider-value">0.50</strong></span>
            <input id="audio-vad-slider" type="range" min="0.10" max="0.95" step="0.01" value="0.50" />
            <span class="tuning-meta">控制是否认为有人在说话。</span>
          </label>
          <label class="tuning-item">
            <span>Motion 像素阈值<strong id="motion-pixel-slider-value">22</strong></span>
            <input id="motion-pixel-slider" type="range" min="8" max="80" step="1" value="22" />
            <span class="tuning-meta">越大越不容易把微小抖动判成移动。</span>
          </label>
          <label class="tuning-item">
            <span>Motion 面积阈值<strong id="motion-area-slider-value">0.03</strong></span>
            <input id="motion-area-slider" type="range" min="0.005" max="0.20" step="0.005" value="0.03" />
            <span class="tuning-meta">要求更大的移动区域才触发 motion。</span>
          </label>
        </div>
        <div class="tuning-meta" id="tuning-status">等待运行时状态...</div>
      </section>

      <section class="card camera-panel">
        <div class="camera-grid">
          <div class="camera-box">
            <div class="camera-head">快反应视频（实时，含行为标记）</div>
            <div class="camera-view-wrap"><img id="camera-fast-view" alt="fast camera stream" /></div>
          </div>
          <div class="camera-box slow-only">
            <div class="camera-head">慢反应视频（1Hz 抽帧，无标记）</div>
            <div class="camera-view-wrap"><img id="camera-slow-view" alt="slow camera stream" /></div>
          </div>
        </div>
        <div class="reaction-box">
          <h3>自然语言结果面板</h3>
          <div><strong>当前检测事件：</strong> <span id="what-saw">等待输入...</span></div>
          <div><strong>当前仲裁逻辑：</strong> <span id="what-decision">-</span></div>
          <div><strong>最终执行事件：</strong> <span id="what-executed">-</span></div>
          <div><strong>机器人回应：</strong> <span id="what-react">等待输入...</span></div>
          <div><strong>当前场景：</strong> <span id="what-scene">-</span></div>
          <div><strong>动作：</strong> <span id="what-action">-</span></div>
          <div><strong>表情：</strong> <span id="what-expression">-</span></div>
          <div><strong>TTS：</strong> <span id="what-tts">-</span></div>
          <div class="slow-only"><strong>慢思考结论：</strong> <span id="what-slow">-</span></div>
        </div>
      </section>

      <section class="card chart">
        <h3>实时时延曲线</h3>
        <div class="canvas-box"><canvas id="latency-canvas"></canvas></div>
      </section>

      <section class="card panel">
        <h3>最新感知</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>识别内容</th><th>检测器</th><th>置信度</th></tr></thead>
            <tbody id="detections-body"><tr><td colspan="4" class="muted">暂无数据</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="card panel">
        <h3>场景与动作</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>场景/动作</th><th>优先级</th><th>模式/状态</th></tr></thead>
            <tbody id="behavior-body"><tr><td colspan="4" class="muted">暂无数据</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="card panel">
        <h3>双通路监测</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>通路</th><th>最近场景</th><th>数量</th><th>状态</th></tr></thead>
            <tbody id="scene-route-body"><tr><td colspan="4" class="muted">暂无数据</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="card panel">
        <h3>5路感知监测</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>模块</th><th>计算位置</th><th>检测/稳定</th><th>场景/决策/执行</th><th>最近事件</th></tr></thead>
            <tbody id="pipeline-monitor-body"><tr><td colspan="5" class="muted">暂无数据</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="card panel">
        <h3>事件跳转链路</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>Trace</th><th>模块</th><th>检测→稳态→场景</th><th>决策→执行</th></tr></thead>
            <tbody id="transition-body"><tr><td colspan="5" class="muted">暂无数据</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="card panel">
        <h3>稳态 / 队列 / 管线</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>模块</th><th>输入</th><th>输出</th><th>过滤/细节</th></tr></thead>
            <tbody id="observability-body"><tr><td colspan="4" class="muted">暂无数据</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="card panel">
        <h3>来源与执行资源</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>资源/项目</th><th>状态</th><th>占用者/指标</th><th>细节</th></tr></thead>
            <tbody id="resources-body"><tr><td colspan="4" class="muted">暂无数据</td></tr></tbody>
          </table>
        </div>
      </section>

      <section class="card feed">
        <h3>事件流</h3>
        <ul class="feed-list" id="feed"><li class="feed-item">等待运行时数据...</li></ul>
      </section>
    </div>
  </div>
  <script>
    const REFRESH_MS = {refresh_ms};
    const canvas = document.getElementById("latency-canvas");
    const ctx = canvas.getContext("2d");
    let tuningRequestInFlight = false;
    let tuningDirty = false;

    const gesturePrioritySlider = document.getElementById("gesture-priority-slider");
    const sceneScoreSlider = document.getElementById("scene-score-slider");
    const faceThresholdSlider = document.getElementById("face-threshold-slider");
    const gestureThresholdSlider = document.getElementById("gesture-threshold-slider");
    const gestureCooldownSlider = document.getElementById("gesture-cooldown-slider");
    const gazeThresholdSlider = document.getElementById("gaze-threshold-slider");
    const audioSemanticSlider = document.getElementById("audio-semantic-slider");
    const audioVadSlider = document.getElementById("audio-vad-slider");
    const motionPixelSlider = document.getElementById("motion-pixel-slider");
    const motionAreaSlider = document.getElementById("motion-area-slider");
    const gesturePriorityValue = document.getElementById("gesture-priority-slider-value");
    const sceneScoreValue = document.getElementById("scene-score-slider-value");
    const faceThresholdValue = document.getElementById("face-threshold-slider-value");
    const gestureThresholdValue = document.getElementById("gesture-threshold-slider-value");
    const gestureCooldownValue = document.getElementById("gesture-cooldown-slider-value");
    const gazeThresholdValue = document.getElementById("gaze-threshold-slider-value");
    const audioSemanticValue = document.getElementById("audio-semantic-slider-value");
    const audioVadValue = document.getElementById("audio-vad-slider-value");
    const motionPixelValue = document.getElementById("motion-pixel-slider-value");
    const motionAreaValue = document.getElementById("motion-area-slider-value");
    const tuningStatus = document.getElementById("tuning-status");

    function syncSliderLabels() {{
      if (gesturePriorityValue) gesturePriorityValue.textContent = `P${{Math.round(Number(gesturePrioritySlider?.value || 0))}}`;
      if (sceneScoreValue) sceneScoreValue.textContent = Number(sceneScoreSlider?.value || 0).toFixed(2);
      if (faceThresholdValue) faceThresholdValue.textContent = Number(faceThresholdSlider?.value || 0).toFixed(2);
      if (gestureThresholdValue) gestureThresholdValue.textContent = Number(gestureThresholdSlider?.value || 0).toFixed(2);
      if (gestureCooldownValue) gestureCooldownValue.textContent = String(Math.round(Number(gestureCooldownSlider?.value || 0)));
      if (gazeThresholdValue) gazeThresholdValue.textContent = Number(gazeThresholdSlider?.value || 0).toFixed(2);
      if (audioSemanticValue) audioSemanticValue.textContent = Number(audioSemanticSlider?.value || 0).toFixed(2);
      if (audioVadValue) audioVadValue.textContent = Number(audioVadSlider?.value || 0).toFixed(2);
      if (motionPixelValue) motionPixelValue.textContent = String(Math.round(Number(motionPixelSlider?.value || 0)));
      if (motionAreaValue) motionAreaValue.textContent = Number(motionAreaSlider?.value || 0).toFixed(3);
    }}

    async function pushTuningUpdate() {{
      if (tuningRequestInFlight || !tuningDirty) return;
      tuningRequestInFlight = true;
      tuningDirty = false;
      const payload = {{
        gesture_scene_priority: Number(gesturePrioritySlider?.value || 1),
        scene_min_single_signal_score: Number(sceneScoreSlider?.value || 0.45),
        face_hysteresis_threshold: Number(faceThresholdSlider?.value || 0.58),
        gesture_hysteresis_threshold: Number(gestureThresholdSlider?.value || 0.68),
        gesture_cooldown_ms: Number(gestureCooldownSlider?.value || 2200),
        gaze_hysteresis_threshold: Number(gazeThresholdSlider?.value || 0.60),
        audio_panns_threshold: Number(audioSemanticSlider?.value || 0.28),
        audio_vad_threshold: Number(audioVadSlider?.value || 0.50),
        motion_pixel_threshold: Number(motionPixelSlider?.value || 22),
        motion_min_area_ratio: Number(motionAreaSlider?.value || 0.03),
      }};
      try {{
        const resp = await fetch("/api/tuning", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        if (resp.ok) {{
          if (tuningStatus) tuningStatus.textContent = `最近应用：${{new Date().toLocaleTimeString()}}`;
        }} else {{
          if (tuningStatus) tuningStatus.textContent = `调参失败：HTTP ${{resp.status}}`;
        }}
      }} catch (_err) {{
        if (tuningStatus) tuningStatus.textContent = "调参失败：网络异常";
      }} finally {{
        tuningRequestInFlight = false;
        if (tuningDirty) {{
          setTimeout(pushTuningUpdate, 10);
        }}
      }}
    }}

    function scheduleTuningUpdate() {{
      tuningDirty = true;
      syncSliderLabels();
      if (tuningStatus) tuningStatus.textContent = "正在应用调参...";
      setTimeout(pushTuningUpdate, 60);
    }}

    function fitCanvas() {{
      const ratio = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    }}

    function renderTableRows(targetId, rows, cols) {{
      const body = document.getElementById(targetId);
      if (!rows || rows.length === 0) {{
        body.innerHTML = `<tr><td colspan="${{cols}}" class="muted">暂无数据</td></tr>`;
        return;
      }}
      body.innerHTML = rows.map((row) => "<tr>" + row.map((v) => `<td>${{v}}</td>`).join("") + "</tr>").join("");
    }}

    function renderFeed(feed) {{
      const el = document.getElementById("feed");
      if (!feed || feed.length === 0) {{
        el.innerHTML = '<li class="feed-item">暂无事件流。</li>';
        return;
      }}
      el.innerHTML = feed.map((item) => {{
        const level = item.level || "ok";
        return `<li class="feed-item ${{level}}">${{item.time}} - ${{item.text}}</li>`;
      }}).join("");
    }}

    function renderLatency(history) {{
      fitCanvas();
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);
      ctx.strokeStyle = "#dde6fa";
      ctx.lineWidth = 1;
      for (let i = 1; i <= 4; i++) {{
        const y = (h / 5) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }}
      if (!history || history.length === 0) {{
        return;
      }}
      const maxVal = Math.max(50, ...history.map((x) => x.latency_ms));
      ctx.strokeStyle = "#2e8bff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      history.forEach((point, idx) => {{
        const x = (idx / Math.max(1, history.length - 1)) * w;
        const y = h - (point.latency_ms / maxVal) * (h - 12) - 6;
        if (idx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }});
      ctx.stroke();
    }}

    function renderLoadBar(payload, options) {{
      const progress = Math.max(0, Math.min(100, Number(payload?.progress_percent ?? 0)));
      const barEl = document.getElementById(options.barId);
      const textEl = document.getElementById(options.textId);
      const metaEl = document.getElementById(options.metaId);
      if (barEl) barEl.style.width = `${{progress}}%`;
      if (textEl) {{
        if (options.kind === "fast") {{
          const loaded = Number(payload?.loaded ?? 0);
          const expected = Number(payload?.expected ?? 0);
          textEl.textContent = `${{progress.toFixed(0)}}% (${{loaded}}/${{expected}}) ${{payload?.status || "-"}}`;
        }} else {{
          textEl.textContent = `${{progress.toFixed(0)}}% ${{payload?.status || "-"}}`;
        }}
      }}
      if (metaEl) {{
        if (options.kind === "fast") {{
          const rows = Array.isArray(payload?.pipelines) ? payload.pipelines : [];
          if (!rows.length) {{
            metaEl.textContent = "快反应管线状态暂不可用";
          }} else {{
            metaEl.textContent = rows.map((item) => {{
              if (!item.enabled) return `${{item.name}}:disabled`;
              const base = `${{item.name}}:${{item.status || "loading"}}/${{item.compute_target_label || item.compute_target || "-"}}`;
              if (item.reason) return `${{base}}(${{item.reason}})`;
              return base;
            }}).join(" | ");
          }}
        }} else {{
          const loaded = payload?.adapter_loaded ? "yes" : "no";
          const worker = payload?.worker_alive ? "yes" : "no";
          const queue = Number(payload?.queue_depth ?? 0);
          const timeout = Number(payload?.timed_out_requests ?? 0);
          metaEl.textContent = `adapter_loaded=${{loaded}} | worker_alive=${{worker}} | queue=${{queue}} | timeout=${{timeout}}`;
        }}
      }}
    }}

    async function refresh() {{
      try {{
        const res = await fetch("/api/state", {{ cache: "no-store" }});
        if (!res.ok) return;
        const state = await res.json();
        document.getElementById("iterations").textContent = state.iterations;
        document.getElementById("loop-fps").textContent = state.loop_fps.toFixed(2);
        document.getElementById("latency-last").textContent = `${{state.last_latency_ms.toFixed(2)}}ms`;
        document.getElementById("detections-total").textContent = state.total_detections;
        document.getElementById("stable-total").textContent = state.total_stable_events;
        document.getElementById("exec-total").textContent = state.total_executions;
        document.getElementById("queue-pending").textContent = state.queue_pending || 0;
        document.getElementById("preemptions").textContent = state.preemptions || 0;
        document.getElementById("stabilizer-pass-rate").textContent = `${{(state.stabilizer_pass_rate || 0).toFixed(1)}}%`;
        document.getElementById("cpu-load").textContent = `${{(state.cpu_percent || 0).toFixed(1)}}%`;
        document.getElementById("mem-load").textContent = `${{(state.mem_percent || 0).toFixed(1)}}%`;
        const gpuPercent = state.gpu_percent;
        const gpuEstimatedPercent = state.gpu_estimated_percent;
        const gpuRatio = Number(state.gpu_pipeline_ratio || 0);
        document.getElementById("gpu-load").textContent =
          (gpuPercent === null || gpuPercent === undefined)
            ? ((gpuEstimatedPercent === null || gpuEstimatedPercent === undefined)
              ? `N/A (${{gpuRatio.toFixed(0)}}%)`
              : `~${{Number(gpuEstimatedPercent).toFixed(1)}}%`)
            : `${{Number(gpuPercent).toFixed(1)}}%`;

        const cpuPercent = Math.max(0, Math.min(100, Number(state.cpu_percent || 0)));
        const memPercent = Math.max(0, Math.min(100, Number(state.mem_percent || 0)));
        const gpuBarPercent = Math.max(0, Math.min(100, Number(gpuPercent ?? gpuEstimatedPercent ?? gpuRatio)));
        const cpuBar = document.getElementById("cpu-load-bar");
        const memBar = document.getElementById("mem-load-bar");
        const gpuBar = document.getElementById("gpu-load-bar");
        if (cpuBar) cpuBar.style.width = `${{cpuPercent}}%`;
        if (memBar) memBar.style.width = `${{memPercent}}%`;
        if (gpuBar) gpuBar.style.width = `${{gpuBarPercent}}%`;
        document.getElementById("cpu-load-text").textContent = `${{cpuPercent.toFixed(1)}}%`;
        document.getElementById("mem-load-text").textContent = `${{memPercent.toFixed(1)}}%`;
        document.getElementById("gpu-load-text").textContent =
          (gpuPercent === null || gpuPercent === undefined)
            ? ((gpuEstimatedPercent === null || gpuEstimatedPercent === undefined)
              ? `N/A (${{gpuRatio.toFixed(0)}}%)`
              : `~${{gpuBarPercent.toFixed(1)}}%`)
            : `${{gpuBarPercent.toFixed(1)}}%`;
        document.getElementById("gpu-load-meta").textContent =
          `backend=${{state.gpu_backend || "none"}}, note=${{state.gpu_note || "-"}}`;

        renderLoadBar(state.fast_reaction || {{}}, {{
          kind: "fast",
          barId: "fast-load-bar",
          textId: "fast-load-text",
          metaId: "fast-load-meta",
        }});
        const health = state.error ? `错误: ${{state.error}}` : "运行中";
        const modeLabel = state.mode === "live" ? "实时" : (state.mode === "mock" ? "模拟" : state.mode);
        const sourceSummary = (state.source_health || []).map((item) => `${{item.name}}:${{item.last_read_ok ? "ok" : "idle"}}/${{item.mode_label || item.mode || "-"}}`).join(" | ");
        const profileLabel = `${{state.current_profile || "-"}} / ${{state.detector_profile || "-"}}`;
        const stabilizerLabel = state.current_stabilizer || "-";
        const holdSeconds = Number(state.reaction_hold_seconds || 0);
        const reactionAgeMs = state.latest_reaction_age_ms;
        const gestureScenePriority = Number(state.gesture_scene_priority ?? 1);
        const sceneMinSingleSignalScore = Number(state.scene_min_single_signal_score ?? 0.45);
        const faceThreshold = Number(state.face_hysteresis_threshold ?? 0.58);
        const gestureThreshold = Number(state.gesture_hysteresis_threshold ?? 0.68);
        const gestureCooldownMs = Number(state.gesture_cooldown_ms ?? 2200);
        const gazeThreshold = Number(state.gaze_hysteresis_threshold ?? 0.60);
        const audioSemanticThreshold = Number(state.audio_panns_threshold ?? 0.28);
        const audioVadThreshold = Number(state.audio_vad_threshold ?? 0.50);
        const motionPixelThreshold = Number(state.motion_pixel_threshold ?? 22);
        const motionMinAreaRatio = Number(state.motion_min_area_ratio ?? 0.03);
        if (!tuningDirty && !tuningRequestInFlight) {{
          if (gesturePrioritySlider) gesturePrioritySlider.value = String(Math.round(gestureScenePriority));
          if (sceneScoreSlider) sceneScoreSlider.value = String(sceneMinSingleSignalScore);
          if (faceThresholdSlider) faceThresholdSlider.value = String(faceThreshold);
          if (gestureThresholdSlider) gestureThresholdSlider.value = String(gestureThreshold);
          if (gestureCooldownSlider) gestureCooldownSlider.value = String(Math.round(gestureCooldownMs));
          if (gazeThresholdSlider) gazeThresholdSlider.value = String(gazeThreshold);
          if (audioSemanticSlider) audioSemanticSlider.value = String(audioSemanticThreshold);
          if (audioVadSlider) audioVadSlider.value = String(audioVadThreshold);
          if (motionPixelSlider) motionPixelSlider.value = String(Math.round(motionPixelThreshold));
          if (motionAreaSlider) motionAreaSlider.value = String(motionMinAreaRatio);
          syncSliderLabels();
        }}
        document.getElementById("meta").textContent =
          `模式=${{modeLabel}} | 配置=${{profileLabel}} | 稳态=${{stabilizerLabel}} | 摄像头帧=${{state.camera_packets}} | 麦克风帧=${{state.microphone_packets}} | 状态=${{health}} | 来源=${{sourceSummary || "-"}} | 话术节流=${{holdSeconds.toFixed(1)}}s | 话术龄=${{reactionAgeMs ?? "-"}}ms | GPU管线占比=${{gpuRatio.toFixed(0)}}%`;
        const fastCamera = document.getElementById("camera-fast-view");
        if (state.has_fast_camera_frame) {{
          fastCamera.src = `/api/camera_fast.jpg?ts=${{Date.now()}}`;
        }} else {{
          fastCamera.removeAttribute("src");
        }}

        const reaction = state.latest_reaction || {{}};
        document.getElementById("what-saw").textContent = reaction.detected_event || reaction.saw || "尚未形成稳定感知";
        document.getElementById("what-decision").textContent = reaction.arbitration_logic || reaction.decision || "-";
        document.getElementById("what-executed").textContent = reaction.executed_event || "-";
        document.getElementById("what-react").textContent = reaction.robot_response || reaction.react || "等待下一次可执行场景";
        document.getElementById("what-scene").textContent = reaction.scene || "-";
        document.getElementById("what-action").textContent = reaction.action || "-";
        document.getElementById("what-expression").textContent = reaction.expression || "-";
        document.getElementById("what-tts").textContent = reaction.tts || "-";
        if (reaction.route_summary) {{
          document.getElementById("what-decision").textContent =
            `${{reaction.arbitration_logic || reaction.decision || "-"}} | ${{reaction.route_summary}}`;
        }}

        const detRows = (state.latest_detections || []).map((d) => [d.time, d.event_type, d.detector, d.confidence]);
        renderTableRows("detections-body", detRows, 4);

        const behaviorRows = [];
        (state.latest_scenes || []).forEach((s) => {{
          behaviorRows.push([s.time, s.scene_type, "-", `评分=${{s.score_hint}}`]);
        }});
        (state.latest_arbitrations || []).forEach((a) => {{
          behaviorRows.push([a.time, a.target_behavior, a.priority, a.mode]);
        }});
        (state.latest_executions || []).forEach((e) => {{
          behaviorRows.push([e.time, e.behavior_id, "-", `${{e.status}}/${{e.degraded ? "降级" : "正常"}}`]);
        }});
        renderTableRows("behavior-body", behaviorRows.slice(0, 16), 4);

        const routeRows = (state.scene_routes || []).map((route) => {{
          return [route.path, route.latest_scene || "-", route.count, route.status || "-"];
        }});
        renderTableRows("scene-route-body", routeRows, 4);

        const monitorRows = (state.pipeline_monitors || []).map((m) => {{
          const detStable = `${{m.detections ?? 0}} / ${{m.stable_events ?? 0}}`;
          const sceneExec = `${{m.scenes ?? 0}} / ${{m.decisions ?? 0}} / ${{m.executions ?? 0}}`;
          const duration = m.last_duration_ms == null ? "-" : `${{Number(m.last_duration_ms).toFixed(2)}}ms`;
          const conf = m.last_confidence == null ? "-" : String(m.last_confidence);
          const tail = `状态=${{m.status_label || m.status || "-"}} | 置信=${{conf}} | 时延=${{duration}} | 追踪=${{m.last_trace || "-"}}`;
          return [m.pipeline, m.compute_target_label || "-", detStable, sceneExec, `${{m.last_event || "-"}} (${{tail}})`];
        }});
        renderTableRows("pipeline-monitor-body", monitorRows, 5);

        const transitionRows = (state.event_transitions || []).slice(0, 20).map((t) => {{
          const left = `${{t.detection || "-"}} → ${{t.stable || "-"}} → ${{t.scene || "-"}}`;
          const right = `${{t.path || "-"}} | ${{t.decision || "-"}} → ${{t.execution || "-"}}`;
          return [t.time || "-", t.trace || "-", t.pipeline || "-", left, right];
        }});
        renderTableRows("transition-body", transitionRows, 5);

        const obsRows = [];
        const st = state.stabilizer || {{}};
        const stTotals = st.totals || {{}};
        if (Object.keys(stTotals).length > 0) {{
          obsRows.push([
            "稳态器汇总",
            stTotals.input ?? 0,
            stTotals.emitted ?? 0,
            `过期过滤=${{stTotals.filtered_ttl ?? 0}}, 防抖过滤=${{stTotals.filtered_debounce ?? 0}}, 回滞过滤=${{stTotals.filtered_hysteresis ?? 0}}, 去重过滤=${{stTotals.filtered_dedup ?? 0}}, 冷却过滤=${{stTotals.filtered_cooldown ?? 0}}`
          ]);
        }}
        const ar = state.arbitration || {{}};
        const outcomes = ar.outcomes || {{}};
        const pendingByPriority = ar.pending_by_priority || {{}};
        obsRows.push([
          "仲裁器",
          ar.pending_queue ?? 0,
          outcomes.executed ?? 0,
          `排队=${{outcomes.queued ?? 0}}, 丢弃=${{outcomes.dropped ?? 0}}, 出队=${{outcomes.dequeued ?? 0}}, 最近结果=${{ar.last_outcome || "-"}}`
        ]);
        obsRows.push([
          "队列明细",
          `P1=${{pendingByPriority.P1 ?? 0}}, P2=${{pendingByPriority.P2 ?? 0}}, P3=${{pendingByPriority.P3 ?? 0}}`,
          `抢占=${{state.preemptions || 0}}`,
          `防抖=${{outcomes.debounced ?? 0}}, 丢弃=${{outcomes.dropped ?? 0}}, 出队=${{outcomes.dequeued ?? 0}}`
        ]);
        (state.pipeline_statuses || []).forEach((pipeline) => {{
          obsRows.push([
            `管线/${{pipeline.name}}`,
            pipeline.enabled ? "enabled" : "disabled",
            pipeline.status_label || pipeline.status || "-",
            `${{pipeline.implementation || "-"}}${{pipeline.reason ? " | " + pipeline.reason : ""}}`
          ]);
        }});
        renderTableRows("observability-body", obsRows, 4);

        const resRows = [];
        const resources = state.resources || {{}};
        const statusMap = resources.status || {{}};
        const ownersMap = resources.owners || {{}};
        Object.keys(statusMap).slice(0, 8).forEach((name) => {{
          const owners = ownersMap[name] || [];
          const lead = owners.length > 0 ? owners[0] : null;
          const ownerText = lead ? `${{lead.behavior_id}}(${{lead.priority}})` : "-";
          const detail = lead ? `剩余TTL=${{lead.ttl_ms}}ms` : "-";
          resRows.push([name, statusMap[name], ownerText, detail]);
        }});
        (state.source_health || []).forEach((source) => {{
          const stateText = source.is_open ? "opened" : "closed";
          const ownerText = `${{source.mode_label || source.mode || "-"}} / ${{source.kind_label || source.source_kind || "-"}}`;
          const detail = `最近读取=${{source.last_read_ok ? "ok" : "idle"}}, 帧龄=${{source.last_frame_age_ms ?? source.last_packet_age_ms ?? "-"}}ms, 失败=${{source.total_failures ?? source.read_failures ?? 0}}, 恢复=${{source.recovery_count ?? 0}}${{source.backend ? ", backend=" + source.backend : ""}}${{source.device ? ", device=" + source.device : ""}}`;
          resRows.push([`来源/${{source.name}}`, stateText, ownerText, detail]);
        }});
        renderTableRows("resources-body", resRows, 4);

        renderFeed(state.feed || []);
        renderLatency(state.latency_history || []);
      }} catch (_err) {{
        // Dashboard should stay alive even if one polling round fails.
      }}
    }}
    window.addEventListener("resize", () => renderLatency([]));
    [
      gesturePrioritySlider,
      sceneScoreSlider,
      faceThresholdSlider,
      gestureThresholdSlider,
      gestureCooldownSlider,
      gazeThresholdSlider,
      audioSemanticSlider,
      audioVadSlider,
      motionPixelSlider,
      motionAreaSlider,
    ].forEach((slider) => {{
      if (!slider) return;
      slider.addEventListener("input", scheduleTuningUpdate);
      slider.addEventListener("change", scheduleTuningUpdate);
    }});
    syncSliderLabels();
    refresh();
    setInterval(refresh, REFRESH_MS);
  </script>
</body>
</html>
"""


@dataclass
class DashboardState:
    mode: str
    current_profile: str = "unknown"
    detector_profile: str = "unknown"
    current_stabilizer: str = "unknown"
    max_history: int = 180
    max_rows: int = 20
    slow_frame_interval_s: float = 5.0
    reaction_hold_seconds: float = 4.0
    preview_refresh_interval_s: float = 0.55
    preview_max_width: int = 360
    preview_jpeg_quality: int = 56
    resource_sample_interval_s: float = 0.8
    _lock: Lock = field(default_factory=Lock, init=False)
    started_at: float = field(default_factory=monotonic, init=False)
    last_error: str | None = field(default=None, init=False)
    iterations: int = field(default=0, init=False)
    camera_packets: int = field(default=0, init=False)
    microphone_packets: int = field(default=0, init=False)
    total_detections: int = field(default=0, init=False)
    total_stable_events: int = field(default=0, init=False)
    total_executions: int = field(default=0, init=False)
    last_latency_ms: float = field(default=0.0, init=False)
    _iteration_times: Deque[float] = field(default_factory=deque, init=False)
    _latency_history: Deque[dict[str, float]] = field(default_factory=deque, init=False)
    _latest_detections: Deque[dict[str, Any]] = field(default_factory=deque, init=False)
    _latest_scenes: Deque[dict[str, Any]] = field(default_factory=deque, init=False)
    _latest_arbitrations: Deque[dict[str, Any]] = field(default_factory=deque, init=False)
    _latest_executions: Deque[dict[str, Any]] = field(default_factory=deque, init=False)
    _feed: Deque[dict[str, str]] = field(default_factory=deque, init=False)
    _stabilizer_snapshot: dict[str, Any] = field(default_factory=dict, init=False)
    _arbitration_snapshot: dict[str, Any] = field(default_factory=dict, init=False)
    _resource_snapshot: dict[str, Any] = field(default_factory=dict, init=False)
    _fast_reaction_snapshot: dict[str, Any] = field(default_factory=dict, init=False)
    _life_state_snapshot: dict[str, Any] = field(default_factory=dict, init=False)
    _slow_scene_snapshot: dict[str, Any] = field(default_factory=dict, init=False)
    _runtime_tuning_snapshot: dict[str, Any] = field(default_factory=dict, init=False)
    _source_health: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    _last_observe_at: float = field(default=0.0, init=False)
    _last_resource_sample_at: float = field(default=0.0, init=False)
    _latest_fast_camera_jpeg: bytes | None = field(default=None, init=False)
    _latest_slow_camera_jpeg: bytes | None = field(default=None, init=False)
    _latest_fast_camera_jpeg_at: float = field(default=0.0, init=False)
    _latest_slow_camera_jpeg_at: float = field(default=0.0, init=False)
    _latest_fast_camera_frame: Any = field(default=None, init=False)
    _latest_slow_camera_frame: Any = field(default=None, init=False)
    _latest_fast_camera_detections: list[Any] = field(default_factory=list, init=False)
    _last_slow_capture_at: float = field(default=0.0, init=False)
    _preview_request_fast: bool = field(default=False, init=False)
    _preview_request_slow: bool = field(default=False, init=False)
    _preview_stop_event: Event = field(default_factory=Event, init=False)
    _preview_wakeup_event: Event = field(default_factory=Event, init=False)
    _preview_thread: Thread | None = field(default=None, init=False)
    _latest_reaction: dict[str, str] = field(default_factory=dict, init=False)
    _latest_slow_natural_text: str = field(default="慢思考暂无结果", init=False)
    _latest_reaction_at: float = field(default=0.0, init=False)
    _latest_reaction_scene_sig: str = field(default="", init=False)
    _latest_reaction_exec_sig: str = field(default="", init=False)
    _pipeline_event_stats: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    _event_transitions: Deque[dict[str, Any]] = field(default_factory=deque, init=False)
    _scene_route_rows: Deque[dict[str, Any]] = field(default_factory=deque, init=False)
    _trace_pipeline_map: dict[str, str] = field(default_factory=dict, init=False)
    _trace_pipeline_order: Deque[str] = field(default_factory=deque, init=False)
    _runtime_resource_snapshot: dict[str, Any] = field(default_factory=dict, init=False)
    _startup_state: str = field(default="booting", init=False)
    _startup_message: str = field(default="dashboard_booting", init=False)
    _startup_state_changed_at: float = field(default_factory=monotonic, init=False)

    def __post_init__(self) -> None:
        env_hold = os.getenv("ROBOT_LIFE_REACTION_HOLD_S")
        if env_hold:
            try:
                self.reaction_hold_seconds = float(env_hold)
            except (TypeError, ValueError):
                logger.warning("invalid ROBOT_LIFE_REACTION_HOLD_S=%r; fallback=%s", env_hold, self.reaction_hold_seconds)
        self.reaction_hold_seconds = max(0.5, min(30.0, float(self.reaction_hold_seconds)))
        self.preview_refresh_interval_s = max(0.2, float(self.preview_refresh_interval_s))
        self.preview_max_width = max(160, int(self.preview_max_width))
        self.preview_jpeg_quality = max(40, min(90, int(self.preview_jpeg_quality)))
        self.resource_sample_interval_s = max(0.2, float(self.resource_sample_interval_s))
        self._iteration_times = deque(maxlen=max(30, self.max_history))
        self._latency_history = deque(maxlen=max(30, self.max_history))
        self._latest_detections = deque(maxlen=max(5, self.max_rows))
        self._latest_scenes = deque(maxlen=max(5, self.max_rows))
        self._latest_arbitrations = deque(maxlen=max(5, self.max_rows))
        self._latest_executions = deque(maxlen=max(5, self.max_rows))
        self._feed = deque(maxlen=max(10, self.max_rows * 2))
        self._event_transitions = deque(maxlen=max(20, self.max_rows * 3))
        self._scene_route_rows = deque(maxlen=max(10, self.max_rows))
        self._trace_pipeline_order = deque(maxlen=max(200, self.max_rows * 40))
        self._runtime_resource_snapshot = {
            "cpu_percent": 0.0,
            "mem_percent": 0.0,
            "gpu_percent": None,
            "gpu_estimated_percent": None,
            "gpu_backend": "none",
            "gpu_note": "sampling_pending",
            "gpu_pipeline_ratio": 0.0,
            "sampled_at": 0.0,
        }

    def _render_preview_payload(self, frame: Any, detections: list[Any], *, annotate: bool) -> bytes | None:
        return _render_camera_preview(
            frame,
            detections,
            annotate=annotate,
            max_width=self.preview_max_width,
            jpeg_quality=self.preview_jpeg_quality,
        )

    def start_preview_worker(self) -> None:
        with self._lock:
            if self._preview_thread is not None and self._preview_thread.is_alive():
                return
            self._preview_stop_event.clear()
            self._preview_wakeup_event.clear()
            self._preview_thread = Thread(
                target=self._preview_worker_loop,
                name="robot-life-ui-preview",
                daemon=True,
            )
            self._preview_thread.start()

    def stop_preview_worker(self) -> None:
        with self._lock:
            thread = self._preview_thread
            self._preview_thread = None
            self._preview_stop_event.set()
            self._preview_wakeup_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _preview_worker_loop(self) -> None:
        while not self._preview_stop_event.is_set():
            self._preview_wakeup_event.wait(timeout=0.25)
            self._preview_wakeup_event.clear()
            drained = True
            while drained and not self._preview_stop_event.is_set():
                drained = self._drain_preview_requests_once()

    def _drain_preview_requests_once(self) -> bool:
        now = monotonic()
        with self._lock:
            request_fast = self._preview_request_fast
            request_slow = self._preview_request_slow
            fast_frame = self._latest_fast_camera_frame if request_fast else None
            fast_detections = list(self._latest_fast_camera_detections) if request_fast else []
            slow_frame = self._latest_slow_camera_frame if request_slow else None
            self._preview_request_fast = False
            self._preview_request_slow = False
        if not request_fast and not request_slow:
            return False

        fast_payload = None
        slow_payload = None
        if fast_frame is not None:
            fast_payload = self._render_preview_payload(
                fast_frame,
                fast_detections,
                annotate=True,
            )
        if slow_frame is not None:
            slow_payload = self._render_preview_payload(
                slow_frame,
                [],
                annotate=False,
            )

        with self._lock:
            if fast_payload is not None:
                self._latest_fast_camera_jpeg = fast_payload
                self._latest_fast_camera_jpeg_at = now
            if slow_payload is not None:
                self._latest_slow_camera_jpeg = slow_payload
                self._latest_slow_camera_jpeg_at = now
        return True

    def set_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message
            if self._startup_state != "running":
                self._startup_state = "failed"
                self._startup_message = message
                self._startup_state_changed_at = monotonic()
            self._feed.appendleft({"time": _now_label(), "text": message, "level": "bad"})

    def set_startup_state(self, state: str, message: str | None = None) -> None:
        resolved_state = str(state or "booting").strip().lower() or "booting"
        resolved_message = str(message or resolved_state)
        with self._lock:
            if self._startup_state == resolved_state and self._startup_message == resolved_message:
                return
            self._startup_state = resolved_state
            self._startup_message = resolved_message
            self._startup_state_changed_at = monotonic()

    def set_reaction_hold_seconds(self, hold_seconds: float) -> float:
        resolved = max(0.5, min(30.0, float(hold_seconds)))
        with self._lock:
            self.reaction_hold_seconds = resolved
            self._feed.appendleft(
                {
                    "time": _now_label(),
                    "text": f"实时调参：话术节流={_round(resolved)}s",
                    "level": "ok",
                }
            )
        return resolved

    def _remember_trace_pipeline(self, trace_id: str, pipeline_name: str) -> None:
        if not trace_id:
            return
        self._trace_pipeline_map[trace_id] = pipeline_name
        self._trace_pipeline_order.append(trace_id)
        while len(self._trace_pipeline_map) > self._trace_pipeline_order.maxlen:
            oldest = self._trace_pipeline_order.popleft()
            if oldest:
                self._trace_pipeline_map.pop(oldest, None)

    def _resolve_pipeline_for_trace(self, trace_id: str, *, event_type: str | None = None) -> str:
        if trace_id and trace_id in self._trace_pipeline_map:
            return self._trace_pipeline_map[trace_id]
        return _infer_pipeline_name(event_type=event_type)

    def _bump_pipeline_stat(
        self,
        *,
        pipeline_name: str,
        stage: str,
        now: float,
        label: str | None = None,
        confidence: float | None = None,
        trace_id: str | None = None,
    ) -> None:
        if pipeline_name in {"", "unknown"}:
            return
        entry = dict(
            self._pipeline_event_stats.get(
                pipeline_name,
                {
                    "pipeline": pipeline_name,
                    "detections": 0,
                    "stable_events": 0,
                    "scenes": 0,
                    "decisions": 0,
                    "executions": 0,
                    "last_event": "-",
                    "last_stage": "-",
                    "last_confidence": None,
                    "last_trace": "-",
                    "last_seen_at": None,
                },
            )
        )
        if stage in {"detections", "stable_events", "scenes", "decisions", "executions"}:
            entry[stage] = int(entry.get(stage, 0)) + 1
        entry["last_stage"] = stage
        if label:
            entry["last_event"] = label
        if confidence is not None:
            entry["last_confidence"] = _round(confidence)
        if trace_id:
            entry["last_trace"] = _short_trace(trace_id)
        entry["last_seen_at"] = now
        self._pipeline_event_stats[pipeline_name] = entry

    def record_iteration(self, result: LiveLoopResult, *, latency_ms: float) -> None:
        now = monotonic()
        camera_frame = result.collected_frames.frames.get("camera")
        reaction_candidate = _build_reaction(result)
        fast_preview_frame: Any = None
        fast_preview_detections: list[Any] = []
        slow_preview_frame: Any = None
        if result.slow_scene_results:
            self._latest_slow_natural_text = _natural_slow_scene_text(result.slow_scene_results[-1])
        reaction_candidate["slow"] = self._latest_slow_natural_text
        scene_signature = ""
        execution_signature = ""
        if result.scene_candidates:
            scene = result.scene_candidates[-1]
            scene_signature = f"{getattr(scene, 'scene_type', '')}:{_round(getattr(scene, 'score_hint', 0.0))}"
        if result.arbitration_results:
            decision = result.arbitration_results[-1]
            scene_signature = (
                scene_signature
                + f"|{getattr(decision, 'target_behavior', '')}:{getattr(getattr(decision, 'mode', None), 'value', '')}"
            )
        if result.execution_results:
            execution = result.execution_results[-1]
            execution_signature = (
                f"{getattr(execution, 'behavior_id', '')}:{getattr(execution, 'status', '')}:"
                f"{int(bool(getattr(execution, 'degraded', False)))}"
            )
        packets = result.collected_frames.packets
        with self._lock:
            self.iterations += 1
            self.last_latency_ms = latency_ms
            self._iteration_times.append(now)
            self._latency_history.append({"t": now, "latency_ms": _round(latency_ms)})
            if "camera" in result.collected_frames.packets:
                self.camera_packets += 1
            if "microphone" in result.collected_frames.packets:
                self.microphone_packets += 1

            self.total_detections += len(result.detections)
            self.total_stable_events += len(result.stable_events)
            self.total_executions += len(result.execution_results)

            transitions_by_trace: dict[str, dict[str, str]] = {}
            for detection in result.detections:
                pipeline_name = _infer_pipeline_name(detector=detection.detector, event_type=detection.event_type)
                self._remember_trace_pipeline(detection.trace_id, pipeline_name)
                self._bump_pipeline_stat(
                    pipeline_name=pipeline_name,
                    stage="detections",
                    now=now,
                    label=_natural_event_name(detection.event_type),
                    confidence=detection.confidence,
                    trace_id=detection.trace_id,
                )
                trace_entry = transitions_by_trace.setdefault(detection.trace_id, {})
                trace_entry["detection"] = _natural_event_name(detection.event_type)
            for stable_event in result.stable_events:
                pipeline_name = self._resolve_pipeline_for_trace(
                    getattr(stable_event, "trace_id", ""),
                    event_type=getattr(stable_event, "event_type", ""),
                )
                self._bump_pipeline_stat(
                    pipeline_name=pipeline_name,
                    stage="stable_events",
                    now=now,
                    label=_natural_event_name(getattr(stable_event, "event_type", "")),
                    trace_id=getattr(stable_event, "trace_id", ""),
                )
                trace_entry = transitions_by_trace.setdefault(getattr(stable_event, "trace_id", ""), {})
                trace_entry["stable"] = _natural_event_name(getattr(stable_event, "event_type", ""))
            for scene in result.scene_candidates:
                pipeline_name = self._resolve_pipeline_for_trace(
                    getattr(scene, "trace_id", ""),
                    event_type=getattr(scene, "scene_type", ""),
                )
                scene_payload = scene.payload if isinstance(getattr(scene, "payload", None), dict) else {}
                scene_path = str(scene_payload.get("scene_path", "")).strip().lower() or "social"
                self._bump_pipeline_stat(
                    pipeline_name=pipeline_name,
                    stage="scenes",
                    now=now,
                    label=_natural_scene_name(getattr(scene, "scene_type", "")),
                    confidence=getattr(scene, "score_hint", 0.0),
                    trace_id=getattr(scene, "trace_id", ""),
                )
                trace_entry = transitions_by_trace.setdefault(getattr(scene, "trace_id", ""), {})
                trace_entry["scene"] = _natural_scene_name(getattr(scene, "scene_type", ""))
                trace_entry["path"] = scene_path
            for decision in result.arbitration_results:
                pipeline_name = self._resolve_pipeline_for_trace(
                    getattr(decision, "trace_id", ""),
                    event_type=getattr(decision, "target_behavior", ""),
                )
                self._bump_pipeline_stat(
                    pipeline_name=pipeline_name,
                    stage="decisions",
                    now=now,
                    label=_natural_behavior_name(getattr(decision, "target_behavior", "")),
                    trace_id=getattr(decision, "trace_id", ""),
                )
                trace_entry = transitions_by_trace.setdefault(getattr(decision, "trace_id", ""), {})
                trace_entry["decision"] = _natural_mode_name(getattr(getattr(decision, "mode", None), "value", ""))
            for execution in result.execution_results:
                pipeline_name = self._resolve_pipeline_for_trace(
                    getattr(execution, "trace_id", ""),
                    event_type=getattr(execution, "behavior_id", ""),
                )
                self._bump_pipeline_stat(
                    pipeline_name=pipeline_name,
                    stage="executions",
                    now=now,
                    label=_natural_behavior_name(getattr(execution, "behavior_id", "")),
                    trace_id=getattr(execution, "trace_id", ""),
                )
                trace_entry = transitions_by_trace.setdefault(getattr(execution, "trace_id", ""), {})
                trace_entry["execution"] = _natural_execution_status(getattr(execution, "status", ""))

            for trace_id, chain in list(transitions_by_trace.items())[:8]:
                self._event_transitions.appendleft(
                    {
                        "time": _now_label(),
                        "trace": _short_trace(trace_id),
                        "pipeline": self._resolve_pipeline_for_trace(trace_id),
                        "path": chain.get("path", "-"),
                        "detection": chain.get("detection", "-"),
                        "stable": chain.get("stable", "-"),
                        "scene": chain.get("scene", "-"),
                        "decision": chain.get("decision", "-"),
                        "execution": chain.get("execution", "-"),
                    }
                )

            scene_batches = result.scene_batches if isinstance(getattr(result, "scene_batches", None), dict) else {}
            route_rows: list[dict[str, Any]] = []
            for path_name in ("safety", "social"):
                path_scenes = scene_batches.get(path_name, [])
                if path_scenes:
                    latest_scene = _natural_scene_name(getattr(path_scenes[-1], "scene_type", ""))
                    status = "待仲裁"
                    if path_name == "safety" and result.execution_results:
                        status = "已执行"
                    elif path_name == "social" and scene_batches.get("safety") and result.execution_results:
                        if any(getattr(execution, "behavior_id", "") == "perform_safety_alert" for execution in result.execution_results):
                            status = "被 safety 压制"
                else:
                    latest_scene = "-"
                    status = "空闲"
                route_rows.append(
                    {
                        "path": path_name,
                        "latest_scene": latest_scene,
                        "count": len(path_scenes),
                        "status": status,
                    }
                )
            self._scene_route_rows.clear()
            for row in route_rows:
                self._scene_route_rows.append(row)

            for source_name, packet in packets.items():
                entry = dict(self._source_health.get(source_name, {}))
                entry["name"] = source_name
                entry["packet_count"] = int(entry.get("packet_count", 0)) + 1
                entry["frame_index"] = getattr(packet, "frame_index", 0)
                entry["last_packet_at"] = now
                entry["last_read_ok"] = True
                if source_name == "microphone":
                    entry.update(_extract_audio_levels(getattr(packet, "payload", None)))
                packet_kind = _infer_packet_source_kind(packet)
                if packet_kind:
                    entry["source_kind"] = packet_kind
                self._source_health[source_name] = entry

            for detection in result.detections[-3:]:
                payload = detection.payload if isinstance(detection.payload, dict) else {}
                detail = _describe_detection_payload(payload)
                self._latest_detections.appendleft(
                    {
                        "time": _now_label(),
                        "event_type": f"{_natural_event_name(detection.event_type)}（{detail}）",
                        "detector": _natural_detector_name(detection.detector),
                        "confidence": _round(detection.confidence),
                    }
                )
            for scene in result.scene_candidates[-2:]:
                self._latest_scenes.appendleft(
                    {
                        "time": _now_label(),
                        "scene_type": _natural_scene_name(scene.scene_type),
                        "score_hint": _round(scene.score_hint),
                    }
                )
            for decision in result.arbitration_results[-2:]:
                self._latest_arbitrations.appendleft(
                    {
                        "time": _now_label(),
                        "target_behavior": _natural_behavior_name(decision.target_behavior),
                        "priority": decision.priority.value,
                        "mode": _natural_mode_name(decision.mode.value),
                    }
                )
            for execution in result.execution_results[-2:]:
                self._latest_executions.appendleft(
                    {
                        "time": _now_label(),
                        "behavior_id": _natural_behavior_name(execution.behavior_id),
                        "status": _natural_execution_status(execution.status),
                        "degraded": bool(execution.degraded),
                    }
                )

            if result.detections:
                last_det = result.detections[-1]
                self._feed.appendleft(
                    {
                        "time": _now_label(),
                        "text": f"检测：{_natural_event_name(last_det.event_type)}，置信度={_round(last_det.confidence)}",
                        "level": "warn",
                    }
                )
            if result.scene_candidates:
                last_scene = result.scene_candidates[-1]
                payload = last_scene.payload if isinstance(getattr(last_scene, "payload", None), dict) else {}
                scene_path = str(payload.get("scene_path", "")).strip().lower() or "social"
                self._feed.appendleft(
                    {
                        "time": _now_label(),
                        "text": f"场景：{_natural_scene_name(last_scene.scene_type)}，通路={scene_path}，评分={_round(last_scene.score_hint)}",
                        "level": "ok",
                    }
                )
            if result.arbitration_results:
                last_decision = result.arbitration_results[-1]
                self._feed.appendleft(
                    {
                        "time": _now_label(),
                        "text": f"仲裁：{_natural_behavior_name(last_decision.target_behavior)}，模式={_natural_mode_name(last_decision.mode.value)}",
                        "level": "ok",
                    }
                )
            if result.execution_results:
                last_exec = result.execution_results[-1]
                self._feed.appendleft(
                    {
                        "time": _now_label(),
                        "text": (
                            f"已执行动作：{_natural_behavior_name(last_exec.behavior_id)}，"
                            f"状态={_natural_execution_status(last_exec.status)}，"
                            f"降级={'是' if last_exec.degraded else '否'}"
                        ),
                        "level": "ok" if not last_exec.degraded else "warn",
                    }
                )
            elif result.stable_events:
                last_stable = result.stable_events[-1]
                self._feed.appendleft(
                    {
                        "time": _now_label(),
                        "text": f"稳定事件：{_natural_event_name(last_stable.event_type)}",
                        "level": "ok",
                    }
                )

            if camera_frame is not None:
                self._latest_fast_camera_frame = camera_frame
                self._latest_fast_camera_detections = list(result.detections[-8:])
                if (
                    self._latest_fast_camera_jpeg is None
                    or (now - self._latest_fast_camera_jpeg_at) >= self.preview_refresh_interval_s
                ):
                    fast_preview_frame = camera_frame
                    fast_preview_detections = list(result.detections[-8:])
            if camera_frame is not None and (
                now - self._last_slow_capture_at
            ) >= max(0.2, float(self.slow_frame_interval_s)):
                self._latest_slow_camera_frame = camera_frame
                self._last_slow_capture_at = now
                if (
                    self._latest_slow_camera_jpeg is None
                    or (now - self._latest_slow_camera_jpeg_at) >= self.slow_frame_interval_s
                ):
                    slow_preview_frame = camera_frame
            # Keep the natural-language panel stable: only switch output when we have
            # a new scene/decision/execution signature and enough hold time elapsed.
            hold_seconds = self.reaction_hold_seconds
            has_structured_signal = bool(
                result.scene_candidates or result.arbitration_results or result.execution_results
            )
            can_update = not self._latest_reaction
            if result.execution_results:
                if execution_signature and execution_signature != self._latest_reaction_exec_sig:
                    can_update = can_update or (now - self._latest_reaction_at) >= hold_seconds
                elif execution_signature == self._latest_reaction_exec_sig:
                    can_update = False
            elif has_structured_signal:
                if scene_signature and scene_signature != self._latest_reaction_scene_sig:
                    can_update = can_update or (now - self._latest_reaction_at) >= hold_seconds
                else:
                    can_update = False
            else:
                can_update = False

            if can_update:
                self._latest_reaction = reaction_candidate
                self._latest_reaction_at = now
                if scene_signature:
                    self._latest_reaction_scene_sig = scene_signature
                if execution_signature:
                    self._latest_reaction_exec_sig = execution_signature
            elif self._latest_reaction:
                # Keep slow-scene narration up to date while freezing fast-reaction wording.
                self._latest_reaction["slow"] = self._latest_slow_natural_text
            else:
                self._latest_reaction = reaction_candidate
                self._latest_reaction_at = now
            self.last_error = None

        if fast_preview_frame is not None or slow_preview_frame is not None:
            with self._lock:
                if fast_preview_frame is not None:
                    self._preview_request_fast = True
                if slow_preview_frame is not None:
                    self._preview_request_slow = True
                self._preview_wakeup_event.set()

    def update_observability(self, loop: LiveLoop, *, min_interval_s: float = 0.5) -> None:
        now = monotonic()
        with self._lock:
            if now - self._last_observe_at < max(0.0, min_interval_s):
                return
            self._last_observe_at = now
            source_health = {
                name: dict(payload) for name, payload in self._source_health.items()
            }

        deps = loop.dependencies
        stabilizer_snapshot: dict[str, Any] = {}
        arbitration_snapshot: dict[str, Any] = {}
        resource_snapshot: dict[str, Any] = {}
        slow_scene_snapshot: dict[str, Any] = {}

        stabilizer = getattr(deps, "stabilizer", None)
        if stabilizer is not None and hasattr(stabilizer, "snapshot_stats"):
            try:
                stabilizer_snapshot = stabilizer.snapshot_stats()
            except Exception:
                stabilizer_snapshot = {}

        arbitration_runtime = getattr(deps, "arbitration_runtime", None)
        if arbitration_runtime is not None and hasattr(arbitration_runtime, "snapshot_stats"):
            try:
                arbitration_snapshot = arbitration_runtime.snapshot_stats()
            except Exception:
                arbitration_snapshot = {}

        executor = getattr(deps, "executor", None)
        if executor is not None and hasattr(executor, "get_debug_snapshot"):
            try:
                debug = executor.get_debug_snapshot()
                resource_snapshot = debug.get("resources", {}) if isinstance(debug, dict) else {}
            except Exception:
                resource_snapshot = {}
        elif executor is not None and hasattr(executor, "get_resource_status"):
            try:
                resource_snapshot = {"status": executor.get_resource_status()}
            except Exception:
                resource_snapshot = {}

        slow_scene = getattr(deps, "slow_scene", None)
        if slow_scene is not None and hasattr(slow_scene, "debug_snapshot"):
            try:
                slow_scene_snapshot = slow_scene.debug_snapshot()
            except Exception:
                slow_scene_snapshot = {}
        elif slow_scene is not None and hasattr(slow_scene, "health"):
            try:
                health = slow_scene.health()
                if hasattr(health, "to_dict"):
                    slow_scene_snapshot = health.to_dict()
                elif isinstance(health, dict):
                    slow_scene_snapshot = health
            except Exception:
                slow_scene_snapshot = {}

        fast_reaction_snapshot = _collect_fast_reaction_snapshot(loop)
        runtime_tuning_snapshot = {
            "fast_path_budget_ms": _round(getattr(loop, "fast_path_budget_ms", 0.0)),
            "async_perception_result_max_age_ms": _round(
                getattr(loop, "async_perception_result_max_age_ms", 0.0)
            ),
            "async_perception_result_max_frame_lag": int(
                getattr(loop, "async_perception_result_max_frame_lag", 0)
            ),
        }
        if stabilizer is not None:
            runtime_tuning_snapshot["face_hysteresis_threshold"] = _event_override_value(
                stabilizer, "stranger_face_detected", "hysteresis_threshold"
            ) or _event_override_value(stabilizer, "familiar_face_detected", "hysteresis_threshold")
            runtime_tuning_snapshot["gesture_hysteresis_threshold"] = _event_override_value(
                stabilizer, "gesture_detected", "hysteresis_threshold"
            )
            runtime_tuning_snapshot["gesture_cooldown_ms"] = _event_override_value(
                stabilizer, "gesture_detected", "cooldown_ms"
            )
            runtime_tuning_snapshot["gaze_hysteresis_threshold"] = _event_override_value(
                stabilizer, "gaze_sustained_detected", "hysteresis_threshold"
            )
        aggregator = getattr(deps, "aggregator", None)
        if aggregator is not None:
            runtime_tuning_snapshot["scene_min_single_signal_score"] = _round(
                getattr(aggregator, "min_single_signal_score", 0.0)
            )
        arbitrator = getattr(deps, "arbitrator", None)
        if arbitrator is not None:
            scene_rules = getattr(arbitrator, "_scene_rules", {})
            if isinstance(scene_rules, dict):
                gesture_rule = scene_rules.get("gesture_bond_scene", {})
                runtime_tuning_snapshot["gesture_scene_priority"] = _priority_rank_value(
                    gesture_rule.get("priority") if isinstance(gesture_rule, dict) else None
                )
        audio_detector = _resolve_audio_detector(loop)
        if audio_detector is not None:
            runtime_tuning_snapshot["audio_rms_threshold"] = getattr(audio_detector, "_rms_threshold", None)
            runtime_tuning_snapshot["audio_db_threshold"] = getattr(audio_detector, "_db_threshold", None)
            runtime_tuning_snapshot["audio_panns_threshold"] = getattr(
                audio_detector, "_panns_confidence_threshold", None
            )
            runtime_tuning_snapshot["audio_vad_threshold"] = getattr(audio_detector, "_vad_threshold", None)
        motion_detector = _resolve_pipeline_detector(loop, "motion")
        if motion_detector is not None:
            runtime_tuning_snapshot["motion_pixel_threshold"] = getattr(motion_detector, "_threshold", None)
            runtime_tuning_snapshot["motion_min_area_ratio"] = getattr(motion_detector, "_min_area_ratio", None)
        life_state_snapshot: dict[str, Any] = {}
        if hasattr(loop, "snapshot_life_state"):
            try:
                life_state_snapshot = loop.snapshot_life_state()
            except Exception:
                life_state_snapshot = {}
        source_bundle = getattr(loop, "source_bundle", None)
        if source_bundle is not None and hasattr(source_bundle, "iter_sources"):
            for source in source_bundle.iter_sources():
                source_name = getattr(source, "source_name", type(source).__name__.lower())
                entry = dict(source_health.get(source_name, {}))
                entry["name"] = source_name
                entry["is_open"] = bool(getattr(source, "is_open", False))
                if hasattr(source, "snapshot_health"):
                    try:
                        entry.update(source.snapshot_health())
                    except Exception:
                        pass
                entry["source_kind"] = entry.get("source_kind") or _infer_source_kind(source)
                entry["mode"] = entry.get("mode") or ("mock" if entry["source_kind"] == "mock" else "real")
                device = getattr(source, "device", None)
                if device not in {None, ""}:
                    entry["device"] = str(device)
                read_failures = getattr(source, "_read_failures", None)
                if read_failures is not None:
                    entry["read_failures"] = int(read_failures)
                source_health[source_name] = entry

        runtime_resource_snapshot: dict[str, Any] | None = None
        if (
            self._last_resource_sample_at <= 0.0
            or (now - self._last_resource_sample_at) >= self.resource_sample_interval_s
        ):
            try:
                runtime_resource_snapshot = _sample_runtime_resources(
                    list(fast_reaction_snapshot.get("pipelines", []))
                )
            except Exception:
                logger.exception("failed to sample runtime resources")
                runtime_resource_snapshot = None

        with self._lock:
            self._stabilizer_snapshot = stabilizer_snapshot
            self._arbitration_snapshot = arbitration_snapshot
            self._resource_snapshot = resource_snapshot
            self._fast_reaction_snapshot = fast_reaction_snapshot
            self._runtime_tuning_snapshot = runtime_tuning_snapshot
            self._life_state_snapshot = life_state_snapshot
            self._slow_scene_snapshot = slow_scene_snapshot
            self._source_health = source_health
            if runtime_resource_snapshot is not None:
                self._runtime_resource_snapshot = runtime_resource_snapshot
                self._last_resource_sample_at = now

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = monotonic()
            while self._iteration_times and (now - self._iteration_times[0]) > 5.0:
                self._iteration_times.popleft()
            loop_fps = len(self._iteration_times) / 5.0 if self._iteration_times else 0.0
            stabilizer_totals = self._stabilizer_snapshot.get("totals", {})
            arbitration_pending = int(self._arbitration_snapshot.get("pending_queue", 0))
            preemptions = int(self._resource_snapshot.get("stats", {}).get("preemptions", 0))
            slow_health = self._slow_scene_snapshot.get("health", self._slow_scene_snapshot)
            slow_queue_depth = int(slow_health.get("queue_depth", 0))
            slow_timed_out = int(slow_health.get("timed_out_requests", 0))
            stabilizer_pass_rate = float(stabilizer_totals.get("pass_rate", 0.0)) * 100.0
            slow_reaction_snapshot = _collect_slow_reaction_snapshot(self._slow_scene_snapshot)
            pipeline_statuses = []
            for pipeline in self._fast_reaction_snapshot.get("pipelines", []):
                item = dict(pipeline)
                item["status_label"] = _natural_pipeline_status(str(item.get("status", "")))
                item["compute_target_label"] = _natural_compute_target(str(item.get("compute_target", "")))
                pipeline_statuses.append(item)
            runtime_resources = dict(self._runtime_resource_snapshot)
            startup_elapsed_ms = _round(max(0.0, (now - self._startup_state_changed_at) * 1000.0))

            pipeline_monitors: list[dict[str, Any]] = []
            pipeline_stats = dict(self._pipeline_event_stats)
            pipeline_meta = {item.get("name"): item for item in pipeline_statuses}
            for pipeline_name in sorted(set(pipeline_stats.keys()) | set(pipeline_meta.keys())):
                if not pipeline_name:
                    continue
                stat = dict(pipeline_stats.get(pipeline_name, {}))
                meta = dict(pipeline_meta.get(pipeline_name, {}))
                last_seen_at = stat.get("last_seen_at")
                last_seen_age_ms = (
                    _round((now - float(last_seen_at)) * 1000.0) if last_seen_at is not None else None
                )
                pipeline_monitors.append(
                    {
                        "pipeline": pipeline_name,
                        "enabled": bool(meta.get("enabled", True)),
                        "status": str(meta.get("status", "unknown")),
                        "status_label": str(meta.get("status_label", "未知")),
                        "compute_target": str(meta.get("compute_target", "cpu")),
                        "compute_target_label": str(meta.get("compute_target_label", "CPU")),
                        "detections": int(stat.get("detections", 0)),
                        "stable_events": int(stat.get("stable_events", 0)),
                        "scenes": int(stat.get("scenes", 0)),
                        "decisions": int(stat.get("decisions", 0)),
                        "executions": int(stat.get("executions", 0)),
                        "last_event": str(stat.get("last_event", "-")),
                        "last_stage": str(stat.get("last_stage", "-")),
                        "last_confidence": stat.get("last_confidence"),
                        "last_trace": str(stat.get("last_trace", "-")),
                        "last_seen_age_ms": last_seen_age_ms,
                        "runtime_budget_ms": meta.get("runtime_budget_ms"),
                        "last_duration_ms": meta.get("last_duration_ms"),
                        "sample_rate_hz": meta.get("sample_rate_hz"),
                        "budget_skips": meta.get("budget_skips", 0),
                    }
                )
            source_health = []
            for source_name, payload in self._source_health.items():
                item = dict(payload)
                item["name"] = source_name
                item["last_packet_age_ms"] = (
                    _round((now - item["last_packet_at"]) * 1000.0)
                    if item.get("last_packet_at") is not None
                    else None
                )
                item["last_frame_age_ms"] = (
                    _round((now - item["last_frame_at"]) * 1000.0)
                    if item.get("last_frame_at") is not None
                    else None
                )
                item["last_read_ok"] = _source_read_ok(item, item["last_packet_age_ms"])
                item["kind_label"] = _natural_source_kind(str(item.get("source_kind", "")))
                mode = str(item.get("mode", "")).lower()
                if mode == "mock":
                    item["mode_label"] = "模拟"
                elif mode == "fallback":
                    item["mode_label"] = "降级"
                else:
                    item["mode_label"] = "真实"
                source_health.append(item)
            source_health.sort(key=lambda item: item["name"])
            mic_audio = next((item for item in source_health if item.get("name") == "microphone"), None)
            if isinstance(mic_audio, dict):
                audio_db = mic_audio.get("last_audio_db")
                audio_rms = mic_audio.get("last_audio_rms")
                for monitor in pipeline_monitors:
                    if monitor.get("pipeline") != "audio" or int(monitor.get("detections", 0)) != 0:
                        continue
                    if audio_db is None and audio_rms is None:
                        packet_count = int(mic_audio.get("packet_count", 0) or 0)
                        if packet_count <= 0:
                            monitor["last_event"] = "麦克风暂无输入帧（请检查输入设备、权限和采样设备索引）"
                            monitor["last_stage"] = "source"
                        continue
                    rms_threshold = "-"
                    db_threshold = "-"
                    meta = next(
                        (item for item in pipeline_statuses if str(item.get("name")) == "audio"),
                        None,
                    )
                    detector_cfg = meta.get("detector_config", {}) if isinstance(meta, dict) else {}
                    if isinstance(detector_cfg, dict):
                        raw_rms_threshold = detector_cfg.get("rms_threshold")
                        raw_db_threshold = detector_cfg.get("db_threshold")
                        if raw_rms_threshold is not None:
                            rms_threshold = raw_rms_threshold
                        if raw_db_threshold is not None:
                            db_threshold = raw_db_threshold
                    runtime_rms_threshold = self._runtime_tuning_snapshot.get("audio_rms_threshold")
                    runtime_db_threshold = self._runtime_tuning_snapshot.get("audio_db_threshold")
                    if runtime_rms_threshold is not None:
                        rms_threshold = runtime_rms_threshold
                    if runtime_db_threshold is not None:
                        db_threshold = runtime_db_threshold
                    monitor["last_event"] = (
                        f"实时音量 rms={audio_rms if audio_rms is not None else '-'}"
                        f" db={audio_db if audio_db is not None else '-'}"
                        f" | 阈值 rms>={rms_threshold} db>={db_threshold}"
                    )
                    monitor["last_stage"] = "source"
            return {
                "mode": self.mode,
                "current_profile": self.current_profile,
                "detector_profile": self.detector_profile,
                "current_stabilizer": self.current_stabilizer,
                "iterations": self.iterations,
                "camera_packets": self.camera_packets,
                "microphone_packets": self.microphone_packets,
                "total_detections": self.total_detections,
                "total_stable_events": self.total_stable_events,
                "total_executions": self.total_executions,
                "last_latency_ms": _round(self.last_latency_ms),
                "reaction_hold_seconds": _round(self.reaction_hold_seconds),
                "latest_reaction_age_ms": (
                    _round((now - self._latest_reaction_at) * 1000.0)
                    if self._latest_reaction_at > 0
                    else None
                ),
                "loop_fps": _round(loop_fps),
                "queue_pending": arbitration_pending,
                "preemptions": preemptions,
                "slow_queue_depth": slow_queue_depth,
                "slow_timed_out": slow_timed_out,
                "stabilizer_pass_rate": _round(stabilizer_pass_rate),
                "has_fast_camera_frame": self._latest_fast_camera_frame is not None,
                "has_slow_camera_frame": self._latest_slow_camera_frame is not None,
                "has_camera_frame": self._latest_fast_camera_frame is not None,
                "latest_reaction": dict(self._latest_reaction),
                "error": self.last_error,
                "startup_state": self._startup_state,
                "startup_message": self._startup_message,
                "startup_elapsed_ms": startup_elapsed_ms,
                "latency_history": list(self._latency_history),
                "latest_detections": list(self._latest_detections),
                "latest_scenes": list(self._latest_scenes),
                "latest_arbitrations": list(self._latest_arbitrations),
                "latest_executions": list(self._latest_executions),
                "stabilizer": self._stabilizer_snapshot,
                "arbitration": self._arbitration_snapshot,
                "resources": self._resource_snapshot,
                "fast_reaction": self._fast_reaction_snapshot,
                "life_state": self._life_state_snapshot,
                "pipeline_statuses": pipeline_statuses,
                "fast_path_budget_ms": self._runtime_tuning_snapshot.get("fast_path_budget_ms"),
                "async_perception_result_max_age_ms": self._runtime_tuning_snapshot.get(
                    "async_perception_result_max_age_ms"
                ),
                "async_perception_result_max_frame_lag": self._runtime_tuning_snapshot.get(
                    "async_perception_result_max_frame_lag"
                ),
                "gesture_scene_priority": self._runtime_tuning_snapshot.get("gesture_scene_priority"),
                "scene_min_single_signal_score": self._runtime_tuning_snapshot.get("scene_min_single_signal_score"),
                "face_hysteresis_threshold": self._runtime_tuning_snapshot.get("face_hysteresis_threshold"),
                "gesture_hysteresis_threshold": self._runtime_tuning_snapshot.get("gesture_hysteresis_threshold"),
                "gesture_cooldown_ms": self._runtime_tuning_snapshot.get("gesture_cooldown_ms"),
                "gaze_hysteresis_threshold": self._runtime_tuning_snapshot.get("gaze_hysteresis_threshold"),
                "audio_panns_threshold": self._runtime_tuning_snapshot.get("audio_panns_threshold"),
                "audio_vad_threshold": self._runtime_tuning_snapshot.get("audio_vad_threshold"),
                "audio_rms_threshold": self._runtime_tuning_snapshot.get("audio_rms_threshold"),
                "audio_db_threshold": self._runtime_tuning_snapshot.get("audio_db_threshold"),
                "motion_pixel_threshold": self._runtime_tuning_snapshot.get("motion_pixel_threshold"),
                "motion_min_area_ratio": self._runtime_tuning_snapshot.get("motion_min_area_ratio"),
                "slow_reaction": slow_reaction_snapshot,
                "slow_scene": self._slow_scene_snapshot,
                "source_health": source_health,
                "cpu_percent": runtime_resources.get("cpu_percent", 0.0),
                "mem_percent": runtime_resources.get("mem_percent", 0.0),
                "gpu_percent": runtime_resources.get("gpu_percent"),
                "gpu_estimated_percent": runtime_resources.get("gpu_estimated_percent"),
                "gpu_backend": runtime_resources.get("gpu_backend", "none"),
                "gpu_note": runtime_resources.get("gpu_note", "sampling_pending"),
                "gpu_pipeline_ratio": runtime_resources.get("gpu_pipeline_ratio", 0.0),
                "pipeline_monitors": pipeline_monitors,
                "scene_routes": list(self._scene_route_rows),
                "event_transitions": list(self._event_transitions),
                "feed": list(self._feed),
            }

    def public_snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = monotonic()
            while self._iteration_times and (now - self._iteration_times[0]) > 5.0:
                self._iteration_times.popleft()
            loop_fps = len(self._iteration_times) / 5.0 if self._iteration_times else 0.0
            arbitration_pending = int(self._arbitration_snapshot.get("pending_queue", 0))
            preemptions = int(self._resource_snapshot.get("stats", {}).get("preemptions", 0))
            pipeline_payloads = list(self._fast_reaction_snapshot.get("pipelines", []))
            source_payloads = {
                name: dict(payload) for name, payload in self._source_health.items()
            }
            latest_reaction = dict(self._latest_reaction)
            latest_detections = list(self._latest_detections)[:8]
            latest_scenes = list(self._latest_scenes)[:6]
            latest_arbitrations = list(self._latest_arbitrations)[:6]
            latest_executions = list(self._latest_executions)[:6]
            feed = list(self._feed)[:10]
            scene_routes = list(self._scene_route_rows)
            latest_reaction_age_ms = (
                _round((now - self._latest_reaction_at) * 1000.0)
                if self._latest_reaction_at > 0
                else None
            )

        pipelines: list[dict[str, Any]] = []
        for pipeline in pipeline_payloads[:8]:
            item = dict(pipeline)
            item["status_label"] = _natural_pipeline_status(str(item.get("status", "")))
            item["compute_target_label"] = _natural_compute_target(str(item.get("compute_target", "")))
            pipelines.append(
                {
                    "name": str(item.get("name", "")),
                    "enabled": bool(item.get("enabled", True)),
                    "status": str(item.get("status", "unknown")),
                    "status_label": str(item.get("status_label", "未知")),
                    "compute_target": str(item.get("compute_target", "cpu")),
                    "compute_target_label": str(item.get("compute_target_label", "CPU")),
                    "reason": str(item.get("reason", "")),
                    "runtime_budget_ms": item.get("runtime_budget_ms"),
                    "last_duration_ms": item.get("last_duration_ms"),
                    "sample_rate_hz": item.get("sample_rate_hz"),
                    "budget_skips": int(item.get("budget_skips", 0) or 0),
                }
            )

        source_health: list[dict[str, Any]] = []
        for source_name, payload in source_payloads.items():
            item = dict(payload)
            item["name"] = source_name
            item["last_packet_age_ms"] = (
                _round((now - item["last_packet_at"]) * 1000.0)
                if item.get("last_packet_at") is not None
                else None
            )
            item["last_frame_age_ms"] = (
                _round((now - item["last_frame_at"]) * 1000.0)
                if item.get("last_frame_at") is not None
                else None
            )
            item["last_read_ok"] = _source_read_ok(item, item["last_packet_age_ms"])
            item["kind_label"] = _natural_source_kind(str(item.get("source_kind", "")))
            mode = str(item.get("mode", "")).lower()
            if mode == "mock":
                item["mode_label"] = "模拟"
            elif mode == "fallback":
                item["mode_label"] = "降级"
            else:
                item["mode_label"] = "真实"
            source_health.append(
                {
                    "name": item["name"],
                    "backend": item.get("backend"),
                    "device": item.get("device"),
                    "mode": item.get("mode"),
                    "mode_label": item.get("mode_label"),
                    "source_kind": item.get("source_kind"),
                    "kind_label": item.get("kind_label"),
                    "is_open": bool(item.get("is_open", False)),
                    "last_read_ok": bool(item.get("last_read_ok", False)),
                    "last_packet_age_ms": item.get("last_packet_age_ms"),
                    "last_frame_age_ms": item.get("last_frame_age_ms"),
                    "packet_count": int(item.get("packet_count", 0) or 0),
                    "last_audio_db": item.get("last_audio_db"),
                    "last_audio_rms": item.get("last_audio_rms"),
                    "read_failures": int(item.get("read_failures", 0) or 0),
                }
            )
        source_health.sort(key=lambda item: item["name"])
        runtime_resources = dict(self._runtime_resource_snapshot)
        startup_elapsed_ms = _round(max(0.0, (now - self._startup_state_changed_at) * 1000.0))

        return {
            "mode": self.mode,
            "current_profile": self.current_profile,
            "detector_profile": self.detector_profile,
            "current_stabilizer": self.current_stabilizer,
            "iterations": self.iterations,
            "camera_packets": self.camera_packets,
            "microphone_packets": self.microphone_packets,
            "total_detections": self.total_detections,
            "total_stable_events": self.total_stable_events,
            "total_executions": self.total_executions,
            "loop_fps": _round(loop_fps),
            "last_latency_ms": _round(self.last_latency_ms),
            "reaction_hold_seconds": _round(self.reaction_hold_seconds),
            "latest_reaction_age_ms": latest_reaction_age_ms,
            "queue_pending": arbitration_pending,
            "preemptions": preemptions,
            "has_camera_frame": self._latest_fast_camera_frame is not None,
            "has_fast_camera_frame": self._latest_fast_camera_frame is not None,
            "latest_reaction": latest_reaction,
            "latest_detections": latest_detections,
            "latest_scenes": latest_scenes,
            "latest_arbitrations": latest_arbitrations,
            "latest_executions": latest_executions,
            "scene_routes": scene_routes,
            "feed": feed,
            "pipeline_statuses": pipelines,
            "pipelines": pipelines,
            "source_health": source_health,
            "sources": source_health,
            "cpu_percent": runtime_resources.get("cpu_percent", 0.0),
            "mem_percent": runtime_resources.get("mem_percent", 0.0),
            "gpu_percent": runtime_resources.get("gpu_percent"),
            "gpu_estimated_percent": runtime_resources.get("gpu_estimated_percent"),
            "gpu_backend": runtime_resources.get("gpu_backend", "none"),
            "gpu_note": runtime_resources.get("gpu_note", "sampling_pending"),
            "gpu_pipeline_ratio": runtime_resources.get("gpu_pipeline_ratio", 0.0),
            "gesture_scene_priority": self._runtime_tuning_snapshot.get("gesture_scene_priority"),
            "scene_min_single_signal_score": self._runtime_tuning_snapshot.get("scene_min_single_signal_score"),
            "face_hysteresis_threshold": self._runtime_tuning_snapshot.get("face_hysteresis_threshold"),
            "gesture_hysteresis_threshold": self._runtime_tuning_snapshot.get("gesture_hysteresis_threshold"),
            "gesture_cooldown_ms": self._runtime_tuning_snapshot.get("gesture_cooldown_ms"),
            "gaze_hysteresis_threshold": self._runtime_tuning_snapshot.get("gaze_hysteresis_threshold"),
            "audio_panns_threshold": self._runtime_tuning_snapshot.get("audio_panns_threshold"),
            "audio_vad_threshold": self._runtime_tuning_snapshot.get("audio_vad_threshold"),
            "motion_pixel_threshold": self._runtime_tuning_snapshot.get("motion_pixel_threshold"),
            "motion_min_area_ratio": self._runtime_tuning_snapshot.get("motion_min_area_ratio"),
            "error": self.last_error,
            "startup_state": self._startup_state,
            "startup_message": self._startup_message,
            "startup_elapsed_ms": startup_elapsed_ms,
        }

    def camera_jpeg(self, *, stream: str = "fast") -> bytes | None:
        with self._lock:
            if stream == "slow":
                cached = self._latest_slow_camera_jpeg
            else:
                cached = self._latest_fast_camera_jpeg
        return cached

def _apply_runtime_tuning(state: DashboardState, loop: LiveLoop, payload: dict[str, Any]) -> dict[str, Any]:
    applied: dict[str, Any] = {}
    if "reaction_hold_seconds" in payload:
        try:
            applied["reaction_hold_seconds"] = state.set_reaction_hold_seconds(
                float(payload["reaction_hold_seconds"])
            )
        except (TypeError, ValueError):
            pass

    if "fast_path_budget_ms" in payload:
        try:
            loop.fast_path_budget_ms = max(1.0, float(payload["fast_path_budget_ms"]))
            applied["fast_path_budget_ms"] = _round(loop.fast_path_budget_ms)
        except (TypeError, ValueError):
            pass

    if "async_perception_result_max_age_ms" in payload:
        try:
            loop.async_perception_result_max_age_ms = max(
                0.0,
                float(payload["async_perception_result_max_age_ms"]),
            )
            applied["async_perception_result_max_age_ms"] = _round(loop.async_perception_result_max_age_ms)
        except (TypeError, ValueError):
            pass

    if "pipeline_runtime_scale" in payload and hasattr(loop.registry, "set_runtime_scale"):
        scales = payload.get("pipeline_runtime_scale")
        if isinstance(scales, dict):
            applied_scales: dict[str, float] = {}
            for name, raw_scale in scales.items():
                try:
                    scale = max(0.0, float(raw_scale))
                except (TypeError, ValueError):
                    continue
                loop.registry.set_runtime_scale(str(name), scale)
                applied_scales[str(name)] = scale
            if applied_scales:
                applied["pipeline_runtime_scale"] = applied_scales

    stabilizer = _resolve_runtime_stabilizer(loop)
    if stabilizer is not None and hasattr(stabilizer, "update_event_override"):
        try:
            face_threshold = payload.get("face_hysteresis_threshold")
            if face_threshold is not None:
                resolved = float(face_threshold)
                stabilizer.update_event_override("familiar_face_detected", hysteresis_threshold=resolved)
                stabilizer.update_event_override("stranger_face_detected", hysteresis_threshold=resolved)
                applied["face_hysteresis_threshold"] = _round(resolved)
            if "gesture_hysteresis_threshold" in payload:
                resolved = float(payload["gesture_hysteresis_threshold"])
                stabilizer.update_event_override("gesture_detected", hysteresis_threshold=resolved)
                applied["gesture_hysteresis_threshold"] = _round(resolved)
            if "gesture_cooldown_ms" in payload:
                resolved = max(0.0, float(payload["gesture_cooldown_ms"]))
                stabilizer.update_event_override("gesture_detected", cooldown_ms=int(round(resolved)))
                applied["gesture_cooldown_ms"] = int(round(resolved))
            if "gaze_hysteresis_threshold" in payload:
                resolved = float(payload["gaze_hysteresis_threshold"])
                stabilizer.update_event_override("gaze_sustained_detected", hysteresis_threshold=resolved)
                applied["gaze_hysteresis_threshold"] = _round(resolved)
        except (TypeError, ValueError):
            pass

    aggregator = _resolve_runtime_aggregator(loop)
    if aggregator is not None and hasattr(aggregator, "update_runtime_tuning"):
        try:
            if "scene_min_single_signal_score" in payload:
                resolved = aggregator.update_runtime_tuning(
                    min_single_signal_score=float(payload["scene_min_single_signal_score"])
                )
                applied["scene_min_single_signal_score"] = _round(
                    resolved.get("min_single_signal_score", 0.0)
                )
        except (TypeError, ValueError):
            pass

    arbitrator = _resolve_runtime_arbitrator(loop)
    if arbitrator is not None and hasattr(arbitrator, "update_scene_priority"):
        try:
            if "gesture_scene_priority" in payload:
                scene_priority = arbitrator.update_scene_priority(
                    "gesture_bond_scene",
                    payload["gesture_scene_priority"],
                )
                if scene_priority is not None:
                    applied["gesture_scene_priority"] = scene_priority
        except (TypeError, ValueError):
            pass

    audio_detector = _resolve_audio_detector(loop)
    if audio_detector is not None and hasattr(audio_detector, "update_thresholds"):
        audio_kwargs: dict[str, float] = {}
        if "audio_rms_threshold" in payload:
            try:
                audio_kwargs["rms_threshold"] = max(0.0, float(payload["audio_rms_threshold"]))
            except (TypeError, ValueError):
                pass
        if "audio_db_threshold" in payload:
            try:
                audio_kwargs["db_threshold"] = float(payload["audio_db_threshold"])
            except (TypeError, ValueError):
                pass
        if "audio_panns_threshold" in payload:
            try:
                audio_kwargs["panns_confidence_threshold"] = max(0.0, float(payload["audio_panns_threshold"]))
            except (TypeError, ValueError):
                pass
        if "audio_vad_threshold" in payload:
            try:
                audio_kwargs["vad_threshold"] = max(0.0, float(payload["audio_vad_threshold"]))
            except (TypeError, ValueError):
                pass
        if audio_kwargs:
            try:
                applied.update(audio_detector.update_thresholds(**audio_kwargs))
            except Exception:
                logger.exception("failed to update runtime audio thresholds")

    motion_detector = _resolve_pipeline_detector(loop, "motion")
    if motion_detector is not None and hasattr(motion_detector, "update_thresholds"):
        motion_kwargs: dict[str, float] = {}
        if "motion_pixel_threshold" in payload:
            try:
                motion_kwargs["pixel_threshold"] = float(payload["motion_pixel_threshold"])
            except (TypeError, ValueError):
                pass
        if "motion_min_area_ratio" in payload:
            try:
                motion_kwargs["min_area_ratio"] = float(payload["motion_min_area_ratio"])
            except (TypeError, ValueError):
                pass
        if motion_kwargs:
            try:
                applied.update(motion_detector.update_thresholds(**motion_kwargs))
            except Exception:
                logger.exception("failed to update runtime motion thresholds")

    state.update_observability(loop, min_interval_s=0.0)
    return applied


def _make_handler(state: DashboardState, loop: LiveLoop, *, html: str) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            parsed = urlparse(self.path)
            if parsed.path == "/":
                payload = html.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path == "/api/state":
                data = json.dumps(state.public_snapshot(), ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parsed.path == "/api/state_full":
                data = json.dumps(state.snapshot(), ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parsed.path in {"/api/camera.jpg", "/api/camera_fast.jpg", "/api/camera_slow.jpg"}:
                stream = "slow" if parsed.path.endswith("_slow.jpg") else "fast"
                payload = state.camera_jpeg(stream=stream)
                if payload is None:
                    self.send_response(HTTPStatus.NO_CONTENT)
                    self.end_headers()
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            parsed = urlparse(self.path)
            if parsed.path != "/api/tuning":
                self.send_response(HTTPStatus.NOT_FOUND)
                self.end_headers()
                return

            raw_length = self.headers.get("Content-Length", "0")
            try:
                content_length = max(0, int(raw_length))
            except (TypeError, ValueError):
                content_length = 0
            try:
                body = self.rfile.read(content_length) if content_length > 0 else b"{}"
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("invalid tuning payload")
            except Exception as exc:
                data = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            applied = _apply_runtime_tuning(state, loop, payload)
            data = json.dumps(
                {
                    "ok": True,
                    "applied": applied,
                    "snapshot": state.snapshot(),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - stdlib API
            logger.debug("dashboard_http: " + format, *args)

    return DashboardHandler


def _dashboard_server_worker(server: ThreadingHTTPServer) -> None:
    try:
        server.serve_forever(poll_interval=0.5)
    except Exception:
        logger.exception("dashboard server failed")


def run_ui_dashboard(
    *,
    loop: LiveLoop,
    mode: str,
    current_profile: str = "unknown",
    detector_profile: str = "unknown",
    current_stabilizer: str = "unknown",
    host: str = "127.0.0.1",
    port: int = 8765,
    refresh_ms: int = 500,
    poll_interval_s: float = 1.0 / 30.0,
    duration_sec: int = 0,
) -> None:
    slow_frame_interval_s = 5.0
    try:
        slow_scene = getattr(loop.dependencies, "slow_scene", None)
        if slow_scene is not None and hasattr(slow_scene, "sample_interval_s"):
            slow_frame_interval_s = float(getattr(slow_scene, "sample_interval_s"))
    except Exception:
        slow_frame_interval_s = 5.0

    state = DashboardState(
        mode=mode,
        current_profile=current_profile,
        detector_profile=detector_profile,
        current_stabilizer=current_stabilizer,
        slow_frame_interval_s=slow_frame_interval_s,
    )
    html = build_dashboard_html(refresh_ms=max(120, int(refresh_ms)))
    handler = _make_handler(state, loop, html=html)
    server = ThreadingHTTPServer((host, int(port)), handler)
    server.timeout = 0.5
    server_thread = Thread(
        target=_dashboard_server_worker,
        args=(server,),
        daemon=True,
        name="robot-life-ui-http",
    )
    stop_event = Event()
    server_thread.start()

    logger.info("ui dashboard serving at http://%s:%s", host, port)
    deadline = monotonic() + duration_sec if duration_sec > 0 else None
    try:
        state.start_preview_worker()
        state.set_startup_state("initializing", "opening_sources_and_pipelines")
        loop.start()
        state.set_startup_state("running", "runtime_ready")
        state.update_observability(loop, min_interval_s=0.0)
        while not stop_event.is_set():
            started = monotonic()
            try:
                result = loop.run_once()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                state.set_error(f"运行时循环失败：{exc}")
                logger.exception("runtime loop failed")
                break
            latency_ms = (monotonic() - started) * 1000.0
            state.record_iteration(result, latency_ms=latency_ms)
            state.update_observability(loop)
            if deadline is not None and monotonic() >= deadline:
                break
            sleep_for = max(0.0, poll_interval_s - (latency_ms / 1000.0))
            if sleep_for > 0:
                stop_event.wait(sleep_for)
    except KeyboardInterrupt:
        logger.info("ui dashboard interrupted by user")
    except Exception as exc:
        state.set_startup_state("failed", f"startup_failed:{type(exc).__name__}")
        state.set_error(f"运行时启动失败：{exc}")
        raise
    finally:
        stop_event.set()
        state.stop_preview_worker()
        try:
            server.shutdown()
        except Exception:
            logger.exception("failed to stop dashboard server")
        server.server_close()
        server_thread.join(timeout=3.0)
        loop.stop()
