from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NodeResult:
    node_name: str
    status: str
    details: str = ""


def run_node(node_name: str, behavior_id: str, degraded: bool = False) -> NodeResult:
    """Execute a minimal behavior-tree node with deterministic placeholder semantics."""
    if node_name == "state_idle":
        return NodeResult(node_name=node_name, status="success", details="idle")

    if node_name == "state_greet":
        return NodeResult(node_name=node_name, status="success", details="greet")

    if node_name == "state_attention":
        return NodeResult(node_name=node_name, status="success", details="attention")

    if node_name == "state_alert":
        return NodeResult(node_name=node_name, status="success", details="alert")

    if node_name == "state_observe":
        return NodeResult(node_name=node_name, status="success", details="observe")

    if node_name == "state_recover":
        return NodeResult(node_name=node_name, status="success", details="recover")

    if node_name == "guard_scene_validity":
        return NodeResult(node_name=node_name, status="success")

    if node_name == "act_nonverbal":
        detail = "degraded_nonverbal" if degraded else "full_nonverbal"
        return NodeResult(node_name=node_name, status="success", details=detail)

    if node_name == "act_speech_optional":
        detail = "speech_suppressed" if degraded else "speech_allowed"
        return NodeResult(node_name=node_name, status="success", details=detail)

    if node_name in {"monitor_preemption", "release"}:
        return NodeResult(node_name=node_name, status="success")

    return NodeResult(node_name=node_name, status="success", details=f"unknown_node:{behavior_id}")
