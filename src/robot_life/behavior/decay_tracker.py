# Behavior Decay & Randomness Tracker

from __future__ import annotations

import random
from collections import defaultdict
from time import monotonic


class BehaviorDecayTracker:
    """Track repeated interactions to implement response decay and randomness.

    PRD §5.1: "同人同场景反应强度逐渐降低", "30%+ 场景仅做非语音反馈".

    For the same (scene_type, target_id) pair, the tracker:
    1. Counts how many times we've responded within a decay window.
    2. Returns a ``strength`` multiplier (1.0 → 0.3) that decays with repetition.
    3. Recommends whether to use voice or silent (visual-only) feedback.
    """

    def __init__(
        self,
        *,
        decay_window_s: float = 300.0,  # 5-minute window
        max_decay_count: int = 5,       # After 5 repeats, minimum strength
        min_strength: float = 0.3,
        silent_probability_base: float = 0.3,
    ) -> None:
        self.decay_window_s = float(decay_window_s)
        self.max_decay_count = max(1, int(max_decay_count))
        self.min_strength = float(min_strength)
        self.silent_probability_base = float(silent_probability_base)
        # (scene_type, target_key) -> list of execution timestamps
        self._history: dict[tuple[str, str], list[float]] = defaultdict(list)

    def evaluate(
        self,
        scene_type: str,
        target_id: str | None,
    ) -> tuple[float, bool]:
        """Return ``(strength, use_voice)``.

        - ``strength``: 1.0 (first encounter) → ``min_strength`` (repeated).
        - ``use_voice``: True = full multimodal, False = visual-only.
        """
        now = monotonic()
        key = (scene_type, target_id or "__any__")
        self._prune(key, now)
        count = len(self._history[key])

        # Decay strength linearly.
        decay_ratio = min(count / self.max_decay_count, 1.0)
        strength = 1.0 - (1.0 - self.min_strength) * decay_ratio

        # Silent probability increases with repetition.
        silent_p = self.silent_probability_base + (decay_ratio * 0.4)
        use_voice = random.random() > silent_p

        return strength, use_voice

    def record(self, scene_type: str, target_id: str | None) -> None:
        now = monotonic()
        key = (scene_type, target_id or "__any__")
        self._history[key].append(now)

    def reset(self) -> None:
        self._history.clear()

    def _prune(self, key: tuple[str, str], now: float) -> None:
        cutoff = now - self.decay_window_s
        self._history[key] = [t for t in self._history[key] if t > cutoff]
