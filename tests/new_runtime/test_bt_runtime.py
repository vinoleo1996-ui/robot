from __future__ import annotations

from robot_life.behavior.behavior_registry import BehaviorTemplate
from robot_life.behavior.bt_runtime import BehaviorRuntime
from robot_life.common.schemas import DecisionMode


def test_behavior_runtime_selector_falls_back_after_failure(monkeypatch) -> None:
    def fake_run_node(*, node_name: str, behavior_id: str, degraded: bool = False):
        status = "failure" if node_name == "guard_bad" else "success"
        return type("NodeResult", (), {"node_name": node_name, "status": status, "details": node_name})()

    monkeypatch.setattr("robot_life.behavior.bt_runtime.run_node", fake_run_node)
    runtime = BehaviorRuntime()
    template = BehaviorTemplate(
        behavior_id="selector_behavior",
        nodes=["guard_bad", "fallback_ok"],
        tree={
            "type": "selector",
            "children": [
                {"type": "action", "name": "guard_bad"},
                {"type": "action", "name": "fallback_ok"},
            ],
        },
    )

    execution = runtime.run_to_completion(
        trace_id="trace-1",
        template=template,
        grant_id="grant-1",
        degraded=False,
        mode=DecisionMode.EXECUTE,
    )
    assert execution.status == "finished"


def test_behavior_runtime_parallel_completes_incrementally() -> None:
    runtime = BehaviorRuntime()
    template = BehaviorTemplate(
        behavior_id="parallel_behavior",
        nodes=["act_nonverbal", "monitor_preemption"],
        tree={
            "type": "parallel",
            "success_threshold": 2,
            "children": [
                {"type": "action", "name": "act_nonverbal"},
                {"type": "action", "name": "monitor_preemption"},
            ],
        },
    )
    runtime.start(
        trace_id="trace-2",
        template=template,
        grant_id="grant-2",
        degraded=False,
        mode=DecisionMode.EXECUTE,
    )

    first = runtime.tick(max_nodes=1)
    assert first is None
    assert runtime.active_behavior() is not None

    second = runtime.tick(max_nodes=1)
    assert second is not None
    assert second.status == "finished"
