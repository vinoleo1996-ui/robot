from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import monotonic

from robot_life.common.schemas import ResourceGrant, new_id

# Standard resource names in the system
RESOURCE_NAMES = [
    "AudioOut",
    "HeadMotion",
    "BodyMotion",
    "FaceExpression",
    "AttentionTarget",
    "DialogContext",
]


class ResourceMode(str, Enum):
    """How a resource can be shared between behaviors."""

    EXCLUSIVE = "EXCLUSIVE"
    SHARED = "SHARED"
    DUCKING = "DUCKING"


@dataclass
class ResourceDef:
    """Definition of a resource's properties."""

    name: str
    mode: ResourceMode
    priority_level: int  # Higher = more important


@dataclass
class ResourceOwner:
    grant_id: str
    behavior_id: str
    priority: int
    end_time: float


# Standard resource definitions
RESOURCE_DEFS = {
    "AudioOut": ResourceDef("AudioOut", ResourceMode.EXCLUSIVE, 3),
    "HeadMotion": ResourceDef("HeadMotion", ResourceMode.SHARED, 2),
    "BodyMotion": ResourceDef("BodyMotion", ResourceMode.SHARED, 2),
    "FaceExpression": ResourceDef("FaceExpression", ResourceMode.EXCLUSIVE, 2),
    "AttentionTarget": ResourceDef("AttentionTarget", ResourceMode.SHARED, 1),
    "DialogContext": ResourceDef("DialogContext", ResourceMode.DUCKING, 2),
}


class ResourceManager:
    """
    Manages resource allocation and ownership.

    Enforces exclusive access, sharing, ducking, and degradation rules.
    """

    def __init__(self) -> None:
        # resource_name -> list[ResourceOwner]
        self._owners: dict[str, list[ResourceOwner]] = {}
        self._active_grants: dict[str, ResourceGrant] = {}
        self._stats: dict[str, int] = {
            "grant_requests": 0,
            "grant_granted": 0,
            "grant_denied": 0,
            "preemptions": 0,
        }

    def request_grant(
        self,
        trace_id: str,
        decision_id: str,
        behavior_id: str,
        required_resources: list[str],
        optional_resources: list[str],
        priority: int = 2,
        duration_ms: int = 5000,
    ) -> ResourceGrant:
        now = monotonic()
        end_time = now + (duration_ms / 1000.0)
        self._cleanup_expired(now)
        self._stats["grant_requests"] += 1

        grant_id = new_id()
        granted: list[str] = []
        denied: list[str] = []
        reason_parts: list[str] = []
        preempt_plan: dict[str, list[str]] = {}

        # Phase 1: verify all required resources can be allocated.
        for resource_name in required_resources:
            can_allocate, preempt_grants = self._evaluate_allocation(resource_name, priority, now)
            if not can_allocate:
                denied.append(resource_name)
                reason_parts.append(self._build_conflict_reason(resource_name, now))
                continue
            preempt_plan[resource_name] = preempt_grants

        if denied:
            self._stats["grant_denied"] += 1
            grant = ResourceGrant(
                grant_id=grant_id,
                trace_id=trace_id,
                decision_id=decision_id,
                granted=False,
                granted_resources=[],
                denied_resources=denied,
                reason=f"required_resources_denied: {', '.join(reason_parts)}",
            )
            # NOTE: Denied grants are NOT stored in _active_grants
            # to prevent unbounded memory growth from failed requests.
            return grant

        # Phase 2: allocate required resources.
        for resource_name in required_resources:
            self._allocate(
                resource_name=resource_name,
                owner=ResourceOwner(
                    grant_id=grant_id,
                    behavior_id=behavior_id,
                    priority=priority,
                    end_time=end_time,
                ),
                preempt_grants=preempt_plan.get(resource_name, []),
            )
            granted.append(resource_name)

        # Phase 3: best-effort optional resource allocation.
        for resource_name in optional_resources:
            can_allocate, preempt_grants = self._evaluate_allocation(resource_name, priority, now)
            if not can_allocate:
                continue
            self._allocate(
                resource_name=resource_name,
                owner=ResourceOwner(
                    grant_id=grant_id,
                    behavior_id=behavior_id,
                    priority=priority,
                    end_time=end_time,
                ),
                preempt_grants=preempt_grants,
            )
            granted.append(resource_name)

        grant = ResourceGrant(
            grant_id=grant_id,
            trace_id=trace_id,
            decision_id=decision_id,
            granted=True,
            granted_resources=granted,
            denied_resources=[],
            reason=f"granted_{len(granted)}_resources" if granted else "no_resources_needed",
        )
        self._stats["grant_granted"] += 1
        self._active_grants[grant_id] = grant
        return grant

    def _evaluate_allocation(
        self,
        resource_name: str,
        priority: int,
        now: float,
    ) -> tuple[bool, list[str]]:
        owners = self._owners.get(resource_name, [])
        owners = [owner for owner in owners if owner.end_time > now]
        self._owners[resource_name] = owners

        if not owners:
            return True, []

        resource_def = RESOURCE_DEFS.get(resource_name)
        if resource_def is None:
            return False, []

        if resource_def.mode == ResourceMode.EXCLUSIVE:
            highest_owner_priority = max(owner.priority for owner in owners)
            if priority > highest_owner_priority:
                return True, [owner.grant_id for owner in owners]
            return False, []

        # SHARED/DUCKING are both multi-owner.
        return True, []

    def _allocate(self, resource_name: str, owner: ResourceOwner, preempt_grants: list[str]) -> None:
        if preempt_grants:
            self._stats["preemptions"] += len(preempt_grants)
            for preempt_grant_id in preempt_grants:
                self._remove_grant_from_resource(resource_name, preempt_grant_id)

        owners = self._owners.setdefault(resource_name, [])
        if not any(existing.grant_id == owner.grant_id for existing in owners):
            owners.append(owner)

    def _remove_grant_from_resource(self, resource_name: str, grant_id: str) -> None:
        owners = self._owners.get(resource_name, [])
        if not owners:
            return

        new_owners = [owner for owner in owners if owner.grant_id != grant_id]
        if new_owners:
            self._owners[resource_name] = new_owners
        else:
            self._owners.pop(resource_name, None)

        grant = self._active_grants.get(grant_id)
        if grant is not None:
            grant.granted_resources = [res for res in grant.granted_resources if res != resource_name]

    def _cleanup_expired(self, now: float) -> None:
        for resource_name in list(self._owners.keys()):
            owners = self._owners[resource_name]
            expired_grant_ids = [owner.grant_id for owner in owners if owner.end_time <= now]
            alive = [owner for owner in owners if owner.end_time > now]
            if alive:
                self._owners[resource_name] = alive
            else:
                self._owners.pop(resource_name, None)

            for grant_id in expired_grant_ids:
                grant = self._active_grants.get(grant_id)
                if grant is not None:
                    grant.granted_resources = [
                        resource for resource in grant.granted_resources if resource != resource_name
                    ]

    def _build_conflict_reason(self, resource_name: str, now: float) -> str:
        owners = self._owners.get(resource_name, [])
        active_owners = [owner for owner in owners if owner.end_time > now]
        if not active_owners:
            return f"{resource_name}:conflict"

        labels = ",".join(
            f"{owner.behavior_id}({self._priority_label(owner.priority)})" for owner in active_owners
        )
        return f"{resource_name}:owned_by_{labels}"

    def release_grant(self, grant_id: str) -> None:
        grant = self._active_grants.pop(grant_id, None)
        if grant is None:
            return

        for resource_name in list(self._owners.keys()):
            self._remove_grant_from_resource(resource_name, grant_id)

    def force_release_all(self) -> None:
        """Emergency path: release every active grant immediately."""
        for grant_id in list(self._active_grants.keys()):
            self.release_grant(grant_id)

    def get_resource_status(self) -> dict[str, str]:
        now = monotonic()
        self._cleanup_expired(now)
        status: dict[str, str] = {}

        for resource_name in RESOURCE_DEFS:
            owners = self._owners.get(resource_name, [])
            if not owners:
                status[resource_name] = "free"
                continue

            owner_parts = []
            for owner in sorted(owners, key=lambda item: item.priority, reverse=True):
                ttl_ms = max(0, int((owner.end_time - now) * 1000))
                owner_parts.append(
                    f"{owner.behavior_id}({self._priority_label(owner.priority)},{ttl_ms}ms)"
                )

            mode = RESOURCE_DEFS[resource_name].mode
            prefix = "owned_by" if mode == ResourceMode.EXCLUSIVE else "shared_by"
            status[resource_name] = f"{prefix}_{'|'.join(owner_parts)}"

        return status

    def debug_snapshot(self) -> dict:
        now = monotonic()
        self._cleanup_expired(now)
        owners_view: dict[str, list[dict[str, str | int]]] = {}
        for resource_name in RESOURCE_DEFS:
            owners = self._owners.get(resource_name, [])
            serialized = []
            for owner in sorted(owners, key=lambda item: item.priority, reverse=True):
                serialized.append(
                    {
                        "grant_id": owner.grant_id,
                        "behavior_id": owner.behavior_id,
                        "priority": self._priority_label(owner.priority),
                        "ttl_ms": max(0, int((owner.end_time - now) * 1000)),
                    }
                )
            owners_view[resource_name] = serialized

        return {
            "stats": dict(self._stats),
            "active_grants": len(self._active_grants),
            "status": self.get_resource_status(),
            "owners": owners_view,
        }

    @staticmethod
    def _priority_label(internal_priority: int) -> str:
        if 0 <= internal_priority <= 3:
            return f"P{3 - internal_priority}"
        return f"internal_{internal_priority}"
