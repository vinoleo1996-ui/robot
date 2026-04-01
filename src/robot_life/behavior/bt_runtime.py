from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any

from robot_life.behavior.behavior_registry import BehaviorTemplate
from robot_life.behavior.bt_nodes import NodeResult, run_node
from robot_life.common.schemas import DecisionMode, ExecutionResult, new_id

_SUCCESS = "success"
_FAILURE = "failure"
_RUNNING = "running"


@dataclass
class ActiveBehavior:
    execution_id: str
    trace_id: str
    behavior_id: str
    grant_id: str
    started_at: float
    degraded: bool
    resumable: bool
    mode: DecisionMode
    nodes: list[str]
    tree: "TreeNode"
    next_node_index: int = 0
    completed_nodes: list[NodeResult] = field(default_factory=list)
    status: str = "running"
    node_state: dict[str, Any] = field(default_factory=dict)


@dataclass
class BehaviorTickContext:
    active: ActiveBehavior
    remaining_budget: int

    def consume(self) -> bool:
        if self.remaining_budget <= 0:
            return False
        self.remaining_budget -= 1
        return True


@dataclass(frozen=True)
class TreeNode:
    node_id: str
    kind: str

    def tick(self, context: BehaviorTickContext) -> str:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass(frozen=True)
class ActionNode(TreeNode):
    name: str

    def tick(self, context: BehaviorTickContext) -> str:
        if not context.consume():
            return _RUNNING
        node_result = run_node(
            node_name=self.name,
            behavior_id=context.active.behavior_id,
            degraded=context.active.degraded,
        )
        context.active.completed_nodes.append(node_result)
        normalized = str(node_result.status or _SUCCESS).lower()
        if normalized not in {_SUCCESS, _FAILURE, _RUNNING}:
            normalized = _SUCCESS
        return normalized


@dataclass(frozen=True)
class SequenceNode(TreeNode):
    children: tuple[TreeNode, ...]

    def tick(self, context: BehaviorTickContext) -> str:
        index = int(context.active.node_state.get(self.node_id, 0))
        while index < len(self.children):
            child_status = self.children[index].tick(context)
            if child_status == _SUCCESS:
                index += 1
                context.active.node_state[self.node_id] = index
                continue
            if child_status == _FAILURE:
                context.active.node_state[self.node_id] = 0
                return _FAILURE
            context.active.node_state[self.node_id] = index
            return _RUNNING
        context.active.node_state[self.node_id] = 0
        return _SUCCESS


@dataclass(frozen=True)
class SelectorNode(TreeNode):
    children: tuple[TreeNode, ...]

    def tick(self, context: BehaviorTickContext) -> str:
        index = int(context.active.node_state.get(self.node_id, 0))
        while index < len(self.children):
            child_status = self.children[index].tick(context)
            if child_status == _SUCCESS:
                context.active.node_state[self.node_id] = 0
                return _SUCCESS
            if child_status == _FAILURE:
                index += 1
                context.active.node_state[self.node_id] = index
                continue
            context.active.node_state[self.node_id] = index
            return _RUNNING
        context.active.node_state[self.node_id] = 0
        return _FAILURE


@dataclass(frozen=True)
class ParallelNode(TreeNode):
    children: tuple[TreeNode, ...]
    success_threshold: int
    failure_threshold: int

    def tick(self, context: BehaviorTickContext) -> str:
        state = context.active.node_state.setdefault(
            self.node_id,
            {"statuses": [_RUNNING for _ in self.children]},
        )
        statuses = list(state["statuses"])
        for index, child in enumerate(self.children):
            if statuses[index] in {_SUCCESS, _FAILURE}:
                continue
            statuses[index] = child.tick(context)
            if context.remaining_budget <= 0 and statuses[index] == _RUNNING:
                break
        state["statuses"] = statuses
        successes = sum(1 for status in statuses if status == _SUCCESS)
        failures = sum(1 for status in statuses if status == _FAILURE)
        if successes >= self.success_threshold:
            state["statuses"] = [_RUNNING for _ in self.children]
            return _SUCCESS
        if failures >= self.failure_threshold:
            state["statuses"] = [_RUNNING for _ in self.children]
            return _FAILURE
        return _RUNNING


class BehaviorRuntime:
    """Behavior-tree runtime with sequence/selector/parallel support."""

    def __init__(self):
        self._active: ActiveBehavior | None = None

    def start(
        self,
        trace_id: str,
        template: BehaviorTemplate,
        grant_id: str,
        degraded: bool,
        mode: DecisionMode,
        started_at: float | None = None,
    ) -> ActiveBehavior:
        active = ActiveBehavior(
            execution_id=new_id(),
            trace_id=trace_id,
            behavior_id=template.behavior_id,
            grant_id=grant_id,
            started_at=started_at if started_at is not None else time(),
            degraded=degraded,
            resumable=template.resumable,
            mode=mode,
            nodes=list(template.nodes),
            tree=self._compile_tree(template),
        )
        self._active = active
        return active

    def tick(self, max_nodes: int = 1) -> ExecutionResult | None:
        active = self._active
        if active is None:
            return None

        context = BehaviorTickContext(active=active, remaining_budget=max(1, int(max_nodes)))
        status = active.tree.tick(context)
        if status == _FAILURE:
            active.status = "failed"
            return self._finish_active()
        if status == _SUCCESS:
            active.status = "finished"
            return self._finish_active()
        active.status = "running"
        return None

    def run_to_completion(
        self,
        trace_id: str,
        template: BehaviorTemplate,
        grant_id: str,
        degraded: bool,
        mode: DecisionMode,
        started_at: float | None = None,
    ) -> ExecutionResult:
        self.start(
            trace_id=trace_id,
            template=template,
            grant_id=grant_id,
            degraded=degraded,
            mode=mode,
            started_at=started_at,
        )
        while True:
            finished = self.tick(max_nodes=max(1, len(template.nodes) + 4))
            if finished is not None:
                return finished

    def _finish_active(self) -> ExecutionResult:
        active = self._active
        if active is None:
            raise RuntimeError("cannot finish inactive behavior")
        finished = ExecutionResult(
            execution_id=active.execution_id,
            trace_id=active.trace_id,
            behavior_id=active.behavior_id,
            status=active.status,
            interrupted=False,
            degraded=active.degraded,
            started_at=active.started_at,
            ended_at=time(),
        )
        self._active = None
        return finished

    def interrupt(self, mode: DecisionMode = DecisionMode.SOFT_INTERRUPT) -> ExecutionResult | None:
        if self._active is None:
            return None

        active = self._active
        active.status = "interrupted"
        self._active = None
        return ExecutionResult(
            execution_id=active.execution_id,
            trace_id=active.trace_id,
            behavior_id=active.behavior_id,
            status="interrupted",
            interrupted=True,
            degraded=active.degraded,
            started_at=active.started_at,
            ended_at=time(),
        )

    def active_behavior(self) -> ActiveBehavior | None:
        return self._active

    def _compile_tree(self, template: BehaviorTemplate) -> TreeNode:
        spec = template.tree
        if spec is None:
            spec = {
                "type": "sequence",
                "children": [{"type": "action", "name": node_name} for node_name in template.nodes],
            }
        return _build_tree(spec)


def _build_tree(spec: dict[str, Any], *, prefix: str = "root") -> TreeNode:
    node_type = str(spec.get("type", "action")).strip().lower()
    if node_type == "action":
        name = str(spec.get("name", prefix))
        return ActionNode(node_id=prefix, kind=node_type, name=name)

    children_spec = tuple(spec.get("children", []) or [])
    children = tuple(_build_tree(child, prefix=f"{prefix}.{index}") for index, child in enumerate(children_spec))
    if node_type == "sequence":
        return SequenceNode(node_id=prefix, kind=node_type, children=children)
    if node_type == "selector":
        return SelectorNode(node_id=prefix, kind=node_type, children=children)
    if node_type == "parallel":
        success_threshold = int(spec.get("success_threshold", len(children) if children else 0))
        failure_threshold = int(spec.get("failure_threshold", 1))
        return ParallelNode(
            node_id=prefix,
            kind=node_type,
            children=children,
            success_threshold=max(0, success_threshold),
            failure_threshold=max(1, failure_threshold),
        )
    raise ValueError(f"unsupported behavior tree node type: {node_type}")
