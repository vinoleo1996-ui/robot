from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class RuntimeConfig(BaseModel):
    project_root: str
    log_level: str = "INFO"
    trace_enabled: bool = True
    mock_drivers: bool = True
    enabled_pipelines: list[str] = Field(default_factory=list)
    fast_path_budget_ms: float = 35.0
    fast_path_pending_limit: int = 64
    max_scenes_per_cycle: int = 4
    async_perception_enabled: bool = False
    async_perception_queue_limit: int = 4
    async_perception_result_max_age_ms: float = 140.0
    async_perception_result_max_frame_lag: int = 3
    async_executor_enabled: bool = False
    async_executor_queue_limit: int = 64
    async_capture_enabled: bool = False
    async_capture_queue_limit: int = 2
    behavior_tick_enabled: bool = False
    behavior_tick_max_nodes: int = 0


class ArbitrationPriorityPolicy(BaseModel):
    interrupt: str = "queue"
    queue_timeout_ms: int = 5_000


class SceneBehaviorConfig(BaseModel):
    target_behavior: str
    priority: str
    required_resources: list[str] = Field(default_factory=list)
    optional_resources: list[str] = Field(default_factory=list)
    degraded_behavior: str | None = None
    resume_previous: bool = True
    hard_interrupt: bool = False


class ArbitrationConfig(BaseModel):
    event_priorities: dict[str, str] = Field(default_factory=dict)
    priorities: dict[str, ArbitrationPriorityPolicy] = Field(default_factory=dict)
    scene_behaviors: dict[str, SceneBehaviorConfig] = Field(default_factory=dict)
    queue: dict[str, int] = Field(default_factory=dict)
    behavior_cooldowns: dict[str, int] = Field(default_factory=dict)


class BehaviorResourcesConfig(BaseModel):
    required_default: list[str] = Field(default_factory=list)
    optional_default: list[str] = Field(default_factory=list)
    available: list[str] = Field(default_factory=list)


class BehaviorConfig(BaseModel):
    default_nonverbal_probability: float = 0.3
    resources: BehaviorResourcesConfig = Field(default_factory=BehaviorResourcesConfig)
    silent_mode: dict[str, bool] = Field(default_factory=dict)


class StabilizerEventOverride(BaseModel):
    cooldown_ms: int | None = None
    debounce_count: int | None = None
    debounce_window_ms: int | None = None
    hysteresis_threshold: float | None = None
    dedup_window_ms: int | None = None
    ttl_ms: int | None = None


class StabilizerConfig(BaseModel):
    debounce_count: int = 2
    debounce_window_ms: int = 300
    cooldown_ms: int = 1_000
    hysteresis_threshold: float = 0.7
    hysteresis_transition_high: float = 0.85
    hysteresis_transition_low: float = 0.6
    dedup_window_ms: int = 500
    default_ttl_ms: int = 3_000
    event_overrides: dict[str, StabilizerEventOverride] = Field(default_factory=dict)


class SlowSceneConfig(BaseModel):
    enabled: bool = True
    queue_size: int = 8
    request_timeout_ms: int = 5_000
    max_pending_per_target: int = 1
    dedup_time_bucket_s: float = 2.0
    trigger_min_score: float = 0.8
    use_qwen: bool = True
    model_path: str = "Qwen/Qwen2-VL-7B-Instruct"
    adapter_config: dict[str, Any] = Field(default_factory=dict)


class SafetyConfig(BaseModel):
    enabled: bool = True
    dangerous_behavior_allowlist: list[str] = Field(default_factory=list)
    dangerous_behavior_tokens: list[str] = Field(default_factory=list)
    emergency_behavior_tokens: list[str] = Field(default_factory=list)
    emergency_reason_tokens: list[str] = Field(default_factory=list)
    behavior_mutex: dict[str, list[str]] = Field(default_factory=dict)


class AppConfig(BaseModel):
    runtime: RuntimeConfig


def _project_root_from_config_path(path: Path) -> Path:
    resolved = path.resolve()
    for parent in resolved.parents:
        if parent.name == "configs":
            return parent.parent
    return resolved.parent


def _looks_like_local_path(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if stripped.startswith(("/", ".", "~")):
        return True
    if stripped.startswith(
        (
            "configs/",
            "data/",
            "logs/",
            "models/",
            "runtime/",
            "scripts/",
            "src/",
            "tests/",
            "tools/",
        )
    ):
        return True
    return bool(Path(stripped).suffix)


def _resolve_path_value(value: str, *, config_path: Path) -> str:
    expanded = os.path.expandvars(os.path.expanduser(value.strip()))
    candidate = Path(expanded)
    if candidate.is_absolute():
        return str(candidate)
    return str((_project_root_from_config_path(config_path) / candidate).resolve())


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping config in {path}")
    return data


def load_app_config(path: Path) -> AppConfig:
    path = Path(path)
    payload = load_yaml(path)
    runtime = payload.get("runtime", {})
    if isinstance(runtime, dict):
        runtime_payload = dict(runtime)
        project_root = runtime_payload.get("project_root")
        if isinstance(project_root, str) and project_root.strip():
            runtime_payload["project_root"] = _resolve_path_value(project_root, config_path=path)
        payload = dict(payload)
        payload["runtime"] = runtime_payload
    return AppConfig.model_validate(payload)


def load_arbitration_config(path: Path) -> ArbitrationConfig:
    payload = load_yaml(path)
    return ArbitrationConfig.model_validate(payload.get("arbitration", {}))


def load_behavior_config(path: Path) -> BehaviorConfig:
    payload = load_yaml(path)
    resources = payload.get("resources")
    if isinstance(resources, list):
        payload = dict(payload)
        payload["resources"] = {"available": resources}
    return BehaviorConfig.model_validate(payload)


def load_slow_scene_config(path: Path) -> SlowSceneConfig:
    path = Path(path)
    payload = load_yaml(path)
    slow_scene_payload = payload.get("slow_scene", payload)
    if isinstance(slow_scene_payload, dict):
        slow_scene_payload = dict(slow_scene_payload)
        model_path = slow_scene_payload.get("model_path")
        if isinstance(model_path, str) and _looks_like_local_path(model_path):
            slow_scene_payload["model_path"] = _resolve_path_value(model_path, config_path=path)
    return SlowSceneConfig.model_validate(slow_scene_payload)


def load_safety_config(path: Path) -> SafetyConfig:
    payload = load_yaml(path)
    safety_payload = payload.get("safety", payload)
    return SafetyConfig.model_validate(safety_payload)


def load_stabilizer_config(path: Path) -> StabilizerConfig:
    payload = load_yaml(path)
    return StabilizerConfig.model_validate(payload.get("stabilizer", {}))
