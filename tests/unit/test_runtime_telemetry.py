from robot_life.runtime.telemetry import NullTelemetrySink, emit_stage_trace


def test_emit_stage_trace_computes_duration() -> None:
    trace = emit_stage_trace(
        sink=NullTelemetrySink(),
        trace_id="trace_1",
        stage="event_builder",
        started_at=10.0,
        ended_at=10.05,
    )
    assert trace.duration_ms is not None
    assert 49.0 <= trace.duration_ms <= 51.0
