from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass

from robot_life.common.config import StabilizerConfig, StabilizerEventOverride
from robot_life.common.schemas import RawEvent, StableEvent, new_id, now_mono


@dataclass(frozen=True)
class _ResolvedRules:
    debounce_count: int
    debounce_window_s: float
    cooldown_s: float
    hysteresis_threshold: float
    dedup_window_s: float
    ttl_override_ms: int | None


class EventStabilizer:
    """Debounce + hysteresis + dedup + cooldown + TTL for detector events."""

    def __init__(
        self,
        debounce_count: int = 2,
        debounce_window_ms: int = 300,
        cooldown_ms: int = 1000,
        hysteresis_threshold: float = 0.7,
        *,
        hysteresis_transition_high: float = 0.85,
        hysteresis_transition_low: float = 0.6,
        dedup_window_ms: int = 500,
        default_ttl_ms: int = 3_000,
        event_overrides: dict[str, StabilizerEventOverride] | None = None,
    ) -> None:
        self.debounce_count = max(1, int(debounce_count))
        self.debounce_window_s = max(0.0, debounce_window_ms / 1000.0)
        self.cooldown_s = max(0.0, cooldown_ms / 1000.0)
        self.hysteresis_threshold = float(hysteresis_threshold)
        self.hysteresis_transition_high = float(hysteresis_transition_high)
        self.hysteresis_transition_low = float(hysteresis_transition_low)
        self.dedup_window_s = max(0.0, dedup_window_ms / 1000.0)
        self.default_ttl_ms = max(1, int(default_ttl_ms))
        self._event_overrides = dict(event_overrides or {})

        # Debounce state: key -> (count, first_time)
        self._debounce_state: dict[str, tuple[int, float]] = {}
        # Hysteresis state: key -> last_stable_confidence
        self._hysteresis_state: dict[str, float] = {}
        # Cooldown state: key -> last_emission_time
        self._cooldown_state: dict[str, float] = defaultdict(float)
        # Dedup state: key -> last_seen_time
        self._dedup_window: dict[str, float] = {}
        # GC bookkeeping
        self._gc_call_count = 0
        self._gc_last_at = 0.0
        self._gc_interval_calls = 100
        self._gc_interval_s = 10.0
        # Lightweight observability counters.
        self._stats_total: dict[str, int] = {
            "input": 0,
            "emitted": 0,
            "filtered_ttl": 0,
            "filtered_debounce": 0,
            "filtered_hysteresis": 0,
            "filtered_dedup": 0,
            "filtered_cooldown": 0,
        }
        self._stats_by_event: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "input": 0,
                "emitted": 0,
                "filtered_ttl": 0,
                "filtered_debounce": 0,
                "filtered_hysteresis": 0,
                "filtered_dedup": 0,
                "filtered_cooldown": 0,
            }
        )

    @classmethod
    def from_config(cls, config: StabilizerConfig) -> "EventStabilizer":
        return cls(
            debounce_count=config.debounce_count,
            debounce_window_ms=config.debounce_window_ms,
            cooldown_ms=config.cooldown_ms,
            hysteresis_threshold=config.hysteresis_threshold,
            hysteresis_transition_high=config.hysteresis_transition_high,
            hysteresis_transition_low=config.hysteresis_transition_low,
            dedup_window_ms=config.dedup_window_ms,
            default_ttl_ms=config.default_ttl_ms,
            event_overrides=config.event_overrides,
        )

    def process(self, raw_event: RawEvent) -> StableEvent | None:
        now = now_mono()
        self._gc_stale_state(now)
        self._inc_stats(raw_event.event_type, "input")
        rules = self._resolve_rules(raw_event.event_type)
        ttl_ms = self._resolve_ttl_ms(raw_event, rules)
        ttl_s = ttl_ms / 1000.0

        if now > raw_event.timestamp_monotonic + ttl_s:
            self._inc_stats(raw_event.event_type, "filtered_ttl")
            return None

        if self._check_debounce(raw_event.cooldown_key, now, rules) is None:
            self._inc_stats(raw_event.event_type, "filtered_debounce")
            return None
        stabilized_by = ["debounce"]

        if not self._check_hysteresis(raw_event.cooldown_key, raw_event.confidence, rules):
            self._inc_stats(raw_event.event_type, "filtered_hysteresis")
            return None
        stabilized_by.append("hysteresis")

        if not self._check_dedup(raw_event, now, rules):
            self._inc_stats(raw_event.event_type, "filtered_dedup")
            return None
        stabilized_by.append("dedup")

        if not self._check_cooldown(raw_event.cooldown_key, now, rules):
            self._inc_stats(raw_event.event_type, "filtered_cooldown")
            return None
        stabilized_by.append("cooldown")

        stable_event = StableEvent(
            stable_event_id=new_id(),
            base_event_id=raw_event.event_id,
            trace_id=raw_event.trace_id,
            event_type=raw_event.event_type,
            priority=raw_event.priority,
            valid_until_monotonic=now + ttl_s,
            stabilized_by=stabilized_by,
            payload=raw_event.payload,
        )
        self._cooldown_state[raw_event.cooldown_key] = now
        self._inc_stats(raw_event.event_type, "emitted")
        return stable_event

    def _resolve_rules(self, event_type: str) -> _ResolvedRules:
        override = self._event_overrides.get(event_type)
        return _ResolvedRules(
            debounce_count=_pick_int(override, "debounce_count", self.debounce_count, minimum=1),
            debounce_window_s=_pick_ms(override, "debounce_window_ms", self.debounce_window_s),
            cooldown_s=_pick_ms(override, "cooldown_ms", self.cooldown_s),
            hysteresis_threshold=_pick_float(
                override, "hysteresis_threshold", self.hysteresis_threshold
            ),
            dedup_window_s=_pick_ms(override, "dedup_window_ms", self.dedup_window_s),
            ttl_override_ms=_pick_optional_int(override, "ttl_ms"),
        )

    def _resolve_ttl_ms(self, raw_event: RawEvent, rules: _ResolvedRules) -> int:
        if rules.ttl_override_ms is not None:
            return max(1, rules.ttl_override_ms)
        if raw_event.ttl_ms > 0:
            return raw_event.ttl_ms
        return self.default_ttl_ms

    def _check_debounce(self, key: str, now: float, rules: _ResolvedRules) -> bool | None:
        if rules.debounce_count <= 1:
            return True

        state = self._debounce_state.get(key)
        if state is None:
            self._debounce_state[key] = (1, now)
            return None

        count, first_time = state
        if rules.debounce_window_s <= 0 or (now - first_time) <= rules.debounce_window_s:
            new_count = count + 1
            if new_count >= rules.debounce_count:
                self._debounce_state.pop(key, None)
                return True
            self._debounce_state[key] = (new_count, first_time)
            return None

        self._debounce_state[key] = (1, now)
        return None

    def _check_hysteresis(self, key: str, confidence: float, rules: _ResolvedRules) -> bool:
        last_confidence = self._hysteresis_state.get(key)
        if last_confidence is None:
            self._hysteresis_state[key] = confidence
            return confidence >= rules.hysteresis_threshold

        effective_threshold = rules.hysteresis_threshold
        if last_confidence < rules.hysteresis_threshold and confidence < self.hysteresis_transition_high:
            effective_threshold = self.hysteresis_transition_high
        elif (
            last_confidence >= rules.hysteresis_threshold
            and confidence < self.hysteresis_transition_low
        ):
            effective_threshold = self.hysteresis_transition_low

        passes = confidence >= effective_threshold
        if passes:
            self._hysteresis_state[key] = confidence
        return passes

    def _check_dedup(self, raw_event: RawEvent, now: float, rules: _ResolvedRules) -> bool:
        if rules.dedup_window_s <= 0:
            return True

        expire_before = now - rules.dedup_window_s
        expired = [key for key, seen_at in self._dedup_window.items() if seen_at < expire_before]
        for key in expired:
            self._dedup_window.pop(key, None)

        dedup_key = f"{raw_event.cooldown_key}:{self._hash_payload(raw_event.payload)}"
        if dedup_key in self._dedup_window:
            return False

        self._dedup_window[dedup_key] = now
        return True

    def _check_cooldown(self, key: str, now: float, rules: _ResolvedRules) -> bool:
        if rules.cooldown_s <= 0:
            return True

        last_emission = self._cooldown_state.get(key)
        if last_emission is None:
            return True
        return (now - last_emission) >= rules.cooldown_s

    @staticmethod
    def _hash_payload(payload: dict) -> int:
        try:
            serialized = json.dumps(payload, sort_keys=True, default=str)
        except (TypeError, ValueError):
            serialized = str(payload)
        return hash(serialized)

    def reset(self, cooldown_key: str | None = None) -> None:
        if cooldown_key is None:
            self._debounce_state.clear()
            self._hysteresis_state.clear()
            self._cooldown_state.clear()
            self._dedup_window.clear()
            return

        self._debounce_state.pop(cooldown_key, None)
        self._hysteresis_state.pop(cooldown_key, None)
        self._cooldown_state.pop(cooldown_key, None)

    def update_event_override(self, event_type: str, **kwargs: object) -> dict[str, object]:
        event_key = str(event_type or "").strip()
        if not event_key:
            return {}
        current = self._event_overrides.get(event_key)
        payload = current.model_dump() if current is not None else {}
        allowed_keys = {
            "cooldown_ms",
            "debounce_count",
            "debounce_window_ms",
            "hysteresis_threshold",
            "dedup_window_ms",
            "ttl_ms",
        }
        for key, value in kwargs.items():
            if key not in allowed_keys or value is None:
                continue
            payload[key] = value
        override = StabilizerEventOverride.model_validate(payload)
        self._event_overrides[event_key] = override
        return override.model_dump(exclude_none=True)

    def snapshot_config(self) -> dict[str, object]:
        return {
            "debounce_count": self.debounce_count,
            "debounce_window_ms": int(round(self.debounce_window_s * 1000.0)),
            "cooldown_ms": int(round(self.cooldown_s * 1000.0)),
            "hysteresis_threshold": self.hysteresis_threshold,
            "hysteresis_transition_high": self.hysteresis_transition_high,
            "hysteresis_transition_low": self.hysteresis_transition_low,
            "dedup_window_ms": int(round(self.dedup_window_s * 1000.0)),
            "default_ttl_ms": self.default_ttl_ms,
            "event_overrides": {
                event_type: override.model_dump(exclude_none=True)
                for event_type, override in self._event_overrides.items()
            },
        }

    def snapshot_stats(self) -> dict:
        totals = dict(self._stats_total)
        totals["filtered_total"] = (
            totals["filtered_ttl"]
            + totals["filtered_debounce"]
            + totals["filtered_hysteresis"]
            + totals["filtered_dedup"]
            + totals["filtered_cooldown"]
        )
        totals["pass_rate"] = (
            float(totals["emitted"]) / float(totals["input"]) if totals["input"] > 0 else 0.0
        )

        by_event: dict[str, dict] = {}
        for event_type, counters in self._stats_by_event.items():
            item = dict(counters)
            item["filtered_total"] = (
                item["filtered_ttl"]
                + item["filtered_debounce"]
                + item["filtered_hysteresis"]
                + item["filtered_dedup"]
                + item["filtered_cooldown"]
            )
            item["pass_rate"] = float(item["emitted"]) / float(item["input"]) if item["input"] > 0 else 0.0
            by_event[event_type] = item

        return {
            "totals": totals,
            "by_event": by_event,
            "state_sizes": {
                "debounce": len(self._debounce_state),
                "hysteresis": len(self._hysteresis_state),
                "cooldown": len(self._cooldown_state),
                "dedup": len(self._dedup_window),
            },
        }

    def _gc_stale_state(self, now: float) -> None:
        """Periodically purge stale internal state to prevent unbounded memory growth."""
        self._gc_call_count += 1
        elapsed_since_gc = now - self._gc_last_at if self._gc_last_at > 0 else float("inf")
        if self._gc_call_count < self._gc_interval_calls and elapsed_since_gc < self._gc_interval_s:
            return

        self._gc_call_count = 0
        self._gc_last_at = now

        # Max staleness: 5× the largest window we use.
        max_debounce_age = max(self.debounce_window_s * 5, 30.0)
        stale_debounce = [
            k for k, (_, first_time) in self._debounce_state.items()
            if (now - first_time) > max_debounce_age
        ]
        for k in stale_debounce:
            self._debounce_state.pop(k, None)

        max_cooldown_age = max(self.cooldown_s * 5, 60.0)
        stale_cooldown = [
            k for k, last_emit in self._cooldown_state.items()
            if last_emit > 0 and (now - last_emit) > max_cooldown_age
        ]
        for k in stale_cooldown:
            self._cooldown_state.pop(k, None)

        max_hysteresis_age = max(self.debounce_window_s * 10, 60.0)
        stale_hysteresis = [
            k for k in self._hysteresis_state
            if k not in self._debounce_state and k not in self._cooldown_state
        ]
        for k in stale_hysteresis:
            self._hysteresis_state.pop(k, None)

        max_dedup_age = max(self.dedup_window_s * 3, 10.0)
        stale_dedup = [
            k for k, last_seen in self._dedup_window.items()
            if (now - last_seen) > max_dedup_age
        ]
        for k in stale_dedup:
            self._dedup_window.pop(k, None)

    def _inc_stats(self, event_type: str, key: str) -> None:
        if key in self._stats_total:
            self._stats_total[key] += 1
        self._stats_by_event[event_type][key] += 1


def _pick_int(
    override: StabilizerEventOverride | None,
    attr: str,
    fallback: int,
    *,
    minimum: int = 0,
) -> int:
    if override is None:
        return max(minimum, int(fallback))
    value = getattr(override, attr)
    if value is None:
        return max(minimum, int(fallback))
    return max(minimum, int(value))


def _pick_float(override: StabilizerEventOverride | None, attr: str, fallback: float) -> float:
    if override is None:
        return float(fallback)
    value = getattr(override, attr)
    if value is None:
        return float(fallback)
    return float(value)


def _pick_optional_int(override: StabilizerEventOverride | None, attr: str) -> int | None:
    if override is None:
        return None
    value = getattr(override, attr)
    if value is None:
        return None
    return int(value)


def _pick_ms(override: StabilizerEventOverride | None, attr: str, fallback_s: float) -> float:
    if override is None:
        return max(0.0, fallback_s)
    value = getattr(override, attr)
    if value is None:
        return max(0.0, fallback_s)
    return max(0.0, float(value) / 1000.0)
