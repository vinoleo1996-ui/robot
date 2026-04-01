"""GGUF-based Qwen adapter for slow-scene multimodal understanding."""

from __future__ import annotations

import base64
import json
import logging
import os
from importlib import import_module
from pathlib import Path
from time import time
from typing import Any

from robot_life.common.cuda_runtime import ensure_cuda_runtime_loaded
from robot_life.common.schemas import SceneJson

try:  # pragma: no cover - optional runtime dependency
    import cv2 as _cv2
except Exception:  # pragma: no cover - optional runtime dependency
    _cv2 = None

try:  # pragma: no cover - optional runtime dependency
    import numpy as _np
except Exception:  # pragma: no cover - optional runtime dependency
    _np = None


class GGUFQwenVLAdapter:
    """Adapter using llama.cpp-compatible GGUF models for Qwen-style scene JSON output."""

    def __init__(self, model_path: str, config: dict[str, Any] | None = None) -> None:
        self.model_path = model_path
        self.config = config or {}
        self._logger = logging.getLogger(__name__)
        self._llm: Any = None
        self._model_file: Path | None = None
        self._mmproj_file: Path | None = None
        self._supports_vision = False
        self._initialized = False
        self._last_prompt: str | None = None
        self._last_output_text: str | None = None
        self._last_scene_json: dict[str, Any] | None = None
        self._last_elapsed_ms: float | None = None
        self._last_error: str | None = None
        self._last_finish_reason: str | None = None
        self._last_usage: dict[str, Any] | None = None
        self._llama_supports_gpu_offload: bool | None = None

    def initialize(self) -> None:
        if self._initialized:
            return

        require_gpu = bool(self.config.get("require_gpu", True))
        n_gpu_layers = int(self.config.get("n_gpu_layers", -1))
        if require_gpu or n_gpu_layers != 0:
            loaded, failed = ensure_cuda_runtime_loaded()
            self._logger.debug("GGUF CUDA bootstrap loaded=%d failed=%d", loaded, failed)

        try:
            llama_module = import_module("llama_cpp")
            Llama = getattr(llama_module, "Llama")
        except Exception as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError(
                "llama-cpp-python is required for GGUF slow-scene. "
                "Install with: pip install llama-cpp-python"
            ) from exc

        supports_gpu = bool(
            getattr(llama_module, "llama_supports_gpu_offload", lambda: False)()
        )
        self._llama_supports_gpu_offload = supports_gpu
        if require_gpu and not supports_gpu:
            raise RuntimeError(
                "GGUF adapter requires GPU offload, but current llama-cpp build does not support it"
            )
        if require_gpu and n_gpu_layers == 0:
            raise RuntimeError("GGUF adapter requires GPU but n_gpu_layers is set to 0")

        model_file, mmproj_file = self._resolve_paths(Path(self.model_path))
        self._model_file = model_file
        self._mmproj_file = mmproj_file

        n_threads_default = max(1, (os.cpu_count() or 2) // 2)
        init_kwargs: dict[str, Any] = {
            "model_path": str(model_file),
            "n_ctx": int(self.config.get("n_ctx", 4096)),
            "n_gpu_layers": int(self.config.get("n_gpu_layers", -1)),
            "n_threads": int(self.config.get("n_threads", n_threads_default)),
            "verbose": bool(self.config.get("verbose", False)),
        }

        # Some llama-cpp builds expose `mmproj`; older ones do not.
        if mmproj_file is not None:
            init_kwargs["mmproj"] = str(mmproj_file)

        try:
            self._llm = Llama(**init_kwargs)
            self._supports_vision = mmproj_file is not None
        except TypeError:
            init_kwargs.pop("mmproj", None)
            self._llm = Llama(**init_kwargs)
            self._supports_vision = False

        self._initialized = True
        self._logger.info(
            "Initialized GGUF adapter model=%s vision=%s mmproj=%s gpu=%s n_gpu_layers=%s",
            model_file,
            self._supports_vision,
            mmproj_file,
            supports_gpu,
            init_kwargs.get("n_gpu_layers"),
        )

    def understand_scene(
        self,
        image: Any,
        context: str | None = None,
        timeout_ms: int = 5000,
    ) -> SceneJson:
        if not self._initialized or self._llm is None:
            self._last_error = "model_not_initialized"
            return self._fallback_scene_json()

        prompt = self._build_prompt(context)
        self._last_prompt = prompt
        started_at = time()

        try:
            message: dict[str, Any]
            if image is not None and self._supports_vision:
                data_url = self._to_data_url(image)
                if data_url is None:
                    message = {"role": "user", "content": prompt}
                else:
                    message = {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    }
            else:
                message = {"role": "user", "content": prompt}

            max_tokens = int(self.config.get("max_new_tokens", 384))
            content, finish_reason, usage = self._run_chat_completion(
                messages=[message],
                max_tokens=max_tokens,
            )
            usage_entries: list[dict[str, Any]] = [usage] if isinstance(usage, dict) else []
            full_content = content

            continuation_enabled = bool(self.config.get("enable_continuation", True))
            max_continuations = max(0, int(self.config.get("max_continuations", 2)))
            continuation_tokens = int(self.config.get("continuation_max_new_tokens", max_tokens))
            if continuation_tokens <= 0:
                continuation_tokens = max_tokens

            if continuation_enabled and max_continuations > 0:
                turns: list[dict[str, Any]] = [message, {"role": "assistant", "content": content}]
                continuation_count = 0
                while (
                    finish_reason == "length"
                    and continuation_count < max_continuations
                    and self._extract_first_json_object(full_content) is None
                ):
                    turns.append(
                        {
                            "role": "user",
                            "content": (
                                "你上一次输出被截断。请从上次最后位置继续，"
                                "只输出剩余 JSON 片段，不要重复已有内容，不要解释。"
                            ),
                        }
                    )
                    more_content, finish_reason, more_usage = self._run_chat_completion(
                        messages=turns,
                        max_tokens=continuation_tokens,
                    )
                    full_content = self._append_continuation(full_content, more_content)
                    turns.append({"role": "assistant", "content": more_content})
                    if isinstance(more_usage, dict):
                        usage_entries.append(more_usage)
                    continuation_count += 1

            structured_retry_enabled = bool(self.config.get("enable_structured_retry", False))
            structured_retry_attempts = max(0, int(self.config.get("structured_retry_attempts", 1)))
            retry_tokens = int(self.config.get("structured_retry_max_new_tokens", max_tokens))
            if retry_tokens <= 0:
                retry_tokens = max_tokens
            retry_count = 0
            while structured_retry_enabled and retry_count < structured_retry_attempts:
                issues = self._validate_structured_json_text(full_content)
                if not issues:
                    break
                retry_prompt = (
                    "你刚才的JSON不合格，请完整重写一个全量JSON对象。"
                    "必须保持字段结构与模板完全一致，且所有字段必须有值，禁止空字符串。"
                    "不要解释，不要Markdown，只输出JSON。"
                    f" 需要修复的问题：{'; '.join(issues[:6])}"
                )
                retry_message = {
                    "role": "user",
                    "content": retry_prompt,
                }
                retry_content, finish_reason, retry_usage = self._run_chat_completion(
                    messages=[message, {"role": "assistant", "content": full_content}, retry_message],
                    max_tokens=retry_tokens,
                )
                full_content = retry_content
                if isinstance(retry_usage, dict):
                    usage_entries.append(retry_usage)
                retry_count += 1

            self._last_finish_reason = finish_reason
            self._last_usage = self._aggregate_usage(usage_entries)
            elapsed_ms = (time() - started_at) * 1000.0

            self._last_output_text = full_content
            self._last_elapsed_ms = float(elapsed_ms)
            if elapsed_ms > timeout_ms:
                self._last_error = f"timeout_{elapsed_ms:.0f}ms"
                return self._fallback_scene_json()

            scene_json = self._parse_scene_json(full_content)
            self._last_scene_json = {
                "scene_type": scene_json.scene_type,
                "confidence": scene_json.confidence,
                "involved_targets": list(scene_json.involved_targets),
                "emotion_hint": scene_json.emotion_hint,
                "urgency_hint": scene_json.urgency_hint,
                "recommended_strategy": scene_json.recommended_strategy,
                "escalate_to_cloud": scene_json.escalate_to_cloud,
            }
            if finish_reason == "length" and self._extract_first_json_object(full_content) is None:
                self._last_error = "completion_truncated_by_max_tokens"
            else:
                self._last_error = None
            return scene_json
        except Exception as exc:
            self._last_error = str(exc)
            self._logger.warning("GGUF scene understanding failed: %s", exc)
            return self._fallback_scene_json()

    def close(self) -> None:
        self._llm = None
        self._initialized = False

    def debug_last_io(self) -> dict[str, Any]:
        return {
            "model_path": self.model_path,
            "resolved_model_file": str(self._model_file) if self._model_file is not None else None,
            "resolved_mmproj_file": str(self._mmproj_file) if self._mmproj_file is not None else None,
            "vision_enabled": self._supports_vision,
            "gpu_offload_supported": self._llama_supports_gpu_offload,
            "last_prompt": self._last_prompt,
            "last_output_text": self._last_output_text,
            "last_scene_json": self._last_scene_json,
            "last_elapsed_ms": self._last_elapsed_ms,
            "last_finish_reason": self._last_finish_reason,
            "last_usage": self._last_usage,
            "last_error": self._last_error,
        }

    @staticmethod
    def _resolve_paths(model_path: Path) -> tuple[Path, Path | None]:
        if model_path.is_file() and model_path.suffix.lower() == ".gguf":
            return model_path, None

        if not model_path.is_dir():
            raise RuntimeError(f"GGUF model path not found: {model_path}")

        model_candidates = sorted(
            (
                item
                for item in model_path.iterdir()
                if item.is_file()
                and item.suffix.lower() == ".gguf"
                and "mmproj" not in item.name.lower()
            ),
            key=lambda item: item.stat().st_size,
            reverse=True,
        )
        if not model_candidates:
            raise RuntimeError(f"No .gguf model file found under: {model_path}")

        mmproj_candidates = sorted(
            (
                item
                for item in model_path.iterdir()
                if item.is_file()
                and item.suffix.lower() == ".gguf"
                and "mmproj" in item.name.lower()
            ),
            key=lambda item: item.stat().st_size,
            reverse=True,
        )
        mmproj = mmproj_candidates[0] if mmproj_candidates else None
        return model_candidates[0], mmproj

    @staticmethod
    def _extract_content(response: Any) -> str:
        if not isinstance(response, dict):
            return str(response)
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(str(part.get("text", "")))
                    else:
                        text_parts.append(str(part))
                return "\n".join(text_parts)
            return str(content)
        return str(response)

    def _run_chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> tuple[str, str | None, dict[str, Any] | None]:
        response = self._llm.create_chat_completion(
            messages=messages,
            temperature=float(self.config.get("temperature", 0.2)),
            top_p=float(self.config.get("top_p", 0.9)),
            max_tokens=int(max_tokens),
        )
        choices = response.get("choices", []) if isinstance(response, dict) else []
        first_choice = choices[0] if isinstance(choices, list) and choices else {}
        finish_reason = str(first_choice.get("finish_reason", "")).strip() if isinstance(first_choice, dict) else ""
        content = self._extract_content(response)
        usage = response.get("usage") if isinstance(response, dict) else None
        return content, (finish_reason or None), usage if isinstance(usage, dict) else None

    @staticmethod
    def _aggregate_usage(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not entries:
            return None
        total_prompt = 0
        total_completion = 0
        total_all = 0
        for item in entries:
            total_prompt += int(item.get("prompt_tokens", 0) or 0)
            total_completion += int(item.get("completion_tokens", 0) or 0)
            total_all += int(item.get("total_tokens", 0) or 0)
        return {
            "segments": len(entries),
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_all,
            "last_segment": entries[-1],
        }

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        source = str(text or "")
        start = source.find("{")
        if start < 0:
            return None

        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(source)):
            ch = source[index]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    return source[start : index + 1]
        return None

    @staticmethod
    def _append_continuation(existing: str, addition: str) -> str:
        base = str(existing or "")
        extra = str(addition or "").strip()
        if not extra:
            return base

        # If the new chunk itself is a complete JSON object, prefer it.
        extra_json = GGUFQwenVLAdapter._extract_first_json_object(extra)
        if extra_json is not None:
            return extra_json

        max_overlap = min(len(base), len(extra), 1024)
        for overlap in range(max_overlap, 0, -1):
            if base.endswith(extra[:overlap]):
                return base + extra[overlap:]
        return base + extra

    def _to_data_url(self, image: Any) -> str | None:
        if _cv2 is None or _np is None:
            return None
        if image is None or not isinstance(image, _np.ndarray):
            return None

        frame = image
        max_side = int(self.config.get("max_image_side", 640))
        if max_side > 0:
            h, w = frame.shape[:2]
            longest = max(h, w)
            if longest > max_side:
                ratio = max_side / float(longest)
                new_w = max(1, int(w * ratio))
                new_h = max(1, int(h * ratio))
                frame = _cv2.resize(frame, (new_w, new_h), interpolation=_cv2.INTER_AREA)

        ok, encoded = _cv2.imencode(".jpg", frame, [_cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return None
        b64 = base64.b64encode(encoded.tobytes()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"

    @staticmethod
    def _build_prompt(context: str | None = None) -> str:
        template = GGUFQwenVLAdapter._structured_scene_template()
        prompt = (
            "你在做家庭机器人主动交互策略判断。"
            "\n只输出一个JSON对象，字段与模板完全一致，禁止Markdown与解释。"
            "\n每个字段都必须填写，禁止空字符串；不确定时填写“未知”。"
            "\n核心门控：先判断画面里有没有可交互人，再决定是否说话。"
            "\n人员判断要保守：只有明确看到人体或人脸才写“是否在场=是”，否则写“否”。"
            "\n若无人或无人脸：是否说话=否；交互行为类型=环境观察；交互目标=无；后续跟进策略=继续观察。"
            "\n若有人但注意力低：优先非语言动作。"
            "\n若是否说话=否，话术模板也必须填写“保持静默观察”。"
            "\n禁止给出与当前画面无关的动作策略。"
            "\n请填写以下空JSON模板：\n"
            f"{json.dumps(template, ensure_ascii=False)}"
        )
        if context:
            prompt += f"\n补充上下文：{context}"
        return prompt

    @staticmethod
    def _parse_scene_json(model_output: str) -> SceneJson:
        try:
            payload = GGUFQwenVLAdapter._extract_first_json_object(model_output)
            if payload is not None:
                data = json.loads(payload)
                if isinstance(data, dict) and "元信息" in data and "场景信息" in data:
                    return GGUFQwenVLAdapter._parse_structured_scene_json(data)

                confidence = float(data.get("confidence", 0.5))
                return SceneJson(
                    scene_type=str(data.get("scene_type", "ambient_tracking_scene")),
                    confidence=confidence,
                    involved_targets=list(data.get("involved_targets", [])),
                    emotion_hint=str(data.get("emotion_hint", "neutral")),
                    urgency_hint=str(data.get("urgency_hint", "low")),
                    recommended_strategy=str(data.get("recommended_strategy", "nonverbal_first")),
                    escalate_to_cloud=confidence >= 0.8,
                )
        except Exception:
            pass
        return GGUFQwenVLAdapter._fallback_scene_json()

    @staticmethod
    def _structured_scene_template() -> dict[str, Any]:
        return {
            "元信息": {
                "事件ID": "",
                "时间戳": "",
                "画面来源": "",
                "运行模式": "",
            },
            "场景信息": {
                "房间类型": "",
                "子区域": "",
                "光照情况": "",
                "环境噪声等级": "",
                "电视状态": "",
                "音乐状态": "",
                "门状态": "",
                "人员活动密度": "",
                "场景稳定性": "",
            },
            "人员信息": [
                {
                    "人员ID": "",
                    "身份类型": "",
                    "是否在场": "",
                    "距离等级": "",
                    "相对位置": "",
                    "姿态": "",
                    "运动状态": "",
                    "对机器人的注意力": "",
                    "人脸是否可见": "",
                    "交互参与度": "",
                }
            ],
            "物体信息": [
                {
                    "物体名称": "",
                    "物体状态": "",
                    "重要性等级": "",
                }
            ],
            "事件信息": {
                "触发类型": "",
                "触发来源": "",
                "事件持续时长毫秒": "",
                "新颖性": "",
                "风险等级": "",
                "是否需要关注": "",
            },
            "交互上下文": {
                "用户可能意图": "",
                "可打扰程度": "",
                "是否安静时段": "",
                "是否隐私敏感": "",
                "近期相同交互次数": "",
                "冷却期是否生效": "",
            },
            "决策信息": {
                "是否说话": "",
                "说话优先级": "",
                "交互行为类型": "",
                "交互目标": "",
                "原因缩略": [""],
                "置信度": "",
            },
            "执行动作": {
                "话术模板": "",
                "非语言动作": "",
                "机器人运动动作": "",
                "后续跟进策略": "",
            },
        }

    @staticmethod
    def _parse_structured_scene_json(data: dict[str, Any]) -> SceneJson:
        decision = data.get("决策信息", {}) if isinstance(data, dict) else {}
        event_info = data.get("事件信息", {}) if isinstance(data, dict) else {}
        execution = data.get("执行动作", {}) if isinstance(data, dict) else {}
        people = data.get("人员信息", []) if isinstance(data, dict) else []

        behavior_text = str(decision.get("交互行为类型", "")).strip()
        scene_type = GGUFQwenVLAdapter._map_behavior_to_scene_type(behavior_text)

        confidence_raw = decision.get("决策置信度", decision.get("置信度", 0.5))
        confidence = GGUFQwenVLAdapter._coerce_float(confidence_raw, 0.5)

        risk_text = str(event_info.get("风险等级", "")).strip().lower()
        urgency = GGUFQwenVLAdapter._map_risk_to_urgency(risk_text)

        attention_text = ""
        involved_targets: list[str] = []
        if isinstance(people, list):
            for person in people:
                if not isinstance(person, dict):
                    continue
                person_id = str(person.get("人员ID", "")).strip()
                if person_id:
                    involved_targets.append(person_id)
                if not attention_text:
                    attention_text = str(person.get("对机器人的注意力", "")).strip().lower()
        emotion = GGUFQwenVLAdapter._map_attention_to_emotion(attention_text)

        strategy = str(execution.get("后续跟进策略", "")).strip()
        if not strategy:
            strategy = str(decision.get("交互行为类型", "")).strip() or "nonverbal_first"

        escalate = confidence >= 0.8 or urgency == "high"
        return SceneJson(
            scene_type=scene_type,
            confidence=confidence,
            involved_targets=involved_targets,
            emotion_hint=emotion,
            urgency_hint=urgency,
            recommended_strategy=strategy,
            escalate_to_cloud=escalate,
        )

    @staticmethod
    def _validate_structured_json_text(model_output: str) -> list[str]:
        payload = GGUFQwenVLAdapter._extract_first_json_object(str(model_output or ""))
        if payload is None:
            return ["未检测到JSON对象"]
        try:
            data = json.loads(payload)
        except Exception:
            return ["JSON解析失败"]
        if not isinstance(data, dict):
            return ["JSON顶层不是对象"]
        if not ("元信息" in data and "场景信息" in data):
            return []

        issues: list[str] = []
        template = GGUFQwenVLAdapter._structured_scene_template()
        GGUFQwenVLAdapter._walk_schema(template, data, "", issues)
        return issues

    @staticmethod
    def _walk_schema(
        template: Any,
        data: Any,
        prefix: str,
        issues: list[str],
    ) -> None:
        if isinstance(template, dict):
            if not isinstance(data, dict):
                issues.append(f"{prefix or 'root'} 类型错误，应为对象")
                return
            for key, value in template.items():
                path = f"{prefix}.{key}" if prefix else key
                if key not in data:
                    issues.append(f"{path} 缺失")
                    continue
                GGUFQwenVLAdapter._walk_schema(value, data.get(key), path, issues)
            return

        if isinstance(template, list):
            if not isinstance(data, list):
                issues.append(f"{prefix} 类型错误，应为数组")
                return
            if not data:
                issues.append(f"{prefix} 不能为空数组")
                return
            # 仅校验首个元素结构，避免过度约束长度。
            GGUFQwenVLAdapter._walk_schema(template[0], data[0], f"{prefix}[0]", issues)
            return

        if isinstance(data, str) and not data.strip():
            issues.append(f"{prefix} 为空字符串")
            return
        if data is None:
            issues.append(f"{prefix} 为空")

    @staticmethod
    def _coerce_float(value: Any, default: float) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip().replace("%", "")
            if stripped.endswith("分"):
                stripped = stripped[:-1]
            try:
                number = float(stripped)
                if number > 1.0:
                    return max(0.0, min(1.0, number / 100.0))
                return max(0.0, min(1.0, number))
            except Exception:
                return default
        return default

    @staticmethod
    def _map_behavior_to_scene_type(behavior_text: str) -> str:
        normalized = behavior_text.lower()
        if any(token in normalized for token in ("安全", "告警", "报警", "危险", "safety", "alert")):
            return "safety_alert_scene"
        if any(token in normalized for token in ("问候", "打招呼", "greeting")):
            return "greeting_scene"
        if any(token in normalized for token in ("手势", "gesture")):
            return "gesture_bond_scene"
        if any(token in normalized for token in ("关注", "注意", "attention")):
            return "attention_scene"
        return "ambient_tracking_scene"

    @staticmethod
    def _map_risk_to_urgency(risk_text: str) -> str:
        if any(token in risk_text for token in ("高", "high", "严重", "danger")):
            return "high"
        if any(token in risk_text for token in ("中", "medium")):
            return "medium"
        return "low"

    @staticmethod
    def _map_attention_to_emotion(attention_text: str) -> str:
        if any(token in attention_text for token in ("高", "注视", "聚焦", "engaged")):
            return "curious"
        if any(token in attention_text for token in ("低", "分散", "离开", "away")):
            return "neutral"
        return "unknown"

    @staticmethod
    def _fallback_scene_json() -> SceneJson:
        return SceneJson(
            scene_type="ambient_tracking_scene",
            confidence=0.0,
            involved_targets=[],
            emotion_hint="unknown",
            urgency_hint="low",
            recommended_strategy="nonverbal_first",
            escalate_to_cloud=False,
        )
