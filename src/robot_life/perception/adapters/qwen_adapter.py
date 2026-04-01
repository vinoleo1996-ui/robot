"""Qwen Vision-Language model integration for slow thinking."""

from __future__ import annotations

import json
import logging
from typing import Any

from robot_life.common.schemas import SceneJson

try:
    from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
    import torch
except ImportError:
    torch = None
    AutoProcessor = None
    Qwen2VLForConditionalGeneration = None


class QwenVLAdapter:
    """
    Adapter for Qwen3-VL or Qwen3.5-VL multimodal model.
    
    Used for slow thinking scene understanding.
    Generates structured Scene JSON from image context.
    """

    def __init__(self, model_path: str = "Qwen/Qwen2-VL-7B-Instruct", config: dict[str, Any] | None = None):
        """
        Initialize Qwen VL adapter.
        
        Args:
            model_path: HuggingFace model path or local path
            config: Configuration dict with params like device, dtype, etc.
        """
        if torch is None or AutoProcessor is None:
            raise RuntimeError("transformers and torch not installed. Install with: pip install torch transformers")

        self.model_path = model_path
        self.config = config or {}
        self._model = None
        self._processor = None
        self._require_gpu = bool(self.config.get("require_gpu", False))
        self._device = self.config.get("device", "cuda" if torch.cuda.is_available() else "cpu")
        if self._require_gpu and not torch.cuda.is_available():
            raise RuntimeError("Qwen adapter requires GPU but torch.cuda.is_available() is False")
        if isinstance(self._device, str) and self._device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(f"Qwen adapter configured device={self._device} but CUDA is unavailable")
        configured_dtype = self.config.get("dtype")
        if isinstance(configured_dtype, str):
            lowered = configured_dtype.strip().lower()
            if lowered in {"float16", "fp16", "half"}:
                configured_dtype = torch.float16
            elif lowered in {"float32", "fp32"}:
                configured_dtype = torch.float32
            elif lowered in {"bfloat16", "bf16"}:
                configured_dtype = torch.bfloat16
            else:
                configured_dtype = None
        self._dtype = configured_dtype or (torch.float16 if self._device == "cuda" else torch.float32)
        self._logger = logging.getLogger(__name__)
        self._last_prompt: str | None = None
        self._last_output_text: str | None = None
        self._last_scene_json: dict[str, Any] | None = None
        self._last_elapsed_ms: float | None = None
        self._last_error: str | None = None

    def initialize(self) -> None:
        """Load Qwen model and processor."""
        try:
            self._logger.info(f"Loading Qwen from {self.model_path}...")

            self._processor = AutoProcessor.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                cache_dir=self.config.get("cache_dir")
            )

            self._model = Qwen2VLForConditionalGeneration.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                torch_dtype=self._dtype,
                device_map=self._device,
                cache_dir=self.config.get("cache_dir")
            )

            # Set to eval mode
            self._model.eval()

            self._logger.info(f"Qwen loaded on {self._device} with dtype {self._dtype}")

        except Exception as e:
            self._logger.error(f"Failed to load Qwen model: {e}")
            raise

    def understand_scene(
        self,
        image: Any,
        context: str | None = None,
        timeout_ms: int = 5000,
    ) -> SceneJson:
        """
        Understand scene from image with optional context.
        
        Args:
            image: Input image (PIL Image or numpy array)
            context: Optional text context about the scene
            timeout_ms: Timeout for inference
            
        Returns:
            SceneJson with scene understanding
        """
        if self._model is None or self._processor is None:
            self._last_prompt = context or ""
            self._last_output_text = None
            self._last_scene_json = None
            self._last_elapsed_ms = None
            self._last_error = "model_not_initialized"
            return self._fallback_scene_json()

        try:
            import time
            start_time = time.time()

            # Build prompt
            prompt = self._build_prompt(context)
            self._last_prompt = prompt

            # Process image and text
            inputs = self._processor(
                text=prompt,
                images=[image],
                padding=True,
                return_tensors="pt"
            )

            # Move to device
            inputs = {k: v.to(self._device) if isinstance(v, torch.Tensor) else v 
                     for k, v in inputs.items()}

            # Generate understanding
            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=512,
                    temperature=0.7,
                    top_p=0.9,
                )

            # Decode output
            generated_text = self._processor.batch_decode(outputs, skip_special_tokens=True)[0]
            elapsed_ms = (time.time() - start_time) * 1000
            self._last_output_text = generated_text
            self._last_elapsed_ms = float(elapsed_ms)

            # Check timeout
            if elapsed_ms > timeout_ms:
                self._logger.warning(f"Scene understanding timeout: {elapsed_ms:.0f}ms > {timeout_ms}ms")
                self._last_error = f"timeout_{elapsed_ms:.0f}ms"
                return self._fallback_scene_json()

            # Parse scene JSON from model output
            scene_json = self._parse_scene_json(generated_text)
            self._last_scene_json = {
                "scene_type": scene_json.scene_type,
                "confidence": scene_json.confidence,
                "involved_targets": list(scene_json.involved_targets),
                "emotion_hint": scene_json.emotion_hint,
                "urgency_hint": scene_json.urgency_hint,
                "recommended_strategy": scene_json.recommended_strategy,
                "escalate_to_cloud": scene_json.escalate_to_cloud,
            }
            self._last_error = None

            return scene_json

        except Exception as e:
            self._logger.error(f"Scene understanding error: {e}")
            self._last_error = str(e)
            return self._fallback_scene_json()

    def _build_prompt(self, context: str | None = None) -> str:
        """Build prompt for scene understanding."""
        base_prompt = """Analyze this image and provide scene understanding in the following JSON format:
        {
            "scene_type": "one of [greeting_scene, attention_scene, safety_alert, gesture_bond, ambient_tracking]",
            "confidence": 0.0-1.0,
            "involved_targets": ["person", "object"],
            "emotion_hint": "neutral/happy/curious/alert",
            "urgency_hint": "low/medium/high",
            "recommended_strategy": "nonverbal_first/cautious/alert"
        }
        
        Respond with ONLY the JSON, no other text.
        """

        if context:
            base_prompt += f"\nContext: {context}"

        return base_prompt

    @staticmethod
    def _parse_scene_json(model_output: str) -> SceneJson:
        """Parse scene JSON from model output."""
        try:
            # Try to extract JSON from output
            import re
            json_match = re.search(r'\{.*\}', model_output, re.DOTALL)
            if json_match:
                scene_dict = json.loads(json_match.group())
                return SceneJson(
                    scene_type=scene_dict.get("scene_type", "ambient_tracking"),
                    confidence=float(scene_dict.get("confidence", 0.5)),
                    involved_targets=scene_dict.get("involved_targets", []),
                    emotion_hint=scene_dict.get("emotion_hint", "neutral"),
                    urgency_hint=scene_dict.get("urgency_hint", "low"),
                    recommended_strategy=scene_dict.get("recommended_strategy", "nonverbal_first"),
                    escalate_to_cloud=float(scene_dict.get("confidence", 0.5)) >= 0.8,
                )
        except Exception:
            pass

        # Fallback
        return SceneJson(
            scene_type="ambient_tracking",
            confidence=0.5,
            involved_targets=[],
            emotion_hint="neutral",
            urgency_hint="low",
            recommended_strategy="nonverbal_first",
            escalate_to_cloud=False,
        )

    @staticmethod
    def _fallback_scene_json() -> SceneJson:
        """Return fallback scene JSON when model unavailable."""
        return SceneJson(
            scene_type="ambient_tracking",
            confidence=0.0,
            involved_targets=[],
            emotion_hint="unknown",
            urgency_hint="low",
            recommended_strategy="nonverbal_first",
            escalate_to_cloud=False,
        )

    def close(self) -> None:
        """Cleanup model resources."""
        if self._model:
            del self._model
            self._model = None
        if self._processor:
            del self._processor
            self._processor = None

        if torch and self._device == "cuda":
            torch.cuda.empty_cache()

    def debug_last_io(self) -> dict[str, Any]:
        return {
            "model_path": self.model_path,
            "device": self._device,
            "last_prompt": self._last_prompt,
            "last_output_text": self._last_output_text,
            "last_scene_json": self._last_scene_json,
            "last_elapsed_ms": self._last_elapsed_ms,
            "last_error": self._last_error,
        }
