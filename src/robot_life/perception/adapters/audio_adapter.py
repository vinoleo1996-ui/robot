"""Lightweight audio detector based on RMS / dB thresholding."""

from __future__ import annotations

import logging
import math
from time import monotonic, time
from typing import Any

from robot_life.common.schemas import DetectionResult
from robot_life.common.tracing import new_trace_id
from robot_life.perception.base import DetectorBase

try:
    import numpy as _np
except ImportError:  # pragma: no cover - optional dependency
    _np = None

logger = logging.getLogger(__name__)


class RMSLoudSoundDetector(DetectorBase):
    """Detect loud sounds from audio chunks using RMS/dB thresholds."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__("rms_audio", "microphone", config)
        self._rms_threshold: float | None = self._read_optional_float("rms_threshold", 0.15)
        db_default = self.config.get("energy_threshold_db")
        self._db_threshold: float | None = self._read_optional_float("db_threshold", db_default)
        if self._db_threshold is not None and self._db_threshold > 0.0:
            logger.warning(
                "rms_audio db_threshold=%s is above 0 dBFS for normalized audio; "
                "ignoring db threshold and falling back to rms_threshold",
                self._db_threshold,
            )
            self._db_threshold = None
        self._cooldown_s = max(
            0.0,
            float(self.config.get("cooldown_s", self.config.get("global_cooldown_sec", 0.5))),
        )
        self._threshold_mode = str(self.config.get("threshold_mode", "all")).strip().lower()
        self._relative_multiplier = max(0.0, float(self.config.get("relative_multiplier", 0.0)))
        self._relative_min_rms = max(0.0, float(self.config.get("relative_min_rms", 0.02)))
        self._relative_baseline_floor = max(1e-6, float(self.config.get("relative_baseline_floor", 0.005)))
        self._baseline_alpha = min(1.0, max(0.01, float(self.config.get("baseline_alpha", 0.12))))
        min_samples_default = self.config.get("min_samples")
        if min_samples_default is None:
            frame_length = self.config.get("frame_length")
            sample_rate = self.config.get("sample_rate")
            if frame_length is not None and sample_rate is not None:
                try:
                    min_samples_default = max(1, int(float(frame_length) * float(sample_rate)))
                except (TypeError, ValueError):
                    min_samples_default = 1
            else:
                min_samples_default = 1
        self._min_samples = max(1, int(min_samples_default))
        self._last_trigger_monotonic = float("-inf")
        self._clock = monotonic
        self._timestamp_fn = time
        self._db_floor_rms = 1e-12
        self._baseline_rms: float | None = None

    def initialize(self) -> None:
        self._initialized = True

    def process(self, frame: Any) -> list[DetectionResult]:
        if not self._initialized:
            return []

        samples = self._extract_samples(frame)
        if samples is None:
            return []

        sample_count = self._sample_count(samples)
        if sample_count < self._min_samples:
            return []

        rms, db = self._compute_rms_db(samples)
        baseline_rms = self._baseline_rms if self._baseline_rms is not None else max(rms, self._relative_baseline_floor)
        absolute_trigger = self._passes_threshold(rms, db)
        relative_trigger = self._passes_relative_threshold(rms, baseline_rms)
        triggered = absolute_trigger or relative_trigger
        self._update_baseline(rms=rms, triggered=triggered)
        if not triggered:
            return []

        now_mono = self._clock()
        if now_mono - self._last_trigger_monotonic < self._cooldown_s:
            return []
        self._last_trigger_monotonic = now_mono

        confidence = self._compute_confidence(rms, db)
        detection = DetectionResult(
            trace_id=new_trace_id(),
            source=self.source,
            detector=self.name,
            event_type="loud_sound",
            timestamp=self._timestamp_fn(),
            confidence=confidence,
            payload={
                "rms": rms,
                "db": db,
                "rms_threshold": self._rms_threshold,
                "db_threshold": self._db_threshold,
                "threshold_mode": self._threshold_mode,
                "sample_count": sample_count,
                "relative_multiplier": self._relative_multiplier if self._relative_multiplier > 0 else None,
                "relative_triggered": bool(relative_trigger),
                "baseline_rms": self._baseline_rms,
            },
        )
        return [detection]

    def close(self) -> None:
        self._initialized = False

    def update_thresholds(
        self,
        *,
        rms_threshold: float | None = None,
        db_threshold: float | None = None,
    ) -> dict[str, float | None]:
        """Update loud-sound thresholds at runtime for local tuning."""

        if rms_threshold is not None:
            self._rms_threshold = max(0.0, float(rms_threshold))
            self.config["rms_threshold"] = self._rms_threshold

        if db_threshold is not None:
            resolved_db = float(db_threshold)
            if resolved_db > 0.0:
                logger.warning(
                    "rms_audio runtime db_threshold=%s is above 0 dBFS; "
                    "ignoring db threshold and keeping previous value=%s",
                    resolved_db,
                    self._db_threshold,
                )
            else:
                self._db_threshold = resolved_db
                self.config["db_threshold"] = self._db_threshold
                self.config["energy_threshold_db"] = self._db_threshold

        return {
            "rms_threshold": self._rms_threshold,
            "db_threshold": self._db_threshold,
        }

    def _read_optional_float(self, key: str, default: float | None) -> float | None:
        raw = self.config.get(key, default)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _flatten_numeric(values: list | tuple) -> list[float]:
        result: list[float] = []
        stack: list[Any] = [values]
        while stack:
            current = stack.pop()
            if isinstance(current, (list, tuple)):
                for item in reversed(current):
                    stack.append(item)
                continue
            try:
                value = float(current)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                result.append(value)
        return result

    def _extract_samples(self, frame: Any) -> Any | None:
        if frame is None:
            return None

        candidate = frame
        if isinstance(frame, dict):
            for key in ("audio", "samples", "chunk", "data"):
                if key in frame:
                    candidate = frame[key]
                    break
            else:
                return None

        if _np is not None and isinstance(candidate, _np.ndarray):
            try:
                array = _np.asarray(candidate, dtype=_np.float64).reshape(-1)
            except Exception:
                return None
            return array if array.size > 0 else None

        if isinstance(candidate, (list, tuple)):
            if _np is not None:
                try:
                    array = _np.asarray(candidate, dtype=_np.float64).reshape(-1)
                    return array if array.size > 0 else None
                except Exception:
                    pass
            flat = self._flatten_numeric(candidate)
            return flat if flat else None

        return None

    @staticmethod
    def _sample_count(samples: Any) -> int:
        if _np is not None and isinstance(samples, _np.ndarray):
            return int(samples.size)
        return len(samples)

    def _compute_rms_db(self, samples: Any) -> tuple[float, float]:
        if _np is not None and isinstance(samples, _np.ndarray):
            rms = float(_np.sqrt(_np.mean(_np.square(samples))))
        else:
            sum_sq = 0.0
            count = 0
            for value in samples:
                value_f = float(value)
                sum_sq += value_f * value_f
                count += 1
            if count == 0:
                return 0.0, -120.0
            rms = math.sqrt(sum_sq / count)

        db = 20.0 * math.log10(max(rms, self._db_floor_rms))
        return rms, db

    def _passes_threshold(self, rms: float, db: float) -> bool:
        checks: list[bool] = []
        if self._rms_threshold is not None:
            checks.append(rms >= self._rms_threshold)
        if self._db_threshold is not None:
            checks.append(db >= self._db_threshold)
        if not checks:
            return False
        if self._threshold_mode in {"any", "or"}:
            return any(checks)
        return all(checks)

    def _passes_relative_threshold(self, rms: float, baseline_rms: float) -> bool:
        if self._relative_multiplier <= 0:
            return False
        dynamic_floor = max(self._relative_baseline_floor, baseline_rms)
        return rms >= self._relative_min_rms and rms >= (dynamic_floor * self._relative_multiplier)

    def _update_baseline(self, *, rms: float, triggered: bool) -> None:
        if self._baseline_rms is None:
            self._baseline_rms = max(rms, self._relative_baseline_floor)
            return
        # Keep baseline stable: when triggered, avoid immediately learning the peak.
        sampled_rms = rms if not triggered else min(rms, self._baseline_rms * 1.1)
        self._baseline_rms = max(
            self._relative_baseline_floor,
            ((1.0 - self._baseline_alpha) * self._baseline_rms) + (self._baseline_alpha * sampled_rms),
        )

    def _compute_confidence(self, rms: float, db: float) -> float:
        scores: list[float] = []

        if self._rms_threshold is not None and self._rms_threshold > 0:
            scores.append(rms / self._rms_threshold)

        if self._db_threshold is not None:
            scores.append(10.0 ** ((db - self._db_threshold) / 20.0))

        ratio = max(scores) if scores else 1.0
        confidence = max(0.0, min(1.0, ratio / 2.0))
        return float(confidence)
