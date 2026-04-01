from __future__ import annotations

from typing import Any


_STATE_TO_INTENT = {
    "IDLE": "idle_scan",
    "NOTICED_HUMAN": "ack_presence",
    "MUTUAL_ATTENTION": "establish_attention",
    "ENGAGING": "maintain_engagement",
    "ONGOING_INTERACTION": "maintain_engagement",
    "RECOVERY": "graceful_disengage",
    "SAFETY_OVERRIDE": "safety_override",
}


def intent_for_state(state_name: str | None) -> str:
    normalized = str(state_name or "IDLE").strip().upper()
    return _STATE_TO_INTENT.get(normalized, "idle_scan")


def intent_from_snapshot(snapshot: dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict):
        return "idle_scan"
    existing = snapshot.get("intent")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()
    return intent_for_state(snapshot.get("state"))
