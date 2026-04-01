from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from statistics import fmean
from time import monotonic
from typing import Any, Protocol, runtime_checkable


logger = logging.getLogger(__name__)


@dataclass
class StageTrace:
    """Trace record for a single runtime stage."""

    trace_id: str
    stage: str
    status: str = "ok"
    started_at: float = field(default_factory=monotonic)
    ended_at: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return max(0.0, (self.ended_at - self.started_at) * 1000.0)


@dataclass
class StageAggregate:
    """Compact aggregate view for one stage."""

    stage: str
    count: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    avg_duration_ms: float | None = None
    max_duration_ms: float | None = None
    min_duration_ms: float | None = None
    last_payload: dict[str, Any] = field(default_factory=dict)
    last_trace_id: str | None = None


@runtime_checkable
class TelemetrySink(Protocol):
    """Interface for telemetry sinks used by live runtime."""

    def emit(self, trace: StageTrace) -> None:
        """Record a trace event."""
        ...


class NullTelemetrySink:
    """No-op telemetry sink for tests and early integration."""

    def emit(self, trace: StageTrace) -> None:  # noqa: D401 - protocol-style method
        return None


class MultiTelemetrySink:
    """Fan-out sink that emits traces to multiple sinks."""

    def __init__(self, *sinks: TelemetrySink | None) -> None:
        self._sinks = [sink for sink in sinks if sink is not None]

    def emit(self, trace: StageTrace) -> None:
        for sink in self._sinks:
            sink.emit(trace)

    def snapshot(self) -> dict[str, Any]:
        snapshots: list[dict[str, Any]] = []
        for sink in self._sinks:
            snapshots.extend(_collect_snapshots(sink))
        return {"sinks": snapshots}


class InMemoryTelemetrySink:
    """Telemetry sink that stores traces in memory for analysis and validation."""

    def __init__(self, *, max_traces: int = 2048) -> None:
        self.traces: deque[StageTrace] = deque(maxlen=max(1, int(max_traces)))
        self._total_traces = 0

    def emit(self, trace: StageTrace) -> None:
        self.traces.append(trace)
        self._total_traces += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "kind": "in_memory",
            "trace_count": self._total_traces,
            "buffered_trace_count": len(self.traces),
            "stages": sorted({trace.stage for trace in self.traces}),
        }


class AggregatingTelemetrySink:
    """In-process observability sink for runtime counters and latency aggregates."""

    def __init__(self, *, max_traces: int = 2048, max_stage_samples: int = 512) -> None:
        self._traces: deque[StageTrace] = deque(maxlen=max(1, int(max_traces)))
        self._total_traces = 0
        self._stage_counts: dict[str, int] = defaultdict(int)
        self._status_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._durations: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=max(1, int(max_stage_samples))))
        self._last_payload: dict[str, dict[str, Any]] = {}
        self._last_trace_id: dict[str, str] = {}

    def emit(self, trace: StageTrace) -> None:
        self._traces.append(trace)
        self._total_traces += 1
        self._stage_counts[trace.stage] += 1
        self._status_counts[trace.stage][trace.status] += 1
        if trace.duration_ms is not None:
            self._durations[trace.stage].append(float(trace.duration_ms))
        self._last_payload[trace.stage] = dict(trace.payload)
        self._last_trace_id[trace.stage] = trace.trace_id

    def reset(self) -> None:
        self._traces.clear()
        self._stage_counts.clear()
        self._status_counts.clear()
        self._durations.clear()
        self._last_payload.clear()
        self._last_trace_id.clear()

    def snapshot(self) -> dict[str, Any]:
        aggregates: dict[str, Any] = {}
        for stage, count in sorted(self._stage_counts.items()):
            durations = self._durations.get(stage, [])
            aggregates[stage] = {
                "count": count,
                "statuses": dict(self._status_counts.get(stage, {})),
                "avg_duration_ms": round(fmean(durations), 3) if durations else None,
                "max_duration_ms": round(max(durations), 3) if durations else None,
                "min_duration_ms": round(min(durations), 3) if durations else None,
                "last_trace_id": self._last_trace_id.get(stage),
                "last_payload": dict(self._last_payload.get(stage, {})),
            }
        return {
            "kind": "aggregating",
            "trace_count": self._total_traces,
            "buffered_trace_count": len(self._traces),
            "stages": aggregates,
        }


class LoggingTelemetrySink:
    """Simple structured logging sink."""

    def __init__(
        self,
        logger_obj: logging.Logger | None = None,
        *,
        level: int = logging.DEBUG,
    ) -> None:
        self._logger = logger_obj or logger
        self._level = int(level)

    def emit(self, trace: StageTrace) -> None:
        if not self._logger.isEnabledFor(self._level):
            return
        self._logger.log(
            self._level,
            "stage=%s trace_id=%s status=%s duration_ms=%s payload=%s",
            trace.stage,
            trace.trace_id,
            trace.status,
            f"{trace.duration_ms:.2f}" if trace.duration_ms is not None else "n/a",
            trace.payload,
        )


def build_stage_trace(
    trace_id: str,
    stage: str,
    *,
    status: str = "ok",
    payload: dict[str, Any] | None = None,
    started_at: float | None = None,
    ended_at: float | None = None,
) -> StageTrace:
    """Create a stage trace with sensible defaults."""
    return StageTrace(
        trace_id=trace_id,
        stage=stage,
        status=status,
        started_at=started_at if started_at is not None else monotonic(),
        ended_at=ended_at,
        payload=payload or {},
    )


def emit_stage_trace(
    sink: TelemetrySink | None,
    trace_id: str,
    stage: str,
    *,
    status: str = "ok",
    payload: dict[str, Any] | None = None,
    started_at: float | None = None,
    ended_at: float | None = None,
) -> StageTrace:
    """Build and emit a stage trace if a sink is provided."""
    trace = build_stage_trace(
        trace_id,
        stage,
        status=status,
        payload=payload,
        started_at=started_at,
        ended_at=ended_at,
    )
    if sink is not None:
        sink.emit(trace)
    return trace


def telemetry_snapshot(sink: TelemetrySink | None) -> dict[str, Any]:
    """Return a best-effort snapshot for one sink or sink tree."""
    if sink is None:
        return {}
    snapshots = _collect_snapshots(sink)
    if not snapshots:
        return {}
    if len(snapshots) == 1:
        return snapshots[0]
    return {"sinks": snapshots}


def _collect_snapshots(sink: Any) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    snapshot_fn = getattr(sink, "snapshot", None)
    if callable(snapshot_fn):
        try:
            snapshot = snapshot_fn()
        except Exception:  # pragma: no cover - defensive observability path
            snapshot = {"kind": sink.__class__.__name__, "snapshot_error": True}
        if isinstance(snapshot, dict):
            snapshots.append(snapshot)
    sinks = getattr(sink, "_sinks", None)
    if isinstance(sinks, list):
        for child in sinks:
            snapshots.extend(_collect_snapshots(child))
    return snapshots
