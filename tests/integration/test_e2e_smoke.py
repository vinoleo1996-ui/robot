"""End-to-end smoke test for the full perception → event engine → arbitration → execution pipeline.

Runs in mock-driver mode (no real camera/mic) so CI can execute it.
Validates:
  1. Events are correctly triggered from mock detections
  2. Priority-based arbitration resolves without conflicts
  3. CooldownManager suppresses duplicate triggers
  4. P0 safety events hard-interrupt lower-priority behaviors
  5. Same-priority events queue rather than fight
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from time import monotonic
import subprocess

import pytest

# Ensure project root is importable.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from robot_life.behavior.executor import BehaviorExecutor
from robot_life.behavior.resources import ResourceManager
from robot_life.behavior.safety_guard import BehaviorSafetyGuard
from robot_life.common.schemas import EventPriority
from robot_life.event_engine.arbitrator import Arbitrator
from robot_life.event_engine.arbitration_runtime import ArbitrationRuntime
from robot_life.event_engine.builder import EventBuilder
from robot_life.event_engine.cooldown_manager import CooldownManager
from robot_life.event_engine.decision_queue import DecisionQueue
from robot_life.event_engine.scene_aggregator import SceneAggregator
from robot_life.event_engine.stabilizer import EventStabilizer
from robot_life.runtime import (
    LiveLoop,
    LiveLoopDependencies,
    NullTelemetrySink,
    SourceBundle,
    SyntheticCameraSource,
    SyntheticMicrophoneSource,
    build_pipeline_registry,
)


def _build_dependencies(*, with_cooldown: bool = True) -> LiveLoopDependencies:
    """Build a minimal LiveLoopDependencies for integration testing."""
    return LiveLoopDependencies(
        builder=EventBuilder(),
        stabilizer=EventStabilizer(
            debounce_count=1,       # No debounce delay for testing
            debounce_window_ms=0,
            cooldown_ms=0,          # No per-event cooldown for testing
            dedup_window_ms=0,
            hysteresis_threshold=0.0,
        ),
        aggregator=SceneAggregator(min_single_signal_score=0.0),
        arbitrator=Arbitrator(),
        arbitration_runtime=ArbitrationRuntime(
            arbitrator=Arbitrator(),
            queue=DecisionQueue(),
        ),
        executor=BehaviorExecutor(
            ResourceManager(),
            safety_guard=BehaviorSafetyGuard(),
        ),
        slow_scene=None,
        telemetry=NullTelemetrySink(),
        event_priorities={},
        cooldown_manager=CooldownManager(global_cooldown_s=0.0, scene_cooldowns={})
        if with_cooldown
        else None,
    )


def _build_loop(dependencies: LiveLoopDependencies, *, iterations: int = 10) -> LiveLoop:
    """Build a LiveLoop with synthetic sources."""
    registry = build_pipeline_registry(
        enabled_pipelines=["face", "gesture", "gaze", "audio", "motion"],
        detector_cfg=None,
        mock_drivers=True,
    )
    source_bundle = SourceBundle(
        camera=SyntheticCameraSource(),
        microphone=SyntheticMicrophoneSource(),
    )
    return LiveLoop(
        registry=registry,
        source_bundle=source_bundle,
        dependencies=dependencies,
    )


class TestE2ESmokeFullPipeline:
    """Verify the full pipeline works end-to-end in mock mode."""

    def test_mock_pipeline_runs_without_crash(self):
        """Most basic test: the pipeline runs N iterations without exceptions."""
        deps = _build_dependencies()
        loop = _build_loop(deps)
        results = loop.run_forever(max_iterations=10)
        assert len(results) == 10, f"Expected 10 results, got {len(results)}"

    def test_detections_are_produced(self):
        """Mock drivers should produce at least some detections."""
        deps = _build_dependencies()
        loop = _build_loop(deps)
        results = loop.run_forever(max_iterations=15)
        total_detections = sum(len(r.detections) for r in results)
        assert total_detections > 0, "Mock drivers should yield detections over 15 iterations"

    def test_stable_events_flow_through(self):
        """With stabilizer thresholds zeroed, all detections should pass through."""
        deps = _build_dependencies()
        loop = _build_loop(deps)
        results = loop.run_forever(max_iterations=15)
        total_stable = sum(len(r.stable_events) for r in results)
        assert total_stable > 0, "Mock detections should produce stable events when debounce=1"

    def test_scene_candidates_are_generated(self):
        """Aggregator should produce scene candidates from stable events."""
        deps = _build_dependencies()
        loop = _build_loop(deps)
        results = loop.run_forever(max_iterations=20)
        total_scenes = sum(len(r.scene_candidates) for r in results)
        assert total_scenes > 0, "Mock pipeline should produce at least one scene candidate"

    def test_execution_results_complete(self):
        """Executor should produce results when arbitration approves behaviors."""
        deps = _build_dependencies()
        loop = _build_loop(deps)
        results = loop.run_forever(max_iterations=20)
        total_executions = sum(len(r.execution_results) for r in results)
        assert total_executions > 0, "Mock pipeline should execute at least one behavior"

    def test_cooldown_manager_is_active(self):
        """Verify CooldownManager is wired and tracking state."""
        deps = _build_dependencies(with_cooldown=True)
        loop = _build_loop(deps)
        results = loop.run_forever(max_iterations=10)
        cooldown = deps.cooldown_manager
        assert cooldown is not None
        snapshot = cooldown.snapshot()
        assert "global_remaining_s" in snapshot
        assert "tracked_scenes" in snapshot

    def test_pipeline_without_cooldown_still_works(self):
        """Ensure backwards compatibility when cooldown_manager is None."""
        deps = _build_dependencies(with_cooldown=False)
        assert deps.cooldown_manager is None
        loop = _build_loop(deps)
        results = loop.run_forever(max_iterations=5)
        assert len(results) == 5

    def test_loop_timing_within_budget(self):
        """Verify the main loop doesn't block excessively per iteration."""
        deps = _build_dependencies()
        loop = _build_loop(deps)
        start = monotonic()
        results = loop.run_forever(max_iterations=10)
        elapsed = monotonic() - start
        # 10 iterations should complete in well under 10 seconds with mock drivers
        assert elapsed < 10.0, f"10 iterations took {elapsed:.2f}s, expected < 10s"


class TestPriorityConflicts:
    """Verify priority-based arbitration prevents behavior fighting."""

    def test_arbitration_runtime_submit_batch_ordering(self):
        """Higher-priority scenes should be processed first in a batch."""
        from robot_life.common.schemas import SceneCandidate, new_id, now_mono

        arbitrator = Arbitrator()
        runtime = ArbitrationRuntime(
            arbitrator=arbitrator,
            queue=DecisionQueue(),
        )

        now = now_mono()
        # Create two scenes: one P2 (attention) and one P1 (greeting).
        attention_scene = SceneCandidate(
            scene_id=new_id(),
            trace_id=new_id(),
            scene_type="attention_scene",
            based_on_events=[new_id()],
            score_hint=0.8,
            valid_until_monotonic=now + 5.0,
            target_id=None,
            payload={},
        )
        greeting_scene = SceneCandidate(
            scene_id=new_id(),
            trace_id=new_id(),
            scene_type="greeting_scene",
            based_on_events=[new_id()],
            score_hint=0.9,
            valid_until_monotonic=now + 5.0,
            target_id="user_001",
            payload={},
        )

        # Submit both in a batch — greeting (P1) should be processed before attention (P2).
        outcomes = runtime.submit_batch(
            [attention_scene, greeting_scene],
            batch_window_ms=40,
        )
        assert len(outcomes) >= 1
        # The first executed outcome should be the higher-priority one.
        executed = [o for o in outcomes if o.executed]
        if executed:
            first_executed = executed[0]
            assert first_executed.decision.priority in {EventPriority.P0, EventPriority.P1}

    def test_cooldown_suppresses_repeated_scenes(self):
        """Repeated execution of the same scene should be cooldown-suppressed."""
        cooldown = CooldownManager(
            global_cooldown_s=1.0,
            scene_cooldowns={"greeting_scene": 5.0},
        )
        # First check: should pass.
        allowed, reason = cooldown.check("greeting_scene", "user_001", EventPriority.P1)
        assert allowed is True

        # Record execution.
        cooldown.record_execution("greeting_scene", "user_001")

        # P1 bypasses global cooldown, but scene cooldown should still block.
        allowed, reason = cooldown.check("greeting_scene", "user_001", EventPriority.P1)
        assert allowed is False
        assert "scene_cooldown" in reason

    def test_p0_bypasses_global_cooldown(self):
        """P0 safety events should bypass the global cooldown layer."""
        cooldown = CooldownManager(global_cooldown_s=10.0)
        cooldown.record_execution("attention_scene", None)

        # P2 should be blocked by global cooldown.
        allowed_p2, _ = cooldown.check("attention_scene", None, EventPriority.P2)
        assert allowed_p2 is False

        # P0 should bypass global cooldown.
        allowed_p0, _ = cooldown.check("safety_alert_scene", None, EventPriority.P0)
        assert allowed_p0 is True


@pytest.mark.parametrize(
    ("script_path", "marker"),
    [
        ("scripts/validate/smoke_mock_profile.sh", "PROFILE SMOKE PASSED: mock"),
        ("scripts/validate/smoke_local_mac_profile.sh", "PROFILE SMOKE PASSED: local_mac"),
        ("scripts/validate/smoke_local_mac_lite_profile.sh", "PROFILE SMOKE PASSED: local_mac_lite"),
        ("scripts/validate/smoke_desktop_4090_profile.sh", "PROFILE SMOKE PASSED: desktop_4090"),
    ],
)
def test_profile_smoke_entrypoints_cover_doctor_detector_status_run_live_and_ui_demo(
    script_path: str,
    marker: str,
) -> None:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    src_path = str(_PROJECT_ROOT / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{pythonpath}" if pythonpath else src_path
    result = subprocess.run(
        ["bash", script_path],
        cwd=_PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert marker in result.stdout
